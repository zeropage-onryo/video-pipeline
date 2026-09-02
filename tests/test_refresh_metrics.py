"""
The nightly analytics sweep never takes itself down on a missing key or
a failed call -- it records the failure per platform and moves on, the
same contract as the per-video refreshers. (Postgres-backed promotion is
not exercised here; refresh_all is the pure, hermetic half.)
"""
from src import db, refresh_metrics


def test_refresh_all_records_missing_key_without_raising(tmp_path, monkeypatch):
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    path = tmp_path / "m.db"
    db.init_db(path)
    db.add_video("clip one", "youtube", "2026-08-01",
                 url="https://youtu.be/abc123", path=path, account_id=None)

    summary = refresh_metrics.refresh_all(platform="youtube", db_path=path)
    assert summary["youtube"]["videos"] == 1
    assert summary["youtube"]["refreshed"] == 0
    assert summary["youtube"]["failed"] == 1
    assert any("YOUTUBE_API_KEY" in e for e in summary["youtube"]["errors"])


def test_refresh_all_empty_db_is_an_empty_summary(tmp_path):
    path = tmp_path / "empty.db"
    db.init_db(path)
    assert refresh_metrics.refresh_all(db_path=path) == {}


def test_unwired_platform_is_reported_not_raised(tmp_path):
    path = tmp_path / "m.db"
    db.init_db(path)
    results = refresh_metrics._refresh_platform("tiktok", [{"id": 1}], db_path=path)
    assert results and results[0]["ok"] is False
    assert "not wired" in results[0]["error"]
