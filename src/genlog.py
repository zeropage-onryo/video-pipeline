#!/usr/bin/env python3
"""
Log generation attempts after you've actually generated in the tool's
own UI. Deliberately thin: rendering the prompt (promptgen.py) is where
the reusable work is; this just records the decision you already made
-- kept, or rejected with a reason. No generation APIs are called here.
"""
import argparse

from . import db
from . import generative as gen
from .shot import TOOLS

REJECT_REASONS = (
    "morphing", "wrong_lighting", "camera_ignored", "subject_wrong",
    "artefacts", "other",
)


def main(argv=None, db_path=None):
    parser = argparse.ArgumentParser(
        description="Log a generation attempt: record one, then mark it kept or rejected."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_record = sub.add_parser("record", help="Log one attempt against a shot")
    p_record.add_argument("shot_id", type=int)
    p_record.add_argument("tool", choices=TOOLS)
    p_record.add_argument("prompt")
    p_record.add_argument("--output-path", default=None)
    p_record.add_argument("--cost-usd", type=float, default=None)
    p_record.add_argument("--notes", default=None)

    p_keep = sub.add_parser("keep", help="Mark a generation as the keeper")
    p_keep.add_argument("generation_id", type=int)
    p_keep.add_argument("--output-path", default=None)

    p_reject = sub.add_parser("reject", help="Mark a generation as rejected, with a reason")
    p_reject.add_argument("generation_id", type=int)
    p_reject.add_argument("reason", choices=REJECT_REASONS)

    args = parser.parse_args(argv)
    kwargs = {"path": db_path} if db_path is not None else {}

    db.init_db(**kwargs)
    gen.init(**kwargs)

    if args.command == "record":
        generation_id = gen.record_generation(
            args.shot_id, args.tool, args.prompt,
            output_path=args.output_path, cost_usd=args.cost_usd, notes=args.notes,
            **kwargs,
        )
        print(f"Recorded generation {generation_id} ({args.tool}, shot {args.shot_id})")

    elif args.command == "keep":
        gen.mark_kept(args.generation_id, output_path=args.output_path, **kwargs)
        print(f"Marked generation {args.generation_id} kept")

    elif args.command == "reject":
        gen.mark_rejected(args.generation_id, args.reason, **kwargs)
        print(f"Marked generation {args.generation_id} rejected ({args.reason})")


if __name__ == "__main__":
    main()
