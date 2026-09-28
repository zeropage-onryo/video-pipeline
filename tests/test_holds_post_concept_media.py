"""
A hold reaches its concept's render (2026-09-26).

The nightly graph parks every run before anything renders, so no hold's
payload carries a clip -- while the Queue's approve and the manual lane
write the clip onto the CONCEPT. holds_post used to read only the
payload, so a scene rendered after its run parked could never be posted
from its hold. It now falls back to the concept, the way
autopilot.build_plan reads a rendered one -- except a timed scene, whose
`media_url` is shot 1's clip and not the scene: that posts only as the
cut src/cut assembled for it, and is refused until one exists.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from src import autonomy, preprod, storage

client = TestClient(app)

RENDER = "https://cdn.example/renders/fal/scene.mp4"


@pytest.fixture
def world(pg, monkeypatch):
    autonomy.init(pg)
    preprod.init(pg)
    autonomy.set_targets("zeropage", "instagram", dsn=pg)
    monkeypatch.setenv("DATABASE_URL", pg)
    monkeypatch.setattr(storage, "configured", lambda: False)   # url_for passes through

    from app import api as api_mod
    from app import auth
    stub = {"id": 1, "email": "t@example.com", "display_name": "T"}
    monkeypatch.setattr(auth, "current_user", lambda request: stub)

    captured = {}

    def fake_execute(plan, approve=False, dry_run=True):
        captured["actions"] = plan["actions"]
        return {"mode": "dry-run", "executed": 0, "skipped": [], "failed": [], "posted": []}

    monkeypatch.setattr(api_mod.autopilot, "execute", fake_execute)
    return {"pg": pg, "captured": captured, "monkeypatch": monkeypatch}


def _concept(pg, shot):
    base = {"n": 1, "type": "BROLL", "source": "AI", "tool": "LTX", "desc": "d", "prompt": "p"}
    return preprod.save_concept({"title": "T", "hook": "h", "shots": [{**base, **shot}]},
                                brand="zeropage", dsn=pg, account_id=None)


def _hold(pg, concept_id):
    return autonomy.to_hold("zeropage", "parked", concept_id=concept_id, caption="cap",
                            payload={"run_id": "r1"}, dsn=pg, account_id=None)


def _timeline(n):
    return {"seconds": 10, "parts": [
        {"n": i, "start": i, "end": i + 1, "media_url": f"https://cdn.example/p{i}.mp4"}
        for i in range(1, n + 1)]}


def test_a_clipless_hold_posts_its_rendered_concept(world):
    hid = _hold(world["pg"], _concept(world["pg"], {"media_url": RENDER}))
    res = client.post(f"/api/holds/{hid}/post")
    assert res.status_code == 200
    actions = world["captured"]["actions"]
    assert [a["video_url"] for a in actions] == [RENDER]
    assert actions[0]["video_path"] == ""                # a public URL, not a file


def test_a_timed_scene_without_a_cut_is_refused_with_a_reason(world):
    cid = _concept(world["pg"], {"media_url": "https://cdn.example/p1.mp4",
                                 "timeline": _timeline(3)})
    res = client.post(f"/api/holds/{_hold(world['pg'], cid)}/post")
    assert res.status_code == 409
    err = res.json()["error"]
    assert err["code"] == "timed_scene_uncut"
    assert "3 shots" in err["message"] and "assemble its cut" in err["message"]
    assert "actions" not in world["captured"]            # nothing reached the gate


def test_a_timed_scene_posts_its_assembled_cut_not_shot_one(world):
    from src.cut import store as cut_store
    cid = _concept(world["pg"], {"media_url": "https://cdn.example/p1.mp4",
                                 "timeline": _timeline(2)})
    seen = {}

    def head(project_id, *, account_id, dsn=None):
        seen["project"] = project_id
        return {"export_url": "https://cdn.example/renders/cut/concept-cut.mp4"}
    world["monkeypatch"].setattr(cut_store, "head", head)

    res = client.post(f"/api/holds/{_hold(world['pg'], cid)}/post")
    assert res.status_code == 200
    assert seen["project"] == f"concept:{cid}"
    assert world["captured"]["actions"][0]["video_url"] == \
        "https://cdn.example/renders/cut/concept-cut.mp4"


def test_an_unrendered_concept_is_refused_before_the_gate(world):
    hid = _hold(world["pg"], _concept(world["pg"], {}))
    res = client.post(f"/api/holds/{hid}/post")
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "no_media"
    assert "not been rendered" in res.json()["error"]["message"]
    assert "actions" not in world["captured"]


def test_the_payload_clip_still_wins_over_the_concept(world):
    cid = _concept(world["pg"], {"media_url": RENDER})
    hid = autonomy.to_hold("zeropage", "parked", concept_id=cid, caption="cap",
                           payload={"clips": [{"url": "https://cdn.example/run.mp4"}]},
                           dsn=world["pg"], account_id=None)
    client.post(f"/api/holds/{hid}/post")
    assert world["captured"]["actions"][0]["video_url"] == "https://cdn.example/run.mp4"
