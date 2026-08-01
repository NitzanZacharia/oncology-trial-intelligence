"""Unit tests for src/matching.py's app-safe query-time API — ranking determinism
(project-plan.md milestones 16-19) and the hard_filter/rank_candidates/explain_match
contracts documented in LLD.md §3.6.
"""

import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix

from src.matching import explain_match, hard_filter, rank_candidates


def _matrix() -> csr_matrix:
    # Row i is candidate index i. Row 0 and row 2 are identical (tests tie-breaking).
    return csr_matrix(
        np.array(
            [
                [1.0, 0.0, 0.0],  # 0
                [0.0, 1.0, 0.0],  # 1
                [1.0, 0.0, 0.0],  # 2 (tie with 0)
                [0.5, 0.5, 0.0],  # 3
                [0.0, 0.0, 0.0],  # 4 (no overlap with any query)
            ]
        )
    )


def _query() -> csr_matrix:
    return csr_matrix(np.array([[1.0, 0.0, 0.0]]))


def test_rank_candidates_is_deterministic_across_repeated_calls():
    matrix = _matrix()
    query = _query()
    candidate_indices = [0, 1, 2, 3, 4]

    first = rank_candidates(query, candidate_indices, matrix, top_n=10)
    for _ in range(10):
        again = rank_candidates(query, candidate_indices, matrix, top_n=10)
        assert again == first, "rank_candidates must return the same order every time given the same inputs"


def test_rank_candidates_sorts_by_similarity_descending():
    matrix = _matrix()
    query = _query()
    ranked = rank_candidates(query, [0, 1, 2, 3, 4], matrix, top_n=10)

    scores = [score for _, score in ranked]
    assert scores == sorted(scores, reverse=True)
    # Row 0 (perfect match) must outrank row 1 (orthogonal) and row 4 (zero vector).
    top_index, top_score = ranked[0]
    assert top_index in (0, 2)
    assert top_score > 0.99


def test_rank_candidates_returns_original_indices_not_subset_positions():
    matrix = _matrix()
    query = _query()
    # Candidate subset deliberately excludes index 0 and starts at a non-zero index.
    ranked = rank_candidates(query, [2, 3, 4], matrix, top_n=10)
    returned_indices = {idx for idx, _ in ranked}
    assert returned_indices.issubset({2, 3, 4})
    assert 0 not in returned_indices


def test_rank_candidates_respects_top_n():
    matrix = _matrix()
    query = _query()
    ranked = rank_candidates(query, [0, 1, 2, 3, 4], matrix, top_n=2)
    assert len(ranked) == 2


def test_rank_candidates_empty_candidate_list_returns_empty():
    matrix = _matrix()
    query = _query()
    assert rank_candidates(query, [], matrix, top_n=10) == []


def test_hard_filter_status_and_condition():
    df = pd.DataFrame(
        {
            "nct_id": ["NCT001", "NCT002", "NCT003", "NCT004"],
            "overall_status": ["RECRUITING", "RECRUITING", "COMPLETED", "RECRUITING"],
            "shortlist_conditions": ["breast", "lung", "breast", "breast;lung"],
            "sex": ["ALL", "ALL", "ALL", "ALL"],
            "minimum_age_years": [None, None, None, None],
            "maximum_age_years": [None, None, None, None],
        },
        index=[10, 11, 12, 13],
    )
    result = hard_filter(df, "breast", None, None)
    assert set(result["nct_id"]) == {"NCT001", "NCT004"}


def test_hard_filter_does_not_reset_index():
    df = pd.DataFrame(
        {
            "nct_id": ["NCT001", "NCT002"],
            "overall_status": ["RECRUITING", "RECRUITING"],
            "shortlist_conditions": ["breast", "breast"],
            "sex": ["ALL", "ALL"],
            "minimum_age_years": [None, None],
            "maximum_age_years": [None, None],
        },
        index=[100, 101],
    )
    result = hard_filter(df, "breast", None, None)
    # Both rows match; original (non-contiguous) index values must survive untouched —
    # this is what lets the caller use result.index.tolist() as candidate_indices into
    # a TF-IDF matrix fit over the same, order-preserved studies_df (LLD §3.6).
    assert result.index.tolist() == [100, 101]


def test_hard_filter_sex_exclusion_only_when_restrictive():
    df = pd.DataFrame(
        {
            "nct_id": ["NCT001", "NCT002", "NCT003"],
            "overall_status": ["RECRUITING", "RECRUITING", "RECRUITING"],
            "shortlist_conditions": ["breast", "breast", "breast"],
            "sex": ["FEMALE", "MALE", "ALL"],
            "minimum_age_years": [None, None, None],
            "maximum_age_years": [None, None, None],
        }
    )
    result = hard_filter(df, "breast", "MALE", None)
    # FEMALE-restricted trial excluded; MALE-restricted and ALL both included.
    assert set(result["nct_id"]) == {"NCT002", "NCT003"}


def test_hard_filter_age_bounds():
    df = pd.DataFrame(
        {
            "nct_id": ["NCT001", "NCT002", "NCT003"],
            "overall_status": ["RECRUITING", "RECRUITING", "RECRUITING"],
            "shortlist_conditions": ["breast", "breast", "breast"],
            "sex": ["ALL", "ALL", "ALL"],
            "minimum_age_years": [18.0, None, 65.0],
            "maximum_age_years": [64.0, None, None],
        }
    )
    # Age 70: excluded from NCT001 (max 64) and NCT003 (min 65 -> included, no wait 70>=65 ok)
    result = hard_filter(df, "breast", None, 70)
    assert set(result["nct_id"]) == {"NCT002", "NCT003"}

    # Age 10: excluded from NCT001 (min 18) and NCT003 (min 65); NCT002 has no bounds.
    result_young = hard_filter(df, "breast", None, 10)
    assert set(result_young["nct_id"]) == {"NCT002"}


def test_explain_match_returns_overlapping_terms_highest_weight_first():
    feature_names = ["her2", "metastatic", "trastuzumab", "unrelated"]
    query_vector = csr_matrix(np.array([[0.9, 0.5, 0.0, 0.0]]))
    trial_vector = csr_matrix(np.array([[0.8, 0.1, 0.6, 0.0]]))
    # Elementwise product: her2=0.72, metastatic=0.05, trastuzumab=0.0, unrelated=0.0
    terms = explain_match(query_vector, trial_vector, feature_names, top_k=2)
    assert terms[0] == "her2"
    assert "unrelated" not in terms


def test_explain_match_no_overlap_returns_empty_list():
    feature_names = ["a", "b"]
    query_vector = csr_matrix(np.array([[1.0, 0.0]]))
    trial_vector = csr_matrix(np.array([[0.0, 1.0]]))
    assert explain_match(query_vector, trial_vector, feature_names, top_k=5) == []
