"""
The one-off data copy, on a small SQLite file in the PRE-migration shape:
integer user ids with an argon2 hash and an auth_identities row, the two
real channels, a video with two snapshots, a concept pinned to a room.

What has to hold: every row lands with its id intact, the users become
unclaimed placeholder rows that the first Supabase sign-in can claim,
memberships follow them, the seeds the inits plant lose to the file,
the identity sequences continue past the copied ids, and a target that
already holds rows is refused unless told to truncate.
"""
import io
import sqlite3

import pytest

from ops import copy_sqlite_to_postgres as copier
from src import accounts, db

OLD_SCHEMA = """
CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE, password_hash TEXT, display_name TEXT, avatar_url TEXT);
CREATE TABLE auth_identities (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
    provider TEXT NOT NULL, provider_subject TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE accounts (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE, display_name TEXT NOT NULL, accent_color TEXT, voice TEXT,
    house_look TEXT, house_negative TEXT, house_aspect TEXT DEFAULT '9:16', never_list TEXT);
CREATE TABLE account_members (account_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
    role TEXT NOT NULL DEFAULT 'owner', PRIMARY KEY (account_id, user_id));
CREATE TABLE channels (name TEXT PRIMARY KEY, autonomy TEXT NOT NULL DEFAULT 'shadow',
    rate_cap INTEGER NOT NULL DEFAULT 1, targets TEXT NOT NULL DEFAULT '', notes TEXT);
CREATE TABLE videos (id INTEGER PRIMARY KEY AUTOINCREMENT, idea_id INTEGER, concept_id INTEGER,
    title TEXT NOT NULL, platform TEXT NOT NULL, posted_at TEXT NOT NULL, url TEXT, timeline TEXT,
    topic TEXT, hook_type TEXT, duration_s REAL, notes TEXT, brand TEXT, account_id INTEGER);
CREATE TABLE metrics (id INTEGER PRIMARY KEY AUTOINCREMENT, video_id INTEGER NOT NULL,
    captured_at TEXT NOT NULL, views INTEGER, likes INTEGER, comments INTEGER, saves INTEGER,
    shares INTEGER, watch_time_seconds REAL, UNIQUE (video_id, captured_at));
CREATE TABLE locations (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
    name TEXT NOT NULL, photo_count INTEGER, description_json TEXT, notes TEXT, account_id INTEGER);
CREATE TABLE shoot_concepts (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
    brand TEXT NOT NULL, client TEXT, spark TEXT, title TEXT NOT NULL, hook TEXT, logline TEXT,
    card_line TEXT, duration TEXT, shots_json TEXT NOT NULL, ai_json TEXT, edit_note TEXT,
    grade_note TEXT, shot_done INTEGER NOT NULL DEFAULT 0, prompt_hash TEXT, warnings_json TEXT,
    use_pov INTEGER NOT NULL DEFAULT 1, notes TEXT, judge_overall REAL, judge_taste REAL,
    judge_perf REAL, judge_reason TEXT, format TEXT, uncanny_overall REAL, uncanny_passed INTEGER,
    uncanny_reason TEXT, picked_at TEXT, archived_at TEXT, archive_reason TEXT, account_id INTEGER);
CREATE TABLE concept_locations (concept_id INTEGER NOT NULL, location_id INTEGER NOT NULL,
    UNIQUE (concept_id, location_id));
"""


@pytest.fixture
def old_db(tmp_path):
    path = tmp_path / "pipeline.db"
    c = sqlite3.connect(path)
    c.executescript(OLD_SCHEMA)
    c.execute("INSERT INTO users VALUES (7, 't', 'mike@example.com', '$argon2id$x', 'Mike', NULL)")
    c.execute("INSERT INTO auth_identities VALUES (1, 7, 'google', 'sub-1', 't')")
    c.execute("INSERT INTO accounts (id, created_at, slug, display_name) "
              "VALUES (1, 't', 'zeropage', 'Zero Page Films')")
    c.execute("INSERT INTO accounts (id, created_at, slug, display_name) "
              "VALUES (2, 't', 'antihero', 'ANTIHERO')")
    c.execute("INSERT INTO account_members VALUES (1, 7, 'owner'), (2, 7, 'owner')")
    c.execute("INSERT INTO channels VALUES ('zeropage', 'queue', 1, 'instagram,youtube', 'the file says queue')")
    c.execute("INSERT INTO channels VALUES ('antihero', 'shadow', 1, '', '')")
    c.execute("INSERT INTO videos (id, title, platform, posted_at, account_id) "
              "VALUES (5, 'Night Run', 'tiktok', '2026-07-01', 1)")
    c.execute("INSERT INTO metrics (video_id, captured_at, views) "
              "VALUES (5, '2026-07-02', 100), (5, '2026-07-09', 900)")
    c.execute("INSERT INTO locations (id, created_at, name, account_id) VALUES (3, 't', 'Garage', 1)")
    c.execute("INSERT INTO shoot_concepts (id, created_at, brand, title, shots_json, account_id) "
              "VALUES (12, 't', 'zeropage', 'A concept', '[]', 1)")
    c.execute("INSERT INTO concept_locations VALUES (12, 3)")
    c.commit()
    c.close()
    return path


def _q(dsn, sql, args=()):
    """Rows as tuples: db.Row is a mapping AND a sequence, and equality
    against a tuple literal wants the sequence half."""
    with db.connect(dsn) as conn:
        return [tuple(r) for r in conn.execute(sql, args).fetchall()]


def test_dry_run_counts_and_writes_nothing(old_db, pg):
    out = io.StringIO()
    result = copier.copy(old_db, pg, dry_run=True, out=out)
    assert result["dry_run"] and result["counts"]["videos"] == 1
    assert "auth_identities" in out.getvalue() and "dropped" in out.getvalue()
    with db.connect(pg) as conn:
        assert not db.table_exists(conn, "shoot_concepts")   # no schema was built


def test_rows_land_with_their_ids_and_the_sequences_continue(old_db, pg):
    result = copier.copy(old_db, pg, out=io.StringIO())
    assert not result["problems"]
    assert _q(pg, "SELECT id, title FROM videos") == [(5, "Night Run")]
    assert _q(pg, "SELECT count(*) FROM metrics")[0][0] == 2
    assert _q(pg, "SELECT concept_id, location_id FROM concept_locations") == [(12, 3)]
    # the sequence continues past 5, not from 1
    assert db.add_video("Next", "tiktok", "2026-08-01", dsn=pg, account_id=1) == 6


def test_users_become_unclaimed_placeholders_that_a_sign_in_claims(old_db, pg):
    result = copier.copy(old_db, pg, out=io.StringIO())
    placeholder = result["user_map"][7]
    [(uid, claimed, cols)] = _q(pg, "SELECT id, claimed_at, (SELECT count(*) FROM information_schema.columns "
                                    "WHERE table_name='users' AND column_name='password_hash') FROM users")
    assert uid == placeholder and claimed is None and cols == 0
    assert {m["slug"] for m in accounts.memberships(placeholder, dsn=pg)} == {"zeropage", "antihero"}
    # the first Supabase sign-in with that email takes the row and its memberships
    real, error = accounts.claim("sb-uuid-mike", "mike@example.com", "Mike", None, dsn=pg)
    assert error is None and real == "sb-uuid-mike"
    assert len(accounts.memberships("sb-uuid-mike", dsn=pg)) == 2
    assert accounts.get_user(placeholder, dsn=pg) is None


def test_the_file_beats_the_seeds(old_db, pg):
    copier.copy(old_db, pg, out=io.StringIO())
    rows = dict(_q(pg, "SELECT name, autonomy FROM channels"))
    assert rows == {"zeropage": "queue", "antihero": "shadow"}   # autonomy.init's seed said shadow for both
    assert _q(pg, "SELECT notes FROM channels WHERE name='zeropage'") == [("the file says queue",)]


def test_a_target_with_rows_is_refused_unless_told_to_truncate(old_db, pg):
    copier.copy(old_db, pg, out=io.StringIO())
    with pytest.raises(SystemExit, match="refusing"):
        copier.copy(old_db, pg, out=io.StringIO())
    result = copier.copy(old_db, pg, truncate=True, out=io.StringIO())
    assert not result["problems"]
    assert _q(pg, "SELECT count(*) FROM videos")[0][0] == 1        # replaced, not doubled


def test_main_refuses_to_guess_the_target(old_db, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert copier.main(["--sqlite", str(old_db), "--dry-run"]) == 2
