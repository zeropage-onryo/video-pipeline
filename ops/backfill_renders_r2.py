#!/usr/bin/env python3
"""One-off (safe to re-run): find every generated_assets row still
pointing at a bare local path (e.g. "/renders/nano/xyz.png" -- only
ever resolvable on the machine that rendered it, per the pre-R2
fallback in nano_banana.py and friends), upload the file at that row's
`output_path` to R2, and repoint media_url at the public URL that comes
back (2026-09-08, Mike -- this is why "Generated: 61" showed the right
count with every tile blank on the deployed site: the rows are in a
shared database, the files were never anywhere but this Mac).

Run from the project root, after R2 is configured (see ops/r2-setup.md)
and from the SAME machine the renders were made on (it needs to read
`output_path` off local disk) -- for most of this project so far,
that's this Mac.
"""
import os
import sys

sys.path.insert(0, os.getcwd())

from dotenv import load_dotenv  # noqa: E402, I001

load_dotenv()

from src import db, render_assets, storage  # noqa: E402


def _local_rows(dsn=None):
    """Every row whose media_url is a bare path (starts with "/") rather
    than a real URL -- that's the tell for "never uploaded to R2",
    regardless of which account it belongs to (unlike render_assets.
    list_all, this isn't scoped to one account -- a backfill has to see
    everyone's).

    It selects `account_id` for one reason: the UPDATE that follows is
    scoped to it. The read spans accounts, the write never does -- which
    is why this SELECT is the only statement of the pair named in
    tests/test_tenancy.py's UNSCOPED_ALLOWED."""
    render_assets.init(dsn)
    with db.connect(dsn) as conn:
        return conn.execute(
            "SELECT id, media_url, output_path, account_id FROM generated_assets "
            "WHERE media_url LIKE '/%' ORDER BY id"
        ).fetchall()


def main() -> int:
    if not storage.configured():
        print("R2 is not configured (see ops/r2-setup.md) -- nothing to do.")
        return 1

    rows = _local_rows()
    if not rows:
        print("No local-path renders found -- nothing to backfill.")
        return 0

    total = uploaded = missing = failed = 0
    for row in rows:
        total += 1
        output_path = row.get("output_path")
        if not output_path or not os.path.isfile(output_path):
            missing += 1
            print(f"  SKIP id={row['id']}: no file at output_path={output_path!r} "
                  f"on this machine (run this from the machine that made it)")
            continue
        key = row["media_url"].lstrip("/")  # "renders/nano/xyz.png"
        try:
            url = storage.upload_file(output_path, key=key)
            render_assets.update_media_url(row["id"], url,
                                           account_id=row["account_id"])
            uploaded += 1
            print(f"  OK   id={row['id']} {row['media_url']} -> {url}")
        except Exception as e:
            failed += 1
            print(f"  FAIL id={row['id']}: {type(e).__name__}: {e}")

    print(f"\n{uploaded}/{total} renders repointed at R2"
          + (f", {missing} missing locally" if missing else "")
          + (f", {failed} failed" if failed else ""))
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
