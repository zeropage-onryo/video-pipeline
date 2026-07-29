#!/usr/bin/env python3
"""
Turns a generative slot's loose description into prompts for all three
tools.

Two layers, deliberately not collapsed: the LLM's only job is turning
the loose description into a well-formed Shot (parse_shot_response) --
structured output into the dataclass, nothing more. shot.py's
render_all() then compiles it, pure and untouched, no model call
anywhere near it. That split means a bad prompt is either a bad Shot
(the model's fault, visible in the JSON) or a bad compile (the
renderer's fault, catchable in a test) -- collapsing the two would make
it impossible to tell which broke.
"""
import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from google import genai

from . import db
from . import generative as gen
from .gemini_utils import generate_with_retry, strip_fences
from .shot import CAMERA, SHOT_SIZE, Shot, render_all

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = PROJECT_ROOT / "prompts"

MODEL = "gemini-3-flash-preview"

SHOT_FIELDS = ("subject", "action", "camera", "size", "setting", "lighting", "duration_s")


def format_examples(entries: list[dict]) -> str:
    """
    Prior shots that landed, for the model to match style against --
    the same retrieval pattern as feeding past pitch picks into the
    pitch prompt: your own record, not general advice. Empty until
    generations get logged (G3), so an empty list renders to nothing.
    """
    if not entries:
        return ""
    lines = ["PRIOR SHOTS THAT WORKED (your own record -- match this style when it fits):"]
    for e in entries:
        lines.append(f"- [{e['tool']}, {e['attempts']} attempt(s)] \"{e['prompt']}\"")
    lines.append("")
    return "\n".join(lines)


def build_shot_prompt(description: str, examples: list[dict]) -> str:
    template = (PROMPTS_DIR / "shot_prompt.txt").read_text()
    return (
        template
        .replace("{description}", description)
        .replace("{camera_options}", ", ".join(CAMERA))
        .replace("{size_options}", ", ".join(SHOT_SIZE))
        .replace("{examples_block}", format_examples(examples))
    )


def parse_shot_response(text: str) -> Shot:
    """
    The critical seam: turns the model's raw text into a Shot. A bad
    camera value or a missing subject raises ValueError here, from
    Shot.__post_init__ itself -- not a second, duplicate validation.
    """
    data = json.loads(strip_fences(text))
    kwargs = {k: v for k, v in data.items() if k in SHOT_FIELDS}
    return Shot(**kwargs)


def structure_shot(description: str, examples: list[dict], client, model: str = MODEL) -> Shot:
    prompt = build_shot_prompt(description, examples)
    response_text = generate_with_retry(client, model, prompt)
    return parse_shot_response(response_text)


def generate_prompts_for_slot(
    description: str,
    idea_id=None,
    slot_index=None,
    client=None,
    model: str = MODEL,
    db_path=None,
) -> dict:
    """
    One generative slot in, three tool prompts out. Persists the
    resolved Shot as an open shot in the database (generative.add_shot)
    so later generation attempts (G3) can be logged against it.
    """
    kwargs = {"path": db_path} if db_path is not None else {}
    examples = gen.winning_prompts(limit=5, **kwargs)

    shot = structure_shot(description, examples, client, model=model)

    shot_id = gen.add_shot(shot, idea_id=idea_id, slot_index=slot_index, **kwargs)
    prompts = render_all(shot)

    return {"shot_id": shot_id, "shot": shot.as_dict(), "prompts": prompts}


def main(db_path=None):
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Turn a generative slot's loose description into prompts for all three tools."
    )
    parser.add_argument("description", help="The edit's loose description of the shot")
    parser.add_argument("--idea-id", type=int, default=None,
                        help="ideas.id this shot serves, if known")
    parser.add_argument("--slot-index", type=int, default=None,
                        help="position of this slot in the edit's edit_list, if known")
    args = parser.parse_args()

    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("GOOGLE_API_KEY (or GEMINI_API_KEY) not set", file=sys.stderr)
        sys.exit(1)

    kwargs = {"path": db_path} if db_path is not None else {}
    db.init_db(**kwargs)
    gen.init(**kwargs)

    client = genai.Client(api_key=api_key)
    result = generate_prompts_for_slot(
        args.description, idea_id=args.idea_id, slot_index=args.slot_index,
        client=client, db_path=db_path,
    )

    print(f"Shot {result['shot_id']} recorded")
    for tool, prompt in result["prompts"].items():
        print(f"\n--- {tool} ---")
        print(prompt)


if __name__ == "__main__":
    main()
