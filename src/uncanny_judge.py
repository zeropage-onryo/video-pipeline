"""
The uncanny judge — Zero Page's ON-BRAND GATE.

This is the check that makes Zero Page safe to put on autopilot. It scores a
concept against a FIXED rubric (not the creator's history, the way taste_judge
does), so it works from day one, before there is any grading data: is the
first frame uncanny, is it grounded-not-glossy, does it ride a real format, is
it faceless. Those are the four properties that define a Zero Page video, and
they are checkable — which is the whole reason Zero Page can post unsupervised
and ANTIHERO cannot.

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

from . import preprod
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
FACELESS_FLOOR = 6.0


def _clamp(v) -> float:
    try:
        return max(0.0, min(10.0, float(v)))
    except (TypeError, ValueError):
        return 0.0


def _concept_str(concept: dict) -> str:
    return (f"Title: {concept.get('title')}\n"
            f"Format: {concept.get('format') or '(unspecified)'}\n"
            f"Hook: {concept.get('hook')}\n"
            f"Logline: {concept.get('logline')}")


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
            and scores["faceless"] >= FACELESS_FLOOR)


def _blocked(reason: str) -> dict:
    """Fail-closed result — did not pass, and says why."""
    return {"uncanny_hook": 0.0, "grounded": 0.0, "format_fit": 0.0,
            "faceless": 0.0, "overall": 0.0, "reasons": [reason],
            "graded": False, "passed": False}


def score_concept(concept: dict, gemini_client=None) -> dict:
    """Score one Zero Page concept on the four brand properties and decide
    whether it clears the gate. Never raises; a failure fails CLOSED."""
    try:
        client = gemini_client or _client()
        raw = generate_with_retry(client, MODEL, build_prompt(concept))
        data = json.loads(strip_fences(raw))
        scores = {
            "uncanny_hook": _clamp(data.get("uncanny_hook")),
            "grounded": _clamp(data.get("grounded")),
            "format_fit": _clamp(data.get("format_fit")),
            "faceless": _clamp(data.get("faceless")),
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
    args = parser.parse_args(argv)

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
              f"faceless {u['faceless']:.1f}  —  {c.get('title')}")
        for r in u["reasons"]:
            print(f"      · {r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
