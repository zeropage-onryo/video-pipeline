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


def test_reference_block_auto_grounds_only_in_craft_and_learned_domains(monkeypatch):
    """
    Ideation's automatic layers are craft/structuring advice (the
    marketing shelf: platform mechanics, edit anatomy) and -- since
    2026-08-24 -- the learned shelves (your own approve/deny verdicts:
    winning_prompts/avoid_prompts/denials). Never ai_prompting (that's
    AI-video prompt syntax for promptgen.py's stage) and never the
    brand's own asset shelves by semantic search (personal_brand,
    cinematography, proven_results), which are opt-in only via
    picked_sources (2026-08-20).
    """
    monkeypatch.setattr(shootgen.preprod, "list_locations",
                        lambda **k: [{"name": "shop", "description": {"space": "garage"}}])
    calls = []

    def fake_retrieve(*args, **kwargs):
        calls.append(kwargs)
        return {"ok": False, "references": [], "error": "not exercised"}

    monkeypatch.setattr(shootgen.rag, "retrieve_references", fake_retrieve)

    shootgen.reference_block(spark="ritual")

    assert [c["domain"] for c in calls] == [shootgen.AUTO_IDEATION_DOMAINS,
                                            shootgen.LEARNED_IDEATION_DOMAINS]
    assert shootgen.AUTO_IDEATION_DOMAINS == ("marketing",)
    for domains in (shootgen.AUTO_IDEATION_DOMAINS, shootgen.LEARNED_IDEATION_DOMAINS):
        assert "ai_prompting" not in domains
        assert "personal_brand" not in domains
        assert "proven_results" not in domains


def test_reference_block_never_touches_asset_shelves_without_picked_sources(monkeypatch):
    monkeypatch.setattr(shootgen.preprod, "list_locations",
                        lambda **k: [{"name": "shop", "description": {"space": "garage"}}])
    monkeypatch.setattr(shootgen.rag, "retrieve_references",
                        lambda *a, **k: {"ok": False, "references": [], "error": "x"})
    called = []
    monkeypatch.setattr(
        shootgen.rag, "fetch_by_sources",
        lambda sources, **k: called.append(sources) or {"ok": True, "references": [
            {"source": "brief.txt", "chunk": "should never surface"}]},
    )

    block = shootgen.reference_block(spark="ritual")

    assert called == []
    assert "brief.txt" not in block


def test_reference_block_pulls_picked_assets_by_exact_name(monkeypatch):
    monkeypatch.setattr(shootgen.preprod, "list_locations",
                        lambda **k: [{"name": "shop", "description": {"space": "garage"}}])
    monkeypatch.setattr(shootgen.rag, "retrieve_references",
                        lambda *a, **k: {"ok": False, "references": [], "error": "x"})
    monkeypatch.setattr(
        shootgen.rag, "fetch_by_sources",
        lambda sources, **k: (
            {"ok": True, "references": [
                {"source": "brief.txt", "chunk": "still, patient, one move"}]}
            if sources == ["brief.txt"] else {"ok": True, "references": []}
        ),
    )

    block = shootgen.reference_block(spark="ritual", picked_sources=["brief.txt"])

    assert "brief.txt" in block and "still, patient, one move" in block


def test_reference_block_combines_picked_assets_with_auto_craft_advice(monkeypatch):
    monkeypatch.setattr(shootgen.preprod, "list_locations",
                        lambda **k: [{"name": "shop", "description": {"space": "garage"}}])
    monkeypatch.setattr(
        shootgen.rag, "retrieve_references",
        lambda *a, **k: {"ok": True, "references": [
            {"source": "short-form-video.md", "chunk": "hook in the first second"}]},
    )
    monkeypatch.setattr(
        shootgen.rag, "fetch_by_sources",
        lambda sources, **k: {"ok": True, "references": [
            {"source": "brief.txt", "chunk": "still, patient, one move"}]},
    )

    block = shootgen.reference_block(spark="ritual", picked_sources=["brief.txt"])

    assert "brief.txt" in block and "still, patient, one move" in block
    assert "short-form-video.md" in block and "hook in the first second" in block
