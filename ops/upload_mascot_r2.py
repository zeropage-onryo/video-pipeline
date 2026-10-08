"""Push the assistant mascot's images to R2 (docs/ASSISTANT_AVATARS.md).

The studio draws them from `site/mascot/<version>/<size>/<look>-<colour>-<mood>.webp`
(web/src/lib/mascot.ts MASCOT_BASE). The images are made outside the repo
(data/_scratch_mascot/cutx/export.py); this only uploads a finished export.

    venv/bin/python -m ops.upload_mascot_r2 <export dir> [--version v1] [--write]

Reports first: what is missing, what is already in the bucket. With --write it
uploads every image not already there. It refuses a set that is not whole
(483 names x 2 sizes, read off the export's manifest.json), because a studio
pointed at a half-uploaded version draws broken tiles. Redoing an image means a
new --version, never an overwrite: a browser may hold the old one for a long time.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src import storage

SIZES = (128, 320)


def expected(manifest: dict) -> list[str]:
    moods = manifest["moods"]
    return [f"{look}-{colour}-{mood}"
            for look, spec in manifest["looks"].items()
            for colour in spec["colours"] for mood in moods]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("export_dir", type=Path)
    ap.add_argument("--version", default="v1")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv)

    manifest = json.loads((args.export_dir / "manifest.json").read_text())
    names = expected(manifest)
    missing = [f"{s}/{n}.webp" for s in SIZES for n in names
               if not (args.export_dir / str(s) / f"{n}.webp").exists()]
    print(f"{len(names)} images x {len(SIZES)} sizes; {len(missing)} missing from the export")
    if missing:
        print("\n".join(missing[:20]))
        print("refusing: the set is not whole")
        return 1
    if not storage.configured():
        print("R2 is not configured here (R2_* in .env)")
        return 1

    prefix = f"site/mascot/{args.version}/"
    there = set(storage.list_keys(prefix))
    todo = [(s, n) for s in SIZES for n in names if f"{prefix}{s}/{n}.webp" not in there]
    print(f"{len(there)} already under {prefix}; {len(todo)} to upload")
    if not args.write:
        print("report only; --write to upload")
        return 0
    for i, (s, n) in enumerate(todo, 1):
        storage.upload_file(args.export_dir / str(s) / f"{n}.webp", f"{prefix}{s}/{n}.webp",
                            content_type="image/webp")
        if i % 100 == 0:
            print(f"  {i}/{len(todo)}")
    print(f"uploaded {len(todo)}; base {storage.url_for_key(prefix.rstrip('/'))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
