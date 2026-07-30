"""
Tests for db.py.

The two that matter:
  test_selection_is_recorded_as_a_label   - the pick becomes training data
  test_old_video_does_not_win_on_totals   - why metrics is its own table
"""

import json

import pytest

from src import db

# the exact shape pitch.py already emits
PITCHES = [
    {"number": n, "title": f"Story {n}", "logline": f"Line {n}.",
     "story_note": f"Opens on A037_0812_C00{n}.mov."}
    for n in range(1, 11)
]


@pytest.fixture
def tmp_db(tmp_path):
    path = tmp_path / "test.db"
    db.init_db(path)
    return path


def test_init_creates_tables(tmp_db):
    assert db.summary(tmp_db) == {
        "pitch_runs": 0, "ideas": 0, "videos": 0, "metrics": 0
    }


def test_save_pitch_run_stores_all_ten(tmp_db):
    run_id = db.save_pitch_run(PITCHES, model="gemini-3-flash-preview",
                               clip_count=42, path=tmp_db)
    assert run_id == 1
    assert db.summary(tmp_db)["ideas"] == 10


def test_empty_run_rejected(tmp_db):
    with pytest.raises(ValueError, match="no pitches"):
        db.save_pitch_run([], path=tmp_db)


def test_pitch_without_title_rejected(tmp_db):
    with pytest.raises(ValueError, match="no title"):
        db.save_pitch_run([{"number": 1, "logline": "x"}], path=tmp_db)


def test_failed_run_leaves_nothing_behind(tmp_db):
    """A bad pitch mid-batch must not leave a half-written run."""
    bad = PITCHES[:3] + [{"number": 4, "logline": "no title here"}]
    with pytest.raises(ValueError):
        db.save_pitch_run(bad, path=tmp_db)
    assert db.summary(tmp_db) == {
        "pitch_runs": 0, "ideas": 0, "videos": 0, "metrics": 0
    }


def test_prompt_hash_changes_with_prompt(tmp_db):
    db.save_pitch_run(PITCHES, prompt_template="version one", path=tmp_db)
    db.save_pitch_run(PITCHES, prompt_template="version two", path=tmp_db)
    with db.connect(tmp_db) as conn:
        hashes = [r[0] for r in conn.execute(
            "SELECT prompt_hash FROM pitch_runs ORDER BY id")]
    assert hashes[0] != hashes[1]
    assert all(h is not None for h in hashes)


def test_selection_is_recorded_as_a_label(tmp_db):
    run_id = db.save_pitch_run(PITCHES, path=tmp_db)
    updated = db.mark_selected_by_number(run_id, [2, 5, 9], path=tmp_db)
    assert updated == 3

    chosen = db.get_labelled_pitches(selected_only=True, path=tmp_db)
    assert sorted(c["number"] for c in chosen) == [2, 5, 9]

    everything = db.get_labelled_pitches(path=tmp_db)
    assert len(everything) == 10
    assert sum(e["selected"] for e in everything) == 3


def test_unreviewed_runs_are_excluded(tmp_db):
    """A run where nothing was picked might just never have been reviewed."""
    db.save_pitch_run(PITCHES, path=tmp_db)
    reviewed = db.save_pitch_run(PITCHES, path=tmp_db)
    db.mark_selected_by_number(reviewed, [1], path=tmp_db)

    assert len(db.get_labelled_pitches(path=tmp_db)) == 10


def test_selection_rate_splits_by_prompt_version(tmp_db):
    old = db.save_pitch_run(PITCHES, prompt_template="old", path=tmp_db)
    db.mark_selected_by_number(old, [1, 2], path=tmp_db)
    new = db.save_pitch_run(PITCHES, prompt_template="new", path=tmp_db)
    db.mark_selected_by_number(new, [1, 2, 3, 4], path=tmp_db)

    stats = db.selection_rate(tmp_db)
    assert stats["pitched"] == 20
    assert stats["chosen"] == 6
    rates = sorted(b["rate"] for b in stats["by_prompt"])
    assert rates == [0.2, 0.4]


def test_selection_rate_empty_is_safe(tmp_db):
    assert db.selection_rate(tmp_db)["rate"] is None


def test_video_links_back_to_its_pitch(tmp_db):
    run_id = db.save_pitch_run(PITCHES, path=tmp_db)
    with db.connect(tmp_db) as conn:
        idea_id = conn.execute(
            "SELECT id FROM ideas WHERE run_id = ? AND number = 2",
            (run_id,)).fetchone()[0]

    vid = db.add_video("Story 2", "tiktok", "2026-07-01",
                       idea_id=idea_id, timeline="Story 2", path=tmp_db)
    db.record_metrics(vid, views=5000, captured_at="2026-07-08", path=tmp_db)

    top = db.get_top_performers(path=tmp_db)
    assert top[0]["logline"] == "Line 2."


def test_bad_platform_rejected(tmp_db):
    with pytest.raises(ValueError, match="platform"):
        db.add_video("x", "myspace", "2026-07-01", path=tmp_db)


def test_bad_date_rejected(tmp_db):
    with pytest.raises(ValueError, match="posted_at"):
        db.add_video("x", "tiktok", "last tuesday", path=tmp_db)


def test_metrics_for_missing_video_rejected(tmp_db):
    with pytest.raises(ValueError, match="no video"):
        db.record_metrics(999, views=10, path=tmp_db)


def test_one_idea_two_platforms(tmp_db):
    a = db.add_video("Story 1", "tiktok", "2026-07-01", path=tmp_db)
    b = db.add_video("Story 1", "youtube", "2026-07-01", path=tmp_db)
    assert a != b
    assert len(db.list_videos(platform="tiktok", path=tmp_db)) == 1


def test_snapshots_accumulate(tmp_db):
    vid = db.add_video("clip", "tiktok", "2026-07-01", path=tmp_db)
    db.record_metrics(vid, views=1000, captured_at="2026-07-02", path=tmp_db)
    db.record_metrics(vid, views=9000, captured_at="2026-07-20", path=tmp_db)
    history = db.get_video_history(vid, path=tmp_db)
    assert [h["views"] for h in history] == [1000, 9000]
    assert history[0]["age_days"] == 1.0


def test_same_timestamp_updates_in_place(tmp_db):
    vid = db.add_video("clip", "tiktok", "2026-07-01", path=tmp_db)
    db.record_metrics(vid, views=100, captured_at="2026-07-02", path=tmp_db)
    db.record_metrics(vid, views=150, captured_at="2026-07-02", path=tmp_db)
    assert len(db.get_video_history(vid, path=tmp_db)) == 1


def test_old_video_does_not_win_on_totals(tmp_db):
    old = db.add_video("old", "tiktok", "2025-01-01", path=tmp_db)
    db.record_metrics(old, views=2_000, captured_at="2025-01-08", path=tmp_db)
    db.record_metrics(old, views=90_000, captured_at="2026-07-01", path=tmp_db)

    new = db.add_video("new", "tiktok", "2026-07-01", path=tmp_db)
    db.record_metrics(new, views=30_000, captured_at="2026-07-08", path=tmp_db)

    top = db.get_top_performers(at_days=7, path=tmp_db)
    assert top[0]["title"] == "new"
    assert top[1]["score"] == 2_000
    assert top[1]["measured_at_days"] == 7.0


def test_top_performers_filters_by_platform(tmp_db):
    a = db.add_video("tt", "tiktok", "2026-07-01", path=tmp_db)
    b = db.add_video("yt", "youtube", "2026-07-01", path=tmp_db)
    db.record_metrics(a, views=100, captured_at="2026-07-08", path=tmp_db)
    db.record_metrics(b, views=999, captured_at="2026-07-08", path=tmp_db)
    top = db.get_top_performers(platform="tiktok", path=tmp_db)
    assert len(top) == 1 and top[0]["title"] == "tt"


def test_bad_metric_name_rejected(tmp_db):
    with pytest.raises(ValueError, match="metric must be"):
        db.get_top_performers(metric="views; DROP TABLE videos", path=tmp_db)


def test_import_existing_pitches_file(tmp_db, tmp_path):
    f = tmp_path / "pitches.json"
    f.write_text(json.dumps(PITCHES))
    run_id = db.import_pitches_file(f, path=tmp_db)
    assert run_id == 1
    assert db.summary(tmp_db)["ideas"] == 10


# ---------- posting window ----------

from datetime import datetime, timedelta, timezone  # noqa: E402


def _days_ago(n: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=n)).date().isoformat()


def _post(tmp_db, title, days_ago, views, platform="tiktok"):
    """A video posted N days ago, measured at 7 days old."""
    posted = _days_ago(days_ago)
    vid = db.add_video(title, platform, posted, path=tmp_db)
    measured = (datetime.fromisoformat(posted)
                + timedelta(days=7)).date().isoformat()
    db.record_metrics(vid, views=views, captured_at=measured, path=tmp_db)
    return vid


def test_window_excludes_older_videos(tmp_db):
    _post(tmp_db, "ancient banger", 400, 90_000)
    _post(tmp_db, "recent solid", 30, 20_000)

    all_time = db.get_top_performers(path=tmp_db)
    assert all_time[0]["title"] == "ancient banger"

    recent = db.get_top_performers(posted_within_days=180, path=tmp_db)
    assert [r["title"] for r in recent] == ["recent solid"]


def test_six_month_window_keeps_everything_inside_it(tmp_db):
    for n, days in enumerate([5, 60, 120, 179]):
        _post(tmp_db, f"v{n}", days, 1000 * (n + 1))
    assert len(db.get_top_performers(
        posted_within_days=180, limit=50, path=tmp_db)) == 4


def test_boundary_day_is_included(tmp_db):
    """
    posted_at is often date-only. A datetime cutoff would compare
    lexically and silently drop a video posted on the boundary day.
    """
    _post(tmp_db, "exactly on the edge", 180, 5000)
    got = db.get_top_performers(posted_within_days=180, path=tmp_db)
    assert [r["title"] for r in got] == ["exactly on the edge"]


def test_window_composes_with_platform(tmp_db):
    _post(tmp_db, "tt recent", 10, 100, platform="tiktok")
    _post(tmp_db, "yt recent", 10, 999, platform="youtube")
    _post(tmp_db, "tt old", 400, 50_000, platform="tiktok")

    got = db.get_top_performers(
        posted_within_days=180, platform="tiktok", path=tmp_db)
    assert [r["title"] for r in got] == ["tt recent"]


def test_window_composes_with_at_days(tmp_db):
    """Recency filter and measurement age are independent."""
    posted = _days_ago(30)
    vid = db.add_video("slow burner", "tiktok", posted, path=tmp_db)
    d = datetime.fromisoformat(posted)
    db.record_metrics(vid, views=500,
                      captured_at=(d + timedelta(days=1)).date().isoformat(),
                      path=tmp_db)
    db.record_metrics(vid, views=40_000,
                      captured_at=(d + timedelta(days=28)).date().isoformat(),
                      path=tmp_db)

    at7 = db.get_top_performers(at_days=7, posted_within_days=180, path=tmp_db)
    at28 = db.get_top_performers(at_days=28, posted_within_days=180, path=tmp_db)
    assert at7[0]["score"] == 500
    assert at28[0]["score"] == 40_000


def test_posted_since_explicit_date(tmp_db):
    _post(tmp_db, "before", 400, 9000)
    _post(tmp_db, "after", 10, 100)
    cutoff = _days_ago(90)
    got = db.get_top_performers(posted_since=cutoff, path=tmp_db)
    assert [r["title"] for r in got] == ["after"]


def test_both_window_args_rejected(tmp_db):
    with pytest.raises(ValueError, match="not both"):
        db.get_top_performers(posted_within_days=180,
                              posted_since="2026-01-01", path=tmp_db)


def test_zero_window_rejected(tmp_db):
    with pytest.raises(ValueError, match="at least 1"):
        db.get_top_performers(posted_within_days=0, path=tmp_db)


def test_bad_since_date_rejected(tmp_db):
    with pytest.raises(ValueError, match="since"):
        db.get_top_performers(posted_since="six months ago", path=tmp_db)


def test_ascending_returns_the_duds(tmp_db):
    _post(tmp_db, "hit", 10, 50_000)
    _post(tmp_db, "flop", 10, 200)
    worst = db.get_top_performers(ascending=True, posted_within_days=180,
                                  path=tmp_db)
    assert worst[0]["title"] == "flop"


def test_empty_window_is_safe(tmp_db):
    _post(tmp_db, "old", 400, 9000)
    assert db.get_top_performers(posted_within_days=30, path=tmp_db) == []


# ---------- benchmark ----------

def test_benchmark_median_odd_count(tmp_db):
    for n, v in enumerate([100, 300, 900]):
        _post(tmp_db, f"v{n}", 10, v)
    b = db.benchmark(posted_within_days=180, path=tmp_db)
    assert b == {"n": 3, "median": 300, "best": 900, "worst": 100}


def test_benchmark_median_even_count(tmp_db):
    for n, v in enumerate([100, 200, 300, 500]):
        _post(tmp_db, f"v{n}", 10, v)
    assert db.benchmark(posted_within_days=180, path=tmp_db)["median"] == 250


def test_benchmark_respects_the_window(tmp_db):
    _post(tmp_db, "old huge", 400, 100_000)
    _post(tmp_db, "recent a", 10, 100)
    _post(tmp_db, "recent b", 20, 300)
    b = db.benchmark(posted_within_days=180, path=tmp_db)
    assert b["n"] == 2 and b["median"] == 200


def test_benchmark_empty_is_safe(tmp_db):
    assert db.benchmark(path=tmp_db) == {
        "n": 0, "median": None, "best": None, "worst": None}


# ---------- distinct_video_field_values ----------

def test_distinct_video_field_values_returns_sorted_unique(tmp_db):
    db.add_video("a", "tiktok", "2026-01-01", topic="workshop", path=tmp_db)
    db.add_video("b", "tiktok", "2026-01-02", topic="workshop", path=tmp_db)
    db.add_video("c", "tiktok", "2026-01-03", topic="commute", path=tmp_db)
    assert db.distinct_video_field_values("topic", path=tmp_db) == ["commute", "workshop"]


def test_distinct_video_field_values_excludes_blank(tmp_db):
    db.add_video("a", "tiktok", "2026-01-01", topic="workshop", path=tmp_db)
    db.add_video("b", "tiktok", "2026-01-02", path=tmp_db)
    assert db.distinct_video_field_values("topic", path=tmp_db) == ["workshop"]


def test_distinct_video_field_values_rejects_unknown_field(tmp_db):
    with pytest.raises(ValueError, match="field must be one of"):
        db.distinct_video_field_values("title", path=tmp_db)


# ---------- latest_metrics_by_video ----------

def test_latest_metrics_by_video_with_no_snapshot_yet(tmp_db):
    vid = db.add_video("a", "tiktok", "2026-01-01", path=tmp_db)
    rows = db.latest_metrics_by_video(path=tmp_db)
    assert rows[0]["video_id"] == vid
    assert rows[0]["views"] is None


def test_latest_metrics_by_video_returns_most_recent_snapshot(tmp_db):
    vid = db.add_video("a", "tiktok", "2026-01-01", path=tmp_db)
    db.record_metrics(vid, views=100, captured_at="2026-01-02", path=tmp_db)
    db.record_metrics(vid, views=500, captured_at="2026-01-10", path=tmp_db)
    rows = db.latest_metrics_by_video(path=tmp_db)
    assert rows[0]["views"] == 500


# ---------- get_video ----------

def test_get_video_returns_none_for_missing_id(tmp_db):
    assert db.get_video(999, path=tmp_db) is None


def test_get_video_includes_metadata(tmp_db):
    vid = db.add_video("Night Run", "youtube", "2026-01-01",
                       url="https://x", topic="workshop", path=tmp_db)
    video = db.get_video(vid, path=tmp_db)
    assert video["title"] == "Night Run"
    assert video["platform"] == "youtube"
    assert video["url"] == "https://x"


def test_get_video_has_no_originating_pitch_when_not_linked(tmp_db):
    vid = db.add_video("Night Run", "youtube", "2026-01-01", path=tmp_db)
    video = db.get_video(vid, path=tmp_db)
    assert video["idea_id"] is None
    assert video["idea_title"] is None


def test_get_video_includes_originating_pitch_when_linked(tmp_db):
    run_id = db.save_pitch_run(PITCHES, path=tmp_db)
    with db.connect(tmp_db) as conn:
        idea_id = conn.execute(
            "SELECT id FROM ideas WHERE run_id = ? AND number = 2", (run_id,)
        ).fetchone()[0]
    vid = db.add_video("Story 2", "tiktok", "2026-01-01", idea_id=idea_id, path=tmp_db)

    video = db.get_video(vid, path=tmp_db)
    assert video["idea_title"] == "Story 2"
    assert video["idea_logline"] == "Line 2."
