"""
src/cut/lanes.py -- keyframe lanes on a picture clip (2026-10-01), the
clip Inspector's second gap from the invideo captures
(docs/reference-look/invideo-editor/06-clip-selected-inspector.jpg).

A lane animates one property of ONE clip:

    clip["lanes"] = [{"path": "zoom", "keys": [
        {"frame": 0,  "value": 1.0, "ease": "linear"},
        {"frame": 45, "value": 1.4, "ease": "ease"}]}]

- `frame` is CLIP-RELATIVE (0 is the clip's first frame on the timeline,
  `clip_length` its end), so moving a clip moves its animation with it and
  only split and trim ever have to touch the keys.
- A lane with ONE key is a constant: that is how a static zoom or offset is
  stored. No lane means the property's default.
- `ease` belongs to the key a segment STARTS at: linear, ease (smoothstep),
  or hold (the value stays until the next key -- a cut, not a move).

The properties are deliberately few and all geometric -- what ffmpeg can
evaluate per frame cheaply (render.py: scale with eval=frame, rotate,
overlay x/y). Crop and opacity are STATIC per clip (`clip["crop"]`,
`clip["opacity"]`), as they are in invideo's Inspector.

Pure module: no I/O. web/src/lib/cut/lanes.ts is its twin for the preview;
tests pin both to the same numbers.
"""
from __future__ import annotations

from typing import Any, Optional

# path -> (min, max, default). x / y are fractions of the CANVAS (0.5 moves
# the picture half a frame right / down); zoom 1 is the clip fitted to the
# canvas; rotation is degrees, clockwise.
PATHS: dict[str, tuple[float, float, float]] = {
    "zoom": (0.1, 4.0, 1.0),
    "x": (-1.0, 1.0, 0.0),
    "y": (-1.0, 1.0, 0.0),
    "rotation": (-360.0, 360.0, 0.0),
}
EASES = ("linear", "ease", "hold")
CROP_SIDES = ("left", "right", "top", "bottom")
MAX_CROP = 0.45          # per side; two opposite sides together stay under 0.9


def default(path: str) -> float:
    return PATHS[path][2]


def lane(clip: dict, path: str) -> Optional[dict]:
    for ln in clip.get("lanes") or []:
        if ln.get("path") == path:
            return ln
    return None


def _shape(u: float, ease: str) -> float:
    if ease == "hold":
        return 0.0
    if ease == "ease":
        return u * u * (3 - 2 * u)
    return u


def value_at(keys: list[dict], frame: float, fallback: float) -> float:
    """The value at a clip-relative frame: held before the first key and
    after the last, interpolated between, by the starting key's ease."""
    if not keys:
        return fallback
    if frame <= keys[0]["frame"]:
        return float(keys[0]["value"])
    for a, b in zip(keys, keys[1:]):
        if frame < b["frame"]:
            span = b["frame"] - a["frame"]
            u = (frame - a["frame"]) / span if span else 1.0
            return float(a["value"]) + (float(b["value"]) - float(a["value"])) * _shape(u, a.get("ease", "linear"))
    return float(keys[-1]["value"])


def value(clip: dict, path: str, frame: float) -> float:
    ln = lane(clip, path)
    return value_at(ln["keys"] if ln else [], frame, default(path))


def animated(clip: dict, path: str) -> bool:
    """Does this property differ from its default anywhere in the clip?"""
    ln = lane(clip, path)
    if not ln or not ln.get("keys"):
        return False
    return any(abs(float(k["value"]) - default(path)) > 1e-9 for k in ln["keys"])


def _num(x: float) -> str:
    return f"{float(x):.6g}"


def expr(keys: list[dict], fps: int, fallback: float) -> str:
    """An ffmpeg expression in `t` (clip-relative seconds, after
    setpts=PTS-STARTPTS) that is value_at -- the same piecewise curve,
    nested if()s, innermost last."""
    if not keys:
        return _num(fallback)
    if len(keys) == 1:
        return _num(keys[0]["value"])
    out = _num(keys[-1]["value"])
    for a, b in reversed(list(zip(keys, keys[1:]))):
        ta, tb = a["frame"] / fps, b["frame"] / fps
        va, vb = float(a["value"]), float(b["value"])
        u = f"((t-{_num(ta)})/{_num(tb - ta)})" if tb > ta else "1"
        ease = a.get("ease", "linear")
        shaped = "0" if ease == "hold" else (f"({u}*{u}*(3-2*{u}))" if ease == "ease" else u)
        seg = f"{_num(va)}+({_num(vb - va)})*{shaped}"
        out = f"if(lt(t,{_num(tb)}),{seg},{out})"
    return f"if(lt(t,{_num(keys[0]['frame'] / fps)}),{_num(keys[0]['value'])},{out})"


# --------------------------------------------------------------------------
# what split and trim do to the keys
# --------------------------------------------------------------------------

def _boundary(keys: list[dict], frame: int, path: str, ease: str = "linear") -> dict:
    return {"frame": frame, "value": round(value_at(keys, frame, default(path)), 6), "ease": ease}


def window(lanes: list[dict], start: int, end: int) -> list[dict]:
    """The lanes of the part of a clip from `start` to `end` (clip-relative
    frames), rebased so `start` is the new 0. A lane that moves across an
    edge gains a key there carrying the value it had at that frame, so the
    piece looks as that stretch of the whole did -- EXACTLY for linear and
    hold segments; a cut through an eased segment re-eases the shorter
    piece (smoothstep over a new span), which is close but not identical.
    The values at every key and edge are always exact."""
    out = []
    for ln in lanes or []:
        keys = sorted(ln.get("keys") or [], key=lambda k: k["frame"])
        if not keys:
            continue
        path = ln["path"]
        if len(keys) == 1:
            out.append({"path": path, "keys": [{**keys[0], "frame": 0}]})
            continue
        inside = [dict(k, frame=k["frame"] - start) for k in keys if start < k["frame"] < end]
        head = _boundary(keys, start, path,
                         ease=next((k.get("ease", "linear") for k in reversed(keys) if k["frame"] <= start), "linear"))
        head["frame"] = 0
        tail = _boundary(keys, end, path)
        tail["frame"] = end - start
        new = [head, *inside]
        # an edge key only where the lane is still moving across that edge
        if any(k["frame"] >= end for k in keys) and tail["frame"] > new[-1]["frame"]:
            new.append(tail)
        # a lane that turned out flat over this window is a constant
        if all(abs(k["value"] - new[0]["value"]) < 1e-9 for k in new):
            new = [{"frame": 0, "value": new[0]["value"], "ease": "linear"}]
        out.append({"path": path, "keys": new})
    return out


def check(clip: dict, length: int, where: str) -> list[str]:
    """The validator's reasons for this clip's lanes, crop and opacity."""
    out: list[str] = []
    lanes = clip.get("lanes")
    if lanes is not None:
        if not isinstance(lanes, list):
            return [f"{where}: lanes must be a list"]
        seen = set()
        for ln in lanes:
            path = ln.get("path") if isinstance(ln, dict) else None
            if path not in PATHS:
                out.append(f"{where}: lane path must be one of {list(PATHS)}, got {path!r}")
                continue
            if path in seen:
                out.append(f"{where}: two lanes for {path}")
            seen.add(path)
            lo, hi, _ = PATHS[path]
            keys = ln.get("keys")
            if not isinstance(keys, list) or not keys:
                out.append(f"{where}: lane {path} has no keys")
                continue
            prev = None
            for k in keys:
                f, v = k.get("frame"), k.get("value")
                if not isinstance(f, int) or isinstance(f, bool) or not 0 <= f <= length:
                    out.append(f"{where}: {path} key at {f!r} is outside the clip (0-{length})")
                    continue
                if not isinstance(v, (int, float)) or isinstance(v, bool) or not lo <= v <= hi:
                    out.append(f"{where}: {path} must be {lo:g} to {hi:g}, got {v!r}")
                if k.get("ease", "linear") not in EASES:
                    out.append(f"{where}: {path} ease must be one of {list(EASES)}")
                if prev is not None and f <= prev:
                    out.append(f"{where}: {path} keys must be in frame order, one per frame")
                prev = f
    crop = clip.get("crop")
    if crop is not None:
        if not isinstance(crop, dict) or set(crop) - set(CROP_SIDES):
            out.append(f"{where}: crop is {{left, right, top, bottom}}")
        else:
            for side in CROP_SIDES:
                v = crop.get(side, 0)
                if not isinstance(v, (int, float)) or isinstance(v, bool) or not 0 <= v <= MAX_CROP:
                    out.append(f"{where}: crop {side} must be 0 to {MAX_CROP:g}, got {v!r}")
            if crop.get("left", 0) + crop.get("right", 0) >= 0.9 or crop.get("top", 0) + crop.get("bottom", 0) >= 0.9:
                out.append(f"{where}: the crop leaves nothing of the picture")
    opacity = clip.get("opacity")
    if opacity is not None and (not isinstance(opacity, (int, float)) or isinstance(opacity, bool)
                                or not 0 <= opacity <= 1):
        out.append(f"{where}: opacity must be 0 to 1, got {opacity!r}")
    return out


def has_look(clip: dict) -> bool:
    """Does the render need the transform path for this clip at all?"""
    if any(animated(clip, p) for p in PATHS):
        return True
    op = clip.get("opacity")
    return op is not None and op < 1


def summary(clip: dict) -> dict[str, Any]:
    """{path: number of keys} for lanes that animate -- for the timeline's
    diamonds and the agent's read of the doc."""
    return {ln["path"]: len(ln.get("keys") or []) for ln in clip.get("lanes") or []
            if len(ln.get("keys") or []) > 1}
