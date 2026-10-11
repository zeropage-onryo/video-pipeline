"""Draft, then finish (item 5 of docs/tasks/task-studio-agent.md).

A draft is the Queue's ordinary approve at the picked model's cheapest
resolution; finishing is the upscale effect run on the draft itself, with
the finished clip put on the shot in the draft's place. These hold the
rules that make that honest: a draft is offered only where it is really
cheaper, a clip is known as a draft from what its own row says, and a
finish can only ever land on the shot the draft is on right now.
"""
import time

import pytest
from fastapi.testclient import TestClient

from app import api, auth
from app.main import app
from src import (
    accounts,
    drafts,
    effects,
    fal,
    generative,
    ledger,
    preprod,
    providers,
    render_assets,
    storage,
)
from src.cut import store as cut_store

WHO = {}


# ---------- which resolution is a draft ----------

def test_a_draft_is_the_cheapest_tier_and_only_where_it_is_really_cheaper():
    for name, spec in fal.VIDEO_MODELS.items():
        draft = fal.draft_resolution(name)
        prices, default = spec["prices"], spec["default_resolution"]
        if draft is None:
            # nothing in the table undercuts what it renders at by default
            assert min(prices.values()) >= prices[default], name
            continue
        assert draft in spec["resolutions"] and draft != default
        assert prices[draft] == min(prices.values())
        assert prices[draft] < prices[default], name
        assert fal.is_draft(name, draft) and not fal.is_draft(name, default)
    # the two that have one today, by the dated table
    assert fal.draft_resolution("wan3") == "480p"
    assert fal.draft_resolution("seedance2.5") == "480p"
    # a lower tier at the SAME price is not a draft: it saves nothing
    assert fal.draft_resolution("seedance2") is None
    # one flat rate, a default that is already the floor, an unknown model
    for none in ("kling3-turbo-pro", "ltx2.3", "ltx2.5-fast", "veo3.1", "no-such-model"):
        assert fal.draft_resolution(none) is None
    assert not fal.is_draft("wan3", None) and not fal.is_draft("nope", "480p")


def test_the_catalogue_tells_the_card_which_frame_is_the_draft():
    by = {m["id"]: m for m in providers.models_for("fal")}
    assert by["wan3"]["draft"] == "480p" and by["seedance2.5"]["draft"] == "480p"
    assert by["ltx2.3"]["draft"] is None and by["kling3-turbo-pro"]["draft"] is None
    # a draft is always a frame the card can actually pick, and it is cheaper
    for m in by.values():
        if m["draft"]:
            assert m["draft"] in m["frame"]["values"]
            cost = m["price"]["usd_by_frame"]
            assert cost[m["draft"]] < cost[m["frame"]["default"]]
            providers.check_render_choice("fal", m["id"], None, m["draft"])   # legal


def test_a_clip_is_known_as_a_draft_from_its_own_row():
    row = {"media_kind": "video", "model": "wan3", "metadata": {"resolution": "480p"}}
    assert drafts.of_row(row) == {"frame": "480p", "model": "wan3"}
    assert drafts.of_row({**row, "metadata": {"resolution": "720p"}}) is None
    assert drafts.of_row({**row, "media_kind": "image"}) is None
    assert drafts.of_row({**row, "model": "upscale", "metadata": {}}) is None   # a finished clip
    assert drafts.of_row({"media_kind": "video", "model": None, "metadata": None}) is None
    assert drafts.of_row(None) is None


# ---------- a scene with two drafted shots ----------

@pytest.fixture
def scene(pg, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", pg)
    accounts.init(pg)
    preprod.init(pg)
    generative.init(pg)
    render_assets.init(pg)
    ledger.init(pg)
    cut_store.init(pg)
    WHO["mine"] = accounts.upsert_account("d-mine", "Mine", "#fff", dsn=pg)
    WHO["theirs"] = accounts.upsert_account("d-theirs", "Theirs", "#fff", dsn=pg)
    monkeypatch.setattr(storage, "configured", lambda: False)
    monkeypatch.setattr(auth, "current_user", lambda request: {"id": "d-user"})
    monkeypatch.setattr(auth, "current_account", lambda request: {"slug": "d-mine"})
    monkeypatch.setattr(ledger, "credit_exempt", lambda account_id, dsn=None: False)
    monkeypatch.setattr(fal, "has_key", lambda account_id=None: True)
    monkeypatch.setattr(effects, "probe_video",
                        lambda target: {"seconds": 5.0, "width": 480, "height": 854, "fps": 24})
    app.dependency_overrides[auth.current_account_id] = lambda: WHO["mine"]

    parts = [{"n": n, "start": (n - 1) * 5, "end": n * 5, "seconds": 5, "text": f"beat {n}",
              "prompt": f"shot {n}", "refs": ["/refs/a.jpg"], "reference_image": None,
              "media_url": f"/renders/fal/draft-{n}.mp4"} for n in (1, 2)]
    shot = {"n": 1, "type": "BROLL", "source": "AI", "tool": "WAN", "prompt": "p",
            "refs": ["/refs/a.jpg"], "media_url": parts[0]["media_url"],
            "timeline": {"seconds": 10, "planner": "split", "source": "x",
                         "continuity": "", "parts": parts}}
    cid = preprod.save_concept({"title": "The Can", "hook": "h", "logline": "l",
                                "duration": "10s", "shots": [shot]},
                               "zeropage", spark="can", account_id=WHO["mine"], dsn=pg)
    ids = []
    for n in (1, 2):
        ids.append(render_assets.record(
            generation_id=n, tool="wan", model="wan3", media_kind="video", prompt=f"shot {n}",
            media_url=f"/renders/fal/draft-{n}.mp4", output_path=None, concept_id=cid, shot_n=1,
            metadata={"model": "wan3", "resolution": "480p", "part": n},
            dsn=pg, account_id=WHO["mine"])["id"])
    yield {"client": TestClient(app), "pg": pg, "concept": cid, "assets": ids}
    app.dependency_overrides.pop(auth.current_account_id, None)


def _wait(client, job_id):
    for _ in range(300):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(.01)
    raise AssertionError("job never finished")


def _slots(scene):
    concept = preprod.get_concept(scene["concept"], scene["pg"], account_id=WHO["mine"])
    return [p["media_url"] for p in concept["shots"][0]["timeline"]["parts"]], concept


def test_a_rendered_scene_lists_its_drafts_by_the_id_finish_takes(scene):
    ready = scene["client"].get("/api/cut/ready").json()["ready"]
    (item,) = [r for r in ready if r["concept_id"] == scene["concept"]]
    assert [(d["part"], d["ref"], d["frame"]) for d in item["drafts"]] == [
        (1, f"gen:{scene['assets'][0]}", "480p"), (2, f"gen:{scene['assets'][1]}", "480p")]
    # the wall and the lookup say so too
    held = [a for a in api._generated_assets(WHO["mine"])]
    assert len(held) == 2 and all(a["draft"] == {"frame": "480p", "model": "wan3"} for a in held)
    wall = scene["client"].get("/api/media?scope=generated&kind=all").json()["items"]
    assert len(wall) == 2 and all(i["draft"] == {"frame": "480p", "model": "wan3"} for i in wall)
    one = scene["client"].get(f"/api/assets/generated/{scene['assets'][0]}").json()
    assert one["draft"]["frame"] == "480p" and one["concept_id"] == scene["concept"]


def test_a_finish_is_priced_like_the_upscale_it_is_and_says_where_it_will_land(scene):
    body = {"effect": "upscale", "sources": [f"gen:{scene['assets'][1]}"],
            "options": drafts.FINISH_OPTIONS, "finish": True}
    quote = scene["client"].post("/api/effects/quote", json=body).json()
    plain = scene["client"].post("/api/effects/quote", json={**body, "finish": False}).json()
    assert quote["credits"] == plain["credits"] > 0          # no second price for a finish
    assert quote["finish"] == {"concept_id": scene["concept"], "shot_n": 1, "part": 2,
                               "label": "shot 1 part 2", "title": "The Can"}
    assert "finish" not in plain


def test_only_the_clip_that_is_on_a_shot_right_now_can_be_finished(scene, monkeypatch):
    client, pg = scene["client"], scene["pg"]
    monkeypatch.setattr(effects, "run", lambda *a, **k: pytest.fail("a refused finish ran"))

    def refused(body):
        got = client.post("/api/effects/quote", json={"options": drafts.FINISH_OPTIONS,
                                                      "finish": True, **body})
        assert got.status_code == 400, got.json()
        return got.json()["error"]["message"]

    # another effect is not a finish
    assert "finished with upscale" in refused({"effect": "add-sound", "prompt": "rain",
                                              "sources": [f"gen:{scene['assets'][0]}"],
                                              "options": {}})
    # a clip that is on no scene
    loose = render_assets.record(generation_id=9, tool="wan", model="wan3", media_kind="video",
                                 prompt="loose", media_url="/renders/fal/loose.mp4",
                                 metadata={"model": "wan3", "resolution": "480p"},
                                 dsn=pg, account_id=WHO["mine"])["id"]
    assert "not a scene's shot" in refused({"effect": "upscale", "sources": [f"gen:{loose}"]})
    # another account's clip does not exist
    theirs = render_assets.record(generation_id=10, tool="wan", model="wan3", media_kind="video",
                                  prompt="theirs", media_url="/renders/fal/t.mp4",
                                  dsn=pg, account_id=WHO["theirs"])["id"]
    refused({"effect": "upscale", "sources": [f"gen:{theirs}"]})
    # a clip its shot no longer carries: finishing it would overwrite the newer one
    from src import timeline
    timeline.attach_part(scene["concept"], 1, 1, "media_url", "/renders/fal/newer.mp4",
                         db_path=pg, account_id=WHO["mine"])
    assert "no longer on its shot" in refused({"effect": "upscale",
                                              "sources": [f"gen:{scene['assets'][0]}"]})


def test_a_finished_clip_takes_the_drafts_place_on_its_shot_and_the_draft_stays(scene, monkeypatch):
    client, pg = scene["client"], scene["pg"]
    ran = []

    def fake_run(effect, urls, prompt, options, **kw):
        ran.append({"effect": effect, "options": options, **kw})
        asset = render_assets.record(generation_id=50, tool="fal", model=effect,
                                     media_kind="video", prompt="finished",
                                     metadata=kw.get("extra"),
                                     media_url="/renders/fal/finished-2.mp4",
                                     dsn=pg, account_id=WHO["mine"])
        return {"ok": True, "media_url": "/renders/fal/finished-2.mp4", "asset_id": asset["id"]}

    monkeypatch.setattr(effects, "run", fake_run)
    monkeypatch.setattr(api, "_effect_urls", lambda req, account_id: ["https://x/clip.mp4"])
    body = {"effect": "upscale", "sources": [f"gen:{scene['assets'][1]}"],
            "options": drafts.FINISH_OPTIONS, "finish": True}
    price = client.post("/api/effects/quote", json=body).json()["credits"]
    job = _wait(client, client.post("/api/effects/run",
                                    json={**body, "expect_credits": price}).json()["job_id"])
    assert job["status"] == "done", job.get("error")
    assert job["finished"] is True and job["kind"] == "effect"
    assert job["ref_id"] == scene["concept"]
    (call,) = ran
    assert call["source"] == "queue"
    assert call["extra"] == {"finish_of": f"gen:{scene['assets'][1]}",
                             "concept_id": scene["concept"], "shot_n": 1, "part": 2}

    urls, concept = _slots(scene)
    assert urls == ["/renders/fal/draft-1.mp4", "/renders/fal/finished-2.mp4"]
    # shot 1 is still the scene's "rendered" marker, untouched
    assert concept["shots"][0]["media_url"] == "/renders/fal/draft-1.mp4"
    # the new render is filed under the scene; the draft is still on the wall
    new = render_assets.get(int(job["asset"].split(":")[1]), pg, account_id=WHO["mine"])
    assert new["concept_id"] == scene["concept"] and new["shot_n"] == 1
    assert render_assets.get(scene["assets"][1], pg, account_id=WHO["mine"])["deleted_at"] is None
    # and the scene has one draft left
    (item,) = [r for r in client.get("/api/cut/ready").json()["ready"]
               if r["concept_id"] == scene["concept"]]
    assert [d["part"] for d in item["drafts"]] == [1]
    # the Library stops calling the finished one a draft: there is no
    # Finish left to point at
    wall = {i["generated_id"]: i["draft"]
            for i in client.get("/api/media?scope=generated&kind=all").json()["items"]}
    assert wall[scene["assets"][0]] == {"frame": "480p", "model": "wan3"}
    assert wall[scene["assets"][1]] is None
    assert client.get(f"/api/assets/generated/{scene['assets'][1]}").json()["draft"] is None
    # finishing the first part moves the scene's own clip with it
    monkeypatch.setattr(effects, "run", lambda effect, urls, prompt, options, **kw: {
        "ok": True, "media_url": "/renders/fal/finished-1.mp4", "asset_id": None})
    first = {**body, "sources": [f"gen:{scene['assets'][0]}"]}
    _wait(client, client.post("/api/effects/run",
                              json={**first, "expect_credits": price}).json()["job_id"])
    urls, concept = _slots(scene)
    assert urls[0] == concept["shots"][0]["media_url"] == "/renders/fal/finished-1.mp4"


def test_a_finish_whose_shot_has_gone_keeps_the_paid_clip_and_says_so(scene, monkeypatch):
    client = scene["client"]
    monkeypatch.setattr(effects, "run", lambda *a, **k: {
        "ok": True, "media_url": "/renders/fal/f.mp4", "asset_id": None})
    monkeypatch.setattr(api, "_effect_urls", lambda req, account_id: ["https://x/clip.mp4"])
    monkeypatch.setattr(drafts, "attach",
                        lambda *a, **k: (_ for _ in ()).throw(ValueError("no concept")))
    body = {"effect": "upscale", "sources": [f"gen:{scene['assets'][0]}"],
            "options": drafts.FINISH_OPTIONS, "finish": True}
    price = client.post("/api/effects/quote", json=body).json()["credits"]
    job = _wait(client, client.post("/api/effects/run",
                                    json={**body, "expect_credits": price}).json()["job_id"])
    # paid for and on the wall: a done job that says what did not happen
    assert job["status"] == "done" and job["finished"] is False
    assert "in your Library" in job["detail"] and "no concept" not in job["detail"]
