"""Data quality checks + quality_report.json, owned by `etl.py` (HLD §2 "Validate",
LLD §3.4).

Pure/local logic only — no network I/O. Runs against the flattened tables produced by
`src.transform.transform_all`, before anything is persisted to /data/processed.
"""

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import pandas as pd

from src.transform import parse_age_to_years

Status = Literal["pass", "warn", "fail"]

_NCT_ID_PATTERN = r"^NCT\d{8}$"
_STATUS_RANK = {"pass": 0, "warn": 1, "fail": 2}
_SAMPLE_CAP = 20

_REQUIRED_STUDY_COLS = ["nct_id", "brief_title", "overall_status", "conditions"]
_OPTIONAL_IMPORTANT_COLS = ["sponsor_class", "phases", "enrollment_count", "eligibility_criteria", "sex"]
_ALLOWED_PHASES = {"NA", "EARLY_PHASE1", "PHASE1", "PHASE2", "PHASE3", "PHASE4"}


@dataclass
class CheckResult:
    """One entry in quality_report.json's checks[] array — LLD §1.5."""

    name: str
    description: str
    status: Status
    scope: Literal["overall", "per_condition"]
    affected_count: int
    total_count: int
    affected_pct: float
    threshold_note: str
    sample_offending_ids: list[str]
    per_condition: dict[str, dict] | None = None


def _pct(affected: int, total: int) -> float:
    return round((affected / total * 100), 4) if total else 0.0


def _sample_ids(df: pd.DataFrame, mask: pd.Series) -> list[str]:
    if "nct_id" not in df.columns or not mask.any():
        return []
    return df.loc[mask, "nct_id"].astype(str).head(_SAMPLE_CAP).tolist()


def _zero_warn_fail_status(affected_count: int, affected_pct: float, warn_max_pct: float) -> Status:
    if affected_count == 0:
        return "pass"
    return "warn" if affected_pct <= warn_max_pct else "fail"


def check_nct_id_format(studies_df: pd.DataFrame) -> CheckResult:
    """Validate nct_id against ^NCT\\d{8}$; offenders are dropped upstream — LLD §2.1."""
    total = len(studies_df)
    if total and "nct_id" in studies_df.columns:
        valid_mask = studies_df["nct_id"].astype(str).str.match(_NCT_ID_PATTERN, na=False)
        invalid_mask = ~valid_mask
    else:
        invalid_mask = pd.Series([], dtype=bool)
    affected = int(invalid_mask.sum())
    pct = _pct(affected, total)
    return CheckResult(
        name="nct_id_format",
        description="Validates nct_id matches ^NCT\\d{8}$; non-conforming rows are dropped (transform.py, upstream of this report).",
        status="fail" if affected > 0 else "pass",
        scope="overall",
        affected_count=affected,
        total_count=total,
        affected_pct=pct,
        threshold_note="fail>0%",
        sample_offending_ids=_sample_ids(studies_df, invalid_mask),
    )


def check_required_fields(studies_df: pd.DataFrame, required_cols: list[str]) -> list[CheckResult]:
    """Fail on any missing value in required fields (nct_id, brief_title, overall_status, conditions) — LLD §2.5."""
    total = len(studies_df)
    results: list[CheckResult] = []
    for col in required_cols:
        if col in studies_df.columns:
            missing_mask = studies_df[col].isna()
        else:
            missing_mask = pd.Series([True] * total)
        affected = int(missing_mask.sum())
        pct = _pct(affected, total)
        results.append(
            CheckResult(
                name=f"required_field_missing_{col}",
                description=f"Fails if any row is missing the required field '{col}'; such rows are dropped (transform.py, upstream of this report).",
                status="fail" if affected > 0 else "pass",
                scope="overall",
                affected_count=affected,
                total_count=total,
                affected_pct=pct,
                threshold_note="fail>0%",
                sample_offending_ids=_sample_ids(studies_df, missing_mask),
            )
        )
    return results


def check_missing_rate(
    studies_df: pd.DataFrame,
    column: str,
    warn_threshold: float = 0.05,
    fail_threshold: float = 0.20,
) -> CheckResult:
    """Compute missing-rate pass/warn/fail for one optional-but-important column, overall + per-condition — LLD §2.5."""
    total = len(studies_df)

    def _status_for(affected_pct_fraction: float) -> Status:
        if affected_pct_fraction > fail_threshold:
            return "fail"
        if affected_pct_fraction > warn_threshold:
            return "warn"
        return "pass"

    if column in studies_df.columns:
        missing_mask = studies_df[column].isna()
    else:
        missing_mask = pd.Series([True] * total)
    affected = int(missing_mask.sum())
    pct = _pct(affected, total)
    overall_status = _status_for(pct / 100)

    per_condition: dict[str, dict] = {}
    if "shortlist_conditions" in studies_df.columns and total:
        exploded = studies_df.assign(
            _cond=studies_df["shortlist_conditions"].fillna("").astype(str).str.split(";")
        ).explode("_cond")
        exploded = exploded[exploded["_cond"] != ""]
        for cond, group in exploded.groupby("_cond"):
            cond_total = len(group)
            if column in group.columns:
                cond_affected = int(group[column].isna().sum())
            else:
                cond_affected = cond_total
            cond_pct = _pct(cond_affected, cond_total)
            per_condition[cond] = {
                "affected_count": cond_affected,
                "total_count": cond_total,
                "affected_pct": cond_pct,
                "status": _status_for(cond_pct / 100),
            }

    return CheckResult(
        name=f"missing_rate_{column}",
        description=f"Missing-rate check for optional-but-important field '{column}' (overall + per shortlisted condition).",
        status=overall_status,
        scope="per_condition",
        affected_count=affected,
        total_count=total,
        affected_pct=pct,
        threshold_note=f"pass<={warn_threshold*100:.0f}%, warn<={fail_threshold*100:.0f}%, fail>{fail_threshold*100:.0f}%",
        sample_offending_ids=_sample_ids(studies_df, missing_mask),
        per_condition=per_condition,
    )


def check_referential_integrity(
    studies_df: pd.DataFrame,
    child_df: pd.DataFrame,
    child_table_name: str,
) -> tuple[pd.DataFrame, CheckResult]:
    """Anti-join child_df.nct_id against studies_df.nct_id; drop orphans; return (clean_df, result) — LLD §2.3."""
    total = len(child_df)
    if total and "nct_id" in child_df.columns:
        valid_ids = set(studies_df["nct_id"]) if "nct_id" in studies_df.columns else set()
        orphan_mask = ~child_df["nct_id"].isin(valid_ids)
    else:
        orphan_mask = pd.Series([False] * total, index=child_df.index)
    affected = int(orphan_mask.sum())
    pct = _pct(affected, total)
    status: Status = "pass" if affected == 0 else ("warn" if pct <= 0.5 else "fail")
    clean_df = child_df.loc[~orphan_mask].reset_index(drop=True)
    result = CheckResult(
        name=f"referential_integrity_{child_table_name}",
        description=f"Anti-joins {child_table_name}.nct_id against studies.nct_id; orphaned rows are dropped.",
        status=status,
        scope="overall",
        affected_count=affected,
        total_count=total,
        affected_pct=pct,
        threshold_note="pass=0, warn<=0.5%, fail>0.5%",
        sample_offending_ids=_sample_ids(child_df, orphan_mask),
    )
    return clean_df, result


def check_enrollment_plausibility(studies_df: pd.DataFrame) -> tuple[pd.DataFrame, CheckResult]:
    """Flag/null out-of-range enrollment_count (0 < n <= 100000) — LLD §2.4."""
    df = studies_df.copy()
    total = len(df)
    if "enrollment_count" in df.columns and total:
        numeric = pd.to_numeric(df["enrollment_count"], errors="coerce")
        present_mask = numeric.notna()
        out_of_range_mask = present_mask & ~((numeric > 0) & (numeric <= 100000))
        df["enrollment_count"] = numeric.where(~out_of_range_mask, other=pd.NA).astype("Int64")
    else:
        out_of_range_mask = pd.Series([False] * total, index=df.index)

    affected = int(out_of_range_mask.sum())
    pct = _pct(affected, total)
    result = CheckResult(
        name="enrollment_plausibility",
        description="Flags and nulls enrollment_count values outside the plausible range 0 < n <= 100000.",
        status=_zero_warn_fail_status(affected, pct, 2.0),
        scope="overall",
        affected_count=affected,
        total_count=total,
        affected_pct=pct,
        threshold_note="pass=0, warn<=2%, fail>2%",
        sample_offending_ids=_sample_ids(df, out_of_range_mask),
    )
    return df, result


def check_phase_enum(studies_df: pd.DataFrame, allowed: set[str]) -> CheckResult:
    """Flag phases[] values outside the documented enum — LLD §2.4."""
    total = len(studies_df)

    def _row_invalid(phases_str) -> bool:
        if pd.isna(phases_str) or phases_str == "":
            return False
        tokens = [t for t in str(phases_str).split(";") if t != ""]
        return any(t not in allowed for t in tokens)

    if "phases" in studies_df.columns and total:
        mask = studies_df["phases"].apply(_row_invalid)
    else:
        mask = pd.Series([False] * total, index=studies_df.index)

    affected = int(mask.sum())
    pct = _pct(affected, total)
    return CheckResult(
        name="phase_enum",
        description="Flags rows whose phases[] contains a value outside the documented ClinicalTrials.gov v2 enum.",
        status=_zero_warn_fail_status(affected, pct, 2.0),
        scope="overall",
        affected_count=affected,
        total_count=total,
        affected_pct=pct,
        threshold_note="pass=0, warn<=2%, fail>2%",
        sample_offending_ids=_sample_ids(studies_df, mask),
    )


def _parse_partial_date(value) -> "datetime.date | None":
    if pd.isna(value) or value == "":
        return None
    text = str(value)
    for fmt in ("%Y-%m-%d", "%Y-%m"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def check_date_ordering(studies_df: pd.DataFrame) -> CheckResult:
    """Flag rows violating start<=primary_completion or first_post<=last_update_post — LLD §2.4."""
    total = len(studies_df)

    def _violates(row) -> bool:
        start = _parse_partial_date(row.get("start_date"))
        primary_completion = _parse_partial_date(row.get("primary_completion_date"))
        first_post = _parse_partial_date(row.get("study_first_post_date"))
        last_update = _parse_partial_date(row.get("last_update_post_date"))
        violation_a = start is not None and primary_completion is not None and start > primary_completion
        violation_b = first_post is not None and last_update is not None and first_post > last_update
        return violation_a or violation_b

    if total:
        mask = studies_df.apply(_violates, axis=1)
    else:
        mask = pd.Series([], dtype=bool)

    affected = int(mask.sum())
    pct = _pct(affected, total)
    return CheckResult(
        name="date_ordering",
        description="Flags rows where start_date>primary_completion_date or study_first_post_date>last_update_post_date (dates parsed permissively; row is kept either way).",
        status=_zero_warn_fail_status(affected, pct, 1.0),
        scope="overall",
        affected_count=affected,
        total_count=total,
        affected_pct=pct,
        threshold_note="pass=0, warn<=1%, fail>1%",
        sample_offending_ids=_sample_ids(studies_df, mask),
    )


def _is_legitimately_absent(value) -> bool:
    if pd.isna(value):
        return True
    if isinstance(value, str) and (value.strip() == "" or value.strip().upper() == "N/A"):
        return True
    return False


def check_age_parsing(studies_df: pd.DataFrame) -> tuple[pd.DataFrame, CheckResult]:
    """Flag present-but-unparseable minimumAge/maximumAge strings (excludes legitimate 'N/A') — LLD §2.4."""
    df = studies_df.copy()
    total = len(df)
    offending_positions: set[int] = set()

    for col in ("minimum_age_years", "maximum_age_years"):
        if col not in df.columns:
            continue
        raw_values = df[col].tolist()
        parsed_values: list[float | None] = []
        for pos, value in enumerate(raw_values):
            if _is_legitimately_absent(value):
                parsed_values.append(None)
                continue
            if isinstance(value, (int, float)):
                # Already numeric (defensive — flatten_study stores the raw string, but
                # guard against a pre-parsed value being passed through).
                parsed_values.append(float(value))
                continue
            years = parse_age_to_years(str(value))
            if years is None:
                offending_positions.add(pos)
            parsed_values.append(years)
        df[col] = pd.array(parsed_values, dtype="float64")

    affected = len(offending_positions)
    pct = _pct(affected, total)
    if affected and "nct_id" in df.columns:
        sample = df.iloc[sorted(offending_positions)]["nct_id"].astype(str).head(_SAMPLE_CAP).tolist()
    else:
        sample = []

    result = CheckResult(
        name="age_parsing",
        description="Flags present-but-unparseable minimumAge/maximumAge strings and nulls them; parses valid ones to years (legitimate 'N/A'/absent values are not flagged).",
        status=_zero_warn_fail_status(affected, pct, 2.0),
        scope="overall",
        affected_count=affected,
        total_count=total,
        affected_pct=pct,
        threshold_note="pass=0, warn<=2%, fail>2%",
        sample_offending_ids=sample,
    )
    return df, result


def _worst_status(statuses: list[Status]) -> Status:
    if not statuses:
        return "pass"
    return max(statuses, key=lambda s: _STATUS_RANK.get(s, 0))


def run_all_checks(
    studies_df: pd.DataFrame,
    interventions_df: pd.DataFrame,
    locations_df: pd.DataFrame,
    raw_row_count: int,
    duplicate_studies_merged: int,
) -> dict:
    """Run every check above in order, assemble the full quality_report.json dict — LLD §1.5."""
    checks: list[CheckResult] = []

    checks.append(check_nct_id_format(studies_df))
    checks.extend(check_required_fields(studies_df, _REQUIRED_STUDY_COLS))

    interventions_df, ref_check_interventions = check_referential_integrity(
        studies_df, interventions_df, "interventions"
    )
    checks.append(ref_check_interventions)
    locations_df, ref_check_locations = check_referential_integrity(studies_df, locations_df, "locations")
    checks.append(ref_check_locations)

    studies_df, enrollment_check = check_enrollment_plausibility(studies_df)
    checks.append(enrollment_check)

    checks.append(check_phase_enum(studies_df, _ALLOWED_PHASES))
    checks.append(check_date_ordering(studies_df))

    studies_df, age_check = check_age_parsing(studies_df)
    checks.append(age_check)

    for col in _OPTIONAL_IMPORTANT_COLS:
        checks.append(check_missing_rate(studies_df, col))

    report = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "overall_status": _worst_status([c.status for c in checks]),
        "row_counts": {
            "raw_rows_pulled": raw_row_count,
            "studies_written": len(studies_df),
            "interventions_written": len(interventions_df),
            "locations_written": len(locations_df),
            "duplicate_studies_merged": duplicate_studies_merged,
        },
        "checks": [asdict(c) for c in checks],
    }
    return report


def write_quality_report(report: dict, path: Path) -> None:
    """Write the assembled quality report dict to /data/processed/quality_report.json."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
