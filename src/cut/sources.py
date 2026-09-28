"""
src/cut/sources.py -- a handle -> a file ffmpeg can open, and what is in it.

The ONLY place in src/cut that reads a URL. A doc names media by handle;
this module looks the handle up (generated_assets for `gen:`, cut_media for
`asset:`), always under the caller's account, and turns what the row
stores into a local path:

1. a file on this disk -- the row's `output_path`, or the `/renders/...`
   route resolved under data/renders (the Mac reads its own renders off
   disk, the reference-photo rule);
2. otherwise the string `media.url_for` mints for it (R2, possibly
   signed), downloaded into the caller's work directory -- through the
   same private-address guard every other server-side fetch here uses,
   with a size cap, because the URL came off a row.

Someone else's handle does not resolve: the lookup is scoped, so it is
exactly as missing as a handle that never existed.

`probe` asks ffprobe what a file is -- length in project frames, whether
it has picture and sound, and its size -- which is what validate needs to
check a doc against reality. `measure` is the same answer through the
cut_media_cache (store.py): what the editor asks on every edit, so a file
is fetched and probed once, not once per keystroke.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional

from . import doc as d

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RENDERS_DIR = PROJECT_ROOT / "data" / "renders"
MAX_FETCH_BYTES = 500 * 1024 * 1024
FETCH_TIMEOUT = 30
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")


class SourceError(RuntimeError):
    pass


def ffprobe_bin() -> Optional[str]:
    return shutil.which("ffprobe")


def ffmpeg_bin() -> Optional[str]:
    return shutil.which("ffmpeg")


def _row_for(handle: str, account_id: Optional[int], dsn: Optional[str]) -> Optional[dict]:
    parsed = d.parse_handle(handle)
    if not parsed:
        return None
    kind, id_ = parsed
    if kind == "gen":
        from .. import render_assets
        return render_assets.get(id_, dsn, account_id=account_id)
    from . import store
    return store.get_media(id_, account_id=account_id, dsn=dsn)


def local_path_for(url: str, output_path: Optional[str] = None) -> Optional[Path]:
    """The file on this disk behind a stored string, or None. Refuses
    anything that climbs out of data/renders."""
    if output_path:
        p = Path(output_path)
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        if p.is_file():
            return p
    from .. import media
    tail = media.tail_for(url or "")
    if tail and tail.startswith("renders/"):
        target = (RENDERS_DIR / tail[len("renders/"):]).resolve()
        if RENDERS_DIR.resolve() in target.parents and target.is_file():
            return target
    return None


def _download(url: str, workdir: Path) -> Path:
    from urllib.parse import urlparse

    import requests

    from .. import refbin

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise SourceError(f"not a fetchable URL: {url[:80]}")
    if not refbin.public_host(parsed.hostname):
        raise SourceError(f"refusing a private address: {parsed.hostname}")
    suffix = Path(parsed.path).suffix or ".bin"
    target = workdir / f"src-{hashlib.sha1(url.encode()).hexdigest()[:12]}{suffix}"
    if target.is_file():
        return target
    total = 0
    with requests.get(url, stream=True, timeout=FETCH_TIMEOUT) as resp:
        resp.raise_for_status()
        with open(target, "wb") as out:
            for chunk in resp.iter_content(256 * 1024):
                total += len(chunk)
                if total > MAX_FETCH_BYTES:
                    out.close()
                    target.unlink(missing_ok=True)
                    raise SourceError(f"{url[:80]} is over {MAX_FETCH_BYTES // (1024 * 1024)}MB")
                out.write(chunk)
    return target


def file_for(handle: str, row: dict, account_id: Optional[int], workdir: Path) -> Path:
    stored = row.get("media_url") or ""
    local = local_path_for(stored, row.get("output_path"))
    if local:
        return local
    from .. import media
    url = media.url_for(stored, account_id)
    if not url.startswith(("http://", "https://")):
        raise SourceError(f"{handle}: its file is not on this machine and has no public copy")
    return _download(url, Path(workdir))


def resolve(handle: str, *, account_id: Optional[int], workdir: Path,
            dsn: Optional[str] = None) -> Path:
    row = _row_for(handle, account_id, dsn)
    if not row:
        raise SourceError(f"unknown media handle {handle}")
    return file_for(handle, row, account_id, workdir)


def probe(path: Path, fps: int) -> dict[str, Any]:
    """{"frames", "seconds", "video", "audio", "width", "height", "still"}
    for a file. Raises SourceError when there is no ffprobe or it cannot
    read the file -- a cut cannot be checked against media nobody measured.

    An image is a STILL: it has no length of its own, so it is reported as
    d.STILL_SECONDS of picture and no sound -- as long as anyone will hold
    one -- and render.py reads it with `-loop 1`."""
    exe = ffprobe_bin()
    if not exe:
        raise SourceError("ffprobe is not installed on this machine")
    try:
        out = subprocess.run(
            [exe, "-v", "error", "-show_entries",
             "format=duration,format_name:stream=codec_type,width,height,duration",
             "-of", "json", str(path)],
            capture_output=True, text=True, timeout=30, check=True).stdout
        info = json.loads(out)
    except (subprocess.SubprocessError, ValueError) as e:
        raise SourceError(f"ffprobe could not read {Path(path).name}: {e}") from None
    streams = info.get("streams") or []
    vid = next((s for s in streams if s.get("codec_type") == "video"), None)
    aud = next((s for s in streams if s.get("codec_type") == "audio"), None)
    fmt = str((info.get("format") or {}).get("format_name") or "")
    if vid is not None and aud is None and (
            Path(path).suffix.lower() in IMAGE_EXTS or fmt == "image2" or fmt.endswith("_pipe")):
        return {"frames": d.STILL_SECONDS * fps, "seconds": float(d.STILL_SECONDS),
                "video": True, "audio": False, "still": True,
                "width": int(vid["width"]) if vid.get("width") else None,
                "height": int(vid["height"]) if vid.get("height") else None}
    try:
        seconds = float((info.get("format") or {}).get("duration")
                        or (vid or aud or {}).get("duration") or 0)
    except (TypeError, ValueError):
        seconds = 0.0
    if seconds <= 0:
        raise SourceError(f"{Path(path).name} has no measurable length")
    return {"frames": d.to_frames(seconds, fps), "seconds": seconds,
            "video": vid is not None, "audio": aud is not None, "still": False,
            "width": int(vid["width"]) if vid and vid.get("width") else None,
            "height": int(vid["height"]) if vid and vid.get("height") else None}


def frames_of(facts: dict, fps: int) -> dict[str, Any]:
    """A cached probe row -> the {"frames", "video", "audio", "seconds",
    "still"} shape validate takes, at THIS doc's fps (the cache stores
    seconds, so one probe serves a 24 and a 30 fps cut alike)."""
    still = bool(facts.get("still"))
    seconds = float(facts.get("seconds") or 0)
    return {"frames": d.STILL_SECONDS * fps if still else d.to_frames(seconds, fps),
            "seconds": seconds, "video": bool(facts.get("has_video")),
            "audio": bool(facts.get("has_audio")), "still": still,
            "width": facts.get("width"), "height": facts.get("height")}


def measure(handles, *, account_id: Optional[int], fps: int,
            dsn: Optional[str] = None) -> dict[str, Optional[dict[str, Any]]]:
    """What each handle's file is, from the cache when it can be.

    Returns handle -> the validate shape, or -> None when the handle is
    this account's but its file could not be read. A handle that is not
    this account's (or never existed) is ABSENT, so the validator calls
    it unknown -- the caller decides what an unmeasured one means (the
    editor lets a clip already on the timeline through, and refuses to
    insert one).

    A miss is probed once -- off this disk, or downloaded into a scratch
    directory that is gone when this returns -- and written back, keyed
    to the row's `media_url` so a re-pointed handle is measured again
    rather than trusted. That is the whole point of the cache: on the
    deployed box a `gen:` file lives in R2, and an op must not download
    every clip on the timeline to validate one trim."""
    import tempfile

    from . import store
    wanted = [h for h in dict.fromkeys(handles) if d.parse_handle(h)]
    rows = store.handle_sources(wanted, account_id=account_id, dsn=dsn)
    known = store.cached(list(rows), account_id=account_id, dsn=dsn)
    out: dict[str, Optional[dict[str, Any]]] = {}
    misses = []
    for h, row in rows.items():
        hit = known.get(h)
        if hit and hit.get("source") == (row.get("media_url") or "") and hit.get("probed_at"):
            out[h] = frames_of(hit, fps)
        else:
            misses.append(h)
    if misses:
        with tempfile.TemporaryDirectory(prefix="zpf-probe-") as tmp:
            for h in misses:
                row = rows[h]
                try:
                    path = file_for(h, row, account_id, Path(tmp))
                    info = probe(path, fps)
                    size = path.stat().st_size
                except Exception:                       # noqa: BLE001 -- unmeasured, not fatal
                    out[h] = None
                    continue
                store.put_probe(h, row.get("media_url") or "", info, account_id=account_id,
                                size_bytes=size, dsn=dsn)
                out[h] = {k: info.get(k) for k in
                          ("frames", "seconds", "video", "audio", "still", "width", "height")}
    return out


def gather(handles, *, account_id: Optional[int], fps: int, workdir: Path,
           dsn: Optional[str] = None) -> tuple[dict[str, Path], dict[str, dict]]:
    """Resolve and probe every handle: (paths, media) where `media` is
    what validate.problems takes."""
    paths: dict[str, Path] = {}
    info: dict[str, dict] = {}
    for h in handles:
        if h in paths:
            continue
        paths[h] = resolve(h, account_id=account_id, workdir=workdir, dsn=dsn)
        info[h] = probe(paths[h], fps)
    return paths, info
