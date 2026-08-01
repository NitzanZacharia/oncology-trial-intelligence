"""Unit tests for every check_* function in src/validate.py against known good/bad
inputs (project-plan.md milestones 16-19), verifying the exact pass/warn/fail thresholds
and drop behavior documented in LLD.md §2.
"""

import pandas as pd

from src.validate import (
    check_age_parsing,
    check_date_ordering,
    check_enrollment_plausibility,
    check_missing_rate,
    check_nct_id_format,
    check_phase_enum,
    check_referential_integrity,
    check_required_fields,
    run_all_checks,
)


def _studies(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def test_check_nct_id_format_all_valid_passes_and_keeps_rows():
    df = _studies([{"nct_id": "NCT12345678"}, {"nct_id": "NCT00000001"}])
    clean_df, result = check_nct_id_format(df)
    assert result.status == "pass"
    assert result.affected_count == 0
    assert len(clean_df) == 2


def test_check_nct_id_format_drops_malformed_ids_and_reports_them():
    df = _studies([{"nct_id": "NCT12345678"}, {"nct_id": "BAD-ID"}, {"nct_id": "NCT1"}])
    clean_df, result = check_nct_id_format(df)
    assert result.status == "fail"
    assert result.affected_count == 2
    assert result.total_count == 3
    assert list(clean_df["nct_id"]) == ["NCT12345678"]


def test_check_required_fields_drops_rows_missing_any_required_field():
    df = _studies(
        [
            {"nct_id": "NCT00000001", "brief_title": "A", "overall_status": "RECRUITING", "conditions": "Breast Cancer"},
            {"nct_id": "NCT00000002", "brief_title": None, "overall_status": "RECRUITING", "conditions": "Lung Cancer"},
            {"nct_id": "NCT00000003", "brief_title": "C", "overall_status": None, "conditions": "Lung Cancer"},
        ]
    )
    clean_df, results = check_required_fields(df, ["nct_id", "brief_title", "overall_status", "conditions"])
    by_name = {r.name: r for r in results}

    assert by_name["required_field_missing_brief_title"].status == "fail"
    assert by_name["required_field_missing_brief_title"].affected_count == 1
    assert by_name["required_field_missing_overall_status"].affected_count == 1
    assert by_name["required_field_missing_nct_id"].affected_count == 0
    # Every check's total_count is the same pre-drop total (3), not a shrinking one.
    assert all(r.total_count == 3 for r in results)
    # Rows missing brief_title OR overall_status are both dropped.
    assert list(clean_df["nct_id"]) == ["NCT00000001"]


def test_check_missing_rate_thresholds_pass_warn_fail():
    # LLD §2.5: pass<=5%, warn<=20%, fail>20%. 10 rows: 0 missing -> pass (0%),
    # 1 missing -> warn (10%), 8 missing -> fail (80%).
    def make(missing_count: int) -> pd.DataFrame:
        values = [None] * missing_count + ["x"] * (10 - missing_count)
        return pd.DataFrame({"sponsor_class": values, "shortlist_conditions": ["breast"] * 10})

    pass_result = check_missing_rate(make(0), "sponsor_class")
    assert pass_result.status == "pass"

    warn_result = check_missing_rate(make(1), "sponsor_class")
    assert warn_result.status == "warn"

    fail_result = check_missing_rate(make(8), "sponsor_class")
    assert fail_result.status == "fail"


def test_check_missing_rate_per_condition_breakdown():
    df = pd.DataFrame(
        {
            "sponsor_class": ["INDUSTRY", None, None, "NIH"],
            "shortlist_conditions": ["breast", "breast", "lung", "lung"],
        }
    )
    result = check_missing_rate(df, "sponsor_class")
    assert result.per_condition["breast"]["affected_count"] == 1
    assert result.per_condition["breast"]["total_count"] == 2
    assert result.per_condition["lung"]["affected_count"] == 1
    assert result.per_condition["lung"]["total_count"] == 2


def test_check_referential_integrity_drops_orphans_and_keeps_matched():
    studies_df = _studies([{"nct_id": "NCT00000001"}, {"nct_id": "NCT00000002"}])
    interventions_df = pd.DataFrame(
        {"nct_id": ["NCT00000001", "NCT00000001", "NCT99999999"], "intervention_name": ["A", "B", "Orphan"]}
    )
    clean_df, result = check_referential_integrity(studies_df, interventions_df, "interventions")
    assert result.affected_count == 1
    assert result.total_count == 3
    assert "NCT99999999" not in set(clean_df["nct_id"])
    assert len(clean_df) == 2


def test_check_referential_integrity_zero_orphans_passes():
    studies_df = _studies([{"nct_id": "NCT00000001"}])
    child_df = pd.DataFrame({"nct_id": ["NCT00000001"]})
    clean_df, result = check_referential_integrity(studies_df, child_df, "locations")
    assert result.status == "pass"
    assert len(clean_df) == 1


def test_check_enrollment_plausibility_nulls_out_of_range_values():
    df = _studies(
        [
            {"enrollment_count": 100},
            {"enrollment_count": -5},
            {"enrollment_count": 200000},
            {"enrollment_count": None},
        ]
    )
    clean_df, result = check_enrollment_plausibility(df)
    assert result.affected_count == 2
    values = clean_df["enrollment_count"].tolist()
    assert values[0] == 100
    assert pd.isna(values[1])
    assert pd.isna(values[2])
    assert pd.isna(values[3])  # legitimately missing, not counted as an offender
    assert result.status in ("warn", "fail")


def test_check_phase_enum_flags_unknown_values():
    df = _studies([{"phases": "PHASE1"}, {"phases": "PHASE1;PHASE2"}, {"phases": "PHASE99"}, {"phases": None}])
    result = check_phase_enum(df, {"NA", "EARLY_PHASE1", "PHASE1", "PHASE2", "PHASE3", "PHASE4"})
    assert result.affected_count == 1


def test_check_date_ordering_flags_violations_but_keeps_rows():
    df = _studies(
        [
            {
                "start_date": "2020-01-01",
                "primary_completion_date": "2021-01-01",
                "study_first_post_date": "2020-01-15",
                "last_update_post_date": "2020-06-01",
            },
            {
                "start_date": "2022-01-01",
                "primary_completion_date": "2021-01-01",  # violates start <= completion
                "study_first_post_date": None,
                "last_update_post_date": None,
            },
        ]
    )
    result = check_date_ordering(df)
    assert result.affected_count == 1
    assert result.status in ("warn", "fail")


def test_check_age_parsing_distinguishes_absent_from_unparseable():
    df = _studies(
        [
            {"minimum_age_years": "18 Years", "maximum_age_years": "N/A"},
            {"minimum_age_years": "6 Months", "maximum_age_years": None},
            {"minimum_age_years": "not a real age", "maximum_age_years": "N/A"},
        ]
    )
    clean_df, result = check_age_parsing(df)
    # Only row 2's minimum_age_years ("not a real age") is a genuine offender;
    # "N/A" and None are legitimately absent and must not be flagged.
    assert result.affected_count == 1
    assert clean_df.loc[0, "minimum_age_years"] == 18.0
    assert clean_df.loc[1, "minimum_age_years"] == 0.5
    assert pd.isna(clean_df.loc[2, "minimum_age_years"])


def test_run_all_checks_report_and_returned_tables_agree():
    studies_df = _studies(
        [
            {
                "nct_id": "NCT00000001",
                "brief_title": "Trial A",
                "overall_status": "RECRUITING",
                "conditions": "Breast Cancer",
                "shortlist_conditions": "breast",
                "sponsor_class": "INDUSTRY",
                "phases": "PHASE2",
                "enrollment_count": 100,
                "eligibility_criteria": "Adults",
                "sex": "ALL",
                "minimum_age_years": "18 Years",
                "maximum_age_years": "N/A",
                "start_date": "2020-01-01",
                "primary_completion_date": "2021-01-01",
                "study_first_post_date": "2020-01-15",
                "last_update_post_date": "2020-06-01",
            },
            {
                "nct_id": "BAD-ID",
                "brief_title": "Trial B",
                "overall_status": "RECRUITING",
                "conditions": "Lung Cancer",
                "shortlist_conditions": "lung",
                "sponsor_class": "NIH",
                "phases": "PHASE1",
                "enrollment_count": 50,
                "eligibility_criteria": "Adults",
                "sex": "ALL",
                "minimum_age_years": "N/A",
                "maximum_age_years": "N/A",
                "start_date": "2020-01-01",
                "primary_completion_date": "2021-01-01",
                "study_first_post_date": "2020-01-15",
                "last_update_post_date": "2020-06-01",
            },
        ]
    )
    interventions_df = pd.DataFrame({"nct_id": ["NCT00000001"], "intervention_name": ["Drug A"]})
    locations_df = pd.DataFrame({"nct_id": ["NCT00000001"], "facility": ["Hospital A"]})

    report, out_studies, out_interventions, out_locations = run_all_checks(
        studies_df, interventions_df, locations_df, raw_row_count=2, duplicate_studies_merged=0
    )

    # The malformed-NCT-ID row must actually be gone from the returned table...
    assert len(out_studies) == 1
    assert out_studies.iloc[0]["nct_id"] == "NCT00000001"
    # ...and the report's row_counts must describe that same, returned data.
    assert report["row_counts"]["studies_written"] == len(out_studies)
    assert report["row_counts"]["interventions_written"] == len(out_interventions)
    assert report["row_counts"]["locations_written"] == len(out_locations)

    nct_id_check = next(c for c in report["checks"] if c["name"] == "nct_id_format")
    assert nct_id_check["status"] == "fail"
    assert nct_id_check["affected_count"] == 1
    assert nct_id_check["total_count"] == 2  # pre-drop total, not the post-drop 1

    assert report["overall_status"] == "fail"
