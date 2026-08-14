"""
Regression: the 'no such column: verdict' crash that took down a trigger
run (hold 4, 2026-08-11). A winning_prompts table created by an older
schema has no `verdict` column; any query that filters on it must not
raise. winners.init() migrates the column in place, and avoid_guidance()
-- reached on every orchestrator run -- must survive a pre-migration
table without crashing the whole shadow run.
"""
from src import db, winners


def _make_pre_verdict_table(path):
    """The winning_prompts table as it existed before `verdict` was added."""
    with db.connect(path) as conn:
        conn.execute(
            "CREATE TABLE winning_prompts ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " created_at TEXT NOT NULL,"
            " tool TEXT NOT NULL DEFAULT 'runway',"
            " prompt TEXT NOT NULL,"
            " note TEXT,"
            " video_ref TEXT,"
            " rag_source TEXT,"
            " ingested INTEGER NOT NULL DEFAULT 0)"
        )
        conn.execute(
            "INSERT INTO winning_prompts (created_at, tool, prompt) "
            "VALUES ('2026-08-01T00:00:00+00:00', 'runway', 'a legacy prompt')"
        )


def test_init_adds_verdict_to_a_legacy_table(tmp_path):
    dbp = tmp_path / "pipeline.db"
    _make_pre_verdict_table(dbp)
    winners.init(path=dbp)  # must migrate, not raise
    with db.connect(dbp) as conn:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(winning_prompts)")}
    assert "verdict" in cols


def test_avoid_guidance_survives_a_pre_verdict_table(tmp_path):
    """The exact crash path: a verdict filter against an unmigrated table.
    avoid_guidance self-initialises and must return a string, never raise."""
    dbp = tmp_path / "pipeline.db"
    _make_pre_verdict_table(dbp)
    result = winners.avoid_guidance(path=dbp)  # regression: raised 'no such column: verdict'
    assert isinstance(result, str)


def test_init_is_idempotent(tmp_path):
    dbp = tmp_path / "pipeline.db"
    _make_pre_verdict_table(dbp)
    winners.init(path=dbp)
    winners.init(path=dbp)  # second call must be a no-op, not an error
    entry_id = winners.add("runway", "another prompt", verdict="didnt_work", path=dbp)
    assert winners.get(entry_id, path=dbp)["verdict"] == "didnt_work"
