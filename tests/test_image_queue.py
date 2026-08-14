"""
The semi-auto Midjourney image path (BACKLOG #6): queue a still as a held
image post on Zero Page, then approve it on /holds and it posts an IMAGE
action (not video) through the gate. The R2 upload branch needs real creds
and isn't exercised here; the pasted-URL branch and the action shape are.
"""
import pytest
from fastapi.testclient import TestClient

import app.main as app_main
from app.main import app
from src import autonomy, db

client = TestClient(app)


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    path = tmp_path / "app.db"
    db.init_db(path)
    autonomy.init(path)          # seeds the zeropage channel + targets
    monkeypatch.setattr(db, "DB_PATH", path)
    return path


def test_queue_creates_a_held_zeropage_image_hold(tmp_db):
    r = client.post("/post-image/queue",
                    data={"image_url": "https://cdn.example/x.jpg", "caption": "night ride"},
                    follow_redirects=False)
    assert r.status_code == 303 and "/holds" in r.headers["location"]
    held = autonomy.list_hold(status="held", path=tmp_db)
    assert held and held[0]["channel"] == "zeropage"
    assert held[0]["payload"]["image_url"] == "https://cdn.example/x.jpg"
    assert held[0]["caption"] == "night ride"


def test_queue_without_an_image_is_rejected(tmp_db):
    r = client.post("/post-image/queue", data={"caption": "no image"},
                    follow_redirects=False)
    assert r.status_code == 303 and "/post-image" in r.headers["location"]
    assert autonomy.list_hold(status="held", path=tmp_db) == []


def test_approving_an_image_hold_builds_an_image_action(tmp_db, monkeypatch):
    hid = autonomy.to_hold("zeropage", "queued", caption="cap",
                           payload={"image_url": "https://cdn.example/x.jpg"},
                           status="held", path=tmp_db)
    captured = {}

    def fake_execute(plan, approve=False, dry_run=True):
        captured["actions"] = plan["actions"]
        return {"mode": "dry-run", "executed": 0, "skipped": []}

    monkeypatch.setattr(app_main.autopilot, "execute", fake_execute)
    client.post(f"/holds/{hid}/post", follow_redirects=False)

    actions = captured["actions"]
    assert actions, "holds_post built no actions for an image hold"
    assert all(a.get("image_url") == "https://cdn.example/x.jpg" for a in actions)
    assert all("video_url" not in a for a in actions)
