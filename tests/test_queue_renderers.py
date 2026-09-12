"""The Queue's approve button, on four vendors instead of one.

Until 2026-09-08 `queue_approve` named runway in three places -- the key
check, the render call and the button's price -- so the ONE surface in
this project that spends money could reach exactly one of four working
adapters. That was never a policy about which vendor may spend: Runway
was simply the only module that had grown a `generate_for_shot`, and the
route was written around the function that existed.

The cost of it was two doors disagreeing. A concept shootgen planned for
KLING rendered on Kling at 3:30am (orchestrator.generate_render's
connectors dict) and on Runway if Michael approved the same row by hand,
with nothing anywhere saying so. These tests are mostly about that
disagreement being gone: the card, the route and the graph all resolve a
shot's `tool` through providers.platform_default, or none of them do.
"""
import time

import pytest
from fastapi.testclient import TestClient

from app.main import app
from src import fal, preprod, providers, runway, veo

client = TestClient(app)

SEED_REF = "/refs/seed.jpg"


@pytest.fixture(autouse=True)
def signed_in(monkeypatch):
    from app import auth
    stub = {"id": 1, "email": "test@example.com", "display_name": "Test"}
    monkeypatch.setattr(auth, "current_user", lambda request: stub)
    monkeypatch.setattr(
        auth, "current_account",
        lambda request, user=None: {"slug": "zeropage", "display_name": "ZERO PAGE"})


@pytest.fixture
def tmp_db(pg, monkeypatch):
    preprod.init(pg)
    monkeypatch.setenv("DATABASE_URL", pg)
    return pg


def wait_for_job(job_id, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed", "cancelled"):
            return job
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} never finished")


def a_queued_scene(path, tool="RUNWAY", refs=None):
    """One grounded, parked scene planned for `tool` -- the row the Queue
    is looking at. Parked rather than picked because that is the case
    approving also has to PICK, and it is the one the chain produces."""
    concept_id = preprod.save_concept(
        {"title": f"scene for {tool}", "hook": "", "logline": "",
         "shots": [{"n": 1, "type": "BROLL", "source": "AI", "tool": tool,
                    "desc": "d", "prompt": "a long enough prompt to render",
                    "refs": [SEED_REF] if refs is None else list(refs)}]},
        brand="zeropage", prompt_template="T", dsn=path, account_id=None)
    preprod.set_shot_parked(concept_id, 1, "keyframe rendered",
                            dsn=path, account_id=None)
    return concept_id


def capture(monkeypatch, module):
    """Stand in for one adapter's generate_for_shot and record the call."""
    seen = {}

    def fake(concept_id, shot_n, **kwargs):
        seen["args"] = (concept_id, shot_n)
        seen["kwargs"] = kwargs
        return {"ok": True, "media_url": "https://x/clip.mp4",
                "generation_id": 1, "error": None}

    monkeypatch.setattr(module, "generate_for_shot", fake)
    monkeypatch.setattr(module, "has_key", lambda account_id=None: True)
    return seen


# --- the plan is the default -------------------------------------------------

def test_an_empty_approve_renders_on_the_tool_the_shot_was_planned_for(tmp_db, monkeypatch):
    """THE BUG THIS WHOLE CHANGE IS ABOUT. A scene written for Kling used
    to be rendered on Runway by this button, silently, because the route
    named one vendor. An empty body is still the old call -- it just
    resolves to the plan now instead of to a constant."""
    on_fal = capture(monkeypatch, fal)
    on_runway = capture(monkeypatch, runway)

    scene = a_queued_scene(tmp_db, tool="KLING")
    res = client.post(f"/api/queue/{scene}/approve")
    assert res.status_code == 200, res.text
    assert wait_for_job(res.json()["job_id"])["status"] == "done"

    assert on_fal["args"] == (scene, 1)
    assert on_fal["kwargs"]["model"] == fal.PLATFORM_MODELS["kling"]
    assert "args" not in on_runway          # the point: Runway was not called
    # and the response says what it spent on, rather than leaving the
    # card to guess from a job id
    assert res.json()["render"]["provider"] == "fal"


def test_a_shot_planned_for_runway_still_goes_to_runway(tmp_db, monkeypatch):
    on_runway = capture(monkeypatch, runway)
    capture(monkeypatch, fal)
    scene = a_queued_scene(tmp_db, tool="RUNWAY")
    res = client.post(f"/api/queue/{scene}/approve", json={})
    assert wait_for_job(res.json()["job_id"])["status"] == "done"
    assert on_runway["kwargs"]["model"] == runway.DEFAULT_MODEL


def test_a_tool_no_adapter_renders_falls_back_rather_than_failing(tmp_db, monkeypatch):
    """shot.PLATFORMS can name a tool the registry has no adapter for.
    That is a reason to offer the default renderer, not to refuse to
    render -- the prompt is written and the person is standing at the
    spend gate."""
    on_runway = capture(monkeypatch, runway)
    scene = a_queued_scene(tmp_db, tool="SOMETHING_ELSE")
    res = client.post(f"/api/queue/{scene}/approve", json={})
    assert wait_for_job(res.json()["job_id"])["status"] == "done"
    assert on_runway["args"] == (scene, 1)


# --- the pick itself ---------------------------------------------------------

def test_the_picked_model_length_and_frame_reach_the_adapter(tmp_db, monkeypatch):
    seen = capture(monkeypatch, fal)
    scene = a_queued_scene(tmp_db, tool="KLING")
    res = client.post(f"/api/queue/{scene}/approve", json={
        "provider": "fal", "model": "seedance2", "duration": 9, "frame": "1080p"})
    assert wait_for_job(res.json()["job_id"])["status"] == "done"
    assert seen["kwargs"]["model"] == "seedance2"
    assert seen["kwargs"]["duration"] == 9
    # every fal model takes `resolution`...
    assert seen["kwargs"]["resolution"] == "1080p"


def test_runway_is_handed_a_ratio_where_the_others_are_handed_a_resolution(tmp_db, monkeypatch):
    """One axis, two parameter names. Runway takes a frame SIZE and calls
    it `ratio`; fal, Higgsfield and Veo take a resolution tier. Passing
    the wrong keyword is a TypeError inside a job, at the one moment
    somebody is watching a spinner."""
    seen = capture(monkeypatch, runway)
    scene = a_queued_scene(tmp_db)
    res = client.post(f"/api/queue/{scene}/approve", json={
        "provider": "runway", "model": "gen4_turbo",
        "duration": 10, "frame": "1280:720"})
    assert wait_for_job(res.json()["job_id"])["status"] == "done"
    assert seen["kwargs"]["ratio"] == "1280:720"
    assert seen["kwargs"]["duration"] == 10
    assert "resolution" not in seen["kwargs"]


def test_the_estimate_comes_back_with_the_job(tmp_db, monkeypatch):
    capture(monkeypatch, fal)
    scene = a_queued_scene(tmp_db, tool="LTX")
    body = client.post(f"/api/queue/{scene}/approve", json={
        "provider": "fal", "model": "ltx2.3", "duration": 10, "frame": "1080p"}).json()
    assert body["render"] == {
        "provider": "fal", "model": "ltx2.3", "duration": 10, "frame": "1080p",
        "estimate_usd": fal.estimate_cost(1, model="ltx2.3", duration=10,
                                          resolution="1080p")}


# --- what is refused, and before what ----------------------------------------

def test_a_length_the_model_cannot_render_is_refused_before_it_spends(tmp_db, monkeypatch):
    seen = capture(monkeypatch, runway)
    scene = a_queued_scene(tmp_db)
    res = client.post(f"/api/queue/{scene}/approve",
                      json={"provider": "runway", "duration": 7})
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "bad_render_choice"
    assert seen == {}          # the point: nothing was billed


def test_no_key_for_the_picked_renderer_says_which_one(tmp_db, monkeypatch):
    """The old message was "RUNWAYML_API_SECRET is not set" whatever you
    had picked, which on a four-vendor picker is a sentence about the
    wrong vendor."""
    capture(monkeypatch, runway)
    monkeypatch.setattr(veo, "has_key", lambda account_id=None: False)
    scene = a_queued_scene(tmp_db)
    res = client.post(f"/api/queue/{scene}/approve", json={"provider": "veo"})
    assert res.status_code == 503
    assert res.json()["error"]["code"] == "renderer_unavailable"
    assert "Veo" in res.json()["error"]["message"]


def test_an_ungrounded_scene_is_refused_on_every_renderer(tmp_db, monkeypatch):
    """Picking a vendor does not move the queue's own doors. An
    ungrounded scene is refused at the spend gate on fal exactly as it is
    on Runway -- reference_gate reads `refs`, and no vendor makes a scene
    with no photographs behind it grounded.

    ("ungrounded" in the name is conftest's opt-in to
    ZEROPAGE_REQUIRE_REFS, the same way the queue's own gate test does
    it -- the suite default is off so eighty unrelated tests are not
    assertions about reference images.)"""
    seen = capture(monkeypatch, fal)
    blind = a_queued_scene(tmp_db, tool="KLING", refs=[])
    res = client.post(f"/api/queue/{blind}/approve", json={"provider": "fal"})
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "no_reference"
    assert seen == {}


def test_approving_still_stamps_the_pick_before_the_spend(tmp_db, monkeypatch):
    capture(monkeypatch, fal)
    scene = a_queued_scene(tmp_db, tool="WAN")
    client.post(f"/api/queue/{scene}/approve", json={"provider": "fal"})
    assert preprod.get_concept(scene, dsn=tmp_db, account_id=None)["picked"] is True


# --- what the card is handed -------------------------------------------------

def test_the_queue_lists_every_renderer_and_the_cards_own_default(tmp_db, monkeypatch):
    a_queued_scene(tmp_db, tool="SEEDANCE")
    data = client.get("/api/queue/pending?brand=zeropage").json()

    assert set(data["renderers"]) == set(providers.VIDEO_PROVIDERS)
    for entry in data["renderers"].values():
        assert {"available", "spend_ok", "spend_env", "models", "frame_axis"} <= set(entry)

    card = data["items"][0]
    assert card["tool"] == "SEEDANCE"
    # resolved server-side through the same function the route uses, so
    # what the card offers first and what an empty approve would spend on
    # cannot come apart
    assert card["render_default"] == {
        "provider": "fal", "model": fal.PLATFORM_MODELS["seedance"]}
    # and the single-vendor shape an older client may still read is
    # deliberately still there
    assert "runway" in data
