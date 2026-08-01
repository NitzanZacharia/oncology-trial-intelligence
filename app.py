"""Streamlit UI for Oncology Trial Match (HLD §1 "app.py", LLD §4). Reads only from
/data/processed via src.storage's read path — zero network calls, zero calls into the
one-time vectorizer-fitting function reserved for the ETL entry point. Run with
`streamlit run app.py` once the processed-data pipeline has populated /data/processed.
"""

from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from src import matching, storage
from src.synonyms import SYNONYM_TABLE

PROCESSED_DIR = Path("data/processed")

_STATUS_ICON = {"pass": "\U0001f7e2", "warn": "\U0001f7e1", "fail": "\U0001f534"}
_CHECK_STATUS_SORT_ORDER = {"fail": 0, "warn": 1, "pass": 2}

_STATUS_MEANING = {
    "fail": "🔴 **Red (FAIL)** means at least one check found an issue affecting more than 20% of records.",
    "warn": "🟡 **Orange (WARN)** means an issue affects some records (up to 20%) but is being handled automatically — safe to use, worth a glance below.",
    "pass": "🟢 **Green (PASS)** means no data-quality issues were found.",
}

_MISSING_PHASES_EXPLANATION = (
    "Here's why: a trial's 'phase' only applies to drug or biologic treatments in "
    "human testing. Trials for surgery, medical devices, or behavioral therapy don't "
    "have a phase at all — that's expected, not an error. This has been checked "
    "across every cancer type in this dataset individually, and it's consistently "
    "high everywhere (not concentrated in one condition), which is what you'd expect "
    "from a real structural property of the data, not a bug. This does not affect "
    "your trial matches — phase is shown when available and omitted when it isn't, "
    "and the ranking doesn't depend on it."
)

# Plain-language, status-agnostic one-liners for each check — purely descriptive of
# what's being checked, not a claim about the current run's result (that's already
# conveyed by the check's own status icon/counts), so these stay accurate across reruns.
_CHECK_PLAIN_LANGUAGE = {
    "nct_id_format": "In plain terms: does every trial's ID look like a real ClinicalTrials.gov ID (the letters 'NCT' followed by 8 digits)?",
    "required_field_missing_nct_id": "In plain terms: does every trial actually have an ID on record?",
    "required_field_missing_brief_title": "In plain terms: does every trial have a title on record?",
    "required_field_missing_overall_status": "In plain terms: is every trial's recruiting status known?",
    "required_field_missing_conditions": "In plain terms: does every trial list at least one condition it treats?",
    "referential_integrity_interventions": "In plain terms: is every listed treatment correctly linked to a real trial, with nothing orphaned?",
    "referential_integrity_locations": "In plain terms: is every listed location correctly linked to a real trial, with nothing orphaned?",
    "enrollment_plausibility": "In plain terms: do the trials' target enrollment numbers look realistic (not zero, not absurdly large)?",
    "phase_enum": "In plain terms: does every trial's phase value match one of ClinicalTrials.gov's official categories?",
    "date_ordering": "In plain terms: are each trial's own dates in a sensible order (e.g. start date before completion date)?",
    "age_parsing": "In plain terms: could each trial's minimum/maximum age requirement be read as an actual number?",
    "missing_rate_sponsor_class": "In plain terms: is sponsor information available for most trials?",
    "missing_rate_phases": "In plain terms: is phase information available for most trials? (See the status explanation above — a real gap here is expected, not a defect.)",
    "missing_rate_enrollment_count": "In plain terms: is target enrollment information available for most trials?",
    "missing_rate_eligibility_criteria": "In plain terms: is eligibility text available for most trials?",
    "missing_rate_sex": "In plain terms: is sex-eligibility information available for most trials?",
}


def _fmt_pct(value: float) -> str:
    return f"{value:.1f}"


@st.cache_data
def load_processed_tables(processed_dir: str, fingerprint: str):
    """Load studies/interventions/locations CSVs; cached on (processed_dir, fingerprint) key."""
    return storage.read_tables(Path(processed_dir))


@st.cache_resource
def load_matching_artifacts(processed_dir: str, fingerprint: str):
    """Load the fitted TfidfVectorizer + sparse matrix via joblib; cached on (processed_dir, fingerprint) key."""
    return storage.read_tfidf_artifacts(Path(processed_dir))


@st.cache_data
def load_quality_report(processed_dir: str, fingerprint: str) -> dict:
    """Load quality_report.json for the in-app quality panel; cached on (processed_dir, fingerprint) key."""
    return storage.read_quality_report(Path(processed_dir))


def _condition_options(studies_df: pd.DataFrame) -> list[str]:
    tokens: set[str] = set()
    for value in studies_df["shortlist_conditions"].dropna():
        for token in str(value).split(";"):
            token = token.strip()
            if token:
                tokens.add(token)
    return sorted(tokens)


def _zero_anchored_bar_chart(counts: pd.Series, category_label: str, value_label: str = "Count") -> alt.Chart:
    """Bar chart with an explicit domainMin=0 y-axis. st.bar_chart's default y-axis
    doesn't reliably anchor at zero across Streamlit/Altair versions, which makes real,
    substantial categories render as barely-visible slivers relative to the largest one —
    force it explicitly rather than relying on the default.
    """
    data = counts.rename(value_label).rename_axis(category_label).reset_index()
    return (
        alt.Chart(data)
        .mark_bar()
        .encode(
            x=alt.X(f"{category_label}:N", sort="-y", title=category_label),
            y=alt.Y(f"{value_label}:Q", scale=alt.Scale(domainMin=0), title=value_label),
        )
    )


def _condition_mask(studies_df: pd.DataFrame, condition: str) -> pd.Series:
    tokens = studies_df["shortlist_conditions"].fillna("").astype(str).str.lower().str.split(";")
    condition_norm = condition.strip().lower()
    return tokens.apply(lambda toks: condition_norm in [t.strip() for t in toks])


def render_patient_match(
    studies_df: pd.DataFrame,
    locations_df: pd.DataFrame,
    vectorizer,
    matrix,
) -> None:
    st.header("Patient Match")
    st.caption(
        "Enter a patient profile to get a ranked, explained shortlist of actively "
        "recruiting trials. Ranking is TF-IDF cosine similarity over each trial's "
        "title, conditions, keywords, and eligibility text — no model, no live "
        "calls, every score reproducible from the data on disk."
    )

    conditions = _condition_options(studies_df)

    with st.form("patient_profile"):
        col1, col2 = st.columns(2)
        with col1:
            condition = st.selectbox("Cancer type", conditions)
            biomarkers_raw = st.text_input(
                "Biomarker tags (comma-separated)", placeholder="e.g. HER2+, EGFR mutation"
            )
            stage = st.text_input(
                "Stage / disease extent (optional)", placeholder="e.g. metastatic, stage IV"
            )
        with col2:
            sex = st.selectbox("Sex", ["Any", "FEMALE", "MALE"])
            age = st.number_input(
                "Age (0 = skip age filter)", min_value=0, max_value=120, value=0, step=1
            )
            top_n = st.slider("Number of matches to show", 5, 50, 20)
        submitted = st.form_submit_button("Find matching trials")

    if not submitted:
        return

    biomarker_tags = [b.strip() for b in biomarkers_raw.split(",") if b.strip()]
    sex_filter = None if sex == "Any" else sex
    age_filter = None if age == 0 else float(age)

    query_text = matching.build_query_text(condition, biomarker_tags, stage or None, SYNONYM_TABLE)
    candidates_df = matching.hard_filter(studies_df, condition, sex_filter, age_filter)

    if candidates_df.empty:
        st.warning(
            "No recruiting trials match the hard filters (condition/sex/age). "
            "Try broadening the profile."
        )
        return

    candidate_indices = candidates_df.index.tolist()
    query_vector = matching.vectorize_query(query_text, vectorizer)
    ranked = matching.rank_candidates(query_vector, candidate_indices, matrix, top_n=top_n)

    if not ranked:
        st.warning("No ranked matches found among the filtered candidates.")
        return

    feature_names = vectorizer.get_feature_names_out().tolist()
    st.subheader(f"{len(ranked)} matching trials for {condition}")

    for row_index, score in ranked:
        trial = studies_df.loc[row_index]
        trial_vector = matrix[row_index]
        matched_terms = matching.explain_match(query_vector, trial_vector, feature_names, top_k=5)
        trial_locations = locations_df[locations_df["nct_id"] == trial["nct_id"]]

        with st.container(border=True):
            st.markdown(
                f"**[{trial['nct_id']}](https://clinicaltrials.gov/study/{trial['nct_id']})** "
                f"— {trial['brief_title']}"
            )
            meta_cols = st.columns(4)
            meta_cols[0].metric(
                "Similarity score",
                f"{score:.3f}",
                help=(
                    "How closely this trial's description matches the patient profile "
                    "you entered, from 0 to 1. Higher means more shared terms "
                    "(condition, biomarkers, stage) — not a medical judgment of fit, "
                    "just a text-similarity score."
                ),
            )
            phase_display = trial["phases"] if pd.notna(trial["phases"]) and trial["phases"] else "—"
            meta_cols[1].write(f"**Phase:** {phase_display}")
            sponsor_name = trial["sponsor_name"] if pd.notna(trial["sponsor_name"]) else "—"
            sponsor_class = trial["sponsor_class"] if pd.notna(trial["sponsor_class"]) else "—"
            meta_cols[2].write(f"**Sponsor:** {sponsor_name} ({sponsor_class})")
            meta_cols[3].write(f"**Locations:** {len(trial_locations)}")

            if matched_terms:
                st.caption("Matched terms: " + ", ".join(matched_terms))
            else:
                st.caption(
                    "No shared keywords, but this trial still passes the basic "
                    "filters (cancer type, and sex/age if specified)."
                )


def render_trial_landscape(studies_df: pd.DataFrame) -> None:
    st.header("Trial Landscape")
    st.caption(
        "Aggregate view of the recruiting-trial pool for a chosen cancer type "
        "— computed entirely from the already-processed local tables, no live calls."
    )

    conditions = _condition_options(studies_df)
    condition = st.selectbox("Cancer type", conditions, key="landscape_condition")

    subset = studies_df[_condition_mask(studies_df, condition)]
    st.caption(f"{len(subset)} studies tagged under '{condition}'")

    col1, col2 = st.columns(2)
    with col1:
        st.subheader(
            "Phase mix",
            help=(
                "Each bar is a testing phase among recruiting trials for this cancer "
                "type. Blank/'Not specified' bars are trials that don't have a phase "
                "at all (common for surgery, device, or behavioral trials) — not "
                "missing data."
            ),
        )
        phase_counts = subset["phases"].fillna("Not specified").replace("", "Not specified").value_counts()
        st.altair_chart(_zero_anchored_bar_chart(phase_counts, "Phase"))
    with col2:
        st.subheader(
            "Sponsor class",
            help=(
                "Who's running each trial — company, government, hospital network, "
                "etc. See the About tab's glossary for what each category means. "
                "Sponsor type isn't a quality signal."
            ),
        )
        sponsor_counts = subset["sponsor_class"].fillna("Unknown").value_counts()
        st.altair_chart(_zero_anchored_bar_chart(sponsor_counts, "Sponsor class"))
        st.caption(
            "\"OTHER\" includes most academic/hospital sponsors — ClinicalTrials.gov's "
            "sponsor-class enum has no separate academic category."
        )

    st.subheader("Recruiting status")
    recruiting_count = int((subset["overall_status"] == "RECRUITING").sum())
    st.metric(
        "Recruiting trials",
        recruiting_count,
        border=True,
        help=(
            "How many trials for this cancer type are open to new participants "
            "right now. This number changes daily as trials open and close."
        ),
    )

    st.subheader("Studies first posted per year")
    years = pd.to_datetime(subset["study_first_post_date"], errors="coerce").dt.year
    year_counts = years.dropna().astype(int).value_counts().sort_index()
    if not year_counts.empty:
        # st.line_chart delegates to Vega-Lite's default quantitative-axis formatting,
        # which renders year labels with thousands-separator commas (e.g. "2,019").
        # An explicit Altair chart with axis format="d" forces plain integer labels.
        year_df = year_counts.reset_index()
        year_df.columns = ["year", "count"]
        year_chart = (
            alt.Chart(year_df)
            .mark_line(point=True)
            .encode(
                x=alt.X("year:Q", axis=alt.Axis(format="d"), title="Year"),
                y=alt.Y("count:Q", scale=alt.Scale(domainMin=0), title="Studies posted"),
            )
        )
        st.altair_chart(year_chart)
        latest_year = int(year_counts.index.max())
        st.caption(
            f"{latest_year} is partial (year-to-date), not a full year — the recent dip "
            "shouldn't be read as a real decline in trial activity."
        )
    else:
        st.caption("No parseable post dates for this condition.")


def render_pipeline_health(quality_report: dict) -> None:
    st.header("Pipeline Health")
    st.caption(
        "Data quality is a visible product feature, not a build-time log line — "
        "every check below ran during the last `python etl.py` run."
    )

    status = quality_report.get("overall_status", "unknown")
    icon = _STATUS_ICON.get(status, "⚪")
    checks = quality_report.get("checks", [])
    driving_checks = [c for c in checks if c["status"] == status] if status != "pass" else []

    badge_col, popover_col = st.columns([5, 1])
    with badge_col:
        st.subheader(f"{icon} Overall status: {status.upper()}")
    with popover_col:
        with st.popover("What does this mean?"):
            st.markdown(f"**Current status: {status.upper()}**")
            if driving_checks:
                for c in driving_checks:
                    plain = _CHECK_PLAIN_LANGUAGE.get(c["name"], c["description"])
                    st.markdown(f"- **{c['name']}**, affecting {_fmt_pct(c['affected_pct'])}% of records: {plain}")
                if any(c["name"] == "missing_rate_phases" for c in driving_checks):
                    st.markdown(_MISSING_PHASES_EXPLANATION)
            st.divider()
            st.markdown(_STATUS_MEANING["fail"])
            st.markdown(_STATUS_MEANING["warn"])
            st.markdown(_STATUS_MEANING["pass"])
            st.caption("See each check below for full detail.")

    st.caption(f"Report generated at: {quality_report.get('generated_at', 'unknown')}")

    row_counts = quality_report.get("row_counts", {})
    if row_counts:
        cols = st.columns(len(row_counts))
        for col, (key, value) in zip(cols, row_counts.items()):
            col.metric(key.replace("_", " ").title(), value)

    st.subheader("Checks")
    sorted_checks = sorted(checks, key=lambda c: _CHECK_STATUS_SORT_ORDER.get(c["status"], 3))
    for check in sorted_checks:
        check_icon = _STATUS_ICON.get(check["status"], "⚪")
        title = (
            f"{check_icon} {check['name']} — {check['status'].upper()} "
            f"({check['affected_count']}/{check['total_count']}, {_fmt_pct(check['affected_pct'])}%)"
        )
        with st.expander(title):
            plain_language = _CHECK_PLAIN_LANGUAGE.get(check["name"])
            if plain_language:
                st.markdown(plain_language)
            st.write(check["description"])
            st.caption(f"Threshold: {check['threshold_note']}")
            if check.get("sample_offending_ids"):
                st.write("Sample offending IDs:", ", ".join(check["sample_offending_ids"][:10]))
            if check.get("per_condition"):
                per_condition_df = pd.DataFrame.from_dict(check["per_condition"], orient="index")
                st.dataframe(per_condition_df)


_GLOSSARY = [
    (
        "NCT ID",
        "Every trial registered on ClinicalTrials.gov has a unique ID starting with "
        "\"NCT\" followed by 8 digits (e.g. `NCT06603597`). Click it to see the "
        "trial's full listing on ClinicalTrials.gov.",
    ),
    (
        "Phase",
        "How far along a drug/biologic trial is in testing. `EARLY_PHASE1` and "
        "`PHASE1` test safety in a small group first; `PHASE2` tests whether it "
        "works; `PHASE3` compares it to standard treatment in a larger group; "
        "`PHASE4` monitors it after approval. Trials for surgery, devices, or "
        "behavioral therapy usually don't have a phase at all — that's normal, not "
        "missing data.",
    ),
    (
        "Recruiting status",
        "Whether a trial is currently open to new participants. \"Recruiting\" "
        "means yes, actively enrolling — this tool only shows those. \"Active, not "
        "recruiting\" means the trial is ongoing but not taking new participants "
        "right now. \"Enrolling by invitation\" means participants are selected "
        "directly from a specific pre-identified group rather than through open "
        "sign-up. \"Completed\" means the trial has finished.",
    ),
    (
        "Sponsor class",
        "Who's running the trial. `INDUSTRY` = a pharmaceutical/biotech company. "
        "`NIH` = the U.S. National Institutes of Health. `NETWORK` = a cooperative "
        "group of hospitals/cancer centers. `OTHER` = academic medical centers, "
        "universities, and hospitals not otherwise categorized (ClinicalTrials.gov's "
        "enum has no separate \"academic\" bucket). None of these categories implies "
        "better or worse trial quality.",
    ),
    (
        "Eligibility criteria",
        "The rules for who can join a trial: cancer type, stage, prior treatments, "
        "age, and other health conditions. This tool reads that text to help rank "
        "and filter matches, but always verify eligibility directly with the trial "
        "team — it's not a substitute for medical guidance.",
    ),
    (
        "Biomarker",
        "A measurable trait of the cancer that can affect which treatments apply, "
        "e.g. `HER2+` (common in some breast cancers) or an `EGFR mutation` (common "
        "in some lung cancers). Entering known biomarkers narrows the match to "
        "trials looking for that same trait.",
    ),
]


def render_about() -> None:
    st.header("About / How to read this")
    st.markdown(
        "This tool helps match cancer patients with clinical trials that might be "
        "right for them. Whether you're a clinical trial navigator, oncologist, or a "
        "patient or family member exploring options, you'll get a ranked shortlist "
        "of trials based on cancer type, stage, and biomarkers, each with a "
        "plain-language note on why it matched. Everything here comes from "
        "ClinicalTrials.gov's public registry — nothing is generated or guessed."
    )

    st.subheader("What each tab does")
    st.markdown(
        "**Patient Match** — Enter a cancer type, and optionally stage and "
        "biomarkers (like \"HER2+\" or \"EGFR mutation\"), and this tab returns "
        "actively recruiting trials ranked by how closely they match. Each result "
        "shows the trial's ID, title, testing phase, sponsor, number of locations, "
        "and exactly which words from your profile matched the trial's description "
        "— so you can see *why* it's on the list, not just that it is."
    )
    st.markdown(
        "**Trial Landscape** — For a chosen cancer type, this tab shows the shape "
        "of the whole recruiting-trial pool: how many trials are in early vs. late "
        "testing, who's running them (companies, universities, government), and how "
        "trial activity has changed over time. Useful for understanding how much "
        "research is happening for a given cancer type, not for finding a specific "
        "trial."
    )
    st.markdown(
        "**Pipeline Health** — A report card for the underlying data itself: how "
        "many trial records were processed, and whether anything looked off "
        "(missing fields, implausible values, broken links between tables). This is "
        "shown openly rather than hidden, because a matching tool is only as "
        "trustworthy as the data behind it."
    )

    st.subheader("Glossary")
    for term, definition in _GLOSSARY:
        st.markdown(f"**{term}** — {definition}")


def main() -> None:
    st.set_page_config(page_title="Oncology Trial Match", layout="wide")

    if not (PROCESSED_DIR / "studies.csv").exists():
        st.error(
            "No processed data found under `data/processed`. Run `python etl.py` first, "
            "per the project's required setup sequence."
        )
        st.stop()

    fingerprint = storage.processed_dir_fingerprint(PROCESSED_DIR)
    studies_df, _interventions_df, locations_df = load_processed_tables(
        str(PROCESSED_DIR), fingerprint
    )
    vectorizer, matrix = load_matching_artifacts(str(PROCESSED_DIR), fingerprint)
    quality_report = load_quality_report(str(PROCESSED_DIR), fingerprint)

    st.title("Oncology Trial Match")
    st.caption("A clinical-trial matching and recommendation tool over ClinicalTrials.gov data.")
    st.caption(
        "New here? The \"About / How to read this\" tab has a plain-language guide "
        "and glossary."
    )

    tab_match, tab_landscape, tab_health, tab_about = st.tabs(
        ["Patient Match", "Trial Landscape", "Pipeline Health", "About / How to read this"]
    )
    with tab_match:
        render_patient_match(studies_df, locations_df, vectorizer, matrix)
    with tab_landscape:
        render_trial_landscape(studies_df)
    with tab_health:
        render_pipeline_health(quality_report)
    with tab_about:
        render_about()


if __name__ == "__main__":
    main()
