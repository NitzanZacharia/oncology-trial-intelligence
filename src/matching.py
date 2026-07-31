"""TF-IDF fit (ETL-time) and query/rank/explain (app-time, query-only vectorization) —
HLD §2 "Store" / "User query -> rank -> explain", LLD §3.6.

Index/row-order alignment contract (see also src/storage.py's module docstring): the
matrix `fit_vectorizer` returns has one row per element of the input `composite_texts`
list, in that exact order, and has no other way to know which matrix row corresponds to
which trial. For `hard_filter()`'s output to be usable as `candidate_indices` into that
matrix (per `rank_candidates`'s signature), whatever calls `fit_vectorizer` (`etl.py`)
must do so with `studies_df["composite_text"].tolist()` from the SAME `studies_df` (same
row order) that then gets written via `storage.write_tables` — so that `studies_df.index`
positions always line up with `matrix` row positions, from ETL through to app-time
querying via `storage.read_tables` + `hard_filter`.
"""

from scipy.sparse import spmatrix
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np
import pandas as pd

from src.synonyms import expand_text

# =============================================================================
# ETL-TIME ONLY. `fit_vectorizer` performs the one-time TF-IDF fit over the full
# studies corpus (HLD §2 "Store", LLD §4). It must never be imported or called from
# `app.py`, or from any function below this separator — every function below is the
# "app-safe, query-time API": it only ever calls `.transform()` against an
# already-fitted vectorizer, so it's safe to call on every user interaction with zero
# re-fit cost (LLD §4 "Confirmation: TF-IDF fit/transform never recomputes per user
# interaction").
# =============================================================================


def fit_vectorizer(composite_texts: list[str]) -> tuple[TfidfVectorizer, spmatrix]:
    """Fit TfidfVectorizer once over all studies' composite_text (ETL-time only, never
    called by app.py).

    Row `i` of the returned matrix corresponds to `composite_texts[i]`. Callers must pass
    `studies_df["composite_text"].tolist()` from the same, order-preserved `studies_df`
    that is subsequently written via `storage.write_tables` — see module docstring.
    """
    vectorizer = TfidfVectorizer()
    matrix = vectorizer.fit_transform(composite_texts)
    return vectorizer, matrix


# =============================================================================
# APP-SAFE, QUERY-TIME API — importable from both etl.py (for the end-of-run sanity
# check) and app.py. Nothing below this line ever fits/re-fits the vectorizer.
# =============================================================================


def build_query_text(
    condition: str,
    biomarker_tags: list[str],
    stage_text: str | None,
    synonym_table: dict[str, list[str]],
) -> str:
    """Build the patient query string and apply the same synonym expansion used at
    transform time (`transform.build_composite_text`, LLD §1.4) — so notation
    differences (e.g. "HER2+" vs. "HER2-positive") match symmetrically on both the query
    side and the trial-document side.
    """
    parts = [condition or ""]
    if biomarker_tags:
        parts.append(" ".join(biomarker_tags))
    if stage_text:
        parts.append(stage_text)
    text = " ".join(p for p in parts if p)
    return expand_text(text, synonym_table)


def hard_filter(
    studies_df: pd.DataFrame,
    condition: str,
    sex: str | None,
    age: float | None,
) -> pd.DataFrame:
    """Filter to RECRUITING + matching condition + sex/age eligibility where present —
    HLD §2.

    - `overall_status == "RECRUITING"`: checked defensively even though extract.py already
      scopes the pull to RECRUITING at fetch time (`filter.overallStatus`) — this function
      does not assume upstream never changes.
    - `condition` must appear as a token in the `;`-split `shortlist_conditions` column
      (the fixed-shortlist tag column, e.g. "breast") — NOT a substring match against the
      free-text `conditions` column, which contains arbitrary disease names.
    - `sex`, if given: a trial is excluded only if its `sex` column is `MALE` or `FEMALE`
      (i.e. actually restricted) and doesn't match the given `sex`. `ALL`/null trials are
      never excluded on this basis.
    - `age`, if given: a trial is excluded if `age` falls outside
      `[minimum_age_years, maximum_age_years]` when those bounds are present; a missing
      bound imposes no constraint on that side.

    Index contract: returns a boolean-masked slice of `studies_df` WITHOUT resetting the
    index — `filtered_df.index.tolist()` therefore gives the correct positional row
    indices into the original, full `studies_df`, and (per the module-level index-
    alignment contract) into the TF-IDF matrix fit over that same, order-preserved table.
    Do not call `.reset_index()` on the result.
    """
    mask = studies_df["overall_status"].astype(str) == "RECRUITING"

    condition_norm = (condition or "").strip().lower()
    shortlist_tokens = (
        studies_df["shortlist_conditions"].fillna("").astype(str).str.lower().str.split(";")
    )
    mask &= shortlist_tokens.apply(lambda tokens: condition_norm in tokens)

    if sex:
        sex_norm = sex.strip().upper()
        sex_col = studies_df["sex"].astype(str).str.upper()
        sex_is_restricted = sex_col.isin(["MALE", "FEMALE"])
        sex_mismatch = sex_is_restricted & (sex_col != sex_norm)
        mask &= ~sex_mismatch

    if age is not None:
        min_age = pd.to_numeric(studies_df["minimum_age_years"], errors="coerce")
        max_age = pd.to_numeric(studies_df["maximum_age_years"], errors="coerce")
        below_min = min_age.notna() & (age < min_age)
        above_max = max_age.notna() & (age > max_age)
        mask &= ~(below_min | above_max)

    return studies_df[mask]


def vectorize_query(query_text: str, vectorizer: TfidfVectorizer) -> spmatrix:
    """Transform (never fit) the incoming query text against the already-fitted
    vectorizer."""
    return vectorizer.transform([query_text])


def rank_candidates(
    query_vector: spmatrix,
    candidate_indices: list[int],
    matrix: spmatrix,
    top_n: int = 20,
) -> list[tuple[int, float]]:
    """Cosine-rank candidate_indices against the precomputed matrix; return
    [(row_index, score), ...] desc.

    `candidate_indices` are positional row indices into `matrix` (per the module-level
    index-alignment contract — typically `hard_filter(...).index.tolist()`). The returned
    tuples use those same original indices, not 0..n positions within the candidate
    subset, so a caller can map a result straight back to `studies_df.iloc[row_index]`.
    """
    if not candidate_indices:
        return []

    candidate_matrix = matrix[candidate_indices]
    similarities = cosine_similarity(query_vector, candidate_matrix)[0]

    scored = list(zip(candidate_indices, (float(s) for s in similarities)))
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored[:top_n]


def explain_match(
    query_vector: spmatrix,
    trial_vector: spmatrix,
    feature_names: list[str],
    top_k: int = 5,
) -> list[str]:
    """Return the top_k highest-weight overlapping terms between query and trial
    vectors, plain language.

    Both vectors are TF-IDF rows over the same fitted vocabulary. Their elementwise
    product highlights terms present (and weighted) in both; the top_k highest-product
    features are mapped to their vocabulary strings via `feature_names` and returned —
    never raw indices/scores.
    """
    query_arr = np.asarray(query_vector.todense()).ravel()
    trial_arr = np.asarray(trial_vector.todense()).ravel()
    product = query_arr * trial_arr

    nonzero_count = int(np.count_nonzero(product))
    if nonzero_count == 0:
        return []

    k = min(top_k, nonzero_count)
    top_indices = np.argpartition(product, -k)[-k:]
    top_indices = top_indices[np.argsort(product[top_indices])[::-1]]

    return [feature_names[i] for i in top_indices]
