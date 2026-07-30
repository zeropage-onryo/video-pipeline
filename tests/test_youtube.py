"""
Tests for the YouTube video-id parser and the public-stats fetcher.
"The parser is the part that actually breaks" per RUNBOOK.md, since
each URL shape has its own way to trip up a naive regex once real
query params show up -- covered first. fetch_video_stats and
refresh_metrics_for_video cover BUILD_SPEC.md's other Session 5 rule:
"Missing key or failed call must not break the screen; manual entry
keeps working" -- refresh_metrics_for_video must never raise.
"""
import pytest

from src import db, youtube
from src.youtube import fetch_video_stats, parse_video_id, refresh_metrics_for_video


def test_parses_watch_url():
    assert parse_video_id("https://www.youtube.com/watch?v=k_S1B0mG9IM") == "k_S1B0mG9IM"


def test_parses_watch_url_without_www():
    assert parse_video_id("https://youtube.com/watch?v=abc12345678") == "abc12345678"


def test_parses_watch_url_with_trailing_query_params():
    assert parse_video_id("https://www.youtube.com/watch?v=abc12345678&t=30s") == "abc12345678"


def test_parses_watch_url_with_v_param_not_first():
    assert parse_video_id(
        "https://www.youtube.com/watch?list=PL123&v=abc12345678&index=2"
    ) == "abc12345678"


def test_parses_short_url():
    assert parse_video_id("https://youtu.be/abc12345678") == "abc12345678"


def test_parses_short_url_with_query_params():
    assert parse_video_id("https://youtu.be/abc12345678?t=30") == "abc12345678"


def test_parses_shorts_url():
    assert parse_video_id("https://www.youtube.com/shorts/abc12345678") == "abc12345678"


def test_parses_shorts_url_with_query_params():
    assert parse_video_id(
        "https://www.youtube.com/shorts/abc12345678?feature=share"
    ) == "abc12345678"


def test_non_youtube_url_returns_none():
    assert parse_video_id("https://vimeo.com/12345678") is None


def test_watch_url_missing_v_param_returns_none():
    assert parse_video_id("https://www.youtube.com/watch?list=PL123") is None


def test_empty_string_returns_none():
    assert parse_video_id("") is None


def test_none_returns_none():
    assert parse_video_id(None) is None


class FakeResponse:
    def __init__(self, json_data, status_code=200):
        self._json = json_data
        self.status_code = status_code

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")


# ---------- fetch_video_stats ----------

def test_fetch_video_stats_parses_response(monkeypatch):
    def fake_get(url, params=None, timeout=None):
        assert params["id"] == "abc123"
        assert params["key"] == "test-key"
        return FakeResponse({
            "items": [{"statistics": {"viewCount": "82", "likeCount": "5", "commentCount": "1"}}]
        })

    monkeypatch.setattr(youtube.requests, "get", fake_get)

    assert fetch_video_stats("abc123", "test-key") == {"views": 82, "likes": 5, "comments": 1}


def test_fetch_video_stats_raises_for_unknown_video(monkeypatch):
    monkeypatch.setattr(youtube.requests, "get", lambda *a, **kw: FakeResponse({"items": []}))
    with pytest.raises(ValueError, match="no video found"):
        fetch_video_stats("missing", "test-key")


def test_fetch_video_stats_raises_on_http_error(monkeypatch):
    monkeypatch.setattr(youtube.requests, "get", lambda *a, **kw: FakeResponse({}, status_code=403))
    with pytest.raises(Exception):
        fetch_video_stats("abc123", "bad-key")


def test_fetch_video_stats_handles_missing_statistics_fields(monkeypatch):
    monkeypatch.setattr(
        youtube.requests, "get",
        lambda *a, **kw: FakeResponse({"items": [{"statistics": {"viewCount": "82"}}]}),
    )
    assert fetch_video_stats("abc123", "test-key") == {"views": 82, "likes": None, "comments": None}


# ---------- refresh_metrics_for_video ----------

@pytest.fixture
def tmp_db(tmp_path):
    path = tmp_path / "test.db"
    db.init_db(path)
    return path


def test_refresh_records_a_snapshot_on_success(tmp_db, monkeypatch):
    vid = db.add_video("Night Run", "youtube", "2025-09-29",
                       url="https://www.youtube.com/watch?v=abc12345678", path=tmp_db)
    video = db.get_video(vid, path=tmp_db)

    monkeypatch.setattr(
        youtube, "fetch_video_stats",
        lambda video_id, api_key: {"views": 82, "likes": 5, "comments": 1},
    )

    result = refresh_metrics_for_video(video, api_key="test-key", db_path=tmp_db)

    assert result["ok"] is True
    history = db.get_video_history(vid, path=tmp_db)
    assert history[-1]["views"] == 82


def test_refresh_fails_gracefully_without_api_key(tmp_db):
    vid = db.add_video("Night Run", "youtube", "2025-09-29",
                       url="https://www.youtube.com/watch?v=abc12345678", path=tmp_db)
    video = db.get_video(vid, path=tmp_db)

    result = refresh_metrics_for_video(video, api_key=None, db_path=tmp_db)

    assert result["ok"] is False
    assert db.get_video_history(vid, path=tmp_db) == []


def test_refresh_fails_gracefully_for_non_youtube_video(tmp_db):
    vid = db.add_video("Night Run", "tiktok", "2025-09-29", path=tmp_db)
    video = db.get_video(vid, path=tmp_db)

    assert refresh_metrics_for_video(video, api_key="test-key", db_path=tmp_db)["ok"] is False


def test_refresh_fails_gracefully_for_unparseable_url(tmp_db):
    vid = db.add_video("Night Run", "youtube", "2025-09-29",
                       url="https://example.com/not-a-real-video", path=tmp_db)
    video = db.get_video(vid, path=tmp_db)

    assert refresh_metrics_for_video(video, api_key="test-key", db_path=tmp_db)["ok"] is False


def test_refresh_fails_gracefully_when_api_call_raises(tmp_db, monkeypatch):
    vid = db.add_video("Night Run", "youtube", "2025-09-29",
                       url="https://www.youtube.com/watch?v=abc12345678", path=tmp_db)
    video = db.get_video(vid, path=tmp_db)

    def boom(video_id, api_key):
        raise Exception("quota exceeded")

    monkeypatch.setattr(youtube, "fetch_video_stats", boom)

    result = refresh_metrics_for_video(video, api_key="test-key", db_path=tmp_db)

    assert result["ok"] is False
    assert db.get_video_history(vid, path=tmp_db) == []
