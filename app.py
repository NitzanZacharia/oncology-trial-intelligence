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
            meta_cols[0].metric("Similarity score", f"{score:.3f}")
            phase_display = trial["phases"] if pd.notna(trial["phases"]) and trial["phases"] else "—"
            meta_cols[1].write(f"**Phase:** {phase_display}")
            sponsor_name = trial["sponsor_name"] if pd.notna(trial["sponsor_name"]) else "—"
            sponsor_class = trial["sponsor_class"] if pd.notna(trial["sponsor_class"]) else "—"
            meta_cols[2].write(f"**Sponsor:** {sponsor_name} ({sponsor_class})")
            meta_cols[3].write(f"**Locations:** {len(trial_locations)}")

            if matched_terms:
                st.caption("Matched terms: " + ", ".join(matched_terms))
            else:
                st.caption("No overlapping TF-IDF terms — ranked by hard filter only.")


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
        st.subheader("Phase mix")
        phase_counts = subset["phases"].fillna("Not specified").replace("", "Not specified").value_counts()
        st.altair_chart(_zero_anchored_bar_chart(phase_counts, "Phase"))
    with col2:
        st.subheader("Sponsor class")
        sponsor_counts = subset["sponsor_class"].fillna("Unknown").value_counts()
        st.altair_chart(_zero_anchored_bar_chart(sponsor_counts, "Sponsor class"))
        st.caption(
            "\"OTHER\" includes most academic/hospital sponsors — ClinicalTrials.gov's "
            "sponsor-class enum has no separate academic category."
        )

    st.subheader("Recruiting status")
    recruiting_count = int((subset["overall_status"] == "RECRUITING").sum())
    st.metric("Recruiting trials", recruiting_count, border=True)

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
    st.subheader(f"{icon} Overall status: {status.upper()}")
    st.caption(f"Report generated at: {quality_report.get('generated_at', 'unknown')}")

    row_counts = quality_report.get("row_counts", {})
    if row_counts:
        cols = st.columns(len(row_counts))
        for col, (key, value) in zip(cols, row_counts.items()):
            col.metric(key.replace("_", " ").title(), value)

    st.subheader("Checks")
    for check in quality_report.get("checks", []):
        check_icon = _STATUS_ICON.get(check["status"], "⚪")
        title = (
            f"{check_icon} {check['name']} — {check['status'].upper()} "
            f"({check['affected_count']}/{check['total_count']}, {check['affected_pct']}%)"
        )
        with st.expander(title):
            st.write(check["description"])
            st.caption(f"Threshold: {check['threshold_note']}")
            if check.get("sample_offending_ids"):
                st.write("Sample offending IDs:", ", ".join(check["sample_offending_ids"][:10]))
            if check.get("per_condition"):
                per_condition_df = pd.DataFrame.from_dict(check["per_condition"], orient="index")
                st.dataframe(per_condition_df)


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

    tab_match, tab_landscape, tab_health = st.tabs(
        ["Patient Match", "Trial Landscape", "Pipeline Health"]
    )
    with tab_match:
        render_patient_match(studies_df, locations_df, vectorizer, matrix)
    with tab_landscape:
        render_trial_landscape(studies_df)
    with tab_health:
        render_pipeline_health(quality_report)


if __name__ == "__main__":
    main()
