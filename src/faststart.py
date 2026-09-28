"""
Put an MP4's index (the `moov` box) in front of its media (`mdat`).

Some provider outputs arrive with `moov` AFTER `mdat` (checked 2026-09-28:
fal's LTX clip for #194 is ftyp, uuid, free, mdat, then moov at the very
end; the other three clips in the bucket were already index-first). A
browser cannot draw a frame -- not even the
Assets wall's first-frame tile under `preload="metadata"` -- until it has
the index, so it has to fetch the start, discover `mdat`, then make a
second range request to the END of the file before anything appears.
Over the rate-limited r2.dev address that is the difference between a
tile and a grey box.

`ffmpeg -c copy -movflags +faststart` fixes it without re-encoding: the
same streams, byte for byte, with the index moved to the front. It is
done once, on the local file, just before it is uploaded
(`storage.upload_file`), so the file on disk and the file in R2 are the
same file.

Best-effort by contract: no ffmpeg, an unreadable box layout, or a
failed remux leaves the file exactly as it was. A slow tile is a
nuisance; a render that fails to upload because of it would lose a paid
output.
"""
from __future__ import annotations

import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path
from typing import Optional

VIDEO_SUFFIXES = {".mp4", ".m4v", ".mov"}


def top_level_boxes(path: Path | str, limit: int = 64) -> list[str]:
    """The top-level box types in file order, read by seeking from header
    to header (never reading `mdat` itself). Stops at the first header it
    cannot parse, so a truncated or non-MP4 file answers with what it has."""
    out: list[str] = []
    try:
        size_total = os.path.getsize(path)
        with open(path, "rb") as f:
            pos = 0
            while pos + 8 <= size_total and len(out) < limit:
                f.seek(pos)
                head = f.read(8)
                if len(head) < 8:
                    break
                size, = struct.unpack(">I", head[:4])
                kind = head[4:8].decode("latin1")
                if size == 1:                    # 64-bit size follows
                    big = f.read(8)
                    if len(big) < 8:
                        break
                    size, = struct.unpack(">Q", big)
                elif size == 0:                  # runs to end of file
                    size = size_total - pos
                if size < 8:
                    break
                out.append(kind)
                pos += size
    except OSError:
        return out
    return out


def needs_faststart(path: Path | str) -> bool:
    """True when `mdat` comes before `moov` -- the layout that makes a
    browser read the end of the file before it can show anything."""
    boxes = top_level_boxes(path)
    if "moov" not in boxes or "mdat" not in boxes:
        return False
    return boxes.index("mdat") < boxes.index("moov")


def ffmpeg_bin() -> Optional[str]:
    return shutil.which("ffmpeg")


def faststart(path: Path | str, *, run=subprocess.run) -> bool:
    """Rewrite `path` in place with its index at the front. True when the
    file was rewritten; False when it did not need it or could not be
    fixed (never raises). `run` is the seam tests replace."""
    path = Path(path)
    if path.suffix.lower() not in VIDEO_SUFFIXES or not path.exists():
        return False
    if not needs_faststart(path):
        return False
    exe = ffmpeg_bin()
    if not exe:
        print(f"[faststart] no ffmpeg on this machine; {path.name} keeps its index at the end",
              file=sys.stderr)
        return False
    tmp = path.with_name(f".{path.stem}.faststart{path.suffix}")
    try:
        done = run([exe, "-hide_banner", "-loglevel", "error", "-y", "-i", str(path),
                    "-map", "0", "-c", "copy", "-movflags", "+faststart", str(tmp)],
                   capture_output=True, timeout=120)
        if getattr(done, "returncode", 1) != 0 or not tmp.exists() or tmp.stat().st_size == 0:
            err = (getattr(done, "stderr", b"") or b"").decode(errors="replace").strip()
            print(f"[faststart] ffmpeg could not remux {path.name}: {err[:200]}", file=sys.stderr)
            return False
        if needs_faststart(tmp):
            return False
        os.replace(tmp, path)
        return True
    except Exception as e:  # best-effort: never lose the original over this
        print(f"[faststart] {path.name}: {e}", file=sys.stderr)
        return False
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
