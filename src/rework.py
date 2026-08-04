#!/usr/bin/env python3
"""
The L3 stage: rework the slate from what actually performed.

Where shootgen ideates from rooms + brand + references, this ideates
from *evidence*: post_seo's derived signals (which topics, hooks and
title words beat this channel's median at equal age) plus the
proven_results shelf promote_winners maintains. Every proposed idea
carries an "evidence" sentence naming the pattern it exploits, so a
slate can be audited against the numbers that produced it.

The proposals land as ordinary concept ideas in preprod -- deliberately.
The human pick (planning one, via shootgen --shotlist or the studio)
stays the recorded label, measured by shortlist_rate against this
module's prompt hash like any other ideation run. Autonomy here means
the machine drafts the slate; it does not mean the pick stops being
yours or stops being measured.

Same hermetic split as shootgen: evidence_block/reference retrieval sit
at the edge (CLI, web routes), and propose_slate takes signals and
references as plain arguments. Degrade-don't-break: no performance data
means a note and an evidence-free ideation run, never a crash.
"""
import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional

from . import crag, post_seo, preprod, rag, shootgen
from .db import DB_PATH, init_db
from .gemini_utils import generate_with_retry, strip_fences

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = PROJECT_ROOT / "prompts"

MODEL = "gemini-3-flash-preview"

DEFAULT_COUNT = 6

# Rework grounds on the same shelves ideation does, with proven_results
# first -- the whole point is drawing on our own record.
REWORK_DOMAINS = ("proven_results", "personal_brand", "marketing", "cinematography")

NO_SIGNALS_NOTE = (
    "note: no performance data yet -- proposing without evidence. Post videos "
    "and record metrics, and rework will reason from what performed."
)


def format_signals(signals: dict) -> str:
    """The evidence block as the model sees it: named patterns with
    counts, not vibes. An empty sample says so plainly."""
    if not signals or not signals.get("sample"):
        return "No performance data yet -- nothing posted and measured."

    def top(counter, n=5):
        items = sorted((counter or {}).items(), key=lambda kv: -kv[1])[:n]
        return ", ".join(f"{k} (won {v}x)" for k, v in items) or "none recorded"

    lines = [
        f"Across {signals['sample']} scored videos (median "
        f"{signals['median']:,.0f} {signals.get('metric', 'views')} at "
        f"{signals.get('at_days', 7)} days):",
        f"- winning topics: {top(signals.get('winning_topics'))}",
        f"- winning hooks: {top(signals.get('winning_hooks'))}",
        f"- winning title words: {top(signals.get('winning_title_words'))}",
        f"- below-median topics: {top(signals.get('losing_topics'))}",
        f"- below-median hooks: {top(signals.get('losing_hooks'))}",
    ]
    return "\n".join(lines)


def build_rework_prompt(locations: list, brand: str, signals: dict,
                        count: int = DEFAULT_COUNT, references: str = "") -> str:
    template = (PROMPTS_DIR / "rework_prompt.txt").read_text()
    return (
        template
        .replace("{signals}", format_signals(signals))
        .replace("{locations}", shootgen.format_locations(locations))
        .replace("{brand}", shootgen.load_brand(brand))
        .replace("{count}", str(count))
        .replace("{references}", references or shootgen.NO_REFERENCES_NOTE)
    )


def parse_slate_response(text: str) -> list:
    """The testable seam: raw model text -> the proposed ideas."""
    data = json.loads(strip_fences(text))
    ideas = data.get("ideas", data if isinstance(data, list) else [])
    if not ideas:
        raise ValueError("no ideas in response")
    for i, idea in enumerate(ideas, start=1):
        if not (idea.get("title") or "").strip():
            raise ValueError(f"idea {i} has no title")
    return ideas


def evidence_block(signals: dict, gemini_client=None, db_path=None) -> str:
    """
    Edge helper, like shootgen.reference_block: retrieve the reference
    material rework grounds on -- proven winners first -- using the
    winning patterns as the query. CRAG-graded when a client is
    available (a weak retrieval gets one query rewrite); plain
    retrieval otherwise. Never raises.
    """
    parts = []
    for key in ("winning_topics", "winning_hooks", "winning_title_words"):
        parts.extend((signals.get(key) or {}).keys())
    query = " ".join(parts) or "proven winning short-form video concepts"

    try:
        if gemini_client is not None:
            retrieval = crag.retrieve_with_crag(
                query, gemini_client, MODEL, domain=REWORK_DOMAINS,
            )
        else:
            retrieval = rag.retrieve_references(query, domain=REWORK_DOMAINS)
    except Exception as e:  # pragma: no cover - belt over crag's own braces
        retrieval = {"ok": False, "references": [], "error": str(e)}

    if retrieval.get("ok") and retrieval.get("references"):
        print(f"Grounding rework in {len(retrieval['references'])} reference(s)",
              file=sys.stderr)
        return rag.format_references(retrieval["references"])

    reason = retrieval.get("error", "reference library is empty")
    print(f"note: reworking without references: {reason}", file=sys.stderr)
    return ""


def propose_slate(brand: str, signals: Optional[dict] = None, gemini_client=None,
                  model: str = MODEL, count: int = DEFAULT_COUNT,
                  db_path=None, references: str = "") -> dict:
    """
    Propose the next slate as ordinary concept ideas, each carrying the
    evidence sentence that ties it to the numbers. Saved through
    preprod.save_concept_ideas so the pick stays the measured label.
    """
    kwargs = {"path": db_path} if db_path is not None else {}
    signals = signals or {"sample": 0}
    if not signals.get("sample"):
        print(NO_SIGNALS_NOTE, file=sys.stderr)

    locations = preprod.list_locations(**kwargs)
    if not locations:
        print(shootgen.NO_LOCATIONS_NOTE, file=sys.stderr)

    prompt = build_rework_prompt(locations, brand, signals, count,
                                 references=references)
    ideas = parse_slate_response(generate_with_retry(gemini_client, model, prompt))

    concept_ids = preprod.save_concept_ideas(
        ideas, brand=brand, spark="rework: evidence-grounded slate",
        prompt_template=prompt, **kwargs,
    )
    return {"concept_ids": concept_ids, "ideas": ideas}


def main(db_path=None):
    from dotenv import load_dotenv
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Propose the next slate from what actually performed."
    )
    parser.add_argument("--brand", choices=preprod.BRANDS, default="antihero")
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT)
    parser.add_argument("--at-days", type=int, default=7)
    parser.add_argument("--posted-within-days", type=int, default=180)
    args = parser.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY (or GOOGLE_API_KEY) not set", file=sys.stderr)
        sys.exit(1)

    from google import genai
    path = db_path if db_path is not None else DB_PATH
    init_db(path=path)
    preprod.init(path=path)
    gemini_client = genai.Client(api_key=api_key)

    signals = post_seo.derive_signals(
        at_days=args.at_days, posted_within_days=args.posted_within_days,
        db_path=path,
    )
    references = evidence_block(signals, gemini_client=gemini_client, db_path=path)

    result = propose_slate(
        brand=args.brand, signals=signals, gemini_client=gemini_client,
        count=args.count, db_path=path, references=references,
    )

    print(f"\n{len(result['ideas'])} evidence-grounded ideas — plan the ones worth making:\n")
    for concept_id, idea in zip(result["concept_ids"], result["ideas"]):
        print(f"  [{concept_id}] {idea['title']}")
        print(f"       hook: {idea.get('hook', '')}")
        print(f"       {idea.get('logline', '')}")
        if idea.get("evidence"):
            print(f"       evidence: {idea['evidence']}")
        print()


if __name__ == "__main__":
    main()
