"""
The uncanny judge is Zero Page's on-brand GATE. Unlike taste_judge it scores a
fixed rubric (works with zero history) and it FAILS CLOSED — a judge that can't
run must never let a concept auto-post. The one LLM call is mocked.
"""
import json

import pytest

from src import preprod, uncanny_judge


def _fake_client(payload):
    """A gemini client stand-in; generate_with_retry is what actually calls it,
    so we monkeypatch that instead in tests that need a specific reply."""
    return object()


def test_a_strong_concept_passes(monkeypatch):
    monkeypatch.setattr(
        uncanny_judge, "generate_with_retry",
        lambda *a, **k: json.dumps({"uncanny_hook": 9, "grounded": 8,
                                    "format_fit": 8, "no_recurring_star": 9,
                                    "overall": 8.5, "reasons": ["frame 1 is wrong"]}))
    out = uncanny_judge.score_concept({"title": "x", "hook": "h"}, gemini_client=object())
    assert out["graded"] is True
    assert out["passed"] is True
    assert out["overall"] == 8.5


def test_glossy_concept_is_gated_even_with_high_overall(monkeypatch):
    # high hook + high overall, but grounded is below the floor -> glossy, HOLD
    monkeypatch.setattr(
        uncanny_judge, "generate_with_retry",
        lambda *a, **k: json.dumps({"uncanny_hook": 9, "grounded": 3,
                                    "format_fit": 8, "no_recurring_star": 9,
                                    "overall": 8.0, "reasons": ["too polished"]}))
    out = uncanny_judge.score_concept({"title": "x"}, gemini_client=object())
    assert out["graded"] is True
    assert out["passed"] is False


def test_no_uncanny_hook_is_gated(monkeypatch):
    monkeypatch.setattr(
        uncanny_judge, "generate_with_retry",
        lambda *a, **k: json.dumps({"uncanny_hook": 2, "grounded": 9,
                                    "format_fit": 8, "no_recurring_star": 9,
                                    "overall": 7.5, "reasons": ["pretty, not wrong"]}))
    assert uncanny_judge.gate({"title": "x"}, gemini_client=object()) is False


def test_a_recurring_star_is_gated(monkeypatch):
    monkeypatch.setattr(
        uncanny_judge, "generate_with_retry",
        lambda *a, **k: json.dumps({"uncanny_hook": 8, "grounded": 8,
                                    "format_fit": 8, "no_recurring_star": 2,
                                    "overall": 8.0, "reasons": ["a recurring star"]}))
    assert uncanny_judge.gate({"title": "x"}, gemini_client=object()) is False


def test_judge_failure_fails_closed(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("no key")
    monkeypatch.setattr(uncanny_judge, "generate_with_retry", boom)
    out = uncanny_judge.score_concept({"title": "x"}, gemini_client=object())
    assert out["graded"] is False
    assert out["passed"] is False   # fail closed — the whole point
    assert "unavailable" in out["reasons"][0]


def test_bad_json_fails_closed(monkeypatch):
    monkeypatch.setattr(uncanny_judge, "generate_with_retry", lambda *a, **k: "not json")
    out = uncanny_judge.score_concept({"title": "x"}, gemini_client=object())
    assert out["passed"] is False


@pytest.fixture
def tmp_db(pg, monkeypatch):
    path = pg
    preprod.init(path)
    monkeypatch.setenv("DATABASE_URL", path)
    return path


def test_save_uncanny_score_persists_pass_and_reason(tmp_db):
    cid = preprod.save_concept(
        {"title": "Wrong Room", "hook": "the ceiling is the floor",
         "logline": "a room that's upside down but nobody reacts",
         "shots": [{"n": 1, "type": "BROLL", "source": "AI",
                    "tool": "VEO", "prompt": "x"}]},
        brand="zeropage", dsn=tmp_db, account_id=None)
    preprod.save_uncanny_score(
        cid, {"overall": 8.5, "passed": True, "reasons": ["frame 1 is wrong"]},
        dsn=tmp_db, account_id=None)
    got = preprod.get_concept(cid, dsn=tmp_db, account_id=None)
    assert got["uncanny_overall"] == 8.5
    assert got["uncanny_passed"] == 1
    assert "frame 1 is wrong" in got["uncanny_reason"]


def test_rank_orders_best_first(monkeypatch):
    replies = iter([
        json.dumps({"uncanny_hook": 5, "grounded": 5, "format_fit": 5,
                    "no_recurring_star": 5, "overall": 5.0, "reasons": []}),
        json.dumps({"uncanny_hook": 9, "grounded": 9, "format_fit": 9,
                    "no_recurring_star": 9, "overall": 9.0, "reasons": []}),
    ])
    monkeypatch.setattr(uncanny_judge, "generate_with_retry", lambda *a, **k: next(replies))
    ranked = uncanny_judge.rank([{"title": "low"}, {"title": "high"}], gemini_client=object())
    assert ranked[0]["title"] == "high"


# --- what the judge actually READS (2026-09-02) -----------------------------
#
# The gate scored four summary lines and nothing else, which made it a grader
# of loglines. Concept 167 passed faceless at 8.0 -- "maintains faceless
# anonymity through POV" -- over a prompt reading "end on his wide-eyed
# reaction", and the keyframe came back with a face across the top third.
# These pin the prompts into the payload, and pin the camera move staying in.

def test_shot_prompts_reach_the_judge():
    concept = {
        "title": "Internal Proof", "hook": "a phone screen",
        "logline": "a package and a photo taken from the wrong side",
        "shots": [{"n": 1, "type": "BROLL",
                   "prompt": "Tilt up from the hand to his wide-eyed face."}],
    }
    payload = uncanny_judge.build_prompt(concept)
    assert "wide-eyed face" in payload      # the thing that gets rendered
    assert "SHOT PROMPTS" in payload


def test_the_camera_move_is_not_stripped():
    """Moves inform the image and stay in the prompt verbatim -- the judge is
    told to score where the move LANDS, not to penalise having one."""
    concept = {"title": "x", "shots": [
        {"n": 1, "prompt": "Slow push in past the doorway, then whip pan."}]}
    payload = uncanny_judge.build_prompt(concept)
    assert "Slow push in past the doorway, then whip pan." in payload
    assert "CAMERA MOVES ARE EXPECTED" in payload


def test_a_concept_with_no_prompts_yet_is_still_judgeable():
    """brand_gate can run before any prompt is written. Failing closed is for
    ERRORS; an early concept still gets scored on its summary."""
    payload = uncanny_judge.build_prompt(
        {"title": "x", "hook": "h", "logline": "l"})
    assert "none written yet" in payload


def test_shots_without_a_prompt_are_skipped():
    concept = {"title": "x", "shots": [
        {"n": 1, "prompt": ""}, {"n": 2, "prompt": "the real one"}]}
    payload = uncanny_judge.build_prompt(concept)
    assert "Shot 2" in payload and "Shot 1" not in payload
