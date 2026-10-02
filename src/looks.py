"""The LOOK a prompt is held to -- resolved here, and only here.

The look belongs to the PROJECT, not the brand (2026-10-02, Mike's call): a
film, an ad, a video each carries its own, and the studio has no house
style. `look_block` answers in this order:

1. a project in scope -> ITS look (`projects.look`), or "" when none is
   typed. Never the brand file: a fallback there is how the house style
   came back without anybody noticing, which is the bug this replaced --
   prompts/look_zeropage.txt imposed a horror grade on every run.
2. no project (the nightly walk, the crawl, research) ->
   prompts/look_<brand>.txt when one exists. The night does not invent a
   look of its own.
3. otherwise "".

The project comes from `project_context` (the ContextVar the Create and
Guide routes already set) unless a caller passes one, so the seven readers
-- the scout digest, the research brief, the two scene writers, refgen,
refcheck, reference_needs and the assistant's memory -- follow the project
with no argument threaded through any of them.

Its own module rather than a function on scout.py because shootgen must
read it too, and shootgen importing scout would drag the crawl's
dependencies into every Studio request.
"""
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = PROJECT_ROOT / "prompts"


def look_block(brand: str, project: Optional[dict] = None) -> str:
    """The look text, or "" -- never an error, because a prompt with no
    look is a different run, not a broken one."""
    try:
        if project is None:
            from . import project_context
            project = project_context.current()
        if project:
            look = project.get("look")
            return look.strip() if isinstance(look, str) else ""
    except Exception:
        return ""
    try:
        return (PROMPTS_DIR / f"look_{brand}.txt").read_text().strip()
    except OSError:
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
