"""
The uncanny judge — Zero Page's ON-BRAND GATE.

This is the check that makes Zero Page safe to put on autopilot. It scores a
concept against a FIXED rubric (not the creator's history, the way taste_judge
does), so it works from day one, before there is any grading data: is the
first frame uncanny, is it grounded-not-glossy, does it ride a real format,
and is it free of a RECURRING STAR. Those are the four properties that define
a Zero Page video, and they are checkable — which is the whole reason Zero
Page can post unsupervised and ANTIHERO cannot.

The fourth one was called `faceless` until 2026-09-02, and the name was the
bug. Zero Page was never a no-humans channel: faces are fine, and a stranger
in close-up is a perfectly good Zero Page frame. What must never happen is a
person the audience meets twice — a recurring star turns the format engine
into Michael's personal account, which is what ANTIHERO already is. Read as
"no faces", the gate held concept 167 for ending on a stranger's reaction:
correct-looking, and wrong about the brand (Mike's call).

Fail-closed, on purpose. taste_judge degrades to a NEUTRAL 5.0 because it only
ranks a slate. This one GATES posting, so a missing key / bad reply degrades to
NOT PASSED (graded=False, passed=False) — the pipeline must never auto-post a
concept it couldn't actually judge. The one LLM call is isolated and never
raises.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from . import accounts, preprod
from .gemini_utils import generate_with_retry, strip_fences

MODEL = os.environ.get("GEMINI_MODEL", "gemini-3-flash-preview")
PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

# Gate thresholds. overall must clear PASS_OVERALL, and the two properties that
# actually define the brand (an uncanny hook, and grounded-not-glossy realism)
# have hard floors — a gorgeous glossy clip or a pretty-but-not-wrong clip is
# not a Zero Page video no matter how high its overall.
PASS_OVERALL = 7.0
HOOK_FLOOR = 6.0
GROUNDED_FLOOR = 6.0
NO_STAR_FLOOR = 6.0


def _clamp(v) -> float:
    try:
        return max(0.0, min(10.0, float(v)))
    except (TypeError, ValueError):
        return 0.0


def _shots_str(concept: dict) -> str:
    """The generation prompts, one per shot -- the text that is actually
    sent to Nano and Runway."""
    lines = []
    for i, shot in enumerate(concept.get("shots") or [], start=1):
        prompt = (shot.get("prompt") or shot.get("written_prompt") or "").strip()
        if not prompt:
            continue
        lines.append(f"Shot {shot.get('n', i)} "
                     f"({shot.get('type') or 'shot'}): {prompt}")
    return "\n".join(lines)


def _concept_str(concept: dict) -> str:
    """Summary lines AND the shot prompts.

    The judge used to read four summary lines and nothing else, which
    made it a grader of loglines rather than of videos. Concept 167
    (2026-09-02) is the proof: it scored the star property 8.0 with the
    note "maintains faceless anonymity through POV" while the prompt
    under it read "end on his wide-eyed reaction" -- and the keyframe
    came back with a face filling the top third of the frame. The
    logline described one video; the thing that got rendered was
    another. (A stranger's face is fine here. The judge agreeing with a
    logline it never checked is not.)

    So the prompts go in, and the template tells the judge they win
    when the two disagree. Camera moves stay in the prompt untouched --
    they are how the shot is directed and the image generator reads
    them -- the judge is simply told to score every frame a move passes
    through instead of only the one it opens on.

    Degrades to the old behaviour when there are no prompts yet: an
    early-stage concept is still judgeable on its summary, and refusing
    would fail a gate that is meant to fail closed only on ERRORS.
    """
    parts = [f"Title: {concept.get('title')}",
             f"Format: {concept.get('format') or '(unspecified)'}",
             f"Hook: {concept.get('hook')}",
             f"Logline: {concept.get('logline')}"]
    shots = _shots_str(concept)
    if shots:
        parts.append("SHOT PROMPTS (what actually gets generated):\n" + shots)
    else:
        parts.append("SHOT PROMPTS: none written yet -- judge the summary above.")
    return "\n".join(parts)


def build_prompt(concept: dict) -> str:
    template = (PROMPTS_DIR / "uncanny_judge_prompt.txt").read_text()
    return template.replace("{concept}", _concept_str(concept))


def _client():
    from google import genai
    return genai.Client(api_key=os.environ.get("GEMINI_API_KEY")
                        or os.environ.get("GOOGLE_API_KEY"))


def _decide(scores: dict) -> bool:
    """The gate: overall clears the bar AND the defining properties clear their
    floors. This is what autopilot checks before auto-posting."""
    return (scores["overall"] >= PASS_OVERALL
            and scores["uncanny_hook"] >= HOOK_FLOOR
            and scores["grounded"] >= GROUNDED_FLOOR
            and scores["no_recurring_star"] >= NO_STAR_FLOOR)


def _blocked(reason: str) -> dict:
    """Fail-closed result — did not pass, and says why."""
    return {"uncanny_hook": 0.0, "grounded": 0.0, "format_fit": 0.0,
            "no_recurring_star": 0.0, "overall": 0.0, "reasons": [reason],
            "graded": False, "passed": False}


def score_concept(concept: dict, gemini_client=None) -> dict:
    """Score one Zero Page concept on the four brand properties and decide
    whether it clears the gate. Never raises; a failure fails CLOSED."""
    try:
        client = gemini_client or _client()
        raw = generate_with_retry(client, MODEL, build_prompt(concept),
                                  stage="uncanny_judge")
        data = json.loads(strip_fences(raw))
        scores = {
            "uncanny_hook": _clamp(data.get("uncanny_hook")),
            "grounded": _clamp(data.get("grounded")),
            "format_fit": _clamp(data.get("format_fit")),
            "no_recurring_star": _clamp(data.get("no_recurring_star")),
        }
        scores["overall"] = _clamp(data.get(
            "overall", sum(scores.values()) / 4))
        scores["reasons"] = [str(r) for r in (data.get("reasons") or [])][:4]
        scores["graded"] = True
        scores["passed"] = _decide(scores)
        return scores
    except Exception as e:
        return _blocked(f"uncanny judge unavailable ({e}) — held, not auto-posted")


def gate(concept: dict, gemini_client=None) -> bool:
    """Convenience: True only if this concept is a ship-it-unsupervised Zero
    Page video. The single call autopilot makes."""
    return score_concept(concept, gemini_client=gemini_client)["passed"]


def rank(concepts: list[dict], gemini_client=None) -> list[dict]:
    """Score every concept and return them best-first (stable)."""
    scored = [{**c, "uncanny": score_concept(c, gemini_client=gemini_client)}
              for c in concepts]
    return sorted(scored, key=lambda c: c["uncanny"]["overall"], reverse=True)


def main(argv=None, account_id: Optional[int] = None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(
        description="Score recent Zero Page concepts on the on-brand (uncanny) gate.")
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--concept-id", type=int)
    parser.add_argument(
        "--account", default=None,
        help=(
            "The account to act as, by slug (zeropage / antihero). "
            "Defaults to the oldest account on the database -- an "
            "unattended run has no session, and acting as nobody "
            "would read an empty database."
        ),
    )
    args = parser.parse_args(argv)
    if account_id is None:
        account_id = accounts.resolve_account(args.account)


    if args.concept_id:
        c = preprod.get_concept(args.concept_id, account_id=account_id)
        if not c:
            print(f"no concept {args.concept_id}", file=sys.stderr)
            return 1
        concepts = [c]
    else:
        concepts = [c for c in preprod.list_concepts(limit=args.limit, account_id=account_id)
                    if c.get("brand") == "zeropage"]

    for c in rank(concepts):
        u = c["uncanny"]
        flag = "PASS" if u["passed"] else "HOLD"
        print(f"[{flag} {u['overall']:.1f}] hook {u['uncanny_hook']:.1f} / "
              f"grounded {u['grounded']:.1f} / format {u['format_fit']:.1f} / "
              f"no-star {u['no_recurring_star']:.1f}  —  {c.get('title')}")
        for r in u["reasons"]:
            print(f"      · {r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
