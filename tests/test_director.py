"""
Tests for src/director.py -- director mode's revise-in-place. Hermetic:
generate_with_retry is patched at the module the code calls, so no test
can bill a model. What's under test is the safety around the call: a
broken revision never lands, attachments survive a wording change, and
validation warnings ride along.
"""
import json

import pytest

from src import db, director, preprod


@pytest.fixture
def tmp_db(tmp_path):
    path = tmp_path / "t.db"
    db.init_db(path)
    preprod.init(path)
    return path


def seed_scene(path):
    return preprod.save_concept(
        {"title": "Vault", "hook": "h", "logline": "l", "duration": "12s",
         "shots": [
             {"n": 1, "type": "BROLL", "source": "AI", "location": "garage",
              "tool": "RUNWAY", "prompt": "low key garage",
              "media_url": "https://cdn.example/one.mp4",
              "reference_image": "https://cdn.example/plate.jpg"},
             {"n": 2, "type": "CHARACTER", "source": "CAMERA", "cam": "BMPCC",
              "location": "garage", "desc": "hands on the wrench"},
         ]},
        brand="antihero", path=path)


def fake_model(response_text):
    """Patch point: director calls generate_with_retry(client, model, prompt)."""
    def _fake(client, model, contents):
        fake_model.last_prompt = contents
        return response_text
    return _fake


def test_direct_revises_and_carries_attachments(tmp_db, monkeypatch):
    concept_id = seed_scene(tmp_db)
    revised = {
        "duration": "12s",
        "shots": [
            {"n": 1, "type": "BROLL", "source": "AI", "location": "garage",
             "tool": "RUNWAY", "prompt": "low key garage, slower push"},
            {"n": 2, "type": "CHARACTER", "source": "CAMERA", "cam": "BMPCC",
             "location": "garage", "desc": "hands on the wrench"},
        ],
        "edit": "hold the reveal",
    }
    monkeypatch.setattr(director, "generate_with_retry",
                        fake_model(json.dumps(revised)))

    result = director.direct_scene(concept_id, "shot 1 slower", db_path=tmp_db)
    assert result["ok"], result["error"]
    assert "revised shot(s) 1" in result["summary"]

    concept = preprod.get_concept(concept_id, path=tmp_db)
    shot1 = concept["shots"][0]
    assert shot1["prompt"] == "low key garage, slower push"
    # the clip and reference attached to shot 1 survived the rewrite
    assert shot1["media_url"] == "https://cdn.example/one.mp4"
    assert shot1["reference_image"] == "https://cdn.example/plate.jpg"
    assert concept["edit_note"] == "hold the reveal"
    # the note and the current shots reached the model
    assert "shot 1 slower" in fake_model.last_prompt
    assert "low key garage" in fake_model.last_prompt


def test_broken_revision_never_lands(tmp_db, monkeypatch):
    concept_id = seed_scene(tmp_db)
    before = preprod.get_concept(concept_id, path=tmp_db)["shots"]

    for bad in ("not json at all", json.dumps({"shots": []})):
        monkeypatch.setattr(director, "generate_with_retry", fake_model(bad))
        result = director.direct_scene(concept_id, "make it moodier", db_path=tmp_db)
        assert result["ok"] is False
        assert preprod.get_concept(concept_id, path=tmp_db)["shots"] == before


def test_silent_shot_loss_is_refused(tmp_db, monkeypatch):
    """A note that didn't ask for cuts must not quietly halve the scene."""
    concept_id = seed_scene(tmp_db)
    one_shot = {"shots": [{"n": 1, "type": "BROLL", "source": "AI",
                           "location": "garage", "tool": "RUNWAY", "prompt": "x"}]}
    monkeypatch.setattr(director, "generate_with_retry",
                        fake_model(json.dumps(one_shot)))
    result = director.direct_scene(concept_id, "make it moodier", db_path=tmp_db)
    assert result["ok"] is False
    assert "dropped" in result["error"]
    # ...but the same shrink is honoured when the note asked for it
    result = director.direct_scene(concept_id, "remove shot 2", db_path=tmp_db)
    assert result["ok"] is True


def test_direct_needs_a_note_and_a_planned_scene(tmp_db, monkeypatch):
    monkeypatch.setattr(director, "generate_with_retry", fake_model("{}"))
    concept_id = preprod.save_concept(
        {"title": "Idea only", "shots": []}, brand="antihero", path=tmp_db)
    assert "no shot plan" in director.direct_scene(
        concept_id, "moodier", db_path=tmp_db)["error"]
    assert "empty note" in director.direct_scene(
        concept_id, "  ", db_path=tmp_db)["error"]
    assert "no concept" in director.direct_scene(
        999, "moodier", db_path=tmp_db)["error"]


def test_hallucinated_location_surfaces_as_warning_not_rejection(tmp_db, monkeypatch):
    """A CAMERA shot moved to a room that doesn't exist is a visible
    warning on the saved scene, never a rejection -- prompts request,
    code advises. (An AI shot may invent a space; that's not flagged.)"""
    preprod.add_location("garage", {"space": "the real garage"}, path=tmp_db)
    concept_id = seed_scene(tmp_db)
    revised = {"shots": [
        {"n": 1, "type": "BROLL", "source": "AI", "location": "garage",
         "tool": "RUNWAY", "prompt": "x"},
        {"n": 2, "type": "CHARACTER", "source": "CAMERA", "cam": "BMPCC",
         "location": "moon base", "desc": "d"},
    ]}
    monkeypatch.setattr(director, "generate_with_retry",
                        fake_model(json.dumps(revised)))
    result = director.direct_scene(concept_id, "move shot 2 somewhere strange",
                                   db_path=tmp_db)
    assert result["ok"] is True                      # saved, not rejected
    assert any("moon base" in w for w in result["warnings"])
    saved = preprod.get_concept(concept_id, path=tmp_db)
    assert any("moon base" in w for w in saved["warnings"])


def test_refine_writes_back_only_a_changed_prompt(tmp_db, monkeypatch):
    concept_id = seed_scene(tmp_db)
    from src import promptgen, rag
    monkeypatch.setattr(rag, "retrieve_references",
                        lambda q, k=5, db_url=None, domain=None, project=None:
                            {"ok": True, "references": [
                                {"source": "s", "chunk": "technique", "domain": "ai_prompting",
                                 "project": None, "source_ref": None, "score": 0.9}]})
    # raising=False: refine_prompt ships with in-flight promptgen work and
    # may not exist on the committed tree -- the patch IS the function then
    monkeypatch.setattr(promptgen, "refine_prompt",
                        lambda raw, tool, client, model=None, references="":
                            raw + ", handheld sway, no plastic AI sheen",
                        raising=False)
    result = director.refine_shot_prompt(concept_id, 1, db_path=tmp_db)
    assert result["ok"] and result["changed"]
    saved = preprod.get_concept(concept_id, path=tmp_db)
    assert saved["shots"][0]["prompt"].endswith("no plastic AI sheen")


def test_refine_without_the_shelf_is_a_result(tmp_db, monkeypatch):
    concept_id = seed_scene(tmp_db)
    from src import promptgen, rag
    monkeypatch.setattr(promptgen, "refine_prompt",
                        lambda *a, **k: "unreached", raising=False)
    monkeypatch.setattr(rag, "retrieve_references",
                        lambda q, k=5, db_url=None, domain=None, project=None:
                            {"ok": False, "references": [], "error": "store down"})
    result = director.refine_shot_prompt(concept_id, 1, db_path=tmp_db)
    assert result["ok"] is False
    assert "technique references" in result["error"]


def test_refine_degrades_when_promptgen_work_has_not_landed(tmp_db, monkeypatch):
    """CI runs the committed tree, where promptgen.refine_prompt may not
    exist yet -- polish must report itself unavailable, not crash."""
    concept_id = seed_scene(tmp_db)
    from src import promptgen
    monkeypatch.delattr(promptgen, "refine_prompt", raising=False)
    result = director.refine_shot_prompt(concept_id, 1, db_path=tmp_db)
    assert result["ok"] is False
    assert "hasn't landed" in result["error"]
