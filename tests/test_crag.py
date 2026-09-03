"""
Tests for the CRAG-style retrieval grading in src/crag.py: grade the
retrieved set, rewrite the query once if it's weak, keep whichever
result actually graded better. All of rag.retrieve_references and
gemini_utils.generate_with_retry are patched out here -- this suite
exercises crag.py's own control flow, not a real embedding or
generation call.
"""
import pytest

from src import crag, evalstore


@pytest.fixture(autouse=True)
def telemetry_db(pg, monkeypatch):
    path = pg
    evalstore.init(dsn=path)
    monkeypatch.setenv("DATABASE_URL", path)
    return path


def make_refs(*scores):
    return [{"source": f"s{i}.txt", "chunk": f"chunk {i}", "score": s}
            for i, s in enumerate(scores)]


# ---------- grade_retrieval ----------

def test_grade_retrieval_strong_when_best_score_clears_threshold():
    grade = crag.grade_retrieval(make_refs(0.3, 0.8), threshold=0.55)
    assert grade["strong"] is True
    assert grade["best_score"] == 0.8


def test_grade_retrieval_weak_when_best_score_misses_threshold():
    grade = crag.grade_retrieval(make_refs(0.3, 0.5), threshold=0.55)
    assert grade["strong"] is False
    assert grade["best_score"] == 0.5


def test_grade_retrieval_weak_on_empty_references():
    grade = crag.grade_retrieval([], threshold=0.55)
    assert grade["strong"] is False
    assert grade["best_score"] == 0.0
    assert "no references" in grade["reason"]


# ---------- retrieve_with_crag ----------

def test_retrieve_with_crag_skips_rewrite_when_retrieval_is_strong(monkeypatch,
                                                                   telemetry_db):
    calls = {"retrieve": 0, "rewrite": 0}

    def fake_retrieve(query, k=5, db_url=None, domain=None, project=None,
                      prefer_project=None):
        calls["retrieve"] += 1
        return {"ok": True, "references": make_refs(0.9)}

    monkeypatch.setattr(crag.rag, "retrieve_references", fake_retrieve)
    monkeypatch.setattr(crag, "rewrite_query", lambda *a, **k: calls.__setitem__("rewrite", calls["rewrite"] + 1))

    result = crag.retrieve_with_crag("a strong query", client=None, model="test-model")

    assert calls["retrieve"] == 1
    assert calls["rewrite"] == 0
    assert result["rewritten_query"] is None
    assert result["grade"]["strong"] is True
    assert result["telemetry"]["requery_triggered"] is False
    summary = evalstore.crag_summary(dsn=telemetry_db)
    assert summary["total"] == 1
    assert summary["requery_rate"] == 0.0


def test_retrieve_with_crag_rewrites_and_adopts_a_better_result(monkeypatch,
                                                                telemetry_db):
    retrieve_calls = []

    def fake_retrieve(query, k=5, db_url=None, domain=None, project=None,
                      prefer_project=None):
        retrieve_calls.append(query)
        if query == "original":
            return {"ok": True, "references": make_refs(0.2)}
        return {"ok": True, "references": make_refs(0.9)}

    monkeypatch.setattr(crag.rag, "retrieve_references", fake_retrieve)
    monkeypatch.setattr(crag, "rewrite_query", lambda *a, **k: "rewritten")

    result = crag.retrieve_with_crag("original", client=None, model="test-model")

    assert retrieve_calls == ["original", "rewritten"]
    assert result["rewritten_query"] == "rewritten"
    assert result["grade"]["best_score"] == 0.9
    assert result["references"][0]["score"] == 0.9
    assert result["telemetry"]["requery_triggered"] is True
    assert result["telemetry"]["score_improved"] is True
    assert result["telemetry"]["rewrite_adopted"] is True
    assert result["telemetry"]["score_change"] == pytest.approx(0.7)
    summary = evalstore.crag_summary(dsn=telemetry_db)
    assert summary["requery_rate"] == 1.0
    assert summary["requery_success_rate"] == 1.0


def test_retrieve_with_crag_keeps_original_when_rewrite_does_not_improve(monkeypatch):
    def fake_retrieve(query, k=5, db_url=None, domain=None, project=None,
                      prefer_project=None):
        # both attempts come back equally weak
        return {"ok": True, "references": make_refs(0.3)}

    monkeypatch.setattr(crag.rag, "retrieve_references", fake_retrieve)
    monkeypatch.setattr(crag, "rewrite_query", lambda *a, **k: "rewritten")

    result = crag.retrieve_with_crag("original", client=None, model="test-model")

    # the rewrite was attempted (recorded) but its result wasn't adopted
    assert result["rewritten_query"] == "rewritten"
    assert result["grade"]["best_score"] == 0.3
    assert result["telemetry"]["score_improved"] is False
    assert result["telemetry"]["rewrite_adopted"] is False


def test_retrieve_with_crag_falls_back_to_original_when_rewrite_fails(monkeypatch):
    def fake_retrieve(query, k=5, db_url=None, domain=None, project=None,
                      prefer_project=None):
        return {"ok": True, "references": make_refs(0.2)}

    def broken_rewrite(*a, **k):
        raise RuntimeError("judge model unavailable")

    monkeypatch.setattr(crag.rag, "retrieve_references", fake_retrieve)
    monkeypatch.setattr(crag, "rewrite_query", broken_rewrite)

    result = crag.retrieve_with_crag("original", client=None, model="test-model")

    assert result["rewritten_query"] is None
    assert result["grade"]["best_score"] == 0.2
    assert result["ok"] is True  # a failed rewrite degrades, it doesn't raise
    assert result["telemetry"]["rewrite_attempted"] is True
    assert result["telemetry"]["requery_triggered"] is False
    assert "rewrite failed" in result["telemetry"]["error"]


def test_retrieve_with_crag_passes_through_a_failed_retrieval_untouched(monkeypatch):
    monkeypatch.setattr(
        crag.rag, "retrieve_references",
        lambda *a, **k: {"ok": False, "references": [], "error": "connection refused"},
    )
    result = crag.retrieve_with_crag("q", client=None, model="test-model")
    assert result["ok"] is False
    assert result["grade"] is None
    assert result["rewritten_query"] is None


def test_retrieve_with_crag_forwards_k_domain_and_project(monkeypatch):
    calls = []

    def fake_retrieve(query, k=5, db_url=None, domain=None, project=None,
                      prefer_project=None):
        calls.append({"k": k, "domain": domain, "project": project})
        return {"ok": True, "references": make_refs(0.9)}

    monkeypatch.setattr(crag.rag, "retrieve_references", fake_retrieve)

    crag.retrieve_with_crag("q", client=None, model="test-model", k=3,
                            domain=("personal_brand",), project="zpf")

    assert calls[0] == {"k": 3, "domain": ("personal_brand",), "project": "zpf"}


def test_telemetry_logging_does_not_reseed_an_emptied_golden_set(telemetry_db):
    for row in evalstore.list_golden(dsn=telemetry_db):
        evalstore.delete_golden(row["id"], dsn=telemetry_db)
    evalstore.log_crag_retrieval({"original_query": "q"}, dsn=telemetry_db)
    assert evalstore.list_golden(dsn=telemetry_db) == []
