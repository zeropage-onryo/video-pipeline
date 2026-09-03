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


def test_init_creates_tables(pg):
    assert db.summary(pg) == {
        "pitch_runs": 0, "ideas": 0, "videos": 0, "metrics": 0
    }


def test_save_pitch_run_stores_all_ten(pg):
    run_id = db.save_pitch_run(PITCHES, model="gemini-3-flash-preview",
                               clip_count=42, dsn=pg)
    assert run_id == 1
    assert db.summary(pg)["ideas"] == 10


def test_empty_run_rejected(pg):
    with pytest.raises(ValueError, match="no pitches"):
        db.save_pitch_run([], dsn=pg)


def test_pitch_without_title_rejected(pg):
    with pytest.raises(ValueError, match="no title"):
        db.save_pitch_run([{"number": 1, "logline": "x"}], dsn=pg)


def test_failed_run_leaves_nothing_behind(pg):
    """A bad pitch mid-batch must not leave a half-written run."""
    bad = PITCHES[:3] + [{"number": 4, "logline": "no title here"}]
    with pytest.raises(ValueError):
        db.save_pitch_run(bad, dsn=pg)
    assert db.summary(pg) == {
        "pitch_runs": 0, "ideas": 0, "videos": 0, "metrics": 0
    }


def test_prompt_hash_changes_with_prompt(pg):
    db.save_pitch_run(PITCHES, prompt_template="version one", dsn=pg)
    db.save_pitch_run(PITCHES, prompt_template="version two", dsn=pg)
    with db.connect(pg) as conn:
        hashes = [r[0] for r in conn.execute(
            "SELECT prompt_hash FROM pitch_runs ORDER BY id")]
    assert hashes[0] != hashes[1]
    assert all(h is not None for h in hashes)


def test_selection_is_recorded_as_a_label(pg):
    run_id = db.save_pitch_run(PITCHES, dsn=pg)
    updated = db.mark_selected_by_number(run_id, [2, 5, 9], dsn=pg)
    assert updated == 3

    chosen = db.get_labelled_pitches(selected_only=True, dsn=pg)
    assert sorted(c["number"] for c in chosen) == [2, 5, 9]

    everything = db.get_labelled_pitches(dsn=pg)
    assert len(everything) == 10
    assert sum(e["selected"] for e in everything) == 3


def test_unreviewed_runs_are_excluded(pg):
    """A run where nothing was picked might just never have been reviewed."""
    db.save_pitch_run(PITCHES, dsn=pg)
    reviewed = db.save_pitch_run(PITCHES, dsn=pg)
    db.mark_selected_by_number(reviewed, [1], dsn=pg)

    assert len(db.get_labelled_pitches(dsn=pg)) == 10


def test_selection_rate_splits_by_prompt_version(pg):
    old = db.save_pitch_run(PITCHES, prompt_template="old", dsn=pg)
    db.mark_selected_by_number(old, [1, 2], dsn=pg)
    new = db.save_pitch_run(PITCHES, prompt_template="new", dsn=pg)
    db.mark_selected_by_number(new, [1, 2, 3, 4], dsn=pg)

    stats = db.selection_rate(pg)
    assert stats["pitched"] == 20
    assert stats["chosen"] == 6
    rates = sorted(b["rate"] for b in stats["by_prompt"])
    assert rates == [0.2, 0.4]


def test_selection_rate_empty_is_safe(pg):
    assert db.selection_rate(pg)["rate"] is None


def test_video_links_back_to_its_pitch(pg):
    run_id = db.save_pitch_run(PITCHES, dsn=pg)
    with db.connect(pg) as conn:
        idea_id = conn.execute(
            "SELECT id FROM ideas WHERE run_id = %s AND number = 2",
            (run_id,)).fetchone()[0]

    vid = db.add_video("Story 2", "tiktok", "2026-07-01",
                       idea_id=idea_id, timeline="Story 2", dsn=pg, account_id=None)
    db.record_metrics(vid, views=5000, captured_at="2026-07-08", dsn=pg, account_id=None)

    top = db.get_top_performers(dsn=pg, account_id=None)
    assert top[0]["logline"] == "Line 2."


def test_bad_platform_rejected(pg):
    with pytest.raises(ValueError, match="platform"):
        db.add_video("x", "myspace", "2026-07-01", dsn=pg, account_id=None)


def test_bad_date_rejected(pg):
    with pytest.raises(ValueError, match="posted_at"):
        db.add_video("x", "tiktok", "last tuesday", dsn=pg, account_id=None)


def test_metrics_for_missing_video_rejected(pg):
    with pytest.raises(ValueError, match="no video"):
        db.record_metrics(999, views=10, dsn=pg, account_id=None)


def test_one_idea_two_platforms(pg):
    a = db.add_video("Story 1", "tiktok", "2026-07-01", dsn=pg, account_id=None)
    b = db.add_video("Story 1", "youtube", "2026-07-01", dsn=pg, account_id=None)
    assert a != b
    assert len(db.list_videos(platform="tiktok", dsn=pg, account_id=None)) == 1


def test_snapshots_accumulate(pg):
    vid = db.add_video("clip", "tiktok", "2026-07-01", dsn=pg, account_id=None)
    db.record_metrics(vid, views=1000, captured_at="2026-07-02", dsn=pg, account_id=None)
    db.record_metrics(vid, views=9000, captured_at="2026-07-20", dsn=pg, account_id=None)
    history = db.get_video_history(vid, dsn=pg, account_id=None)
    assert [h["views"] for h in history] == [1000, 9000]
    assert history[0]["age_days"] == 1.0


def test_same_timestamp_updates_in_place(pg):
    vid = db.add_video("clip", "tiktok", "2026-07-01", dsn=pg, account_id=None)
    db.record_metrics(vid, views=100, captured_at="2026-07-02", dsn=pg, account_id=None)
    db.record_metrics(vid, views=150, captured_at="2026-07-02", dsn=pg, account_id=None)
    assert len(db.get_video_history(vid, dsn=pg, account_id=None)) == 1


def test_old_video_does_not_win_on_totals(pg):
    old = db.add_video("old", "tiktok", "2025-01-01", dsn=pg, account_id=None)
    db.record_metrics(old, views=2_000, captured_at="2025-01-08", dsn=pg, account_id=None)
    db.record_metrics(old, views=90_000, captured_at="2026-07-01", dsn=pg, account_id=None)

    new = db.add_video("new", "tiktok", "2026-07-01", dsn=pg, account_id=None)
    db.record_metrics(new, views=30_000, captured_at="2026-07-08", dsn=pg, account_id=None)

    top = db.get_top_performers(at_days=7, dsn=pg, account_id=None)
    assert top[0]["title"] == "new"
    assert top[1]["score"] == 2_000
    assert top[1]["measured_at_days"] == 7.0


def test_top_performers_filters_by_platform(pg):
    a = db.add_video("tt", "tiktok", "2026-07-01", dsn=pg, account_id=None)
    b = db.add_video("yt", "youtube", "2026-07-01", dsn=pg, account_id=None)
    db.record_metrics(a, views=100, captured_at="2026-07-08", dsn=pg, account_id=None)
    db.record_metrics(b, views=999, captured_at="2026-07-08", dsn=pg, account_id=None)
    top = db.get_top_performers(platform="tiktok", dsn=pg, account_id=None)
    assert len(top) == 1 and top[0]["title"] == "tt"


def test_bad_metric_name_rejected(pg):
    with pytest.raises(ValueError, match="metric must be"):
        db.get_top_performers(metric="views; DROP TABLE videos", dsn=pg, account_id=None)


def test_import_existing_pitches_file(pg, tmp_path):
    f = tmp_path / "pitches.json"
    f.write_text(json.dumps(PITCHES))
    run_id = db.import_pitches_file(f, dsn=pg)
    assert run_id == 1
    assert db.summary(pg)["ideas"] == 10


# ---------- posting window ----------

from datetime import datetime, timedelta, timezone  # noqa: E402


def _days_ago(n: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=n)).date().isoformat()


def _post(pg, title, days_ago, views, platform="tiktok"):
    """A video posted N days ago, measured at 7 days old."""
    posted = _days_ago(days_ago)
    vid = db.add_video(title, platform, posted, dsn=pg, account_id=None)
    measured = (datetime.fromisoformat(posted)
                + timedelta(days=7)).date().isoformat()
    db.record_metrics(vid, views=views, captured_at=measured, dsn=pg, account_id=None)
    return vid


def test_window_excludes_older_videos(pg):
    _post(pg, "ancient banger", 400, 90_000)
    _post(pg, "recent solid", 30, 20_000)

    all_time = db.get_top_performers(dsn=pg, account_id=None)
    assert all_time[0]["title"] == "ancient banger"

    recent = db.get_top_performers(posted_within_days=180, dsn=pg, account_id=None)
    assert [r["title"] for r in recent] == ["recent solid"]


def test_six_month_window_keeps_everything_inside_it(pg):
    for n, days in enumerate([5, 60, 120, 179]):
        _post(pg, f"v{n}", days, 1000 * (n + 1))
    assert len(db.get_top_performers(
        posted_within_days=180, limit=50, dsn=pg, account_id=None)) == 4


def test_boundary_day_is_included(pg):
    """
    posted_at is often date-only. A datetime cutoff would compare
    lexically and silently drop a video posted on the boundary day.
    """
    _post(pg, "exactly on the edge", 180, 5000)
    got = db.get_top_performers(posted_within_days=180, dsn=pg, account_id=None)
    assert [r["title"] for r in got] == ["exactly on the edge"]


def test_window_composes_with_platform(pg):
    _post(pg, "tt recent", 10, 100, platform="tiktok")
    _post(pg, "yt recent", 10, 999, platform="youtube")
    _post(pg, "tt old", 400, 50_000, platform="tiktok")

    got = db.get_top_performers(
        posted_within_days=180, platform="tiktok", dsn=pg, account_id=None)
    assert [r["title"] for r in got] == ["tt recent"]


def test_window_composes_with_at_days(pg):
    """Recency filter and measurement age are independent."""
    posted = _days_ago(30)
    vid = db.add_video("slow burner", "tiktok", posted, dsn=pg, account_id=None)
    d = datetime.fromisoformat(posted)
    db.record_metrics(vid, views=500,
                      captured_at=(d + timedelta(days=1)).date().isoformat(),
                      dsn=pg, account_id=None)
    db.record_metrics(vid, views=40_000,
                      captured_at=(d + timedelta(days=28)).date().isoformat(),
                      dsn=pg, account_id=None)

    # Ages that the video actually has readings near. This test used to
    # ask at_days=7 and expect the day-1 reading, which was asserting the
    # bug: the closest snapshot won however far away it was.
    at1 = db.get_top_performers(at_days=1, posted_within_days=180, dsn=pg, account_id=None)
    at28 = db.get_top_performers(at_days=28, posted_within_days=180, dsn=pg, account_id=None)
    assert at1[0]["score"] == 500
    assert at28[0]["score"] == 40_000

    # and asking for an age it was never measured at returns nothing,
    # rather than quietly substituting a reading from a different week
    assert db.get_top_performers(at_days=7, posted_within_days=180, dsn=pg, account_id=None) == []


def test_posted_since_explicit_date(pg):
    _post(pg, "before", 400, 9000)
    _post(pg, "after", 10, 100)
    cutoff = _days_ago(90)
    got = db.get_top_performers(posted_since=cutoff, dsn=pg, account_id=None)
    assert [r["title"] for r in got] == ["after"]


def test_both_window_args_rejected(pg):
    with pytest.raises(ValueError, match="not both"):
        db.get_top_performers(posted_within_days=180,
                              posted_since="2026-01-01", dsn=pg, account_id=None)


def test_zero_window_rejected(pg):
    with pytest.raises(ValueError, match="at least 1"):
        db.get_top_performers(posted_within_days=0, dsn=pg, account_id=None)


def test_bad_since_date_rejected(pg):
    with pytest.raises(ValueError, match="since"):
        db.get_top_performers(posted_since="six months ago", dsn=pg, account_id=None)


def test_ascending_returns_the_duds(pg):
    _post(pg, "hit", 10, 50_000)
    _post(pg, "flop", 10, 200)
    worst = db.get_top_performers(ascending=True, posted_within_days=180,
                                  dsn=pg, account_id=None)
    assert worst[0]["title"] == "flop"


def test_empty_window_is_safe(pg):
    _post(pg, "old", 400, 9000)
    assert db.get_top_performers(posted_within_days=30, dsn=pg, account_id=None) == []


# ---------- benchmark ----------

def test_benchmark_median_odd_count(pg):
    for n, v in enumerate([100, 300, 900]):
        _post(pg, f"v{n}", 10, v)
    b = db.benchmark(posted_within_days=180, dsn=pg, account_id=None)
    assert b == {"n": 3, "median": 300, "best": 900, "worst": 100}


def test_benchmark_median_even_count(pg):
    for n, v in enumerate([100, 200, 300, 500]):
        _post(pg, f"v{n}", 10, v)
    assert db.benchmark(posted_within_days=180, dsn=pg, account_id=None)["median"] == 250


def test_benchmark_respects_the_window(pg):
    _post(pg, "old huge", 400, 100_000)
    _post(pg, "recent a", 10, 100)
    _post(pg, "recent b", 20, 300)
    b = db.benchmark(posted_within_days=180, dsn=pg, account_id=None)
    assert b["n"] == 2 and b["median"] == 200


def test_benchmark_empty_is_safe(pg):
    assert db.benchmark(dsn=pg, account_id=None) == {
        "n": 0, "median": None, "best": None, "worst": None}


# ---------- distinct_video_field_values ----------

def test_distinct_video_field_values_returns_sorted_unique(pg):
    db.add_video("a", "tiktok", "2026-01-01", topic="workshop", dsn=pg, account_id=None)
    db.add_video("b", "tiktok", "2026-01-02", topic="workshop", dsn=pg, account_id=None)
    db.add_video("c", "tiktok", "2026-01-03", topic="commute", dsn=pg, account_id=None)
    assert db.distinct_video_field_values("topic", dsn=pg, account_id=None) == ["commute", "workshop"]


def test_distinct_video_field_values_excludes_blank(pg):
    db.add_video("a", "tiktok", "2026-01-01", topic="workshop", dsn=pg, account_id=None)
    db.add_video("b", "tiktok", "2026-01-02", dsn=pg, account_id=None)
    assert db.distinct_video_field_values("topic", dsn=pg, account_id=None) == ["workshop"]


def test_distinct_video_field_values_rejects_unknown_field(pg):
    with pytest.raises(ValueError, match="field must be one of"):
        db.distinct_video_field_values("title", dsn=pg, account_id=None)


# ---------- latest_metrics_by_video ----------

def test_latest_metrics_by_video_with_no_snapshot_yet(pg):
    vid = db.add_video("a", "tiktok", "2026-01-01", dsn=pg, account_id=None)
    rows = db.latest_metrics_by_video(dsn=pg, account_id=None)
    assert rows[0]["video_id"] == vid
    assert rows[0]["views"] is None


def test_latest_metrics_by_video_returns_most_recent_snapshot(pg):
    vid = db.add_video("a", "tiktok", "2026-01-01", dsn=pg, account_id=None)
    db.record_metrics(vid, views=100, captured_at="2026-01-02", dsn=pg, account_id=None)
    db.record_metrics(vid, views=500, captured_at="2026-01-10", dsn=pg, account_id=None)
    rows = db.latest_metrics_by_video(dsn=pg, account_id=None)
    assert rows[0]["views"] == 500


# ---------- get_video ----------

def test_get_video_returns_none_for_missing_id(pg):
    assert db.get_video(999, dsn=pg, account_id=None) is None


def test_get_video_includes_metadata(pg):
    vid = db.add_video("Night Run", "youtube", "2026-01-01",
                       url="https://x", topic="workshop", dsn=pg, account_id=None)
    video = db.get_video(vid, dsn=pg, account_id=None)
    assert video["title"] == "Night Run"
    assert video["platform"] == "youtube"
    assert video["url"] == "https://x"


def test_get_video_has_no_originating_pitch_when_not_linked(pg):
    vid = db.add_video("Night Run", "youtube", "2026-01-01", dsn=pg, account_id=None)
    video = db.get_video(vid, dsn=pg, account_id=None)
    assert video["idea_id"] is None
    assert video["idea_title"] is None


def test_get_video_includes_originating_pitch_when_linked(pg):
    run_id = db.save_pitch_run(PITCHES, dsn=pg)
    with db.connect(pg) as conn:
        idea_id = conn.execute(
            "SELECT id FROM ideas WHERE run_id = %s AND number = 2", (run_id,)
        ).fetchone()[0]
    vid = db.add_video("Story 2", "tiktok", "2026-01-01", idea_id=idea_id, dsn=pg, account_id=None)

    video = db.get_video(vid, dsn=pg, account_id=None)
    assert video["idea_title"] == "Story 2"
    assert video["idea_logline"] == "Line 2."


# ---------- at_days must actually mean "at that age" ----------

def test_a_video_with_no_snapshot_near_the_age_is_excluded(pg):
    """
    Without a tolerance, ROW_NUMBER picks the closest snapshot however
    far off it is -- so a video measured on day 1 gets compared against
    one measured on day 90, and the benchmark colouring lies.
    """
    old = db.add_video("measured late", "tiktok", "2026-01-01", dsn=pg, account_id=None)
    db.record_metrics(old, views=5000, captured_at="2026-04-01", dsn=pg, account_id=None)  # ~90d

    young = db.add_video("measured early", "tiktok", "2026-03-30", dsn=pg, account_id=None)
    db.record_metrics(young, views=40, captured_at="2026-03-31", dsn=pg, account_id=None)  # ~1d

    at_90 = [r["title"] for r in db.get_top_performers(
        at_days=90, posted_within_days=None, posted_since="2025-01-01", dsn=pg, account_id=None)]
    assert at_90 == ["measured late"], "a 1-day-old reading is not a 90-day reading"

    at_1 = [r["title"] for r in db.get_top_performers(
        at_days=1, posted_within_days=None, posted_since="2025-01-01", dsn=pg, account_id=None)]
    assert at_1 == ["measured early"]


def test_benchmark_only_averages_comparable_readings(pg):
    old = db.add_video("late", "tiktok", "2026-01-01", dsn=pg, account_id=None)
    db.record_metrics(old, views=5000, captured_at="2026-04-01", dsn=pg, account_id=None)
    young = db.add_video("early", "tiktok", "2026-03-30", dsn=pg, account_id=None)
    db.record_metrics(young, views=40, captured_at="2026-03-31", dsn=pg, account_id=None)

    bench = db.benchmark(at_days=90, posted_since="2025-01-01", dsn=pg, account_id=None)
    assert bench["n"] == 1 and bench["median"] == 5000


def test_tolerance_is_generous_enough_for_a_few_days_slip(pg):
    """Checking numbers on day 9 instead of day 7 is normal use."""
    vid = db.add_video("slightly late", "tiktok", "2026-01-01", dsn=pg, account_id=None)
    db.record_metrics(vid, views=100, captured_at="2026-01-10", dsn=pg, account_id=None)  # 9d
    got = db.get_top_performers(at_days=7, posted_since="2025-01-01", dsn=pg, account_id=None)
    assert [r["title"] for r in got] == ["slightly late"]
