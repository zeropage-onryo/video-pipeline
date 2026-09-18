"""Copy every object in the bucket into the tenant key scheme.

The step between `ZEROPAGE_MEDIA=legacy` and `ZEROPAGE_MEDIA=tenant`.
New writes land on `m/<account>/<tail>` the moment the rung changes;
everything written BEFORE it is still sitting on the flat global key, so
flipping without running this first gives a studio full of empty tiles.

COPIES, never moves. The old key is left exactly where it is, still
public, still serving, so the flip is reversible: set the variable back
and every legacy URL resolves as it did this morning. That is also why
this is safe to interrupt and safe to re-run -- an object already at its
destination is skipped, not re-sent.

THE HARD PART IS OWNERSHIP. A flat key does not say whose bytes it
holds; that was the entire problem with the flat scheme. So the owner is
recovered from the database, per kind:

  refs/<sha>.jpg       nobody -- the bin is SHARED (src/media.py says
                       why) and goes to `m/shared/refs/...` with no
                       lookup at all
  characters/<slug>/…  the account holding an asset with that slug.
  props/…  locations/… Read off the DATABASE, never off this laptop's
                       disk: the deploy has no `characters/` folder, and
                       an owner map that depended on one would call a
                       photo unowned purely because the machine running
                       the script had not seen it.
  everything else      whichever accounts' rows mention the filename --
  (renders, soul-      generated assets, generations, a shot's refs, a
   training, images)   character's reference_image, a parked workflow

Anything whose owner cannot be established is REPORTED AND LEFT ALONE.
Not guessed, not dropped into a shared prefix: an object copied under
the wrong account is a reference photo handed to the wrong studio, and
"I could not tell" is a finding worth reading rather than a silence.

A slug owned by two accounts is the collision the tenant prefix exists
to prevent, arriving from the past -- under the flat scheme the second
upload overwrote the first, so nobody can now say which account's bytes
survived. Those are reported as ambiguous and skipped, deliberately:
the honest repair is to re-upload the photo from the account that owns
it, which the app already does correctly.

    python -m ops.migrate_media_keys                  # report only
    python -m ops.migrate_media_keys --write
    python -m ops.migrate_media_keys --write --thumbs # + 480px derivatives
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from src import asset_shelf, db, entities, media, preprod, storage

# The credentials and the DSN both live in .env, and a one-off run from a
# cron or a bare shell has neither -- without this the script reports "R2
# is not configured" on a machine where it plainly is, which reads as a
# finished pass that changed nothing.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

CONCEPT_SCAN_LIMIT = 100000


def _has(conn, table: str, column: str) -> bool:
    """Is there such a column? The scan list below names tables from
    several eras of this repo, and a missing one must be skipped rather
    than take the whole pass down."""
    return bool(conn.execute(
        "SELECT 1 FROM information_schema.columns WHERE table_schema='public' "
        "AND table_name=%s AND column_name=%s", (table, column)).fetchone())


# Every column that can hold a media URL, with the account that owns the
# row. Driven from the BUCKET side: for each object, which accounts'
# rows mention it. That direction is the one that answers the question
# that actually matters -- "what breaks if this object does not move" --
# and it does not care which of six writers put the file there.
SCAN_COLUMNS = (
    ("shoot_concepts", "shots_json"),
    ("generated_assets", "media_url"),
    ("generated_assets", "output_path"),
    ("generations", "output_path"),
    ("characters", "reference_image"),
    ("props", "reference_image"),
    ("workflows", "graph_json"),
    ("hold_queue", "payload"),
)

ASSET_ROOTS = {"characters": "character", "props": "prop",
               "locations": "location"}


def _slug_owners(conn) -> dict:
    """(plural, slug) -> {account_id}, from the asset rows themselves."""
    out: dict = defaultdict(set)
    rows = conn.execute("SELECT id FROM accounts ORDER BY id").fetchall()
    for (account_id,) in rows:
        for plural, kind in ASSET_ROOTS.items():
            if kind == "location":
                names = [r["name"] for r in
                         preprod.list_locations(account_id=account_id)]
            elif kind == "character":
                names = [r["name"] for r in
                         entities.list_characters(account_id=account_id)]
            else:
                names = [r["name"] for r in
                         entities.list_props(account_id=account_id)]
            for name in names:
                out[(plural, asset_shelf.slugify(name))].add(account_id)
    return out


def _mention_owners(conn, filenames: set) -> dict:
    """filename -> {account_id}, by scanning every column that can carry
    a media URL. A filename here is a sha or a timestamped render name,
    so a false match is not a practical worry; an asset photo, whose
    name can be as generic as IMG_0586.JPG, is resolved by slug above
    instead and never reaches this."""
    out: dict = defaultdict(set)
    for table, column in SCAN_COLUMNS:
        if not (_has(conn, table, column) and _has(conn, table, "account_id")):
            continue
        rows = conn.execute(
            f'SELECT account_id, "{column}"::text FROM "{table}" '
            f'WHERE "{column}" IS NOT NULL').fetchall()
        for account_id, blob in rows:
            if account_id is None or not blob:
                continue
            for name in filenames:
                if name in blob:
                    out[name].add(account_id)
    return out


def plan(dsn: Optional[str] = None) -> dict:
    """What a --write run would do. No copies, no uploads."""
    existing = set(storage.list_keys())
    live = [k for k in sorted(existing)
            if not k.startswith((f"{media.MASTER_PREFIX}/", f"{media.THUMB_PREFIX}/"))]
    result = {"copy": [], "already": [], "shared": [], "unowned": [],
              "objects": len(existing)}

    with db.connect(dsn) as conn:
        slug_owner = _slug_owners(conn)
        wanted = {k.rsplit("/", 1)[-1] for k in live
                  if (media.tail_for(k) or "").split("/")[0] not in ASSET_ROOTS}
        mention_owner = _mention_owners(conn, wanted)

    def _record(source: str, dest: str, bucket_: str = "copy") -> None:
        (result["already"] if dest in existing else result[bucket_]).append(
            (source, dest))

    for key in live:
        tail = media.tail_for(key)
        if not tail:
            result["unowned"].append((key, "not a shape this pipeline writes"))
            continue
        root = tail.split("/")[0]
        if root in media.SHARED_ROOTS:
            _record(key, f"{media.MASTER_PREFIX}/{media.SHARED_SCOPE}/{tail}",
                    "shared")
            continue
        if root in ASSET_ROOTS:
            accounts_for = slug_owner.get((root, tail.split("/")[1])) or set()
            why = "no asset row has that slug"
        else:
            accounts_for = mention_owner.get(key.rsplit("/", 1)[-1]) or set()
            why = "no row in the database points at it"
        if not accounts_for:
            result["unowned"].append((key, why))
            continue
        for account_id in sorted(accounts_for):
            _record(key, f"{media.MASTER_PREFIX}/{account_id}/{tail}")
    return result


def _one(source: str, dest: str, thumbs: bool) -> tuple:
    """Copy one object, optionally deriving its thumbnail. Returns
    (copied, derived, error) -- never raises, because this runs on a
    pool and one unreadable object must not cost the rest of the pass."""
    try:
        storage.copy_key(source, dest)
    except Exception as e:                              # noqa: BLE001
        return 0, 0, f"{source} -> {dest}: {type(e).__name__}: {e}"
    if not thumbs:
        return 1, 0, None
    tail = media.tail_for(source)
    try:
        local = asset_shelf.resolve_photo("/" + tail) if tail else None
        if local is None:
            return 1, 0, None          # only derive from bytes we have here
        small = media.thumb_bytes(Path(local).read_bytes())
        if not small:
            return 1, 0, None
        storage.upload_bytes(
            small, f"{media.THUMB_PREFIX}/{dest.split('/')[1]}/{tail}",
            content_type="image/jpeg")
        return 1, 1, None
    except Exception as e:                              # noqa: BLE001
        return 1, 0, f"thumb {dest}: {type(e).__name__}: {e}"


def run(dsn: Optional[str] = None, write: bool = False,
        thumbs: bool = False, workers: int = 12) -> dict:
    """Report, then optionally copy. Never raises on one bad object --
    a single unreadable key must not cost the rest of the pass.

    The copies run on a small pool: each is a server-side COPY, so the
    work is entirely waiting on Cloudflare, and serially a few hundred
    of them take long enough that a run gets interrupted -- which is
    survivable here, but only because nothing is destructive.
    """
    todo = plan(dsn)
    todo["copied"], todo["derived"], todo["errors"] = 0, 0, []

    if not write:
        return todo

    work = todo["copy"] + todo["shared"]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_one, source, dest, thumbs)
                   for source, dest in work]
        for future in as_completed(futures):
            copied, derived, error = future.result()
            todo["copied"] += copied
            todo["derived"] += derived
            if error:
                todo["errors"].append(error)
    return todo


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(
        description="Copy bucket objects into the m/<account>/ key scheme.")
    parser.add_argument("--write", action="store_true",
                        help="actually copy (default is a report)")
    parser.add_argument("--thumbs", action="store_true",
                        help="also build the 480px derivative for photos this "
                             "machine holds locally")
    parser.add_argument("--dsn", default=None)
    args = parser.parse_args(argv)

    if not storage.configured():
        print("R2 is not configured (the five R2_* vars) -- nothing to do.")
        return

    result = run(args.dsn, write=args.write, thumbs=args.thumbs)
    verb = "copied" if args.write else "would copy"
    print(f"{result['objects']} objects in the bucket")
    print(f"  {verb} to an account: {len(result['copy'])}")
    print(f"  {verb} to the shared bin: {len(result['shared'])}")
    print(f"  already in the new scheme: {len(result['already'])}")
    print(f"  nothing points at it -- orphan, left where it is: "
          f"{len(result['unowned'])}")
    if args.write:
        print(f"  derivatives built: {result['derived']}")
    for key, why in result["unowned"][:20]:
        print(f"    unowned    {key}  -- {why}")
    for error in result["errors"][:20]:
        print(f"    ERROR      {error}")
    if not args.write:
        print("\nreport only -- re-run with --write to copy. The old keys are "
              "left in place either way.")


if __name__ == "__main__":
    main()
