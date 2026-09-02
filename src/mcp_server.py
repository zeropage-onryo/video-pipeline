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
database path; the FastMCP wrapper around them is built lazily in
`build_server`. So the whole tool surface stays testable with no `mcp`
package installed, and a machine that never serves MCP does not grow an
import-time dependency on one -- the same degrade-don't-break rule the
rest of src/ follows.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Optional

from . import accounts, db, preprod, refbin, scout

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


def _full(concept: dict) -> dict[str, Any]:
    """The whole concept, prompts included. Shots are passed through
    rather than reshaped -- `shots_json` is the flexible column every
    other surface reads, and a second shape maintained here is a second
    thing to forget to update."""
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
    return out


def _check(value: str, allowed, label: str) -> str:
    if value not in allowed:
        raise ValueError(f"{label} must be one of {list(allowed)}, got {value!r}")
    return value


# --- the board -------------------------------------------------------------

def _account(account_id: Optional[int], path) -> Optional[int]:
    """Which account an MCP call acts as.

    There is no session here: the MCP surface is reached from a Claude
    session on Mike's machine, holding a bearer token, not a cookie. So
    it acts as the bootstrap account unless told otherwise -- the same
    call the CLIs make, for the same reason. After the tenancy backfill,
    acting as nobody means reading an empty database and reporting it as
    an empty board.
    """
    return account_id if account_id is not None else accounts.resolve_account(path=path)


def list_ideas(
    brand: Optional[str] = None,
    status: str = "open",
    limit: int = LIST_LIMIT,
    path: Path | str = db.DB_PATH,
    account_id: Optional[int] = None,
) -> dict[str, Any]:
    """The board. Newest first, because the ones just generated are the
    ones being decided about."""
    account_id = _account(account_id, path)
    _check(status, STATUSES, "status")
    if brand:
        _check(brand, preprod.BRANDS, "brand")
    limit = max(1, min(int(limit), 100))

    cards = []
    for concept in preprod.list_concepts(limit=SEARCH_SCAN, path=path, account_id=account_id):
        if brand and concept["brand"] != brand:
            continue
        if not _matches(concept, status):
            continue
        cards.append(_card(concept))
        if len(cards) >= limit:
            break
    return {"brand": brand or "all", "status": status,
            "count": len(cards), "ideas": cards}


def get_idea(idea_id: int, path: Path | str = db.DB_PATH, account_id: Optional[int] = None) -> dict[str, Any]:
    """One concept in full, including the scene prompt."""
    account_id = _account(account_id, path)
    concept = preprod.get_concept(int(idea_id), path=path, account_id=account_id)
    if concept is None:
        raise ValueError(f"no idea {idea_id}")
    return _full(concept)


def search_ideas(
    query: str,
    brand: Optional[str] = None,
    limit: int = LIST_LIMIT,
    path: Path | str = db.DB_PATH,
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
    account_id = _account(account_id, path)
    needle = (query or "").strip().lower()
    if not needle:
        raise ValueError("query is empty")
    if brand:
        _check(brand, preprod.BRANDS, "brand")
    limit = max(1, min(int(limit), 100))

    hits = []
    for concept in preprod.list_concepts(limit=SEARCH_SCAN, path=path, account_id=account_id):
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
        if len(hits) >= limit:
            break
    return {"query": query, "count": len(hits), "ideas": hits}


def capture_idea(
    brand: str,
    title: str,
    hook: str = "",
    logline: str = "",
    spark: str = "",
    path: Path | str = db.DB_PATH,
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
    account_id = _account(account_id, path)
    _check(brand, preprod.BRANDS, "brand")
    title = (title or "").strip()
    if not title:
        raise ValueError("title is required")

    idea = {"title": title, "hook": hook or "", "logline": logline or ""}
    (idea_id,) = preprod.save_concept_ideas(
        [idea], brand=brand, spark=(spark or "").strip() or None, path=path,
        account_id=account_id,
    )
    card = _card(preprod.get_concept(idea_id, path=path, account_id=account_id))
    card["next"] = (
        "Idea only -- no scene prompt yet. Write one on the machine with "
        f"`venv/bin/python -m src.shootgen --scene {idea_id}`."
    )
    return card


def pick_idea(idea_id: int, picked: bool = True,
              path: Path | str = db.DB_PATH,
              account_id: Optional[int] = None,
) -> dict[str, Any]:
    """Mark a concept worth rendering -- the label `pick_rate` reads.

    Picking does NOT render. It puts the concept in front of the Queue's
    spend gate, where approving is what calls Runway, on the machine.
    """
    account_id = _account(account_id, path)
    preprod.set_picked(int(idea_id), picked=picked, path=path, account_id=account_id)
    return _card(preprod.get_concept(int(idea_id), path=path, account_id=account_id))


def archive_idea(idea_id: int, archived: bool = True, reason: str = "",
                 path: Path | str = db.DB_PATH,
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
    account_id = _account(account_id, path)
    preprod.set_archived(int(idea_id), archived=archived, path=path,
                         account_id=account_id, reason=reason)
    return _card(preprod.get_concept(int(idea_id), path=path, account_id=account_id))


# --- the night's direction -------------------------------------------------

def bank_spark(
    brand: str,
    spark: str,
    rationale: str = "",
    evidence: str = "",
    score: float = HUMAN_SPARK_SCORE,
    path: Path | str = db.DB_PATH,
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
        for row in scout.list_findings(brand=brand, path=path)
        if row.get("spark_key") == key
    ]
    finding_id = scout.record(
        brand,
        {"spark": spark, "rationale": rationale, "evidence": evidence,
         "sources": [], "score": float(score)},
        lanes="human",
        path=path,
    )
    return {"id": finding_id, "brand": brand, "spark": spark,
            "score": float(score), "lanes": "human",
            "duplicate_of": clashes,
            "serves_next": float(score) >= scout.SCORE_FLOOR}


def next_spark(brand: str, path: Path | str = db.DB_PATH) -> dict[str, Any]:
    """What tonight's `--scout` run would take: the highest-scoring
    unused finding at or above the floor. None means it falls back to
    the `prompts/sparks.txt` rotation, which is the healthy degraded
    path, not an error."""
    _check(brand, scout.BRANDS, "brand")
    row = scout.next_spark(brand, path=path)
    if row is None:
        return {"brand": brand, "spark": None,
                "note": f"nothing unused at or above the {scout.SCORE_FLOOR} "
                        "floor -- tonight falls back to sparks.txt"}
    return {"brand": brand, "id": row["id"], "spark": row["spark"],
            "score": row.get("score"), "rationale": row.get("rationale") or "",
            "evidence": row.get("evidence") or "", "lanes": row.get("lanes") or ""}


def list_sparks(brand: Optional[str] = None, unused_only: bool = True,
                limit: int = 20, path: Path | str = db.DB_PATH) -> dict[str, Any]:
    """The scout's bank, highest-scoring first."""
    if brand:
        _check(brand, scout.BRANDS, "brand")
    rows = scout.list_findings(brand=brand, unused_only=unused_only,
                               limit=max(1, min(int(limit), 100)), path=path)
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

def pipeline_stats(path: Path | str = db.DB_PATH, account_id: Optional[int] = None) -> dict[str, Any]:
    """The two surviving labels plus what is sitting on the board.

    `by_prompt` is dropped on purpose: it is the per-prompt-hash
    breakdown the Dev Studio's Stats tab renders, and a phone asking
    "how are we doing" wants the headline. The Stats tab is where the
    breakdown belongs.
    """
    account_id = _account(account_id, path)
    pick = preprod.pick_rate(path=path, account_id=account_id)
    shoot = preprod.shoot_rate(path=path, account_id=account_id)
    board = {s: 0 for s in STATUSES if s != "all"}
    for concept in preprod.list_concepts(limit=SEARCH_SCAN, path=path, account_id=account_id):
        board[_status_of(concept)] += 1
    return {
        "pick_rate": {k: pick[k] for k in ("generated", "picked", "rate")},
        "shoot_rate": {k: shoot.get(k) for k in ("generated", "shot", "rate")},
        "board": board,
        # `board` counts are exclusive so they sum to the row count.
        # `list_ideas(status="open")` is not exclusive -- a parked scene
        # is still waiting on a person -- so the number it returns is
        # spelled out here rather than left to be derived wrongly.
        "waiting_on_you": board["open"] + board["parked"],
        "sparks_unused": len(
            scout.list_findings(unused_only=True, limit=100, path=path)
        ),
    }


# --- the research bin ------------------------------------------------------

def bank_reference(
    finding_id: int,
    image_url: str,
    source_url: str,
    title: str = "",
    path: Path | str = db.DB_PATH,
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
    """
    finding = scout.get_finding(int(finding_id), path=path)
    if finding is None:
        raise ValueError(f"no finding {finding_id}")
    if not (source_url or "").strip():
        raise ValueError("source_url is required — an unattributed reference "
                         "is the wrong thing to put in front of a spend")

    pass_id = (finding.get("pass_id") or "").strip()
    if not pass_id:
        pass_id = scout.agent_pass_id(finding["id"])
        scout.set_pass_id(finding["id"], pass_id, path=path)

    stored = refbin.fetch(image_url)
    if not stored:
        return {"ok": False, "finding_id": finding["id"], "pass_id": pass_id,
                "error": "not a readable image, too large, or a refused host",
                "banked": len(scout.bin_for_pass(pass_id, path=path))}

    row = scout.bin_add(finding["brand"], pass_id, stored,
                        source_url=source_url.strip(), title=title.strip(),
                        lane="agent", path=path)
    banked = scout.bin_for_pass(pass_id, path=path)
    if row is None:
        return {"ok": False, "finding_id": finding["id"], "pass_id": pass_id,
                "url": stored, "banked": len(banked),
                "error": f"already banked, or the pass is full "
                         f"({scout.MAX_BIN_IMAGES} images)"}
    return {"ok": True, "finding_id": finding["id"], "pass_id": pass_id,
            "url": stored, "source_url": row["source_url"],
            "banked": len(banked), "cap": scout.MAX_BIN_IMAGES}


def spark_images(finding_id: int, path: Path | str = db.DB_PATH) -> dict[str, Any]:
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
    rows = scout.bin_for_finding(int(finding_id), path=path)
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
# the judge, and a Nano keyframe under NANO_DAILY_CAP. Cents, not
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
LANES = ("web", "shorts", "feeds", "instagram", "creators")


def engine_enabled() -> bool:
    return os.environ.get(ENGINE_ENV) == "1"


def run_research(brand: str, count: int = 4, lanes=None,
                 path: Path | str = db.DB_PATH) -> dict[str, Any]:
    """One full scout pass: crawl the lanes, digest to scored sparks,
    bank them, and stash the images behind them.

    Returns the banked findings rather than the crawl. The digest step
    exists precisely so raw crawl text never reaches a generator, and
    handing it to an agent instead would just move that mistake one
    layer out.
    """
    _check(brand, scout.BRANDS, "brand")
    lanes = tuple(lanes) if lanes else LANES
    unknown = [lane for lane in lanes if lane not in LANES]
    if unknown:
        raise ValueError(f"unknown lanes {unknown}; known: {list(LANES)}")

    result = scout.scout(brand=brand, count=max(1, min(int(count), 8)),
                         lanes=lanes, path=path)
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


def run_graph(spark: str, brand: str, goal: str = "",
              channel: str = "",
              account_id: Optional[int] = None,
) -> dict[str, Any]:
    """One pass through the LangGraph content graph: ground, generate,
    evaluate, retry, score the prompt, keyframe if it clears the gate,
    and park in the Queue.

    Parking IS the terminal state, and that is the point -- the graph
    ends at the spend gate rather than through it, so an agent can drive
    concept generation end to end without being able to buy anything.

    Refuses outright when ZEROPAGE_RENDER=1. That flag turns
    `generate_render` from a dry stub into real Veo spend, and the one
    thing this surface must never be is the caller that trips it.
    """
    account_id = _account(account_id, db.DB_PATH)
    if os.environ.get("ZEROPAGE_RENDER") == "1":
        raise Refused(
            "refusing: ZEROPAGE_RENDER=1 makes the graph spend render "
            "credit, and this surface is not allowed to be what trips "
            "it. Run the graph on the machine, or unset the flag."
        )
    _check(brand, preprod.BRANDS, "brand")
    spark = " ".join((spark or "").split())
    if not spark:
        raise ValueError("spark is empty")

    from . import orchestrator

    state = orchestrator.run(goal or spark, brand=brand, spark=spark,
                             channel=channel or brand, account_id=account_id)
    concept_id = state.get("concept_id")
    out = {
        "concept_id": concept_id,
        "brand": brand,
        "spark": spark,
        "attempts": state.get("attempts"),
        "held_reason": state.get("held_reason") or "",
        "parked_reason": state.get("parked_reason") or "",
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
        out["idea"] = _card(preprod.get_concept(concept_id, account_id=account_id))
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
    archive_idea, bank_spark, bank_reference, next_spark, list_sparks, spark_images,
    pipeline_stats,
)
ENGINE_TOOLS = (run_research, run_graph)


def build_server(path: Path | str = db.DB_PATH, name: str = "zeropage-ideas",
                 start_job=None, job_status=None):
    """Wrap the functions above as an MCP server.

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

    read_only = ToolAnnotations(read_only_hint=True)
    writes = ToolAnnotations(read_only_hint=False, destructive_hint=False)

    server = MCPServer(
        name,
        instructions=(
            "The Zero Page Films pre-production board. Read the board, "
            "pick or archive concepts, capture ideas, and bank sparks "
            "for the nightly run. Nothing here renders video: picking a "
            "concept puts it in front of a spend gate that a human "
            "approves on the machine."
        ),
    )

    def _run(fn, *args, **kwargs):
        """Engine tools go through the job registry when one was
        injected, and return a job id instead of a result. The job is
        the operator's (this surface has a bearer token, not a session
        -- see _account), so it shows on their rail and nobody else's."""
        label = kwargs.pop("_label", fn.__name__)
        if start_job is None:
            return _t(fn, *args, **kwargs)
        job = start_job("mcp", label, lambda job: {"result": fn(*args, **kwargs)},
                        account_id=_account(None, path))
        return {"job_id": job["id"], "status": job["status"], "label": label,
                "note": "started; poll with the `job` tool"}

    @server.tool(annotations=read_only)
    def board(brand: Optional[str] = None, status: str = "open",
              limit: int = LIST_LIMIT) -> dict:
        """List concepts on the pre-production board. status is one of
        open, picked, archived, parked, shot, all. brand is antihero or
        zeropage."""
        return _t(list_ideas, brand=brand, status=status, limit=limit, path=path)

    @server.tool(annotations=read_only)
    def idea(idea_id: int) -> dict:
        """Read one concept in full, including its scene prompt."""
        return _t(get_idea, idea_id, path=path)

    @server.tool(annotations=read_only)
    def search(query: str, brand: Optional[str] = None,
               limit: int = LIST_LIMIT) -> dict:
        """Find concepts whose title, hook, logline, spark or scene
        prompt contains this text."""
        return _t(search_ideas, query, brand=brand, limit=limit, path=path)

    @server.tool(annotations=writes)
    def capture(brand: str, title: str, hook: str = "", logline: str = "",
                spark: str = "") -> dict:
        """Put a new idea on the board. Saves an idea with no scene
        prompt; writing the scene is a separate step."""
        return _t(capture_idea, brand=brand, title=title, hook=hook,
                            logline=logline, spark=spark, path=path)

    @server.tool(annotations=writes)
    def pick(idea_id: int, picked: bool = True) -> dict:
        """Mark a concept worth rendering. Does NOT render or spend --
        it puts the concept in front of the Queue's spend gate, which a
        human approves on the machine."""
        return _t(pick_idea, idea_id, picked=picked, path=path)

    @server.tool(annotations=writes)
    def archive(idea_id: int, archived: bool = True, reason: str = "") -> dict:
        """Take a concept off the board. Hides it; never deletes. `reason`
        is one of boring, off-brand, unshootable, seen it, other -- the
        only record this pipeline keeps of WHY anything was rejected."""
        return _t(archive_idea, idea_id, archived=archived, reason=reason,
                  path=path)

    @server.tool(annotations=writes)
    def add_spark(brand: str, spark: str, rationale: str = "",
                  evidence: str = "") -> dict:
        """Bank a one-line direction for the nightly run to generate
        from."""
        return _t(bank_spark, brand=brand, spark=spark, rationale=rationale,
                          evidence=evidence, path=path)

    @server.tool(annotations=read_only)
    def tonight(brand: str) -> dict:
        """What direction tonight's scheduled run would take."""
        return _t(next_spark, brand, path=path)

    @server.tool(annotations=read_only)
    def sparks(brand: Optional[str] = None, unused_only: bool = True,
               limit: int = 20) -> dict:
        """List banked sparks, highest-scoring first."""
        return _t(list_sparks, brand=brand, unused_only=unused_only,
                           limit=limit, path=path)

    @server.tool(annotations=read_only)
    def images(finding_id: int) -> dict:
        """The reference images the scout banked alongside a spark, each
        with the source URL it came from."""
        return _t(spark_images, finding_id, path=path)

    @server.tool(annotations=writes)
    def reference(finding_id: int, image_url: str, source_url: str,
                  title: str = "") -> dict:
        """Bank one reference image behind a spark, so the run it feeds
        has something to render against and not just words.

        Hand over the image's URL and the page it came from -- this
        downloads it here, through the same guards and into the same
        /refs/<sha>.jpg bin a composer upload lands in. Attribution is
        required. Your own cast and prop photos do NOT go through here:
        they are already on file and get attached automatically to any
        scene that names them, ahead of anything banked."""
        return _t(bank_reference, finding_id, image_url=image_url,
                  source_url=source_url, title=title, path=path)

    @server.tool(annotations=read_only)
    def stats() -> dict:
        """Pick rate, shoot rate, and what is sitting on the board."""
        return _t(pipeline_stats, path=path)

    if engine_enabled():
        @server.tool(annotations=writes)
        def research(brand: str, count: int = 4,
                     lanes: Optional[list] = None) -> dict:
            """Run a research pass: crawl the lanes, bank scored sparks,
            and download the reference images behind them. Spends a
            grounded search and one digest call."""
            return _run(run_research, brand=brand, count=count, lanes=lanes,
                        path=path, _label=f"research {brand}")

        @server.tool(annotations=writes)
        def generate(spark: str, brand: str, goal: str = "") -> dict:
            """Run the LangGraph content graph on a spark: ground,
            generate, evaluate, score, keyframe, and park the scene in
            the Queue. Ends AT the spend gate, never through it."""
            return _run(run_graph, spark=spark, brand=brand, goal=goal,
                        _label=f"graph {brand}")

    if job_status is not None:
        @server.tool(annotations=read_only)
        def job(job_id: int) -> dict:
            """Check a background job: one this server started, or one
            /ui started on the machine. Registered whenever a registry
            was injected, engine tools or not -- reading the progress of
            a render somebody kicked off in Studio is exactly the thing
            worth having on a phone."""
            snap = job_status(int(job_id), account_id=_account(None, path))
            if snap is None:
                raise ToolError(
                    f"no job {job_id} -- the registry is in-process and a "
                    "restart clears it"
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
                        help="database path (default: data/pipeline.db)")
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

    path = args.db or db.DB_PATH
    # Tables the tools read must exist before the first call: a desktop
    # that launches this on a fresh clone would otherwise answer its
    # first `board` with "no such table" instead of an empty board.
    db.init_db(path)
    preprod.init(path)
    scout.init(path)

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

    build_server(path=path, start_job=start_job, job_status=job_status).run("stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
