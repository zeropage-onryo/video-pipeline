"""
A partial fan-out must never post twice (2026-09-26).

The zeropage channel targets instagram,youtube. With R2 configured the
hold's clip is a public URL: Instagram publishes it (Meta fetches it),
YouTube refuses it (it uploads bytes, never an http URL). Before the fix
autopilot.execute raised out of its loop on YouTube, holds_post answered
502 without recording anything, the hold stayed `held`, and the next
click published to Instagram AGAIN. These tests drive the real gate and
the real dispatch; only the two platform adapters are stood in for.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from src import autonomy, autopilot, instagram, tiktok, youtube

client = TestClient(app)

CLIP = "https://pub-x.r2.dev/renders/runway/clip.mp4"


@pytest.fixture
def world(pg, monkeypatch, tmp_path):
    autonomy.init(pg)
    autonomy.set_targets("zeropage", "instagram,youtube", dsn=pg)
    monkeypatch.setenv("DATABASE_URL", pg)
    # the gate, fully open -- the adapters below are the only thing that "posts"
    monkeypatch.setenv(autopilot.ENABLE_ENV, "1")
    monkeypatch.setenv(autopilot.POST_ENV, "1")
    monkeypatch.setattr(autopilot, "KILL_SWITCH_PATH", tmp_path / "autopilot.off")

    from app import auth
    stub = {"id": 1, "email": "t@example.com", "display_name": "T"}
    monkeypatch.setattr(auth, "current_user", lambda request: stub)

    calls = {"instagram": 0, "youtube": 0}

    def ig(action):
        calls["instagram"] += 1
        action["result"] = {"ok": True, "media_id": "ig-777"}

    def yt(action):
        calls["youtube"] += 1
        raise RuntimeError("youtube post action has no local video file")

    monkeypatch.setattr(instagram, "execute_post_action", ig)
    monkeypatch.setattr(youtube, "execute_post_action", yt)
    hid = autonomy.to_hold("zeropage", "parked", caption="cap",
                           payload={"clips": [{"url": CLIP}]},
                           dsn=pg, account_id=None)
    return {"pg": pg, "hid": hid, "calls": calls, "monkeypatch": monkeypatch}


def test_instagram_succeeds_youtube_fails_click_twice_posts_instagram_once(world):
    hid, calls = world["hid"], world["calls"]

    first = client.post(f"/api/holds/{hid}/post")
    assert first.status_code == 200
    body = first.json()
    assert body["posted"] is False and body["partial"] is True
    assert body["posted_to"] == {"instagram": "ig-777"}
    assert "posted to instagram" in body["detail"]
    assert "youtube failed: youtube post action has no local video file" in body["detail"]

    hold = autonomy.get_hold(hid, dsn=world["pg"], account_id=None)
    assert hold["status"] == "held"                      # the rest is retryable
    assert hold["payload"]["posted"] == {"instagram": "ig-777"}

    second = client.post(f"/api/holds/{hid}/post")
    assert second.status_code == 200
    assert second.json()["partial"] is True

    assert calls["instagram"] == 1                       # THE regression
    assert calls["youtube"] == 2


def test_the_retry_resolves_the_hold_once_every_target_has_posted(world):
    hid, calls = world["hid"], world["calls"]
    client.post(f"/api/holds/{hid}/post")

    def yt_ok(action):
        calls["youtube"] += 1
        action["result"] = {"ok": True, "media_id": "yt-1"}
    world["monkeypatch"].setattr(youtube, "execute_post_action", yt_ok)

    res = client.post(f"/api/holds/{hid}/post")
    assert res.status_code == 200
    assert res.json()["posted"] is True
    assert res.json()["posted_to"] == {"instagram": "ig-777", "youtube": "yt-1"}
    assert calls["instagram"] == 1
    hold = autonomy.get_hold(hid, dsn=world["pg"], account_id=None)
    assert hold["status"] == "posted"


def test_every_target_failing_is_still_a_502_and_records_nothing(world):
    def ig_down(action):
        raise RuntimeError("meta is down")
    world["monkeypatch"].setattr(instagram, "execute_post_action", ig_down)

    res = client.post(f"/api/holds/{world['hid']}/post")
    assert res.status_code == 502
    message = res.json()["error"]["message"]
    assert "instagram failed: meta is down" in message
    assert "youtube failed" in message
    hold = autonomy.get_hold(world["hid"], dsn=world["pg"], account_id=None)
    assert hold["status"] == "held"
    assert "posted" not in hold["payload"]


# ---------- autopilot.execute: one result per action ----------

def test_execute_records_each_action_instead_of_aborting(monkeypatch, tmp_path):
    monkeypatch.setenv(autopilot.ENABLE_ENV, "1")
    monkeypatch.setenv(autopilot.POST_ENV, "1")
    monkeypatch.setattr(autopilot, "KILL_SWITCH_PATH", tmp_path / "autopilot.off")
    fired = []

    def post(action):
        fired.append(action["platform"])
        if action["platform"] == "youtube":
            raise RuntimeError("nope")
        action["result"] = {"media_id": f"m-{action['platform']}"}
    monkeypatch.setitem(autopilot.EXECUTORS, "post", post)

    result = autopilot.execute({"actions": [
        {"kind": "post", "platform": "youtube"},
        {"kind": "post", "platform": "instagram"},
    ]}, approve=True, dry_run=False)

    assert fired == ["youtube", "instagram"]             # the failure did not stop the loop
    assert result["executed"] == 1
    assert result["posted"] == [{"platform": "instagram", "media_id": "m-instagram"}]
    assert result["failed"] == [{"platform": "youtube", "error": "nope"}]


def test_execute_redacts_both_credentials_in_a_failure(monkeypatch, tmp_path):
    monkeypatch.setenv(autopilot.ENABLE_ENV, "1")
    monkeypatch.setenv(autopilot.POST_ENV, "1")
    monkeypatch.setattr(autopilot, "KILL_SWITCH_PATH", tmp_path / "autopilot.off")
    monkeypatch.setattr(instagram, "access_token", lambda: "ig-sekrit")
    monkeypatch.setattr(tiktok, "access_token", lambda: "tt-sekrit")

    def post(action):
        raise RuntimeError("bad ig-sekrit and tt-sekrit")
    monkeypatch.setitem(autopilot.EXECUTORS, "post", post)

    result = autopilot.execute({"actions": [{"kind": "post", "platform": "tiktok"}]},
                               approve=True, dry_run=False)
    error = result["failed"][0]["error"]
    assert "sekrit" not in error
    assert error.count("<redacted>") == 2


def test_a_non_live_preview_carries_empty_results():
    result = autopilot.execute({"actions": [{"kind": "post", "platform": "instagram"}]})
    assert result["mode"] != "live"
    assert result["posted"] == [] and result["failed"] == []
