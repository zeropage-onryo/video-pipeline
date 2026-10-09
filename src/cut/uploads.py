"""
A file a person brings in, filed as an `asset:<id>` (2026-10-09, lifted
out of app/cut_routes.py's upload route for docs/tasks/
task-mcp-studio-v2.md step 3+4).

Two doors take a file and one body files it: the editor's upload route
(`POST /api/cut/media`, bytes from a browser) and the studio MCP's
`import_file` (bytes read off this machine's disk). Either way the file is
typed by its extension, size-capped, PROBED (a file ffprobe cannot read,
or that is not what its extension says, is refused here, never at the
first edit or render that uses it), written content-addressed under the
editor's media folder, mirrored to the bucket under the account's prefix,
recorded in `cut_media` (OWNED) and its probe cached -- so the first op or
render that names the handle downloads nothing.

The handle is `asset:<id>`: never a URL, owned by one account, and the
same id the editor's bin, Assemble's music bed and the MCP's references,
effect sources and joins all take.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Optional

from . import sources, store

AUDIO_TYPES = {".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".aac": "audio/aac",
               ".wav": "audio/wav", ".ogg": "audio/ogg", ".flac": "audio/flac"}
VIDEO_TYPES = {".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm",
               ".m4v": "video/x-m4v"}
IMAGE_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
               ".webp": "image/webp"}
UPLOAD_TYPES = {**AUDIO_TYPES, **VIDEO_TYPES, **IMAGE_TYPES}

MB = 1024 * 1024
MAX_MEDIA_BYTES = 100 * MB
# footage is bigger than a music bed; still one request, so still capped
MAX_VIDEO_BYTES = 500 * MB


class UploadRefused(ValueError):
    """A file that will not be filed, and why: `code` is the route's error
    code (bad_type, empty, too_big, unreadable, no_audio, no_video,
    not_an_image), the message a sentence a person can act on."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def kind_of(ext: str) -> Optional[str]:
    ext = (ext or "").lower()
    if ext in AUDIO_TYPES:
        return "audio"
    if ext in VIDEO_TYPES:
        return "video"
    if ext in IMAGE_TYPES:
        return "image"
    return None


def cap_for(kind: str) -> int:
    return MAX_VIDEO_BYTES if kind == "video" else MAX_MEDIA_BYTES


def save(data: bytes, filename: str, *, account_id: Optional[int], media_dir: Path,
         types: Optional[dict] = None, dsn: Optional[str] = None) -> dict[str, Any]:
    """File `data` (named `filename`) as an upload. `types` narrows what is
    taken (an extension -> mime map, default every upload type). Returns
    {"handle", "row", "info", "stored", "kind", "size", "sha256"}; raises
    UploadRefused."""
    types = types if types is not None else UPLOAD_TYPES
    ext = Path(filename or "").suffix.lower()
    kind = kind_of(ext) if ext in types else None
    if kind is None:
        raise UploadRefused("bad_type", "audio, video or an image: "
                            f"{', '.join(sorted(types))}" if types is UPLOAD_TYPES
                            else f"one of {', '.join(sorted(types))}")
    if not data:
        raise UploadRefused("empty", "the file is empty")
    cap = cap_for(kind)
    if len(data) > cap:
        raise UploadRefused("too_big", f"over {cap // MB}MB")
    sha = hashlib.sha256(data).hexdigest()
    media_dir = Path(media_dir)
    media_dir.mkdir(parents=True, exist_ok=True)
    target = media_dir / f"{sha[:24]}{ext}"
    target.write_bytes(data)
    try:
        info = sources.probe(target, 30)
    except sources.SourceError as e:
        target.unlink(missing_ok=True)
        raise UploadRefused("unreadable", str(e)) from e
    refusal = None
    # a picture has a size: ffprobe reports a text file named .jpg as a 0x0
    # mjpeg "still" (found 2026-10-09 by import_file's test), so a still or
    # a clip with no width and height is not what its extension says
    sized = bool(info.get("width") and info.get("height"))
    if kind == "audio" and not info["audio"]:
        refusal = UploadRefused("no_audio", "that file has no sound in it")
    elif kind == "video" and (not info["video"] or info.get("still") or not sized):
        refusal = UploadRefused("no_video", "that file has no moving picture in it")
    elif kind == "image" and (not info.get("still") or not sized):
        refusal = UploadRefused("not_an_image", "that file is not a still image")
    if refusal:
        target.unlink(missing_ok=True)
        raise refusal
    from .. import media
    stored = f"/renders/cut/media/{target.name}"
    media.mirror(target, stored.lstrip("/"), account_id, content_type=UPLOAD_TYPES[ext],
                 derive=False)
    row = store.add_media(account_id=account_id, kind=kind,
                          filename=Path(filename).name[:200], media_url=stored,
                          output_path=str(target),
                          seconds=None if kind == "image" else info["seconds"], sha256=sha,
                          dsn=dsn)
    handle = f"asset:{row['id']}"
    store.put_probe(handle, stored, info, account_id=account_id, size_bytes=len(data),
                    sha256=sha, dsn=dsn)
    return {"handle": handle, "row": row, "info": info, "stored": stored, "kind": kind,
            "size": len(data), "sha256": sha}


__all__ = ["AUDIO_TYPES", "VIDEO_TYPES", "IMAGE_TYPES", "UPLOAD_TYPES", "MAX_MEDIA_BYTES",
           "MAX_VIDEO_BYTES", "UploadRefused", "kind_of", "cap_for", "save"]
