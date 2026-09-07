"""
Tests for tiktok.py -- the Content Posting (Direct Post) + Display API
module, pinned to the same contract as instagram.py and youtube.py: thin
wrappers may raise; the public orchestrators (post_video,
refresh_metrics_for_video) never do, and no error text ever carries the
token.

All hermetic through the module's ONE network seam: every test patches
tiktok._request, and conftest's guard catches a patch that misses. That
seam is the reason this file can assert what was sent to which endpoint
without a fake HTTP library.
"""
import pytest

from src import db, tiktok


def ok(data: dict) -> dict:
    """TikTok's success envelope: real failures live inside a 200."""
    return {"data": data, "error": {"code": "ok", "message": ""}}


@pytest.fixture
def calls(monkeypatch):
    """Record every request and answer it from a scripted queue."""
    seen = []
    replies = []

    def fake_request(method, url, token, payload=None, params=None):
        seen.append({"method": method, "url": url, "token": token,
                     "payload": payload, "params": params})
        if not replies:
            raise AssertionError(f"unscripted call to {url}")
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(tiktok, "_request", fake_request)
    return {"seen": seen, "replies": replies}


# ---------- configuration ----------

def test_has_key_follows_the_env(monkeypatch):
    monkeypatch.delenv("TIKTOK_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("TIKTOK_TOKEN", raising=False)
    assert tiktok.has_key() is False
    monkeypatch.setenv("TIKTOK_ACCESS_TOKEN", "tok")
    assert tiktok.has_key() is True
    assert tiktok.access_token() == "tok"


def test_every_endpoint_is_a_module_constant():
    """A spec change should be a one-line fix, which is only true while
    no call site spells a URL out."""
    for url in (tiktok.PUBLISH_INIT_URL, tiktok.PUBLISH_STATUS_URL,
                tiktok.VIDEO_QUERY_URL):
        assert url.startswith(tiktok.API_ROOT)


# ---------- the publish dance ----------

def test_post_video_inits_with_pull_from_url_then_polls_to_complete(calls):
    calls["replies"].extend([
        ok({"publish_id": "pub-1"}),
        ok({"status": "PROCESSING_UPLOAD"}),
        ok({"status": "PUBLISH_COMPLETE",
            "publicaly_available_post_id": [7300000000000000001]}),
    ])
    result = tiktok.post_video("https://cdn.example/clip.mp4", "a caption",
                               "tok", sleep=lambda s: None)

    assert result["ok"] is True
    assert result["publish_id"] == "pub-1"
    assert result["video_id"] == "7300000000000000001"

    init = calls["seen"][0]
    assert init["url"] == tiktok.PUBLISH_INIT_URL
    assert init["payload"]["source_info"]["source"] == tiktok.SOURCE_PULL_FROM_URL
    assert init["payload"]["source_info"]["video_url"] == "https://cdn.example/clip.mp4"
    assert init["payload"]["post_info"]["title"] == "a caption"
    assert calls["seen"][1]["url"] == tiktok.PUBLISH_STATUS_URL
    assert calls["seen"][1]["payload"] == {"publish_id": "pub-1"}


def test_post_video_reports_the_step_it_died_at(calls):
    """"init failed" (an unverified URL domain) and "poll failed" (TikTok
    rejected the file) call for different fixes, so the step is part of
    the answer -- instagram.post_reel's contract exactly."""
    calls["replies"].append(RuntimeError("access_token_invalid"))
    result = tiktok.post_video("https://cdn.example/c.mp4", "c", "tok",
                               sleep=lambda s: None)
    assert result["ok"] is False
    assert result["step"] == "init"


def test_a_failed_publish_is_a_result_not_an_exception(calls):
    calls["replies"].extend([
        ok({"publish_id": "pub-2"}),
        ok({"status": "FAILED", "fail_reason": "video_format_unsupported"}),
    ])
    result = tiktok.post_video("https://cdn.example/c.mp4", "c", "tok",
                               sleep=lambda s: None)
    assert result["ok"] is False
    assert result["step"] == "poll"
    assert "video_format_unsupported" in result["error"]


def test_polling_gives_up_rather_than_claiming_a_post(calls):
    calls["replies"].extend([ok({"publish_id": "p"})]
                            + [ok({"status": "PROCESSING_UPLOAD"})] * 3)
    result = tiktok.post_video("https://cdn.example/c.mp4", "c", "act.longtoken",
                               poll_tries=3, sleep=lambda s: None)
    assert result["ok"] is False
    assert result["video_id"] is None
    assert "not published after 3 poll" in result["error"]


def test_tiktoks_error_envelope_inside_a_200_is_a_failure(calls):
    """The API answers 200 and reports the failure in the body; reading
    the status code alone would call that a published post."""
    calls["replies"].append({"data": {}, "error": {"code": "spam_risk_too_many_posts",
                                                   "message": "too many"}})
    result = tiktok.post_video("https://cdn.example/c.mp4", "c", "tok",
                               sleep=lambda s: None)
    assert result["ok"] is False
    assert "spam_risk_too_many_posts" in result["error"]


# ---------- the token never leaks ----------

def test_the_token_never_appears_in_error_text(calls):
    secret = "act.SUPERSECRETTOKEN123"
    calls["replies"].append(RuntimeError(f"401 for Bearer {secret}"))
    result = tiktok.post_video("https://cdn.example/c.mp4", "c", secret,
                               sleep=lambda s: None)
    assert secret not in result["error"]
    assert "<redacted>" in result["error"]


def test_the_token_never_leaks_out_of_a_metrics_failure(pg, calls):
    secret = "act.ANOTHERSECRET456"
    video_id = db.add_video("a tok", "tiktok", "2026-09-01",
                            url="https://www.tiktok.com/@zp/video/7300000000000000001",
                            dsn=pg, account_id=None)
    calls["replies"].append(RuntimeError(f"boom with {secret} in it"))
    result = tiktok.refresh_metrics_for_video(
        {"id": video_id, "platform": "tiktok",
         "url": "https://www.tiktok.com/@zp/video/7300000000000000001"},
        token=secret, db_path=pg)
    assert result["ok"] is False
    assert secret not in result["error"]


# ---------- ids ----------

@pytest.mark.parametrize("stored,expected", [
    ("7300000000000000001", "7300000000000000001"),
    ("tiktok://7300000000000000001", "7300000000000000001"),
    ("https://www.tiktok.com/@zeropage/video/7300000000000000001", "7300000000000000001"),
    ("https://www.tiktok.com/@zeropage", None),
    ("", None),
    (None, None),
])
def test_parse_video_id(stored, expected):
    assert tiktok.parse_video_id(stored) == expected


# ---------- metrics ----------

def test_refresh_metrics_records_a_snapshot(pg, calls):
    video_id = db.add_video("a tok", "tiktok", "2026-09-01",
                            url="https://www.tiktok.com/@zp/video/7300000000000000001",
                            dsn=pg, account_id=None)
    calls["replies"].append(ok({"videos": [{
        "id": "7300000000000000001", "view_count": 900, "like_count": 40,
        "comment_count": 5, "share_count": 3}]}))

    result = tiktok.refresh_metrics_for_video(
        {"id": video_id, "platform": "tiktok",
         "url": "https://www.tiktok.com/@zp/video/7300000000000000001"},
        token="tok", db_path=pg)

    assert result["ok"] is True
    assert (result["views"], result["likes"], result["shares"]) == (900, 40, 3)
    # the API exposes no save count; None is the honest answer, not 0
    assert result["saves"] is None
    assert calls["seen"][0]["url"] == tiktok.VIDEO_QUERY_URL
    assert "view_count" in calls["seen"][0]["params"]["fields"]

    with db.connect(pg) as conn:
        row = conn.execute("SELECT views, shares FROM metrics WHERE video_id = %s",
                           (video_id,)).fetchone()
    assert row["views"] == 900 and row["shares"] == 3


def test_refresh_metrics_guards_platform_and_token(pg):
    assert tiktok.refresh_metrics_for_video(
        {"id": 1, "platform": "youtube"}, token="t")["ok"] is False
    out = tiktok.refresh_metrics_for_video({"id": 1, "platform": "tiktok"},
                                           token=None)
    assert out["ok"] is False and "TIKTOK_ACCESS_TOKEN" in out["error"]


def test_an_unparseable_url_says_so_rather_than_guessing(pg):
    out = tiktok.refresh_metrics_for_video(
        {"id": 1, "platform": "tiktok", "url": "https://www.tiktok.com/@zp"},
        token="tok")
    assert out["ok"] is False
    assert "no video id" in out["error"]


# ---------- the autopilot adapter ----------

def test_execute_post_action_needs_a_public_url(monkeypatch):
    """Direct Post pulls the file itself, so a local path is a refusal
    with a reason rather than a failure inside TikTok's fetcher."""
    monkeypatch.setenv("TIKTOK_ACCESS_TOKEN", "tok")
    with pytest.raises(RuntimeError, match="public video_url"):
        tiktok.execute_post_action({"video_url": "/renders/clip.mp4"})


def test_execute_post_action_refuses_without_a_token(monkeypatch):
    monkeypatch.delenv("TIKTOK_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("TIKTOK_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="TIKTOK_ACCESS_TOKEN"):
        tiktok.execute_post_action({"video_url": "https://cdn.example/c.mp4"})


def test_execute_post_action_writes_the_result_back(monkeypatch, calls):
    monkeypatch.setenv("TIKTOK_ACCESS_TOKEN", "tok")
    calls["replies"].extend([
        ok({"publish_id": "pub-9"}),
        ok({"status": "PUBLISH_COMPLETE",
            "publicaly_available_post_id": ["7300000000000000009"]}),
    ])
    action = {"video_url": "https://cdn.example/c.mp4", "caption": "hi"}
    tiktok.execute_post_action(action)
    assert action["result"]["video_id"] == "7300000000000000009"


def test_a_failed_publish_raises_in_live_mode(monkeypatch, calls):
    """Live mode is the only mode that reaches here, and a failed live
    publish must surface so the caller records a failed row."""
    monkeypatch.setenv("TIKTOK_ACCESS_TOKEN", "tok")
    calls["replies"].append(RuntimeError("nope"))
    with pytest.raises(RuntimeError, match="tiktok publish failed"):
        tiktok.execute_post_action({"video_url": "https://cdn.example/c.mp4"})
