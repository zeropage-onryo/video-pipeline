"""
Move the index to the front of every clip already in R2 (2026-09-28).

`storage.upload_file` now runs `src/faststart.py` on every clip before it
uploads, so a new render arrives with its `moov` box first and a browser
can draw its first frame from the start of the file. Some clips uploaded
before that carry their index at the END (on 2026-09-28: one of five, the
LTX render for #194), which makes a browser read the end of the file
before it can show anything.

The `t/` prefix is skipped: those are the 480px derivatives, and a clip's
poster is a JPEG stored under the clip's own tail, `.mp4` name and all.

This finds them and fixes them in place, under the SAME key -- the URL on
every row stays true, so nothing in the database is touched. The remux is
`ffmpeg -c copy`: the same audio and video streams, byte for byte, with
the index moved. Before a clip is replaced, the rewritten file must parse
index-first and be within 1% of the original's size; anything else is
reported and left alone.

Reports first; `--write` to replace. Re-runnable: a clip already
index-first is only read (its first 64KB), never downloaded.

    set -a && source .env && set +a
    venv/bin/python -m ops.faststart_clips [--prefix m/] [--write]
"""
from __future__ import annotations

import argparse
import struct
import sys
import tempfile
from pathlib import Path

from src import faststart, storage

HEAD_BYTES = 64 * 1024
VIDEO_TYPES = (".mp4", ".m4v", ".mov")


def layout_from_head(head: bytes, total: int) -> str:
    """'index-first', 'index-last' or 'unknown', from the first bytes only.
    Walks box headers inside the buffer; `mdat` before any `moov` is the
    slow layout, `moov` before any `mdat` is the fast one."""
    pos = 0
    while pos + 8 <= len(head):
        size, = struct.unpack(">I", head[pos:pos + 4])
        kind = head[pos + 4:pos + 8].decode("latin1")
        if kind == "moov":
            return "index-first"
        if kind == "mdat":
            return "index-last"
        if size == 1:
            if pos + 16 > len(head):
                return "unknown"
            size, = struct.unpack(">Q", head[pos + 8:pos + 16])
        elif size == 0:
            size = total - pos
        if size < 8:
            return "unknown"
        pos += size
    return "unknown"


def _head(client, bucket: str, key: str) -> tuple[bytes, int]:
    obj = client.get_object(Bucket=bucket, Key=key, Range=f"bytes=0-{HEAD_BYTES - 1}")
    total = int(str(obj.get("ContentRange", "")).rsplit("/", 1)[-1] or obj.get("ContentLength") or 0)
    return obj["Body"].read(), total


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--prefix", default="", help="only keys under this prefix")
    parser.add_argument("--write", action="store_true", help="replace the index-last clips")
    args = parser.parse_args(argv)
    if not storage.configured():
        print("R2 is not configured (R2_* in .env) -- nothing to read", file=sys.stderr)
        return 1
    if args.write and not faststart.ffmpeg_bin():
        print("ffmpeg is not installed on this machine -- cannot remux", file=sys.stderr)
        return 1

    client, bucket = storage._client(), storage.bucket()
    keys = [k for k in storage.list_keys(args.prefix)
            if k.lower().endswith(VIDEO_TYPES) and not k.startswith("t/")]
    counts = {"index-first": 0, "index-last": 0, "unknown": 0, "fixed": 0, "refused": 0}
    with tempfile.TemporaryDirectory() as work:
        for key in keys:
            try:
                head, total = _head(client, bucket, key)
            except Exception as e:
                print(f"  ? {key}: could not read ({e})")
                counts["unknown"] += 1
                continue
            layout = layout_from_head(head, total)
            counts[layout] += 1
            if layout != "index-last":
                if layout == "unknown":
                    print(f"  ? {key}: layout not readable from the first {HEAD_BYTES // 1024}KB -- left alone")
                continue
            if not args.write:
                print(f"  - {key}: index at the end ({total / 1e6:.1f} MB)")
                continue
            local = Path(work) / Path(key).name
            client.download_file(bucket, key, str(local))
            before = local.stat().st_size
            if not faststart.faststart(local):
                print(f"  ! {key}: remux did not happen -- left alone")
                counts["refused"] += 1
                continue
            after = local.stat().st_size
            if faststart.needs_faststart(local) or abs(after - before) > before * 0.01:
                print(f"  ! {key}: rewritten file failed its check ({before} -> {after} bytes) -- left alone")
                counts["refused"] += 1
                continue
            client.upload_file(str(local), bucket, key, ExtraArgs={"ContentType": "video/mp4"})
            counts["fixed"] += 1
            print(f"  + {key}: index moved to the front ({before} -> {after} bytes)")
            local.unlink()

    print(f"{len(keys)} clips: {counts['index-first']} index-first, {counts['index-last']} index-last, "
          f"{counts['unknown']} unreadable"
          + (f"; fixed {counts['fixed']}, left alone {counts['refused']}" if args.write
             else " -- run with --write to fix the index-last ones"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
