"""
src/cut/preview.py -- what the browser plays while you edit
(docs/CUT_EDITOR.md section 5.5, Mike's D3).

The browser previews from PROXIES; the ffmpeg render stays the export of
record. Per media file, built once and keyed by the sha256 of its bytes:

- a 540p H.264 PROXY (short edge 540, never upscaled) with a keyframe
  every second (`-g fps -keyint_min fps`, no scene-cut keyframes) and
  faststart, AAC sound kept -- so a scrub lands on a keyframe within a
  second and the first frame plays before the whole file has arrived;
- a FILMSTRIP: one frame per `interval` seconds, 90px tall, tiled into
  ONE horizontal JPEG, capped at 120 frames (the interval widens for long
  media rather than the strip growing without bound);
- WAVEFORM peaks: ~50 values per second, 0..1, three decimal places --
  the ABSOLUTE peak, not normalised, so a quiet bed draws as quiet;
- a POSTER frame for the bin tile when the Asset Bank has none.

An image gets a one-frame filmstrip and a poster, and no proxy or
waveform (it is a still: `<img>` is its proxy). Audio gets a waveform
only.

The files land under data/renders/cut/preview/<sha[:24]>/ -- served by
the app's /renders mount on this machine -- and are mirrored to R2 through
`media.mirror` (derive=False: they ARE the derivatives), so the deployed
box, which has no such folder, serves them the same way; `media.url_for`
mints them on read. What the cache row stores is the logical name, never
a minted URL (the 2026-09-14 rule: a signed URL is true for an hour).

`build` is ffmpeg and nothing else (tested with a tiny generated clip);
`ensure` is the job body: find the file, hash it, reuse a finished
preview of the same bytes under another handle, else build, publish and
record. It never raises -- a failure is `failed` on the row with the
reason, which is what the preview route reports.

Nothing here spends: ffmpeg on this box, no model call, no ledger hold.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from array import array
from datetime import datetime, timedelta, timezone
from math import ceil
from pathlib import Path
from typing import Any, Optional

from . import doc as d
from . import sources, store

PREVIEW_DIR = sources.RENDERS_DIR / "cut" / "preview"
PROXY_SHORT_EDGE = 540
FILMSTRIP_HEIGHT = 90
FILMSTRIP_MAX_FRAMES = 120
POSTER_EDGE = 480
PEAKS_PER_SECOND = 50
PEAK_RATE = 8000                     # decode rate for peaks: 160 samples per value
BUILD_TIMEOUT = 600
# a `pending` row older than this is a build that died with its process
# (the job registry is in-memory; a deploy clears it), and is claimed again
PENDING_STALE = timedelta(minutes=15)

STATUSES = ("ready", "pending", "failed", "unavailable")


class PreviewError(RuntimeError):
    pass


def _run(args: list[str], timeout: int = BUILD_TIMEOUT) -> subprocess.CompletedProcess:
    exe = sources.ffmpeg_bin()
    if not exe:
        raise PreviewError("ffmpeg is not installed on this machine")
    try:
        proc = subprocess.run([exe, "-hide_banner", "-nostdin", "-loglevel", "error", "-y", *args],
                              capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise PreviewError(f"ffmpeg ran past {timeout}s") from None
    if proc.returncode != 0:
        tail = (proc.stderr or b"").decode("utf-8", "replace").strip().splitlines()[-2:]
        raise PreviewError("ffmpeg failed: " + (" | ".join(tail) or f"exit {proc.returncode}"))
    return proc


def fingerprint(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


# --------------------------------------------------------------------------
# the pieces
# --------------------------------------------------------------------------

def filmstrip_plan(seconds: float) -> tuple[int, int]:
    """(interval seconds, frame count) for a strip of one frame per
    second, widened past FILMSTRIP_MAX_FRAMES. The count is the frames
    that START strictly inside the media, so ffmpeg's `fps` filter always
    produces at least that many -- the strip is never padded with black."""
    seconds = max(float(seconds or 0), 0.0)
    interval = max(1, ceil(seconds / FILMSTRIP_MAX_FRAMES))
    count = max(1, min(FILMSTRIP_MAX_FRAMES, int(seconds // interval)))
    return interval, count


def _scale_short_edge(width: Optional[int], height: Optional[int], edge: int) -> str:
    """A scale filter taking the SHORT edge to `edge` (never up), the
    other to the nearest even number -- 540p means 540 across a 9:16
    frame, not 540 tall."""
    if not width or not height:
        return f"scale=-2:'min({edge},ih)'"
    if width >= height:
        return f"scale=-2:{min(edge, height) // 2 * 2}"
    return f"scale={min(edge, width) // 2 * 2}:-2"


def make_proxy(src: Path, out: Path, info: dict, fps: int = d.DEFAULT_FPS) -> Path:
    args = ["-i", str(src), "-map", "0:v:0", "-vf",
            f"fps={fps},{_scale_short_edge(info.get('width'), info.get('height'), PROXY_SHORT_EDGE)}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-pix_fmt", "yuv420p",
            "-g", str(fps), "-keyint_min", str(fps), "-sc_threshold", "0"]
    if info.get("audio"):
        args += ["-map", "0:a:0", "-c:a", "aac", "-b:a", "96k", "-ac", "2"]
    else:
        args += ["-an"]
    _run(args + ["-movflags", "+faststart", str(out)])
    return out


def make_filmstrip(src: Path, out: Path, info: dict) -> dict[str, Any]:
    if info.get("still"):
        interval, count = int(d.STILL_SECONDS), 1
        _run(["-i", str(src), "-vf", f"scale=-2:{FILMSTRIP_HEIGHT}", "-frames:v", "1",
              "-q:v", "5", str(out)])
    else:
        interval, count = filmstrip_plan(info.get("seconds") or 0)
        _run(["-i", str(src), "-an", "-vf",
              f"fps=1/{interval},scale=-2:{FILMSTRIP_HEIGHT},tile={count}x1",
              "-frames:v", "1", "-q:v", "5", str(out)])
    width, height = _image_size(out)
    return {"frame_width": width // count, "frame_height": height,
            "count": count, "interval": interval}


def make_poster(src: Path, out: Path, info: dict) -> Path:
    at = [] if info.get("still") else ["-ss", f"{min(0.5, (info.get('seconds') or 0) / 2):.3f}"]
    _run([*at, "-i", str(src), "-frames:v", "1", "-vf",
          _scale_short_edge(info.get("width"), info.get("height"), POSTER_EDGE),
          "-q:v", "4", str(out)])
    return out


def peaks(src: Path, per_second: int = PEAKS_PER_SECOND) -> list[float]:
    """The absolute peak of every 1/per_second of sound, 0..1, 3 dp.
    Decoded to mono 16-bit at PEAK_RATE, which keeps a ten-minute bed
    under 10MB in memory and loses nothing a 50-per-second line can show."""
    proc = _run(["-i", str(src), "-vn", "-ac", "1", "-ar", str(PEAK_RATE),
                 "-f", "s16le", "-acodec", "pcm_s16le", "-"])
    samples = array("h")
    samples.frombytes(proc.stdout[: len(proc.stdout) // 2 * 2])
    step = PEAK_RATE // per_second
    out = []
    for i in range(0, len(samples), step):
        chunk = samples[i:i + step]
        top = max(max(chunk), -min(chunk))
        out.append(round(min(top / 32768, 1.0), 3))
    return out


def _image_size(path: Path) -> tuple[int, int]:
    exe = sources.ffprobe_bin()
    if not exe:
        raise PreviewError("ffprobe is not installed on this machine")
    out = subprocess.run([exe, "-v", "error", "-show_entries", "stream=width,height",
                          "-of", "json", str(path)], capture_output=True, text=True,
                         timeout=30).stdout
    stream = (json.loads(out or "{}").get("streams") or [{}])[0]
    return int(stream.get("width") or 0), int(stream.get("height") or 0)


def build(src: Path, out_dir: Path, info: dict, fps: int = d.DEFAULT_FPS) -> dict[str, Any]:
    """Every preview a file of this shape gets, written into `out_dir`.
    Returns {"proxy": name|None, "filmstrip": {...,"file"}|None,
    "waveform": {"file", "per_second"}|None, "poster": name|None} with
    FILE NAMES (the caller turns them into stored strings)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {"proxy": None, "filmstrip": None, "waveform": None, "poster": None}
    if info.get("video"):
        strip = make_filmstrip(src, out_dir / "filmstrip.jpg", info)
        result["filmstrip"] = {**strip, "file": "filmstrip.jpg"}
        make_poster(src, out_dir / "poster.jpg", info)
        result["poster"] = "poster.jpg"
        if not info.get("still"):
            make_proxy(src, out_dir / "proxy.mp4", info, fps)
            result["proxy"] = "proxy.mp4"
    if info.get("audio"):
        values = peaks(src)
        (out_dir / "waveform.json").write_text(
            json.dumps({"per_second": PEAKS_PER_SECOND, "peaks": values}), encoding="utf-8")
        result["waveform"] = {"file": "waveform.json", "per_second": PEAKS_PER_SECOND}
    return result


# --------------------------------------------------------------------------
# the job, and what the route reads
# --------------------------------------------------------------------------

_TYPES = {"proxy.mp4": "video/mp4", "filmstrip.jpg": "image/jpeg", "poster.jpg": "image/jpeg",
          "waveform.json": "application/json"}


def _publish(folder: Path, name: str, account_id: Optional[int]) -> str:
    """The stored string for one preview file, mirrored to R2 on the way."""
    from .. import media
    tail = f"renders/cut/preview/{folder.name}/{name}"
    media.mirror(folder / name, tail, account_id, content_type=_TYPES[name], derive=False)
    return f"/{tail}"


def ensure(handle: str, *, account_id: Optional[int], dsn: Optional[str] = None,
           fps: int = d.DEFAULT_FPS) -> dict[str, Any]:
    """Build (or reuse) one handle's previews and record them. The job
    body. Never raises: returns {"status", "note"?} and leaves the same
    on the cache row."""
    def fail(note: str) -> dict[str, Any]:
        store.set_preview(handle, account_id=account_id, status="failed", note=note[:400],
                          dsn=dsn)
        return {"status": "failed", "note": note}

    rows = store.handle_sources([handle], account_id=account_id, dsn=dsn)
    row = rows.get(handle)
    if row is None:
        return fail(f"unknown media handle {handle}")
    try:
        with tempfile.TemporaryDirectory(prefix="zpf-preview-") as tmp:
            src = sources.file_for(handle, row, account_id, Path(tmp))
            info = sources.probe(src, fps)
            sha = fingerprint(src)
            store.put_probe(handle, row.get("media_url") or "", info, account_id=account_id,
                            size_bytes=src.stat().st_size, sha256=sha, dsn=dsn)
            twin = store.preview_by_sha(sha, account_id=account_id, dsn=dsn)
            if twin and twin["handle"] != handle:
                store.set_preview(handle, account_id=account_id, status="ready", sha256=sha,
                                  proxy_url=twin.get("proxy_url"),
                                  filmstrip=twin.get("filmstrip"),
                                  waveform=twin.get("waveform"),
                                  poster_url=twin.get("poster_url"), dsn=dsn)
                return {"status": "ready", "reused": twin["handle"]}
            folder = Path(PREVIEW_DIR) / sha[:24]
            built = build(src, folder, info, fps)
    except (PreviewError, sources.SourceError) as e:
        return fail(str(e))
    except Exception as e:                              # noqa: BLE001 -- recorded, not raised
        return fail(f"{type(e).__name__}: {e}")

    strip = built["filmstrip"]
    wave = built["waveform"]
    store.set_preview(
        handle, account_id=account_id, status="ready", sha256=sha,
        proxy_url=_publish(folder, built["proxy"], account_id) if built["proxy"] else None,
        filmstrip=({**{k: strip[k] for k in ("frame_width", "frame_height", "count", "interval")},
                    "url": _publish(folder, strip["file"], account_id)} if strip else None),
        waveform=({"url": _publish(folder, wave["file"], account_id),
                   "per_second": wave["per_second"]} if wave else None),
        poster_url=_publish(folder, built["poster"], account_id) if built["poster"] else None,
        dsn=dsn)
    return {"status": "ready"}


def _stale(when: Optional[str]) -> bool:
    try:
        at = datetime.fromisoformat(str(when))
    except (TypeError, ValueError):
        return True
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - at > PENDING_STALE


def needs_build(row: Optional[dict], source: str) -> bool:
    """Whether a GET should start a build: never built, built from a file
    the handle no longer points at, or `pending` so long its job must have
    died. A `failed` build is NOT retried by reading it -- the route would
    otherwise re-run a broken ffmpeg on every poll."""
    if not row or row.get("source") != source:
        return True
    status = row.get("preview_status")
    if status is None:
        return True
    return status == "pending" and _stale(row.get("preview_at"))


def stale_before() -> str:
    return (datetime.now(timezone.utc) - PENDING_STALE).isoformat(timespec="seconds")


def view(row: Optional[dict], account_id: Optional[int]) -> dict[str, Any]:
    """A cache row -> the preview route's JSON, with every stored string
    minted for THIS reader, now."""
    from .. import media

    def mint(stored):
        return media.url_for(stored, account_id) if stored else None

    status = (row or {}).get("preview_status") or "pending"
    out: dict[str, Any] = {"status": status, "proxy": None, "filmstrip": None, "waveform": None}
    if status == "ready":
        strip = row.get("filmstrip")
        wave = row.get("waveform")
        out["proxy"] = mint(row.get("proxy_url"))
        out["filmstrip"] = {**strip, "url": mint(strip.get("url"))} if strip else None
        out["waveform"] = ({"url": mint(wave.get("url")), "per_second": wave.get("per_second")}
                           if wave else None)
    elif status == "failed" and row.get("preview_note"):
        out["note"] = row["preview_note"]
    return out
