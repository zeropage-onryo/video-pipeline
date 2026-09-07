"""
The nightly analytics sweep never takes itself down on a missing key or
a failed call -- it records the failure per platform and moves on, the
same contract as the per-video refreshers. (Postgres-backed promotion is
not exercised here; refresh_all is the pure, hermetic half.)
"""
from src import db, refresh_metrics


def test_refresh_all_records_missing_key_without_raising(pg, monkeypatch):
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    path = pg
    db.add_video("clip one", "youtube", "2026-08-01",
                 url="https://youtu.be/abc123", dsn=path, account_id=None)

    summary = refresh_metrics.refresh_all(platform="youtube", db_path=path)
    assert summary["youtube"]["videos"] == 1
    assert summary["youtube"]["refreshed"] == 0
    assert summary["youtube"]["failed"] == 1
    assert any("YOUTUBE_API_KEY" in e for e in summary["youtube"]["errors"])


def test_refresh_all_empty_db_is_an_empty_summary(pg):
    path = pg
    assert refresh_metrics.refresh_all(db_path=path) == {}


def test_unwired_platform_is_reported_not_raised(pg):
    """Facebook is the last stub (BACKLOG #4); TikTok left this branch
    on 2026-09-07 when src/tiktok.py landed."""
    path = pg
    results = refresh_metrics._refresh_platform("facebook", [{"id": 1}], db_path=path)
    assert results and results[0]["ok"] is False
    assert "not wired" in results[0]["error"]


def test_tiktok_is_in_the_sweep_and_reports_a_missing_token(pg, monkeypatch):
    """Wired means it goes through tiktok.refresh_metrics_for_video --
    which, with no token, is a recorded failure, not a stub message and
    not an exception."""
    monkeypatch.delenv("TIKTOK_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("TIKTOK_TOKEN", raising=False)
    path = pg
    db.add_video("a tok", "tiktok", "2026-09-01",
                 url="https://www.tiktok.com/@zp/video/7300000000000000001",
                 dsn=path, account_id=None)

    summary = refresh_metrics.refresh_all(platform="tiktok", db_path=path)
    assert summary["tiktok"]["videos"] == 1
    assert summary["tiktok"]["failed"] == 1
    assert any("TIKTOK_ACCESS_TOKEN" in e for e in summary["tiktok"]["errors"])
    assert "tiktok" in refresh_metrics.WIRED_PLATFORMS
