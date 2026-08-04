"""
Reference grounding for ideation.

Retrieval lives at the edges (the CLI and the web routes) via
reference_block; the generate functions take an already-retrieved
`references` string. That split is what makes these tests hermetic --
patching shootgen.rag.retrieve_references is enough, nothing here can
reach Postgres through rag.connect (which sits below conftest's socket
guard) or Gemini.
"""
from src import shootgen


def test_build_ideas_prompt_injects_references():
    locs = [{"name": "shop", "description": {"space": "garage"}}]
    prompt = shootgen.build_ideas_prompt(
        locs, "antihero", references="1. [brief.txt] still, patient, one move"
    )
    assert "1. [brief.txt] still, patient, one move" in prompt
    assert "{references}" not in prompt


def test_build_ideas_prompt_falls_back_without_references():
    locs = [{"name": "shop", "description": {"space": "garage"}}]
    prompt = shootgen.build_ideas_prompt(locs, "antihero", references="")
    assert shootgen.NO_REFERENCES_NOTE in prompt
    assert "{references}" not in prompt


def test_build_concept_prompt_injects_references():
    locs = [{"name": "shop", "description": {"space": "garage"}}]
    prompt = shootgen.build_concept_prompt(
        locs, "antihero", references="1. [kurosawa.txt] hold the frame"
    )
    assert "1. [kurosawa.txt] hold the frame" in prompt
    assert shootgen.NO_REFERENCES_NOTE not in prompt


def test_build_reference_query_uses_spark_and_room_mood():
    locs = [{"name": "shop",
             "description": {"space": "garage", "textures": ["wet metal"],
                             "constraints": "no clean wide"}}]
    q = shootgen.build_reference_query(locs, spark="gearing up ritual", client=None)
    assert "gearing up ritual" in q
    assert "wet metal" in q and "no clean wide" in q


def test_reference_block_formats_hits(monkeypatch):
    monkeypatch.setattr(shootgen.preprod, "list_locations",
                        lambda **k: [{"name": "shop", "description": {"space": "garage"}}])
    monkeypatch.setattr(
        shootgen.rag, "retrieve_references",
        lambda *a, **k: {"ok": True, "references": [
            {"source": "brief.txt", "chunk": "still, patient, one move"}]},
    )
    block = shootgen.reference_block(spark="ritual")
    assert "brief.txt" in block and "still, patient, one move" in block


def test_reference_block_degrades_to_empty(monkeypatch):
    monkeypatch.setattr(shootgen.preprod, "list_locations",
                        lambda **k: [{"name": "shop", "description": {"space": "garage"}}])
    monkeypatch.setattr(
        shootgen.rag, "retrieve_references",
        lambda *a, **k: {"ok": False, "references": [], "error": "no postgres"},
    )
    assert shootgen.reference_block(spark="ritual") == ""


def test_reference_block_empty_when_no_locations(monkeypatch):
    monkeypatch.setattr(shootgen.preprod, "list_locations", lambda **k: [])
    # no rooms -> empty query -> no retrieval attempted, returns ""
    assert shootgen.reference_block(spark="ritual") == ""


def test_reference_block_scopes_to_the_ideation_domains(monkeypatch):
    """
    Ideation grounds in brand/cinematography/marketing/proven_results,
    never ai_prompting -- that shelf is AI-video prompt syntax for
    promptgen.py's stage, not "what should we shoot" material.
    """
    monkeypatch.setattr(shootgen.preprod, "list_locations",
                        lambda **k: [{"name": "shop", "description": {"space": "garage"}}])
    calls = []

    def fake_retrieve(*args, **kwargs):
        calls.append(kwargs)
        return {"ok": False, "references": [], "error": "not exercised"}

    monkeypatch.setattr(shootgen.rag, "retrieve_references", fake_retrieve)

    shootgen.reference_block(spark="ritual")

    assert len(calls) == 1
    assert calls[0]["domain"] == shootgen.IDEATION_DOMAINS
    assert "ai_prompting" not in shootgen.IDEATION_DOMAINS
    assert "proven_results" in shootgen.IDEATION_DOMAINS
