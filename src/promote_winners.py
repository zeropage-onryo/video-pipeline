#!/usr/bin/env python3
"""
Closes the loop the rest of the pipeline leaves open: db.py knows which
videos performed, rag.py grounds pitch.py/shootgen.py in reference
material, but nothing carries a proven winner from one into the other.
Every future pitch keeps drawing on outside craft references and on the
brand/footage record -- never on "here is a concept of ours that
actually worked." winning_prompts() already closes an equivalent loop
for generation prompts (feeding promptgen.py directly out of SQLite);
this is the same idea for concepts, one layer up, and it has to go
through RAG because that is what pitch.py/shootgen.py actually read.

Two steps, not one, on purpose -- same shape as inbox-sweep's trash
list and daily-brief's close-out: `propose` finds candidates and writes
them to a queue file without touching the RAG store; `approve` (or
`reject`) is the human decision that actually changes what future
generations are grounded against. A video can do well for the wrong
reason -- a giveaway, a controversy, a platform quirk -- and silently
promoting that poisons every pitch after it. That mistake compounds
quietly, because nobody re-reads the reference shelf once it's set.

`run --auto` composes propose+approve for candidates that clear
AUTO_THRESHOLD, no queue file and no review step in between. It is the
on-ramp to running this unattended once you trust the threshold --
point a schedule at it later -- without a second implementation to
build when that day comes.
"""
import argparse
import json
from pathlib import Path
from typing import Any, Optional

from . import db, post_seo, rag

PROJECT_ROOT = Path(__file__).resolve().parent.parent
QUEUE_PATH = PROJECT_ROOT / "data" / "promotion_queue.json"

# The shelf label proven winners live under -- never mixed with
# personal_brand/cinematography (what the brand *is*) or marketing/
# ai_prompting (outside craft). A pitch that grounds against this shelf
# is grounding against "what actually worked for us", nothing else.
DOMAIN = "proven_results"

# A candidate must beat its comparison-window median by at least this
# multiple to be proposed at all. Filters "did fine" out so the queue
# stays short enough to actually read.
MIN_MULTIPLE = 1.2

# run --auto only promotes candidates clearing this higher bar, with no
# human in the loop -- deliberately stricter than MIN_MULTIPLE, which
# only has to clear the bar for a person to *see* it, not to act
# without one.
AUTO_THRESHOLD = 2.0


def source_key(video_id: int) -> str:
    """
    The stable RAG source identity for a promoted video. Deterministic
    and re-derivable from the video id alone, so re-promoting the same
    video replaces its chunks (per rag.ingest_records) instead of
    duplicating them, and _promoted_video_ids can recover the id set
    from rag.list_sources without a second tracking table.
    """
    return f"{DOMAIN}/video-{video_id}.txt"


def _promoted_video_ids(conn) -> set:
    rag.init_store(conn)
    ids = set()
    for row in rag.list_sources(conn):
        if row["domain"] != DOMAIN:
            continue
        # "proven_results/video-42.txt" -> 42
        tail = row["source"].rsplit("-", 1)[-1]
        ids.add(int(tail.removesuffix(".txt")))
    return ids


def render_reference_doc(candidate: dict, signals: Optional[dict] = None) -> str:
    """
    The reference text that lands in RAG for a winning video: what the
    concept was, plus enough performance context that a future pitch
    reads it as "this worked", not just "this happened".

    With `signals` (post_seo.derive_signals over the same window), the
    doc also names the *patterns* across the window's winners and losers
    -- hooks, topics, title words -- so retrieval returns actionable
    field-level signal, not just one video's story.
    """
    lines = [f"WINNING CONCEPT -- {candidate['title']} ({candidate['platform']})"]
    if candidate.get("logline"):
        lines.append(f"Logline: {candidate['logline']}")
    if candidate.get("story_note"):
        lines.append(f"Story note: {candidate['story_note']}")
    tags = ", ".join(
        f"{label}: {candidate[key]}"
        for label, key in (("Hook type", "hook_type"), ("Topic", "topic"))
        if candidate.get(key)
    )
    if tags:
        lines.append(tags)
    lines.append(
        f"Performance: {candidate['score']:,.0f} {candidate['metric']} at "
        f"{candidate['measured_at_days']:.0f} days -- "
        f"{candidate['multiple']:.1f}x the {candidate['median']:,.0f} median "
        f"for videos posted in the same comparison window."
    )
    if signals and signals.get("sample"):
        def top(counter, n=3):
            items = sorted(counter.items(), key=lambda kv: -kv[1])[:n]
            return ", ".join(f"{k} ({v})" for k, v in items)

        lines.append("Patterns across this window's winners:")
        if signals["winning_topics"]:
            lines.append(f"  winning topics: {top(signals['winning_topics'])}")
        if signals["winning_hooks"]:
            lines.append(f"  winning hooks: {top(signals['winning_hooks'])}")
        if signals["winning_title_words"]:
            lines.append(f"  winning title words: {top(signals['winning_title_words'], 5)}")
        losing = []
        if signals["losing_topics"]:
            losing.append(f"topics {top(signals['losing_topics'])}")
        if signals["losing_hooks"]:
            losing.append(f"hooks {top(signals['losing_hooks'])}")
        if losing:
            lines.append(f"  below-median patterns to avoid: {'; '.join(losing)}")
    return "\n".join(lines)


def candidate_winners(
    at_days: int = 7,
    posted_within_days: Optional[int] = 180,
    platform: Optional[str] = None,
    metric: str = "views",
    limit: int = 20,
    min_multiple: float = MIN_MULTIPLE,
    db_path=None,
    conn=None,
) -> list[dict[str, Any]]:
    """
    Videos that beat their comparison-window median by at least
    min_multiple, and are not already sitting on the proven_results
    shelf. Pass a live RAG connection in `conn` to reuse one across a
    propose/run call; without one, nothing has been promoted yet is
    assumed (used by tests and by callers that only care about the
    db.py side).
    """
    kwargs = {"path": db_path} if db_path is not None else {}
    bench = db.benchmark(
        at_days=at_days, posted_within_days=posted_within_days,
        platform=platform, metric=metric, **kwargs,
    )
    if not bench["median"]:
        return []

    already_promoted = _promoted_video_ids(conn) if conn is not None else set()

    rows = db.get_top_performers(
        at_days=at_days, posted_within_days=posted_within_days,
        platform=platform, metric=metric, limit=limit, **kwargs,
    )
    out = []
    for row in rows:
        if row["video_id"] in already_promoted or not row["score"]:
            continue
        multiple = row["score"] / bench["median"]
        if multiple < min_multiple:
            continue
        out.append({**row, "metric": metric, "median": bench["median"], "multiple": multiple})
    return out


def _window_signals(kwargs: dict) -> Optional[dict]:
    """post_seo signals for the same comparison window as the candidate
    query, so the patterns written into a doc describe the field that
    video actually beat. Never raises -- a signal failure just means a
    doc without a Patterns section."""
    try:
        return post_seo.derive_signals(
            at_days=kwargs.get("at_days", 7),
            posted_within_days=kwargs.get("posted_within_days", 180),
            metric=kwargs.get("metric", "views"),
            db_path=kwargs.get("db_path"),
        )
    except Exception:
        return None


def _to_queue_entry(c: dict, signals: Optional[dict] = None) -> dict:
    return {
        "video_id": c["video_id"], "idea_id": c["idea_id"],
        "title": c["title"], "platform": c["platform"],
        "metric": c["metric"], "score": c["score"],
        "median": c["median"], "multiple": round(c["multiple"], 2),
        "doc": render_reference_doc(c, signals=signals),
    }


def _ingest_candidates(candidates: list, signals: Optional[dict] = None) -> None:
    records = [
        {"source": source_key(c["video_id"]),
         "text": render_reference_doc(c, signals=signals),
         "domain": DOMAIN, "source_ref": f"video:{c['video_id']}"}
        for c in candidates
    ]
    if not records:
        return
    client = rag.make_client()
    conn = rag.connect()
    try:
        rag.init_store(conn)
        rag.ingest_records(records, client, conn)
    finally:
        conn.close()


def propose(**kwargs) -> list[dict[str, Any]]:
    """
    Find candidates and write them to the queue file. Never ingests --
    that only happens on approve, once a person has looked at the list.
    """
    conn = rag.connect()
    try:
        candidates = candidate_winners(conn=conn, **kwargs)
    finally:
        conn.close()

    signals = _window_signals(kwargs)
    queue = [_to_queue_entry(c, signals=signals) for c in candidates]
    QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    QUEUE_PATH.write_text(json.dumps(queue, indent=2))
    return queue


def _load_queue() -> list[dict[str, Any]]:
    if not QUEUE_PATH.exists():
        return []
    return json.loads(QUEUE_PATH.read_text())


def _save_queue(queue: list[dict[str, Any]]) -> None:
    QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    QUEUE_PATH.write_text(json.dumps(queue, indent=2))


def approve(video_ids: Optional[list] = None) -> dict[str, Any]:
    """
    Ingest queued entries into RAG under the proven_results shelf.
    video_ids=None approves everything still queued; a list approves
    only those ids, leaving the rest queued for a later decision.
    """
    queue = _load_queue()
    to_promote = [c for c in queue if video_ids is None or c["video_id"] in video_ids]
    if not to_promote:
        return {"promoted": 0, "video_ids": []}

    client = rag.make_client()
    conn = rag.connect()
    try:
        rag.init_store(conn)
        records = [
            {"source": source_key(c["video_id"]), "text": c["doc"],
             "domain": DOMAIN, "source_ref": f"video:{c['video_id']}"}
            for c in to_promote
        ]
        rag.ingest_records(records, client, conn)
    finally:
        conn.close()

    promoted_ids = {c["video_id"] for c in to_promote}
    _save_queue([c for c in queue if c["video_id"] not in promoted_ids])
    return {"promoted": len(to_promote), "video_ids": sorted(promoted_ids)}


def reject(video_ids: list) -> dict[str, Any]:
    """Drop entries from the queue without ingesting them."""
    queue = _load_queue()
    remaining = [c for c in queue if c["video_id"] not in video_ids]
    dropped = len(queue) - len(remaining)
    _save_queue(remaining)
    return {"dropped": dropped}


def run_auto(**kwargs) -> dict[str, Any]:
    """
    propose + approve in one call, restricted to candidates clearing
    AUTO_THRESHOLD -- no queue file, no review step. The unattended
    path: once you trust the threshold, point a schedule at
    `promote_winners run --auto` and every future pitch/shootgen call
    grounds against new winners without you touching it.
    """
    kwargs.setdefault("min_multiple", AUTO_THRESHOLD)
    conn = rag.connect()
    try:
        candidates = candidate_winners(conn=conn, **kwargs)
    finally:
        conn.close()

    _ingest_candidates(candidates, signals=_window_signals(kwargs))
    return {"promoted": len(candidates),
            "video_ids": sorted(c["video_id"] for c in candidates)}


def main(argv=None) -> None:
    from dotenv import load_dotenv
    load_dotenv()

    parser = argparse.ArgumentParser(
        prog="promote_winners",
        description="Promote proven-performing videos into the RAG store as reference material.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_propose = sub.add_parser("propose", help="find candidates, write the review queue")
    p_propose.add_argument("--at-days", type=int, default=7)
    p_propose.add_argument("--posted-within-days", type=int, default=180)
    p_propose.add_argument("--platform")
    p_propose.add_argument("--metric", default="views")
    p_propose.add_argument("--min-multiple", type=float, default=MIN_MULTIPLE)

    p_approve = sub.add_parser("approve", help="ingest queued candidates into RAG")
    p_approve.add_argument("--ids", help="comma-separated video ids; default is all queued")

    p_reject = sub.add_parser("reject", help="drop queued candidates without ingesting")
    p_reject.add_argument("ids", help="comma-separated video ids")

    sub.add_parser("list", help="show what's currently queued")

    p_run = sub.add_parser("run", help="propose+approve in one call, no review step")
    p_run.add_argument("--auto", action="store_true", required=True,
                       help="required -- makes it explicit this call skips review")
    p_run.add_argument("--at-days", type=int, default=7)
    p_run.add_argument("--posted-within-days", type=int, default=180)
    p_run.add_argument("--platform")
    p_run.add_argument("--metric", default="views")

    args = parser.parse_args(argv)

    if args.command == "propose":
        queue = propose(
            at_days=args.at_days, posted_within_days=args.posted_within_days,
            platform=args.platform, metric=args.metric, min_multiple=args.min_multiple,
        )
        if not queue:
            print("No new candidates clear the bar.")
        else:
            for c in queue:
                print(f"[{c['video_id']}] {c['title']} -- {c['multiple']}x median "
                      f"({c['score']} {c['metric']})")
            print(f"\n{len(queue)} candidate(s) written to {QUEUE_PATH}")
            print("Review, then: promote_winners approve --ids <id,id,...>  (omit --ids for all)")

    elif args.command == "approve":
        ids = [int(x) for x in args.ids.split(",")] if args.ids else None
        result = approve(ids)
        print(f"Promoted {result['promoted']} video(s): {result['video_ids']}")

    elif args.command == "reject":
        ids = [int(x) for x in args.ids.split(",")]
        result = reject(ids)
        print(f"Dropped {result['dropped']} candidate(s) from the queue")

    elif args.command == "list":
        queue = _load_queue()
        if not queue:
            print("Queue is empty.")
        for c in queue:
            print(f"[{c['video_id']}] {c['title']} -- {c['multiple']}x median")

    elif args.command == "run":
        result = run_auto(
            at_days=args.at_days, posted_within_days=args.posted_within_days,
            platform=args.platform, metric=args.metric,
        )
        print(f"Auto-promoted {result['promoted']} video(s): {result['video_ids']}")


if __name__ == "__main__":
    main()
