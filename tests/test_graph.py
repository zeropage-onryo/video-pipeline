"""
Tests for src/graph.py -- the evaluate-and-retry orchestrator.

Hermetic the same way test_shootgen is: the model call is patched at
graph.generate_with_retry (the graph's one seam to Gemini), and RAG
never enters -- the graph takes `references` as a plain string. Every
test drives the *compiled* graph through run_concept_graph, so the
edges and the conditional are exercised, not just the node functions.
"""
import json

import pytest

from src import db, graph, preprod


@pytest.fixture
def tmp_db(tmp_path):
    path = tmp_path / "test.db"
    db.init_db(path)
    preprod.init(path)
    preprod.add_location("hallway", {"space": "narrow hallway"}, photo_count=2, path=path)
    preprod.add_location("garage", {"space": "cold garage"}, photo_count=3, path=path)
    return path


def make_concept(**overrides):
    concept = {
        "title": "The Waiting",
        "hook": "a hand already on the door handle",
        "duration": "12s",
        "logline": "He waits for someone who never knocks.",
        "shots": [
            {"n": 1, "type": "CHARACTER", "cam": "BMPCC", "location": "hallway",
             "desc": "low angle, he steps into frame", "light": "overhead practical"},
            {"n": 2, "type": "BROLL", "cam": "ACTION5", "location": "garage",
             "desc": "POV of the handle turning", "light": "spill under the door"},
        ],
        "edit": "hard cuts, silence until the handle",
        "grade": "crushed shadows, one warm accent",
    }
    concept.update(overrides)
    return concept


def respond_with(*concepts):
    """A fake generate_with_retry that serves each concept in turn and
    records every prompt it was asked for."""
    queue = list(concepts)
    prompts = []

    def fake(client, model, prompt):
        prompts.append(prompt)
        return json.dumps({"concept": queue.pop(0)})

    fake.prompts = prompts
    return fake


# ---------- the happy path ----------

def test_clean_first_attempt_saves_once(tmp_db, monkeypatch):
    monkeypatch.setattr(graph, "generate_with_retry", respond_with(make_concept()))

    result = graph.run_concept_graph(brand="antihero", db_path=tmp_db)

    assert result["attempts"] == 1
    assert result["warnings"] == []
    saved = preprod.get_concept(result["concept_id"], path=tmp_db)
    assert saved["title"] == "The Waiting"
    assert len(preprod.list_concepts(path=tmp_db)) == 1  # one write, not one per attempt


# ---------- the evaluator loop ----------

def test_invalid_attempt_retries_with_evaluator_notes(tmp_db, monkeypatch):
    bad = make_concept(shots=[
        {"n": 1, "type": "CHARACTER", "cam": "BMPCC", "location": "rooftop helipad",
         "desc": "x", "light": "y"},
    ])
    fake = respond_with(bad, make_concept())
    monkeypatch.setattr(graph, "generate_with_retry", fake)

    result = graph.run_concept_graph(brand="antihero", db_path=tmp_db)

    assert result["attempts"] == 2
    assert result["warnings"] == []
    assert result["concept"]["shots"][0]["location"] == "hallway"
    # the second prompt carried the first attempt's warnings back in
    assert "EVALUATOR NOTES" in fake.prompts[1]
    assert "rooftop helipad" in fake.prompts[1]
    # and the first prompt did not
    assert "EVALUATOR NOTES" not in fake.prompts[0]


def test_never_valid_saves_best_attempt_with_warnings(tmp_db, monkeypatch):
    worse = make_concept(shots=[
        {"n": 1, "type": "WIDE", "cam": "GOPRO", "location": "moon", "desc": "x"},
    ])                                          # 3 warnings
    better = make_concept(shots=[
        {"n": 1, "type": "CHARACTER", "cam": "BMPCC", "location": "moon", "desc": "x"},
    ])                                          # 1 warning
    monkeypatch.setattr(graph, "generate_with_retry",
                        respond_with(worse, better, worse))

    result = graph.run_concept_graph(brand="antihero", db_path=tmp_db, max_attempts=3)

    assert result["attempts"] == 3
    # saved the best attempt (attempt 2), not the last one
    assert result["concept"]["shots"][0]["type"] == "CHARACTER"
    assert len(result["warnings"]) == 1
    saved = preprod.get_concept(result["concept_id"], path=tmp_db)
    assert saved["warnings"]                    # still visible on the record
    assert len(preprod.list_concepts(path=tmp_db)) == 1


def test_retry_that_gets_worse_cannot_overwrite_best(tmp_db, monkeypatch):
    better = make_concept(shots=[
        {"n": 1, "type": "CHARACTER", "cam": "BMPCC", "location": "moon", "desc": "x"},
    ])                                          # 1 warning
    worse = make_concept(shots=[
        {"n": 1, "type": "WIDE", "cam": "GOPRO", "location": "moon", "desc": "x"},
    ])                                          # 3 warnings
    monkeypatch.setattr(graph, "generate_with_retry", respond_with(better, worse))

    result = graph.run_concept_graph(brand="antihero", db_path=tmp_db, max_attempts=2)

    assert result["concept"]["shots"][0]["type"] == "CHARACTER"
    assert len(result["warnings"]) == 1


# ---------- grounding contract ----------

def test_no_locations_is_a_loud_error(tmp_path, monkeypatch):
    path = tmp_path / "empty.db"
    db.init_db(path)
    preprod.init(path)
    monkeypatch.setattr(graph, "generate_with_retry", respond_with(make_concept()))

    with pytest.raises(ValueError, match="no locations described yet"):
        graph.run_concept_graph(brand="antihero", db_path=path)


def test_references_reach_the_prompt(tmp_db, monkeypatch):
    fake = respond_with(make_concept())
    monkeypatch.setattr(graph, "generate_with_retry", fake)

    graph.run_concept_graph(brand="antihero", db_path=tmp_db,
                            references="1. [brief.txt] still, patient, one move")

    assert "still, patient, one move" in fake.prompts[0]


def test_prompt_template_recorded_without_evaluator_notes(tmp_db, monkeypatch):
    """The stored prompt is the base template: feedback varies per run,
    and hashing it in would fragment the per-prompt rates."""
    bad = make_concept(shots=[
        {"n": 1, "type": "CHARACTER", "cam": "BMPCC", "location": "moon", "desc": "x"},
    ])
    monkeypatch.setattr(graph, "generate_with_retry",
                        respond_with(bad, make_concept()))

    result = graph.run_concept_graph(brand="antihero", db_path=tmp_db)

    saved = preprod.get_concept(result["concept_id"], path=tmp_db)
    assert saved is not None
    assert "EVALUATOR NOTES" not in (saved.get("prompt_template") or "")


# ---------- smoke ----------

def test_smoke_full_graph_end_to_end(tmp_db, monkeypatch):
    """The whole compiled graph, invalid-then-valid, through to a DB
    row -- the offline smoke run. The live equivalent is
    `python -m src.graph --spark ...`."""
    bad = make_concept(shots=[
        {"n": 1, "type": "CHARACTER", "cam": "BMPCC", "location": "rooftop",
         "desc": "x", "light": "y"},
    ])
    monkeypatch.setattr(graph, "generate_with_retry",
                        respond_with(bad, make_concept()))

    result = graph.run_concept_graph(
        brand="antihero", spark="gearing up ritual", db_path=tmp_db,
        references="1. [brief.txt] noir, patient",
    )

    assert result["attempts"] == 2
    assert result["warnings"] == []
    saved = preprod.get_concept(result["concept_id"], path=tmp_db)
    assert saved["title"] == "The Waiting"
    assert saved["brand"] == "antihero"
    assert saved["spark"] == "gearing up ritual"
