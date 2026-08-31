"""
The spine: what got pitched, what got shot, how it did.

Four tables:

    pitch_runs - one execution of pitch.py against a manifest
    ideas      - one pitch. 10 per run. `selected` records your choice.
    videos     - something you actually posted
    metrics    - a snapshot of how a video was doing at one moment

Two design decisions worth knowing.

`selected` on ideas exists because pitch.py generates 10 and you pick a
few. That choice is a human label. Ten pitches from the same manifest
under the same prompt, three marked good, seven not — that is a
preference set, and it is the only source of ground truth in this
system that does not require waiting for a video to be posted.

`metrics` is its own table because numbers change. A video has 8k views
on day one and 40k on day thirty. Overwrite the row and you lose the
growth curve, and you can no longer compare a video posted yesterday
against one posted last year. Snapshots let you ask "how did each look
at 7 days old", which is the only fair comparison.

SQLite because it needs no setup and lives in one file. The SQL is
plain enough to move to Postgres by changing connect() and swapping
AUTOINCREMENT for SERIAL.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Optional, Sequence

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "pipeline.db"

PLATFORMS = ("instagram", "tiktok", "youtube")

# How far a snapshot may sit from the requested age and still count as a
# reading "at" that age, as a fraction of at_days. Without this, the
# closest snapshot always wins however far off it is, so a video measured
# on day 1 gets ranked against one measured on day 90 and the benchmark
# colouring is comparing two different questions. Proportional rather
# than fixed: two days' slip matters at day 7 and is noise at day 90.
AGE_TOLERANCE = 0.5


SCHEMA = """
CREATE TABLE IF NOT EXISTS pitch_runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at   TEXT    NOT NULL,
    model        TEXT,
    clip_count   INTEGER,
    brief_hash   TEXT,
    settings_hash TEXT,
    prompt_hash  TEXT,
    notes        TEXT
);

CREATE TABLE IF NOT EXISTS ideas (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      INTEGER REFERENCES pitch_runs(id) ON DELETE CASCADE,
    number      INTEGER,
    title       TEXT    NOT NULL,
    logline     TEXT,
    story_note  TEXT,
    hook_clip   TEXT,
    selected    INTEGER NOT NULL DEFAULT 0,
    trend_informed INTEGER NOT NULL DEFAULT 0,
    notes       TEXT
);

CREATE TABLE IF NOT EXISTS videos (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    idea_id    INTEGER REFERENCES ideas(id) ON DELETE SET NULL,
    title      TEXT    NOT NULL,
    platform   TEXT    NOT NULL,
    posted_at  TEXT    NOT NULL,
    url        TEXT,
    timeline   TEXT,
    topic      TEXT,
    hook_type  TEXT,
    duration_s REAL,
    notes      TEXT,
    brand      TEXT
);

CREATE TABLE IF NOT EXISTS metrics (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id           INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    captured_at        TEXT    NOT NULL,
    views              INTEGER,
    likes              INTEGER,
    comments           INTEGER,
    saves              INTEGER,
    shares             INTEGER,
    watch_time_seconds REAL,
    UNIQUE (video_id, captured_at)
);

CREATE INDEX IF NOT EXISTS idx_ideas_run       ON ideas (run_id);
CREATE INDEX IF NOT EXISTS idx_ideas_selected  ON ideas (selected);
CREATE INDEX IF NOT EXISTS idx_videos_platform ON videos (platform);
CREATE INDEX IF NOT EXISTS idx_metrics_video   ON metrics (video_id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _hash(text: str | None) -> str | None:
    """Short content hash, so you can tell which prompt version produced what."""
    if text is None:
        return None
    return hashlib.sha256(text.encode()).hexdigest()[:12]


@contextmanager
def connect(path: Path | str = DB_PATH) -> Iterator[sqlite3.Connection]:
    """Commits on success, rolls back on error, always closes."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# --------------------------------------------------------------------------
# tenancy -- every owned row carries the account that owns it
# --------------------------------------------------------------------------

# The tables whose rows belong to one account rather than to the
# installation. Every SELECT against one of these needs an account_id
# predicate; tests/test_tenancy.py asserts that none is missing.
#
# `accounts` IS the brand table (accounts.seed creates zeropage and
# antihero), so account_id is the scoping key and the `brand` TEXT column
# is a label carried alongside it, not the boundary. See
# docs/tasks/task-account-tenancy.md.
OWNED_TABLES = (
    "shoot_concepts",
    "locations",
    "characters",
    "props",
    "generations",
    "videos",
    "scene_briefs",
    "shots",
)


def _ensure_accounts_table(conn: sqlite3.Connection) -> None:
    """The FK target has to exist before a column can point at it.

    Imported lazily: accounts.py imports this module, so a top-level
    import would be a cycle. Idempotent -- the schema is all
    CREATE TABLE IF NOT EXISTS -- which matters because init order varies
    (the app lifespan runs accounts.init() itself; a test that only calls
    preprod.init() does not).
    """
    from .accounts import SCHEMA as ACCOUNTS_SCHEMA
    conn.executescript(ACCOUNTS_SCHEMA)


def add_account_column(conn: sqlite3.Connection, table: str) -> bool:
    """Additive ALTER TABLE, the preprod.picked_at pattern. True if added.

    Nullable on purpose. SQLite cannot add a NOT NULL column to a table
    that already has rows without a default, and the only honest default
    -- a literal account id -- differs per database. So NULL means
    "predates tenancy" and backfill_owner is what claims those rows.
    Ownership is enforced by the queries, not by the column.
    """
    cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
    if "account_id" in cols:
        return False
    _ensure_accounts_table(conn)
    conn.execute(
        f"ALTER TABLE {table} ADD COLUMN account_id INTEGER REFERENCES accounts(id)"
    )
    return True


def bootstrap_account_id(conn: sqlite3.Connection) -> Optional[int]:
    """The account pre-tenancy rows belong to: the oldest one, which on
    every database that exists today is Mike's. None before seeding."""
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'accounts'"
    ).fetchone()
    if exists is None:
        return None
    row = conn.execute("SELECT MIN(id) AS id FROM accounts").fetchone()
    return row["id"] if row and row["id"] is not None else None


def backfill_owner(conn: sqlite3.Connection, table: str,
                   account_id: Optional[int] = None) -> int:
    """Claim every ownerless row for the bootstrap account; returns how
    many. A no-op when there is no account yet -- init() runs before
    seed() on a fresh database, so accounts.seed() calls this again once
    there is finally an owner to claim them for."""
    if account_id is None:
        account_id = bootstrap_account_id(conn)
    if account_id is None:
        return 0
    cur = conn.execute(
        f"UPDATE {table} SET account_id = ? WHERE account_id IS NULL",
        (account_id,),
    )
    return cur.rowcount


def own_table(conn: sqlite3.Connection, table: str) -> None:
    """add_account_column + backfill_owner -- the pair every init() wants."""
    add_account_column(conn, table)
    backfill_owner(conn, table)


def init_db(path: Path | str = DB_PATH) -> None:
    """Create the tables. Safe to run repeatedly."""
    with connect(path) as conn:
        conn.executescript(SCHEMA)
        # migrate: add videos.brand to a DB that predates per-brand tagging
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(videos)")}
        if "brand" not in cols:
            conn.execute("ALTER TABLE videos ADD COLUMN brand TEXT")
        # tenancy: a posted video belongs to the account that made it
        own_table(conn, "videos")


# --------------------------------------------------------------------------
# pitches
# --------------------------------------------------------------------------


def save_pitch_run(
    pitches: Sequence[dict],
    model: Optional[str] = None,
    clip_count: Optional[int] = None,
    brief: Optional[str] = None,
    settings: Optional[str] = None,
    prompt_template: Optional[str] = None,
    path: Path | str = DB_PATH,
) -> int:
    """
    Store a whole batch from pitch.py. Returns the run id.

    Pass the raw text of brief.txt, settings.txt and pitch_prompt.txt and
    their hashes get recorded. That is what lets you ask later whether a
    prompt change actually improved anything, instead of guessing.

    Accepts the exact dicts pitch.py already builds:
        {"number": 1, "title": ..., "logline": ..., "story_note": ...}
    """
    if not pitches:
        raise ValueError("no pitches to save")

    with connect(path) as conn:
        cur = conn.execute(
            """
            INSERT INTO pitch_runs
                (created_at, model, clip_count, brief_hash, settings_hash,
                 prompt_hash)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (_now(), model, clip_count, _hash(brief), _hash(settings),
             _hash(prompt_template)),
        )
        run_id = int(cur.lastrowid)

        for p in pitches:
            title = (p.get("title") or "").strip()
            if not title:
                raise ValueError(f"pitch {p.get('number')} has no title")
            conn.execute(
                """
                INSERT INTO ideas
                    (run_id, number, title, logline, story_note, hook_clip)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (run_id, p.get("number"), title, p.get("logline"),
                 p.get("story_note"), p.get("hook_clip")),
            )
        return run_id


def mark_selected(
    idea_ids: Sequence[int],
    path: Path | str = DB_PATH,
) -> int:
    """
    Record which pitches you chose to cut. Returns how many were updated.

    Call this from editgen.py with the pitches the human picked. This is
    the label. Without it the run is just ten unranked strings.
    """
    if not idea_ids:
        return 0
    with connect(path) as conn:
        placeholders = ",".join("?" * len(idea_ids))
        cur = conn.execute(
            f"UPDATE ideas SET selected = 1 WHERE id IN ({placeholders})",
            tuple(idea_ids),
        )
        return cur.rowcount


def mark_selected_by_number(
    run_id: int,
    numbers: Sequence[int],
    path: Path | str = DB_PATH,
) -> int:
    """
    Same, but by the pitch numbers editgen.py already takes on the command
    line, so wiring it in is a one-line change.
    """
    if not numbers:
        return 0
    with connect(path) as conn:
        placeholders = ",".join("?" * len(numbers))
        cur = conn.execute(
            f"""
            UPDATE ideas SET selected = 1
            WHERE run_id = ? AND number IN ({placeholders})
            """,
            (run_id, *numbers),
        )
        return cur.rowcount


def most_recent_run_id(path: Path | str = DB_PATH) -> Optional[int]:
    """
    The id of the latest pitch_runs row, or None if none exist yet.

    Backs editgen.py's --run-id default, so marking a selection doesn't
    require typing the run id back in by hand for the common case of
    editing right after the pitch run that produced it.
    """
    with connect(path) as conn:
        row = conn.execute(
            "SELECT id FROM pitch_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return row["id"] if row else None


def get_labelled_pitches(
    selected_only: bool = False,
    limit: int = 200,
    path: Path | str = DB_PATH,
) -> list[dict[str, Any]]:
    """
    Pitches from runs where at least one was picked, so you know the
    unpicked ones were genuinely rejected rather than never reviewed.

    This is your evaluation set. Feed the selected ones in as examples of
    what good looks like; use the pairing to check whether a new prompt
    ranks your real choices near the top.
    """
    sql = """
        SELECT i.*, r.created_at AS run_created_at, r.model, r.prompt_hash
        FROM ideas i
        JOIN pitch_runs r ON r.id = i.run_id
        WHERE i.run_id IN (SELECT run_id FROM ideas WHERE selected = 1)
        {selected_clause}
        ORDER BY i.run_id DESC, i.number ASC
        LIMIT ?
    """.format(selected_clause="AND i.selected = 1" if selected_only else "")
    with connect(path) as conn:
        return [dict(r) for r in conn.execute(sql, (limit,))]


def selection_rate(path: Path | str = DB_PATH) -> dict[str, Any]:
    """
    How many pitches you keep, overall and per prompt version.

    If a prompt change makes you pick 4 out of 10 instead of 2, that is a
    real signal and it costs nothing to collect.
    """
    with connect(path) as conn:
        rows = conn.execute(
            """
            SELECT r.prompt_hash,
                   COUNT(*)                AS pitched,
                   SUM(i.selected)         AS chosen
            FROM ideas i
            JOIN pitch_runs r ON r.id = i.run_id
            WHERE i.run_id IN (SELECT run_id FROM ideas WHERE selected = 1)
            GROUP BY r.prompt_hash
            """
        ).fetchall()
    by_prompt = [
        {
            "prompt_hash": r["prompt_hash"],
            "pitched": r["pitched"],
            "chosen": r["chosen"] or 0,
            "rate": round((r["chosen"] or 0) / r["pitched"], 3),
        }
        for r in rows
    ]
    total_pitched = sum(b["pitched"] for b in by_prompt)
    total_chosen = sum(b["chosen"] for b in by_prompt)
    return {
        "pitched": total_pitched,
        "chosen": total_chosen,
        "rate": round(total_chosen / total_pitched, 3) if total_pitched else None,
        "by_prompt": by_prompt,
    }


# --------------------------------------------------------------------------
# videos and numbers
# --------------------------------------------------------------------------


def add_video(
    title: str,
    platform: str,
    posted_at: str,
    idea_id: Optional[int] = None,
    url: Optional[str] = None,
    timeline: Optional[str] = None,
    topic: Optional[str] = None,
    hook_type: Optional[str] = None,
    duration_s: Optional[float] = None,
    notes: Optional[str] = None,
    brand: Optional[str] = None,
    path: Path | str = DB_PATH,
    *,
    account_id: int,
) -> int:
    """
    Store a posted video. Returns its id.

    `timeline` is the Resolve timeline name, so a posted video traces back
    to the actual project. posted_at is an ISO date like "2026-07-14".
    idea_id is optional so you can backfill videos that predate this.

    One idea posted to two platforms is two rows, because the numbers
    differ and that difference is worth seeing.
    """
    if platform not in PLATFORMS:
        raise ValueError(f"platform must be one of {PLATFORMS}, got {platform!r}")
    _check_date(posted_at, "posted_at")
    with connect(path) as conn:
        if idea_id is not None:
            if not conn.execute("SELECT 1 FROM ideas WHERE id = ?", (idea_id,)).fetchone():
                raise ValueError(f"no idea with id {idea_id}")
        cur = conn.execute(
            """
            INSERT INTO videos
                (idea_id, title, platform, posted_at, url, timeline,
                 topic, hook_type, duration_s, notes, brand, account_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (idea_id, title, platform, posted_at, url, timeline,
             topic, hook_type, duration_s, notes, brand, account_id),
        )
        return int(cur.lastrowid)


def record_metrics(
    video_id: int,
    views: Optional[int] = None,
    likes: Optional[int] = None,
    comments: Optional[int] = None,
    saves: Optional[int] = None,
    shares: Optional[int] = None,
    watch_time_seconds: Optional[float] = None,
    captured_at: Optional[str] = None,
    path: Path | str = DB_PATH,
    *,
    account_id: int,
) -> int:
    """
    Save a snapshot of how a video is doing right now.

    `metrics` carries no owner of its own: a snapshot belongs to a video,
    and the video belongs to an account. What is scoped is the right to
    write one -- you cannot attach numbers to a stranger's post.

    Call it every time you check. Do not overwrite old rows. A repeat
    write for the same timestamp updates in place rather than duplicating.
    """
    captured_at = captured_at or _now()
    with connect(path) as conn:
        owned = conn.execute(
            "SELECT 1 FROM videos WHERE id = ? AND account_id IS ?",
            (video_id, account_id),
        ).fetchone()
        if not owned:
            raise ValueError(f"no video with id {video_id}")
        cur = conn.execute(
            """
            INSERT INTO metrics
                (video_id, captured_at, views, likes, comments, saves,
                 shares, watch_time_seconds)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (video_id, captured_at) DO UPDATE SET
                views              = excluded.views,
                likes              = excluded.likes,
                comments           = excluded.comments,
                saves              = excluded.saves,
                shares             = excluded.shares,
                watch_time_seconds = excluded.watch_time_seconds
            """,
            (video_id, captured_at, views, likes, comments, saves,
             shares, watch_time_seconds),
        )
        return int(cur.lastrowid)


def list_videos(
    platform: Optional[str] = None,
    limit: int = 200,
    brand: Optional[str] = None,
    path: Path | str = DB_PATH,
    *,
    account_id: int,
) -> list[dict[str, Any]]:
    """This account's videos, newest first, optionally filtered to one
    platform and/or brand. A brand filter is NULL-inclusive -- videos
    tagged with that brand OR not yet tagged at all -- so legacy posts
    still show while the pipeline tags new ones. Ownership is not
    NULL-inclusive in the same way: `brand` is a label you may not have
    filled in, `account_id` is who the row belongs to."""
    sql = "SELECT * FROM videos"
    clauses: list[str] = ["account_id IS ?"]
    params: list[Any] = [account_id]
    if platform:
        clauses.append("platform = ?")
        params.append(platform)
    if brand:
        clauses.append("(brand = ? OR brand IS NULL)")
        params.append(brand)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY posted_at DESC LIMIT ?"
    params.append(limit)
    with connect(path) as conn:
        return [dict(r) for r in conn.execute(sql, params)]


def get_video(video_id: int, path: Path | str = DB_PATH, *,
              account_id: int) -> Optional[dict[str, Any]]:
    """
    One video's full metadata, plus its originating pitch (idea_title,
    idea_logline, idea_story_note) if idea_id is set -- all None
    otherwise. None if no such video.
    """
    with connect(path) as conn:
        row = conn.execute(
            """
            SELECT v.*, i.title AS idea_title, i.logline AS idea_logline,
                   i.story_note AS idea_story_note
            FROM videos v
            LEFT JOIN ideas i ON i.id = v.idea_id
            WHERE v.id = ? AND v.account_id IS ?
            """,
            (video_id, account_id),
        ).fetchone()
    return dict(row) if row else None


def _cutoff(
    within_days: Optional[int],
    since: Optional[str],
) -> Optional[str]:
    """
    Turn a window into a date string comparable against posted_at.

    Date-only on purpose. posted_at is often stored as "2026-07-14" with no
    time, and ISO strings compare lexically — "2026-07-14" >= a full
    "2026-07-14T09:30:00" is False, which would silently drop videos posted
    on the boundary day.
    """
    if within_days is not None and since is not None:
        raise ValueError("pass within_days or since, not both")
    if since is not None:
        _check_date(since, "since")
        return since[:10]
    if within_days is not None:
        if within_days < 1:
            raise ValueError(f"within_days must be at least 1, got {within_days}")
        return (datetime.now(timezone.utc) - timedelta(days=within_days)).date().isoformat()
    return None


def get_top_performers(
    at_days: int = 7,
    posted_within_days: Optional[int] = None,
    posted_since: Optional[str] = None,
    platform: Optional[str] = None,
    limit: int = 5,
    metric: str = "views",
    ascending: bool = False,
    path: Path | str = DB_PATH,
    *,
    account_id: int,
) -> list[dict[str, Any]]:
    """
    Your best videos, compared fairly.

    Two independent knobs, easy to confuse:

      at_days             how old each video was when measured. Every video
                          is judged at the same age, so one from last year
                          does not beat one from last month purely on
                          accumulated totals.
      posted_within_days  which videos are eligible at all. 180 for the
                          last six months.

    So at_days=7, posted_within_days=180 means: of everything posted since
    roughly January, which did best in its first week.

    Use the window when feeding retrieval. An all-time winner from two years
    ago is a poor model for what to shoot next — your style moved, the
    platform moved, the audience moved.

    ascending=True flips it to worst-first. Feed both ends to an LLM and ask
    what separates them; that is the "why did this work" analysis, and it
    needs the losers as much as the winners.

    Returns the originating pitch text where there is one.
    """
    allowed = {"views", "likes", "comments", "saves", "shares",
               "watch_time_seconds"}
    if metric not in allowed:
        raise ValueError(f"metric must be one of {sorted(allowed)}")

    cutoff = _cutoff(posted_within_days, posted_since)

    sql = f"""
        WITH snapshots AS (
            SELECT
                v.id AS video_id, v.title, v.platform, v.posted_at,
                v.topic, v.hook_type, v.timeline, v.idea_id,
                i.logline, i.story_note,
                m.{metric} AS score,
                m.captured_at,
                julianday(m.captured_at) - julianday(v.posted_at) AS age_days,
                ROW_NUMBER() OVER (
                    PARTITION BY v.id
                    ORDER BY ABS(
                        julianday(m.captured_at) - julianday(v.posted_at) - ?
                    )
                ) AS closest
            FROM videos v
            JOIN metrics m ON m.video_id = v.id
            LEFT JOIN ideas i ON i.id = v.idea_id
            WHERE m.{metric} IS NOT NULL
              AND v.account_id IS ?
              AND ABS(julianday(m.captured_at) - julianday(v.posted_at) - ?) <= ?
              {"AND substr(v.posted_at, 1, 10) >= ?" if cutoff else ""}
        )
        SELECT video_id, title, platform, posted_at, topic, hook_type,
               timeline, idea_id, logline, story_note, score, captured_at,
               ROUND(age_days, 1) AS measured_at_days
        FROM snapshots
        WHERE closest = 1
          {"AND platform = ?" if platform else ""}
        ORDER BY score {"ASC" if ascending else "DESC"}
        LIMIT ?
    """
    # order matters: the account predicate sits before the two age
    # placeholders in the WHERE clause above
    params: list[Any] = [at_days, account_id, at_days, at_days * AGE_TOLERANCE]
    if cutoff:
        params.append(cutoff)
    if platform:
        params.append(platform)
    params.append(limit)

    with connect(path) as conn:
        return [dict(r) for r in conn.execute(sql, params)]


def benchmark(
    at_days: int = 7,
    posted_within_days: Optional[int] = None,
    posted_since: Optional[str] = None,
    platform: Optional[str] = None,
    metric: str = "views",
    path: Path | str = DB_PATH,
    *,
    account_id: int,
) -> dict[str, Any]:
    """
    Median and spread for the same window, so a single video can be called
    above or below par.

    The dashboard needs this: colouring a row green for "above median"
    requires knowing the median of a comparable set, not of everything ever
    posted. Same two knobs as get_top_performers.
    """
    rows = get_top_performers(
        at_days=at_days,
        posted_within_days=posted_within_days,
        posted_since=posted_since,
        platform=platform,
        limit=100_000,
        metric=metric,
        path=path,
        account_id=account_id,
    )
    scores = sorted(r["score"] for r in rows if r["score"] is not None)
    if not scores:
        return {"n": 0, "median": None, "best": None, "worst": None}
    mid = len(scores) // 2
    median = (
        scores[mid] if len(scores) % 2
        else (scores[mid - 1] + scores[mid]) / 2
    )
    return {
        "n": len(scores),
        "median": median,
        "best": scores[-1],
        "worst": scores[0],
    }


def get_video_history(
    video_id: int, path: Path | str = DB_PATH, *, account_id: int
) -> list[dict[str, Any]]:
    """Every snapshot for one video, oldest first. The growth curve."""
    with connect(path) as conn:
        return [
            dict(r)
            for r in conn.execute(
                """
                SELECT m.*,
                       ROUND(julianday(m.captured_at)
                             - julianday(v.posted_at), 1) AS age_days
                FROM metrics m
                JOIN videos v ON v.id = m.video_id
                WHERE m.video_id = ? AND v.account_id IS ?
                ORDER BY m.captured_at ASC
                """,
                (video_id, account_id),
            )
        ]


_VIDEO_TEXT_FIELDS = {"topic", "hook_type"}


def distinct_video_field_values(field: str, path: Path | str = DB_PATH, *,
                                account_id: int) -> list[str]:
    """
    Values already used for a free-text video field, so a datalist can
    converge vocabulary without locking it down. `field` is checked
    against an allowlist rather than trusted directly -- column names
    can't be parameterized, so this is what keeps it injection-safe.
    """
    if field not in _VIDEO_TEXT_FIELDS:
        raise ValueError(f"field must be one of {sorted(_VIDEO_TEXT_FIELDS)}, got {field!r}")
    with connect(path) as conn:
        rows = conn.execute(
            f"SELECT DISTINCT {field} FROM videos "
            f"WHERE account_id IS ? AND {field} IS NOT NULL AND {field} != '' "
            f"ORDER BY {field}",
            (account_id,),
        ).fetchall()
    return [r[0] for r in rows]


def latest_metrics_by_video(path: Path | str = DB_PATH, *,
                            account_id: int) -> list[dict[str, Any]]:
    """
    One row per video with its most recent snapshot, if any. Backs
    /metrics/new's "previous value greyed behind each input" -- the
    reference point for whether a new number is worth typing.
    """
    with connect(path) as conn:
        return [
            dict(r)
            for r in conn.execute(
                """
                SELECT v.id AS video_id, v.title, v.platform, v.posted_at,
                       v.brand, m.views, m.likes, m.comments, m.saves, m.captured_at
                FROM videos v
                LEFT JOIN metrics m ON m.id = (
                    SELECT id FROM metrics
                    WHERE video_id = v.id
                    ORDER BY captured_at DESC
                    LIMIT 1
                )
                WHERE v.account_id IS ?
                ORDER BY v.posted_at DESC
                """,
                (account_id,),
            )
        ]


def summary(path: Path | str = DB_PATH) -> dict[str, int]:
    """Row counts. A quick check that things are landing."""
    with connect(path) as conn:
        return {
            t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("pitch_runs", "ideas", "videos", "metrics")
        }


def _check_date(value: str, field: str) -> None:
    try:
        datetime.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError(
            f"{field} must be an ISO date like '2026-07-14', got {value!r}"
        ) from None


def import_pitches_file(
    pitches_path: Path | str,
    path: Path | str = DB_PATH,
) -> int:
    """
    One-off: pull an existing pitches.json into the database so past runs
    are not lost. Returns the run id.
    """
    pitches = json.loads(Path(pitches_path).read_text())
    return save_pitch_run(pitches, path=path)


if __name__ == "__main__":
    init_db()
    print(f"database ready at {DB_PATH}")
    print(summary())
