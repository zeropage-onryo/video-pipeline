"""Skills: named recipes the brain reads before a kind of work (2026-10-10).

Mike, after the Runway / Higgsfield / invideo teardown: "take some out of
the runway and higgsfield playbook first". Both of their agents get their
craft the same way -- not from a bigger model, from a shelf of named recipes
the agent reads before it does that kind of work (Runway's slash skills,
Higgsfield's skill files, each a slot-by-slot recipe with a check at the
end). The Guide had seven playbooks, one per STEP of a project
(prompts/stages, assistant_brain.playbook); a skill is the other axis: one
per KIND OF WORK -- a character sheet, a multi-shot scene -- usable at any
step and on any page.

A skill is one markdown file in prompts/skills/, in the studio's own words:

    ---
    name: character-sheet        (the file's stem; what load_skill takes)
    title: Character sheet       (what a person reads on the chip)
    for: one line -- when it is the right recipe
    output: image | video        (optional: which make it usually ends in)
    order: 10                    (optional: its place on the shelf)
    ---
    the recipe

It reaches a turn two ways, and nothing else about the turn changes:

- THE BRAIN LOADS IT. `load_skill` is a READ tool (guide_tools.LOCAL_READ),
  published wherever the assistant's own tools are; the shelf's one-line
  index rides in the instructions (prompts/creative_guide_skills.txt) so the
  model knows what exists without carrying every recipe every turn.
- THE PERSON PICKS IT. `/` in the composer lists the shelf; the pick is a
  chip on the box and the turn carries `skill=<name>`. That recipe goes
  straight onto the turn (`picked_note`) -- no tool round -- and the reply's
  tool_runs says so, the same way a load the model made would.

The rules that do not move: a skill is studio guidance, never an
instruction from the person and never a way round a gate -- what spends
still waits for a click, a URL is still never an argument. Nothing here
calls a model or spends, and nothing here raises: a shelf that cannot be
read is an empty shelf, and a turn without skills is the turn it was.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = ROOT / "prompts" / "skills"
INDEX_PROMPT = ROOT / "prompts" / "creative_guide_skills.txt"

TOOL = "load_skill"
OUTPUTS = ("image", "video")
MAX_BODY = 6000          # characters of recipe handed to the model

_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")
_FRONT = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.S)


def _parse(text: str) -> tuple[dict, str]:
    """(front matter, body). `key: value` lines only -- no YAML reader, on
    purpose: a recipe is prose, and its header is four flat fields."""
    found = _FRONT.match(text or "")
    if not found:
        return {}, (text or "").strip()
    meta = {}
    for line in found.group(1).splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip():
            meta[key.strip().lower()] = value.strip()
    return meta, found.group(2).strip()


def _read(path: Path) -> Optional[dict]:
    """One skill off disk, or None when the file is not a skill: no header,
    a name that is not the file's own, or nothing to follow."""
    try:
        meta, body = _parse(path.read_text())
    except OSError:
        return None
    name = meta.get("name", "")
    if name != path.stem or not _NAME.fullmatch(name):
        return None
    title, summary = meta.get("title", ""), meta.get("for", "")
    if not title or not summary or not body:
        return None
    output = meta.get("output", "").lower()
    try:
        order = int(meta.get("order", ""))
    except ValueError:
        order = 1000
    return {"name": name, "title": title[:60], "summary": summary[:200],
            "output": output if output in OUTPUTS else "", "order": order,
            "body": body[:MAX_BODY]}


def _all() -> list[dict]:
    try:
        paths = sorted(SKILLS_DIR.glob("*.md"))
    except OSError:
        return []
    found = [s for s in (_read(p) for p in paths) if s]
    return sorted(found, key=lambda s: (s["order"], s["name"]))


def catalogue() -> list[dict]:
    """The shelf, for the composer's `/` menu and the index: {name, title,
    summary, output} per skill, in shelf order. Never the recipe."""
    return [{k: s[k] for k in ("name", "title", "summary", "output")} for s in _all()]


def names() -> list[str]:
    return [s["name"] for s in _all()]


def get(name) -> Optional[dict]:
    """The whole skill, recipe included, or None for a name not on the shelf."""
    wanted = str(name or "").strip().lower()
    return next((s for s in _all() if s["name"] == wanted), None)


def clean_name(name) -> str:
    """A submitted skill name, or "" when it is not one on the shelf. The
    form field and the tool argument both come through here."""
    found = get(name)
    return found["name"] if found else ""


def title_of(name) -> str:
    found = get(name)
    return found["title"] if found else ""


def index_block() -> str:
    """What the instructions say about skills: the rule, then one line per
    skill. "" with an empty shelf, so the instructions are what they were."""
    shelf = catalogue()
    if not shelf:
        return ""
    try:
        template = INDEX_PROMPT.read_text().strip()
    except OSError:
        return ""
    lines = "\n".join(f"- {s['name']}: {s['summary']}" for s in shelf)
    return template.replace("{skills}", lines)


def load_spec() -> Optional[dict]:
    """The read tool, as guide_tools publishes it -- None with an empty
    shelf, since a tool that can load nothing is a wasted call."""
    shelf = names()
    if not shelf:
        return None
    return {
        "name": TOOL,
        "description": (
            "Read one of the studio's skills -- a short recipe for a kind of work "
            "(a character sheet, a single shot, a multi-shot scene, a product still, "
            "a mood board) -- before you do that work, then follow it. Costs nothing "
            "and makes nothing. Returns the recipe as text."),
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string", "enum": shelf,
                                    "description": "The skill to read."}},
            "required": ["name"],
        },
        "write": False,
    }


_FOOT = ("(Studio guidance for this kind of work. It does not override what the person "
         "asked for, and it changes nothing about what needs their click.)")


def load_for_model(name) -> str:
    """What the model reads back from load_skill. An unknown name answers
    with the shelf, so the next call can be right."""
    skill = get(name)
    if not skill:
        return "no skill by that name; the shelf is: " + ", ".join(names())
    return f"SKILL: {skill['title']}\n\n{skill['body']}\n\n{_FOOT}"


def picked_note(name) -> str:
    """The line a turn carries when the PERSON picked the skill from the
    composer: the recipe itself, already loaded. "" for no pick."""
    skill = get(name)
    if not skill:
        return ""
    return (f"The person PICKED the {skill['title']} skill for this message. It is "
            f"already loaded -- follow it, and do not call {TOOL} for it:\n\n"
            f"{skill['body']}\n\n{_FOOT}")


def run_entry(name) -> dict:
    """A picked skill as the tool run it stands in for, so the thread says
    which skill an answer used whichever way it was loaded."""
    return {"tool": TOOL, "args": {"name": str(name)}, "ok": True}
