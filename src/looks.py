"""The LOOK a prompt is held to -- the PROJECT's, or none.

The look belongs to the project (2026-10-02, Mike's call), and since
2026-10-04 there is no other source: the per-brand files
(prompts/look_zeropage.txt, look_antihero.txt) are deleted. "Even still
you're building the brand and look from scratch" -- a look is typed when a
project starts, never inherited from a house style. `look_block` answers:

1. a project in scope (passed, or `project_context.current()`) -> its
   `projects.look`, or "" when none is typed;
2. anything else -- the nightly walk, the crawl, research -> "".

The project comes from `project_context` (the ContextVar the Create and
Guide routes already set) unless a caller passes one, so every reader --
the two scene writers, refgen, refcheck, reference_needs and the
assistant's memory -- follows the project with no argument threaded
through any of them.

Its own module rather than a function on scout.py because shootgen must
read it too, and shootgen importing scout would drag the crawl's
dependencies into every Studio request.
"""
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = PROJECT_ROOT / "prompts"


def look_block(brand: str = "", project: Optional[dict] = None) -> str:
    """The project's look, or "" -- never an error, because a prompt with
    no look is a different run, not a broken one. `brand` is accepted and
    ignored: a brand has no look of its own any more."""
    try:
        if project is None:
            from . import project_context
            project = project_context.current()
        if project:
            look = project.get("look")
            return look.strip() if isinstance(look, str) else ""
    except Exception:
        pass
    return ""


def unset_note() -> str:
    """What a scene writer reads in the look's place when look_block is
    "": that the absence is deliberate, so it takes the look from the idea
    and the references instead of reaching for a default. Not a style --
    prompts/look_unset.txt names none."""
    try:
        return (PROMPTS_DIR / "look_unset.txt").read_text().strip()
    except OSError:
        return ""
