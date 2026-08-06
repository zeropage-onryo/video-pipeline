"""
Tests for src/orchestrator.py -- the LangGraph loop over pre-production.

Hermetic: the two stage calls the graph makes (shootgen.generate_concept,
shootgen.reference_block) are patched at the shootgen module, so no
Gemini, no RAG, no real DB writes. Every test drives the compiled GRAPH
through run(), so the edges and both conditionals are exercised.
"""
import pytest

from src import db, orchestrator, preprod


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """The orchestrator's nodes read db.DB_PATH directly (same as the web
    routes), so point it at a throwaway database."""
    path = tmp_path / "test.db"
    db.init_db(path)
    preprod.init(path)
    monkeypatch.setattr(db, "DB_PATH", path)
    preprod.add_location("hallway", {"space": "narrow hallway"}, photo_count=2, path=path)
    return path


def make_concept(**overrides):
    concept = {
        "title": "The Waiting",
        "logline": "He waits for someone who never knocks.",
        "shots": [
            {"n": 1, "type": "CHARACTER", "source": "CAMERA", "cam": "BMPCC",
             "location": "hallway", "desc": "low angle, he steps into frame"},
            {"n": 2, "type": "BROLL", "source": "AI", "tool": "KLING",
             "location": "hallway", "desc": "the handle turns on its own",
             "prompt": "a door handle turning in the dark, noir grain"},
        ],
    }
    concept.update(overrides)
    return concept


def stage_fakes(monkeypatch, results):
    """Patch the two shootgen calls; record the spark each attempt used."""
    queue = list(results)
    sparks = []

    def fake_generate(brand, client=None, spark=None, gemini_client=None,
                      model=None, use_pov=True, db_path=None, references=""):
        sparks.append(spark)
        concept, warnings = queue.pop(0)
        return {"concept_id": len(sparks), "concept": concept, "warnings": warnings}

    monkeypatch.setattr(orchestrator.shootgen, "generate_concept", fake_generate)
    monkeypatch.setattr(orchestrator.shootgen, "reference_block", lambda **k: "")
    monkeypatch.setattr(orchestrator, "_client", lambda: None)
    return sparks


# ---------- the happy path ----------

def test_clean_first_attempt_passes(tmp_db, monkeypatch):
    stage_fakes(monkeypatch, [(make_concept(), [])])

    result = orchestrator.run("gearing up ritual")

    assert result["attempts"] == 1
    assert result["critique"]["ok"] is True
    assert result["critique"]["issues"] == []
    assert result.get("error") is None


def test_finalize_extracts_only_ai_shot_prompts(tmp_db, monkeypatch):
    stage_fakes(monkeypatch, [(make_concept(), [])])

    result = orchestrator.run("ritual")

    assert result["shot_prompts"] == [
        {"tool": "KLING", "prompt": "a door handle turning in the dark, noir grain"},
    ]


# ---------- the corrective loop ----------

def test_warnings_trigger_a_retry_with_feedback_in_the_spark(tmp_db, monkeypatch):
    sparks = stage_fakes(monkeypatch, [
        (make_concept(), ["shot 1: unknown location 'rooftop' -- not a described space"]),
        (make_concept(), []),
    ])

    result = orchestrator.run("gearing up ritual")

    assert result["attempts"] == 2
    assert result["critique"]["ok"] is True
    assert "Fix these issues" in sparks[1]
    assert "rooftop" in sparks[1]
    assert "Fix these issues" not in (sparks[0] or "")


def test_never_clean_stops_at_max_attempts_and_still_finalizes(tmp_db, monkeypatch):
    bad = (make_concept(), ["concept has no shots"])
    stage_fakes(monkeypatch, [bad] * orchestrator.MAX_ATTEMPTS)

    result = orchestrator.run("ritual")

    assert result["attempts"] == orchestrator.MAX_ATTEMPTS
    assert result["critique"]["ok"] is False
    assert "concept has no shots" in result["critique"]["issues"]
    # stop still routes through finalize -- the prompts are extractable
    assert "shot_prompts" in result


# ---------- grounding + judge defaults ----------

def test_no_locations_stops_before_any_generation(tmp_path, monkeypatch):
    path = tmp_path / "empty.db"
    db.init_db(path)
    preprod.init(path)
    monkeypatch.setattr(db, "DB_PATH", path)
    sparks = stage_fakes(monkeypatch, [])

    result = orchestrator.run("ritual")

    assert "No described locations" in result["error"]
    assert sparks == []                      # generate never ran


def test_judge_is_off_unless_asked_for(tmp_db, monkeypatch):
    monkeypatch.delenv("JUDGE", raising=False)
    called = []
    monkeypatch.setattr(orchestrator, "_judge", lambda c: called.append(1) or (0.0, ["x"]))
    stage_fakes(monkeypatch, [(make_concept(), [])])

    result = orchestrator.run("ritual")

    assert called == []                      # judge never invoked
    assert result["critique"]["score"] == 1.0


def test_judge_score_below_floor_fails_the_critique(tmp_db, monkeypatch):
    monkeypatch.setenv("JUDGE", "1")
    monkeypatch.setattr(orchestrator, "_judge",
                        lambda c: (0.2, ["needs a crew to pull focus"]))
    stage_fakes(monkeypatch, [(make_concept(), [])] * orchestrator.MAX_ATTEMPTS)

    result = orchestrator.run("ritual")

    assert result["critique"]["ok"] is False
    assert "needs a crew to pull focus" in result["critique"]["issues"]
