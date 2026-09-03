"""Ingest a folder of pictures you saved yourself into the reference bin.

WHY THIS EXISTS. The scout's image lanes are down: Instagram's
public-content endpoint refuses without a Facebook app review, and the
YouTube lane is throwing in refresh_metrics. On 2026-09-02 the crawl
banked 8 sparks from 33 signals and "0 reference image(s) binned", so
every Zero Page scene that night was keyframed from prompt text alone.

Browsing for images cannot fix that, because the run that needs them
happens at 03:30 with no browser and nobody watching. Pictures already
on disk can. So: save what you like into a folder -- from Pinterest,
from anywhere -- and this puts them where the pipeline already looks.

Deliberately NOT a scraper. It reads a folder, hashes each image into
data/refs the same way a composer upload lands, and banks a scout_bin
row so a spark can carry it. `source` is whatever you pass in, so the
attribution the bin exists to keep is only as honest as that argument.

    venv/bin/python ops/ingest-saved-images.py ~/Pictures/zeropage-refs \\
        --brand zeropage --source pinterest --dry-run
"""
import argparse
import sys
from pathlib import Path as _P

# Run as `venv/bin/python ops/<name>.py` from anywhere: the repo root
# is not on sys.path unless the project happens to be pip-installed.
sys.path.insert(0, str(_P(__file__).resolve().parent.parent))
from pathlib import Path

from src import db, refbin, scout

SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".HEIC"}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("folder", help="folder of saved images")
    ap.add_argument("--brand", default="zeropage", choices=list(scout.BRANDS))
    ap.add_argument("--source", default="saved",
                    help="where these came from, kept on every row")
    ap.add_argument("--pass-id", default="",
                    help="bank under an existing pass; default is a new one")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    folder = Path(args.folder).expanduser()
    if not folder.is_dir():
        print(f"not a folder: {folder}", file=sys.stderr)
        return 1

    files = sorted(f for f in folder.iterdir()
                   if f.is_file() and f.suffix in SUFFIXES)
    if not files:
        print(f"no images in {folder}")
        return 0

    import uuid
    pass_id = args.pass_id or f"saved-{uuid.uuid4().hex[:12]}"
    scout.init()
    banked = 0

    for f in files:
        if args.dry_run:
            print(f"  would ingest {f.name}")
            continue
        jpeg = refbin.to_jpeg(f.read_bytes())
        if not jpeg:
            print(f"  skipped (undecodable): {f.name}", file=sys.stderr)
            continue
        url = refbin.save(jpeg)
        if not url:
            print(f"  skipped (not saved): {f.name}", file=sys.stderr)
            continue
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO scout_bin (created_at, pass_id, brand, url, "
                "source_url, title, lane, metric) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                (scout._now(), pass_id, args.brand, url, args.source,
                 f.stem[:120], "saved", ""),
            )
        banked += 1
        print(f"  {f.name} -> {url}")

    if not args.dry_run:
        print(f"\nbanked {banked} image(s) under pass {pass_id}")
        print("attach them to a spark with: scout.record(..., pass_id=<that>)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
