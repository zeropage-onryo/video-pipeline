"""
Only posts the pipeline produced may teach the loop (docs/BACKLOG.md,
2026-09-07).

The ten rows on the live `videos` table are hand-made YouTube uploads
that predate the pipeline, and every teaching reader was learning from
them. Each test here seeds the same pair -- one legacy upload, one
pipeline post carrying a `concept_id` -- and asserts one reader ignores
the first and uses the second. The pair is deliberately shaped so the
LEGACY row is the better performer: a reader that still sees it cannot
quietly pass by picking the same answer for a different reason.

`concept_id` is set with SQL because nothing writes it yet (db.add_video
has no parameter for it -- see preprod.posted_outcomes); the flag under
test is `videos.legacy`, and the column is only how the backfill guessed
it once.
"""
import pytest

from src import autonomy, crag, db, post_seo, preprod, refresh_metrics, taste_judge, winners
from src import promote_winners as pw


def _seed_pair(path, posted_at="2026-06-01"):
    """A legacy upload that did GREAT and a pipeline post that did fine.

    Both measured at day 7, so get_top_performers' equal-age window
    holds them both and the only thing separating them is the flag.
    """
    legacy_id = db.add_video("Cocktail recipe", "youtube", posted_at,
                             topic="cocktails", hook_type="pour",
                             dsn=path, account_id=None)
    pipeline_id = db.add_video("Concept 12", "youtube", posted_at,
                               topic="garage", hook_type="cold open",
                               dsn=path, account_id=None)
    db.record_metrics(legacy_id, views=100_000, captured_at="2026-06-08T00:00:00",
                      dsn=path, account_id=None)
    db.record_metrics(pipeline_id, views=9_000, captured_at="2026-06-08T00:00:00",
                      dsn=path, account_id=None)
    with db.connect(path) as conn:
        conn.execute("UPDATE videos SET legacy = TRUE WHERE id = %s", (legacy_id,))
        conn.execute("UPDATE videos SET concept_id = 1 WHERE id = %s", (pipeline_id,))
    return legacy_id, pipeline_id


# ---------- the migration ----------

def _drop_legacy_column(path):
    """Rewind one database to before the migration, which is the only
    state the migration is for -- db.SCHEMA carries the column inline, so
    a fresh test database is already past it."""
    with db.connect(path) as conn:
        conn.execute("ALTER TABLE videos DROP COLUMN legacy")


def test_migration_backfills_concept_less_rows_and_is_idempotent(pg):
    path = pg
    hand_made = db.add_video("A haircut", "youtube", "2026-06-01",
                             dsn=path, account_id=None)
    from_pipeline = db.add_video("Concept 12", "youtube", "2026-06-01",
                                 dsn=path, account_id=None)
    with db.connect(path) as conn:
        conn.execute("UPDATE videos SET concept_id = 7 WHERE id = %s", (from_pipeline,))
    _drop_legacy_column(path)

    with db.connect(path) as conn:
        assert "legacy" not in db.columns(conn, "videos")
        assert db.add_legacy_column(conn) is True

    with db.connect(path) as conn:
        flags = {r["id"]: r["legacy"] for r in conn.execute("SELECT id, legacy FROM videos")}
    assert flags[hand_made] is True        # concept_id IS NULL at migration time
    assert flags[from_pipeline] is False   # the pipeline made it

    # The dev server re-runs migrations on every save. A second pass must
    # do nothing at all -- including not re-marking a row somebody
    # deliberately corrected with mark_legacy.
    db.mark_legacy(hand_made, False, dsn=path, account_id=None)
    for _ in range(3):
        with db.connect(path) as conn:
            assert db.add_legacy_column(conn) is False
    with db.connect(path) as conn:
        again = {r["id"]: r["legacy"] for r in conn.execute("SELECT id, legacy FROM videos")}
    assert again[hand_made] is False

    # and init_db, which is what actually runs it, is safe to repeat too
    db.init_db(path)
    db.init_db(path)


def test_new_videos_are_not_legacy(pg):
    """The default is what makes the rule work going forward: a post the
    pipeline makes tonight teaches without anyone remembering to say so."""
    vid = db.add_video("Concept 13", "youtube", "2026-06-01", dsn=pg, account_id=None)
    with db.connect(pg) as conn:
        row = conn.execute("SELECT legacy FROM videos WHERE id = %s", (vid,)).fetchone()
    assert row["legacy"] is False


def test_mark_legacy_flips_the_flag_both_ways(pg):
    path = pg
    vid = db.add_video("A short film", "youtube", "2026-06-01", dsn=path, account_id=None)
    assert db.mark_legacy(vid, True, dsn=path, account_id=None) is True
    with db.connect(path) as conn:
        assert conn.execute("SELECT legacy FROM videos WHERE id = %s", (vid,)).fetchone()["legacy"]
    assert db.mark_legacy(vid, False, dsn=path, account_id=None) is True
    with db.connect(path) as conn:
        assert not conn.execute("SELECT legacy FROM videos WHERE id = %s", (vid,)).fetchone()["legacy"]
    assert db.mark_legacy(999_999, True, dsn=path, account_id=None) is False


# ---------- the readers that TEACH ----------

def test_top_performers_shows_legacy_but_can_be_asked_not_to(pg):
    path = pg
    legacy_id, pipeline_id = _seed_pair(path)

    shown = db.get_top_performers(posted_within_days=None, dsn=path, account_id=None)
    assert {r["video_id"] for r in shown} == {legacy_id, pipeline_id}

    taught = db.get_top_performers(posted_within_days=None, include_legacy=False,
                                   dsn=path, account_id=None)
    assert [r["video_id"] for r in taught] == [pipeline_id]

    # the median moves with it -- which is the point: the legacy row was
    # setting the bar every real candidate was measured against
    assert db.benchmark(posted_within_days=None, dsn=path, account_id=None)["n"] == 2
    assert db.benchmark(posted_within_days=None, include_legacy=False,
                        dsn=path, account_id=None)["n"] == 1


def test_promote_winners_never_proposes_a_legacy_upload(pg):
    path = pg
    legacy_id, pipeline_id = _seed_pair(path)
    # a third pipeline post, so the legacy-free window has a median the
    # winner can beat rather than being its own median
    dud = db.add_video("Concept 13", "youtube", "2026-06-01", dsn=path, account_id=None)
    db.record_metrics(dud, views=1_000, captured_at="2026-06-08T00:00:00",
                      dsn=path, account_id=None)
    with db.connect(path) as conn:
        conn.execute("UPDATE videos SET concept_id = 2 WHERE id = %s", (dud,))

    ids = {c["video_id"] for c in pw.candidate_winners(posted_within_days=None, db_path=path)}
    assert legacy_id not in ids
    assert pipeline_id in ids


def test_derive_signals_tallies_only_pipeline_traits(pg):
    path = pg
    _seed_pair(path)
    signals = post_seo.derive_signals(posted_within_days=None, db_path=path)
    assert signals["sample"] == 1
    tallied = set(signals["winning_topics"]) | set(signals["losing_topics"])
    assert "cocktails" not in tallied
    assert "garage" in tallied


def test_winners_listing_drops_notes_written_against_a_legacy_post(pg):
    path = pg
    legacy_id, pipeline_id = _seed_pair(path)
    winners.add("runway", "a legacy prompt", video_ref=str(legacy_id), dsn=path)
    winners.add("runway", "a pipeline prompt", video_ref=str(pipeline_id), dsn=path)

    shown = {w["prompt"] for w in winners.list_all(dsn=path)}
    assert shown == {"a pipeline prompt", "a legacy prompt"}

    taught = [w["prompt"] for w in winners.list_all(dsn=path, include_legacy=False)]
    assert taught == ["a pipeline prompt"]


def test_taste_judge_scores_against_pipeline_history_only(pg):
    path = pg
    preprod.init(path)
    autonomy.init(path)
    winners.init(path)
    legacy_id, pipeline_id = _seed_pair(path)
    winners.add("runway", "a legacy prompt", video_ref=str(legacy_id), dsn=path)
    winners.add("runway", "a pipeline prompt", video_ref=str(pipeline_id), dsn=path)

    signals = taste_judge.gather_signals(db_path=path)
    assert [w["prompt"] for w in signals["winners"]] == ["a pipeline prompt"]
    assert signals["perf"]["sample"] == 1


def test_crag_drops_proven_results_promoted_from_a_legacy_post(pg, monkeypatch):
    path = pg
    legacy_id, pipeline_id = _seed_pair(path)
    monkeypatch.setenv("DATABASE_URL", path)
    refs = [
        {"source": pw.source_key(legacy_id), "chunk": "a cocktail travelled", "score": 0.9},
        {"source": pw.source_key(pipeline_id), "chunk": "a concept travelled", "score": 0.8},
        {"source": "marketing/hooks.txt", "chunk": "craft advice", "score": 0.7},
    ]
    kept = [r["source"] for r in crag.drop_legacy_references(refs)]
    assert kept == [pw.source_key(pipeline_id), "marketing/hooks.txt"]


def test_crag_passes_references_through_when_the_database_is_unreachable(monkeypatch):
    """Fails open: retrieval degrades a run, it never stops one."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://nobody@127.0.0.1:1/nothing")
    refs = [{"source": pw.source_key(1), "chunk": "x", "score": 0.9}]
    assert crag.drop_legacy_references(refs) == refs


def test_metric_refresh_still_sweeps_legacy_videos(pg, monkeypatch):
    """The sweep's two halves part company here: refreshing a legacy
    video keeps the Analytics page honest, and only the promote step
    below it teaches."""
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    path = pg
    _seed_pair(path)
    summary = refresh_metrics.refresh_all(platform="youtube", db_path=path)
    assert summary["youtube"]["videos"] == 2


# ---------- the way back in ----------

@pytest.mark.parametrize("value", ["1", "true", "yes"])
def test_env_override_re_includes_legacy_everywhere(pg, monkeypatch, value):
    path = pg
    legacy_id, pipeline_id = _seed_pair(path)
    winners.add("runway", "a legacy prompt", video_ref=str(legacy_id), dsn=path)

    monkeypatch.setenv(db.LEARN_FROM_LEGACY_ENV, value)
    assert db.learn_from_legacy() is True

    taught = db.get_top_performers(posted_within_days=None, include_legacy=False,
                                   dsn=path, account_id=None)
    assert {r["video_id"] for r in taught} == {legacy_id, pipeline_id}
    assert post_seo.derive_signals(posted_within_days=None, db_path=path)["sample"] == 2
    assert len(winners.list_all(dsn=path, include_legacy=False)) == 1
    assert crag.drop_legacy_references(
        [{"source": pw.source_key(legacy_id), "chunk": "x", "score": 0.9}]) != []


def test_env_override_off_by_default(pg, monkeypatch):
    monkeypatch.delenv(db.LEARN_FROM_LEGACY_ENV, raising=False)
    assert db.learn_from_legacy() is False
    monkeypatch.setenv(db.LEARN_FROM_LEGACY_ENV, "0")
    assert db.learn_from_legacy() is False
