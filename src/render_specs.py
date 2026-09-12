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

# --- THE REFERENCE LANE (2026-09-12) ---------------------------------------
# gen4_turbo and gen4.5 cannot carry a reference image at all: their SDK
# type declares `promptImage` entries as `position: Required[Literal["first"]]`
# and offers no reference field, so on those two models a shot's `refs`
# have exactly one route into the render -- baked into the keyframe's
# pixels by Nano. Seedance is the family that takes references directly
# ("omit position for reference images"), which is why it is registered
# here rather than left to the Higgsfield lane.
#
# Its frame sizes are a DIFFERENT list from the gen4 family's, and this
# is the one fact that makes the lane usable: 720:1280 -- RATIO_9_16, the
# platform vertical -- is in both, so switching a render to the reference
# lane does not change the frame anything downstream was cut for.
# Grouped BY RESOLUTION TIER, not flat, because Seedance's rate card is
# quoted per tier and the request only ever states a frame -- so the
# frame has to be able to name its tier. Grouped rather than derived from
# the numbers: the short side does not identify the tier (992:432 is a
# 480p frame whose short side is 432, and 752:560's is 560), so any
# arithmetic shortcut here prices real frames wrongly. These are the
# three rows of six the SDK lists, in its order.
SEEDANCE_2_5_RATIOS_BY_TIER: dict[str, tuple[str, ...]] = {
    "480p": ("992:432", "854:480", "752:560", "640:640", "560:752", "480:854"),
    "720p": ("1470:630", "1280:720", "1112:834", "960:960", "834:1112", "720:1280"),
    "1080p": ("2206:946", "1920:1080", "1664:1248", "1440:1440", "1248:1664",
              "1080:1920"),
}

SEEDANCE_2_5_RATIOS = tuple(
    ratio for tier in SEEDANCE_2_5_RATIOS_BY_TIER.values() for ratio in tier)

# Unlike the gen4 pair's two duration chips, Seedance's SDK type declares
# a bare `duration: int` -- there is no published list of legal lengths to
# check a claim against. None says exactly that, and `check_duration`
# already reads a missing list as "not checked" rather than as "nothing is
# legal". Inventing a range here would refuse a length that is perfectly
# real, which is the mistake HIGGSFIELD_LANE_MODELS exists to not repeat.
SEEDANCE_DURATIONS = None

RUNWAY_MODELS: dict[str, dict] = {
    "gen4_turbo": {"ratios": RUNWAY_RATIOS, "durations": RUNWAY_DURATIONS,
                   "verified": "2026-08-12"},
    # Same endpoint and the same frame sizes; priced at 12 credits/s
    # rather than 5 (src/runway.py's CREDITS_PER_SECOND), which is a
    # difference the API lane cares about and this one does not.
    "gen4.5": {"ratios": RUNWAY_RATIOS, "durations": RUNWAY_DURATIONS,
               "verified": "2026-08-12"},
    # The reference lane. Priced by output RESOLUTION rather than by model
    # name, which is why src/runway.py costs it from the ratio instead of
    # from a single credits/second number like the gen4 pair.
    "seedance2_5": {"ratios": SEEDANCE_2_5_RATIOS, "durations": SEEDANCE_DURATIONS,
                    "references": True, "verified": "2026-09-12"},
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


def seedance_tier(ratio: Optional[str]) -> Optional[str]:
    """Which resolution tier a Seedance frame bills at, or None for a
    frame this module does not recognise. The caller decides what an
    unknown frame costs -- src/runway.py charges it at the dearest tier,
    because an estimate a person approves against should never read low."""
    wanted = (ratio or "").strip()
    for tier, ratios in SEEDANCE_2_5_RATIOS_BY_TIER.items():
        if wanted in ratios:
            return tier
    return None


def takes_references(lane: str, model: str) -> bool:
    """Whether this model accepts reference images alongside the prompt.

    False is the honest answer for every gen4 model and for any lane with
    no list to check -- a caller that attaches references to a model that
    cannot read them has not enriched the render, it has silently dropped
    them, and this is the function that lets the caller say so in the row
    instead of finding out from the output."""
    known = models_for(lane)
    if known is None:
        return False
    spec = known.get((model or "").strip()) or {}
    return bool(spec.get("references"))


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
    "SEEDANCE_2_5_RATIOS", "SEEDANCE_2_5_RATIOS_BY_TIER", "SEEDANCE_DURATIONS",
    "seedance_tier", "takes_references",
    "HIGGSFIELD_LANE_MODELS", "LANE_MODELS", "LANE_RATIO", "LANE_DURATION",
    "models_for", "check_model", "check_ratio", "check_duration",
]
