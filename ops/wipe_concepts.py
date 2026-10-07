"""The one-off wipe of old concepts (2026-10-07, Mike's call: "old concepts
are wiped; testing starts fresh").

The single exception to "archiving never deletes". It REPORTS by default and
deletes only with --write, and it is not to be run with --write without
Mike's explicit go-ahead (docs/tasks/task-projects-board.md).

WHAT IT KEEPS -- a concept survives when any of these is true:

  - its id is in --keep (default: 375, the one linked to a posted video
    with metrics);
  - any shot, or any timed part of a shot, carries a `media_url` (it was
    rendered);
  - it is picked, or any shot is parked for the Queue, or it is marked shot;
  - another record still points at it: a `generated_assets` row (a paid
    render), a `videos` row (a post), a live `cut_projects` row or a
    `timelines` key `concept:<id>` (an edit), or a `fal_requests` receipt
    whose context names it (a billed render attempt). Those rows are never
    touched, so neither is the concept they point at.

WHAT IT DELETES, for every other concept of ONE account (--account, required):
the `shoot_concepts` row (its `concept_locations` rows cascade), its
concept-scoped `workflows` canvases and its `hold_queue` rows. Nothing else.
`prompt_scores` (the gate's own log, keyed by run, shared by decision),
`winning_prompts` (the shared brain) and every ledger table are left as they
are.

BEFORE ANY DELETE, with --write:

  1. every column in the schema whose name contains "concept" is listed and
     checked against the ones this script understands -- an unknown one
     refuses the write, so a table added later is decided by a person, not
     guessed at;
  2. pending winners pairs (`winning_prompts.video_ref` = `concept-<id>-shot-<n>`,
     `ingested = 0`) are ingested so their lessons reach the RAG shelves (an
     embedding call each, metered as usual); one that fails stops the write;
  3. the account's current pick / shoot rates are exported to
     docs/stats/ (they reset by design once the rows are gone);
  4. a JSON backup of every account concept and of the dependent rows about
     to go is written to data/backups/.

Then it deletes in ONE transaction, compares each table's deleted count with
the report, and rolls back if any differs. Re-runnable: a second run finds
nothing left to delete.

It never falls back to a database on its own: DATABASE_URL must be exported
(or --dsn given), and the report prints which host and database it read --
`src.accounts` once wrote to the local throwaway because nothing was
exported (CLAUDE.md, 2026-09-18).

    set -a && source .env && set +a
    venv/bin/python -m ops.wipe_concepts --account zeropage            # report only
    venv/bin/python -m ops.wipe_concepts --account zeropage --write    # after the go-ahead
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

from psycopg.conninfo import conninfo_to_dict

from src import accounts, db, preprod

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_KEEP = (375,)

# Every column named like "concept" this script knows how to treat. Anything
# else found in the schema refuses --write.
KNOWN_CONCEPT_COLUMNS = {
    "shoot_concepts.id",
    "concept_locations.concept_id",      # cascades with shoot_concepts
    "workflows.concept_id",              # deleted with the concept
    "hold_queue.concept_id",             # deleted with the concept
    "generated_assets.concept_id",       # a render: keeps its concept
    "videos.concept_id",                 # a post: keeps its concept
    "cut_projects.concept_id",           # an edit: keeps its concept
}
_PAIR_REF = re.compile(r"^concept-(\d+)-shot-\d+$")


def _where(dsn: str) -> str:
    """Host and database, never the password."""
    try:
        parts = conninfo_to_dict(dsn)
    except Exception:
        return "an unreadable DSN"
    options = parts.get("options") or ""
    return f"{parts.get('host') or 'localhost'}:{parts.get('port') or 5432}/{parts.get('dbname') or '?'}" \
        + (f" ({options})" if options else "")


def _shots(row: dict) -> list:
    try:
        shots = json.loads(row.get("shots_json") or "[]")
    except (TypeError, ValueError):
        return []
    return [s for s in shots if isinstance(s, dict)]


def _rendered(shots: list) -> bool:
    for shot in shots:
        if shot.get("media_url"):
            return True
        timeline = shot.get("timeline") if isinstance(shot.get("timeline"), dict) else {}
        if any(isinstance(p, dict) and p.get("media_url") for p in timeline.get("parts") or []):
            return True
    return False


def concept_columns(conn) -> set[str]:
    """Every `table.column` on the connection's schema whose column name
    mentions a concept."""
    rows = conn.execute(
        "SELECT table_name, column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND column_name ILIKE '%%concept%%'").fetchall()
    return {f"{r['table_name']}.{r['column_name']}" for r in rows}


def _ids(conn, sql: str, args: tuple) -> set[int]:
    return {int(r["concept_id"]) for r in conn.execute(sql, args).fetchall()
            if r["concept_id"] is not None}


def scan(dsn: str, *, account_id: int, keep_ids=DEFAULT_KEEP) -> dict[str, Any]:
    """What a wipe would do, read-only: {keep: {id: [reasons]}, delete: [ids],
    dependents: {table: n}, pending_pairs: [video_ref], unknown_columns}."""
    with db.connect(dsn) as conn:
        rows = conn.execute(
            "SELECT id, title, picked_at, shot_done, shots_json FROM shoot_concepts "
            "WHERE account_id IS NOT DISTINCT FROM %s ORDER BY id", (account_id,)).fetchall()
        tables = {r["table_name"] for r in conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = current_schema()").fetchall()}
        columns = concept_columns(conn)
        linked: dict[str, set[int]] = {}
        if "generated_assets" in tables:
            linked["a generated asset"] = _ids(
                conn, "SELECT DISTINCT concept_id FROM generated_assets "
                      "WHERE account_id IS NOT DISTINCT FROM %s", (account_id,))
        if "videos" in tables:
            linked["a posted video"] = _ids(
                conn, "SELECT DISTINCT concept_id FROM videos "
                      "WHERE account_id IS NOT DISTINCT FROM %s", (account_id,))
        if "cut_projects" in tables:
            linked["an edit"] = _ids(
                conn, "SELECT DISTINCT concept_id FROM cut_projects "
                      "WHERE account_id IS NOT DISTINCT FROM %s AND deleted_at IS NULL",
                (account_id,))
        if "timelines" in tables:
            keys = conn.execute(
                "SELECT DISTINCT project_id FROM timelines "
                "WHERE account_id IS NOT DISTINCT FROM %s AND project_id LIKE 'concept:%%'",
                (account_id,)).fetchall()
            linked.setdefault("an edit", set()).update(
                int(k["project_id"].split(":", 1)[1]) for k in keys
                if k["project_id"].split(":", 1)[1].isdigit())
        if "fal_requests" in tables:
            receipts = conn.execute(
                "SELECT context_json FROM fal_requests "
                "WHERE account_id IS NOT DISTINCT FROM %s AND context_json LIKE '%%concept_id%%'",
                (account_id,)).fetchall()
            billed = set()
            for r in receipts:
                try:
                    cid = json.loads(r["context_json"] or "{}").get("concept_id")
                except ValueError:
                    cid = None
                if isinstance(cid, int):
                    billed.add(cid)
            linked["a billed render attempt"] = billed

        keep: dict[int, list[str]] = {}
        delete: list[int] = []
        for row in rows:
            cid = int(row["id"])
            shots = _shots(row)
            why = []
            if cid in set(keep_ids):
                why.append("kept by id")
            if _rendered(shots):
                why.append("rendered")
            if row["picked_at"]:
                why.append("picked")
            if any(s.get("parked_at") for s in shots):
                why.append("parked for the Queue")
            if row["shot_done"]:
                why.append("marked shot")
            why += [f"points from {label}" for label, ids in linked.items() if cid in ids]
            if why:
                keep[cid] = why
            else:
                delete.append(cid)

        dependents = {"shoot_concepts": len(delete)}
        if "workflows" in tables:
            dependents["workflows"] = conn.execute(
                "SELECT COUNT(*) AS n FROM workflows WHERE concept_id = ANY(%s) "
                "AND account_id IS NOT DISTINCT FROM %s", (delete, account_id)).fetchone()["n"]
        if "hold_queue" in tables:
            dependents["hold_queue"] = conn.execute(
                "SELECT COUNT(*) AS n FROM hold_queue WHERE concept_id = ANY(%s) "
                "AND account_id IS NOT DISTINCT FROM %s", (delete, account_id)).fetchone()["n"]
        if "concept_locations" in tables:
            dependents["concept_locations (cascade)"] = conn.execute(
                "SELECT COUNT(*) AS n FROM concept_locations l JOIN shoot_concepts c "
                "ON c.id = l.concept_id WHERE c.id = ANY(%s) "
                "AND c.account_id IS NOT DISTINCT FROM %s", (delete, account_id)).fetchone()["n"]
        pending = []
        if "winning_prompts" in tables and delete:
            gone = set(delete)
            for r in conn.execute(
                    "SELECT DISTINCT video_ref FROM winning_prompts "
                    "WHERE ingested = 0 AND video_ref LIKE 'concept-%%-shot-%%'").fetchall():
                m = _PAIR_REF.match(r["video_ref"] or "")
                if m and int(m.group(1)) in gone:
                    pending.append(r["video_ref"])
    return {"keep": keep, "delete": delete, "dependents": dependents,
            "pending_pairs": sorted(pending),
            "unknown_columns": sorted(columns - KNOWN_CONCEPT_COLUMNS
                                      - {c for c in columns if c.startswith("shoot_concepts.")})}


def _backup(dsn: str, account_id: int, delete: list[int], out: Path) -> Path:
    with db.connect(dsn) as conn:
        concepts = conn.execute(
            "SELECT * FROM shoot_concepts WHERE account_id IS NOT DISTINCT FROM %s ORDER BY id",
            (account_id,)).fetchall()
        workflows = conn.execute(
            "SELECT * FROM workflows WHERE concept_id = ANY(%s) "
            "AND account_id IS NOT DISTINCT FROM %s", (delete, account_id)).fetchall()
        holds = conn.execute(
            "SELECT * FROM hold_queue WHERE concept_id = ANY(%s) "
            "AND account_id IS NOT DISTINCT FROM %s", (delete, account_id)).fetchall()
        places = conn.execute(
            "SELECT l.* FROM concept_locations l JOIN shoot_concepts c ON c.id = l.concept_id "
            "WHERE c.id = ANY(%s) AND c.account_id IS NOT DISTINCT FROM %s",
            (delete, account_id)).fetchall()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "written_at": datetime.now(timezone.utc).isoformat(), "account_id": account_id,
        "deleting": delete, "shoot_concepts": [dict(r) for r in concepts],
        "workflows": [dict(r) for r in workflows], "hold_queue": [dict(r) for r in holds],
        "concept_locations": [dict(r) for r in places]}, default=str, indent=1))
    return out


def _export_stats(dsn: str, account_id: int, out: Path) -> Path:
    stats = {"exported_at": datetime.now(timezone.utc).isoformat(), "account_id": account_id,
             "note": "the concept-level rates before the 2026-10-07 wipe; they reset by design"}
    for name in ("pick_rate", "shoot_rate", "reason_counts", "ungrounded_count"):
        try:
            stats[name] = getattr(preprod, name)(dsn, account_id=account_id)
        except Exception as e:                     # a missing rate is reported, never fatal
            stats[name] = f"unavailable: {e}"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(stats, default=str, indent=1))
    return out


def wipe(dsn: str, *, account_id: int, plan: dict[str, Any], ingest=None,
         project: Optional[str] = None, backup_dir: Path = ROOT / "data" / "backups",
         stats_dir: Path = ROOT / "docs" / "stats") -> dict[str, Any]:
    """Do what `plan` (a scan) says. Raises RuntimeError -- with nothing
    deleted -- on an unknown column, a pair that would not ingest, or a
    count that does not match the plan (the transaction rolls back)."""
    if plan["unknown_columns"]:
        raise RuntimeError("columns this script does not understand point at concepts: "
                           + ", ".join(plan["unknown_columns"]) + " -- decide them first")
    delete = plan["delete"]
    if not delete:
        return {"deleted": {}, "backup": None, "stats": None}
    if ingest is None:
        from src import winners

        def ingest(ref):
            return winners.ingest_pending(ref, dsn=dsn, project=project)
    failed = [ref for ref in plan["pending_pairs"] if not (ingest(ref) or {}).get("ok")]
    if failed:
        raise RuntimeError("these pending lessons would not ingest, so nothing was deleted: "
                           + ", ".join(failed))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    stats = _export_stats(dsn, account_id, stats_dir / f"concept-rates-before-wipe-{account_id}-{date.today()}.json")
    backup = _backup(dsn, account_id, delete, backup_dir / f"wipe-concepts-{account_id}-{stamp}.json")

    expected = plan["dependents"]
    done: dict[str, int] = {}
    with db.connect(dsn) as conn:
        done["workflows"] = conn.execute(
            "DELETE FROM workflows WHERE concept_id = ANY(%s) "
            "AND account_id IS NOT DISTINCT FROM %s", (delete, account_id)).rowcount
        done["hold_queue"] = conn.execute(
            "DELETE FROM hold_queue WHERE concept_id = ANY(%s) "
            "AND account_id IS NOT DISTINCT FROM %s", (delete, account_id)).rowcount
        done["shoot_concepts"] = conn.execute(
            "DELETE FROM shoot_concepts WHERE id = ANY(%s) "
            "AND account_id IS NOT DISTINCT FROM %s", (delete, account_id)).rowcount
        off = {k: (expected.get(k), v) for k, v in done.items() if expected.get(k, v) != v}
        if off:
            # raising inside db.connect rolls the whole transaction back
            raise RuntimeError(f"deleted counts differ from the report, rolled back: {off}")
    return {"deleted": done, "backup": str(backup), "stats": str(stats)}


def _print_plan(plan: dict[str, Any]) -> None:
    keep, delete = plan["keep"], plan["delete"]
    print(f"\n  keep {len(keep)} concept(s):")
    for cid, why in sorted(keep.items()):
        print(f"    #{cid:<6} {', '.join(why)}")
    print(f"\n  delete {len(delete)} concept(s)"
          + (f": {', '.join(f'#{i}' for i in delete[:40])}" + (" …" if len(delete) > 40 else "")
             if delete else ""))
    print("\n  rows that go with them:")
    for table, n in plan["dependents"].items():
        print(f"    {table:<30} {n}")
    print(f"\n  pending lessons to ingest first: {len(plan['pending_pairs'])}")
    if plan["unknown_columns"]:
        print("\n  !! columns this script does not understand (a write will refuse):")
        for c in plan["unknown_columns"]:
            print(f"     {c}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Wipe old concepts (report by default).")
    ap.add_argument("--account", required=True, help="account slug, e.g. zeropage")
    ap.add_argument("--dsn", help="database URL (default: the exported DATABASE_URL)")
    ap.add_argument("--keep", default=",".join(str(i) for i in DEFAULT_KEEP),
                    help="concept ids always kept (comma separated; default 375)")
    ap.add_argument("--write", action="store_true",
                    help="actually delete; without it this only reports")
    args = ap.parse_args(argv)

    dsn = args.dsn or os.environ.get("DATABASE_URL")
    if not dsn:
        print("refusing: no --dsn and no DATABASE_URL exported -- this script never "
              "guesses which database to delete from (`set -a && source .env && set +a`)",
              file=sys.stderr)
        return 2
    keep_ids = tuple(int(x) for x in args.keep.split(",") if x.strip().isdigit())
    account_id = accounts.resolve_account(args.account, dsn=dsn)
    if account_id is None:
        print(f"refusing: no account {args.account!r} on {_where(dsn)}", file=sys.stderr)
        return 2
    print(f"database: {_where(dsn)}")
    print(f"account:  {args.account} (id {account_id}) · always kept: {', '.join(map(str, keep_ids))}")
    plan = scan(dsn, account_id=account_id, keep_ids=keep_ids)
    _print_plan(plan)
    if not args.write:
        print("\n  report only -- nothing was changed. Re-run with --write after the go-ahead.")
        return 0
    try:
        result = wipe(dsn, account_id=account_id, plan=plan, project=args.account)
    except RuntimeError as e:
        print(f"\n  stopped: {e}", file=sys.stderr)
        return 3
    print(f"\n  deleted: {result['deleted']}")
    print(f"  backup:  {result['backup']}")
    print(f"  rates:   {result['stats']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
