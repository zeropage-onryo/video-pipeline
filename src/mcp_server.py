"""
The MCP surface: this pipeline's idea board, reachable from somewhere
other than the machine it runs on.

WHY AN ADAPTER AND NOT A STORE. Every idea this project has already
lives in data/pipeline.db -- `shoot_concepts` is the board, and
`scout_findings` is the bank of directions a night can run from. A
second store synced against those would be the same mistake
`asset_shelf` exists to fix: two places holding one fact, drifting
apart the first time a write path forgets the other. So nothing here
holds state. Every function below is a thin call into `preprod` or
`scout`, and the database stays the single source of truth.

WHAT IT IS FOR. The decisions this pipeline needs from a human are
cheap, frequent and small -- read the board, pick one, kill three, hand
the night a direction -- and every one of them was trapped behind being
sat at the machine. Generating was never the bottleneck. Deciding was.
So the deciding is what this exposes.

WHAT IT DELIBERATELY WILL NOT DO. Nothing here spends money. No render,
no keyframe, no enhance, no Runway, no Nano, no model call of any kind.
Approving in the Queue stays the ONE spend gate: on the machine, in
front of somebody who can see what they are about to buy. That single
gate is load-bearing (see "One idea box, one board, one spend gate" in
CLAUDE.md), and a second door onto it from a phone is precisely how it
stops being one. The test asserts this by walking this module for the
connectors rather than trusting this paragraph -- a docstring cannot
fail CI.

TWO LAYERS, ON PURPOSE. The functions here are plain Python against a
database URL; the FastMCP wrapper around them is built lazily in
`build_server`. So the whole tool surface stays testable with no `mcp`
package installed, and a machine that never serves MCP does not grow an
import-time dependency on one -- the same degrade-don't-break rule the
rest of src/ follows.
"""
from __future__ import annotations

import contextvars
import os
import sys
from pathlib import Path
from typing import Any, Literal, Optional

from . import accounts, autonomy, db, imagesearch, preprod, refbin, scout

ARCHIVE_DESCRIPTION = (
    "Take a concept off the board. Hides it; never deletes. `reason` is WHY "
    "-- the only record this pipeline keeps of why anything was rejected, "
    "and what avoid_guidance learns from. One of: "
    f"{' · '.join(preprod.ARCHIVE_REASONS)}. Never required: an archive with "
    "no word still archives."
)

# The board's filters. "open" is deliberately first and is the default:
# it is the only one that answers "what is waiting on me".
STATUSES = ("open", "picked", "archived", "parked", "shot", "all")

# What a spark typed by a human scores. `scout.next_spark` serves the
# highest-scoring unused finding at or above SCORE_FLOOR (0.55), so a
# hand-banked spark has to outrank a crawled one -- otherwise the night
# would keep preferring its own research to an explicit instruction,
# which is the opposite of why anybody would type one.
HUMAN_SPARK_SCORE = 1.0

# A list call returns cards, not concepts. A scene prompt is ~1200
# characters and a board read is a dozen of them, so returning whole
# rows turns "what's on the board" into 15k characters of camera
# direction nobody asked for. `get_idea` returns the whole thing and is
# one call away.
LIST_LIMIT = 25
SEARCH_SCAN = 500

# --- what the directory publishes (2026-10-07) ------------------------------
#
# One constant per registered tool, in `build_server`'s order. These are
# what a STRANGER reads -- a creator who installed the connector from the
# directory and has none of this repo's vocabulary -- so they say what the
# tool does and when to call it, in the product's words (board, idea,
# scene, reference image, spark, the studio), and nothing about how it is
# run here. A test pins every registered tool to its row and screens the
# words. ARCHIVE_DESCRIPTION above is the first of these and keeps its name.

DEFAULT_BRAND = "zeropage"
Brand = Literal[preprod.BRANDS]
Status = Literal[STATUSES]
Lane = Literal[scout.KNOWN_LANES]

INSTRUCTIONS = (
    "Your studio's idea board. Read the concepts on it, pick the ones worth "
    "making, archive the rest with a reason, capture new ideas, and see "
    "which reference images sit behind a direction. Nothing here renders: a "
    "pick quotes what the stills would cost and the render is approved in the "
    "studio, where the price is shown."
)

TITLES = {
    "board": "List the idea board",
    "idea": "Read one idea in full",
    "search": "Search ideas",
    "capture": "Capture a new idea",
    "pick": "Pick an idea (or unpick)",
    "shoot": "Mark an idea as made",
    "archive": "Archive an idea (reversible)",
    "add_spark": "Bank a direction",
    "tonight": "Next banked direction",
    "sparks": "List banked directions",
    "images": "Reference images behind a direction",
    "reference": "Bank a reference image",
    "imagine_reference": "Render a reference still (spends credits)",
    "images_for": "Find reference images",
    "stats": "Board statistics",
    "research": "Run a research pass (spends)",
    "generate": "Write a scene from a direction (spends)",
    "job": "Check a background job",
    "elements": "List your elements (reference photos)",
    "write_scene": "Save a scene prompt onto an idea",
    "quote": "Price the keyframes and the clip",
    "approve": "Approve a priced render (spends credits)",
}

_CAP = f"Returns at most `limit` rows (default {LIST_LIMIT}, maximum 100)"

DESCRIPTIONS = {
    "board": (
        "List the ideas on your board as short cards (id, title, one-line "
        "summary, status, how many reference images it carries), newest "
        "first. `status` filters: open (the default: nothing decided yet, "
        "which includes parked), picked, archived, parked, shot, or all. "
        f"{_CAP}; `truncated` is true when more matched, so narrow with "
        "`status` or use `search`. Read-only."
    ),
    "idea": (
        "One idea in full by its id: title, hook, logline, the written scene "
        "prompt(s) with their reference images, and any warnings or scores "
        "recorded on it. Use after `board` or `search` to read a card you want "
        "to decide on. Read-only."
    ),
    "search": (
        "Find ideas on your board whose title, hook, logline, direction or "
        f"scene prompt contains the text (case-insensitive substring). {_CAP}; "
        "`truncated` is true when more matched, so use a longer phrase. "
        "Read-only."
    ),
    "capture": (
        "Add a new idea to your board with a title and optional hook, logline "
        "and the direction it came from. Saves the idea only -- no scene is "
        "written and nothing is spent; write its scene afterwards with "
        "`write_scene`, or in the studio. Returns the new card."
    ),
    "pick": (
        "Mark an idea as worth making (`picked: false` undoes it). Spends "
        "nothing. The reply quotes the stills a rendered version would need "
        "(`keyframes`: count and credits); drawing them and rendering the clip "
        "are approved in the studio, where the price is shown."
    ),
    "shoot": (
        "Record that an idea was actually made, by any means (`shot: false` "
        "undoes it). A label for your statistics; spends nothing."
    ),
    "archive": ARCHIVE_DESCRIPTION,
    "add_spark": (
        "Bank a one-line direction (a spark) for a future scene, with an "
        "optional rationale and evidence. Returns the bank row; a direction "
        "already banked is reported as `duplicate_of`, not refused."
    ),
    "tonight": (
        "The highest-scoring unused direction in the bank -- the one the next "
        "scene would be written from -- or a note when nothing qualifies. "
        "Read-only."
    ),
    "sparks": (
        "List banked directions, highest-scoring first; `unused_only` (default "
        "true) hides ones a scene was already written from. Returns at most "
        "`limit` rows (default 20, maximum 100). Read-only."
    ),
    "images": (
        "The reference images banked behind one direction (by its `finding_id` "
        "from `sparks` or `tonight`), each with the page it came from. Errors "
        "with `no finding N` for an unknown id. Read-only."
    ),
    "reference": (
        "Bank one reference image behind a direction. Pass a `candidate_id` "
        "from `images_for`; the image and its source page come from that "
        "search result, so an id that no search issued is refused. "
        "(`image_url` + `source_url` is the alternative for a photo a person "
        "supplied; `source_url` must resolve.) The image is fetched by the "
        "server and stored; nothing is billed."
    ),
    "imagine_reference": (
        "Render ONE reference still for a direction from a hook frame (what is "
        "on screen in frame one, and its light) and bank it behind the "
        "direction. SPENDS CREDITS from your balance on the call, the price "
        "of one still; the reply says what was charged, or a note when the "
        "balance or the daily cap refuses it (do not retry a refusal)."
    ),
    "images_for": (
        "Search the web's open image sources for reference frames matching a "
        "description of the light and surfaces wanted (e.g. \"cold fluorescent "
        "on wet tile, overhead\"). Returns up to `limit` (default 6, maximum 12) "
        "candidates as ids with what each shows and its credit -- never URLs. "
        "Pass an id to `reference` to bank it. Read-only."
    ),
    "stats": (
        "Your board in numbers: pick rate and shoot rate (ideas picked and "
        "ideas made, against ideas written), the count in each status, and how "
        "many are waiting on you. Read-only."
    ),
    "research": (
        "Run one research pass: crawl the configured lanes, distil what is "
        "landing into scored one-line directions, bank them with the reference "
        "images behind them. Spends model credit. Starts a background job; poll "
        "it with `job`."
    ),
    "generate": (
        "Write a scene from a direction: ground it on the reference images "
        "banked behind that direction, write the scene prompt, score it, and "
        "park it on your board for a decision. Spends model credit; never "
        "renders. Pass `finding_id` from `sparks` or `tonight`, or the spark "
        "text. Starts a background job; poll it with `job`."
    ),
    "job": (
        "The status of a background job by id -- one this connector started "
        "(`research`, `generate`) or one you started in the studio: status, "
        "label, progress detail and the result or error when it finished. "
        "Jobs live in memory, so a server restart forgets them. Read-only."
    ),
    "elements": (
        "Your elements: the characters, props and places whose photos you "
        "uploaded in the studio, each with its photo refs. A scene is "
        "rendered against those photographs, so `write_scene` takes refs "
        "from this list and nothing else. Read-only."
    ),
    "write_scene": (
        "Save a scene prompt you wrote onto one of your ideas, so it can be "
        "priced and rendered. `prompt` is the full scene (the studio's shape: "
        "an opening line naming the attached photos, a style block, timed "
        "beats like (0-4s) each one shot, diegetic sound, an avoid list); "
        "`seconds` is its total length (4-30); `refs` are photo refs from "
        "`elements` -- the first one anchors the render, and at least one is "
        "required. Timed beats become the shots. Replaces any scene the idea "
        "already carried. Spends nothing."
    ),
    "quote": (
        "What rendering one of your ideas would cost, in credits: the "
        "keyframe stills still to draw and the clip (one render per timed "
        "shot), with a signed token per render that `approve` takes, plus "
        "your balance. Optional `provider`, `model`, `duration` (whole-scene "
        "only) and `frame` pick the renderer; the defaults are the studio's. "
        "Read-only; a quote is valid for one hour."
    ),
    "approve": (
        "SPENDS CREDITS. Approve a quoted render for one of your picked "
        "ideas: `what` is \"keyframes\" (draw the stills) or \"clip\" (render "
        "the shots); for a clip pass the `tokens` from `quote` and the same "
        "renderer choice. Credit is held before anything is submitted and "
        "released if the render fails. Starts a background job; poll it with "
        "`job`. Refused when the idea is not picked, has no reference photos, "
        "the quote is stale, or the balance is short."
    ),
}

# What each tool DOES, for Claude's permission model: `read` (no change),
# `destructive` (cannot be undone -- here, spends money or crawls and
# writes), `idempotent` (the same call again changes nothing more),
# `open_world` (reaches beyond this server: the web, a provider).
HINTS = {
    "board":             {"read": True,  "destructive": False, "idempotent": True,  "open_world": False},
    "idea":              {"read": True,  "destructive": False, "idempotent": True,  "open_world": False},
    "search":            {"read": True,  "destructive": False, "idempotent": True,  "open_world": False},
    "capture":           {"read": False, "destructive": False, "idempotent": False, "open_world": False},
    "pick":              {"read": False, "destructive": False, "idempotent": True,  "open_world": False},
    "shoot":             {"read": False, "destructive": False, "idempotent": True,  "open_world": False},
    "archive":           {"read": False, "destructive": False, "idempotent": True,  "open_world": False},
    "add_spark":         {"read": False, "destructive": False, "idempotent": False, "open_world": False},
    "tonight":           {"read": True,  "destructive": False, "idempotent": True,  "open_world": False},
    "sparks":            {"read": True,  "destructive": False, "idempotent": True,  "open_world": False},
    "images":            {"read": True,  "destructive": False, "idempotent": True,  "open_world": False},
    "reference":         {"read": False, "destructive": False, "idempotent": True,  "open_world": True},
    "imagine_reference": {"read": False, "destructive": True,  "idempotent": False, "open_world": True},
    "images_for":        {"read": True,  "destructive": False, "idempotent": True,  "open_world": True},
    "stats":             {"read": True,  "destructive": False, "idempotent": True,  "open_world": False},
    "research":          {"read": False, "destructive": True,  "idempotent": False, "open_world": True},
    "generate":          {"read": False, "destructive": True,  "idempotent": False, "open_world": True},
    "job":               {"read": True,  "destructive": False, "idempotent": True,  "open_world": False},
    "elements":          {"read": True,  "destructive": False, "idempotent": True,  "open_world": False},
    "write_scene":       {"read": False, "destructive": False, "idempotent": True,  "open_world": False},
    "quote":             {"read": True,  "destructive": False, "idempotent": True,  "open_world": False},
    "approve":           {"read": False, "destructive": True,  "idempotent": False, "open_world": True},
}

# THE LISTED SET (2026-10-07, Mike's call). What a signed-in stranger is
# offered through the HTTP mount: read the board and decide on it, and
# (once built) quote and approve a render. Claude does the ideation in the
# chat, so nothing here calls a paid model, and the spark bank -- a SHARED
# table (db.SHARED_TABLES) -- stays on the operator's own server, where one
# person's directions are not listed to another. `build_server(listed=True)`
# registers exactly these; the static-token door and stdio keep everything.
LISTED_TOOLS = ("board", "idea", "search", "capture", "pick", "shoot",
                "archive", "stats", "elements", "write_scene", "quote",
                "approve", "job")

# Words a directory user does not have. The test screens every published
# description and title for them (case-insensitive).
INTERNAL_WORDS = (
    "nightly", "the night", "Mike", "Michael", "Higgsfield", "Runway", "venv",
    "/ui", "Dev Studio", "LangGraph", "Nano", "Midjourney", "Gemini",
    "antihero", "zeropage", "on the machine", "src.", "hold_queue",
)


class Refused(Exception):
    """A deliberate no, not a failure.

    Separate from ValueError because the two mean different things to a
    caller -- a ValueError says "you asked wrongly, ask again", a
    Refused says "this surface will not do that at all, stop asking" --
    and separate from a bare RuntimeError because the translation layer
    in build_server has to be able to tell a refusal it should relay
    from a crash it must not dress up as one.
    """


# --- shaping ---------------------------------------------------------------

def _status_of(concept: dict) -> str:
    """The one word a card carries. Ordered by which decision is most
    recent rather than by the columns' order: a concept that was picked
    and then shot reads as shot, and a picked concept that the night had
    already parked reads as picked, because picking is the later and
    more human of the two."""
    if concept.get("shot_done"):
        return "shot"
    if concept.get("archived"):
        return "archived"
    if concept.get("picked"):
        return "picked"
    if concept.get("parked"):
        return "parked"
    return "open"


def _matches(concept: dict, status: str) -> bool:
    if status == "all":
        return True
    if status == "open":
        # Everything nothing has been said about yet, either way. A
        # PARKED scene is open on purpose: the night got it as far as it
        # could without spending, and what remains is somebody's call.
        return not concept.get("picked") and not concept.get("archived")
    return _status_of(concept) == status


def _card(concept: dict) -> dict[str, Any]:
    """One row as the board draws it: enough to decide on, not enough to
    read the scene."""
    shot = (concept.get("shots") or [{}])[0]
    return {
        "id": concept["id"],
        "brand": concept["brand"],
        "title": concept["title"],
        "summary": preprod.concept_summary(
            concept.get("card_line") or "",
            concept.get("logline") or "",
            shot.get("prompt") or "",
        ),
        "status": _status_of(concept),
        "is_scene": concept.get("is_scene", False),
        "spark": concept.get("spark") or "",
        "refs": len(concept.get("refs") or []),
        "warnings": concept.get("warnings") or [],
        "created_at": concept["created_at"],
    }


# What a null `judge_overall` means, said on the card rather than left
# to be inferred. Two doors write concepts and only one of them scores
# anything -- and neither writes THAT column.
ORIGIN_NOTE = {
    "graph": "ran through the LangGraph: `gate` is its verdict",
    "studio": ("written by Studio's Create, which stops on the board by design "
               "(2026-08-29) -- never scored; a null judge means unscored, not "
               "scored badly. Pick it to put it in front of the Queue"),
    "capture": "captured as an idea only -- no scene prompt yet, nothing to score",
}


def _gate(concept: dict, dsn, account_id: Optional[int]) -> dict[str, Any]:
    """The verdict the graph actually reached on this concept, read from
    where the graph actually writes it.

    `judge_overall` on the row is the Dev Studio's TASTE judge -- a
    manual per-click tool that no automated path has ever called -- so
    reading it as "the graph scored this" is wrong in both directions:
    #167 read 7.0 because somebody clicked, and every graph row reads
    null however it scored. The prompt gate logs to `prompt_scores` by
    run_id and the run's outcome is the hold row's reason, and until
    2026-09-03 neither reached this surface, so an agent asked why #173
    was held (5/10, "too many sequential character actions") had
    nothing to say. Origin is derived from the hold row: a concept the
    graph wrote always has one (`_park` runs on every terminal edge),
    and one it did not write never does.
    """
    hold = autonomy.hold_for_concept(concept["id"], dsn=dsn, account_id=account_id)
    if hold is None:
        origin = "capture" if not concept.get("shots") else "studio"
        return {"origin": origin, "note": ORIGIN_NOTE[origin], "gate": None}
    run_id = (hold.get("payload") or {}).get("run_id") if isinstance(
        hold.get("payload"), dict) else None
    scores = autonomy.prompt_scores_for_run(run_id, dsn=dsn)
    latest = scores[-1] if scores else None
    return {
        "origin": "graph",
        "note": ORIGIN_NOTE["graph"],
        "gate": {
            "hold_id": hold["id"],
            "status": hold.get("status") or "held",
            "outcome": hold.get("reason") or "",
            "run_id": run_id or "",
            "score": latest["score"] if latest else None,
            "passed": latest["passed"] if latest else None,
            "reason": (latest.get("reason") or "") if latest else "",
            "scores": [{"score": x["score"], "passed": x["passed"],
                        "reason": x.get("reason") or ""} for x in scores],
        },
    }


def _full(concept: dict, dsn=None, account_id: Optional[int] = None) -> dict[str, Any]:
    """The whole concept, prompts included. Shots are passed through
    rather than reshaped -- `shots_json` is the flexible column every
    other surface reads, and a second shape maintained here is a second
    thing to forget to update. `judge_overall`/`judge_reason` are the
    Dev Studio's manual taste judge and stay under that name; the
    graph's own verdict is `gate` (see _gate)."""
    out = _card(concept)
    out.update(
        {
            "hook": concept.get("hook") or "",
            "card_line": concept.get("card_line") or "",
            "logline": concept.get("logline") or "",
            "duration": concept.get("duration") or "",
            "format": concept.get("format") or "",
            "locations": [loc["name"] for loc in concept.get("locations") or []],
            "park_reason": concept.get("park_reason") or "",
            "judge_overall": concept.get("judge_overall"),
            "judge_reason": concept.get("judge_reason") or "",
            "notes": concept.get("notes") or "",
            "shots": concept.get("shots") or [],
        }
    )
    out.update(_gate(concept, dsn, account_id))
    return out


def _check(value: str, allowed, label: str) -> str:
    if value not in allowed:
        raise ValueError(f"{label} must be one of {list(allowed)}, got {value!r}")
    return value


def _truncation(rows: list, limit: int, advice: str) -> dict[str, Any]:
    """The cap, said out loud (2026-10-07). A list that stops at `limit`
    with no word looks complete, and an agent that reads 25 cards as the
    whole board decides on a third of it. The scan reads ONE row past the
    cap so `truncated` is a fact, not a guess."""
    if len(rows) <= limit:
        return {"truncated": False}
    return {"truncated": True,
            "note": f"more than {limit} matched; {advice}"}


# --- the board -------------------------------------------------------------

CALLER_ACCOUNT: contextvars.ContextVar[Optional[int]] = contextvars.ContextVar(
    "zeropage_mcp_caller_account", default=None)
"""The account a SIGNED-IN caller is acting as, for the length of one
HTTP request. Set by app/mcp_mount.py's guard once a Supabase access
token has been verified, and unset for every other caller.

It lives here, in src/, rather than in the app layer for the reason the
whole injection pattern exists: `src/` never imports `app/`, and
`_account` is the one place that decides whose board a tool reads, so
the value has to be readable from here. Verified empirically rather than
assumed -- the streamable-HTTP transport in stateless mode runs a tool
body in a task that inherits the request's context, so a value set in
the ASGI wrapper reaches the tool. A stateful session would not
guarantee that, which is one more reason the mount is stateless."""


def _account(account_id: Optional[int], dsn) -> Optional[int]:
    """Which account an MCP call acts as.

    Three callers, in order of precedence:

    - An EXPLICIT `account_id`, which is how the Guide opens a server
      per signed-in request.
    - A caller the transport authenticated (`CALLER_ACCOUNT`) -- a person
      who signed in through the OAuth door. Their own account, never the
      operator's: the bootstrap fallback below is exactly the bug that
      would hand a stranger Mike's board, so it must not be reachable
      once somebody has identified themselves.
    - Nobody named, which is the static-token door: an agent on the
      operator's own machine holding `ZEROPAGE_MCP_TOKEN`, or a CLI. It
      acts as the bootstrap account -- the same call the CLIs make, for
      the same reason. After the tenancy backfill, acting as nobody means
      reading an empty database and reporting it as an empty board.
    """
    if account_id is not None:
        return account_id
    caller = CALLER_ACCOUNT.get()
    if caller is not None:
        return caller
    return accounts.resolve_account(dsn=dsn)


def list_ideas(
    brand: Optional[str] = None,
    status: str = "open",
    limit: int = LIST_LIMIT,
    dsn: Optional[str] = None,
    account_id: Optional[int] = None,
) -> dict[str, Any]:
    """The board. Newest first, because the ones just generated are the
    ones being decided about."""
    account_id = _account(account_id, dsn)
    _check(status, STATUSES, "status")
    if brand:
        _check(brand, preprod.BRANDS, "brand")
    limit = max(1, min(int(limit), 100))

    cards = []
    for concept in preprod.list_concepts(limit=SEARCH_SCAN, dsn=dsn, account_id=account_id):
        if brand and concept["brand"] != brand:
            continue
        if not _matches(concept, status):
            continue
        cards.append(_card(concept))
        if len(cards) > limit:
            break
    return {"brand": brand or "all", "status": status,
            "count": min(len(cards), limit), "ideas": cards[:limit],
            **_truncation(cards, limit, "narrow with `status` or use `search`")}


def get_idea(idea_id: int, dsn: Optional[str] = None, account_id: Optional[int] = None) -> dict[str, Any]:
    """One concept in full, including the scene prompt."""
    account_id = _account(account_id, dsn)
    concept = preprod.get_concept(int(idea_id), dsn=dsn, account_id=account_id)
    if concept is None:
        raise ValueError(f"no idea {idea_id}")
    return _full(concept, dsn=dsn, account_id=account_id)


def search_ideas(
    query: str,
    brand: Optional[str] = None,
    limit: int = LIST_LIMIT,
    dsn: Optional[str] = None,
    account_id: Optional[int] = None,
) -> dict[str, Any]:
    """Substring search across title, hook, logline, spark and the scene
    prompt itself.

    Deliberately not SQL LIKE and deliberately not embeddings: the
    prompt lives inside a JSON column, the board is a few hundred rows,
    and a semantic search would make a free question cost a model call.
    The RAG library is where similarity search belongs; this is a
    find-the-one-I-mean.
    """
    account_id = _account(account_id, dsn)
    needle = (query or "").strip().lower()
    if not needle:
        raise ValueError("query is empty")
    if brand:
        _check(brand, preprod.BRANDS, "brand")
    limit = max(1, min(int(limit), 100))

    hits = []
    for concept in preprod.list_concepts(limit=SEARCH_SCAN, dsn=dsn, account_id=account_id):
        if brand and concept["brand"] != brand:
            continue
        hay = " ".join(
            [
                concept.get("title") or "",
                concept.get("hook") or "",
                concept.get("logline") or "",
                concept.get("spark") or "",
                *[s.get("prompt") or "" for s in concept.get("shots") or []],
            ]
        ).lower()
        if needle in hay:
            hits.append(_card(concept))
        if len(hits) > limit:
            break
    return {"query": query, "count": min(len(hits), limit), "ideas": hits[:limit],
            **_truncation(hits, limit, "use a longer phrase, or raise `limit` up to 100")}


def capture_idea(
    brand: str,
    title: str,
    hook: str = "",
    logline: str = "",
    spark: str = "",
    dsn: Optional[str] = None,
    account_id: Optional[int] = None,
) -> dict[str, Any]:
    """Put an idea on the board from wherever you are.

    Saved through `save_concept_ideas`, so it lands with `shots = []` --
    an IDEA, not a scene. That is not a shortcoming to fix later: a row
    with no shots is excluded from `pick_rate` (which counts one-shot
    concepts only), so capturing on a phone cannot quietly move the
    metric that measures generation quality. Writing its scene is a
    separate, model-costing step on the machine.
    """
    account_id = _account(account_id, dsn)
    _check(brand, preprod.BRANDS, "brand")
    title = (title or "").strip()
    if not title:
        raise ValueError("title is required")

    idea = {"title": title, "hook": hook or "", "logline": logline or ""}
    (idea_id,) = preprod.save_concept_ideas(
        [idea], brand=brand, spark=(spark or "").strip() or None, dsn=dsn,
        account_id=account_id,
    )
    card = _card(preprod.get_concept(idea_id, dsn=dsn, account_id=account_id))
    # `write_scene` is on BOTH servers; `generate` is not on the listed one,
    # so pointing a directory user at it named a tool they do not have
    # (found on the 2026-10-08 second-account walk)
    card["next"] = (
        "Idea only -- no scene prompt yet. Write its scene with `write_scene` "
        "(photo refs from `elements`), or in the studio (Create, with the idea "
        "as the brief)."
    )
    return card


def pick_idea(idea_id: int, picked: bool = True,
              dsn: Optional[str] = None,
              account_id: Optional[int] = None,
) -> dict[str, Any]:
    """Mark a concept worth rendering -- the label `pick_rate` reads.

    SPENDS NOTHING AGAIN (2026-09-29, Mike's call). From 2026-09-08 this
    drew the scene's still on pick; a still now costs credits, and every
    spend of credits sits behind a priced approve a person presses. So the
    pick records the choice and says what drawing would cost
    (`keyframes`: stills and credits, from scene_chain.stills_to_draw);
    the draw is the "Draw keyframes" button on the Queue card
    (`POST /api/concepts/{id}/keyframes`). The read/decide tools are back
    to never spending.
    """
    from . import scene_chain
    account_id = _account(account_id, dsn)
    preprod.set_picked(int(idea_id), picked=picked, dsn=dsn, account_id=account_id)
    concept = preprod.get_concept(int(idea_id), dsn=dsn, account_id=account_id)
    card = _card(concept)
    if picked:
        quote = scene_chain.keyframe_quote(concept)
        if quote:
            card["keyframes"] = {
                "stills": quote["stills"], "credits": quote["credits"],
                "note": "not drawn -- approve \"Draw keyframes\" on the "
                        "Queue card in the studio to spend the credits"}
    return card


def shoot_idea(idea_id: int, shot: bool = True,
               dsn: Optional[str] = None,
               account_id: Optional[int] = None,
) -> dict[str, Any]:
    """Record that this one actually got made -- by ANY means.

    `shot` means a finished piece exists: the render lane, Higgsfield,
    Mike's own studio, a camera. It is deliberately NOT "a render came
    back" and NOT bound to the Queue's approve button -- approve
    precedes the output (it authorises a spend, and failed and discarded
    renders would all count), and studio work never passes through the
    Queue at all. Every piece so far was produced by hand, and this is
    the only way the system can see that work: `shoot_rate` read 0.0%
    across 52 concepts while things shipped. Never spends.
    """
    account_id = _account(account_id, dsn)
    preprod.mark_shot(int(idea_id), shot=shot, dsn=dsn, account_id=account_id)
    return _card(preprod.get_concept(int(idea_id), dsn=dsn, account_id=account_id))


def archive_idea(idea_id: int, archived: bool = True, reason: str = "",
                 dsn: Optional[str] = None,
                 account_id: Optional[int] = None,
) -> dict[str, Any]:
    """Take a concept off the board. Hides, never deletes -- an unpicked
    row is the only negative signal this system collects, and it stays
    in the ungraded pool until it has taught the RAG shelves something.

    `reason` is WHY (2026-09-01), the same vocabulary the Grade tab's
    Pass buttons write. archived_at records only THAT a concept was
    passed over; the reason is the part that can ever reach
    avoid_guidance. Never a gate -- an archive that fails because nobody
    picked a word is an archive that does not happen, and the row sits on
    the board forever.
    """
    account_id = _account(account_id, dsn)
    reason = (reason or "").strip()
    preprod.set_archived(int(idea_id), archived=archived, dsn=dsn,
                         account_id=account_id, reason=reason)
    card = _card(preprod.get_concept(int(idea_id), dsn=dsn, account_id=account_id))
    if archived and reason and reason not in preprod.ARCHIVE_REASONS:
        # Recorded as given -- never a gate -- but said back, because the
        # tally counts WORDS: "boring" and "other" (the vocabulary the
        # old docstring named) are buckets of one beside "weak concept",
        # and a bucket of one teaches nothing. The live tally on
        # 2026-09-03 held 1 boring and 7 other for exactly this reason.
        card["reason_note"] = (
            f"recorded {reason!r}; the counted vocabulary is "
            f"{', '.join(preprod.ARCHIVE_REASONS)} -- use one next time so "
            "the tally can move")
    return card


# --- Claude writes the scene, the studio renders it (2026-10-07) ------------
#
# Mike's call: the listed connector uses Claude for the ideation -- no
# Gemini Create, no research pass -- and the MCP for the render. So a
# scene prompt written in the chat is SAVED here, against the person's
# own element photographs (the reference gate's rule, unchanged), priced
# by the same pricing the Queue card shows, and approved through the same
# bodies the Queue's buttons post to.

MIN_SCENE_WORDS = 15
WhatToApprove = Literal["keyframes", "clip"]


def list_elements(dsn: Optional[str] = None,
                  account_id: Optional[int] = None) -> dict[str, Any]:
    """The account's characters, props and places with their photo refs --
    the only strings `write_scene` accepts as references."""
    from . import asset_shelf
    account_id = _account(account_id, dsn)
    items = asset_shelf.catalogue(dsn, account_id=account_id)
    out = [{"kind": item["category"], "name": item["name"],
            "description": (item.get("text") or "")[:300],
            "photos": [{"ref": asset_shelf.storable_ref(url), "label": _photo_label(url)}
                       for url in item.get("photos") or []]}
           for item in items]
    return {"count": len(out), "elements": out,
            "note": ("" if out else
                     "no elements yet -- upload photos of your characters, "
                     "products or places in the studio (Elements) first; a scene "
                     "renders only against photographs you attached")}


def _photo_label(url: str) -> str:
    from . import asset_shelf
    parsed = asset_shelf.parse_ref(url) or {}
    return parsed.get("filename") or url.rsplit("/", 1)[-1]


def _allowed_refs(dsn, account_id) -> dict[str, str]:
    """storable ref -> the catalogue's own URL string, for every photo the
    account owns. The gate on `write_scene`: a ref is accepted only when
    `elements` could have issued it, which refuses a typed URL, another
    account's photo and a guess alike -- the candidate_id rule."""
    from . import asset_shelf
    allowed: dict[str, str] = {}
    for item in asset_shelf.catalogue(dsn, account_id=account_id):
        for url in item.get("photos") or []:
            allowed[asset_shelf.storable_ref(url)] = url
            allowed[url] = url
    return allowed


def _check_prompt(prompt: str) -> str:
    text = " ".join((prompt or "").split())
    if len(text.split()) < MIN_SCENE_WORDS:
        raise ValueError(f"the scene prompt is too short ({len(text.split())} words; "
                         f"at least {MIN_SCENE_WORDS}) -- write the whole scene")
    if "{" in text and "}" in text:
        raise ValueError("the scene prompt still carries a {placeholder} -- fill it in")
    return (prompt or "").strip()


def write_scene(idea_id: int, prompt: str, seconds: int = 10, refs=None,
                dsn: Optional[str] = None,
                account_id: Optional[int] = None) -> dict[str, Any]:
    """Save a scene written in the chat onto the caller's idea.

    The shot is the one `shootgen.generate_scene_concept` writes (n=1,
    AI, the fal default tool, the prompt, its seconds, its refs), so
    every reader -- the board, the Queue, pricing, the render loop --
    treats it as any other scene. Timed windows in the prompt become the
    timeline through `timeline.fallback`, the split with no model in it:
    the chat already wrote each window as one shot, and a planner call
    here would spend the money this door exists to save. `source` is
    stamped so `timeline.ensure` reads it as current and never re-plans.

    The reference gate is asked HERE, before the row changes: a scene
    with no photographs never reaches the board from any other door
    either (preprod.reference_gate), and refusing it with the reason is
    kinder than saving a scene the Queue will refuse.
    """
    from . import shootgen, timeline
    account_id = _account(account_id, dsn)
    concept = preprod.get_concept(int(idea_id), dsn=dsn, account_id=account_id)
    if concept is None:
        raise ValueError(f"no idea {idea_id}")
    prompt = _check_prompt(prompt)
    seconds = timeline.scene_seconds(seconds)

    wanted = [str(r).strip() for r in (refs or []) if str(r).strip()]
    allowed = _allowed_refs(dsn, account_id)
    picked: list[str] = []
    for ref in wanted:
        if ref not in allowed:
            raise ValueError(
                f"ref {ref!r} is not one of your elements' photos -- call "
                "`elements` and pass a `ref` from its list (URLs and guesses are refused)")
        stored = allowed[ref]
        if stored not in picked:
            picked.append(stored)

    shot: dict[str, Any] = {
        "n": 1, "type": "BROLL", "source": "AI",
        "tool": shootgen.DEFAULT_SCENE_TOOL,
        "desc": concept.get("logline") or concept.get("title") or "",
        "prompt": prompt, "seconds": seconds, "refs": picked,
        "written_by": "chat",
    }
    ungrounded = preprod.reference_gate({**concept, "shots": [shot]})
    if ungrounded:
        raise ValueError(
            f"{ungrounded} -- attach at least one of your element photos "
            "(`refs` from `elements`); the studio renders only against "
            "photographs you attached")

    windows = timeline.parse_windows(prompt)
    if len(windows) >= 2:
        split = timeline.fallback(prompt, windows, picked)
        total = sum(w["seconds"] for w in windows)
        shot["timeline"] = {"seconds": total, "planner": "split", "brain": None,
                            "source": timeline.source_hash(prompt, picked),
                            "continuity": split["continuity"], "parts": split["parts"]}
        shot["seconds"] = total
    previous = (concept.get("shots") or [{}])[0]
    preprod.update_concept_shots(
        int(idea_id), {"shots": [shot], "duration": f"{shot['seconds']}s"},
        warnings=[], dsn=dsn, account_id=account_id)

    out = get_idea(int(idea_id), dsn=dsn, account_id=account_id)
    out["shots_written"] = len(windows) if len(windows) >= 2 else 1
    out["seconds"] = shot["seconds"]
    if previous.get("media_url") or previous.get("reference_image"):
        out["note"] = ("the idea's earlier scene had renders attached; they stay on "
                       "the Assets wall but are no longer this idea's")
    out["next"] = "`pick` it, then `quote` for the price, then `approve`"
    return out


def quote_render(idea_id: int, provider: Optional[str] = None, model: Optional[str] = None,
                 duration: Optional[int] = None, frame: Optional[str] = None,
                 dsn: Optional[str] = None,
                 account_id: Optional[int] = None) -> dict[str, Any]:
    """The price of rendering an idea, as the Queue card prints it:
    pricing.display for the clip (one render per timed shot, a token per
    render when the server can sign) and scene_chain.keyframe_quote for
    the stills, beside the balance. Nothing is held or spent."""
    from . import accounts, ledger, pricing, scene_chain
    account_id = _account(account_id, dsn)
    concept = preprod.get_concept(int(idea_id), dsn=dsn, account_id=account_id)
    if concept is None:
        raise ValueError(f"no idea {idea_id}")
    shot = (concept.get("shots") or [None])[0]
    if not shot or not (shot.get("prompt") or "").strip():
        raise ValueError(f"idea {idea_id} has no scene prompt yet -- `write_scene` first")
    ungrounded = preprod.reference_gate(concept)
    if ungrounded:
        raise ValueError(f"{ungrounded} -- `write_scene` with `refs` from `elements`")
    try:
        clip = pricing.display(account_id=account_id, shot=shot, shot_id=int(idea_id),
                               provider=provider, model=model, seconds=duration, frame=frame)
    except pricing.PricingRefused as e:
        if e.reason == "nothing_to_render":
            clip = None
        else:
            raise ValueError(str(e)) from e
    except ValueError as e:
        raise ValueError(f"bad renderer choice: {e}") from e
    keyframes = scene_chain.keyframe_quote(concept)
    exempt = bool(account_id is not None and accounts.is_credit_exempt(account_id, dsn=dsn))
    # the ledger's tables exist wherever the app booted; a bare database
    # (stdio on a fresh clone, a test schema) gets them here, idempotently
    ledger.init(dsn)
    balance = None if account_id is None else ledger.available(account_id, dsn=dsn)
    needed = (keyframes or {}).get("credits", 0) + ((clip or {}).get("credits") or 0)
    return {
        "idea_id": int(idea_id),
        "picked": bool(concept.get("picked")),
        "keyframes": keyframes,
        "clip": clip,
        "balance": balance,
        "exempt": exempt,
        "credits_needed": needed,
        "affordable": exempt or balance is None or balance >= needed,
        "note": ("every shot already has a clip" if clip is None else
                 "tokens are valid for one hour; pass them to `approve` with the same "
                 "renderer choice" if (clip or {}).get("signed") else
                 "this server signs no quotes; `approve` takes the renderer choice alone"),
    }


# --- the night's direction -------------------------------------------------

def bank_spark(
    brand: str,
    spark: str,
    rationale: str = "",
    evidence: str = "",
    score: float = HUMAN_SPARK_SCORE,
    dsn: Optional[str] = None,
) -> dict[str, Any]:
    """Hand the nightly run a direction, in the scout's own bank.

    Banked rather than written to prompts/sparks.txt because the bank is
    what `--scout` actually reads, and because a banked finding is
    claimed exactly once (`mark_used`) -- so a spark typed twice by
    accident cannot fire two of the night's 16 runs.

    A colliding spark is reported, not refused. `_spark_key` exists to
    stop the CRAWL rediscovering its own findings; a person retyping a
    direction usually means it.
    """
    _check(brand, scout.BRANDS, "brand")
    spark = " ".join((spark or "").split())
    if not spark:
        raise ValueError("spark is empty")

    key = scout._spark_key(spark)
    clashes = [
        row["id"]
        for row in scout.list_findings(brand=brand, dsn=dsn)
        if row.get("spark_key") == key
    ]
    finding_id = scout.record(
        brand,
        {"spark": spark, "rationale": rationale, "evidence": evidence,
         "sources": [], "score": float(score)},
        lanes="human",
        dsn=dsn,
    )
    return {"id": finding_id, "brand": brand, "spark": spark,
            "score": float(score), "lanes": "human",
            "duplicate_of": clashes,
            "serves_next": float(score) >= scout.SCORE_FLOOR}


def next_spark(brand: str, dsn: Optional[str] = None) -> dict[str, Any]:
    """What tonight's `--scout` run would take: the highest-scoring
    unused finding at or above the floor. None means it falls back to
    the `prompts/sparks.txt` rotation, which is the healthy degraded
    path, not an error."""
    _check(brand, scout.BRANDS, "brand")
    row = scout.next_spark(brand, dsn=dsn)
    if row is None:
        return {"brand": brand, "spark": None,
                "note": f"nothing unused at or above the {scout.SCORE_FLOOR} "
                        "floor -- tonight falls back to sparks.txt"}
    return {"brand": brand, "id": row["id"], "spark": row["spark"],
            "score": row.get("score"), "rationale": row.get("rationale") or "",
            "evidence": row.get("evidence") or "", "lanes": row.get("lanes") or ""}


def list_sparks(brand: Optional[str] = None, unused_only: bool = True,
                limit: int = 20, dsn: Optional[str] = None) -> dict[str, Any]:
    """The scout's bank, highest-scoring first."""
    if brand:
        _check(brand, scout.BRANDS, "brand")
    rows = scout.list_findings(brand=brand, unused_only=unused_only,
                               limit=max(1, min(int(limit), 100)), dsn=dsn)
    return {
        "brand": brand or "all",
        "unused_only": unused_only,
        "count": len(rows),
        "sparks": [
            {"id": r["id"], "brand": r["brand"], "spark": r["spark"],
             "score": r.get("score"), "lanes": r.get("lanes") or "",
             "used_at": r.get("used_at"),
             "rationale": r.get("rationale") or ""}
            for r in rows
        ],
    }


# --- the numbers -----------------------------------------------------------

def pipeline_stats(dsn: Optional[str] = None, account_id: Optional[int] = None,
                   include_bank: bool = True) -> dict[str, Any]:
    """The two surviving labels plus what is sitting on the board.

    `by_prompt` is dropped on purpose: it is the per-prompt-hash
    breakdown the Dev Studio's Stats tab renders, and a phone asking
    "how are we doing" wants the headline. The Stats tab is where the
    breakdown belongs.

    `include_bank=False` on the listed server: `sparks_unused` counts the
    SHARED spark bank (`scout_findings`, db.SHARED_TABLES), which the
    listed server otherwise keeps away from strangers -- the 2026-10-08
    second-account walk read the operator's 38 off it.
    """
    account_id = _account(account_id, dsn)
    pick = preprod.pick_rate(dsn=dsn, account_id=account_id)
    shoot = preprod.shoot_rate(dsn=dsn, account_id=account_id)
    board = {s: 0 for s in STATUSES if s != "all"}
    for concept in preprod.list_concepts(limit=SEARCH_SCAN, dsn=dsn, account_id=account_id):
        board[_status_of(concept)] += 1
    out = {
        "pick_rate": {k: pick[k] for k in ("generated", "picked", "rate")},
        "shoot_rate": {k: shoot.get(k) for k in ("generated", "shot", "rate")},
        "board": board,
        # `board` counts are exclusive so they sum to the row count.
        # `list_ideas(status="open")` is not exclusive -- a parked scene
        # is still waiting on a person -- so the number it returns is
        # spelled out here rather than left to be derived wrongly.
        "waiting_on_you": board["open"] + board["parked"],
    }
    if include_bank:
        out["sparks_unused"] = len(
            scout.list_findings(unused_only=True, limit=100, dsn=dsn))
    return out


# --- the research bin ------------------------------------------------------

def _reachable(url: str) -> bool:
    """Does this page actually exist? A HEAD, five seconds, fail-open on
    anything that is not a definite 4xx.

    Fail-open because the job here is catching FABRICATION, not policing
    the web: a timeout or a bot-wall is not evidence the page is fake,
    and refusing on one would make the bank hostage to a flaky network.
    A 404 is evidence.
    """
    import requests
    try:
        resp = requests.head(url, timeout=5, allow_redirects=True)
        if resp.status_code == 405:              # HEAD not allowed; try GET
            resp = requests.get(url, timeout=5, stream=True)
        return not (400 <= resp.status_code < 500)
    except Exception:
        return True


def _store_local(path_str: str) -> Optional[str]:
    """A frame off his own disk into the bin, through refbin's own
    normalisation so it is addressed exactly like every other reference
    and resolves through the same reader."""
    try:
        data = Path(path_str).read_bytes()
    except OSError:
        return None
    jpeg = refbin.to_jpeg(data)
    return refbin.save(jpeg) if jpeg else None


def find_images(
    query: str,
    brand: str = "",
    limit: int = 6,
    dsn: Optional[str] = None,
) -> dict[str, Any]:
    """Look for reference images, and hand back ids -- never URLs.

    THE OMITTED FIELD IS THE FEATURE. On 2026-09-02 an agent with no
    image search banked eleven references by writing stock URLs from
    memory; the CDNs served *something* for every guess, so a sunny tree
    was banked as "bark texture" and six of the source pages 404. It was
    not lying, it was recalling -- and no prompt fixes recall.

    So the candidate keeps the URL and the caller only ever holds an
    `id`. There is no address here to invent, and `bank_reference`
    accepts an id that this function issued or nothing at all.
    """
    found = imagesearch.search(query, brand=brand or None,
                               limit=max(1, min(int(limit), 12)), dsn=dsn)
    live = imagesearch.sources()
    return {
        "query": " ".join((query or "").split()),
        "sources": live,
        "count": len(found),
        # "no lane is configured" and "nothing matched" are different
        # problems with the same empty list, and the second one wasted
        # two days when the scout bin was silently unfillable.
        "note": ("" if found else
                 ("no image source is configured — Openverse is off "
                  "(OPENVERSE_LANE=0) and no GOOGLE_CSE_ID / REDDIT_CLIENT_ID / "
                  "UNSPLASH_ACCESS_KEY / PEXELS_API_KEY is set"
                  if not imagesearch.any_web(live)
                  else "nothing matched; try plainer words for the light and "
                       "the surfaces rather than the story")),
        "images": [{"id": c["id"], "shows": c.get("title") or "(no description)",
                    "source": c["source"], "credit": c.get("credit") or ""}
                   for c in found],
    }


def bank_reference(
    finding_id: int,
    image_url: str = "",
    source_url: str = "",
    title: str = "",
    candidate_id: str = "",
    dsn: Optional[str] = None,
) -> dict[str, Any]:
    """Put ONE reference image behind a banked spark.

    The gap this closes: bank_spark hands the nightly run a direction
    but no photographs, and the only thing that ever wrote to the bin
    was the crawl -- so on a night the crawl found no images (or failed
    on DNS, which is what happened 2026-09-01) an agent could give the
    graph an idea and not one frame to render it against.

    THE FETCH HAPPENS HERE, SERVER-SIDE, ON PURPOSE. The caller hands
    over a URL, not bytes: refbin.fetch is what enforces the public-host
    guard, the 8MB cap, the JPEG normalisation and the content-addressed
    /refs/<sha>.jpg name. An agent chose this URL after reading some
    page, which makes it exactly the input those guards exist for --
    passing bytes straight through would put the decision in the
    client's hands and the request on this machine's network.

    `source_url` is REQUIRED, not decoration. These are other people's
    frames held as mood reference, and an unattributed one in front of
    somebody about to spend a render is the wrong affordance --
    spark_images returns it on every tile for the same reason.

    Capped at MAX_BIN_IMAGES per pass, same as the crawl: a bin bigger
    than one generation carries has a tail that can never be used.

    TWO WAYS IN, AND ONLY ONE OF THEM IS FOR AGENTS.

    `candidate_id` redeems something `find_images` served: the URL and
    the attribution come out of the row WE wrote, so neither can be
    invented. That is the path the research agent takes.

    A bare `image_url` is the composer's path -- a photo Michael dragged
    on, where a person vouched for it. Left open for that reason, but it
    now has to survive `_reachable(source_url)`: on 2026-09-02 six of
    eleven agent-banked references cited Unsplash pages that 404, and
    nothing had ever resolved one. A HEAD request would have caught
    every one.
    """
    # strict: a database that could not be asked must not come back as
    # "this spark does not exist" -- the agent's only move on that answer
    # is to give up on the images, which is what happened on 2026-09-07.
    try:
        finding = scout.get_finding(int(finding_id), dsn=dsn, strict=True)
    except scout.Unreadable as e:
        raise Refused(str(e)) from e
    if finding is None:
        raise ValueError(f"no finding {finding_id}")

    local_path = ""
    if candidate_id:
        candidate = imagesearch.get(candidate_id, dsn=dsn)
        if candidate is None:
            # An id nobody issued is what a guess looks like now, and it
            # has to say so rather than falling through to a fetch.
            raise ValueError(
                f"no candidate {candidate_id!r} — ids come from find_images "
                f"and cannot be composed; search again and pick one")
        image_url = candidate["image_url"]
        source_url = candidate["source_url"]
        title = title or candidate.get("title") or ""
        if candidate["source"] == "frames":
            # His own footage never leaves this machine, so there is no
            # URL to fetch and no host to guard -- the "url" is a path.
            local_path, image_url = candidate["image_url"], ""
    elif not (image_url or "").strip():
        raise ValueError("give either a candidate_id from find_images or an "
                         "image_url")

    if not (source_url or "").strip():
        raise ValueError("source_url is required — an unattributed reference "
                         "is the wrong thing to put in front of a spend")
    if not candidate_id and not _reachable(source_url):
        raise ValueError(f"source_url {source_url!r} does not resolve — an "
                         f"attribution nobody can check is worse than none")


    # The fetch-and-bank tail is scout's, shared with the automatic
    # backstop (`scout.illustrate`). Everything above this line is what
    # is specific to an AGENT asking: the id has to have been issued, and
    # the attribution has to resolve.
    result = scout.bank_candidate(
        finding,
        {"image_url": local_path or image_url,
         "source_url": source_url, "title": title,
         "source": "frames" if local_path else "", "lane": "agent"},
        dsn=dsn)
    result.setdefault("finding_id", finding["id"])
    return result


def spark_images(finding_id: int, dsn: Optional[str] = None) -> dict[str, Any]:
    """The reference images the scout downloaded on the pass this spark
    came out of.

    The scout already fetched and normalised these into data/refs during
    its pass, addressed as `/refs/<sha>.jpg` -- the same URL shape a
    composer upload gets, which is why they can ride the existing path
    into a keyframe with no new route. Nothing is downloaded here;
    this reads the bank.

    `source_url` is returned on every tile and is not optional
    decoration: these are other people's frames held as mood reference,
    and an unattributed one in front of somebody about to spend a render
    is the wrong affordance.
    """
    if scout.get_finding(int(finding_id), dsn=dsn) is None:
        raise ValueError(f"no finding {finding_id}")
    rows = scout.bin_for_finding(int(finding_id), dsn=dsn)
    return {
        "finding_id": int(finding_id),
        "count": len(rows),
        "images": [
            {"url": r["url"], "source_url": r.get("source_url") or "",
             "title": r.get("title") or "", "lane": r.get("lane") or "",
             "metric": r.get("metric") or ""}
            for r in rows
        ],
    }


# --- the engine ------------------------------------------------------------
#
# The two tools below are the ones that cost something, and they are the
# reason this module has a posture rather than a flat rule.
#
# Reading and deciding is free, so it is always on. A scout pass spends
# a grounded search plus one digest call; a graph run spends generation,
# the judge, and a Nano keyframe charged in credits. Cents, not
# dollars -- but cents fired by something that is not sitting in front
# of the machine, so they register only under ZEROPAGE_MCP_ENGINE=1,
# the same shape as ZEROPAGE_RENDER and RUNWAY_SPEND_OK.
#
# Runway is what actually costs money, and it stays exactly where it
# was: behind approving in the Queue, on the machine. The graph cannot
# reach it from here by construction -- `generate_render` is a dry stub
# unless ZEROPAGE_RENDER=1, and `run_graph` below REFUSES to run at all
# when that flag is set, because a remote caller must never be the thing
# that trips a live render.

ENGINE_ENV = "ZEROPAGE_MCP_ENGINE"
# Every lane the scout can dispatch -- ITS list, never a copy: this one had
# drifted (still naming `feeds` as a default, missing `pinterest`) and, as
# the tool's default, ran Instagram for every caller. The default is now
# scout.default_lanes(<the caller's account>).
LANES = scout.KNOWN_LANES


def engine_enabled() -> bool:
    return os.environ.get(ENGINE_ENV) == "1"


def _create_gate(account_id: Optional[int], dsn=None) -> None:
    """research and generate spend Gemini money for their caller, so they
    ask the same question Studio's Create does (charge.create_refusal,
    2026-09-29): an account with no plan and no credit balance is Refused
    -- a deliberate no, so an agent stops rather than retrying. The
    operator's key resolves to an exempt account and is never refused."""
    from . import charge
    reason = charge.create_refusal(_account(account_id, dsn), dsn=dsn)
    if reason:
        raise Refused(reason)


def run_research(brand: str, count: int = 4, lanes=None,
                 dsn: Optional[str] = None,
                 account_id: Optional[int] = None) -> dict[str, Any]:
    """One full scout pass: crawl the lanes, digest to scored sparks,
    bank them, and stash the images behind them.

    Returns the banked findings rather than the crawl. The digest step
    exists precisely so raw crawl text never reaches a generator, and
    handing it to an agent instead would just move that mistake one
    layer out.
    """
    _check(brand, scout.BRANDS, "brand")
    _create_gate(account_id, dsn)
    lanes = tuple(lanes) if lanes else scout.default_lanes(_account(account_id, dsn), dsn=dsn)
    unknown = [lane for lane in lanes if lane not in LANES]
    if unknown:
        raise ValueError(f"unknown lanes {unknown}; known: {list(LANES)}")

    result = scout.scout(brand=brand, count=max(1, min(int(count), 8)),
                         lanes=lanes, dsn=dsn, account_id=_account(account_id, dsn))
    return {
        "ok": result["ok"],
        "brand": brand,
        "signals": result.get("signals", 0),
        "images": len(result.get("bin") or []),
        # Errors are returned, never swallowed: a crawl that quietly
        # finds nothing looks exactly like a healthy one, which is the
        # failure mode that hid the dead launchd job for eleven nights.
        "errors": result.get("errors") or [],
        "findings": [
            {"id": f.get("id"), "spark": f.get("spark"),
             "score": f.get("score"), "rationale": f.get("rationale") or ""}
            for f in result.get("findings") or []
        ],
    }


def resolve_finding(spark: str, brand: str, finding_id: Optional[int] = None,
                    dsn: Optional[str] = None) -> tuple[str, str, Optional[dict]]:
    """Which banked finding, if any, a generate call is running FROM --
    and therefore whose reference images ride along.

    The server decides, the same way /api/scenes/run decides for the
    composer: a client-side id is exactly what goes stale. Three cases.
    An explicit `finding_id` with no spark runs that finding's spark. An
    explicit id WITH a spark must be that finding's spark (on
    `_spark_key`, so fixed capitals still match) -- a reworded direction
    anchored on a stranger's thumbnail is not the caller's direction, and
    rather than silently drop the photos the way the composer does, this
    door says so, because an agent can act on a message and a person
    can see a tile. No id: the spark text is looked up, so `add_spark`
    -> `reference` -> `generate(spark)` finds its own photographs
    without the agent having to carry an id between calls.

    Returns (spark, brand, finding-or-None). Never spends.
    """
    spark = " ".join((spark or "").split())
    finding = None
    if finding_id is not None:
        try:
            finding = scout.get_finding(int(finding_id), dsn=dsn, strict=True)
        except scout.Unreadable as e:
            raise Refused(str(e)) from e
        if finding is None:
            raise ValueError(f"no finding {finding_id}")
        if spark and not scout.claims(finding["id"], spark, dsn=dsn):
            raise ValueError(
                f"spark {spark!r} is not finding {finding['id']}'s spark "
                f"({finding['spark']!r}). Run the finding's own spark, or omit "
                "finding_id to run a direction of your own -- its references "
                "belong to the direction they were banked behind.")
        spark = spark or " ".join((finding.get("spark") or "").split())
        brand = brand or finding["brand"]
        if brand != finding["brand"]:
            raise ValueError(f"finding {finding['id']} was banked for "
                             f"{finding['brand']!r}, not {brand!r}")
    elif spark and brand:
        finding = scout.find_by_spark(brand, spark, dsn=dsn)
    return spark, brand, finding


def run_graph(spark: str = "", brand: str = "", goal: str = "",
              channel: str = "", finding_id: Optional[int] = None,
              account_id: Optional[int] = None,
) -> dict[str, Any]:
    """One pass through the LangGraph content graph: ground, generate,
    evaluate, retry, score the prompt, keyframe if it clears the gate,
    and park in the Queue.

    Parking IS the terminal state, and that is the point -- the graph
    ends at the spend gate rather than through it, so an agent can drive
    concept generation end to end without being able to buy anything.

    THE REFERENCES COME FROM THE SPARK'S BIN (2026-09-03). This call
    used to take a spark string and nothing else, and `orchestrator.run`
    with an explicit spark never reads the bin (the scout node acts only
    when asked to CHOOSE the direction) -- so an agent could bank six
    photographs behind a spark with `reference` and then generate from
    that spark with none of them. Now `resolve_finding` names the
    finding, its bin becomes `reference_photos`, and the id rides the
    run so `planner` claims the finding and the hold card says where
    the idea came from. Same rule as the composer: the photos behind a
    direction ride with THAT direction, never a reworded one.

    Refuses outright when ZEROPAGE_RENDER=1. That flag turns
    `generate_render` from a dry stub into real Veo spend, and the one
    thing this surface must never be is the caller that trips it.

    `finding_id` closes a gap the composer already closed for itself
    (`/api/scenes/run`'s `scout_finding_id`): a spark run straight
    through here -- Mike pasting a banked spark's text into `generate`,
    or an agent firing on one it read from `sparks`/`tonight` -- never
    claimed the bank row, because `orchestrator.planner` only stamps
    `used_at` when its OWN `scout` node pulled the finding
    (state["scout"]=True, the nightly path only). A finding that sits
    unused at its original score is what the next `next_spark` call, or
    tonight's batch, hands back out as a "new" direction -- the same
    idea generated twice. Same guard as the composer's: `scout.claims()`
    checks the text still matches this finding (a stale id is not
    silently trusted), and the claim lands only once a concept actually
    exists, so a run that errored or held burns nothing.
    """
    account_id = _account(account_id, None)      # None: DATABASE_URL, read at call time
    if os.environ.get("ZEROPAGE_RENDER") == "1":
        raise Refused(
            "refusing: ZEROPAGE_RENDER=1 makes the graph spend render "
            "credit, and this surface is not allowed to be what trips "
            "it. Run the graph on the machine, or unset the flag."
        )
    _create_gate(account_id)
    # DATABASE_URL read at CALL time, like _account above: a default bound
    # at import is the path the process started with, not the one a
    # test (or a later reconfiguration) points the module at.
    spark, brand, finding = resolve_finding(spark, brand, finding_id)
    _check(brand, preprod.BRANDS, "brand")
    if not spark:
        raise ValueError("spark is empty")
    photos = [b["url"] for b in scout.bin_for_finding(finding["id"])
              if b.get("url")] if finding else []

    from . import orchestrator

    state = orchestrator.run(goal or spark, brand=brand, spark=spark,
                             channel=channel or brand, account_id=account_id,
                             reference_photos=photos,
                             scout_finding_id=finding["id"] if finding else None)
    concept_id = state.get("concept_id")
    claimed = bool(finding_id) and scout.claims(finding_id, spark)
    if claimed and concept_id:
        scout.mark_used(finding_id, run_id=f"concept:{concept_id}")
    out = {
        "concept_id": concept_id,
        "brand": brand,
        "spark": spark,
        "finding_id": finding["id"] if finding else None,
        "reference_photos": photos,
        "attempts": state.get("attempts"),
        "held_reason": state.get("held_reason") or "",
        "parked_reason": state.get("parked_reason") or "",
        "finding_claimed": bool(claimed and concept_id),
        "keyframes": [
            {"n": k.get("n"), "ok": k.get("ok"), "url": k.get("url") or "",
             "error": k.get("error") or ""}
            for k in state.get("keyframes") or []
        ],
        "prompt_scores": [
            {"score": p.get("score"), "pass": p.get("pass"),
             "reason": p.get("reason") or ""}
            for p in state.get("prompt_scores") or []
        ],
        "error": state.get("error"),
    }
    if concept_id:
        concept = preprod.get_concept(concept_id, account_id=account_id)
        out["idea"] = _card(concept)
        # The verdict rides back with the run rather than waiting for a
        # second call: a held run's whole point is the reason it held.
        out["idea"].update(_gate(concept, None, account_id))
    return out


# --- the server ------------------------------------------------------------

# Written against the INSTALLED mcp SDK, 2.1.1 (2026-08-31). v2 renamed
# FastMCP to MCPServer and moved `stateless_http` from the constructor
# onto `streamable_http_app()`; code written for mcp 1.x imports a
# module that no longer exists. requirements.txt pins mcp>=2 for that
# reason -- verify this import on a major bump, the same rule veo.py
# carries for google-genai.

TOOLS = (
    list_ideas, get_idea, search_ideas, capture_idea, pick_idea,
    archive_idea, bank_spark, bank_reference, find_images, next_spark,
    list_sparks, spark_images, pipeline_stats,
)
ENGINE_TOOLS = (run_research, run_graph)


def build_server(dsn: Optional[str] = None, name: str = "zeropage-ideas",
                 start_job=None, job_status=None, account_id: Optional[int] = None,
                 engine: Optional[bool] = None, listed: bool = False,
                 approve_render=None, approve_keyframes=None):
    """Wrap the functions above as an MCP server.

    `listed=True` registers LISTED_TOOLS only -- the set a stranger reaches
    through the directory listing -- and never the engine tools, whatever
    the flag says. The mount builds one of each and routes by door.

    `approve_render` / `approve_keyframes` are app/api.py's priced approve
    bodies, injected like `start_job` because src/ never imports app/.
    The `approve` tool registers only when both are given; a server
    without them (stdio, a test) has `quote` and no way to spend.

    `account_id` is whose board this server reads (2026-09-18): the
    Guide opens one in-process per signed-in request, and the board it
    shows must be that account's, not the bootstrap account's. None
    keeps the bearer-token posture (`_account`). `engine` overrides the
    environment gate: the Guide passes False explicitly, the way
    `research_agent._server_env` strips the variable -- `.env` has it
    on and the server loads `.env` itself. None reads the environment.

    `mcp` is imported lazily so it stays an optional dependency: the
    tool surface is testable, and the pipeline runs, on a machine that
    never installed it.

    `start_job`/`job_status` are the app-layer capability src/ cannot
    reach -- `app/jobs.py` is a thread registry that belongs to the web
    process -- so they are INJECTED as callables, the same way
    `scene_chain` takes the two capabilities it needs from app/. Without
    them the engine tools still register, but run inline; that is fine
    for a CLI or a test and wrong for HTTP, where a five-minute graph
    run would sit on an open request until something times out.

    Each tool is registered explicitly rather than in a loop over TOOLS,
    because the SDK publishes a tool's signature to the model -- and a
    loop would publish `path` as an argument, which is a database path
    chosen by a remote caller.
    """
    from mcp.server.mcpserver import MCPServer
    from mcp.server.mcpserver.exceptions import ToolError
    from mcp.types import ToolAnnotations

    def _t(fn, *args, **kwargs):
        """Call a tool function, translating its ValueErrors.

        The SDK draws a deliberate line: a ToolError's message reaches
        the model, and every other exception is a crash whose text stays
        on the server as "Error executing tool <name>". Every ValueError
        raised above is a CALLER error -- an unknown id, a brand that
        does not exist, an empty query -- and the message is the whole
        useful part of it. Without this translation an agent cannot tell
        "you passed a bad id" from "the server is broken", and its only
        recovery from either is to retry the identical call.
        """
        try:
            return fn(*args, **kwargs)
        except (ValueError, Refused) as exc:
            raise ToolError(str(exc)) from exc

    # --- what a stranger reads (2026-10-07, the directory listing) ------
    #
    # Every title, description and annotation comes from the constants
    # above (TITLES / DESCRIPTIONS / HINTS), never from a docstring: the
    # SDK reads a docstring at registration, so a docstring written for
    # the operator's agent ("the nightly", "the Dev Studio", a venv
    # command) is what a directory user would have been handed. The test
    # pins each registered tool to its constant and screens the
    # vocabulary. The functions' own docstrings stay as the operator's
    # notes, which is what they always were.
    def _ann(name: str) -> ToolAnnotations:
        hints = HINTS[name]
        return ToolAnnotations(title=TITLES[name], read_only_hint=hints["read"],
                               destructive_hint=hints["destructive"],
                               idempotent_hint=hints["idempotent"],
                               open_world_hint=hints["open_world"])

    def _reg(name: str):
        if listed and name not in LISTED_TOOLS:
            return lambda fn: fn          # not offered on the listed server
        return server.tool(name=name, title=TITLES[name],
                           description=DESCRIPTIONS[name], annotations=_ann(name))

    server = MCPServer(name, instructions=INSTRUCTIONS)

    def _run(fn, *args, **kwargs):
        """Engine tools go through the job registry when one was
        injected, and return a job id instead of a result. The job is
        the caller's (resolved here, in the request)."""
        label = kwargs.pop("_label", fn.__name__)
        if start_job is None:
            return _t(fn, *args, **kwargs)
        job = start_job("mcp", label, lambda job: {"result": fn(*args, **kwargs)},
                        account_id=_account(account_id, dsn))
        return {"job_id": job["id"], "status": job["status"], "label": label,
                "note": "started; poll with the `job` tool"}

    @_reg("board")
    def board(brand: Optional[Brand] = None, status: Status = "open",
              limit: int = LIST_LIMIT) -> dict:
        return _t(list_ideas, brand=brand, status=status, limit=limit, dsn=dsn,
                  account_id=account_id)

    @_reg("idea")
    def idea(idea_id: int) -> dict:
        return _t(get_idea, idea_id, dsn=dsn, account_id=account_id)

    @_reg("search")
    def search(query: str, brand: Optional[Brand] = None,
               limit: int = LIST_LIMIT) -> dict:
        return _t(search_ideas, query, brand=brand, limit=limit, dsn=dsn,
                  account_id=account_id)

    @_reg("capture")
    def capture(title: str, hook: str = "", logline: str = "", spark: str = "",
                brand: Brand = DEFAULT_BRAND) -> dict:
        return _t(capture_idea, brand=brand, title=title, hook=hook,
                  logline=logline, spark=spark, dsn=dsn, account_id=account_id)

    @_reg("pick")
    def pick(idea_id: int, picked: bool = True) -> dict:
        return _t(pick_idea, idea_id, picked=picked, dsn=dsn, account_id=account_id)

    @_reg("shoot")
    def shoot(idea_id: int, shot: bool = True) -> dict:
        return _t(shoot_idea, idea_id, shot=shot, dsn=dsn, account_id=account_id)

    @_reg("archive")
    def archive(idea_id: int, archived: bool = True, reason: str = "") -> dict:
        return _t(archive_idea, idea_id, archived=archived, reason=reason,
                  dsn=dsn, account_id=account_id)

    @_reg("add_spark")
    def add_spark(spark: str, rationale: str = "", evidence: str = "",
                  brand: Brand = DEFAULT_BRAND) -> dict:
        return _t(bank_spark, brand=brand, spark=spark, rationale=rationale,
                  evidence=evidence, dsn=dsn)

    @_reg("tonight")
    def tonight(brand: Brand = DEFAULT_BRAND) -> dict:
        return _t(next_spark, brand, dsn=dsn)

    @_reg("sparks")
    def sparks(brand: Optional[Brand] = None, unused_only: bool = True,
               limit: int = 20) -> dict:
        return _t(list_sparks, brand=brand, unused_only=unused_only,
                  limit=limit, dsn=dsn)

    @_reg("images")
    def images(finding_id: int) -> dict:
        return _t(spark_images, finding_id, dsn=dsn)

    @_reg("reference")
    def reference(finding_id: int, candidate_id: str = "",
                  image_url: str = "", source_url: str = "",
                  title: str = "") -> dict:
        return _t(bank_reference, finding_id, candidate_id=candidate_id,
                  image_url=image_url, source_url=source_url, title=title,
                  dsn=dsn)

    @_reg("imagine_reference")
    def imagine_reference(finding_id: int, hook_frame: str) -> dict:
        from . import refgen
        # the caller pays (2026-09-29): a signed-in account is charged the
        # still, the operator's key resolves to an exempt account
        return _t(refgen.render_for_finding, finding_id, hook_frame, dsn=dsn,
                  account_id=_account(account_id, dsn))

    @_reg("images_for")
    def images_for(query: str, brand: str = "", limit: int = 6) -> dict:
        return _t(find_images, query, brand=brand, limit=limit, dsn=dsn)

    @_reg("stats")
    def stats() -> dict:
        return _t(pipeline_stats, dsn=dsn, account_id=account_id, include_bank=not listed)

    if (engine_enabled() if engine is None else engine) and not listed:
        @_reg("research")
        def research(brand: Brand = DEFAULT_BRAND, count: int = 4,
                     lanes: Optional[list[Lane]] = None) -> dict:
            return _run(run_research, brand=brand, count=count, lanes=lanes,
                        dsn=dsn,
                        # resolved HERE, in the request: the job runs on
                        # another thread, where the signed-in caller's
                        # ContextVar is not promised to follow
                        account_id=_account(account_id, dsn),
                        _label=f"research {brand}")

        @_reg("generate")
        def generate(spark: str = "", brand: Optional[Brand] = None, goal: str = "",
                     finding_id: Optional[int] = None) -> dict:
            # Resolved HERE, before the job starts: a bad id or a
            # reworded spark is a caller error, and one raised inside a
            # background job is a failed job the agent has to poll for.
            spark, brand, finding = _t(resolve_finding, spark, brand or "",
                                       finding_id, dsn=dsn)
            brand = brand or DEFAULT_BRAND
            return _run(run_graph, spark=spark, brand=brand, goal=goal,
                        finding_id=finding["id"] if finding else None,
                        account_id=_account(account_id, dsn),
                        _label=f"graph {brand}")

    @_reg("elements")
    def elements() -> dict:
        return _t(list_elements, dsn=dsn, account_id=account_id)

    @_reg("write_scene")
    def write_scene_tool(idea_id: int, prompt: str, seconds: int = 10,
                         refs: Optional[list[str]] = None) -> dict:
        return _t(write_scene, idea_id, prompt, seconds=seconds, refs=refs,
                  dsn=dsn, account_id=account_id)

    @_reg("quote")
    def quote(idea_id: int, provider: Optional[str] = None, model: Optional[str] = None,
              duration: Optional[int] = None, frame: Optional[str] = None) -> dict:
        return _t(quote_render, idea_id, provider=provider, model=model,
                  duration=duration, frame=frame, dsn=dsn, account_id=account_id)

    if approve_render is not None and approve_keyframes is not None:
        @_reg("approve")
        def approve(idea_id: int, what: WhatToApprove = "clip",
                    tokens: Optional[list[str]] = None, provider: Optional[str] = None,
                    model: Optional[str] = None, duration: Optional[int] = None,
                    frame: Optional[str] = None) -> dict:
            from .approvals import ApproveRefused
            acting = _account(account_id, dsn)
            try:
                if what == "keyframes":
                    out = approve_keyframes(int(idea_id), acting)
                else:
                    out = approve_render(int(idea_id), acting, {
                        "provider": provider, "model": model, "duration": duration,
                        "frame": frame, "tokens": [t for t in (tokens or []) if t]})
            except ApproveRefused as e:
                hint = (" -- call `quote` and pass its tokens"
                        if e.code in ("missing_quote", "expired", "stale_content",
                                      "wrong_render", "bad_signature") else
                        " -- `pick` the idea first" if e.code == "not_queued" else "")
                raise ToolError(f"{e.code}: {e.message}{hint}") from e
            out = dict(out)
            out.setdefault("note", "started; poll with the `job` tool")
            return out

    if job_status is not None:
        @_reg("job")
        def job(job_id: int) -> dict:
            snap = job_status(int(job_id), account_id=_account(account_id, dsn))
            if snap is None:
                raise ToolError(
                    f"no job {job_id} -- jobs live in memory and a restart "
                    "clears them; start the work again if it was yours"
                )
            return snap

    return server


# --- stdio ------------------------------------------------------------------
#
# TWO TRANSPORTS, TWO CALLERS, AND THE DEFAULT IS THE SAFE ONE.
#
# The HTTP mount (app/mcp_mount.py) exists for a caller that is not on
# this machine: the studio app's own agent, or a phone through a tunnel.
# It costs a public endpoint, a bearer token, and a tunnel to keep alive.
#
# stdio costs none of that. Claude Desktop LAUNCHES this process itself,
# talks to it down a pipe, and there is no port, no token on the
# internet, and nothing to leave running. Since the desktop app also
# proxies its local MCP servers up to cloud sessions, the board is
# reachable from a phone through the SAME connection -- the tunnel was
# only ever buying the part the desktop app already does.
#
# So stdio is the default and the documented path. The HTTP mount stays
# for the case stdio genuinely cannot serve: something that is not
# Claude Desktop, talking to this pipeline over a network.

def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="The Zero Page idea board as an MCP server.")
    parser.add_argument("--db", default=None,
                        help="database URL (default: DATABASE_URL)")
    parser.add_argument("--engine", action="store_true",
                        help=f"register the two tools that spend model credit "
                             f"(same as {ENGINE_ENV}=1)")
    args = parser.parse_args(argv)

    # .env is loaded HERE rather than at import: Claude Desktop launches
    # this with a bare environment -- no shell profile, no cwd it would
    # find -- so GEMINI_API_KEY and the rest have to be read off disk or
    # every engine tool fails with a missing key it cannot explain.
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    if args.engine:
        os.environ[ENGINE_ENV] = "1"

    dsn = args.db or None
    # Tables the tools read must exist before the first call: a desktop
    # that launches this on a fresh clone would otherwise answer its
    # first `board` with "no such table" instead of an empty board.
    db.init_db(dsn)
    preprod.init(dsn)
    scout.init(dsn)

    # The job registry, injected here for the same reason app/mcp_mount.py
    # injects it: a graph run takes minutes, and a tool call that blocks
    # that long is a tool call the desktop times out. With it, `generate`
    # and `research` hand back a job id and `job` polls them.
    #
    # This is the ONE place src/ reaches into app/, and it is deliberate:
    # the rule exists so the LIBRARY layer stays importable without the
    # web app, and `main` is a process entry point, not a module anything
    # imports. app/jobs.py is stdlib-only (asyncio, threading, datetime)
    # -- importing it pulls in no FastAPI and costs nothing. The
    # alternative was a second job registry living in src/, and one
    # registry with an odd import beats two implementations that drift.
    try:
        from app import jobs
        start_job, job_status = jobs.start, jobs.get
    except Exception as exc:                    # surfaced, never silent
        print(f"note: no job registry ({type(exc).__name__}: {exc}) -- engine "
              "tools will run inline and may time out", file=sys.stderr)
        start_job = job_status = None

    build_server(dsn=dsn, start_job=start_job, job_status=job_status).run("stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
