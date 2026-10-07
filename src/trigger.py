#!/usr/bin/env python3
"""
The scheduled trigger -- fires a shadow run on a schedule instead of a
click. Build-order step 5: autonomous *creation*, posting still gated.

    venv/bin/python -m src.trigger                # tonight's spark, rotated
    venv/bin/python -m src.trigger --spark "..."  # explicit direction
    venv/bin/python -m src.trigger --scout        # a spark the scout crawled for
    venv/bin/python -m src.trigger --research     # let Claude research one first

The spark rotates through prompts/sparks.txt by day of year, so
consecutive nights get different directions with nobody typing.
`--scout` asks src/scout.py's bank for a researched direction instead;
the rotation is still computed and passed, because it is what the run
falls back to when the bank is empty or thin (see orchestrator.scout). The run
itself goes through the full content graph and -- with render/publish
stubbed and both channels in shadow -- always ends as a hold_queue row.
The morning ritual on /holds (approve/reject) is what grades the
evaluator; this just keeps the queue fed.

Exit 0 with the hold row printed, exit 1 on anything unexpected -- a
cron/launchd line has no one watching stderr, so the outcome lands in
the dead-man log either way (even a crashed run writes a hold row).
Since 2026-09-07 a crash is also CLASSIFIED (`classify_error`): the
hold reason and the exit code say whether the failure was about this
concept or about the world, so a caller looping over sparks can stop
instead of running fifteen more runs into the same dead socket. Exit 2
is the systemic one. (The nightly walk that was that caller,
src/nightly.py, was deleted 2026-10-07, Mike's call.)
"""
import argparse
import socket
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SPARKS_PATH = PROJECT_ROOT / "prompts" / "sparks.txt"


def load_sparks(path: Path = SPARKS_PATH) -> list:
    """Non-empty, non-comment lines. Missing file -> empty list, and the
    caller falls back to a generic spark rather than dying."""
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return []
    return [ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")]


def pick_spark(sparks: list, day: int) -> str:
    """Deterministic rotation: same night, same spark -- a re-run after a
    crash produces the same direction, not a surprise second slate."""
    if not sparks:
        return "tonight's shadow slate"
    return sparks[day % len(sparks)]


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
    """SYSTEMIC (the world is broken) or CONTENT (this concept is).

    Order matters. A Postgres deadlock arrives as an OperationalError,
    the same class a dead socket does, so the content markers are read
    FIRST -- otherwise one unlucky transaction would look like a broken
    database. Everything unrecognised is CONTENT: erring that way costs
    one wasted run, and erring the other way stops a loop on an
    exception nobody has seen yet.
    """
    from . import gemini_utils  # pulls in google-genai; --help needn't

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


def run_once(spark: str, *, channel: str = "zeropage", brand=None,
             scout=None, research=None, brain=None) -> dict:
    """One graph run, as a result dict instead of an exit code.

    The shape the CLI wraps: `ok`, the `held` reason a shadow run
    always has, and on a crash the `kind` (`SYSTEMIC` / `CONTENT`) that
    says whether another run is worth attempting.
    """
    # Imported here, not at module top: orchestrator pulls in the whole
    # generation stack, and `--help` on a cron box shouldn't need it.
    from . import autonomy, orchestrator

    try:
        # Tri-state, passed through rather than collapsed: None means
        # "no flag was given", which is what lets ZEROPAGE_GRAPH_SCOUT /
        # _RESEARCH turn the pair on for a cron run that names nothing.
        # Collapsing it to False here (`scout or research`) would have
        # made this the one caller the env could never reach.
        if scout is None and research:
            scout = True
        result = orchestrator.run(spark, brand=brand, channel=channel,
                                  scout=scout, research=research, brain=brain)
    except Exception as e:
        kind = classify_error(e)
        # the dead-man log gets the crash too -- a silent night looks
        # exactly like a healthy night unless failures leave a row. The
        # write itself is best-effort: a systemic crash is usually the
        # database, and the explanation must not die of the thing it is
        # explaining.
        try:
            autonomy.init()
            from . import accounts
            autonomy.to_hold(channel, f"trigger crashed ({kind}): {e}",
                             account_id=accounts.resolve_account())
        except Exception:
            pass
        return {"ok": False, "kind": kind, "error": str(e), "spark": spark}

    return {
        "ok": True,
        "kind": None,
        # the spark the run actually used, which --scout may have replaced
        "spark": result.get("spark") or spark,
        "held": result.get("held_reason"),
        "result": result,
    }


def main(argv=None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(
        description="Fire one shadow run through the content graph."
    )
    parser.add_argument("--spark", default=None,
                        help="explicit direction; default rotates prompts/sparks.txt")
    parser.add_argument("--channel", default="zeropage")
    # No hardcoded default here on purpose -- orchestrator.run() defaults an
    # omitted brand to match --channel, so "channel set, brand not" can no
    # longer silently generate the wrong brand's content under the other
    # channel's label (see run()'s docstring; this is what produced
    # hold_queue row 13 / concept 111 on 2026-08-14). Pass --brand
    # explicitly only when you actually want it to differ from --channel.
    parser.add_argument("--brand", default=None)
    # default=None, not False: an absent flag means "no opinion" and
    # defers to ZEROPAGE_GRAPH_SCOUT / ZEROPAGE_GRAPH_RESEARCH. --no-scout
    # / --no-research are the way to force them off for one run.
    parser.add_argument("--scout", action="store_true", default=None,
                        help="use a spark from src.scout's bank, falling back "
                             "to the rotation when it has nothing servable "
                             "(default: ZEROPAGE_GRAPH_SCOUT)")
    parser.add_argument("--no-scout", dest="scout", action="store_false",
                        help="keep the spark passed in, whatever the env says")
    parser.add_argument("--research", action="store_true", default=None,
                        help="let the Claude agent fill the bank first (implies "
                             "--scout; no-op without ANTHROPIC_API_KEY; "
                             "default: ZEROPAGE_GRAPH_RESEARCH)")
    parser.add_argument("--no-research", dest="research", action="store_false",
                        help="skip the agent for this run")
    # None, not "fast": an unnamed tier is what lets ZEROPAGE_BRAIN
    # decide (orchestrator.brain_default), the same tri-state shape
    # --scout/--research use. A walk is ten runs, so naming `reasoning`
    # here is a bill somebody chose.
    parser.add_argument("--brain", default=None,
                        help="model tier for the writer: fast (default) or reasoning")
    args = parser.parse_args(argv)

    spark = args.spark or pick_spark(load_sparks(), date.today().timetuple().tm_yday)

    outcome = run_once(spark, channel=args.channel, brand=args.brand,
                       scout=args.scout, research=args.research,
                       brain=args.brain)
    if not outcome["ok"]:
        print(f"trigger: run crashed ({outcome['kind']}): {outcome['error']}",
              file=sys.stderr)
        # 2 is the systemic one: a caller looping over sparks can tell
        # "this concept broke" from "the world is broken" without
        # parsing stderr.
        return 2 if outcome["kind"] == SYSTEMIC else 1

    result = outcome["result"]
    used = outcome["spark"]
    print(f"trigger: spark={used!r} channel={args.channel} "
          f"attempts={result.get('attempts')} "
          f"concept_id={result.get('concept_id')} "
          f"hold_id={result.get('hold_id')} "
          f"held={result.get('held_reason')!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
