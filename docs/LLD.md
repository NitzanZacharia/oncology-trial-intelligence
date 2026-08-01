# Low-Level Design — Oncology Trial Match

Status: draft for lead approval, before any code is written. This is the
third and final planning document. It takes every decision in `docs/HLD.md`
(architecture, data flow stages, storage formats) and `docs/project-plan.md`
(scope, API grounding, milestones) as locked and extends them to
implementation-ready detail: exact schemas, exact check thresholds, exact
function signatures, exact caching strategy. Nothing here revisits or
second-guesses those two documents.

No implementation code is written from this document. All function bodies
below are stubs (`...`) for planning purposes only; the module layout in
Section 3 is what `etl.py`/`app.py` will import from once implementation
starts.

---

## 1. Exact flattened schema

### 1.1 `studies` table (`/data/processed/studies.csv`) — one row per NCT ID

| Column | Dtype | Nullable | Source (`protocolSection` module.field) |
|---|---|---|---|
| `nct_id` | `string` | No (PK) | `identificationModule.nctId` |
| `brief_title` | `string` | No | `identificationModule.briefTitle` |
| `official_title` | `string` | Yes | `identificationModule.officialTitle` |
| `overall_status` | `category` | No | `statusModule.overallStatus` |
| `start_date` | `string` (ISO `YYYY-MM-DD` or `YYYY-MM`) | Yes | `statusModule.startDateStruct.date` |
| `primary_completion_date` | `string` (ISO, partial allowed) | Yes | `statusModule.primaryCompletionDateStruct.date` |
| `study_first_post_date` | `string` (ISO, partial allowed) | Yes | `statusModule.studyFirstPostDateStruct.date` |
| `last_update_post_date` | `string` (ISO, partial allowed) | Yes | `statusModule.lastUpdatePostDateStruct.date` |
| `sponsor_class` | `category` (`INDUSTRY`/`NIH`/`FED`/`OTHER`/`OTHER_GOV`/`NETWORK`/`INDIV`/`UNKNOWN`) | Yes | `sponsorCollaboratorsModule.leadSponsor.class` |
| `sponsor_name` | `string` | Yes | `sponsorCollaboratorsModule.leadSponsor.name` |
| `conditions` | `string` (`;`-joined list) | No | `conditionsModule.conditions[]` |
| `keywords` | `string` (`;`-joined list) | Yes | `conditionsModule.keywords[]` |
| `shortlist_conditions` | `string` (`;`-joined list) | No | derived — see §2.2 dedupe rule; which of the 8 shortlisted queries this NCT ID was returned under |
| `study_type` | `category` | Yes | `designModule.studyType` |
| `phases` | `string` (`;`-joined list) | Yes | `designModule.phases[]` |
| `enrollment_count` | `Int64` (nullable int) | Yes | `designModule.enrollmentInfo.count` |
| `enrollment_type` | `category` (`ACTUAL`/`ESTIMATED`) | Yes | `designModule.enrollmentInfo.type` |
| `eligibility_criteria` | `string` (free text) | Yes | `eligibilityModule.eligibilityCriteria` |
| `sex` | `category` (`ALL`/`FEMALE`/`MALE`) | Yes | `eligibilityModule.sex` |
| `minimum_age_years` | `float64` | Yes | parsed from `eligibilityModule.minimumAge` (see §2.4) |
| `maximum_age_years` | `float64` | Yes | parsed from `eligibilityModule.maximumAge` (see §2.4) |
| `healthy_volunteers` | `boolean` (nullable bool) | Yes | `eligibilityModule.healthyVolunteers` |
| `composite_text` | `string` | No | derived — see §1.4 |

Row-level rule: a row is only ever written to `studies.csv` if `nct_id`
passes the format check in §2.1 and `brief_title`/`overall_status`/
`conditions` are non-null (§2.5 "required fields"). Rows failing that are
dropped and reported, never silently written with nulls in required columns.

### 1.2 `interventions` table (`/data/processed/interventions.csv`) — one row per study/intervention pair

| Column | Dtype | Nullable | Source |
|---|---|---|---|
| `nct_id` | `string` (FK → `studies.nct_id`) | No | `identificationModule.nctId` (carried down from parent study) |
| `intervention_type` | `category` (`DRUG`/`BIOLOGICAL`/`DEVICE`/`PROCEDURE`/`RADIATION`/`BEHAVIORAL`/`DIETARY_SUPPLEMENT`/`COMBINATION_PRODUCT`/`DIAGNOSTIC_TEST`/`GENETIC`/`OTHER`) | Yes | `armsInterventionsModule.interventions[].type` |
| `intervention_name` | `string` | No | `armsInterventionsModule.interventions[].name` |

Dedupe key for this table: exact-value duplicate rows
(`nct_id`, `intervention_type`, `intervention_name`) are dropped — see §2.2.

### 1.3 `locations` table (`/data/processed/locations.csv`) — one row per study/facility pair

| Column | Dtype | Nullable | Source |
|---|---|---|---|
| `nct_id` | `string` (FK → `studies.nct_id`) | No | `identificationModule.nctId` (carried down from parent study) |
| `facility` | `string` | Yes | `contactsLocationsModule.locations[].facility` |
| `city` | `string` | Yes | `contactsLocationsModule.locations[].city` |
| `state` | `string` | Yes | `contactsLocationsModule.locations[].state` |
| `country` | `string` | Yes | `contactsLocationsModule.locations[].country` |

Dedupe key for this table: exact-value duplicate rows
(`nct_id`, `facility`, `city`, `state`, `country`) are dropped — see §2.2.

### 1.4 Derived composite text column (`studies.composite_text`)

Purpose: the single field TF-IDF is fit over (per HLD §2/§3). Constructed
per study row, in this fixed order, space-joined:

1. `brief_title`
2. `conditions` (the `;`-joined list, `;` replaced with space)
3. `keywords` (same, empty string if null)
4. `eligibility_criteria` (free text, empty string if null)

Then **synonym expansion is applied additively, not by replacement**: for
every alias key found (case-insensitive substring match) in the concatenated
string, all of that key's alternate forms (from the static table in
`src/synonyms.py`, §3) are appended once to the end of the string. This
means a trial whose eligibility text says "HER2-positive" ends up with
"HER2+" also present in `composite_text`, and vice versa — so a patient
query typed with either notation matches. Appending (rather than replacing)
means the original clinical wording is never lost from the document TF-IDF
scores against.

Lowercasing/tokenization/stop-word handling is left to `TfidfVectorizer`'s
own defaults at fit time (§3, `src/matching.py`) — `composite_text` itself
stores mixed-case natural text, not a pre-tokenized form.

### 1.5 `quality_report.json` schema

Top-level object, written by `src/validate.py` (§3) and read by the in-app
quality panel in `app.py`:

```json
{
  "generated_at": "2025-01-01T00:00:00Z",
  "overall_status": "pass | warn | fail",
  "row_counts": {
    "raw_rows_pulled": 0,
    "studies_written": 0,
    "interventions_written": 0,
    "locations_written": 0,
    "duplicate_studies_merged": 0
  },
  "checks": [
    {
      "name": "nct_id_format",
      "description": "one-line human-readable description of what the check does",
      "status": "pass | warn | fail",
      "scope": "overall | per_condition",
      "affected_count": 0,
      "total_count": 0,
      "affected_pct": 0.0,
      "threshold_note": "e.g. warn>5%, fail>20%",
      "sample_offending_ids": ["NCT........", "..."],
      "per_condition": {
        "breast": {"affected_count": 0, "total_count": 0, "affected_pct": 0.0, "status": "pass"}
      }
    }
  ]
}
```

`per_condition` is only populated for checks defined as
`scope: "per_condition"` in §2.5 (missing-rate checks); checks that are
inherently table-wide (dedupe, referential integrity) omit it. Every check
in §2 below maps 1:1 to one entry in `checks[]`. `overall_status` is the
worst status (`fail` > `warn` > `pass`) across all entries in `checks[]`.

---

## 2. Data quality check logic and thresholds

All checks below run in `src/validate.py` against the flattened,
pre-dedupe/post-dedupe DataFrames, before anything is written to
`/data/processed`, per HLD §2 "Validate". Each check produces one
`checks[]` entry per §1.5.

### 2.1 NCT ID format validation

- Pattern: `^NCT\d{8}$` (exact — `NCT` followed by exactly 8 digits).
- Any row whose `identificationModule.nctId` fails this pattern is dropped
  from `studies` (and cascades: its `interventions`/`locations` rows are
  dropped too, since they can never satisfy referential integrity in §2.3
  anyway).
- Threshold: **fail** if `affected_pct > 0%` (i.e. any occurrence at all is
  a fail) — this is treated as a data-contract violation, not a tolerance
  question, since the API's ID format is fixed and documented.

### 2.2 Dedupe key and dedupe rule

- Dedupe key: `nct_id`, table-wide across all 8 condition pulls (a study
  whose `conditionsModule.conditions[]` includes e.g. both "Breast Cancer"
  and "Lung Cancer" is returned once per matching `query.cond` pull, so the
  same NCT ID can appear in two or more of the per-condition raw JSON
  files).
- Rule: **first-seen wins for all scalar fields.** "First-seen" order is
  the fixed shortlist iteration order defined in `src/extract.py`
  (`CANCER_TYPE_SHORTLIST`, §3) — e.g. if `breast` is pulled before `lung`
  and NCT12345678 appears in both, the row instantiated from the `breast`
  pull's copy of the record is canonical.
- The one field that is *merged* rather than first-seen-wins is
  `shortlist_conditions` (§1.1): every condition pull that returned this
  NCT ID is unioned into that column, so downstream landscape filtering by
  cancer type still finds the study under both. (Note: since `breast` and
  `lung` pulls return the identical underlying API record, `conditions`/
  `eligibility_criteria`/etc. are byte-identical between the duplicates —
  the only thing that differs between the two raw copies is which
  condition query surfaced them, hence only `shortlist_conditions` needs an
  explicit merge step.)
- `interventions`/`locations` rows are flattened per raw record instance;
  duplicate raw instances of the same study therefore produce duplicate
  rows in those two tables, deduped by exact-row-value equality (§1.2,
  §1.3) after flattening, independent of the `studies`-level merge.
- Not a pass/warn/fail check — `row_counts.duplicate_studies_merged`
  (§1.5) is informational only.

### 2.3 Referential integrity

- Check logic (conceptually a `LEFT JOIN` / anti-join): for each of
  `interventions` and `locations`, compute
  `orphans = df[~df.nct_id.isin(studies.nct_id)]`. Symmetric check in the
  other direction is not needed because `interventions`/`locations` rows
  are only ever created *from* a study record already being flattened into
  `studies` in the same pass — an orphan can only arise from a bug (e.g. a
  study dropped by §2.1's NCT ID check after its child rows were already
  emitted).
- Orphans are **dropped** from `interventions`/`locations` before write (an
  intervention/location row with no parent study is meaningless to the
  app's filtering, which always starts from `studies`) and every dropped
  `nct_id` is recorded in `sample_offending_ids` (capped at 20 examples).
- Threshold: **pass** if 0 orphans; **warn** if orphans ≤ 0.5% of the
  pre-drop row count of that table; **fail** if > 0.5% (at that point the
  cascade from §2.1 is producing more loss than a rare edge case should,
  and the pipeline should surface it loudly rather than quietly drop rows).

### 2.4 Plausibility rules

**Enrollment count** (`designModule.enrollmentInfo.count` →
`enrollment_count`):
- Valid range: `0 < enrollment_count <= 100000`.
- Non-numeric or missing → `enrollment_count = NA` (not an error; sparse
  by design on some study types — counted under the missing-rate check in
  §2.5, not this plausibility check).
- Present but `<= 0` or `> 100000` → value is set to `NA` and the row's
  `nct_id` is recorded as an offender of this check (value itself is
  discarded rather than kept out-of-range, since a negative/absurd
  enrollment count is not usable downstream).
- Threshold: **pass** if 0 out-of-range values; **warn** if
  `affected_pct <= 2%`; **fail** if `> 2%`.

**Phase enum** (`designModule.phases[]` → `phases`):
- Allowed enum values (per ClinicalTrials.gov v2 documented set): `NA`,
  `EARLY_PHASE1`, `PHASE1`, `PHASE2`, `PHASE3`, `PHASE4`.
- Any value in the `phases[]` array not in this set is invalid; the whole
  row is flagged (not silently coerced), and the offending value is kept
  in the `phases` string as-is (informational) but the row counts toward
  `affected_count`.
- Threshold: **pass** if 0 invalid values; **warn** if
  `affected_pct <= 2%`; **fail** if `> 2%`.

**Status date ordering** (`statusModule.*DateStruct.date` fields):
- Two ordering rules checked per row, each independently:
  1. `start_date <= primary_completion_date` (when both present).
  2. `study_first_post_date <= last_update_post_date` (when both present).
- Dates are parsed permissively (`YYYY-MM-DD` or `YYYY-MM`; a
  year-month-only value is treated as the 1st of that month for comparison
  purposes only — the original string is preserved in the column, never
  overwritten).
- A row violating either rule is flagged; the row is **kept** (dates are
  descriptive metadata, not used in hard filtering, so a violation doesn't
  justify dropping the trial from the match pool — it's a data-quality
  signal shown in the report, not a filter).
- Threshold: **pass** if 0 violations; **warn** if `affected_pct <= 1%`;
  **fail** if `> 1%`.

**`minimumAge`/`maximumAge` parsing** (`eligibilityModule.minimumAge`/
`maximumAge` → `minimum_age_years`/`maximum_age_years`):
- Raw values are strings like `"18 Years"`, `"6 Months"`, `"N/A"`, or
  absent entirely.
- Parse regex: `^(\d+(?:\.\d+)?)\s*(Year|Years|Month|Months|Week|Weeks|Day|Days)$`
  (case-insensitive). Convert to years: `Years` → as-is; `Months` → `/12`;
  `Weeks` → `/52.1775`; `Days` → `/365.25`.
- `"N/A"`, empty string, or field absent → `NA`, **not** flagged as an
  error (this is the documented, expected representation of "no age
  bound" and is extremely common — most trials have no `maximumAge`).
- A string that is present, non-`"N/A"`, and fails the regex (unexpected
  format) → `NA` **and** flagged as an offender (this is the only failure
  mode this check reports on — unparseable-but-present values, not
  legitimately-absent ones).
- Threshold: **pass** if 0 unparseable-but-present values; **warn** if
  `affected_pct <= 2%`; **fail** if `> 2%`.

### 2.5 Missing-rate (pass/warn/fail) thresholds feeding `quality_report.json`

Two tiers of fields, checked both **overall** (across all 8 conditions
combined) and **per-condition** (using `shortlist_conditions`, §1.1) so a
single condition's API quirk doesn't get diluted into an overall "pass":

**Required fields** — `nct_id`, `brief_title`, `overall_status`,
`conditions`. These are present in every study record per the API's own
schema contract (project-plan.md §0 grounding), so any missing value here
is a fail, not a tolerance question:
- **fail** if `affected_pct > 0%` for any of these four fields, overall or
  per-condition. Rows missing any required field are dropped from
  `studies` entirely (§1.1) and counted here, not silently carried
  forward with a null.

**Important-but-optional fields** — `sponsor_class`, `phases`,
`enrollment_count`, `eligibility_criteria`, `sex`:
- **pass** if `affected_pct <= 5%`
- **warn** if `5% < affected_pct <= 20%`
- **fail** if `affected_pct > 20%`

These thresholds exist because these fields feed either the matching
pipeline (`eligibility_criteria`, `sex` → hard filter and composite text)
or the landscape view (`sponsor_class`, `phases`) directly — a field
missing on more than a fifth of recruiting studies for a shortlisted
cancer type would materially degrade either feature, and the report should
surface that loudly rather than let it pass quietly as "just some nulls."

---

## 3. Module layout and function signatures

Consistent with HLD §1: everything under `src/extract.py` is the *only*
network-I/O-capable code, imported exclusively by `etl.py`. Everything else
is pure/local-I/O and importable from both `etl.py` and `app.py` where
relevant (`src/synonyms.py`, `src/matching.py`'s query-time functions,
`src/storage.py`'s read path). No file below is created as an actual `.py`
file — these are markdown-only stubs for planning purposes.

### 3.1 `src/extract.py` — all network I/O, owned exclusively by `etl.py`

```python
from pathlib import Path
from typing import Iterator

CANCER_TYPE_SHORTLIST: list[str] = [
    "breast", "lung", "prostate", "colorectal",
    "pancreatic", "melanoma", "leukemia", "lymphoma",
]  # fixed iteration order — also the "first-seen" order for dedupe (LLD §2.2)

FIELDS: list[str] = [
    # explicit fields= list limited to modules used downstream (HLD §2 Extract)
]

def raw_checkpoint_path(condition: str, raw_dir: Path) -> Path:
    """Return the /data/raw/<condition>.json path for a given shortlisted condition."""
    ...

def has_checkpoint(condition: str, raw_dir: Path) -> bool:
    """Return True if a raw checkpoint for this condition already exists (resume check)."""
    ...

def fetch_condition_page(
    condition: str,
    page_token: str | None,
    fields: list[str],
    page_size: int,
    base_url: str,
) -> dict:
    """Fetch one page of GET /api/v2/studies for a condition; returns raw JSON response.
    On HTTP 429, retries with exponential backoff (not just the fixed 1.2s inter-request
    delay) — the fixed delay paces normal requests, this retry is the actual rate-limit
    error handling for when pacing alone wasn't enough."""
    ...

def paginate_condition(
    condition: str,
    fields: list[str] = FIELDS,
    page_size: int = 500,
    request_delay_s: float = 1.2,
    base_url: str = "https://clinicaltrials.gov/api/v2/studies",
) -> Iterator[dict]:
    """Yield every raw study record for a condition, following pageToken/nextPageToken."""
    ...

def write_raw_checkpoint(condition: str, studies: list[dict], raw_dir: Path) -> None:
    """Write the concatenated pages for one condition to /data/raw/<condition>.json."""
    ...

def load_raw_checkpoint(condition: str, raw_dir: Path) -> list[dict]:
    """Load a previously written /data/raw/<condition>.json checkpoint."""
    ...

def extract_all(
    conditions: list[str] = CANCER_TYPE_SHORTLIST,
    raw_dir: Path = Path("data/raw"),
    fields: list[str] = FIELDS,
) -> dict[str, list[dict]]:
    """Orchestrate the full extract stage: skip conditions with an existing checkpoint (resume), pull the rest, return {condition: [raw studies]}."""
    ...
```

### 3.2 `src/synonyms.py` — static biomarker alias table, used by both ETL transform and app query building

```python
SYNONYM_TABLE: dict[str, list[str]] = {
    "her2+": ["her2-positive", "her2 positive"],
    "her2-positive": ["her2+"],
    "egfr mutation": ["egfr mutant", "egfr-mutated"],
    # ... static, hand-curated table (project-plan.md §1 "one piece of smarts")
}

def load_synonym_table() -> dict[str, list[str]]:
    """Return the static synonym/alias table (module-level constant, no file I/O)."""
    ...

def expand_text(text: str, synonym_table: dict[str, list[str]] | None = None) -> str:
    """Append every alias for each matched key found in text (additive, not replacing) — LLD §1.4."""
    ...
```

### 3.3 `src/transform.py` — flatten raw JSON into the three tables + composite text, owned by `etl.py`

```python
import pandas as pd

def flatten_study(raw_study: dict, source_condition: str) -> dict:
    """Flatten one raw study's protocolSection into one studies-table row dict (pre-dedupe)."""
    ...

def flatten_interventions(raw_study: dict) -> list[dict]:
    """Flatten one raw study's armsInterventionsModule.interventions[] into interventions-table rows."""
    ...

def flatten_locations(raw_study: dict) -> list[dict]:
    """Flatten one raw study's contactsLocationsModule.locations[] into locations-table rows."""
    ...

def parse_age_to_years(age_str: str | None) -> float | None:
    """Parse eligibilityModule.minimumAge/maximumAge strings (e.g. '18 Years', 'N/A') to years — LLD §2.4."""
    ...

def build_composite_text(study_row: dict, synonym_table: dict[str, list[str]]) -> str:
    """Build the synonym-expanded composite_text field for one study row — LLD §1.4."""
    ...

def merge_duplicate_studies(studies_rows: list[dict]) -> pd.DataFrame:
    """Dedupe on nct_id: first-seen-wins for scalar fields, union shortlist_conditions — LLD §2.2."""
    ...

def dedupe_child_rows(rows: list[dict], key_columns: list[str]) -> pd.DataFrame:
    """Drop exact-value duplicate rows in interventions/locations after flattening — LLD §1.2/§1.3."""
    ...

def transform_all(
    raw_by_condition: dict[str, list[dict]],
    synonym_table: dict[str, list[str]],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Run the full transform stage; return (studies_df, interventions_df, locations_df) pre-validation.

    Does NOT drop NCT-ID-format or required-field violations — that happens inside
    validate.check_nct_id_format/check_required_fields (§3.4), which own their own drop the
    same way check_referential_integrity/check_enrollment_plausibility/check_age_parsing do,
    so quality_report.json's affected_count/total_count for those checks describe the real
    pre-drop data rather than trivially reporting 0 against an already-filtered frame."""
    ...
```

### 3.4 `src/validate.py` — data quality checks + `quality_report.json`, owned by `etl.py`

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
import pandas as pd

Status = Literal["pass", "warn", "fail"]

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

def check_nct_id_format(studies_df: pd.DataFrame) -> tuple[pd.DataFrame, CheckResult]:
    """Validate nct_id against ^NCT\\d{8}$; drop offenders and return (clean_df, result) — LLD §2.1."""
    ...

def check_required_fields(
    studies_df: pd.DataFrame, required_cols: list[str]
) -> tuple[pd.DataFrame, list[CheckResult]]:
    """Fail on any missing value in required fields (nct_id, brief_title, overall_status, conditions); drop offending rows and return (clean_df, results) — LLD §2.5."""
    ...

def check_missing_rate(
    studies_df: pd.DataFrame,
    column: str,
    warn_threshold: float = 0.05,
    fail_threshold: float = 0.20,
) -> CheckResult:
    """Compute missing-rate pass/warn/fail for one optional-but-important column, overall + per-condition — LLD §2.5."""
    ...

def check_referential_integrity(
    studies_df: pd.DataFrame,
    child_df: pd.DataFrame,
    child_table_name: str,
) -> tuple[pd.DataFrame, CheckResult]:
    """Anti-join child_df.nct_id against studies_df.nct_id; drop orphans; return (clean_df, result) — LLD §2.3."""
    ...

def check_enrollment_plausibility(studies_df: pd.DataFrame) -> tuple[pd.DataFrame, CheckResult]:
    """Flag/null out-of-range enrollment_count (0 < n <= 100000) — LLD §2.4."""
    ...

def check_phase_enum(studies_df: pd.DataFrame, allowed: set[str]) -> CheckResult:
    """Flag phases[] values outside the documented enum — LLD §2.4."""
    ...

def check_date_ordering(studies_df: pd.DataFrame) -> CheckResult:
    """Flag rows violating start<=primary_completion or first_post<=last_update_post — LLD §2.4."""
    ...

def check_age_parsing(studies_df: pd.DataFrame) -> tuple[pd.DataFrame, CheckResult]:
    """Flag present-but-unparseable minimumAge/maximumAge strings (excludes legitimate 'N/A') — LLD §2.4."""
    ...

def run_all_checks(
    studies_df: pd.DataFrame,
    interventions_df: pd.DataFrame,
    locations_df: pd.DataFrame,
    raw_row_count: int,
    duplicate_studies_merged: int,
) -> tuple[dict, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Run every check above in order, assemble the full quality_report.json dict, and
    return it alongside the cleaned (studies_df, interventions_df, locations_df) —
    NCT-ID-format and required-field violations dropped, referential-integrity orphans
    dropped, enrollment out-of-range values nulled, ages parsed to float — LLD §1.5. The
    report and the returned tables must describe the same data: callers write these
    returned DataFrames to /data/processed, not the ones passed in, so quality_report.json
    never claims a fix that isn't actually on disk."""
    ...

def write_quality_report(report: dict, path: Path) -> None:
    """Write the assembled quality report dict to /data/processed/quality_report.json."""
    ...
```

### 3.5 `src/storage.py` — read/write of `/data/processed`, read path shared by `app.py`

```python
from pathlib import Path
import pandas as pd

def write_tables(
    studies_df: pd.DataFrame,
    interventions_df: pd.DataFrame,
    locations_df: pd.DataFrame,
    processed_dir: Path,
) -> None:
    """Write the three validated flat tables to /data/processed/*.csv."""
    ...

def read_tables(processed_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Read the three flat tables back with correct dtypes applied on load."""
    ...

def write_tfidf_artifacts(vectorizer, matrix, processed_dir: Path) -> None:
    """Persist the fitted TfidfVectorizer and sparse matrix via joblib.dump."""
    ...

def read_tfidf_artifacts(processed_dir: Path) -> tuple[object, object]:
    """Load the fitted TfidfVectorizer and sparse matrix via joblib.load."""
    ...

def read_quality_report(processed_dir: Path) -> dict:
    """Read /data/processed/quality_report.json for the in-app quality panel."""
    ...

def processed_dir_fingerprint(processed_dir: Path) -> str:
    """Hash the mtimes of all files under /data/processed — cache key input for app.py (LLD §4)."""
    ...
```

### 3.6 `src/matching.py` — TF-IDF fit (ETL-time) and query/rank/explain (app-time, query-only vectorization)

```python
from scipy.sparse import spmatrix
from sklearn.feature_extraction.text import TfidfVectorizer
import pandas as pd

def fit_vectorizer(composite_texts: list[str]) -> tuple[TfidfVectorizer, spmatrix]:
    """Fit TfidfVectorizer once over all studies' composite_text (ETL-time only, never called by app.py)."""
    ...

def build_query_text(
    condition: str,
    biomarker_tags: list[str],
    stage_text: str | None,
    synonym_table: dict[str, list[str]],
) -> str:
    """Build the patient query string and apply the same synonym expansion used at transform time."""
    ...

def hard_filter(
    studies_df: pd.DataFrame,
    condition: str,
    sex: str | None,
    age: float | None,
) -> pd.DataFrame:
    """Filter to RECRUITING + matching condition + sex/age eligibility where present — HLD §2."""
    ...

def vectorize_query(query_text: str, vectorizer: TfidfVectorizer) -> spmatrix:
    """Transform (never fit) the incoming query text against the already-fitted vectorizer."""
    ...

def rank_candidates(
    query_vector: spmatrix,
    candidate_indices: list[int],
    matrix: spmatrix,
    top_n: int = 20,
) -> list[tuple[int, float]]:
    """Cosine-rank candidate_indices against the precomputed matrix; return [(row_index, score), ...] desc."""
    ...

def explain_match(
    query_vector: spmatrix,
    trial_vector: spmatrix,
    feature_names: list[str],
    top_k: int = 5,
) -> list[str]:
    """Return the top_k highest-weight overlapping terms between query and trial vectors, plain language."""
    ...
```

---

## 4. Streamlit caching strategy

Loader/compute functions in `app.py` (owned by `app.py`, calling into
`src/storage.py` and `src/matching.py`'s read/transform-only functions —
never `src/extract.py` or `src/matching.py.fit_vectorizer`, per HLD §1's
one-way arrow):

```python
import streamlit as st

@st.cache_data
def load_processed_tables(processed_dir: str, fingerprint: str):
    """Load studies/interventions/locations CSVs; cached on (processed_dir, fingerprint) key."""
    ...

@st.cache_resource
def load_matching_artifacts(processed_dir: str, fingerprint: str):
    """Load the fitted TfidfVectorizer + sparse matrix via joblib; cached on (processed_dir, fingerprint) key."""
    ...

@st.cache_data
def load_quality_report(processed_dir: str, fingerprint: str) -> dict:
    """Load quality_report.json for the in-app quality panel; cached on (processed_dir, fingerprint) key."""
    ...
```

**Decorator choice, per HLD §3:**
- `st.cache_data` for the three flat tables and the quality report — these
  are plain, hashable/serializable data (DataFrames, dict), which is
  exactly what `cache_data` is designed for and gives copy-on-read safety
  (a user can't mutate the cached DataFrame across sessions).
- `st.cache_resource` for the TF-IDF vectorizer + sparse matrix — these are
  a fitted scikit-learn estimator and a scipy sparse matrix, neither of
  which `cache_data`'s hashing/pickling path is meant for; `cache_resource`
  is Streamlit's documented mechanism for exactly this "load a heavy
  singleton resource once" case, matching HLD §3's own reasoning.

**Cache key strategy.** All three loaders take `fingerprint` as an explicit
argument rather than relying on Streamlit's default file-path-only hashing.
`processed_dir_fingerprint()` (`src/storage.py`, §3.5) computes a hash of
the mtimes (and sizes, as a cheap corroborating signal) of every file under
`/data/processed`. `app.py` computes this fingerprint once at the top of
the script (a fast, uncached stat-only operation) and passes it into each
`@st.cache_data`/`@st.cache_resource` function as an argument — since
Streamlit's cache key includes all arguments to the function, a changed
fingerprint (i.e. `etl.py` was re-run and touched files under
`/data/processed`) automatically invalidates and reloads every cached
artifact, with no manual cache-clearing step and no risk of the app
silently serving stale tables/vectorizer against a fresh ETL run.

**Confirmation: TF-IDF fit/transform never recomputes per user
interaction.** `fit_vectorizer()` (`src/matching.py`, §3.6) is called
exactly once, inside `etl.py`, and is never imported by `app.py`. Every
per-interaction call in `app.py` — triggered by the patient profile form
being submitted — only calls `vectorize_query()` (§3.6), which is a
`.transform()` call against the already-fitted vectorizer loaded once by
`load_matching_artifacts()`. This is the same guarantee HLD §2 ("App
load") and project-plan.md risk #4 both call for: the expensive fit step
happens zero times in the Streamlit process, no matter how many times a
user changes the form and re-submits.
