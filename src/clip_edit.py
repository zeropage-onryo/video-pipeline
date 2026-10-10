"""
Edit a clip by instruction -- one frame first, then the whole clip
(2026-10-10, docs/tasks/task-mcp-studio-v2.md step 2c).

A video edit is the dearest thing an instruction can buy here, and the one
most likely to come back not as meant. So it is two spends, each quoted
and approved on its own:

1. FRAME. One frame is pulled from the clip with ffmpeg (free, on this
   server) and edited as a still by the studio's identity-keeping image
   editor (`FRAME_EFFECT`). Cents. The person looks at it.
2. VIDEO. The instruction is run on the whole clip by one of MODELS, and
   it is only taken with the `gen:<id>` of a frame stage 1 made from THIS
   clip with THIS instruction -- the proof somebody had a still to look at
   before the dollars. Where the model takes a reference image, that
   approved frame is handed to it; where it does not (`frame: None`), the
   frame was a preview of the instruction and the quote says so.

THE MODELS are a dated table, read on CHECKED off each endpoint's OpenAPI
schema and its own price text / `endpointBilling` record. The full survey
of fal's instruction editors that day -- sixteen of them, with why each of
the others is not here -- is in the task doc; re-read it before adding one.
They are deliberately NOT rows of `effects.EFFECTS`: there they would be
reachable through `apply_effect` in one call, with no frame.

Nothing here spends or writes: `effects.run` does both, for the frame
(a real EFFECTS row) and for the video (its `row` + `endpoint_body`).
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Optional

CHECKED = "2026-10-10"
FRAME_EFFECT = "nano-banana-edit"       # effects.EFFECTS: keeps faces and identity
STAGES = ("frame", "video")
MB = 1024 * 1024

MODELS: dict[str, dict] = {
    "kling-o1": {
        "label": "Kling O1 Edit",
        "note": "natural-language edit of subjects, settings and style; the approved frame "
                "is its look reference",
        "endpoint": "fal-ai/kling-video/o1/standard/video-to-video/edit",
        "usd_per_second": 0.126,
        # the schema's own limits: 3.0-10.05s, each side 720-2160px, 24-60fps, 200MB
        "min_seconds": 3.0, "max_seconds": 10.05, "min_side": 720, "max_side": 2160,
        "min_fps": 24, "max_fps": 60, "max_bytes": 200 * MB, "containers": (".mp4", ".mov"),
        "frame": "reference", "audio": True,
        "source": "https://fal.ai/models/fal-ai/kling-video/o1/standard/video-to-video/edit",
    },
    "kling-o1-pro": {
        "label": "Kling O1 Edit Pro",
        "note": "as kling-o1 on the Pro tier: more faithful, a third dearer",
        "endpoint": "fal-ai/kling-video/o1/video-to-video/edit",
        "usd_per_second": 0.168,
        "min_seconds": 3.0, "max_seconds": 10.05, "min_side": 720, "max_side": 2160,
        "min_fps": 24, "max_fps": 60, "max_bytes": 200 * MB, "containers": (".mp4", ".mov"),
        "frame": "reference", "audio": True,
        "source": "https://fal.ai/models/fal-ai/kling-video/o1/video-to-video/edit",
    },
    "flux-3": {
        "label": "FLUX.3 Edit Video",
        "note": "the cheap one: the clip re-rendered at 720p keeping motion, timing and "
                "framing; takes the instruction only, so the frame is a preview, not a steer",
        "endpoint": "blackforestlabs/flux-3/edit-video",
        "usd_per_second": 0.03,
        # "MP4, under 50 MB and under 15 seconds"
        "min_seconds": 0.0, "max_seconds": 15.0, "max_bytes": 50 * MB, "containers": (".mp4",),
        "frame": None, "audio": False,
        "source": "https://fal.ai/models/blackforestlabs/flux-3/edit-video",
    },
}
MODEL_NAMES = tuple(MODELS)
DEFAULT_MODEL = "kling-o1"
INSTRUCTION_MAX = 1500


def spec(model: str) -> dict:
    row = MODELS.get((model or "").strip())
    if row is None:
        raise ValueError(f"model must be one of {list(MODEL_NAMES)}, got {model!r}")
    return row


def normal(instruction: str) -> str:
    """The instruction as it is compared, quoted and sent: whitespace
    collapsed. Stage 2 must carry the same one stage 1's frame was made
    with."""
    text = " ".join((instruction or "").split())
    if not text:
        raise ValueError("say what to change -- e.g. \"make the jacket red\"")
    if len(text) > INSTRUCTION_MAX:
        raise ValueError(f"the instruction is at most {INSTRUCTION_MAX} characters")
    return text


def check_clip(model: str, probe: dict, *, suffix: str = "",
               size_bytes: Optional[int] = None) -> None:
    """Refuse, before any quote, a clip the model's published limits would
    refuse after the hold. Raises ValueError naming the limit."""
    m = spec(model)
    seconds = float(probe.get("seconds") or 0)
    if seconds < m["min_seconds"]:
        raise ValueError(f"{m['label']} takes clips of at least {m['min_seconds']:g}s; "
                         f"this one is {seconds:g}s")
    if seconds > m["max_seconds"]:
        raise ValueError(f"{m['label']} takes clips up to {m['max_seconds']:g}s; "
                         f"this one is {seconds:g}s")
    w, h = int(probe.get("width") or 0), int(probe.get("height") or 0)
    if m.get("min_side") and w and h and min(w, h) < m["min_side"]:
        raise ValueError(f"{m['label']} needs at least {m['min_side']}px on the short side; "
                         f"this clip is {w}x{h}")
    if m.get("max_side") and max(w, h) > m["max_side"]:
        raise ValueError(f"{m['label']} takes at most {m['max_side']}px on the long side; "
                         f"this clip is {w}x{h}")
    fps = float(probe.get("fps") or 0)
    if fps and m.get("min_fps") and fps < m["min_fps"] - 0.1:
        raise ValueError(f"{m['label']} takes {m['min_fps']}-{m['max_fps']}fps; "
                         f"this clip is {fps:g}fps")
    if fps and m.get("max_fps") and fps > m["max_fps"] + 0.1:
        raise ValueError(f"{m['label']} takes {m['min_fps']}-{m['max_fps']}fps; "
                         f"this clip is {fps:g}fps")
    suffix = (suffix or "").lower()
    if suffix and suffix not in m["containers"]:
        raise ValueError(f"{m['label']} takes {' / '.join(m['containers'])} files, "
                         f"not {suffix}")
    if size_bytes and size_bytes > m["max_bytes"]:
        raise ValueError(f"{m['label']} takes files up to {m['max_bytes'] // MB}MB; "
                         f"this one is {size_bytes // MB}MB")


def video_usd(model: str, probe: dict) -> float:
    """Per second of generated video, which is the clip's own length."""
    return round(float(probe["seconds"]) * spec(model)["usd_per_second"], 4)


def frame_usd() -> float:
    from . import effects
    return effects.quote_usd(FRAME_EFFECT, effects.check_options(FRAME_EFFECT, {}))


def options_for(probe: dict, *, suffix: str = "", size_bytes: Optional[int] = None) -> list[dict]:
    """Every model against THIS clip: its price, or why it cannot take it
    -- what the frame stage's quote shows, so the dear half is known before
    the cheap half is bought."""
    out = []
    for name, m in MODELS.items():
        row = {"model": name, "label": m["label"], "note": m["note"],
               "frame_steers": bool(m["frame"]), "checked": CHECKED, "page": m["source"]}
        try:
            check_clip(name, probe, suffix=suffix, size_bytes=size_bytes)
            row["usd"] = video_usd(name, probe)
        except ValueError as e:
            row["cannot"] = str(e)
        out.append(row)
    return out


def frame_prompt(instruction: str) -> str:
    """The still's edit: the instruction, and nothing else changed -- a
    frame that drifts elsewhere tells the person nothing about the edit."""
    return (f"{instruction.rstrip('.')}. Keep everything else in the frame exactly as it "
            "is: the same framing, people, objects and light.")


def video_body(model: str, video_url: str, instruction: str, *,
               frame_url: Optional[str] = None, keep_audio: bool = True) -> tuple[str, dict]:
    """(endpoint, body) for the video stage, in each model's wire shape."""
    m = spec(model)
    body: dict[str, Any] = {"video_url": video_url}
    if m["frame"] == "reference" and frame_url:
        # Kling names reference images in the prompt, in order: @Image1
        body["prompt"] = (f"{instruction.rstrip('.')}. Match @Image1, which shows how one "
                          "frame of this video should look after the edit.")
        body["image_urls"] = [frame_url]
    else:
        body["prompt"] = instruction
    if m["audio"]:
        body["keep_audio"] = bool(keep_audio)
    return m["endpoint"], body


def extract_frame(target: str, at: float, out_path: Path) -> Path:
    """One frame of a clip (a local path or a URL) as a JPEG, by ffmpeg.
    Raises ValueError when no frame comes out."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-ss", f"{max(0.0, float(at)):.3f}", "-i", str(target),
             "-frames:v", "1", "-q:v", "2", str(out_path)],
            capture_output=True, text=True, timeout=120, check=True)
    except Exception as e:
        raise ValueError(f"could not take a frame from the clip ({type(e).__name__})") from e
    if not out_path.is_file() or out_path.stat().st_size == 0:
        raise ValueError("could not take a frame from the clip (nothing was decoded there)")
    return out_path


__all__ = ["CHECKED", "FRAME_EFFECT", "STAGES", "MODELS", "MODEL_NAMES", "DEFAULT_MODEL",
           "spec", "normal", "check_clip", "video_usd", "frame_usd", "options_for",
           "frame_prompt", "video_body", "extract_frame"]
