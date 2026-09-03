"""Attach references to concepts whose shots carry none.

Those scenes name Michael, the Cyclops and the Ducati and say
"(reference photos on file)" -- because format_cast told the generator
to -- but nothing was attaching the files, so their shots carry no
refs and the Director graph grounds on nothing.

Additive and idempotent: only shots with NO refs are touched, and the
prompt is never rewritten. Run from the project root:

    python -m ops.backfill_scene_refs                    # report only
    python -m ops.backfill_scene_refs --write
    python -m ops.backfill_scene_refs --account antihero --write
"""
import sys
from typing import Optional

from app import api
from src import accounts, preprod


def main(write: bool, account_id: Optional[int] = None) -> int:
    # A one-off ops script has no session. Without this it acts as
    # nobody, and after the tenancy backfill nobody owns no rows --
    # so it would report zero work and look like a clean run.
    if account_id is None:
        account_id = accounts.resolve_account()
    touched = 0
    failed = 0
    for concept in preprod.list_concepts(limit=1000,
                                         account_id=account_id):
        shots = concept.get("shots") or []
        if not shots or shots[0].get("refs"):
            continue
        text = " ".join(str(shots[0].get(k) or "")
                        for k in ("desc", "prompt", "location"))
        # account_id is REQUIRED here, not decorative. _auto_refs ->
        # _assets_all -> entities.list_* is `WHERE account_id IS ?`, so
        # None matches only unowned rows -- which, after the tenancy
        # pass, is nothing at all. Omitting it reproduced the exact bug
        # this script exists to repair: every scene "names no asset"
        # and the run looks clean (2026-09-01).
        found = api._auto_refs(text, [], account_id)
        title = (concept.get("title") or "untitled")[:34]
        if not found:
            print(f"  SHOOT-{concept['id']:02d} {title:<36} "
                  f"— names no asset with photos")
            continue
        print(f"  SHOOT-{concept['id']:02d} {title:<36} "
              f"— {', '.join(r.split('/')[2] for r in found)}")
        if write:
            # Count what was STORED, never what was matched.
            # _attach_scene_refs re-reads the concept under account_id
            # and returns [] when that read comes back empty, so
            # counting the match would print "15 updated" over a total
            # no-op -- the silent success this repo keeps paying for.
            if not api._attach_scene_refs(concept["id"], [], account_id):
                print(f"       !! NOT STORED — concept {concept['id']} "
                      f"unreadable as account {account_id}")
                failed += 1
                continue
        touched += 1
    print(f"\n{touched} concept(s) {'updated' if write else 'would be updated'}")
    if failed:
        print(f"{failed} matched but FAILED to store — fix before re-running")
    return touched


if __name__ == "__main__":
    argv = sys.argv[1:]
    slug = argv[argv.index("--account") + 1] if "--account" in argv else None
    main("--write" in argv,
         accounts.resolve_account(slug) if slug else None)
