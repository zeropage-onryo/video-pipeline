"""
A refresh records against the video's OWN account (2026-09-22).

Found by running the sweep against the live database: every caller --
`src.refresh_metrics`, the app's refresh routes -- called the platform
refreshers without an account, `db.record_metrics` scopes on it, and an
owned video was "not found" at the write. That was a ValueError out of a
function whose whole contract is never raising, so the nightly sweep
died on its first owned Instagram video, and no owned video anywhere has
had a snapshot recorded by a refresh since videos became owned rows.

The video dict comes off `SELECT *` and carries `account_id`; the
refreshers now write against that when the caller passes none, and a
write that fails anyway is a result, not an exception.
"""
import pytest

from src import accounts, db, instagram, tiktok, youtube


@pytest.fixture
def tmp_db(pg):
    """A throwaway database with ONE real account: videos.account_id is a
    foreign key, so an owned video needs an owner row to exist."""
    accounts.init(pg)
    accounts.seed("mike@example.com", dsn=pg)
    return pg


def _owner(tmp_db) -> int:
    with db.connect(tmp_db) as conn:
        return int(conn.execute("SELECT MIN(id) FROM accounts").fetchone()[0])


def _owned(tmp_db, platform, url):
    owner = _owner(tmp_db)
    vid = db.add_video("Owned", platform, "2026-09-01", url=url, dsn=tmp_db, account_id=owner)
    return db.get_video(vid, dsn=tmp_db, account_id=owner)


def _snapshots(tmp_db, vid):
    return db.get_video_history(vid, dsn=tmp_db, account_id=_owner(tmp_db))


def test_instagram_refresh_records_against_the_videos_owner(tmp_db, monkeypatch):
    video = _owned(tmp_db, "instagram", "ig://17900000000000001")
    monkeypatch.setattr(instagram, "fetch_media_insights",
                        lambda media_id, token: {"views": 12, "likes": 3})
    result = instagram.refresh_metrics_for_video(video, token="tok", db_path=tmp_db)
    assert result["ok"] is True, result
    assert _snapshots(tmp_db, video["id"])[-1]["views"] == 12


def test_youtube_refresh_records_against_the_videos_owner(tmp_db, monkeypatch):
    video = _owned(tmp_db, "youtube", "https://youtu.be/abc123xyz00")
    monkeypatch.setattr(youtube, "fetch_video_stats",
                        lambda video_id, key: {"views": 40, "likes": 4, "comments": 1})
    result = youtube.refresh_metrics_for_video(video, api_key="k", db_path=tmp_db)
    assert result["ok"] is True, result
    assert _snapshots(tmp_db, video["id"])[-1]["views"] == 40


def test_tiktok_refresh_records_against_the_videos_owner(tmp_db, monkeypatch):
    video = _owned(tmp_db, "tiktok", "https://www.tiktok.com/@zp/video/7300000000000000001")
    monkeypatch.setattr(tiktok, "fetch_video_stats",
                        lambda ids, token: {str(ids[0]): {"view_count": 7, "like_count": 1,
                                                          "comment_count": 0, "share_count": 0}})
    result = tiktok.refresh_metrics_for_video(video, token="tok", db_path=tmp_db)
    assert result["ok"] is True, result
    assert _snapshots(tmp_db, video["id"])[-1]["views"] == 7


def test_an_explicit_account_still_wins_and_a_wrong_one_is_a_result_not_a_raise(tmp_db, monkeypatch):
    video = _owned(tmp_db, "instagram", "ig://17900000000000002")
    monkeypatch.setattr(instagram, "fetch_media_insights", lambda m, t: {"views": 1})
    result = instagram.refresh_metrics_for_video(video, token="tok", db_path=tmp_db,
                                                 account_id=None)
    assert result["ok"] is True
    # a caller that names the WRONG account gets a result, never a raise
    result = instagram.refresh_metrics_for_video(video, token="tok", db_path=tmp_db,
                                                 account_id=_owner(tmp_db) + 1000)
    assert result["ok"] is False
    assert "metrics not recorded" in result["error"]
    assert len(_snapshots(tmp_db, video["id"])) == 1
