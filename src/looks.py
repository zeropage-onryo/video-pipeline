"""The per-brand LOOK -- prompts/look_<brand>.txt -- in one place.

Distilled from the two reference clips Mike handed over on 2026-09-04
(docs/reference-look/): teal-and-amber, one red accent, wet, hazed,
glossy. Three prompts read it -- the crawl digest, the research brief
and the scene brief -- because the failure it fixes lived at every
stage: sparks were written blind to it, and the scene brief's house
style ("raw handheld, matte, NOT glossy") then overrode any reference
that carried it. One file per brand, edited there, never in Python.

Its own module rather than a function on scout.py because shootgen must
read it too, and shootgen importing scout would drag the crawl's
dependencies into every Studio request.
"""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = PROJECT_ROOT / "prompts"


def look_block(brand: str) -> str:
    """The look text for a brand, or a one-line note when the file is
    missing -- never an error, because a prompt with no look is a worse
    night, not a broken one."""
    try:
        return (PROMPTS_DIR / f"look_{brand}.txt").read_text().strip()
    except OSError:
        return f"(no look file for this brand -- prompts/look_{brand}.txt)"
