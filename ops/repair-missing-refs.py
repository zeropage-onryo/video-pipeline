"""One-off: repair concepts whose prompt cites @Image N but has no refs.

WHY THESE EXIST. `scene_chain.attach_refs` closes the loop `format_cast`
opens -- the writer is told Michael has "reference photos on file", says
so in the prompt as "@Image 1", and something has to actually attach the
file. The Studio path closed this on 2026-08-28 and the graph on
2026-08-31; every concept written before its own path was fixed is still
sitting in the Queue citing images that resolve to nothing. Approving one
buys a clip that cannot hold the likeness it is built around.

WHY ZERO PAGE ROWS ARE NOT REPAIRED. Attaching Michael's face to a Zero
Page concept would make the render match a prompt that should never have
named him (see shootgen.CAST_BRANDS, 2026-09-01). Those are not broken
references, they are off-brand concepts -- so they get archived with a
reason instead, which is the negative signal the Grade tab collects.

    venv/bin/python ops/repair-missing-refs.py --dry-run
    venv/bin/python ops/repair-missing-refs.py
"""
import argparse
import re
import sys
from pathlib import Path as _P

# Run as `venv/bin/python ops/<name>.py` from anywhere: the repo root
# is not on sys.path unless the project happens to be pip-installed.
sys.path.insert(0, str(_P(__file__).resolve().parent.parent))

from src import accounts, preprod, scene_chain

CITES = re.compile(r"@Image\s*\d+")


def find(path, account_id):
    broken = []
    for concept in preprod.list_concepts(limit=1000, dsn=path, account_id=account_id):
        shots = concept.get("shots") or []
        if not shots:
            continue
        prompt = shots[0].get("prompt") or ""
        if CITES.search(prompt) and not (shots[0].get("refs") or []):
            broken.append(concept)
    return broken


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    account_id = accounts.resolve_account()
    broken = find(None, account_id)
    if not broken:
        print("nothing to repair")
        return 0

    for concept in broken:
        cid, brand, title = concept["id"], concept["brand"], concept["title"][:34]
        if brand == "zeropage":
            if args.dry_run:
                print(f"  [{cid}] {title:34} zeropage -> would archive (off-brand)")
                continue
            preprod.set_archived(cid, account_id=account_id,
                                 reason="off-brand")
            print(f"  [{cid}] {title:34} archived (off-brand) — row kept")
        else:
            if args.dry_run:
                print(f"  [{cid}] {title:34} {brand} -> would attach refs")
                continue
            refs = scene_chain.attach_refs(cid, [], db_path=None,
                                           account_id=account_id)
            anchor = refs[0] if refs else "NONE — nothing matched, left as-is"
            print(f"  [{cid}] {title:34} {len(refs)} refs, anchor {anchor}")

    if not args.dry_run:
        print("\ntally now:", preprod.reason_counts(account_id=account_id))
    return 0


if __name__ == "__main__":
    sys.exit(main())
