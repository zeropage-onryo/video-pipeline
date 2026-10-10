"""A plan is several makes proposed as one answer (src/make_plan.py, 2026-10-10).

It is still ONE write that ends the turn unrun; these hold the rail every
plan passes before a card may draw it: each step is checked by its own
tool's check, a step that acts on a scene needs that scene before it, and
nothing in a plan is a URL.
"""
import json
import types as pytypes

import pytest
from fastapi.testclient import TestClient

from app import auth
from app.main import app
from src import creative_guide, gemini_utils, guide_tools
from src import make_plan as plans

STILL = {"do": "image", "prompt": "the exact can on wet steel", "aspect": "4:5",
         "why": "the hero frame"}
SCENE = {"do": "scene", "prompt": "She lifts the can off the counter.", "seconds": 10, "shots": 3,
         "uses": [1]}


def test_a_plan_is_its_steps_each_through_its_own_tools_check():
    clean = plans.check({"summary": "A 10s ad for the can", "steps": [
        STILL, SCENE, {"do": "keyframes", "scene": 2}, {"do": "queue"}]})
    assert clean["summary"] == "A 10s ad for the can"
    assert [s["n"] for s in clean["steps"]] == [1, 2, 3, 4]
    assert [s["do"] for s in clean["steps"]] == ["image", "scene", "keyframes", "queue"]
    still, scene, frames, queue = clean["steps"]
    # exactly what make_image / make_video would have been handed alone
    assert still["args"] == guide_tools.check_args("make_image", {
        "prompt": STILL["prompt"], "aspect": "4:5"})
    assert scene["args"]["seconds"] == 10 and scene["args"]["shots"] == 3
    assert still["why"] == "the hero frame" and scene["uses"] == [1]
    # keyframes named its scene; the queue found the only one there is
    assert frames["scene"] == 2 and queue["scene"] == 2
    assert frames["args"] == {} and queue["uses"] == []


def test_a_shot_count_is_said_in_the_words_the_scene_writer_reads():
    """/scenes/run takes an idea and no count, so the count rides in it --
    in the phrasing timeline.requested_shots is strict about."""
    from src import timeline
    idea = plans.check({"steps": [STILL, SCENE]})["steps"][1]["args"]["prompt"]
    assert idea.endswith("Cut it into exactly 3 shots.")
    assert timeline.requested_shots(idea) == 3
    one = plans.scene_idea({"prompt": "He climbs the stairs with the cake.", "shots": 1})
    assert timeline.one_take_requested(one)
    # words that already carry a count, or timed windows, are left alone
    said = "A 3-shot scene: she lifts the can."
    assert plans.scene_idea({"prompt": said, "shots": 3}) == said
    timed = "(0-4s) Wide on the counter. (4-10s) Close on the tab."
    assert plans.scene_idea({"prompt": timed, "shots": 2}) == timed
    assert plans.scene_idea({"prompt": "She waits."}) == "She waits."


@pytest.mark.parametrize("args, why", [
    ({}, "needs the steps"),
    ({"steps": []}, "needs the steps"),
    ({"steps": ["draw it"]}, "is not a step"),
    ({"steps": [STILL, {"do": "render"}]}, "not something a plan can do"),
    ({"steps": [STILL, {"do": "image", "prompt": ""}]}, "step 2"),
    ({"steps": [STILL, {"do": "image", "prompt": "see https://x.y/can.jpg"}]}, "step 2"),
    ({"steps": [STILL, {"do": "keep", "candidate_ids": []}]}, "step 2"),
    ({"steps": [STILL, {"do": "sheet", "name": ""}]}, "step 2"),
    ({"steps": [STILL, {"do": "keyframes"}]}, "needs a scene step before it"),
    ({"steps": [{"do": "queue", "scene": 2}, SCENE]}, "needs a scene step before it"),
    ({"steps": [SCENE, dict(SCENE), {"do": "queue"}]}, "needs a scene step before it"),
    ({"steps": [STILL, dict(SCENE, why="like www.example.com/ad")]}, "does not take a URL"),
    ({"summary": "from https://x.y", "steps": [STILL, SCENE]}, "does not take a URL"),
    ({"steps": [STILL] * (plans.MAX_STEPS + 1)}, "at most"),
])
def test_what_is_broken_refuses_the_plan(args, why):
    with pytest.raises(guide_tools.Refused, match=why):
        plans.check(args)


def test_a_reference_that_is_not_there_is_dropped_never_the_step():
    clean = plans.check({"steps": [
        dict(SCENE, uses=[1]),                       # nothing before it
        STILL,
        dict(SCENE, uses=[2, 1, 9, "2", True]),      # step 1 is a scene, 9 is not there
    ]})
    assert [s["uses"] for s in clean["steps"]] == [[], [], [2]]
    # anything a step's tool does not take is not carried
    assert "uses" not in clean["steps"][1]["args"] and "why" not in clean["steps"][1]["args"]


def test_a_plan_with_no_summary_is_called_by_its_steps():
    clean = plans.check({"steps": [STILL, SCENE, {"do": "keyframes"}]})
    assert clean["summary"] == "A plan in 3 steps: a still, then the scene, then its keyframes."
    assert len(plans.check({"summary": "x" * 900, "steps": [STILL, SCENE]})["summary"]) == plans.MAX_SUMMARY


def test_a_plan_of_one_step_is_that_steps_own_tool():
    one = plans.check({"steps": [STILL]})
    assert plans.collapse(one) == ("make_image", one["steps"][0]["args"])
    assert plans.collapse(plans.check({"steps": [STILL, SCENE]})) is None
    sheet = plans.check({"steps": [{"do": "sheet", "name": "Ana"}]})
    assert plans.collapse(sheet)[0] == guide_tools.SHEET_TOOL


def test_the_spec_offers_exactly_what_check_takes():
    step = plans.SPEC["input_schema"]["properties"]["steps"]["items"]["properties"]
    assert step["do"]["enum"] == list(plans.DOES)
    taken = {k for keys in plans.ARG_KEYS.values() for k in keys} | {"do", "scene", "uses", "why"}
    assert set(step) == taken
    assert plans.SPEC["write"] is True and plans.SPEC["name"] == plans.TOOL
    # every step kind is said in the description the model reads
    assert all(kind in plans.SPEC["description"] for kind in plans.DOES)


# ---------- the turn ----------

class _Resp:
    def __init__(self, text=None, calls=()):
        self.text = text
        self.function_calls = [pytypes.SimpleNamespace(name=n, args=a) for n, a in calls]
        self.candidates = [pytypes.SimpleNamespace(
            content=pytypes.SimpleNamespace(role="model", parts=[]))]


def _turn(monkeypatch, responses, *, makes=None):
    monkeypatch.setattr(guide_tools, "available", lambda: False)
    specs, run_tool = guide_tools.session(local=True, maker=True, makes=makes)
    seen = []

    def generate(client, model, contents, **kwargs):
        seen.append(kwargs)
        r = responses.pop(0)
        return r if kwargs.get("raw") else r.text

    monkeypatch.setattr(gemini_utils, "generate_with_retry", generate)
    reply = creative_guide.respond(
        creative_guide.Conversation(messages=[{"role": "user", "content": "make an ad from this can"}]),
        client=object(), brand="zeropage", grounding={}, tools=specs, run_tool=run_tool,
        output="video")
    return reply, seen, specs


def test_the_plan_is_offered_to_the_composer_and_never_to_the_pill(monkeypatch):
    monkeypatch.setattr(guide_tools, "available", lambda: False)
    composer, _ = guide_tools.session(local=True, maker=True)
    pill, _ = guide_tools.session(local=True, maker=True, makes=("make_image",))
    talk, _ = guide_tools.session(local=True)
    assert plans.TOOL in {s["name"] for s in composer}
    assert plans.TOOL not in {s["name"] for s in pill}
    assert plans.TOOL not in {s["name"] for s in talk}
    assert guide_tools.is_make(plans.TOOL) and guide_tools.is_write(plans.TOOL)
    # the words about plans ride only where the tool does
    with_plan = creative_guide.instructions("zeropage", with_tools=True, maker=True, with_plan=True)
    without = creative_guide.instructions("zeropage", with_tools=True, maker=True)
    assert "A PLAN IS FOR WORK" in with_plan and "A PLAN IS FOR WORK" not in without


def test_a_plan_call_ends_the_turn_as_one_proposal_and_runs_nothing(monkeypatch):
    call = _Resp(calls=[(plans.TOOL, {"summary": "A 10s ad for the can", "steps": [
        STILL, SCENE, {"do": "keyframes"}, {"do": "queue"}]})])
    reply, seen, _ = _turn(monkeypatch, [call])
    assert len(seen) == 1                                   # the turn ended on the call
    proposal = reply["proposal"]
    assert proposal["tool"] == plans.TOOL and proposal["label"] == plans.LABEL
    assert [s["do"] for s in proposal["args"]["steps"]] == ["image", "scene", "keyframes", "queue"]
    assert reply["message"] == "A 10s ad for the can"       # the line above the card, never JSON
    assert "A PLAN IS FOR WORK" in seen[0]["config"].system_instruction


def test_a_plan_of_one_step_comes_back_as_that_make(monkeypatch):
    reply, _, _ = _turn(monkeypatch, [_Resp(calls=[(plans.TOOL, {"steps": [STILL]})])])
    assert reply["proposal"]["tool"] == "make_image"
    assert reply["proposal"]["label"] == guide_tools.WRITE_LABELS["make_image"]
    assert reply["message"] == STILL["prompt"]              # a make's line is its prompt


def test_a_broken_plan_is_refused_not_carried(monkeypatch):
    with pytest.raises(guide_tools.Refused, match="needs a scene step"):
        _turn(monkeypatch, [_Resp(calls=[(plans.TOOL, {"steps": [STILL, {"do": "queue"}]})])])


def test_nothing_on_the_server_runs_a_plan(monkeypatch):
    """The studio runs a plan's steps through each step's own door; a
    server that ran one off a POST body would be a spend door with no card."""
    with pytest.raises(guide_tools.Refused, match="made by the studio"):
        guide_tools.run(plans.TOOL, {"steps": [STILL, SCENE]})
    monkeypatch.setattr(auth, "current_user", lambda request: {"id": "guide-user"})
    monkeypatch.setattr(auth, "current_account", lambda request: {"slug": "zeropage"})
    app.dependency_overrides[auth.current_account_id] = lambda: 42
    try:
        client = TestClient(app, headers={"X-ZPF-Model-Connection": "1"})
        r = client.post("/api/creative-guide/act", json={
            "tool": plans.TOOL, "args": {"steps": [STILL, SCENE]}})
        assert r.status_code == 400 and r.json()["error"]["code"] == "bad_tool"
    finally:
        app.dependency_overrides.pop(auth.current_account_id, None)
    assert json.dumps(plans.check({"steps": [STILL, SCENE]}))    # a plan is plain data
