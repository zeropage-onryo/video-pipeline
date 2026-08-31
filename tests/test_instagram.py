"""
Tests for instagram.py -- the Meta Graph publish + insights module.

Same contract as youtube.py, pinned the same way: thin API wrappers may
raise; the public orchestrators (post_reel, refresh_metrics_for_video)
never do -- a missing token or failed call is a result dict, not an
exception that takes a page or the scheduler down. All hermetic:
instagram.requests is patched everywhere, and conftest's network guard
catches any patch that misses.
"""
import pytest

from src import db, instagram


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status

    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError(f"HTTP {self.status}")

    def json(self):
        return self.payload


@pytest.fixture
def tmp_db(tmp_path):
    path = tmp_path / "test.db"
    db.init_db(path)
    return path


# ---------- thin wrappers: payload shapes ----------

def test_create_reel_container_posts_the_reels_payload(monkeypatch):
    seen = {}

    def fake_post(url, data=None, timeout=None):
        seen.update({"url": url, "data": data, "timeout": timeout})
        return FakeResponse({"id": "container-1"})

    monkeypatch.setattr(instagram.requests, "post", fake_post)
    container = instagram.create_reel_container(
        "user-9", "https://cdn.example/clip.mp4", "a caption", "tok",
    )
    assert container == "container-1"
    assert seen["url"].endswith("/user-9/media")
    assert seen["data"]["media_type"] == "REELS"
    assert seen["data"]["video_url"] == "https://cdn.example/clip.mp4"
    assert seen["data"]["caption"] == "a caption"
    assert seen["data"]["access_token"] == "tok"
    assert seen["timeout"] is not None


def test_create_image_container_posts_the_image_payload(monkeypatch):
    seen = {}

    def fake_post(url, data=None, timeout=None):
        seen.update({"data": data})
        return FakeResponse({"id": "container-2"})

    monkeypatch.setattr(instagram.requests, "post", fake_post)
    instagram.create_image_container("user-9", "https://cdn.example/f.jpg", "c", "tok")
    assert seen["data"]["image_url"] == "https://cdn.example/f.jpg"
    assert "media_type" not in seen["data"] or seen["data"].get("media_type") == "IMAGE"


def test_publish_container_returns_the_media_id(monkeypatch):
    monkeypatch.setattr(
        instagram.requests, "post",
        lambda url, data=None, timeout=None: FakeResponse({"id": "media-7"}),
    )
    assert instagram.publish_container("user-9", "container-1", "tok") == "media-7"


def test_wrappers_raise_on_http_failure(monkeypatch):
    monkeypatch.setattr(
        instagram.requests, "post",
        lambda *a, **k: FakeResponse({}, status=400),
    )
    with pytest.raises(Exception):
        instagram.create_reel_container("u", "https://x/v.mp4", "c", "tok")


# ---------- post_reel: create -> poll -> publish ----------

def _status_sequence(monkeypatch, statuses):
    """POSTs succeed; GET status walks the given sequence."""
    calls = {"post": [], "get": []}

    def fake_post(url, data=None, timeout=None):
        calls["post"].append(url)
        return FakeResponse({"id": "media-1" if "media_publish" in url else "container-1"})

    def fake_get(url, params=None, timeout=None):
        calls["get"].append(url)
        index = min(len(calls["get"]) - 1, len(statuses) - 1)
        return FakeResponse({"status_code": statuses[index]})

    monkeypatch.setattr(instagram.requests, "post", fake_post)
    monkeypatch.setattr(instagram.requests, "get", fake_get)
    return calls


def test_post_reel_waits_for_finished_then_publishes(monkeypatch):
    calls = _status_sequence(monkeypatch, ["IN_PROGRESS", "IN_PROGRESS", "FINISHED"])
    naps = []
    result = instagram.post_reel(
        "user-9", "https://cdn.example/v.mp4", "cap", "tok",
        poll_tries=5, poll_delay=1, sleep=naps.append,
    )
    assert result["ok"] is True
    assert result["media_id"] == "media-1"
    assert len(calls["get"]) == 3
    assert any("media_publish" in u for u in calls["post"])
    assert naps  # it waited between polls rather than hammering


def test_post_reel_stops_dead_on_error_status(monkeypatch):
    calls = _status_sequence(monkeypatch, ["ERROR"])
    result = instagram.post_reel(
        "user-9", "https://cdn.example/v.mp4", "cap", "tok", sleep=lambda s: None,
    )
    assert result["ok"] is False
    assert result["step"] == "poll"
    # never publish a container that reported ERROR
    assert not any("media_publish" in u for u in calls["post"])


def test_post_reel_gives_up_after_poll_tries(monkeypatch):
    calls = _status_sequence(monkeypatch, ["IN_PROGRESS"])
    result = instagram.post_reel(
        "user-9", "https://cdn.example/v.mp4", "cap", "tok",
        poll_tries=3, sleep=lambda s: None,
    )
    assert result["ok"] is False
    assert result["step"] == "poll"
    assert len(calls["get"]) == 3
    assert not any("media_publish" in u for u in calls["post"])


def test_post_reel_reports_create_failure_without_raising(monkeypatch):
    def fake_post(url, data=None, timeout=None):
        raise RuntimeError("boom with tok inside")

    monkeypatch.setattr(instagram.requests, "post", fake_post)
    result = instagram.post_reel("user-9", "https://x/v.mp4", "cap", "tok",
                                sleep=lambda s: None)
    assert result["ok"] is False
    assert result["step"] == "create"
    assert "tok" not in result["error"]          # redacted
    assert "<redacted>" in result["error"]


def test_post_reel_reports_publish_failure(monkeypatch):
    def fake_post(url, data=None, timeout=None):
        if "media_publish" in url:
            raise RuntimeError("publish exploded")
        return FakeResponse({"id": "container-1"})

    monkeypatch.setattr(instagram.requests, "post", fake_post)
    monkeypatch.setattr(
        instagram.requests, "get",
        lambda url, params=None, timeout=None: FakeResponse({"status_code": "FINISHED"}),
    )
    result = instagram.post_reel("user-9", "https://x/v.mp4", "cap", "tok",
                                sleep=lambda s: None)
    assert result["ok"] is False
    assert result["step"] == "publish"


# ---------- parse_media_id ----------

def test_parse_media_id_shapes():
    assert instagram.parse_media_id("17912345678901234") == "17912345678901234"
    assert instagram.parse_media_id("ig://17912345678901234") == "17912345678901234"
    assert instagram.parse_media_id(
        "https://www.instagram.com/reel/AbC123/?media_id=17912345678901234"
    ) == "17912345678901234"
    # a bare shortcode permalink does not contain the numeric id
    assert instagram.parse_media_id("https://www.instagram.com/reel/AbC123/") is None
    assert instagram.parse_media_id(None) is None


# ---------- refresh_metrics_for_video ----------

def test_refresh_guards_non_instagram_video(tmp_db):
    video = {"id": 1, "platform": "youtube", "url": "https://youtu.be/x"}
    result = instagram.refresh_metrics_for_video(video, token="tok", db_path=tmp_db)
    assert result["ok"] is False
    assert "instagram" in result["error"]


def test_refresh_guards_missing_token(tmp_db):
    video = {"id": 1, "platform": "instagram", "url": "17912345678901234"}
    result = instagram.refresh_metrics_for_video(video, token=None, db_path=tmp_db)
    assert result["ok"] is False
    assert "IG_ACCESS_TOKEN" in result["error"]


def test_refresh_honest_about_permalink_without_media_id(tmp_db):
    video = {"id": 1, "platform": "instagram",
             "url": "https://www.instagram.com/reel/AbC123/"}
    result = instagram.refresh_metrics_for_video(video, token="tok", db_path=tmp_db)
    assert result["ok"] is False
    assert "media id" in result["error"]


def test_refresh_writes_a_snapshot_on_success(tmp_db, monkeypatch):
    vid = db.add_video("Reel", "instagram", "2026-08-01",
                       url="ig://17912345678901234", path=tmp_db, account_id=None)

    def fake_get(url, params=None, timeout=None):
        assert "17912345678901234/insights" in url
        return FakeResponse({"data": [
            {"name": "views", "values": [{"value": 420}]},
            {"name": "likes", "values": [{"value": 33}]},
            {"name": "comments", "values": [{"value": 5}]},
            {"name": "saved", "values": [{"value": 7}]},
            {"name": "shares", "values": [{"value": 2}]},
        ]})

    monkeypatch.setattr(instagram.requests, "get", fake_get)
    video = db.get_video(vid, path=tmp_db, account_id=None)
    result = instagram.refresh_metrics_for_video(video, token="tok", db_path=tmp_db)
    assert result == {"ok": True, "views": 420, "likes": 33, "comments": 5,
                      "saves": 7, "shares": 2}

    history = db.get_video_history(vid, path=tmp_db, account_id=None)
    assert history[-1]["views"] == 420
    assert history[-1]["saves"] == 7


def test_refresh_prefers_a_stored_media_id_key(tmp_db, monkeypatch):
    vid = db.add_video("Reel", "instagram", "2026-08-01",
                       url="https://www.instagram.com/reel/AbC123/", path=tmp_db, account_id=None)
    monkeypatch.setattr(
        instagram.requests, "get",
        lambda url, params=None, timeout=None: FakeResponse(
            {"data": [{"name": "views", "values": [{"value": 9}]}]}),
    )
    video = dict(db.get_video(vid, path=tmp_db, account_id=None), media_id="17900000000000000")
    result = instagram.refresh_metrics_for_video(video, token="tok", db_path=tmp_db)
    assert result["ok"] is True
    assert result["views"] == 9


def test_refresh_reports_api_failure_with_token_redacted(tmp_db, monkeypatch):
    vid = db.add_video("Reel", "instagram", "2026-08-01",
                       url="ig://179", path=tmp_db, account_id=None)

    def fake_get(url, params=None, timeout=None):
        raise RuntimeError("denied for token tok-secret")

    monkeypatch.setattr(instagram.requests, "get", fake_get)
    video = db.get_video(vid, path=tmp_db, account_id=None)
    result = instagram.refresh_metrics_for_video(video, token="tok-secret", db_path=tmp_db)
    assert result["ok"] is False
    assert "tok-secret" not in result["error"]


# ---------- _safe_error ----------

def test_safe_error_redacts_the_token():
    error = RuntimeError("400 at https://graph.instagram.com/x?access_token=sekrit")
    assert "sekrit" not in instagram._safe_error(error, "sekrit")


# ---------- the autopilot adapter ----------

def test_execute_post_action_raises_without_env(monkeypatch):
    for name in ("IG_USER_ID", "IG_ACCESS_TOKEN",
                 "INSTAGRAM_USER_ID", "INSTAGRAM_ACCESS_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(RuntimeError):
        instagram.execute_post_action(
            {"kind": "post", "video_url": "https://x/v.mp4", "caption": "c"})


def test_execute_post_action_posts_and_writes_result_back(monkeypatch):
    monkeypatch.setenv("IG_USER_ID", "user-9")
    monkeypatch.setenv("IG_ACCESS_TOKEN", "tok")
    monkeypatch.setattr(
        instagram, "post_reel",
        lambda *a, **k: {"ok": True, "media_id": "media-5", "step": "publish",
                         "error": None},
    )
    action = {"kind": "post", "video_url": "https://x/v.mp4", "caption": "c"}
    instagram.execute_post_action(action)
    assert action["result"]["media_id"] == "media-5"


def test_execute_post_action_raises_on_failed_publish(monkeypatch):
    monkeypatch.setenv("IG_USER_ID", "user-9")
    monkeypatch.setenv("IG_ACCESS_TOKEN", "tok")
    monkeypatch.setattr(
        instagram, "post_reel",
        lambda *a, **k: {"ok": False, "media_id": None, "step": "poll",
                         "error": "container ERROR"},
    )
    with pytest.raises(RuntimeError, match="container ERROR"):
        instagram.execute_post_action(
            {"kind": "post", "video_url": "https://x/v.mp4", "caption": "c"})
