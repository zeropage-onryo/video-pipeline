#!/usr/bin/env python3
"""
The nightly walk, with a way to stop.

    python3 -m src.nightly walk        # the 8 sparks x 2 brands the bash loop ran
    python3 -m src.nightly preflight   # the three checks, printed, nothing spent
    python3 -m src.nightly status      # the last few nights' receipts

This replaces step 4 of run_morning_prompts.sh -- the bare `for PAIR; for
spark; python3 -m src.trigger` loop -- and nothing else in that script.
Steps 1 to 3 (metrics, the idea-agent bank, the research agent, the
crawl) stay in bash where they are, each already never-fatal.

WHY A PYTHON RUNNER. The bash loop had no opinion about failure, so one
week of the owner's real logs reads like this:

  * `trigger: run crashed: [Errno 8] nodename nor servname provided` --
    one DNS lookup to the Supabase pooler failed, and the walk ran the
    other fifteen runs straight into the same dead socket.
  * `429 RESOURCE_EXHAUSTED ... prepayment credits are depleted`, retried
    six times per call, in all sixteen runs. A card with no money on it
    does not fill up during a twenty-second backoff.
  * `held='no keyframe: daily ceiling: 20/20 images generated ...'` --
    the image cap was already spent before the walk began, so every run
    produced a keyframe-less scene and sixteen identical hold reasons.

None of those are content problems. They are one fact about the world,
discovered sixteen times, at the cost of a night. So this runner asks
the world ONCE (preflight), stops the moment a failure is systemic
rather than about one concept (the breaker), stops when the night has
cost more than it is allowed to (the budget), and writes down that it
ran at all (db.nightly_runs) -- because eleven nights were lost to
launchd being refused by TCC, and a night with no runs looks exactly
like a healthy night unless something says otherwise.

WHAT IT DELIBERATELY DOES NOT DO: skip the walk when the image cap is
spent. Concept text is the cheap and useful half of a run; only the
keyframe is capped. So a capped night runs with ZEROPAGE_KEYFRAME=0 and
says so once, instead of paying for sixteen concepts and then explaining
sixteen times why none of them has a picture.
"""
from __future__ import annotations

import argparse
import functools
import os
import socket
import sys
from datetime import datetime, timezone
from typing import Callable, Optional

from dotenv import load_dotenv

from . import db, gemini_utils

# --------------------------------------------------------------------------
# what kind of failure this is
# --------------------------------------------------------------------------

SYSTEMIC = "systemic"
CONTENT = "content"

# The world is broken in a way the next run will hit too: the database is
# unreachable, the name does not resolve, the card is empty, the key is
# refused. Fifteen more attempts produce fifteen more copies of this.
_DNS_MARKERS = (
    "nodename nor servname",
    "name or service not known",
    "temporary failure in name resolution",
    "could not translate host name",
    "getaddrinfo failed",
    "connection refused",
    "connection reset by peer",
    "server closed the connection",
    "could not connect to server",
    "network is unreachable",
    "no route to host",
    "connection timed out",
)
_AUTH_MARKERS = (
    "api key not valid",
    "api_key_invalid",
    "invalid api key",
    "unauthenticated",
    "permission_denied",
    "401 unauthorized",
    "403 forbidden",
    "password authentication failed",
)
# A failure about THIS concept, or about one unlucky transaction. The next
# spark is a different concept and deserves its own attempt.
_CONTENT_MARKERS = (
    "deadlock detected",
    "deadlock",
    "could not serialize access",
)


def classify_error(error) -> str:
    """SYSTEMIC (stop the walk) or CONTENT (try the next spark).

    The one place that opinion lives, shared by the runner and by
    src/trigger.py's crash handler so a hold row and the breaker cannot
    disagree about the same exception.

    Order matters. A Postgres deadlock arrives as an OperationalError,
    the same class a dead socket does, so the content markers are read
    FIRST -- otherwise one unlucky transaction would look like a broken
    database and end a night that had nothing wrong with it. Everything
    unrecognised is CONTENT: erring that way costs one wasted run, and
    erring the other way costs the whole walk on an exception nobody has
    seen yet.
    """
    text = str(error).lower()
    if any(marker in text for marker in _CONTENT_MARKERS):
        return CONTENT
    if gemini_utils.is_depleted(error):
        return SYSTEMIC
    if isinstance(error, (socket.gaierror, ConnectionError)):
        return SYSTEMIC
    if any(marker in text for marker in _DNS_MARKERS):
        return SYSTEMIC
    if any(marker in text for marker in _AUTH_MARKERS):
        return SYSTEMIC
    try:
        import psycopg
        if isinstance(error, psycopg.OperationalError):
            return SYSTEMIC
    except Exception:      # psycopg missing is not this function's problem
        pass
    return CONTENT


def _first_line(error) -> str:
    """One line of an exception, for a log that has to stay readable.
    A google-genai 429 body is JSON several hundred characters long."""
    text = " ".join(str(error).split())
    return text[:200]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------
# preflight: ask the world once
# --------------------------------------------------------------------------

# A prompt small enough that its answer costs a rounding error, and
# specific enough that a model which replies at all has replied usefully.
PREFLIGHT_PROMPT = "Reply with the single word: ready"


def check_db(dsn: Optional[str] = None) -> dict:
    """Is the database there. This is the DNS check too -- the pooler
    hostname that failed to resolve on the owner's box is the one in
    DATABASE_URL, so a connection either proves name resolution or
    reproduces exactly the failure that killed the walk."""
    try:
        with db.connect(dsn) as conn:
            conn.execute("SELECT 1")
        return {"ok": True, "detail": "reachable"}
    except Exception as e:
        return {"ok": False, "kind": classify_error(e), "detail": _first_line(e)}


def check_gemini(client=None) -> dict:
    """One tiny call through the real retry helper.

    Through `generate_with_retry` on purpose, not around it: the thing
    being checked is the path the runs use, including its fallback
    chain, and since 2026-09-07 including its refusal to retry a
    depleted 429 -- which is what makes this check cost one second
    rather than five minutes on the night it matters most.
    """
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        return {"ok": False, "kind": SYSTEMIC, "detail": "GEMINI_API_KEY not set"}
    try:
        if client is None:
            from google import genai
            client = genai.Client(api_key=key)
        from . import shootgen
        model = os.environ.get("GEMINI_MODEL", shootgen.MODEL)
        gemini_utils.generate_with_retry(client, model, PREFLIGHT_PROMPT)
        return {"ok": True, "detail": f"{model} answered"}
    except Exception as e:
        return {"ok": False, "kind": classify_error(e), "detail": _first_line(e)}


def check_image_cap(dsn: Optional[str] = None, *, account_id: Optional[int] = None) -> dict:
    """How many keyframes the night may still render, against BOTH walls
    -- the per-account cap and the installation ceiling, since the
    ceiling is the one that was already spent when the walk started.

    A broken counter reports headroom None and `ok` True: not knowing is
    not a reason to run a keyframe-less night, and the caps themselves
    still refuse at the point of spend.
    """
    from . import nano_banana
    try:
        used = nano_banana.generations_today(db_path=dsn, account_id=account_id)
        everyone = nano_banana.generations_today(db_path=dsn, everyone=True)
    except Exception as e:
        return {"ok": True, "headroom": None, "detail": f"cap unreadable ({_first_line(e)})"}
    # A ceiling of 0 means OFF, not a ceiling of zero (2026-09-14, the same
    # reading generative.cap_error takes). Subtracting it blindly made
    # headroom negative, clamped to 0, and reported ok=False -- which would
    # have stopped the nightly walk every night on an installation that had
    # simply turned the installation-wide wall off.
    headroom = nano_banana.DAILY_CAP - used
    if nano_banana.GLOBAL_DAILY_CAP > 0:
        headroom = min(headroom, nano_banana.GLOBAL_DAILY_CAP - everyone)
    headroom = max(headroom, 0)
    return {
        "ok": headroom > 0,
        "headroom": headroom,
        "used": used,
        "everyone": everyone,
        "detail": (f"{used}/{nano_banana.DAILY_CAP} today"
                   + (f", {everyone}/{nano_banana.GLOBAL_DAILY_CAP} installation-wide"
                      if nano_banana.GLOBAL_DAILY_CAP > 0
                      else f", {everyone} installation-wide (no ceiling)")),
    }


def preflight(dsn: Optional[str] = None, *, account_id: Optional[int] = None,
              gemini_client=None) -> dict:
    """The three checks, once, before sixteen runs discover them the hard
    way. `stop` is the reason to not walk at all, or None."""
    database = check_db(dsn)
    gemini = check_gemini(gemini_client) if database["ok"] else {
        "ok": False, "detail": "not checked (database unreachable)"}
    images = check_image_cap(dsn, account_id=account_id) if database["ok"] else {
        "ok": True, "headroom": None, "detail": "not checked"}

    stop = None
    if not database["ok"]:
        stop = f"database unreachable: {database['detail']}"
    elif not gemini["ok"]:
        stop = f"gemini unreachable: {gemini['detail']}"
    return {
        "db": database, "gemini": gemini, "images": images,
        "stop": stop,
        "keyframes": bool(images.get("ok")),
    }


def preflight_line(report: dict) -> str:
    """The one line that goes in the log. One, because the point of a
    preflight is that the night's shape is legible before the runs."""
    images = report["images"]
    headroom = images.get("headroom")
    keyframes = ("keyframes off (image cap spent)" if not report["keyframes"]
                 else f"keyframes {headroom if headroom is not None else '?'} left")
    return (f"nightly preflight: db={'ok' if report['db']['ok'] else 'FAIL'} "
            f"gemini={'ok' if report['gemini']['ok'] else 'FAIL'} "
            f"images={images.get('detail')} -- {keyframes}"
            + (f" -- STOP: {report['stop']}" if report["stop"] else ""))


# --------------------------------------------------------------------------
# the walk
# --------------------------------------------------------------------------

BUDGET_ENV = "NIGHTLY_BUDGET_USD"
DEFAULT_BUDGET_USD = 5.00

# Both brand/channel pairs, matched, exactly as the bash loop passed them
# (see run_morning_prompts.sh's step 4 comment for why they are paired
# rather than crossed).
PAIRS = (("antihero", "antihero"), ("zeropage", "zeropage"))

# HOW MANY SPARKS A NIGHT WALKS, per pair. 2026-09-08, Mike's call: cut
# to 5 (so 5 antihero + 5 zeropage = 10 runs) until the concepts are
# worth more than they cost -- "we'll increase it once I see it gets
# better". Before this the walk took every line in prompts/sparks.txt,
# which had grown to 20, so a night was 40 runs and roughly $1.70 of
# Gemini for a queue nobody had finished grading.
#
# Deliberately a per-PAIR limit and not a total: a total of five, walked
# brand by brand, would spend the whole night on antihero and leave Zero
# Page's queue empty -- the exact failure the paired loop was written to
# fix.
SPARKS_ENV = "NIGHTLY_SPARKS"
DEFAULT_SPARKS_PER_PAIR = 5


def sparks_per_pair() -> int:
    """Read per call, so `NIGHTLY_SPARKS=20 python -m src.nightly walk` is
    a whole configuration change. Zero or unparseable falls back to the
    default rather than to a night that walks nothing."""
    raw = (os.environ.get(SPARKS_ENV) or "").strip()
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_SPARKS_PER_PAIR
    return value if value > 0 else DEFAULT_SPARKS_PER_PAIR

# LangSmith's client retries a failed export and prints a traceback per
# call. On a night with no network to it that is thousands of lines
# between the sixteen lines anybody wants. The runner turns tracing off
# for the walk unless NIGHTLY_TRACING=1 asks for it back.
TRACING_ENV = "NIGHTLY_TRACING"


def budget_usd() -> float:
    """Read per call, so a one-off `NIGHTLY_BUDGET_USD=1 python -m
    src.nightly walk` is a whole configuration change. An unparseable
    value falls back to the default rather than to no budget."""
    raw = (os.environ.get(BUDGET_ENV) or "").strip()
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_BUDGET_USD
    return value if value > 0 else DEFAULT_BUDGET_USD


def quiet_langsmith(log: Callable[[str], None] = print) -> bool:
    """Silence LangSmith for the walk unless asked otherwise. True if it
    was turned off here.

    Not a fix for the connection errors -- the fix is a working key or no
    key -- but the runner's log is the only record of a night, and an
    unreachable tracer must not be the loudest thing in it.
    """
    if (os.environ.get(TRACING_ENV) or "").strip().lower() in {"1", "true", "yes"}:
        return False
    # Only what is ON is turned off. An unset variable already means "no
    # tracing", and writing "false" over every one of them would leave
    # three new variables in the environment of everything the walk
    # imports -- a bigger footprint than the problem.
    changed = False
    for name in ("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2", "LANGCHAIN_TRACING"):
        if (os.environ.get(name) or "").strip().lower() in {"1", "true", "yes"}:
            os.environ[name] = "false"
            changed = True
    if changed:
        log(f"nightly: LangSmith tracing off for the walk ({TRACING_ENV}=1 to keep it)")
    return changed


def run_one(channel: str, brand: str, spark: str, *, research=True) -> dict:
    """One trigger run, IN PROCESS.

    In process rather than as a subprocess so the breaker can see the
    exception's class instead of guessing from an exit code, and so
    ZEROPAGE_KEYFRAME=0 set by the cap check actually reaches the graph.
    The seam every test patches.
    """
    from . import trigger
    return trigger.run_once(spark, channel=channel, brand=brand,
                            scout=None if research is None else research,
                            research=research)


def _restores_env(*names: str):
    """Put back what the walk changed.

    `walk` turns two things off for its own duration -- LangSmith tracing
    (quiet_langsmith) and keyframes when the image cap is already spent --
    by writing os.environ directly, and never put either back. As a
    one-shot subprocess on the Mac that was invisible: the process exits
    and takes the environment with it. Under the always-on Fly container
    it is not, because cron and uvicorn share a machine and a process
    environment, so one night that hit the image cap left ZEROPAGE_KEYFRAME
    pinned to "0" for the WEB app until the machine restarted -- every
    Director keyframe after it silently disabled, with the reason sitting
    in a log nobody reads.

    Snapshot before, restore after, delete the ones that were not there.
    """
    def decorate(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            before = {n: os.environ.get(n) for n in names}
            try:
                return fn(*args, **kwargs)
            finally:
                for name, was in before.items():
                    if was is None:
                        os.environ.pop(name, None)
                    else:
                        os.environ[name] = was
        return wrapper
    return decorate


@_restores_env("ZEROPAGE_KEYFRAME", "LANGSMITH_TRACING",
               "LANGCHAIN_TRACING_V2", "LANGCHAIN_TRACING")
def walk(*, sparks: Optional[list] = None, pairs=PAIRS,
         per_pair: Optional[int] = None,
         scout_per_brand: Optional[int] = None,
         budget: Optional[float] = None,
         dsn: Optional[str] = None, account_id: Optional[int] = None,
         log: Callable[[str], None] = print,
         gemini_client=None) -> dict:
    """The whole night. Returns the summary that also becomes the row."""
    from . import trigger

    quiet_langsmith(log)
    if sparks is None:
        sparks = trigger.load_sparks()
    limit = per_pair if per_pair is not None else sparks_per_pair()
    if limit and len(sparks) > limit:
        log(f"nightly: walking {limit} of {len(sparks)} sparks per brand "
            f"({SPARKS_ENV} to change)")
        sparks = sparks[:limit]
    if scout_per_brand is None:
        scout_per_brand = int(os.environ.get("SCOUT_PER_BRAND", "8") or 8)
    if budget is None:
        budget = budget_usd()

    started = _now()
    row_id = db.start_nightly_run(dsn)
    if row_id is None:
        log("nightly: could not write the nightly_runs row (the log is the "
            "only record of this walk)")

    report = preflight(dsn, account_id=account_id, gemini_client=gemini_client)
    log(preflight_line(report))

    summary = {"started_at": started, "attempted": 0, "succeeded": 0,
               "held": 0, "failed": 0, "spent_usd": 0.0, "stopped_reason": None,
               "preflight": report, "run_id": row_id}

    if report["stop"]:
        return _close(summary, report["stop"], dsn=dsn, log=log,
                      account_id=account_id, row_id=row_id, started=started)

    if not report["keyframes"]:
        # said once, here, instead of sixteen times as a hold reason
        os.environ["ZEROPAGE_KEYFRAME"] = "0"
        log("nightly: image cap already spent -- running text-only "
            "(ZEROPAGE_KEYFRAME=0); concepts are cheap and still worth having")

    stopped = None
    for channel, brand in pairs:
        if stopped:
            break
        for index, spark in enumerate(sparks):
            spent = _spent(started, dsn, account_id=account_id)
            if spent >= budget:
                stopped = (f"budget: ${spent:.2f} of ${budget:.2f} spent "
                           f"({BUDGET_ENV} to raise)")
                break
            summary["attempted"] += 1
            # None past the quota, not False: those runs express no
            # opinion and let the env flags decide, the same as any
            # other caller that names nothing.
            result = run_one(channel, brand, spark,
                             research=(index < scout_per_brand) or None)
            if result.get("ok"):
                summary["succeeded"] += 1
                if result.get("held"):
                    summary["held"] += 1
                log(f"nightly: {channel}/{brand} ok spark={result.get('spark')!r} "
                    f"held={result.get('held')!r}")
            else:
                summary["failed"] += 1
                kind = result.get("kind") or CONTENT
                log(f"nightly: {channel}/{brand} FAILED ({kind}) "
                    f"spark={spark!r}: {result.get('error')}")
                if kind == SYSTEMIC:
                    stopped = f"systemic failure: {result.get('error')}"
                    break

    return _close(summary, stopped, dsn=dsn, log=log, account_id=account_id,
                  row_id=row_id, started=started)


def _spent(started: str, dsn: Optional[str], *, account_id: Optional[int]) -> float:
    """Dollars since the walk began. A meter that cannot be read reports
    0.0 -- the budget then stops nothing, which is the same night the
    walk had before there was a budget, and better than a night stopped
    at run one by a broken query."""
    from . import costs
    try:
        return float(costs.spent_since(started, dsn, account_id=account_id)["total_usd"])
    except Exception:
        return 0.0


def _close(summary: dict, stopped: Optional[str], *, dsn, log, account_id,
           row_id, started) -> dict:
    """Finish the receipt: the row, the hold, the one-line summary."""
    summary["stopped_reason"] = stopped
    summary["spent_usd"] = _spent(started, dsn, account_id=account_id)
    summary["finished_at"] = _now()
    db.finish_nightly_run(row_id, attempted=summary["attempted"],
                          succeeded=summary["succeeded"], failed=summary["failed"],
                          spent_usd=summary["spent_usd"], stopped_reason=stopped,
                          dsn=dsn)
    if stopped:
        _hold(stopped, dsn=dsn)
    log(f"nightly: attempted={summary['attempted']} "
        f"succeeded={summary['succeeded']} held={summary['held']} "
        f"failed={summary['failed']} spent=${summary['spent_usd']:.2f} "
        f"stopped={stopped!r}")
    return summary


def _hold(reason: str, *, dsn: Optional[str] = None) -> Optional[int]:
    """ONE hold row saying why the night ended early, so the morning
    review finds it where every other outcome is filed. Never raises: the
    breaker usually trips because the database is unreachable, and the
    explanation must not die of the thing it is explaining."""
    try:
        from . import accounts, autonomy
        autonomy.init(dsn)
        return autonomy.to_hold("zeropage", f"nightly stopped: {reason}",
                                dsn=dsn, account_id=accounts.resolve_account(dsn=dsn))
    except Exception:
        return None


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(argv=None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="The nightly walk, with a breaker.")
    parser.add_argument("command", choices=("walk", "preflight", "status"),
                        nargs="?", default="walk")
    parser.add_argument("--budget", type=float, default=None,
                        help=f"dollars for the whole walk (default {BUDGET_ENV} "
                             f"or {DEFAULT_BUDGET_USD:.2f})")
    parser.add_argument("--limit", type=int, default=7,
                        help="how many receipts `status` prints")
    args = parser.parse_args(argv)

    if args.command == "preflight":
        report = preflight()
        print(preflight_line(report))
        return 0 if not report["stop"] else 1

    if args.command == "status":
        for row in db.recent_nightly_runs(args.limit):
            print(f"{row['started_at']} -> {row['finished_at'] or 'UNFINISHED'} "
                  f"attempted={row['attempted']} succeeded={row['succeeded']} "
                  f"failed={row['failed']} spent=${row['spent_usd']:.2f} "
                  f"stopped={row['stopped_reason']!r}")
        return 0

    summary = walk(budget=args.budget)
    # Exit 1 on a stopped walk so a scheduler that reports failures has
    # something to report. A night where every run merely HELD is a
    # success: holding is what shadow mode does.
    return 1 if summary["stopped_reason"] else 0


if __name__ == "__main__":
    sys.exit(main())
