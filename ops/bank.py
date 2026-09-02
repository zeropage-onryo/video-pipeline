#!/usr/bin/env python3
"""
ops/bank.py -- put an agent's research into the scout's bank, from a
file instead of from a live MCP connection.

    python -m ops.bank spark --brand zeropage --spark "..." --rationale "..."
    python -m ops.bank reference --finding 12 --url https://... --source https://...
    python -m ops.bank ingest data/idea_agent            # what 6am runs
    python -m ops.bank list --unused

WHY THIS EXISTS, GIVEN bank_spark ALREADY DOES IT.

`src/mcp_server.py` already holds the rules for banking a direction and
a reference image, and this file imports them rather than restating
them -- two implementations of "what a banked spark is" is the drift
bug this repo has paid for twice already (see asset_shelf, refbin).
What it does NOT have is a way to be *reached* on a schedule.

An MCP server never runs itself; a client drives it. So Claude-over-MCP
cannot be the thing that fills the bank before the 6am batch -- it can
only fill it when somebody is sitting there asking. And the desktop
connection is the wrong dependency for a cron path anyway: it needs the
app running, registered and awake at 5am on one specific Mac.

So the agent writes a PLAN FILE into `data/idea_agent/` -- plain JSON,
no database, no venv, no network -- and the morning batch ingests it
seconds before it needs it, on this machine, in the real venv, where
`refbin.fetch` has a network and `data/pipeline.db` is a local file
rather than a mounted one. Two consequences worth having:

- **A night with no agent still runs.** No plan file is not an error;
  ingest reports nothing to do and the crawl and sparks.txt rotation
  carry the night exactly as before. Same degrade-don't-break posture
  as every other lane here.
- **The plan is reviewable before it fires.** It is a file, sitting in
  the repo, that says which directions were proposed and which images
  are meant to ground them. A spark that goes straight into a database
  from a chat window is not something anybody reads twice.

The images are fetched at INGEST time, not when the plan was written.
That is deliberate -- the fetch has to happen where refbin's guards and
this machine's disk are -- but it means a URL that has expired by 6am
banks nothing. A dead link is a missing picture, never a failed plan.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# Where the agent leaves its plans. Inside data/ because it is state,
# not source, and data/ is already what the backups copy.
PLANS_DIR = PROJECT_ROOT / "data" / "idea_agent"


def _plans(source: Path) -> list[Path]:
    """Every plan waiting in a directory, oldest name first -- or the
    one file that was named directly."""
    if source.is_file():
        return [source]
    if not source.is_dir():
        return []
    return sorted(p for p in source.glob("*.json") if p.is_file())


def read_plan(path: Path) -> list[dict]:
    """A plan file as a list of spark dicts.

    Two shapes accepted, because an agent writing JSON by hand produces
    both: a bare list, or an object with a `sparks` key beside whatever
    else it wanted to record (when it ran, what it read). Anything else
    raises -- a malformed plan should be seen, not silently skipped.
    """
    data = json.loads(path.read_text())
    if isinstance(data, dict):
        data = data.get("sparks")
    if not isinstance(data, list):
        raise ValueError("a plan is a list of sparks, or an object with a "
                         "'sparks' list")
    return [s for s in data if isinstance(s, dict)]


def bank_one(entry: dict, *, path, dry_run: bool = False) -> dict:
    """One spark and the images behind it. Never raises: a bad entry in
    a plan of eight must not cost the other seven."""
    from src import mcp_server, scout

    brand = (entry.get("brand") or "").strip()
    spark = " ".join((entry.get("spark") or "").split())
    out = {"brand": brand, "spark": spark, "id": None, "images": 0,
           "errors": []}
    if not spark:
        out["errors"].append("empty spark")
        return out

    # A STAKE IS REQUIRED, in code, the way novelty is.
    #
    # `prompts/scout_digest_prompt.txt` says it plainly -- "a candidate
    # you cannot write a stake for is a candidate to throw away" -- and
    # the crawl is held to it by its scoring rubric. Nothing held an
    # AGENT to it, and this is not a hypothetical failure: four camera
    # specs ("macro zoom tracking a pulsing wrist") sat in the bank at
    # 0.80 and above with no stake between them, and the shoot rate off
    # them was zero. Asking a prompt for a field and then accepting
    # entries without it is steering nothing.
    #
    # Refused rather than scored down, because a plan file is written
    # deliberately: a missing stake there is an entry to fix and
    # re-bank, not a weak signal to rank below the others.
    if not (entry.get("stake") or "").strip():
        out["errors"].append(f"no stake — {spark[:48]!r} refused; a spark with "
                             f"no feeling under it is a weird GIF")
        return out

    if dry_run:
        out["images"] = len(entry.get("images") or [])
        return out

    # turn + stake live in the rationale column, folded by the same
    # function record() uses, so an agent-banked spark reads exactly
    # like a crawled one on the board rather than losing both fields.
    try:
        banked = mcp_server.bank_spark(
            brand, spark,
            rationale=scout._fold_reasoning({
                "turn": (entry.get("turn") or "").strip(),
                "stake": (entry.get("stake") or "").strip(),
                "rationale": (entry.get("rationale") or "").strip()}),
            evidence=(entry.get("evidence") or "").strip(),
            score=float(entry.get("score", mcp_server.HUMAN_SPARK_SCORE)),
            path=path)
    except Exception as e:
        out["errors"].append(f"{type(e).__name__}: {e}")
        return out
    out["id"] = banked["id"]
    if banked.get("duplicate_of"):
        # Reported, not refused -- same call bank_spark makes. A repeat
        # is usually meant; it is only the CRAWL that must not
        # rediscover its own findings.
        out["errors"].append(f"repeats finding {banked['duplicate_of']}")

    for image in (entry.get("images") or []):
        if not isinstance(image, dict):
            continue
        try:
            result = mcp_server.bank_reference(
                out["id"], (image.get("url") or "").strip(),
                source_url=(image.get("source_url") or "").strip(),
                title=(image.get("title") or "").strip(), path=path)
        except Exception as e:
            out["errors"].append(f"{type(e).__name__}: {e}")
            continue
        if result.get("ok"):
            out["images"] += 1
        else:
            out["errors"].append(f"{image.get('url', '?')[:60]}: "
                                 f"{result.get('error', 'not banked')}")
    return out


def ingest(source: Path, *, path, dry_run: bool = False,
           keep: bool = False) -> dict:
    """Bank every plan in a directory and file it away.

    A plan is moved to `done/` once it has been read, whether or not
    every image in it landed -- an ingested plan must never run twice,
    and a half-banked one re-run would double the sparks and leave the
    night preferring yesterday's research to today's.
    """
    plans = _plans(source)
    summary = {"plans": len(plans), "sparks": 0, "images": 0, "errors": []}
    for plan in plans:
        try:
            entries = read_plan(plan)
        except Exception as e:
            summary["errors"].append(f"{plan.name}: unreadable ({e})")
            continue
        for entry in entries:
            result = bank_one(entry, path=path, dry_run=dry_run)
            if result["id"] or dry_run:
                summary["sparks"] += 1
            summary["images"] += result["images"]
            for err in result["errors"]:
                summary["errors"].append(f"{plan.name}: {err}")
        if dry_run or keep:
            continue
        done = plan.parent / "done"
        try:
            done.mkdir(parents=True, exist_ok=True)
            shutil.move(str(plan), str(done / plan.name))
        except Exception as e:
            summary["errors"].append(
                f"{plan.name}: banked but not filed away ({e}) -- move it by "
                f"hand or the next run banks it again")
    return summary


def main(argv=None) -> int:
    load_dotenv()
    from src import db, mcp_server, scout

    parser = argparse.ArgumentParser(
        description="Put an agent's research into the scout's bank.")
    parser.add_argument("--db", default=None, help="database path (testing)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_spark = sub.add_parser("spark", help="bank one direction")
    p_spark.add_argument("--brand", choices=scout.BRANDS, required=True)
    p_spark.add_argument("--spark", required=True)
    p_spark.add_argument("--rationale", default="")
    p_spark.add_argument("--evidence", default="")
    p_spark.add_argument("--score", type=float,
                         default=mcp_server.HUMAN_SPARK_SCORE)

    p_ref = sub.add_parser("reference", help="bank one image behind a spark")
    p_ref.add_argument("--finding", type=int, required=True)
    p_ref.add_argument("--url", required=True)
    p_ref.add_argument("--source", required=True,
                       help="the page it came off -- required, it is attribution")
    p_ref.add_argument("--title", default="")

    p_in = sub.add_parser("ingest", help="bank every plan file in a directory")
    p_in.add_argument("source", nargs="?", default=str(PLANS_DIR))
    p_in.add_argument("--dry-run", action="store_true",
                      help="say what would be banked, touch nothing")
    p_in.add_argument("--keep", action="store_true",
                      help="do not move plans to done/ afterwards")

    p_list = sub.add_parser("list", help="what is in the bank")
    p_list.add_argument("--brand", choices=scout.BRANDS, default=None)
    p_list.add_argument("--unused", action="store_true")

    args = parser.parse_args(argv)
    path = Path(args.db) if args.db else db.DB_PATH
    scout.init(path)

    if args.command == "spark":
        out = mcp_server.bank_spark(args.brand, args.spark,
                                    rationale=args.rationale,
                                    evidence=args.evidence, score=args.score,
                                    path=path)
        print(f"banked #{out['id']} [{out['score']:.2f}] {out['spark']}")
        if out["duplicate_of"]:
            print(f"  note: repeats {out['duplicate_of']}", file=sys.stderr)
        if not out["serves_next"]:
            print(f"  note: below the {scout.SCORE_FLOOR} floor — no run will "
                  f"take it", file=sys.stderr)
        return 0

    if args.command == "reference":
        out = mcp_server.bank_reference(args.finding, args.url,
                                        source_url=args.source,
                                        title=args.title, path=path)
        if not out.get("ok"):
            print(f"not banked: {out.get('error')}", file=sys.stderr)
            return 1
        print(f"banked {out['url']} <- {out['source_url']} "
              f"({out['banked']}/{out['cap']})")
        return 0

    if args.command == "ingest":
        summary = ingest(Path(args.source), path=path, dry_run=args.dry_run,
                         keep=args.keep)
        for err in summary["errors"]:
            print(f"  note: {err}", file=sys.stderr)
        if not summary["plans"]:
            # Not an error. Most nights nobody ran the agent, and the
            # crawl plus the rotation carry it exactly as before.
            print(f"bank: no plans in {args.source} — the night runs on the "
                  f"crawl and sparks.txt")
            return 0
        stamp = "would bank" if args.dry_run else "banked"
        print(f"bank: {stamp} {summary['sparks']} spark(s) and "
              f"{summary['images']} image(s) from {summary['plans']} plan(s)")
        return 0 if summary["sparks"] else 1

    if args.command == "list":
        rows = scout.list_findings(brand=args.brand, unused_only=args.unused,
                                   path=path)
        if not rows:
            print("nothing banked yet")
        for r in rows:
            mark = "used" if r.get("used_at") else "open"
            images = len(scout.bin_for_finding(r["id"], path=path))
            print(f"[{r['score']:.2f}] {r['brand']:9s} {mark:4s} "
                  f"{images} img  {r['spark']}")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
