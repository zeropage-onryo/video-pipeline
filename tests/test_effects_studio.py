"""Effects from the studio (item 3 of docs/tasks/task-studio-agent.md).

src/effects.py was reachable only from the Claude Desktop connector. The
studio's own door is three routes and two brain tools; these hold what
makes it safe: the gallery is a projection of the table and shows credits
only, a run happens at the price the card showed or not at all, a source
is the account's own, and the brain names an effect but never what it
acts on.
"""
import json
import time
import types as pytypes

import pytest
from fastapi.testclient import TestClient

from app import api, auth, jobs
from app.main import app
from src import (
    accounts,
    creative_guide,
    effects,
    fal,
    gemini_utils,
    generative,
    guide_tools,
    ledger,
    mcp_server,
    render_assets,
)

ACCOUNT = 42


@pytest.fixture
def client(pg, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", pg)
    generative.init(pg)
    render_assets.init(pg)
    ledger.init(pg)
    monkeypatch.setattr(auth, "current_user", lambda request: {"id": "fx-user"})
    monkeypatch.setattr(auth, "current_account", lambda request: {"slug": "zeropage"})
    monkeypatch.setattr(ledger, "credit_exempt", lambda account_id, dsn=None: False)
    monkeypatch.setattr(fal, "has_key", lambda account_id=None: True)
    app.dependency_overrides[auth.current_account_id] = lambda: ACCOUNT
    yield TestClient(app)
    app.dependency_overrides.pop(auth.current_account_id, None)


def _wait(client, job_id):
    for _ in range(300):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(.01)
    raise AssertionError("job never finished")


# ---------- the gallery ----------

def test_the_gallery_is_the_table_in_credits_and_names_no_price_in_dollars(client):
    body = client.get("/api/effects").json()
    assert [e["id"] for e in body["items"]] == list(effects.EFFECT_NAMES)
    assert [c["id"] for c in body["categories"]] == list(effects.CATEGORIES)
    assert body["ready"] is True and body["exempt"] is False
    assert "$" not in json.dumps(body) and "fal.ai" not in json.dumps(body)
    by = {e["id"]: e for e in body["items"]}
    # every effect has words a customer reads, written for them
    assert set(api.EFFECT_BLURBS) == set(effects.EFFECT_NAMES)
    assert all(by[n]["blurb"] == api.EFFECT_BLURBS[n] for n in by)
    # a fixed price is shown in credits, at the default options
    still = by["remove-background"]
    assert still["credits"] == ledger.charge_credits(effects.quote_usd("remove-background", {}))
    kling = by["kling-effect"]
    assert kling["credits"] == ledger.charge_credits(0.056 * 5)
    assert len(kling["options"]["effect_scene"]["values"]) == len(effects.KLING_EFFECTS)
    assert kling["options"]["effect_scene"]["required"] is True
    # a price that depends on the clip is not guessed
    assert by["upscale"]["credits"] is None and by["add-sound"]["credits"] is None


# ---------- the price ----------

def test_a_quote_is_checked_like_a_run_and_spends_nothing(client, monkeypatch):
    monkeypatch.setattr(effects, "run", lambda *a, **k: pytest.fail("a quote ran the effect"))
    monkeypatch.setattr(fal, "as_image_url", lambda *a, **k: pytest.fail("a quote uploaded"))
    ok = client.post("/api/effects/quote", json={
        "effect": "pixverse-effect", "sources": ["/refs/can.jpg"],
        "options": {"effect": effects.PIXVERSE_EFFECTS[0], "resolution": "1080p"}})
    assert ok.status_code == 200
    assert ok.json()["credits"] == ledger.charge_credits(effects.PIXVERSE_5S_USD["1080p"])
    assert ok.json()["charged"] is True and ok.json()["output"] == "video"

    def refused(**body):
        r = client.post("/api/effects/quote", json=body)
        assert r.status_code == 400 and r.json()["error"]["code"] == "bad_effect"
        return r.json()["error"]["message"]

    assert "must be one of" in refused(effect="lip-sync", sources=["/refs/a.jpg"])
    assert "needs `effect_scene`" in refused(effect="kling-effect", sources=["/refs/a.jpg"])
    assert "is not one of" in refused(effect="kling-effect", sources=["/refs/a.jpg"],
                                      options={"effect_scene": "melt-it"})
    assert "takes no prompt" in refused(effect="remove-background", sources=["/refs/a.jpg"],
                                        prompt="cut it out")
    assert "needs a prompt" in refused(effect="nano-banana-edit", sources=["/refs/a.jpg"])
    assert "takes exactly 1" in refused(effect="remove-background", sources=[])
    # a clip effect takes a clip BY ID: an address is never a source
    assert "URLs are never taken" in refused(effect="upscale", sources=["https://x.y/a.mp4"])
    assert "no render 999" in refused(effect="upscale", sources=["gen:999"])
    # an unknown field is refused, not dropped
    assert client.post("/api/effects/quote", json={"effect": "upscale", "url": "x"}).status_code == 422


def _clip(pg, account_id, n=[0]):
    """A clip on this account's Assets wall; its id is what `gen:<id>` names."""
    n[0] += 1
    return render_assets.record(
        generation_id=n[0], tool="fal", model="ltx2.3", media_kind="video", prompt="a clip",
        media_url=f"https://cdn.example/clip-{n[0]}.mp4", dsn=pg, account_id=account_id)["id"]


def test_a_clip_is_priced_off_its_measured_length_and_only_the_accounts_own(client, pg, monkeypatch):
    accounts.init(pg)
    me = accounts.upsert_account("fx-mine", "Mine", "#fff", dsn=pg)
    them = accounts.upsert_account("fx-theirs", "Theirs", "#fff", dsn=pg)
    app.dependency_overrides[auth.current_account_id] = lambda: me
    mine = _clip(pg, account_id=me)
    theirs = _clip(pg, account_id=them)
    monkeypatch.setattr(effects, "probe_video", lambda target: {
        "seconds": 8.0, "width": 720, "height": 1280, "fps": 24.0})
    r = client.post("/api/effects/quote", json={
        "effect": "add-sound", "sources": [f"gen:{mine}"], "prompt": "rain on a tin roof"})
    assert r.status_code == 200, r.text
    assert r.json()["clip"] == {"seconds": 8.0, "width": 720, "height": 1280}
    assert r.json()["credits"] == ledger.charge_credits(effects.quote_usd(
        "add-sound", {}, {"seconds": 8.0, "width": 720, "height": 1280, "fps": 24.0}))
    other = client.post("/api/effects/quote", json={
        "effect": "add-sound", "sources": [f"gen:{theirs}"], "prompt": "rain"})
    assert other.status_code == 400 and "no render" in other.json()["error"]["message"]
    # too long for the effect: refused before any price
    monkeypatch.setattr(effects, "probe_video", lambda target: {
        "seconds": 31.0, "width": 720, "height": 1280, "fps": 24.0})
    long = client.post("/api/effects/quote", json={
        "effect": "add-sound", "sources": [f"gen:{mine}"], "prompt": "rain"})
    assert long.status_code == 400 and "up to 30s" in long.json()["error"]["message"]


# ---------- the run ----------

def test_a_run_happens_at_the_price_the_card_showed_or_not_at_all(client, monkeypatch):
    ran = []
    monkeypatch.setattr(api, "_photo_bytes", lambda url: b"jpeg-bytes")
    monkeypatch.setattr(api, "_to_jpeg", lambda raw: raw)
    monkeypatch.setattr(fal, "as_image_url", lambda value, **k: "https://bucket.example/src.jpg")

    def run(effect, urls, prompt, options, **kw):
        ran.append({"effect": effect, "urls": urls, "prompt": prompt, "options": options, **kw})
        return {"ok": True, "media_url": "https://bucket.example/out.png", "asset_id": 9,
                "generation_id": 3}

    monkeypatch.setattr(effects, "run", run)
    body = {"effect": "nano-banana-edit", "sources": ["/refs/can.jpg"],
            "prompt": "make the label blue"}
    price = client.post("/api/effects/quote", json=body).json()["credits"]

    assert client.post("/api/effects/run", json=body).json()["error"]["code"] == "missing_price"
    stale = client.post("/api/effects/run", json={**body, "expect_credits": price + 1})
    assert stale.status_code == 409 and stale.json()["credits"] == price
    assert ran == []                                     # neither spent anything

    started = client.post("/api/effects/run", json={**body, "expect_credits": price})
    assert started.status_code == 200 and started.json()["credits"] == price
    job = _wait(client, started.json()["job_id"])
    assert job["status"] == "done", job
    assert job["output"] == "https://bucket.example/out.png"
    assert job["asset"] == "gen:9" and job["media"] == "image"
    assert job["kind"] == "effect"       # the job's own kind is not written over
    (call,) = ran
    assert call["urls"] == ["https://bucket.example/src.jpg"]
    assert call["usd"] == effects.quote_usd("nano-banana-edit", call["options"])
    assert call["account_id"] == ACCOUNT and call["source"] == "composer"
    assert call["sources"] == ["/refs/can.jpg"] and call["prompt"] == "make the label blue"


def test_a_render_on_this_machines_disk_is_read_by_its_own_guarded_reader(client, monkeypatch):
    """A still a composer result points at as /renders/... (no bucket on a
    dev box): opened only through imagery.render_bytes, which refuses any
    path outside data/renders."""
    from src import imagery
    seen = []
    monkeypatch.setattr(api, "_photo_bytes", lambda url: None)
    monkeypatch.setattr(imagery, "render_bytes", lambda path: seen.append(path) or b"png")
    monkeypatch.setattr(api, "_to_jpeg", lambda raw: raw)
    monkeypatch.setattr(fal, "as_image_url", lambda value, **k: "https://bucket.example/s.jpg")
    monkeypatch.setattr(effects, "run", lambda *a, **k: {"ok": True, "media_url": "/renders/o.png",
                                                         "asset_id": 4})
    for ref, read in (("/renders/nano/still.png", True), ("/etc/passwd", False)):
        seen.clear()
        body = {"effect": "remove-background", "sources": [ref]}
        price = client.post("/api/effects/quote", json=body).json()["credits"]
        job = _wait(client, client.post("/api/effects/run",
                                        json={**body, "expect_credits": price}).json()["job_id"])
        assert (job["status"] == "done") is read and bool(seen) is read


def test_a_source_that_cannot_be_read_fails_the_job_before_any_spend(client, monkeypatch):
    monkeypatch.setattr(api, "_photo_bytes", lambda url: None)
    monkeypatch.setattr(effects, "run", lambda *a, **k: pytest.fail("ran against nothing"))
    body = {"effect": "remove-background", "sources": ["/refs/gone.jpg"]}
    price = client.post("/api/effects/quote", json=body).json()["credits"]
    job = _wait(client, client.post("/api/effects/run",
                                    json={**body, "expect_credits": price}).json()["job_id"])
    assert job["status"] == "failed" and "could not be read" in job["error"]


def test_a_failed_effect_is_said_plainly_and_nothing_names_the_vendor(client, monkeypatch):
    monkeypatch.setattr(api, "_photo_bytes", lambda url: b"x")
    monkeypatch.setattr(api, "_to_jpeg", lambda raw: raw)
    monkeypatch.setattr(fal, "as_image_url", lambda value, **k: "https://bucket.example/s.jpg")
    monkeypatch.setattr(effects, "run", lambda *a, **k: {
        "ok": False, "error": 'HTTP Error 403: Forbidden -- {"detail":"User is locked. '
                              'Reason: Exhausted balance. Top up at fal.ai/dashboard/billing."}'})
    body = {"effect": "remove-background", "sources": ["/refs/can.jpg"]}
    price = client.post("/api/effects/quote", json=body).json()["credits"]
    job = _wait(client, client.post("/api/effects/run",
                                    json={**body, "expect_credits": price}).json()["job_id"])
    assert job["status"] == "failed"
    assert job["error"] == ("The effect was not made: the effects service turned the studio "
                            "away. That is ours to fix, not yours. Nothing was charged.")


def test_effects_are_refused_plainly_when_the_server_has_no_key(client, monkeypatch):
    monkeypatch.setattr(fal, "has_key", lambda account_id=None: False)
    assert client.get("/api/effects").json()["ready"] is False
    body = {"effect": "remove-background", "sources": ["/refs/can.jpg"]}
    price = client.post("/api/effects/quote", json=body).json()["credits"]
    r = client.post("/api/effects/run", json={**body, "expect_credits": price})
    assert r.status_code == 503 and r.json()["error"]["code"] == "effects_unavailable"


def test_the_studio_door_shares_the_connectors_checks():
    """One table, two doors: the same functions decide what is legal."""
    assert api._effect_request.__code__.co_names.count("check_options") == 1
    for name in ("spec", "check_options", "check_prompt", "check_sources", "quote_usd"):
        assert name in api._effect_request.__code__.co_names
        assert name in mcp_server.run_effect.__code__.co_names


# ---------- the brain ----------

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
        seen.append({"contents": contents, **kwargs})
        r = responses.pop(0)
        return r if kwargs.get("raw") else r.text

    monkeypatch.setattr(gemini_utils, "generate_with_retry", generate)
    reply = creative_guide.respond(
        creative_guide.Conversation(messages=[{"role": "user", "content": "give it a camera move"}]),
        client=object(), brand="zeropage", grounding={}, tools=specs, run_tool=run_tool,
        output="image")
    return reply, seen, specs


def test_the_effects_tools_are_the_composers_and_never_the_pills(monkeypatch):
    monkeypatch.setattr(guide_tools, "available", lambda: False)
    composer = {s["name"] for s in guide_tools.session(local=True, maker=True)[0]}
    pill = {s["name"] for s in guide_tools.session(local=True, maker=True, makes=("make_image",))[0]}
    assert {"apply_effect", "list_effects"} <= composer
    assert not {"apply_effect", "list_effects"} & pill
    assert guide_tools.is_make("apply_effect") and guide_tools.is_write("apply_effect")
    assert not guide_tools.is_write("list_effects")
    with pytest.raises(guide_tools.Refused, match="made by the studio"):
        guide_tools.run("apply_effect", {"effect": "remove-background"})
    with_fx = creative_guide.instructions("zeropage", with_tools=True, maker=True, with_effects=True)
    assert "EFFECTS CHANGE WHAT ALREADY EXISTS" in with_fx
    assert "EFFECTS CHANGE" not in creative_guide.instructions("zeropage", with_tools=True, maker=True)


def test_the_brain_reads_the_table_then_proposes_and_nothing_runs(monkeypatch):
    move = effects.CAMERA_MOVES[0]
    reply, seen, _ = _turn(monkeypatch, [
        _Resp(calls=[("list_effects", {"effect": "camera-move"})]),
        _Resp(calls=[("apply_effect", {"effect": "camera-move", "prompt": "the can turns to camera",
                                       "options": {"camera_movement": move}})]),
    ])
    # the read handed back every legal move, and no price
    # (the model's own turn is appended after it: the result is one back)
    listed = seen[1]["contents"][-2].parts[0].function_response.response["result"]
    assert move in listed and "$" not in listed and "fal.ai" not in listed
    proposal = reply["proposal"]
    assert proposal["tool"] == "apply_effect" and proposal["label"] == "Apply this effect"
    assert proposal["args"]["options"]["camera_movement"] == move
    assert proposal["args"]["options"]["resolution"] == "720p"      # the table's default, filled in
    assert set(proposal["args"]) == {"effect", "options", "prompt"}  # never a source
    assert reply["message"].startswith("Camera move") and "the can turns to camera" in reply["message"]
    assert reply["tool_runs"] == [{"tool": "list_effects", "args": {"effect": "camera-move"}, "ok": True}]


def test_a_template_the_brain_made_up_goes_back_to_it_with_the_real_names(monkeypatch):
    real = effects.KLING_EFFECTS[1]
    reply, seen, _ = _turn(monkeypatch, [
        _Resp(calls=[("apply_effect", {"effect": "kling-effect", "options": {"effect_scene": "melt-it"}})]),
        _Resp(calls=[("apply_effect", {"effect": "kling-effect", "options": {"effect_scene": real}})]),
    ])
    told = seen[1]["contents"][-2].parts[0].function_response.response["result"]
    assert told.startswith("error: ") and "is not one of" in told
    assert reply["proposal"]["args"]["options"]["effect_scene"] == real
    assert reply["tool_runs"][0] == {"tool": "apply_effect", "ok": False,
                                     "args": {"effect": "kling-effect",
                                              "options": {"effect_scene": "melt-it"}}}


def test_the_act_route_never_runs_an_effect(client):
    r = client.post("/api/creative-guide/act", headers={"X-ZPF-Model-Connection": "1"},
                    json={"tool": "apply_effect", "args": {"effect": "remove-background"}})
    assert r.status_code == 400 and r.json()["error"]["code"] == "bad_tool"
    assert jobs  # the job registry is the only place an effect runs
