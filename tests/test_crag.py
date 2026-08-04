"""
Tests for the CRAG-style retrieval grading in src/crag.py: grade the
retrieved set, rewrite the query once if it's weak, keep whichever
result actually graded better. All of rag.retrieve_references and
gemini_utils.generate_with_retry are patched out here -- this suite
exercises crag.py's own control flow, not a real embedding or
generation call.
"""
from src import crag


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

def test_retrieve_with_crag_skips_rewrite_when_retrieval_is_strong(monkeypatch):
    calls = {"retrieve": 0, "rewrite": 0}

    def fake_retrieve(query, k=5, db_url=None, domain=None, project=None):
        calls["retrieve"] += 1
        return {"ok": True, "references": make_refs(0.9)}

    monkeypatch.setattr(crag.rag, "retrieve_references", fake_retrieve)
    monkeypatch.setattr(crag, "rewrite_query", lambda *a, **k: calls.__setitem__("rewrite", calls["rewrite"] + 1))

    result = crag.retrieve_with_crag("a strong query", client=None, model="test-model")

    assert calls["retrieve"] == 1
    assert calls["rewrite"] == 0
    assert result["rewritten_query"] is None
    assert result["grade"]["strong"] is True


def test_retrieve_with_crag_rewrites_and_adopts_a_better_result(monkeypatch):
    retrieve_calls = []

    def fake_retrieve(query, k=5, db_url=None, domain=None, project=None):
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


def test_retrieve_with_crag_keeps_original_when_rewrite_does_not_improve(monkeypatch):
    def fake_retrieve(query, k=5, db_url=None, domain=None, project=None):
        # both attempts come back equally weak
        return {"ok": True, "references": make_refs(0.3)}

    monkeypatch.setattr(crag.rag, "retrieve_references", fake_retrieve)
    monkeypatch.setattr(crag, "rewrite_query", lambda *a, **k: "rewritten")

    result = crag.retrieve_with_crag("original", client=None, model="test-model")

    # the rewrite was attempted (recorded) but its result wasn't adopted
    assert result["rewritten_query"] == "rewritten"
    assert result["grade"]["best_score"] == 0.3


def test_retrieve_with_crag_falls_back_to_original_when_rewrite_fails(monkeypatch):
    def fake_retrieve(query, k=5, db_url=None, domain=None, project=None):
        return {"ok": True, "references": make_refs(0.2)}

    def broken_rewrite(*a, **k):
        raise RuntimeError("judge model unavailable")

    monkeypatch.setattr(crag.rag, "retrieve_references", fake_retrieve)
    monkeypatch.setattr(crag, "rewrite_query", broken_rewrite)

    result = crag.retrieve_with_crag("original", client=None, model="test-model")

    assert result["rewritten_query"] is None
    assert result["grade"]["best_score"] == 0.2
    assert result["ok"] is True  # a failed rewrite degrades, it doesn't raise


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

    def fake_retrieve(query, k=5, db_url=None, domain=None, project=None):
        calls.append({"k": k, "domain": domain, "project": project})
        return {"ok": True, "references": make_refs(0.9)}

    monkeypatch.setattr(crag.rag, "retrieve_references", fake_retrieve)

    crag.retrieve_with_crag("q", client=None, model="test-model", k=3,
                            domain=("personal_brand",), project="zpf")

    assert calls[0] == {"k": 3, "domain": ("personal_brand",), "project": "zpf"}
