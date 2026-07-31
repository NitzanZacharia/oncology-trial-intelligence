"""Read/write of `/data/processed`, read path shared by `app.py` (HLD §3 storage
decisions, LLD §3.5).

Pure/local I/O only — no network calls. `write_tables`/`write_tfidf_artifacts` are
called exclusively from `etl.py`; `read_tables`/`read_tfidf_artifacts`/
`read_quality_report`/`processed_dir_fingerprint` are called from both `etl.py`
(sanity checks) and `app.py` (LLD §4 caching).

Index/row-order alignment contract (see also src/matching.py's module docstring):
`etl.py` fits the TF-IDF matrix via `matching.fit_vectorizer(studies_df["composite_text"]
.tolist())` over a given `studies_df`, in that exact row order, and then calls
`write_tables(studies_df, ...)` with that SAME, unreordered `studies_df`. `write_tables`
must not sort or otherwise reorder rows before writing, and `read_tables` reads the CSV
back with a fresh `0..n-1` RangeIndex via plain `pandas.read_csv` (which preserves file
row order). As long as both halves of that contract hold, position `i` in the studies
table read back by `read_tables` always corresponds to row `i` of the TF-IDF matrix
persisted by `write_tfidf_artifacts`/loaded by `read_tfidf_artifacts` — which is what lets
`matching.hard_filter()`'s output index values be used directly as `candidate_indices`
into that matrix at app query-time.
"""

import hashlib
import json
from pathlib import Path

import joblib
import pandas as pd

from src.transform import _cast_child_dtypes, _cast_studies_dtypes

_STUDIES_FILENAME = "studies.csv"
_INTERVENTIONS_FILENAME = "interventions.csv"
_LOCATIONS_FILENAME = "locations.csv"
_QUALITY_REPORT_FILENAME = "quality_report.json"
_VECTORIZER_FILENAME = "tfidf_vectorizer.joblib"
_MATRIX_FILENAME = "tfidf_matrix.joblib"

# Post-validation dtype: minimum_age_years/maximum_age_years are raw strings out of
# transform.transform_all(), but by the time run_all_checks() (src/validate.py) has run,
# they've been parsed to float64 (validate.check_age_parsing). transform._cast_studies_dtypes
# deliberately leaves these two columns untouched (it's shared with the pre-validation path),
# so storage.py — which only ever sees post-validation studies_df — casts them explicitly here.
_STUDIES_FLOAT_COLS = ["minimum_age_years", "maximum_age_years"]

_INTERVENTIONS_CATEGORY_COLS = ["intervention_type"]
_LOCATIONS_CATEGORY_COLS: list[str] = []


def write_tables(
    studies_df: pd.DataFrame,
    interventions_df: pd.DataFrame,
    locations_df: pd.DataFrame,
    processed_dir: Path,
) -> None:
    """Write the three validated flat tables to /data/processed/*.csv.

    Row-order contract: writes rows in exactly the order they appear in the given
    DataFrames — never sorts or reorders. `studies_df` in particular must be the same
    DataFrame (same row order) that was passed to `matching.fit_vectorizer()` to build the
    TF-IDF matrix, so that a later `read_tables()` call's row positions keep lining up with
    that matrix's row positions (see module docstring).
    """
    processed_dir = Path(processed_dir)
    processed_dir.mkdir(parents=True, exist_ok=True)
    studies_df.to_csv(processed_dir / _STUDIES_FILENAME, index=False)
    interventions_df.to_csv(processed_dir / _INTERVENTIONS_FILENAME, index=False)
    locations_df.to_csv(processed_dir / _LOCATIONS_FILENAME, index=False)


def read_tables(processed_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Read the three flat tables back with correct dtypes applied on load.

    Row-order contract: `pandas.read_csv` preserves on-disk row order and assigns a fresh
    `0..n-1` RangeIndex, so `studies_df.index` positions returned here line up with
    `matching`'s TF-IDF matrix row positions exactly as they did at ETL-fit time — as long
    as `write_tables` wrote this same, unreordered row order (see module docstring).
    """
    processed_dir = Path(processed_dir)

    studies_df = pd.read_csv(processed_dir / _STUDIES_FILENAME)
    studies_df = _cast_studies_dtypes(studies_df)
    for col in _STUDIES_FLOAT_COLS:
        if col in studies_df.columns:
            studies_df[col] = pd.to_numeric(studies_df[col], errors="coerce").astype("float64")

    interventions_df = pd.read_csv(processed_dir / _INTERVENTIONS_FILENAME)
    interventions_df = _cast_child_dtypes(interventions_df, _INTERVENTIONS_CATEGORY_COLS)

    locations_df = pd.read_csv(processed_dir / _LOCATIONS_FILENAME)
    locations_df = _cast_child_dtypes(locations_df, _LOCATIONS_CATEGORY_COLS)

    return studies_df, interventions_df, locations_df


def write_tfidf_artifacts(vectorizer, matrix, processed_dir: Path) -> None:
    """Persist the fitted TfidfVectorizer and sparse matrix via joblib.dump.

    joblib, not pickle, per HLD §3 (scikit-learn's own recommended path for fitted
    estimators / scipy sparse artifacts).
    """
    processed_dir = Path(processed_dir)
    processed_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(vectorizer, processed_dir / _VECTORIZER_FILENAME)
    joblib.dump(matrix, processed_dir / _MATRIX_FILENAME)


def read_tfidf_artifacts(processed_dir: Path) -> tuple[object, object]:
    """Load the fitted TfidfVectorizer and sparse matrix via joblib.load."""
    processed_dir = Path(processed_dir)
    vectorizer = joblib.load(processed_dir / _VECTORIZER_FILENAME)
    matrix = joblib.load(processed_dir / _MATRIX_FILENAME)
    return vectorizer, matrix


def read_quality_report(processed_dir: Path) -> dict:
    """Read /data/processed/quality_report.json for the in-app quality panel."""
    processed_dir = Path(processed_dir)
    with open(processed_dir / _QUALITY_REPORT_FILENAME, "r", encoding="utf-8") as f:
        return json.load(f)


def processed_dir_fingerprint(processed_dir: Path) -> str:
    """Hash the mtimes of all files under /data/processed — cache key input for app.py
    (LLD §4).

    Hashes the sorted list of (filename, mtime, size) for every file directly under
    `processed_dir` into a stable hex digest: identical file states hash identically, and
    any file being added/removed/modified under `processed_dir` (e.g. a re-run of `etl.py`)
    changes the digest. `app.py` passes this string as an explicit argument to its
    `@st.cache_data`/`@st.cache_resource` loaders so a stale cache is never silently served.
    """
    processed_dir = Path(processed_dir)
    entries: list[str] = []
    if processed_dir.exists():
        for path in sorted(processed_dir.iterdir(), key=lambda p: p.name):
            if not path.is_file():
                continue
            stat = path.stat()
            entries.append(f"{path.name}:{stat.st_mtime_ns}:{stat.st_size}")
    digest_input = "|".join(entries).encode("utf-8")
    return hashlib.sha256(digest_input).hexdigest()
