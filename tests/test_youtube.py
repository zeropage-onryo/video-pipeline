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
from src.youtube import (
    fetch_stats_bulk,
    fetch_video_stats,
    get_uploads_playlist_id,
    import_channel_videos,
    list_channel_videos,
    parse_video_id,
    refresh_metrics_for_video,
)


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


# ---------- channel import ----------

def make_fake_api(channels=None, pages=None, stats=None, fail_on=None):
    """
    A requests.get stand-in that dispatches on which YouTube endpoint is
    being hit, so one fake covers the whole multi-call import flow.
    """
    def fake_get(url, params=None, timeout=None):
        if fail_on and fail_on in url:
            return FakeResponse({}, status_code=403)

        if url.endswith("/channels"):
            return FakeResponse(channels)

        if url.endswith("/playlistItems"):
            token = (params or {}).get("pageToken")
            index = 0 if token is None else int(token)
            return FakeResponse(pages[index])

        if url.endswith("/videos"):
            requested = (params or {}).get("id", "").split(",")
            return FakeResponse({
                "items": [
                    {"id": vid, "statistics": stats[vid]}
                    for vid in requested if vid in (stats or {})
                ]
            })

        raise AssertionError(f"unexpected url {url}")

    return fake_get


CHANNELS_OK = {
    "items": [{"contentDetails": {"relatedPlaylists": {"uploads": "UUuploads123"}}}]
}


def _page(items, next_token=None):
    page = {"items": [
        {"snippet": {
            "title": title,
            "publishedAt": published,
            "resourceId": {"videoId": vid},
        }}
        for vid, title, published in items
    ]}
    if next_token is not None:
        page["nextPageToken"] = next_token
    return page


def test_get_uploads_playlist_id(monkeypatch):
    monkeypatch.setattr(youtube.requests, "get", make_fake_api(channels=CHANNELS_OK))
    assert get_uploads_playlist_id("@someone", "test-key") == "UUuploads123"


def test_get_uploads_playlist_id_raises_for_unknown_channel(monkeypatch):
    monkeypatch.setattr(youtube.requests, "get", make_fake_api(channels={"items": []}))
    with pytest.raises(ValueError, match="no channel found"):
        get_uploads_playlist_id("@nobody", "test-key")


def test_list_channel_videos_returns_video_metadata(monkeypatch):
    pages = [_page([("vid1", "Night Run", "2025-09-29T00:00:00Z")])]
    monkeypatch.setattr(youtube.requests, "get",
                        make_fake_api(channels=CHANNELS_OK, pages=pages))

    videos = list_channel_videos("@someone", "test-key")

    assert videos == [{
        "video_id": "vid1", "title": "Night Run", "published_at": "2025-09-29",
    }]


def test_list_channel_videos_follows_pagination(monkeypatch):
    pages = [
        _page([("vid1", "One", "2025-01-01T00:00:00Z")], next_token="1"),
        _page([("vid2", "Two", "2025-02-01T00:00:00Z")]),
    ]
    monkeypatch.setattr(youtube.requests, "get",
                        make_fake_api(channels=CHANNELS_OK, pages=pages))

    videos = list_channel_videos("@someone", "test-key")

    assert [v["video_id"] for v in videos] == ["vid1", "vid2"]


def test_fetch_stats_bulk_returns_stats_per_video(monkeypatch):
    stats = {
        "vid1": {"viewCount": "82", "likeCount": "5", "commentCount": "1"},
        "vid2": {"viewCount": "344"},
    }
    monkeypatch.setattr(youtube.requests, "get", make_fake_api(stats=stats))

    result = fetch_stats_bulk(["vid1", "vid2"], "test-key")

    assert result["vid1"] == {"views": 82, "likes": 5, "comments": 1}
    assert result["vid2"] == {"views": 344, "likes": None, "comments": None}


def test_fetch_stats_bulk_empty_list_makes_no_call():
    assert fetch_stats_bulk([], "test-key") == {}


def test_fetch_stats_bulk_batches_over_50(monkeypatch):
    ids = [f"vid{n}" for n in range(120)]
    stats = {vid: {"viewCount": "1"} for vid in ids}
    calls = []

    fake = make_fake_api(stats=stats)

    def counting_get(url, params=None, timeout=None):
        calls.append(params.get("id"))
        return fake(url, params=params, timeout=timeout)

    monkeypatch.setattr(youtube.requests, "get", counting_get)

    result = fetch_stats_bulk(ids, "test-key")

    assert len(result) == 120
    assert len(calls) == 3  # 50 + 50 + 20, not 120 separate calls


def test_import_adds_new_videos_with_initial_snapshot(tmp_db, monkeypatch):
    pages = [_page([
        ("vid1", "Night Run", "2025-09-29T00:00:00Z"),
        ("vid2", "Lone star", "2023-01-15T00:00:00Z"),
    ])]
    stats = {
        "vid1": {"viewCount": "82"},
        "vid2": {"viewCount": "344"},
    }
    monkeypatch.setattr(youtube.requests, "get",
                        make_fake_api(channels=CHANNELS_OK, pages=pages, stats=stats))

    result = import_channel_videos("@someone", api_key="test-key", db_path=tmp_db)

    assert result["ok"] is True
    assert result["added"] == 2

    videos = db.list_videos(path=tmp_db)
    assert {v["title"] for v in videos} == {"Night Run", "Lone star"}
    assert all(v["platform"] == "youtube" for v in videos)

    night_run = next(v for v in videos if v["title"] == "Night Run")
    assert db.get_video_history(night_run["id"], path=tmp_db)[-1]["views"] == 82


def test_import_skips_videos_already_in_the_database(tmp_db, monkeypatch):
    db.add_video("Night Run", "youtube", "2025-09-29",
                 url="https://www.youtube.com/watch?v=vid1", path=tmp_db)

    pages = [_page([
        ("vid1", "Night Run", "2025-09-29T00:00:00Z"),
        ("vid2", "Lone star", "2023-01-15T00:00:00Z"),
    ])]
    monkeypatch.setattr(
        youtube.requests, "get",
        make_fake_api(channels=CHANNELS_OK, pages=pages,
                      stats={"vid2": {"viewCount": "344"}}),
    )

    result = import_channel_videos("@someone", api_key="test-key", db_path=tmp_db)

    assert result["added"] == 1
    assert len(db.list_videos(path=tmp_db)) == 2  # not 3 -- no duplicate Night Run


def test_import_fails_gracefully_without_api_key(tmp_db):
    result = import_channel_videos("@someone", api_key=None, db_path=tmp_db)
    assert result["ok"] is False
    assert result["added"] == 0
    assert db.list_videos(path=tmp_db) == []


def test_import_fails_gracefully_when_channel_lookup_fails(tmp_db, monkeypatch):
    monkeypatch.setattr(youtube.requests, "get", make_fake_api(fail_on="/channels"))

    result = import_channel_videos("@someone", api_key="bad-key", db_path=tmp_db)

    assert result["ok"] is False
    assert db.list_videos(path=tmp_db) == []


def test_import_error_never_leaks_the_api_key(tmp_db, monkeypatch):
    """
    requests puts the full request URL in its error text, and ours
    carry key=<api key>. That error string gets rendered straight into
    the page, so an unredacted key would be a real leak.
    """
    secret = "AIzaSuperSecretKeyValue"

    def leaky_get(url, params=None, timeout=None):
        raise Exception(f"400 Client Error for url: {url}?key={secret}")

    monkeypatch.setattr(youtube.requests, "get", leaky_get)

    result = import_channel_videos("@someone", api_key=secret, db_path=tmp_db)

    assert result["ok"] is False
    assert secret not in result["error"]
    assert "<redacted>" in result["error"]


def test_refresh_error_never_leaks_the_api_key(tmp_db, monkeypatch):
    secret = "AIzaSuperSecretKeyValue"
    vid = db.add_video("Night Run", "youtube", "2025-09-29",
                       url="https://www.youtube.com/watch?v=abc12345678", path=tmp_db)
    video = db.get_video(vid, path=tmp_db)

    def leaky_fetch(video_id, api_key):
        raise Exception(f"400 Client Error for url: https://x?key={secret}")

    monkeypatch.setattr(youtube, "fetch_video_stats", leaky_fetch)

    result = refresh_metrics_for_video(video, api_key=secret, db_path=tmp_db)

    assert secret not in result["error"]


def test_import_still_adds_videos_when_stats_call_fails(tmp_db, monkeypatch):
    """Stats are a bonus -- losing them shouldn't lose the videos too."""
    pages = [_page([("vid1", "Night Run", "2025-09-29T00:00:00Z")])]
    monkeypatch.setattr(
        youtube.requests, "get",
        make_fake_api(channels=CHANNELS_OK, pages=pages, fail_on="/videos"),
    )

    result = import_channel_videos("@someone", api_key="test-key", db_path=tmp_db)

    assert result["ok"] is True
    assert result["added"] == 1
    videos = db.list_videos(path=tmp_db)
    assert db.get_video_history(videos[0]["id"], path=tmp_db) == []
