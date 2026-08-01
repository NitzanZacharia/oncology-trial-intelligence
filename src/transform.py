"""Flatten raw ClinicalTrials.gov JSON into the three flat tables + composite text,
owned by `etl.py` (HLD §2 "Transform", LLD §3.3).

Pure/local logic only — no network I/O, no `requests` import. Consumes the raw
`{condition: [raw studies]}` dict produced by `src.extract.extract_all` and produces
(studies_df, interventions_df, locations_df) pre-validation, per LLD §1.
"""

import re

import pandas as pd

from src.extract import CANCER_TYPE_SHORTLIST
from src.storage import _cast_child_dtypes, _cast_studies_dtypes
from src.synonyms import expand_text

_AGE_RE = re.compile(
    r"^(\d+(?:\.\d+)?)\s*(Year|Years|Month|Months|Week|Weeks|Day|Days)$",
    re.IGNORECASE,
)

_AGE_UNIT_DIVISORS = {
    "year": 1.0,
    "years": 1.0,
    "month": 12.0,
    "months": 12.0,
    "week": 52.1775,
    "weeks": 52.1775,
    "day": 365.25,
    "days": 365.25,
}

_INTERVENTIONS_KEY_COLS = ["nct_id", "intervention_type", "intervention_name"]
_LOCATIONS_KEY_COLS = ["nct_id", "facility", "city", "state", "country"]

_STUDIES_COLUMNS = [
    "nct_id", "brief_title", "official_title", "overall_status",
    "start_date", "primary_completion_date", "study_first_post_date", "last_update_post_date",
    "sponsor_class", "sponsor_name", "conditions", "keywords", "shortlist_conditions",
    "study_type", "phases", "enrollment_count", "enrollment_type", "eligibility_criteria",
    "sex", "minimum_age_years", "maximum_age_years", "healthy_volunteers",
]


def _get_module(raw_study: dict, module_name: str) -> dict:
    """Safely fetch a protocolSection module dict, tolerating absent keys."""
    return raw_study.get("protocolSection", {}).get(module_name) or {}


def _join_or_none(values: list[str] | None) -> str | None:
    """`;`-join a list of strings, or None if the list is missing/empty."""
    if not values:
        return None
    return ";".join(values)


def flatten_study(raw_study: dict, source_condition: str) -> dict:
    """Flatten one raw study's protocolSection into one studies-table row dict (pre-dedupe)."""
    ident = _get_module(raw_study, "identificationModule")
    status = _get_module(raw_study, "statusModule")
    sponsor = _get_module(raw_study, "sponsorCollaboratorsModule")
    lead_sponsor = sponsor.get("leadSponsor") or {}
    conditions_mod = _get_module(raw_study, "conditionsModule")
    design = _get_module(raw_study, "designModule")
    enrollment_info = design.get("enrollmentInfo") or {}
    eligibility = _get_module(raw_study, "eligibilityModule")

    return {
        "nct_id": ident.get("nctId"),
        "brief_title": ident.get("briefTitle"),
        "official_title": ident.get("officialTitle"),
        "overall_status": status.get("overallStatus"),
        "start_date": (status.get("startDateStruct") or {}).get("date"),
        "primary_completion_date": (status.get("primaryCompletionDateStruct") or {}).get("date"),
        "study_first_post_date": (status.get("studyFirstPostDateStruct") or {}).get("date"),
        "last_update_post_date": (status.get("lastUpdatePostDateStruct") or {}).get("date"),
        "sponsor_class": lead_sponsor.get("class"),
        "sponsor_name": lead_sponsor.get("name"),
        "conditions": _join_or_none(conditions_mod.get("conditions")),
        "keywords": _join_or_none(conditions_mod.get("keywords")),
        "shortlist_conditions": source_condition,
        "study_type": design.get("studyType"),
        "phases": _join_or_none(design.get("phases")),
        "enrollment_count": enrollment_info.get("count"),
        "enrollment_type": enrollment_info.get("type"),
        "eligibility_criteria": eligibility.get("eligibilityCriteria"),
        "sex": eligibility.get("sex"),
        # NOTE: kept as the raw API string (e.g. "18 Years", "N/A") here, not yet parsed
        # to float — src.validate.check_age_parsing (LLD §2.4) owns the actual parse +
        # flag-and-null step, since it needs the raw string to distinguish "legitimately
        # absent" from "present but unparseable" (both parse to None via parse_age_to_years
        # alone). Converted to the final float64 dtype only after that check runs.
        "minimum_age_years": eligibility.get("minimumAge"),
        "maximum_age_years": eligibility.get("maximumAge"),
        "healthy_volunteers": eligibility.get("healthyVolunteers"),
    }


def flatten_interventions(raw_study: dict) -> list[dict]:
    """Flatten one raw study's armsInterventionsModule.interventions[] into interventions-table rows."""
    nct_id = _get_module(raw_study, "identificationModule").get("nctId")
    interventions = _get_module(raw_study, "armsInterventionsModule").get("interventions") or []
    return [
        {
            "nct_id": nct_id,
            "intervention_type": iv.get("type"),
            "intervention_name": iv.get("name"),
        }
        for iv in interventions
    ]


def flatten_locations(raw_study: dict) -> list[dict]:
    """Flatten one raw study's contactsLocationsModule.locations[] into locations-table rows."""
    nct_id = _get_module(raw_study, "identificationModule").get("nctId")
    locations = _get_module(raw_study, "contactsLocationsModule").get("locations") or []
    return [
        {
            "nct_id": nct_id,
            "facility": loc.get("facility"),
            "city": loc.get("city"),
            "state": loc.get("state"),
            "country": loc.get("country"),
        }
        for loc in locations
    ]


def parse_age_to_years(age_str: str | None) -> float | None:
    """Parse eligibilityModule.minimumAge/maximumAge strings (e.g. '18 Years', 'N/A') to years — LLD §2.4."""
    if age_str is None:
        return None
    age_str = age_str.strip()
    if not age_str or age_str.upper() == "N/A":
        return None
    match = _AGE_RE.match(age_str)
    if not match:
        return None
    value = float(match.group(1))
    divisor = _AGE_UNIT_DIVISORS[match.group(2).lower()]
    return value / divisor


def build_composite_text(study_row: dict, synonym_table: dict[str, list[str]]) -> str:
    """Build the synonym-expanded composite_text field for one study row — LLD §1.4."""
    brief_title = study_row.get("brief_title") or ""
    conditions = (study_row.get("conditions") or "").replace(";", " ")
    keywords = (study_row.get("keywords") or "").replace(";", " ")
    eligibility_criteria = study_row.get("eligibility_criteria") or ""

    text = " ".join([brief_title, conditions, keywords, eligibility_criteria])
    return expand_text(text, synonym_table)


def merge_duplicate_studies(studies_rows: list[dict]) -> pd.DataFrame:
    """Dedupe on nct_id: first-seen-wins for scalar fields, union shortlist_conditions — LLD §2.2."""
    if not studies_rows:
        return pd.DataFrame(columns=_STUDIES_COLUMNS)

    shortlist_rank = {cond: i for i, cond in enumerate(CANCER_TYPE_SHORTLIST)}

    def _rank(row: dict) -> int:
        return shortlist_rank.get(row.get("shortlist_conditions"), len(CANCER_TYPE_SHORTLIST))

    # Stable sort: enforces first-seen == fixed CANCER_TYPE_SHORTLIST order regardless of
    # the input list's own ordering (defensive — doesn't rely on the caller having already
    # iterated conditions in shortlist order).
    ordered_rows = sorted(studies_rows, key=_rank)

    merged: dict[str, dict] = {}
    seen_conditions: dict[str, set[str]] = {}
    insertion_order: list[str] = []

    for row in ordered_rows:
        nct_id = row.get("nct_id")
        if nct_id not in merged:
            merged[nct_id] = dict(row)
            seen_conditions[nct_id] = set()
            insertion_order.append(nct_id)
        condition = row.get("shortlist_conditions")
        if condition:
            seen_conditions[nct_id].add(condition)

    for nct_id in insertion_order:
        conditions = sorted(seen_conditions[nct_id], key=lambda c: shortlist_rank.get(c, len(CANCER_TYPE_SHORTLIST)))
        merged[nct_id]["shortlist_conditions"] = ";".join(conditions)

    return pd.DataFrame([merged[nct_id] for nct_id in insertion_order])


def dedupe_child_rows(rows: list[dict], key_columns: list[str]) -> pd.DataFrame:
    """Drop exact-value duplicate rows in interventions/locations after flattening — LLD §1.2/§1.3."""
    if not rows:
        return pd.DataFrame(columns=key_columns)
    df = pd.DataFrame(rows, columns=key_columns)
    return df.drop_duplicates(subset=key_columns, keep="first").reset_index(drop=True)


def transform_all(
    raw_by_condition: dict[str, list[dict]],
    synonym_table: dict[str, list[str]],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Run the full transform stage; return (studies_df, interventions_df, locations_df) pre-validation."""
    studies_rows: list[dict] = []
    interventions_rows: list[dict] = []
    locations_rows: list[dict] = []

    # Iterate in the fixed shortlist order first (first-seen priority for dedupe),
    # then any remaining conditions not in the shortlist (defensive).
    ordered_conditions = list(CANCER_TYPE_SHORTLIST) + [
        c for c in raw_by_condition if c not in CANCER_TYPE_SHORTLIST
    ]
    for condition in ordered_conditions:
        for raw_study in raw_by_condition.get(condition, []):
            studies_rows.append(flatten_study(raw_study, condition))
            interventions_rows.extend(flatten_interventions(raw_study))
            locations_rows.extend(flatten_locations(raw_study))

    studies_df = merge_duplicate_studies(studies_rows)

    # NCT-ID-format and required-field drops (LLD §2.1/§2.5) happen inside
    # validate.run_all_checks, not here — those checks own dropping the rows they flag
    # (the same (clean_df, CheckResult) pattern check_referential_integrity/
    # check_enrollment_plausibility/check_age_parsing already use) so quality_report.json
    # reports the real affected counts instead of always showing 0 against already-clean
    # data. composite_text is therefore built here over the full pre-validation set;
    # any rows later dropped by those checks are dropped in their entirety, composite_text
    # included.
    if not studies_df.empty:
        studies_df["composite_text"] = studies_df.apply(
            lambda row: build_composite_text(row.to_dict(), synonym_table), axis=1
        )
    else:
        studies_df["composite_text"] = pd.Series(dtype=object)

    studies_df = _cast_studies_dtypes(studies_df)

    interventions_df = dedupe_child_rows(interventions_rows, _INTERVENTIONS_KEY_COLS)
    interventions_df = _cast_child_dtypes(interventions_df, ["intervention_type"])

    locations_df = dedupe_child_rows(locations_rows, _LOCATIONS_KEY_COLS)
    locations_df = _cast_child_dtypes(locations_df, [])

    return studies_df, interventions_df, locations_df
