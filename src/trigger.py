#!/usr/bin/env python3
"""
The scheduled trigger -- fires a shadow run on a schedule instead of a
click. Build-order step 5: autonomous *creation*, posting still gated.

    venv/bin/python -m src.trigger                # tonight's spark, rotated
    venv/bin/python -m src.trigger --spark "..."  # explicit direction

The spark rotates through prompts/sparks.txt by day of year, so
consecutive nights get different directions with nobody typing. The run
itself goes through the full content graph and -- with render/publish
stubbed and both channels in shadow -- always ends as a hold_queue row.
The morning ritual on /holds (approve/reject) is what grades the
evaluator; this just keeps the queue fed.

Exit 0 with the hold row printed, exit 1 on anything unexpected -- a
cron/launchd line has no one watching stderr, so the outcome lands in
the dead-man log either way (even a crashed run writes a hold row).
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
    args = parser.parse_args(argv)

    spark = args.spark or pick_spark(load_sparks(), date.today().timetuple().tm_yday)

    # Imported here, not at module top: orchestrator pulls in the whole
    # generation stack, and `--help` on a cron box shouldn't need it.
    from . import autonomy, db, orchestrator

    try:
        result = orchestrator.run(spark, brand=args.brand, channel=args.channel)
    except Exception as e:
        # the dead-man log gets the crash too -- a silent night looks
        # exactly like a healthy night unless failures leave a row
        autonomy.init(path=db.DB_PATH)
        autonomy.to_hold(args.channel, f"trigger crashed: {e}", path=db.DB_PATH)
        print(f"trigger: run crashed: {e}", file=sys.stderr)
        return 1

    print(f"trigger: spark={spark!r} channel={args.channel} "
          f"attempts={result.get('attempts')} "
          f"concept_id={result.get('concept_id')} "
          f"hold_id={result.get('hold_id')} "
          f"held={result.get('held_reason')!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
