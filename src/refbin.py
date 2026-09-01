"""
The reference bin: `data/refs/` -- one owner for the directory, the
file naming, and the JPEG normalisation every reference goes through.

This existed as three private helpers inside app/api.py (`_to_jpeg`,
`_save_upload_ref`, `UPLOAD_REFS_DIR`) back when a composer upload was
the only thing that ever landed there. src/scout.py now writes to the
same place -- the research images behind a crawled spark -- and `src/`
never imports `app/`, so the rule would have had to be written twice.
Two implementations of a content-addressed filename is the shape of bug
this project has already paid for elsewhere (see asset_shelf's
docstring): the second writer drifts, and the same photo starts
existing under two names.

So the rule lives here and app/api.py delegates. The URL shape does not
change -- `/refs/<sha>.jpg`, served by the static mount in app/main.py,
resolved by `_resolve_asset_photo` -- which is exactly why a scouted
research image can ride into a generation through the existing
composer path without a single new route.

Everything is best-effort: a reference that cannot be read or written
is dropped and returns None. A reference is an enhancement, and the
standing rule in this repo is that a bad one must never fail the run
that was using it.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REFS_DIR = PROJECT_ROOT / "data" / "refs"

# A remote image that is bigger than this is almost certainly not a
# reference photo -- it is a page asset, a PDF, or something that will
# cost more to decode than it is worth. Bounded because scout fetches
# URLs it did not choose.
MAX_FETCH_BYTES = 8 * 1024 * 1024
FETCH_TIMEOUT = 10


def to_jpeg(data: bytes) -> Optional[bytes]:
    """Any readable image -> upright RGB JPEG bytes, or None.

    `exif_transpose` runs BEFORE convert("RGB"), which drops the EXIF it
    reads. Every still off an iPhone is stored landscape with
    orientation 6 -- portrait only because a tag says so -- and
    converting first baked half this project's asset bank in sideways
    into data/refs, where nothing downstream could recover it
    (2026-08-28). pillow-heif is registered when present, because HEIC
    is otherwise accepted, listed, and silently dropped at render.
    """
    import io

    from PIL import Image
    try:
        import pillow_heif  # iPhone photos, when it is installed
        pillow_heif.register_heif_opener()
    except Exception:
        pass                    # degrade: .heic simply stays unreadable
    try:
        from PIL import ImageOps
        image = Image.open(io.BytesIO(data))
        image = ImageOps.exif_transpose(image).convert("RGB")
        buf = io.BytesIO()
        image.save(buf, "JPEG", quality=90)
        return buf.getvalue()
    except Exception:
        return None             # not a readable image -- skip, never fail the run


def save(jpeg: bytes) -> Optional[str]:
    """Persist one reference, return the URL it rides on.

    Content-addressed, so attaching the same photo to six scenes -- or
    the scout re-finding the same thumbnail on two consecutive nights --
    stores it once."""
    try:
        REFS_DIR.mkdir(parents=True, exist_ok=True)
        name = hashlib.sha256(jpeg).hexdigest()[:24] + ".jpg"
        target = REFS_DIR / name
        if not target.exists():
            target.write_bytes(jpeg)
        return f"/refs/{name}"
    except Exception:
        return None


def resolve(url_path: str) -> Optional[Path]:
    """`/refs/<name>.jpg` -> the file on disk, or None.

    Lives beside `save` deliberately. When the write lived here and the
    read stayed in app/api.py, patching one directory in a test moved
    the writer and left the reader pointing somewhere else -- a file
    saved successfully and then resolved to nothing, which is the exact
    silent-reference failure this module exists to prevent. One module
    owns the directory, both directions.

    Anything that escapes the directory resolves to None rather than
    raising: these URLs arrive from a form, and an attachment is an
    enhancement.
    """
    clean = (url_path or "").split("?")[0].strip("/")
    parts = clean.split("/")
    if len(parts) != 2 or parts[0] != "refs":
        return None
    try:
        target = (REFS_DIR / parts[1]).resolve()
        if REFS_DIR.resolve() != target.parent:
            return None
        return target if target.is_file() else None
    except Exception:
        return None


def public_host(host) -> bool:
    """SSRF guard: only addresses outside the private ranges.

    THE canonical one -- src/imagery.py delegates here. It moved down
    when the MCP surface gained bank_reference (2026-09-01): a crawl URL
    at least came from Reddit or YouTube, but an AGENT-supplied URL is
    whatever a page the agent read told it to fetch, and this fetch runs
    server-side. A guard that only one of two fetchers has is the shape
    of bug where the weaker one is the one that gets called.
    """
    import ipaddress
    import socket

    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            return False
    return bool(infos)


def fetch(url: str) -> Optional[str]:
    """Download a remote image into the bin, normalised. None on
    anything that isn't a readable image within the size bound.

    Streamed with a hard byte cap rather than read whole, and refused
    outright for a private address: these URLs come off a crawl -- or,
    since bank_reference, off whatever page an agent happened to read --
    so nothing has vouched for what is behind them.
    """
    from urllib.parse import urlparse

    import requests

    parsed = urlparse(url or "")
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return None
    if not public_host(parsed.hostname):
        return None
    try:
        with requests.get(url, stream=True, timeout=FETCH_TIMEOUT) as resp:
            resp.raise_for_status()
            chunks, total = [], 0
            for chunk in resp.iter_content(64 * 1024):
                total += len(chunk)
                if total > MAX_FETCH_BYTES:
                    return None
                chunks.append(chunk)
        jpeg = to_jpeg(b"".join(chunks))
        return save(jpeg) if jpeg else None
    except Exception:
        return None
