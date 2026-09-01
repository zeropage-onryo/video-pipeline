#!/usr/bin/env python3
"""
The repo side of rendering the queue on SUBSCRIPTION credits.

Why this file exists. src/higgsfield.py talks to Higgsfield Cloud, which
bills API credits -- real money, a balance separate from the app plan.
The Higgsfield MCP spends the app subscription's credits instead (~997
already paid for, ~4.8 per seedance clip), but an MCP server is only
reachable from a Claude session, never from the nightly LangGraph. So
the split is:

    Claude session   -- picks the shots, calls the MCP, downloads the mp4
    this file        -- tells it what is waiting, and files what came back

Two subcommands, both safe to run by hand:

    python3 ops/render_queue.py list
    python3 ops/render_queue.py import --concept 128 --shot 1 \
        --file /tmp/clip.mp4 --model seedance1_5 --credits 4.8

WHERE THE CLIP HAS TO LIVE. app/main.py mounts /renders on data/renders/,
so that directory is the only place a media_url can point at -- a file
left in footage/generated/ 404s in the Queue however real it is. import
copies whatever you hand it into data/renders/higgsfield/ (the same
folder src/higgsfield.py writes to) and derives the URL from there.

DELIBERATELY STDLIB-ONLY. It imports src.preprod / src.generative (which
are themselves stdlib) and nothing else, so it runs under any python3 --
the repo venvs are macOS builds and a Claude session's shell is Linux.
No third-party import may be added here without breaking that.

THE SQLITE PRAGMA, and why it is not a hack. Writing to data/pipeline.db
over the desktop bridge's FUSE mount fails at COMMIT with "disk I/O
error" -- the mount cannot do what SQLite's rollback journal needs.
`PRAGMA journal_mode=MEMORY` is per-CONNECTION and, unlike WAL, is not
persisted in the file header, so it changes nothing about the database
his Mac opens and does not touch the plain-file-copy backups. It costs
crash-safety mid-transaction, which for one INSERT of one already-
downloaded clip is the right trade. Applied always: harmless natively.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

_real_connect = sqlite3.connect


def _fuse_safe_connect(*args, **kwargs):
    conn = _real_connect(*args, **kwargs)
    try:
        conn.execute("PRAGMA journal_mode=MEMORY")
    except sqlite3.Error:
        pass          # a read-only open, or a mount that does not need it
    return conn


sqlite3.connect = _fuse_safe_connect          # before src.db is imported

# ruff: noqa: I001 -- these imports MUST come after the patch above, so
# they cannot be hoisted into the sorted block at the top of the file.
from src import accounts, db, generative, preprod       # noqa: E402
from src.shot import Shot                     # noqa: E402


def pending(brand=None, account_id: int | None = None) -> list[dict]:
    """What is waiting on a spend, by exactly the rule app/api.py's
    /queue/pending uses: picked or parked, not archived, a scene, and no
    clip yet. Duplicated deliberately in ONE place only -- if that rule
    changes, this is the line to change with it."""
    out = []
    for concept in preprod.list_concepts(path=db.DB_PATH, account_id=account_id):
        if brand and concept.get("brand") != brand:
            continue
        if not (concept.get("picked") or concept.get("parked")):
            continue
        if concept.get("archived") or not concept.get("is_scene"):
            continue
        for shot in concept.get("shots") or []:
            if shot.get("media_url"):
                continue
            out.append({
                "concept_id": concept["id"],
                "title": concept.get("title") or "",
                "brand": concept.get("brand"),
                "shot_n": shot.get("n", 1),
                "tool": (shot.get("tool") or "").upper(),
                "prompt": (shot.get("prompt") or "").strip(),
                "reference_image": shot.get("reference_image") or "",
                "logline": concept.get("logline") or "",
            })
    return out


RENDER_DIR = REPO / "data" / "renders" / "higgsfield"
RENDERS_ROOT = REPO / "data" / "renders"


def _place(src: Path) -> Path:
    """The clip, sitting somewhere /renders can actually serve it.
    Already under data/renders/ -> left alone. Anywhere else -> copied
    (not moved: a Claude session's shell cannot delete, and a half-moved
    render is worse than a duplicate)."""
    src = src.resolve()
    try:
        src.relative_to(RENDERS_ROOT.resolve())
        return src
    except ValueError:
        pass
    RENDER_DIR.mkdir(parents=True, exist_ok=True)
    dest = RENDER_DIR / src.name
    n = 1
    while dest.exists():
        dest = RENDER_DIR / f"{src.stem}-{n}{src.suffix}"
        n += 1
    dest.write_bytes(src.read_bytes())
    return dest


def import_clip(concept_id: int, shot_n, file: str, model: str,
                credits: float | None, prompt: str | None,
                anchored: bool,
                account_id: int | None = None,
) -> dict:
    """File a finished clip: a generations row so genlog, pick_rate and
    the tool scoreboard see the attempt, then the media_url that
    autopilot.build_plan requires before it will emit a post action.

    cost_usd is left NULL on purpose. The clip was paid for out of a
    subscription that was already bought, so a dollar figure here would
    be invented -- the credits spent go in params_json where they are
    honest. Nothing downstream sums cost_usd into money owed.
    """
    path = Path(file)
    if not path.is_absolute():
        path = REPO / path
    if not path.is_file():
        raise SystemExit(f"no such clip: {path}")
    if path.stat().st_size < 1024:
        raise SystemExit(f"clip is {path.stat().st_size} bytes -- that is not a video")

    concept = preprod.get_concept(concept_id, path=db.DB_PATH, account_id=account_id)
    if concept is None:
        raise SystemExit(f"no concept {concept_id}")
    shot = next((s for s in concept.get("shots") or []
                 if s.get("n") == shot_n), None)
    if shot is None:
        raise SystemExit(f"concept {concept_id} has no shot {shot_n}")

    text = (prompt or shot.get("prompt") or "").strip()
    if not text:
        raise SystemExit("no prompt to log this attempt against")

    path = _place(path)
    generative.init(path=db.DB_PATH)
    shot_row_id = generative.add_shot(
        Shot(subject=text[:100], action="as prompted"),
        notes=f"rendered via the Higgsfield MCP on subscription credits "
              f"(concept {concept_id} shot {shot_n})",
        path=db.DB_PATH, account_id=account_id)
    generation_id = generative.record_generation(
        shot_row_id, "higgsfield", text,
        params={"model": model, "source": "mcp-subscription",
                "credits": credits, "concept_id": concept_id,
                "shot_n": shot_n, "prompt_image": bool(anchored)},
        output_path=str(path),
        cost_usd=None,
        notes="subscription credits, not API credits",
        path=db.DB_PATH, account_id=account_id)

    media_url = "/renders/" + str(path.relative_to(RENDERS_ROOT.resolve())).replace("\\", "/")
    preprod.set_shot_media_url(concept_id, shot_n, media_url, path=db.DB_PATH, account_id=account_id)
    return {"ok": True, "generation_id": generation_id,
            "media_url": media_url, "path": str(path)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="what is waiting on a spend, as JSON")
    p_list.add_argument("--brand")

    p_imp = sub.add_parser("import", help="file a finished clip")
    p_imp.add_argument("--concept", type=int, required=True)
    p_imp.add_argument("--shot", type=int, default=1)
    p_imp.add_argument("--file", required=True)
    p_imp.add_argument("--model", required=True)
    p_imp.add_argument("--credits", type=float)
    p_imp.add_argument("--prompt")
    p_imp.add_argument("--anchored", action="store_true",
                       help="the render was anchored on the keyframe")

    ap.add_argument(
        "--account", default=None,
        help="account slug to act as (default: the oldest on the database)")

    args = ap.parse_args()
    # A Claude session drives this by hand; there is no cookie behind it.
    # Resolving here rather than defaulting to None deeper down, because
    # after the tenancy backfill nobody owns nothing -- `list` would print
    # an empty queue and look like there was no work waiting.
    account_id = accounts.resolve_account(args.account)
    if args.cmd == "list":
        print(json.dumps(pending(args.brand, account_id=account_id), indent=2))
    else:
        print(json.dumps(import_clip(args.concept, args.shot, args.file,
                                     args.model, args.credits, args.prompt,
                                     args.anchored, account_id=account_id), indent=2))


if __name__ == "__main__":
    main()
