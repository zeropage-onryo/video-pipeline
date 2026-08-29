"""
Tests for src/rag_eval.py -- retrieval quality as numbers (hit@k, MRR)
so a chunking or embedding change can be measured against a labeled
set of queries instead of argued about. Pure math; no store, no model.
"""
import pytest

from src import rag_eval

# ---------- hit@k ----------

def test_hit_when_a_relevant_source_is_in_the_top_k():
    assert rag_eval.hit_at_k(["a", "b", "c"], ["b"], k=3) == 1


def test_miss_when_the_relevant_source_is_below_k():
    assert rag_eval.hit_at_k(["a", "b", "c"], ["c"], k=2) == 0


def test_miss_when_nothing_relevant_was_retrieved():
    assert rag_eval.hit_at_k(["a", "b"], ["z"], k=5) == 0


def test_duplicate_chunks_from_one_source_count_once():
    # three chunks of "a" must not push "b" out of the top-2 ranking
    assert rag_eval.hit_at_k(["a", "a", "a", "b"], ["b"], k=2) == 1


# ---------- reciprocal rank ----------

def test_reciprocal_rank_of_first_relevant_source():
    assert rag_eval.reciprocal_rank(["x", "y", "target"], ["target"]) == pytest.approx(1 / 3)


def test_reciprocal_rank_is_zero_when_absent():
    assert rag_eval.reciprocal_rank(["x", "y"], ["target"]) == 0.0


def test_reciprocal_rank_uses_the_best_relevant_hit():
    assert rag_eval.reciprocal_rank(["x", "t1", "t2"], ["t2", "t1"]) == pytest.approx(1 / 2)


# ---------- evaluate ----------

CASES = [
    {"query": "red room hesitation", "relevant": ["brief.txt"]},
    {"query": "engine cleaning", "relevant": ["ducati-notes.md"]},
]


def fake_retrieve(query, k):
    canned = {
        "red room hesitation": [{"source": "brief.txt", "chunk": "...", "score": 0.9}],
        "engine cleaning": [{"source": "unrelated.md", "chunk": "...", "score": 0.4}],
    }
    return canned[query][:k]


def test_evaluate_aggregates_hit_rate_and_mrr():
    report = rag_eval.evaluate(CASES, fake_retrieve, k=5)
    assert report["n"] == 2
    assert report["k"] == 5
    assert report["hit_rate"] == pytest.approx(0.5)     # one of two queries hit
    assert report["mrr"] == pytest.approx(0.5)          # (1/1 + 0) / 2
    assert len(report["per_query"]) == 2
    assert report["per_query"][0]["hit"] == 1
    assert report["per_query"][1]["hit"] == 0


def test_evaluate_refuses_an_empty_case_set():
    # an eval over nothing shouldn't be reportable as a great score
    with pytest.raises(ValueError):
        rag_eval.evaluate([], fake_retrieve, k=5)


def test_compare_base_and_crag_tracks_retry_quality_separately():
    cases = [
        {"query": "corrected", "relevant": ["target.md"]},
        {"query": "higher but wrong", "relevant": ["target.md"]},
        {"query": "strong first", "relevant": ["target.md"]},
    ]

    def base(query, k):
        return {
            "corrected": [{"source": "wrong.md", "score": 0.2}],
            "higher but wrong": [{"source": "wrong.md", "score": 0.2}],
            "strong first": [{"source": "target.md", "score": 0.9}],
        }[query]

    def full_crag(query, k):
        data = {
            "corrected": ("target.md", True, True, 0.2, 0.8),
            "higher but wrong": ("still-wrong.md", True, True, 0.2, 0.7),
            "strong first": ("target.md", False, False, 0.9, None),
        }[query]
        source, retried, adopted, initial, retry = data
        return {
            "ok": True, "references": [{"source": source, "score": retry or initial}],
            "telemetry": {
                "requery_triggered": retried,
                "score_improved": adopted,
                "rewrite_adopted": adopted,
                "initial_score": initial,
                "retry_score": retry,
                "final_score": retry or initial,
                "score_change": (retry - initial) if retry is not None else None,
            },
        }

    report = rag_eval.evaluate_comparison(cases, base, full_crag, k=5)
    assert report["base_hit_rate"] == pytest.approx(1 / 3, abs=0.0001)
    assert report["hit_rate"] == pytest.approx(2 / 3, abs=0.0001)
    assert report["requery_rate"] == pytest.approx(2 / 3, abs=0.0001)
    assert report["requery_success_rate"] == 1.0
    assert report["requery_expected_source_rate"] == 0.5
    assert report["per_query"][0]["requery_corrected_miss"] is True
    assert report["per_query"][1]["score_improved"] is True
    assert report["per_query"][1]["requery_retrieved_expected"] is False


def test_comparison_refuses_empty_case_set():
    with pytest.raises(ValueError):
        rag_eval.evaluate_comparison([], fake_retrieve, lambda q, k: {}, k=5)


def test_cli_requires_a_cases_file():
    with pytest.raises(SystemExit):
        rag_eval.main([])
