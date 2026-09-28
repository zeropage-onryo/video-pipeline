"""
Draw the poster for every generated clip that has none (2026-09-28).

`fal._publish` and the manual import now write a clip's poster -- one frame,
480px, under the clip's own tail in `t/` (src/media.py, `mirror_poster`) --
so the Assets wall draws a still instead of a dark tile. Clips rendered
before that have no poster. This finds them and draws one.

Reports first; `--write` to upload. Re-runnable: a clip whose poster is
already in the bucket is skipped. Reads every account's rows on purpose
(it is the operator's repair pass), and writes each poster under its own
row's account. Needs ffmpeg and R2; reads the clip from `output_path` when
this machine has it, else downloads it from its media URL.

    set -a && source .env && set +a
    venv/bin/python -m ops.backfill_video_posters [--write]
"""
from __future__ import annotations

import argparse
import sys
import tempfile
import urllib.request
from pathlib import Path

from src import db, media, storage


def _clips(dsn=None) -> list[dict]:
    with db.connect(dsn) as conn:
        if not db.table_exists(conn, "generated_assets"):
            return []
        # every account's rows (the operator's repair pass), carrying each
        # row's account_id so the poster lands under its owner's prefix
        rows = conn.execute(
            "SELECT id, account_id, media_url, output_path FROM generated_assets "
            "WHERE media_kind = 'video' AND deleted_at IS NULL ORDER BY id").fetchall()
    return [dict(r) for r in rows]


def _local_copy(row: dict, work: Path) -> Path | None:
    path = Path(row.get("output_path") or "")
    if path.is_file():
        return path
    url = media.url_for(row["media_url"], row["account_id"])
    if not url.startswith("http"):
        return None
    target = work / f"clip-{row['id']}.mp4"
    request = urllib.request.Request(url, headers={"User-Agent": "zeropage-backfill"})
    with urllib.request.urlopen(request, timeout=120) as response:
        target.write_bytes(response.read())
    return target


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--write", action="store_true", help="upload the posters")
    args = parser.parse_args(argv)
    if not storage.configured():
        print("R2 is not configured -- nothing to write a poster to.", file=sys.stderr)
        return 1

    todo = done = failed = 0
    with tempfile.TemporaryDirectory() as tmp:
        for row in _clips():
            tail = media.tail_for(row["media_url"])
            if not tail:
                print(f"#{row['id']}: {row['media_url']} is not ours -- skipped")
                continue
            key = media.thumb_key_for_tail(tail, row["account_id"])
            if storage.key_exists(key):
                done += 1
                continue
            todo += 1
            if not args.write:
                print(f"#{row['id']} (account {row['account_id']}): would write {key}")
                continue
            try:
                clip = _local_copy(row, Path(tmp))
                url = media.mirror_poster(clip, tail, row["account_id"]) if clip else None
            except Exception as e:                      # noqa: BLE001
                url = None
                print(f"#{row['id']}: {type(e).__name__}: {e}", file=sys.stderr)
            if url:
                print(f"#{row['id']}: wrote {key}")
            else:
                failed += 1
                print(f"#{row['id']}: no poster drawn")
    verb = "written" if args.write else "to write"
    print(f"{todo} {verb} ({failed} failed), {done} already had one")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
