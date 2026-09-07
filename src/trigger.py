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
Since 2026-09-07 a crash is also CLASSIFIED (`nightly.classify_error`):
the hold reason and the exit code say whether the failure was about
this concept or about the world, which is what lets src/nightly.py stop
a walk instead of running fifteen more runs into the same dead socket.
Exit 2 is the systemic one.
"""
import argparse
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


def run_once(spark: str, *, channel: str = "zeropage", brand=None,
             scout: bool = False, research: bool = False) -> dict:
    """One graph run, as a result dict instead of an exit code.

    The shape the nightly runner needs and the CLI wraps: `ok`, the
    `held` reason a shadow run always has, and on a crash the `kind`
    (`nightly.SYSTEMIC` / `CONTENT`) that decides whether the rest of
    the walk is worth attempting. One implementation, so a run fired by
    cron and a run inside the walk cannot behave differently.
    """
    # Imported here, not at module top: orchestrator pulls in the whole
    # generation stack, and `--help` on a cron box shouldn't need it.
    from . import autonomy, nightly, orchestrator

    try:
        result = orchestrator.run(spark, brand=brand, channel=channel,
                                  scout=scout or research, research=research)
    except Exception as e:
        kind = nightly.classify_error(e)
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
    parser.add_argument("--scout", action="store_true",
                        help="use a spark from src.scout's bank, falling back "
                             "to the rotation when it has nothing servable")
    parser.add_argument("--research", action="store_true",
                        help="let the Claude agent fill the bank first (implies "
                             "--scout; no-op without ANTHROPIC_API_KEY)")
    args = parser.parse_args(argv)

    spark = args.spark or pick_spark(load_sparks(), date.today().timetuple().tm_yday)

    outcome = run_once(spark, channel=args.channel, brand=args.brand,
                       scout=args.scout, research=args.research)
    if not outcome["ok"]:
        print(f"trigger: run crashed ({outcome['kind']}): {outcome['error']}",
              file=sys.stderr)
        # 2 is the systemic one: a caller looping over sparks can tell
        # "this concept broke" from "the world is broken" without
        # parsing stderr.
        from . import nightly
        return 2 if outcome["kind"] == nightly.SYSTEMIC else 1

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
