"""Take every ungrounded concept off the board.

The repair half of the reference gate (2026-09-08, Mike's call). The
gate itself runs at the two writers -- `scene_chain.run` for a Studio
Create, `orchestrator.gen_concept` for the nightly graph -- so from now
on a scene with no reference photos never reaches the board. This is
what clears the rows written BEFORE it existed: on the morning it was
built, 87 of 152 live concepts carried `refs: 0`, most of them parked in
the Queue behind cards reading "KEYFRAMED · AWAITING APPROVAL" -- which
they were, on a still Nano had drawn from the prompt rather than from
any photograph.

WHAT IT WILL NOT TOUCH, on purpose:

  - anything already archived. Re-archiving would overwrite the reason
    somebody typed ("weak concept") with a machine one, and those six
    words are the only record of why anything was rejected.
  - anything marked SHOT. That concept is a video that exists. Grounding
    is a question about what to make next, and a made thing is past it.
  - anything PICKED, unless --picked is passed. A pick is a human saying
    this one is worth it; quietly archiving it out from under him is how
    a cleanup script becomes something you stop trusting. Reported
    instead, so the decision stays his.

Archiving hides, it never deletes -- so the rows keep counting and keep
teaching the grade queue, and `--undo` puts back exactly what this put
away. Report first, then write:

    python -m ops.archive_ungrounded                     # report only
    python -m ops.archive_ungrounded --write
    python -m ops.archive_ungrounded --account antihero --write
    python -m ops.archive_ungrounded --undo --write      # put them back
"""
from __future__ import annotations

import argparse
from typing import Optional

from src import accounts, preprod


def _scan(account_id: Optional[int], brand: Optional[str], picked: bool):
    """(to_archive, skipped_picked, skipped_shot, grounded) as id lists."""
    to_archive, was_picked, was_shot, grounded = [], [], [], []
    for concept in preprod.list_concepts(limit=100000, account_id=account_id,
                                         brand=brand):
        if concept.get("archived"):
            continue                     # keep the reason somebody typed
        if preprod.reference_gate(concept) is None:
            grounded.append(concept["id"])
            continue
        if concept.get("shot_done"):
            was_shot.append(concept["id"])
            continue
        if concept.get("picked") and not picked:
            was_picked.append(concept["id"])
            continue
        to_archive.append(concept["id"])
    return to_archive, was_picked, was_shot, grounded


def _undone(account_id: Optional[int], brand: Optional[str]) -> list[int]:
    """The ids THIS script archived -- identified by the machine reason,
    never by 'archived and ungrounded'. Undo has to put back exactly what
    was put away: a concept Michael archived as 'off-brand' that also
    happens to carry no photos is not this script's to restore."""
    return [c["id"] for c in preprod.list_concepts(
        limit=100000, account_id=account_id, brand=brand)
        if c.get("archived") and c.get("archive_reason") in preprod.MACHINE_REASONS]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Archive concepts with no reference photos attached.")
    ap.add_argument("--account", help="account slug (default: the oldest)")
    ap.add_argument("--brand", help="antihero | zeropage")
    ap.add_argument("--write", action="store_true",
                    help="actually archive; without it this only reports")
    ap.add_argument("--picked", action="store_true",
                    help="also archive concepts you had picked")
    ap.add_argument("--undo", action="store_true",
                    help="put back what this script archived")
    args = ap.parse_args(argv)

    # A one-off ops script has no session, and after the tenancy backfill
    # "nobody" owns no rows -- so without this it reports zero work and
    # looks like a clean run (the ops/backfill_scene_refs lesson).
    account_id = accounts.resolve_account(args.account)

    if args.undo:
        ids = _undone(account_id, args.brand)
        print(f"{len(ids)} archived for '{preprod.NO_REFERENCE}'")
        if not args.write:
            print("dry run — pass --write to put them back")
            return 0
        for concept_id in ids:
            preprod.set_archived(concept_id, False, account_id=account_id)
        print(f"restored {len(ids)}")
        return 0

    to_archive, was_picked, was_shot, grounded = _scan(
        account_id, args.brand, args.picked)
    print(f"{len(grounded)} grounded · {len(to_archive)} to archive"
          f" · {len(was_picked)} picked, left alone"
          f" · {len(was_shot)} already shot, left alone")
    if was_picked:
        print("  picked but ungrounded (pass --picked to include): "
              + ", ".join(str(i) for i in was_picked))
    if was_shot:
        print("  shot but ungrounded: " + ", ".join(str(i) for i in was_shot))
    if not args.write:
        print("dry run — pass --write to archive")
        return 0

    failed = []
    for concept_id in to_archive:
        try:
            preprod.set_archived(concept_id, True, account_id=account_id,
                                 reason=preprod.NO_REFERENCE)
        except Exception as e:           # one bad row never stops the sweep
            failed.append((concept_id, str(e)))
    print(f"archived {len(to_archive) - len(failed)}")
    for concept_id, err in failed:
        print(f"  FAILED {concept_id}: {err}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
