"""
One generated clip, described once and compiled per tool.

The pattern: a Shot is tool-agnostic. Separate renderer functions compile
it into whatever Runway, Veo or Kling currently want. Two reasons this
layer exists rather than storing prompt strings directly:

1. These tools change their prompt vocabulary. When one does, you fix one
   render function instead of rewriting every prompt you have stored.
2. Renderers are testable without spending money. Generative video is slow
   and paid; you want the compile step covered by tests that run in
   milliseconds.

IMPORTANT: the per-tool phrasing below is a starting point. Verify it
against each tool's current documentation before trusting the output —
these vocabularies move. The structure is what is stable, not the words.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

# Controlled vocabulary. Free text here is the thing that makes prompts
# unreproducible and untestable, so it is rejected.
CAMERA = (
    "static",
    "pan_left",
    "pan_right",
    "tilt_up",
    "tilt_down",
    "push_in",
    "pull_out",
    "tracking",
    "handheld",
    "crane_up",
    "crane_down",
    "orbit",
)

SHOT_SIZE = (
    "extreme_wide",
    "wide",
    "medium_wide",
    "medium",
    "medium_close",
    "close",
    "extreme_close",
)

TOOLS = ("runway", "veo", "kling")

# Zero Page Films house style, from prompts/brief.txt and settings.txt.
# Every rendered prompt carries this so generated clips cut against real
# footage without a visible seam.
HOUSE_LOOK = (
    "noir, gritty, high contrast, crushed shadows, desaturated, "
    "warmth only from practical light sources"
)
HOUSE_NEGATIVE = (
    "no subject addressing camera, no text overlays, no logos, "
    "no lens flares, no upbeat or saturated colour grading"
)
HOUSE_ASPECT = "9:16"


@dataclass
class Shot:
    """
    What the edit needs this clip to be. Written once, rendered per tool.

    duration_s is what the cut needs, not what the tool will give you —
    most generate in fixed lengths, so the renderer's job includes asking
    for the nearest available and letting you trim.
    """

    subject: str
    action: str
    camera: str = "static"
    size: str = "medium"
    setting: str = ""
    lighting: str = ""
    duration_s: float = 4.0
    aspect: str = HOUSE_ASPECT
    look: str = HOUSE_LOOK
    negative: str = HOUSE_NEGATIVE
    notes: str = ""
    audio: str = ""      # ambient/SFX direction for models that generate sound (Veo). No dialogue by house style.
    tags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.subject.strip():
            raise ValueError("subject is required")
        if not self.action.strip():
            raise ValueError("action is required")
        if self.camera not in CAMERA:
            raise ValueError(
                f"camera must be one of {CAMERA}, got {self.camera!r}. "
                "Free text is rejected on purpose — it makes prompts "
                "unreproducible."
            )
        if self.size not in SHOT_SIZE:
            raise ValueError(f"size must be one of {SHOT_SIZE}, got {self.size!r}")
        if not 0.5 <= self.duration_s <= 20:
            raise ValueError(f"duration_s out of range: {self.duration_s}")

    def as_dict(self) -> dict:
        return {
            "subject": self.subject,
            "action": self.action,
            "camera": self.camera,
            "size": self.size,
            "setting": self.setting,
            "lighting": self.lighting,
            "duration_s": self.duration_s,
            "aspect": self.aspect,
            "notes": self.notes,
            "audio": self.audio,
            "tags": list(self.tags),
        }


def _readable_size(size: str) -> str:
    return size.replace("_", " ")


def _phrase(*parts: str) -> str:
    """Join non-empty fragments into one clean sentence-ish string."""
    return ", ".join(p.strip() for p in parts if p and p.strip())


# --------------------------------------------------------------------------
# renderers — one per tool, each a pure function of Shot -> str
# --------------------------------------------------------------------------

RUNWAY_CAMERA = {
    "static": "static camera",
    "pan_left": "camera pans left",
    "pan_right": "camera pans right",
    "tilt_up": "camera tilts up",
    "tilt_down": "camera tilts down",
    "push_in": "camera pushes in",
    "pull_out": "camera pulls back",
    "tracking": "tracking shot",
    "handheld": "handheld camera",
    "crane_up": "crane up",
    "crane_down": "crane down",
    "orbit": "camera orbits subject",
}


def render_runway(shot: Shot) -> str:
    """Descriptive single paragraph, camera motion stated plainly."""
    return _phrase(
        f"{_readable_size(shot.size)} shot of {shot.subject}",
        shot.action,
        shot.setting,
        shot.lighting,
        RUNWAY_CAMERA[shot.camera],
        shot.look,
    )


# Veo 3.1 cinematography vocabulary — the standard camera terms Google Cloud's
# "Ultimate prompting guide for Veo 3.1" recommends (dolly / tracking / crane /
# pan / POV). Verify against that guide before changing.
# Updated 2026-08-04 from .claude/skills/video-prompting/references/models/veo3/prompting.md
VEO_CAMERA = {
    "static": "locked-off static shot",
    "pan_left": "slow pan left",
    "pan_right": "slow pan right",
    "tilt_up": "tilt up",
    "tilt_down": "tilt down",
    "push_in": "slow dolly in, pushing toward the subject",
    "pull_out": "slow dolly out, pulling back from the subject",
    "tracking": "tracking shot moving alongside the subject",
    "handheld": "subtle handheld",
    "crane_up": "crane shot rising",
    "crane_down": "crane shot descending",
    "orbit": "arcing orbit around the subject",
}

# Veo's guide says to phrase exclusions as a described scene rather than an
# abstract "no X" list, so the house negatives are rewritten as a positive
# frame description for this model only.
VEO_NEGATIVE = (
    "a clean, unbranded frame with no on-screen text, logos, or lens flares; "
    "the subject faces away from or past the lens and never addresses the camera; "
    "colour stays muted and filmic, never saturated or upbeat"
)


def render_veo(shot: Shot) -> str:
    """
    Veo 3.1's five-part formula:
    [Cinematography] + [Subject] + [Action] + [Context] + [Style & ambiance].
    Aspect/duration are deliberately NOT in the prompt text — Veo's guide says
    keep those as external parameters (see veo_parameters()). Veo generates
    audio, so it's directed explicitly and defaults to no dialogue to match the
    house style.
    """
    cinematography = _phrase(VEO_CAMERA[shot.camera], f"{_readable_size(shot.size)} shot")
    context = _phrase(shot.setting, shot.lighting)
    lines = [
        f"Cinematography: {cinematography}",
        f"Subject: {shot.subject}",
        f"Action: {shot.action}",
    ]
    if context:
        lines.append(f"Context: {context}")
    lines.append(f"Style & ambiance: {shot.look}")
    lines.append(f"Audio: {shot.audio.strip() or 'ambient sound only, no dialogue'}")
    lines.append(f"Avoid: {VEO_NEGATIVE}")
    return "\n".join(lines)


def veo_parameters(shot: Shot) -> dict:
    """The generation params Veo's guide says to keep OUT of the prompt text —
    supply them alongside the prompt, not inside it."""
    return {"aspect_ratio": shot.aspect, "duration_s": shot.duration_s}


KLING_CAMERA = {
    "static": "fixed camera",
    "pan_left": "pan left",
    "pan_right": "pan right",
    "tilt_up": "tilt up",
    "tilt_down": "tilt down",
    "push_in": "zoom in slowly",
    "pull_out": "zoom out slowly",
    "tracking": "follow shot",
    "handheld": "handheld movement",
    "crane_up": "rise upward",
    "crane_down": "descend downward",
    "orbit": "circle around subject",
}


def render_kling(shot: Shot) -> str:
    """Compact positive prompt; negatives are a separate field in the UI."""
    return _phrase(
        f"{_readable_size(shot.size)} shot, {shot.subject} {shot.action}",
        shot.setting,
        shot.lighting,
        KLING_CAMERA[shot.camera],
        shot.look,
    )


RENDERERS: dict[str, Callable[[Shot], str]] = {
    "runway": render_runway,
    "veo": render_veo,
    "kling": render_kling,
}


def render(shot: Shot, tool: str) -> str:
    """Compile a Shot for one tool."""
    if tool not in RENDERERS:
        raise ValueError(f"tool must be one of {tuple(RENDERERS)}, got {tool!r}")
    return RENDERERS[tool](shot)


def render_all(shot: Shot) -> dict[str, str]:
    """Compile for every tool, so you can run the same shot head to head."""
    return {tool: fn(shot) for tool, fn in RENDERERS.items()}


def negative_prompt(shot: Shot) -> str:
    """
    Kling and Runway take negatives as a separate field rather than inline.
    Veo's renderer already embeds it.
    """
    return shot.negative
