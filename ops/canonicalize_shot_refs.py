"""Rewrite every reference already stored on a shot to its public R2 URL.

The repair half of the canonical-URL change (2026-09-08, Mike: "the
reference photos aren't appearing" -- a Queue card showing four empty
tiles above a scene whose shot carried four refs). The refs were fine;
the URLs were `/characters/michael/photo/...` and `/refs/<sha>.jpg`,
which are true only on the machine holding the folder. characters/,
props/, locations/ and data/refs/ are gitignored AND dockerignored, and
data/ on the deploy is a fresh Fly volume, so the deployed site 404s all
of them -- and a renderer running there reaches for a face it cannot
fetch.

New rows store the canonical URL as they are written
(`asset_shelf.canonical_url`, applied in app/api.py's
`_attach_scene_refs` and `src/scene_chain.attach_refs`). This is the
backlog. Run `ops/backfill_reference_photos_r2.py` first -- it is what
puts the bytes up there.

A ref is rewritten ONLY when its key is really in the bucket
(`storage.key_exists`). "The URL is built from a template" is not
evidence that an object exists, and a local path that works on his Mac
beats an R2 URL that works nowhere; anything left behind is still
served by the R2 redirect on app/main.py's photo routes. Report first,
then write:

    python -m ops.canonicalize_shot_refs                 # report only
    python -m ops.canonicalize_shot_refs --write
    python -m ops.canonicalize_shot_refs --account antihero --write
"""
from __future__ import annotations

import argparse
from pathlib import Path

from dotenv import load_dotenv

from src import accounts, asset_shelf, preprod, storage

# The credentials and the DSN both live in .env, and a one-off run from a
# cron or a bare shell has neither -- without this the script reports "R2
# is not configured" on a machine where it plainly is, which reads as a
# finished pass that changed nothing.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def canonicalize(refs: list, seen: dict) -> tuple:
    """(rewritten refs, missing keys) -- each key checked once a pass."""
    out, missing = [], []
    for ref in refs:
        key = asset_shelf.r2_key(ref)
        if not key:                       # already absolute, or no key
            out.append(ref)
            continue
        if key not in seen:
            seen[key] = storage.key_exists(key)
        if not seen[key]:
            missing.append(ref)
            out.append(ref)
            continue
        out.append(asset_shelf.canonical_url(ref))
    return out, missing


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Store references as public R2 URLs, not local paths.")
    ap.add_argument("--account", help="account slug (default: the oldest)")
    ap.add_argument("--brand", help="antihero | zeropage")
    ap.add_argument("--write", action="store_true",
                    help="actually rewrite; without it this only reports")
    args = ap.parse_args(argv)

    if not storage.configured():
        print("R2 is not configured (see ops/r2-setup.md) -- nothing to do.")
        return 1

    # A one-off ops script has no session, and "nobody" owns no rows
    # after the tenancy backfill (the ops/backfill_scene_refs lesson).
    account_id = accounts.resolve_account(args.account)

    seen: dict = {}
    carried = todo = missing_total = 0
    changes = []
    for concept in preprod.list_concepts(limit=100000, account_id=account_id,
                                         brand=args.brand):
        refs = list(concept.get("refs") or [])
        if not refs:
            continue
        carried += 1
        new, missing = canonicalize(refs, seen)
        missing_total += len(missing)
        for ref in missing:
            print(f"  #{concept['id']}: not in R2, left as-is -- {ref}")
        if new != refs:
            todo += 1
            changes.append((concept["id"], new))

    print(f"{carried} concept(s) carry refs · {todo} to rewrite"
          f" · {missing_total} ref(s) not in the bucket")
    if not args.write:
        print("dry run — pass --write to rewrite")
        return 0

    failed = []
    for concept_id, new in changes:
        try:
            full = preprod.get_concept(concept_id, account_id=account_id)
            shots = [dict(s) for s in full["shots"]]
            shots[0]["refs"] = new
            preprod.update_concept_shots(
                concept_id, {"shots": shots, "duration": full.get("duration")},
                warnings=full.get("warnings") or [], account_id=account_id)
        except Exception as e:        # one bad row never stops the sweep
            failed.append((concept_id, str(e)))
    print(f"rewrote {len(changes) - len(failed)}")
    for concept_id, err in failed:
        print(f"  FAILED {concept_id}: {err}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
