"""
The render numbers the by-hand lanes and the composer have to agree on.

WHY THIS IS ITS OWN MODULE, with no imports at all -- not even from this
package. `ops/render_queue.py` has to run under a bare `python3` (the repo
venvs are macOS builds, a Claude session's shell is Linux) without
dragging google-genai in, so the few literals it shares with the app live
here, importable from anywhere because importing it costs nothing.

WHAT CHANGED ON 2026-09-26. This module used to be mostly Runway: the
per-model legal ratios and durations of gen4_turbo / gen4.5 / seedance2_5,
which both src/runway.py and the Runway Unlimited lane checked a claim
against. fal became the only video renderer that day (docs/tasks/
task-fal-only.md), Runway retired Unlimited in June 2026, and both went.
What is left:

- the FRAME SIZES the Studio composer offers a scene ("720:1280") -- a
  scene's shape, stored on its shot, which the keyframe is drawn at;
- the two by-hand lanes' model lists, both None: the generic clip import
  files a clip rendered anywhere, and the Higgsfield MCP's model names are
  its own and published nowhere this repo can read. A lane with no list
  records the model it was told, UNVERIFIED (`model_verified: false` in
  the row), rather than checking it against a list this repo made up.
"""
from __future__ import annotations

from typing import Optional

# The house vertical, as a frame size.
RATIO_9_16 = "720:1280"

# The frames a scene can be written for (the composer's ratio pill,
# GET /api/render-choices). Frame SIZES, so width and height are one choice.
FRAME_SIZES = ("1280:720", "720:1280", "1104:832",
               "832:1104", "960:960", "1584:672")

# The by-hand lanes. None == no list to check a model claim against.
HIGGSFIELD_LANE_MODELS: Optional[dict[str, dict]] = None
MANUAL_LANE_MODELS: Optional[dict[str, dict]] = None

LANE_MODELS: dict[str, Optional[dict]] = {
    "manual": MANUAL_LANE_MODELS,
    "higgsfield": HIGGSFIELD_LANE_MODELS,
}

LANE_RATIO = RATIO_9_16
LANE_DURATION = 10


def models_for(lane: str) -> Optional[dict[str, dict]]:
    """The legal models for a lane, or None where there is no list."""
    return LANE_MODELS.get((lane or "").strip().lower())


def check_model(lane: str, model: str) -> bool:
    """Refuse a model this lane cannot have rendered. True when the claim
    was actually CHECKED, False when there was no list to check it
    against -- the caller writes that distinction into the row."""
    known = models_for(lane)
    if known is None:
        return False
    if (model or "").strip() not in known:
        raise ValueError(
            f"unknown {lane} model {model!r} -- one of {sorted(known)}. "
            f"The scoreboard reads this field, so a typo here becomes a "
            f"measurement of a model that never ran.")
    return True


__all__ = [
    "RATIO_9_16", "FRAME_SIZES",
    "HIGGSFIELD_LANE_MODELS", "MANUAL_LANE_MODELS", "LANE_MODELS",
    "LANE_RATIO", "LANE_DURATION",
    "models_for", "check_model",
]
