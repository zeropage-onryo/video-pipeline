"""
Tests for post_seo.py -- the post-level performance signal the autonomy
loop optimizes against. (app/seo.py is the *site's* crawler surface;
this scores *posts*: titles, hooks, topics. Two different things that
share a word, like concepts.json vs shoot_concepts.)

Everything here is pure against SQLite: derive_signals reads the same
tables db.benchmark reads, score_post is a function of its arguments.
No network, no model.
"""
import pytest

from src import db, post_seo


@pytest.fixture
def seeded_db(tmp_path):
    """Six videos measured at the same age: three winners on one trait
    profile, three losers on another, so the split is unambiguous."""
    path = tmp_path / "test.db"
    db.init_db(path)
    winners = [
        ("Wrench ritual at 3am", "workshop", "cold-open"),
        ("Engine teardown ritual", "workshop", "cold-open"),
        ("Bolt by bolt ritual", "workshop", "text-hook"),
    ]
    losers = [
        ("My gear list", "gear", "talking-head"),
        ("Gear I bought this month", "gear", "talking-head"),
        ("Unboxing new gear", "gear", "voiceover"),
    ]
    for i, (title, topic, hook) in enumerate(winners):
        vid = db.add_video(title, "youtube", "2026-01-01", topic=topic,
                           hook_type=hook, path=path, account_id=None)
        db.record_metrics(vid, views=1000 + i, captured_at="2026-01-08", path=path, account_id=None)
    for i, (title, topic, hook) in enumerate(losers):
        vid = db.add_video(title, "youtube", "2026-01-01", topic=topic,
                           hook_type=hook, path=path, account_id=None)
        db.record_metrics(vid, views=10 + i, captured_at="2026-01-08", path=path, account_id=None)
    return path


# ---------- derive_signals ----------

def test_derive_signals_splits_traits_at_the_median(seeded_db):
    signals = post_seo.derive_signals(posted_within_days=None, db_path=seeded_db)
    assert signals["sample"] == 6
    assert signals["winning_topics"].get("workshop") == 3
    assert signals["losing_topics"].get("gear") == 3
    assert "cold-open" in signals["winning_hooks"]
    assert "talking-head" in signals["losing_hooks"]


def test_derive_signals_collects_winning_title_words(seeded_db):
    signals = post_seo.derive_signals(posted_within_days=None, db_path=seeded_db)
    assert signals["winning_title_words"].get("ritual") == 3
    # stopwords don't count as signal
    assert "at" not in signals["winning_title_words"]


def test_derive_signals_empty_db_is_a_null_signal(tmp_path):
    path = tmp_path / "empty.db"
    db.init_db(path)
    signals = post_seo.derive_signals(db_path=path)
    assert signals["sample"] == 0


# ---------- score_post ----------

def test_score_rewards_winning_traits_with_evidence(seeded_db):
    signals = post_seo.derive_signals(posted_within_days=None, db_path=seeded_db)
    scored = post_seo.score_post(
        "Midnight wrench ritual", topic="workshop", hook_type="cold-open",
        signals=signals,
    )
    weak = post_seo.score_post(
        "My gear list part 2", topic="gear", hook_type="talking-head",
        signals=signals,
    )
    assert scored["score"] > weak["score"]
    # the reasons must cite the evidence, not just assert goodness
    assert any("workshop" in r for r in scored["reasons"])
    assert any("gear" in r for r in weak["reasons"])


def test_score_without_signals_is_neutral_and_says_so():
    scored = post_seo.score_post("Anything at all")
    assert scored["score"] == post_seo.BASELINE
    assert any("no performance data" in r for r in scored["reasons"])


def test_score_penalises_an_empty_title(seeded_db):
    signals = post_seo.derive_signals(posted_within_days=None, db_path=seeded_db)
    scored = post_seo.score_post("", signals=signals)
    assert scored["score"] < post_seo.BASELINE
    assert any("title" in r.lower() for r in scored["reasons"])


def test_score_is_clamped_to_the_unit_interval(seeded_db):
    signals = post_seo.derive_signals(posted_within_days=None, db_path=seeded_db)
    scored = post_seo.score_post(
        "ritual ritual engine teardown wrench bolt", topic="workshop",
        hook_type="cold-open", signals=signals,
    )
    assert 0.0 <= scored["score"] <= 1.0
