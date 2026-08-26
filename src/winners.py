"""
Human feedback on prompts -- BOTH directions. The automatic loops can't
capture your hand judgment: promote_winners promotes concepts by
analytics, generative tracks render attempts. This lets you say, by hand,
per prompt:

  - "this WORKED" -> embedded into the RAG 'winning_prompts' shelf so
    future generations imitate your proven phrasing, and
  - "this DIDN'T work (+ why)" -> embedded into the RAG 'avoid_prompts'
    shelf AND surfaced as a negative steer the generator is told to avoid.

add() persists durably in SQLite (never lost if the RAG store is down);
ingest_to_rag() teaches it to the right shelf by verdict. Same shape as
autonomy.py/entities.py: own SCHEMA, own init(), one shared SQLite file.
"""
from __future__ import annotations

from datetime import datetime, timezone

from . import db

DOMAIN = "winning_prompts"        # the "worked" shelf shootgen grounds on
AVOID_DOMAIN = "avoid_prompts"    # the "didn't work" shelf -> negative steer

SCHEMA = """
CREATE TABLE IF NOT EXISTS winning_prompts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    tool       TEXT NOT NULL DEFAULT 'runway',   -- runway | midjourney
    prompt     TEXT NOT NULL,                     -- the final, edited prompt text
    note       TEXT,                              -- why it worked / why it failed
    video_ref  TEXT,                              -- link/id of the finished piece
    verdict    TEXT NOT NULL DEFAULT 'worked',    -- worked | didnt_work
    pair_id    INTEGER,                           -- the other half of a fix pair
    rag_source TEXT,
    ingested   INTEGER NOT NULL DEFAULT 0
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm_verdict(v) -> str:
    v = str(v or "worked").strip().lower()
    return "didnt_work" if v.startswith(("didn", "no", "fail", "bad")) else "worked"


def init(path=db.DB_PATH) -> None:
    with db.connect(path) as conn:
        conn.executescript(SCHEMA)
        # migrate: add verdict to a table that predates it
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(winning_prompts)")}
        if "verdict" not in cols:
            conn.execute("ALTER TABLE winning_prompts ADD COLUMN "
                         "verdict TEXT NOT NULL DEFAULT 'worked'")
        if "pair_id" not in cols:
            conn.execute("ALTER TABLE winning_prompts ADD COLUMN pair_id INTEGER")


def add(tool, prompt, note="", video_ref="", verdict="worked", path=db.DB_PATH) -> int:
    prompt = (prompt or "").strip()
    if not prompt:
        raise ValueError("a prompt cannot be empty")
    with db.connect(path) as conn:
        cur = conn.execute(
            "INSERT INTO winning_prompts (created_at, tool, prompt, note, "
            "video_ref, verdict) VALUES (?, ?, ?, ?, ?, ?)",
            (_now(), (tool or "runway").strip().lower(), prompt,
             (note or "").strip(), (video_ref or "").strip(), _norm_verdict(verdict)))
        return cur.lastrowid


def get(entry_id, path=db.DB_PATH):
    with db.connect(path) as conn:
        row = conn.execute(
            "SELECT * FROM winning_prompts WHERE id = ?", (entry_id,)).fetchone()
        return dict(row) if row else None


def list_all(path=db.DB_PATH) -> list:
    with db.connect(path) as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM winning_prompts ORDER BY created_at DESC")]


def _render_doc(w: dict, pair: dict | None = None) -> str:
    """One entry as the text that gets embedded. A paired entry carries
    the OTHER half in its own document: the lesson in "this failed, this
    worked instead" is the contrast between them, and a doc holding only
    one side can't teach it -- retrieval hits one chunk, not both."""
    if w.get("verdict") == "didnt_work":
        lines = [f"AVOID -- a {w['tool'].upper()} prompt that DID NOT work. "
                 "Do not imitate this; steer away from what made it fail."]
        if w.get("note"):
            lines.append(f"Why it failed: {w['note']}")
        lines.append(f"Failed prompt: {w['prompt']}")
        if pair:
            lines.append("What was written instead, and DID work -- prefer this "
                         f"shape: {pair['prompt']}")
        return "\n".join(lines)
    lines = [f"WINNING {w['tool'].upper()} PROMPT -- your own proven record; "
             "match this phrasing and style when it fits the shot."]
    if w.get("note"):
        lines.append(f"Why it won: {w['note']}")
    if w.get("video_ref"):
        lines.append(f"Finished piece: {w['video_ref']}")
    lines.append(f"Prompt: {w['prompt']}")
    if pair:
        lines.append("This was the FIX for an attempt that failed. The failed "
                     f"version, for contrast: {pair['prompt']}")
    return "\n".join(lines)


def ingest_to_rag(entry_id, path=db.DB_PATH) -> dict:
    """Embed the entry into the right RAG shelf by verdict (winning_prompts
    or avoid_prompts). Never raises -- if the store is down it stays saved
    and can be re-ingested."""
    w = get(entry_id, path=path)
    if not w:
        return {"ok": False, "error": "no such entry"}
    pair = get(w["pair_id"], path=path) if w.get("pair_id") else None
    domain = AVOID_DOMAIN if w.get("verdict") == "didnt_work" else DOMAIN
    try:
        from . import rag
        source = f"{domain}/entry-{entry_id}.txt"
        client = rag.make_client()
        conn = rag.connect()
        try:
            rag.init_store(conn)
            written = rag.ingest_records(
                [{"source": source, "text": _render_doc(w, pair), "domain": domain,
                  "source_ref": w.get("video_ref") or None}], client, conn)
        finally:
            conn.close()
        with db.connect(path) as c:
            c.execute("UPDATE winning_prompts SET ingested = 1, rag_source = ? "
                      "WHERE id = ?", (source, entry_id))
        return {"ok": True, "chunks": written}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def record_and_learn(tool, prompt, note="", video_ref="", verdict="worked",
                     path=db.DB_PATH) -> dict:
    entry_id = add(tool, prompt, note=note, video_ref=video_ref,
                   verdict=verdict, path=path)
    result = ingest_to_rag(entry_id, path=path)
    return {"id": entry_id, "verdict": _norm_verdict(verdict),
            "ingested": result.get("ok", False), "error": result.get("error")}


def record_pair(tool, failed_prompt, working_prompt, note="", video_ref="",
                path=db.DB_PATH) -> dict:
    """
    The strongest feedback shape there is: "this one failed, and THIS is
    what I wrote instead that worked."

    Two rows, linked both ways, landing on both shelves -- the failure on
    avoid_prompts and the fix on winning_prompts -- with each document
    naming the other. Recording only the failure teaches what to run from
    without saying where to run to; recording only the fix throws away the
    contrast that makes it legible.

    Ingest is best-effort per half, the standing contract: a store that
    dies between the two writes leaves both rows saved and re-ingestable
    rather than losing the label.
    """
    failed_prompt = (failed_prompt or "").strip()
    working_prompt = (working_prompt or "").strip()
    if not working_prompt:
        raise ValueError("record_pair needs the prompt that actually worked")
    failed_id = add(tool, failed_prompt, note=note, video_ref=video_ref,
                    verdict="didnt_work", path=path)
    worked_id = add(tool, working_prompt, note=note, video_ref=video_ref,
                    verdict="worked", path=path)
    with db.connect(path) as conn:
        conn.execute("UPDATE winning_prompts SET pair_id = ? WHERE id = ?",
                     (worked_id, failed_id))
        conn.execute("UPDATE winning_prompts SET pair_id = ? WHERE id = ?",
                     (failed_id, worked_id))
    failed_result = ingest_to_rag(failed_id, path=path)
    worked_result = ingest_to_rag(worked_id, path=path)
    return {
        "id": worked_id, "failed_id": failed_id, "worked_id": worked_id,
        "verdict": "pair", "paired": True,
        "ingested": bool(failed_result.get("ok") and worked_result.get("ok")),
        "error": failed_result.get("error") or worked_result.get("error"),
    }


def avoid_guidance(limit=8, path=db.DB_PATH) -> str:
    """A negative-steer block from prompts you marked 'didn't work', folded
    into generation so the next batch avoids repeating them. '' when none."""
    try:
        init(path)  # ensure the table + verdict column exist before querying
        with db.connect(path) as conn:
            rows = [dict(r) for r in conn.execute(
                "SELECT tool, note FROM winning_prompts WHERE verdict = 'didnt_work' "
                "ORDER BY created_at DESC LIMIT ?", (limit,))]
    except Exception:
        return ""   # negative steer is best-effort; never block a generation
    if not rows:
        return ""
    lines = ["AVOID what has failed before (do not repeat these):"]
    for r in rows:
        why = f" — {r['note']}" if r.get("note") else ""
        lines.append(f"- [{(r.get('tool') or 'runway')}]{why}")
    return "\n".join(lines)
