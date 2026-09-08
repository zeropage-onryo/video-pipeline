#!/usr/bin/env python3
"""
The render numbers both the adapter and the by-hand lane have to agree on.

WHY THIS IS ITS OWN MODULE, with no imports at all -- not even from this
package. `ops/render_queue.py` has to run under a bare `python3` (the
repo venvs are macOS builds, a Claude session's shell is Linux), and it
must not import `src/runway.py`, which drags google-genai in through
render_assets. So until 2026-09-08 the vertical ratio the manual lane
asks the Runway web app for was a SECOND literal, in src/manual_lane.py,
with a test asserting the two had not drifted. A drift test is a smoke
alarm, not a fix: it tells you the day somebody edits one of the two,
and says nothing about the several hours between the edit and the run.
This module is the fix -- one literal, importable from the script, the
adapter and the app alike, because importing it costs nothing.

WHAT ELSE LIVES HERE, AND WHY IT IS THE SAME PROBLEM. `import` used to
write `--model`, `--ratio` and `--duration` into a `generations` row
unverified: whatever the operator typed at 1am became the tool
scoreboard's record of what was rendered, so a mistyped model silently
became a data point about a model that never ran. Checking a claim needs
the legal values, and the script cannot import the adapter to get them,
which is this module's problem exactly once more. So the per-model legal
values live here too, and both `src/runway.py` and the script read them
from here rather than from each other.

REFUSING RATHER THAN CLAMPING is deliberate. A claim outside the legal
set is not a value to round into range -- it is evidence that the person
filing the clip and the clip itself have come apart, and the whole point
of the row is to say what actually happened. So `check_*` raises and the
import stops before anything is copied or written.

WHAT THIS MODULE DOES NOT KNOW. The Higgsfield lane runs through the
MCP, whose model names are its own (`seedance1_5`) and are published
nowhere this repo can read -- they are not `src/higgsfield.py`'s Cloud
registry under another spelling. A guessed list there would refuse a
model that is perfectly real and break the operator's working lane, so
that lane's models are recorded UNVERIFIED (`HIGGSFIELD_LANE_MODELS`
is None, and the row says `model_verified: false`) rather than checked
against a list this repo made up. Saying "I did not check" in the row is
worth more than a check that is wrong in both directions.
"""
from __future__ import annotations

from typing import Optional

# The platform vertical: 9:16, the one frame every lane in this project
# renders. `src/runway.py`'s DEFAULT_RATIO and the manual lane's
# LANE_RATIO are both THIS, not copies of it.
RATIO_9_16 = "720:1280"

# Runway's documented frame sizes for the gen4 family, off the SDK type
# definitions the rest of src/runway.py was verified against
# (docs.dev.runwayml.com, 2026-08-12 -- the same check that dated the
# model list and the credits/second table). Re-verify on an SDK bump;
# Runway versions these, and a ratio that leaves the list has to leave
# it HERE, where both readers see it at once.
RUNWAY_RATIOS = ("1280:720", "720:1280", "1104:832",
                 "832:1104", "960:960", "1584:672")

# Both gen4 models take a 5s or a 10s generation and nothing between:
# the web app offers two duration chips and the API takes the same two.
# This is why `--duration 7` is a refusal and not a rounding.
RUNWAY_DURATIONS = (5, 10)

RUNWAY_MODELS: dict[str, dict] = {
    "gen4_turbo": {"ratios": RUNWAY_RATIOS, "durations": RUNWAY_DURATIONS,
                   "verified": "2026-08-12"},
    # Same endpoint and the same frame sizes; priced at 12 credits/s
    # rather than 5 (src/runway.py's CREDITS_PER_SECOND), which is a
    # difference the API lane cares about and this one does not.
    "gen4.5": {"ratios": RUNWAY_RATIOS, "durations": RUNWAY_DURATIONS,
               "verified": "2026-08-12"},
}

# The Higgsfield MCP's model names -- see the docstring. None means
# "there is no list to check against", NOT "anything goes": the
# difference is written into the row as `model_verified`.
HIGGSFIELD_LANE_MODELS: Optional[dict[str, dict]] = None

LANE_MODELS: dict[str, Optional[dict]] = {
    "runway": RUNWAY_MODELS,
    "higgsfield": HIGGSFIELD_LANE_MODELS,
}

# What the manual lane asks the Runway web app for. The ratio is
# RATIO_9_16 -- the same object src/runway.py's DEFAULT_RATIO is, so
# there is nothing left to drift. The duration is deliberately NOT
# src/runway.py's DEFAULT_DURATION of 5: on the API every second is a
# credit, and on Explore Mode the queue is the price and the seconds are
# free, so the lane asks for the longest chip. It is also the control the
# web app silently resets to 5s on every page reload (docs/RUNBOOK.md,
# 2026-09-06), which is why `list` prints it as a target on every row.
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


def check_ratio(lane: str, model: str, ratio: Optional[str]) -> bool:
    """Refuse a frame this model does not produce. None ratio == not
    claimed, which is not a claim to be wrong about."""
    known = models_for(lane)
    if known is None or ratio is None:
        return False
    spec = known.get((model or "").strip())
    legal = (spec or {}).get("ratios")
    if not legal:
        return False
    if str(ratio).strip() not in legal:
        raise ValueError(
            f"{model} does not render {ratio!r} -- one of {list(legal)}")
    return True


def check_duration(lane: str, model: str, duration) -> bool:
    """Refuse a length this model does not generate. Refuses rather than
    clamping: a wrong number here is evidence the row and the clip have
    come apart, and rounding it hides exactly that."""
    known = models_for(lane)
    if known is None or duration is None:
        return False
    spec = known.get((model or "").strip())
    legal = (spec or {}).get("durations")
    if not legal:
        return False
    try:
        seconds = int(duration)
    except (TypeError, ValueError):
        raise ValueError(f"duration {duration!r} is not a number of seconds") from None
    if seconds not in legal:
        raise ValueError(
            f"{model} does not generate {seconds}s -- one of {list(legal)}")
    return True


__all__ = [
    "RATIO_9_16", "RUNWAY_RATIOS", "RUNWAY_DURATIONS", "RUNWAY_MODELS",
    "HIGGSFIELD_LANE_MODELS", "LANE_MODELS", "LANE_RATIO", "LANE_DURATION",
    "models_for", "check_model", "check_ratio", "check_duration",
]
