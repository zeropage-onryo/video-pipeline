"""Attach references to concepts written before 2026-08-28.

Those scenes name Michael, the Cyclops and the Ducati and say
"(reference photos on file)" -- because format_cast told the generator
to -- but nothing was attaching the files, so their shots carry no
refs and the Director graph grounds on nothing.

Additive and idempotent: only shots with NO refs are touched, and the
prompt is never rewritten. Run from the project root:

    python -m ops.backfill_scene_refs          # report only
    python -m ops.backfill_scene_refs --write
"""
import sys
from typing import Optional

from app import api
from src import accounts, db, preprod


def main(write: bool, account_id: Optional[int] = None) -> int:
    # A one-off ops script has no session. Without this it acts as
    # nobody, and after the tenancy backfill nobody owns no rows --
    # so it would report zero work and look like a clean run.
    if account_id is None:
        account_id = accounts.resolve_account()
    touched = 0
    for concept in preprod.list_concepts(limit=1000, path=db.DB_PATH, account_id=account_id):
        shots = concept.get("shots") or []
        if not shots or shots[0].get("refs"):
            continue
        text = " ".join(str(shots[0].get(k) or "")
                        for k in ("desc", "prompt", "location"))
        found = api._auto_refs(text, [])
        if not found:
            print(f"  SHOOT-{concept['id']:02d} {concept['title'][:34]:<36} "
                  f"— names no asset with photos")
            continue
        print(f"  SHOOT-{concept['id']:02d} {concept['title'][:34]:<36} "
              f"— {', '.join(r.split('/')[2] for r in found)}")
        if write:
            api._attach_scene_refs(concept["id"], [])
        touched += 1
    print(f"\n{touched} concept(s) {'updated' if write else 'would be updated'}")
    return touched


if __name__ == "__main__":
    main("--write" in sys.argv)
