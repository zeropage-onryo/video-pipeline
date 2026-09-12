#!/usr/bin/env python3
"""One-off (safe to re-run): push every reference photo under
characters/, props/, and locations/ up to R2, under the exact key
scheme asset_shelf.photo_url() looks for (2026-09-08, Mike -- these
folders are gitignored AND dockerignored, so a photo saved on this
machine never reaches the deployed Fly site's own disk; R2 gives it one
real URL every machine can load).

Run from the project root, after R2_ACCOUNT_ID / R2_ACCESS_KEY_ID /
R2_SECRET_ACCESS_KEY / R2_BUCKET / R2_PUBLIC_BASE_URL are all set in
.env -- see ops/r2-setup.md. Requires no other setup; reads nothing
from the database, just walks the three folders on disk.
"""
import os
import sys

sys.path.insert(0, os.getcwd())

from dotenv import load_dotenv  # noqa: E402, I001

load_dotenv()

from src import asset_shelf, refbin, storage  # noqa: E402


def main() -> int:
    if not storage.configured():
        print("R2 is not configured (see ops/r2-setup.md) -- nothing to do.")
        return 1

    total = uploaded = failed = 0

    # data/refs/ first: composer uploads and every image the scout has
    # ever downloaded. Same problem as the asset folders (gitignored,
    # dockerignored) plus one more -- data/ on Fly is a fresh volume, so
    # even a deploy that shipped the folder would start empty. refbin
    # mirrors new ones at save time; this is the backlog.
    if refbin.REFS_DIR.is_dir():
        for photo in sorted(p for p in refbin.REFS_DIR.iterdir() if p.is_file()):
            total += 1
            key = f"refs/{photo.name}"
            try:
                url = storage.upload_file(photo, key=key,
                                          content_type="image/jpeg")
                uploaded += 1
                print(f"  OK   {key} -> {url}")
            except Exception as e:
                failed += 1
                print(f"  FAIL {key}: {type(e).__name__}: {e}")

    for plural, directory in asset_shelf.photo_roots().items():
        if not directory.is_dir():
            continue
        for slug_dir in sorted(p for p in directory.iterdir() if p.is_dir()):
            for photo in sorted(p for p in slug_dir.iterdir() if p.is_file()):
                total += 1
                key = f"{plural}/{slug_dir.name}/{photo.name}"
                try:
                    url = storage.upload_file(photo, key=key,
                                              content_type="image/jpeg")
                    uploaded += 1
                    print(f"  OK   {key} -> {url}")
                except Exception as e:
                    failed += 1
                    print(f"  FAIL {key}: {type(e).__name__}: {e}")

    print(f"\n{uploaded}/{total} photos uploaded" + (f", {failed} failed" if failed else ""))
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
