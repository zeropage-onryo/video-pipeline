"""
Tests for scheduling.py -- the queue that owns the clock Meta doesn't.

The publish itself always goes through autopilot.execute, so the gate,
dry-run default, and kill switch apply unchanged; these tests pin that a
dry run publishes nothing (the API wrapper is a raising spy), that rows
are marked `publishing` before dispatch and `posted`/`failed` after, and
that the per-day cap holds. Queue management itself is not gated.
"""
import pytest

from src import autopilot, instagram, scheduling


@pytest.fixture
def tmp_db(pg):
    path = pg
    scheduling.init(path)
    return path


@pytest.fixture
def open_gate(tmp_path, monkeypatch):
    """Env enabled, posting approved for the run, no kill switch -- live
    is reachable when asked for."""
    monkeypatch.setenv(autopilot.ENABLE_ENV, "1")
    monkeypatch.setenv(autopilot.POST_ENV, "1")
    monkeypatch.setattr(autopilot, "KILL_SWITCH_PATH", tmp_path / "autopilot.off")


@pytest.fixture
def publish_spy(monkeypatch):
    """If any real publish wrapper fires, the test fails loudly."""
    def explode(*args, **kwargs):
        raise AssertionError("publish wrapper called -- the gate leaked")

    monkeypatch.setattr(instagram, "create_reel_container", explode)
    monkeypatch.setattr(instagram, "publish_container", explode)
    monkeypatch.setattr(instagram, "post_reel", explode)


# ---------- queue management (ungated) ----------

def test_add_and_list_work_without_any_gate_env(tmp_db, monkeypatch):
    monkeypatch.delenv(autopilot.ENABLE_ENV, raising=False)
    post_id = scheduling.add_post(
        "https://cdn.example/v.mp4", "caption", "2026-08-05T09:00:00",
        db_path=tmp_db,
    )
    queue = scheduling.list_queue(db_path=tmp_db)
    assert len(queue) == 1
    assert queue[0]["id"] == post_id
    assert queue[0]["status"] == "planned"
    assert queue[0]["platform"] == "instagram"


def test_due_posts_windowing(tmp_db):
    scheduling.add_post("u1", "c", "2026-08-04T09:00:00", db_path=tmp_db)
    scheduling.add_post("u2", "c", "2026-08-04T18:00:00", db_path=tmp_db)
    due = scheduling.due_posts("2026-08-04T12:00:00", db_path=tmp_db)
    assert [d["video_ref"] for d in due] == ["u1"]


def test_due_posts_excludes_non_planned_rows(tmp_db):
    post_id = scheduling.add_post("u1", "c", "2026-08-01T00:00:00", db_path=tmp_db)
    scheduling.mark_status(post_id, "posted", media_id="m1", db_path=tmp_db)
    assert scheduling.due_posts("2026-08-04T00:00:00", db_path=tmp_db) == []


# ---------- run_due: dry-run publishes nothing ----------

def test_dry_run_publishes_nothing_and_leaves_rows_planned(
        tmp_db, open_gate, publish_spy):
    scheduling.add_post("https://x/v.mp4", "c", "2026-08-01T00:00:00", db_path=tmp_db)
    result = scheduling.run_due(now="2026-08-04T00:00:00", db_path=tmp_db)

    assert result["published"] == 0
    assert len(result["would_publish"]) == 1
    queue = scheduling.list_queue(db_path=tmp_db)
    assert queue[0]["status"] == "planned"      # untouched, ready for the real run


def test_gate_disabled_beats_live_flags(tmp_db, publish_spy, tmp_path, monkeypatch):
    monkeypatch.delenv(autopilot.ENABLE_ENV, raising=False)
    monkeypatch.setattr(autopilot, "KILL_SWITCH_PATH", tmp_path / "autopilot.off")
    scheduling.add_post("https://x/v.mp4", "c", "2026-08-01T00:00:00", db_path=tmp_db)

    result = scheduling.run_due(now="2026-08-04T00:00:00", approve=True, live=True,
                                db_path=tmp_db)
    assert result["published"] == 0
    assert result["mode"] == "disabled"
    assert scheduling.list_queue(db_path=tmp_db)[0]["status"] == "planned"


# ---------- run_due: live path ----------

def _wire_fake_adapter(monkeypatch, outcome):
    """Replace the post executor with a controllable fake."""
    def adapter(action):
        if isinstance(outcome, Exception):
            raise outcome
        action["result"] = outcome

    monkeypatch.setitem(autopilot.EXECUTORS, "post", adapter)


def test_live_marks_publishing_then_posted_with_media_id(
        tmp_db, open_gate, monkeypatch):
    transitions = []
    real_mark = scheduling.mark_status

    def recording_mark(post_id, status, **kwargs):
        transitions.append(status)
        return real_mark(post_id, status, **kwargs)

    monkeypatch.setattr(scheduling, "mark_status", recording_mark)
    _wire_fake_adapter(monkeypatch, {"ok": True, "media_id": "media-9"})
    # quota check is a network call in live mode; stub it permissive
    monkeypatch.setattr(scheduling, "_quota_remaining", lambda: 99)

    scheduling.add_post("https://x/v.mp4", "c", "2026-08-01T00:00:00", db_path=tmp_db)
    result = scheduling.run_due(now="2026-08-04T00:00:00", approve=True, live=True,
                                db_path=tmp_db)

    assert result["published"] == 1
    assert transitions[0] == "publishing"       # marked BEFORE dispatch
    assert transitions[-1] == "posted"
    row = scheduling.list_queue(db_path=tmp_db)[0]
    assert row["status"] == "posted"
    assert row["media_id"] == "media-9"


def test_live_failure_marks_failed_with_redacted_error(
        tmp_db, open_gate, monkeypatch):
    monkeypatch.setenv("IG_ACCESS_TOKEN", "sekrit-tok")
    _wire_fake_adapter(monkeypatch, RuntimeError("denied for sekrit-tok"))
    monkeypatch.setattr(scheduling, "_quota_remaining", lambda: 99)

    scheduling.add_post("https://x/v.mp4", "c", "2026-08-01T00:00:00", db_path=tmp_db)
    result = scheduling.run_due(now="2026-08-04T00:00:00", approve=True, live=True,
                                db_path=tmp_db)

    assert result["published"] == 0
    row = scheduling.list_queue(db_path=tmp_db)[0]
    assert row["status"] == "failed"
    assert "sekrit-tok" not in (row["error"] or "")
    assert "<redacted>" in row["error"]


def test_daily_cap_respected(tmp_db, open_gate, monkeypatch):
    _wire_fake_adapter(monkeypatch, {"ok": True, "media_id": "m"})
    monkeypatch.setattr(scheduling, "_quota_remaining", lambda: 99)
    monkeypatch.setattr(scheduling, "DAILY_CAP", 2)

    for i in range(4):
        scheduling.add_post(f"https://x/v{i}.mp4", "c", "2026-08-01T00:00:00",
                            db_path=tmp_db)
    result = scheduling.run_due(now="2026-08-04T00:00:00", approve=True, live=True,
                                db_path=tmp_db)

    assert result["published"] == 2
    statuses = [r["status"] for r in scheduling.list_queue(db_path=tmp_db)]
    assert statuses.count("posted") == 2
    assert statuses.count("planned") == 2       # deferred, not failed


def test_quota_exhausted_defers_rather_than_posting(tmp_db, open_gate, monkeypatch):
    _wire_fake_adapter(monkeypatch, {"ok": True, "media_id": "m"})
    monkeypatch.setattr(scheduling, "_quota_remaining", lambda: 0)

    scheduling.add_post("https://x/v.mp4", "c", "2026-08-01T00:00:00", db_path=tmp_db)
    result = scheduling.run_due(now="2026-08-04T00:00:00", approve=True, live=True,
                                db_path=tmp_db)
    assert result["published"] == 0
    assert scheduling.list_queue(db_path=tmp_db)[0]["status"] == "planned"


# ---------- caption fallback ----------

def test_build_caption_falls_back_without_a_model(monkeypatch, tmp_db):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    caption = scheduling.build_caption("fallback caption", db_path=tmp_db)
    assert caption == "fallback caption"
