"""
The second reader: judges a candidate spark independently of the self-score
the digest call attached to it, and measures the real engagement evidence
(view/upvote counts already sitting in this pass's signals) behind it.

Built 2026-09-04, closing the gap named in [[research_node]] and
[[feedback_stories]]: "the crawl grades its own homework" -- every digest
candidate up to now has been a self-score from the same call that wrote the
spark. This module is deliberately two separate things that happen to be
scored together:

  judge_spark()      an LLM call, but not the writer's -- grounded in the
                      story_craft RAG shelf and the account's own
                      winning_prompts/avoid_prompts shelves, so the verdict
                      is checked against written craft rules and this
                      account's real history rather than vibes. Costs a
                      model call and two RAG round trips; never raises.
  virality_signal()  pure arithmetic over the metrics the crawl already
                      fetched (real view counts, real upvotes) -- no
                      network, no model call, safe to run on every
                      candidate every pass at zero extra cost. This is
                      NOT a prediction of a topic's general virality; it is
                      "how much real engagement evidence backs the specific
                      signal this spark claims to be grounded in."

Both degrade to a documented "couldn't measure this" result rather than
raising -- the contract every other lane in scout.py already follows.
"""
import json
import math
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
JUDGE_PROMPT_PATH = PROJECT_ROOT / "prompts" / "story_judge_prompt.txt"

# The RAG shelves a judgment is grounded in. story_craft is the standing
# definition of "a good idea" (data/rag_seed/story_craft.md, ingested with
# --domain story_craft); winning_prompts/avoid_prompts are the same shelves
# shootgen already grounds shot-writing on (src/winners.py) -- reusing them
# here means a spark that repeats the shape of something that already
# didn't work gets caught before it's ever banked, not after it's shot.
STORY_DOMAIN = "story_craft"
REFERENCE_DOMAINS = ("winning_prompts", "avoid_prompts")

# How much the independent judge vs. the real-engagement evidence counts
# toward the final blended score. Weighted toward story on purpose --
# virality_signal answers "is there proof this specific signal is already
# travelling," which is real but narrower than "is this actually a story,"
# and a spark with zero linkable engagement evidence (very common -- most
# signals never get matched) should not be punished as heavily as a spark
# that fails the spine.
STORY_WEIGHT = 0.65
VIRALITY_WEIGHT = 0.35


# --- the independent judge --------------------------------------------------

def _format_context(refs: list) -> str:
    if not refs:
        return "(nothing on file yet)"
    return "\n".join(f"- [{r.get('domain', '?')}] {r.get('chunk', '')}" for r in refs)


def build_judge_prompt(spark: str, rationale: str,
                       craft_context: str, reference_context: str) -> str:
    template = JUDGE_PROMPT_PATH.read_text()
    return (template
            .replace("{spark}", spark)
            .replace("{rationale}", rationale or "(none given)")
            .replace("{craft_context}", craft_context)
            .replace("{reference_context}", reference_context))


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"```\s*$", "", text)
    return text.strip()


def parse_judge_response(text: str) -> dict:
    """Tolerant of the usual model output shapes, same contract as
    scout.parse_digest_response. {"ok": False, ...} rather than raising --
    a malformed verdict must fall back to the self-score, not crash a
    pass over one bad judge call."""
    try:
        data = json.loads(_strip_fences(text or ""))
    except Exception:
        match = re.search(r"\{.*\}", text or "", re.S)
        if not match:
            return {"ok": False, "score": None, "verdict": "", "missing": [],
                    "error": "unparseable judge response"}
        try:
            data = json.loads(match.group(0))
        except Exception:
            return {"ok": False, "score": None, "verdict": "", "missing": [],
                    "error": "unparseable judge response"}
    if not isinstance(data, dict) or "score" not in data:
        return {"ok": False, "score": None, "verdict": "", "missing": [],
                "error": "judge response had no score"}
    try:
        score = max(0.0, min(1.0, float(data.get("score"))))
    except (TypeError, ValueError):
        return {"ok": False, "score": None, "verdict": "", "missing": [],
                "error": "judge score was not a number"}
    missing = [m for m in (data.get("missing") or []) if isinstance(m, str)]
    return {"ok": True, "score": score,
            "verdict": (data.get("verdict") or "").strip(), "missing": missing}


def judge_spark(spark: str, rationale: str, client, model: str, *,
                rag_client=None, rag_conn=None, k: int = 4) -> dict:
    """A second, independent grading call -- never the same call that
    wrote the spark. Never raises: {"ok": False, "error": ...} is a
    normal result (no RAG configured, no network, a bad key) and the
    caller's contract is to fall back to the self-score, exactly like a
    dead crawl lane falls back to sparks.txt.

    rag_client/rag_conn are accepted so a caller running this over many
    candidates in one pass can open the connection once rather than once
    per spark -- omit them and this opens and closes its own."""
    try:
        from . import rag
        query_text = f"{spark}\n{rationale or ''}"
        conn = rag_conn
        close_conn = False
        if conn is None:
            conn = rag.connect()
            close_conn = True
        try:
            r_client = rag_client or rag.make_client()
            craft_refs = rag.query(query_text, r_client, conn, k=k, domain=STORY_DOMAIN)
            reference_refs = rag.query(query_text, r_client, conn, k=k,
                                       domain=list(REFERENCE_DOMAINS))
        finally:
            if close_conn:
                conn.close()

        prompt = build_judge_prompt(spark, rationale,
                                    _format_context(craft_refs),
                                    _format_context(reference_refs))
        resp = client.models.generate_content(model=model, contents=prompt)
        return parse_judge_response(getattr(resp, "text", "") or "")
    except Exception as e:
        return {"ok": False, "score": None, "verdict": "", "missing": [],
                "error": f"{type(e).__name__}: {e}"}


# --- real engagement evidence, no network --------------------------------

_METRIC_RE = re.compile(r"([\d,]+)\s*(views?|upvotes?|likes?|comments?)", re.I)

# What counts as "clearly already travelling" for that unit -- a working
# ceiling this account can revise, not an objective virality threshold.
# Log-scaled so one outlier signal can't alone max out a score.
_UNIT_CEILING = {"view": 200_000, "upvote": 5_000, "like": 20_000, "comment": 2_000}


def _parse_metric(metric: str):
    if not metric:
        return None
    m = _METRIC_RE.search(metric)
    if not m:
        return None
    count = int(m.group(1).replace(",", ""))
    unit = m.group(2).lower().rstrip("s")
    return count, unit


def _metric_strength(count: int, unit: str) -> float:
    ceiling = _UNIT_CEILING.get(unit, 10_000)
    if count <= 0 or ceiling <= 0:
        return 0.0
    return max(0.0, min(1.0, math.log10(count + 1) / math.log10(ceiling + 1)))


def _tokens(text: str) -> set:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) > 2}


def virality_signal(candidate: dict, signals: list) -> dict:
    """How much real engagement evidence backs the signal this candidate
    claims to come from -- computed from the view/upvote counts the crawl
    already fetched this pass. Not a topic-virality guess: it is
    arithmetic over numbers already in memory, so it costs nothing extra
    to run on every candidate.

    Linking a candidate back to the signal that inspired it is inherently
    fuzzy -- the digest paraphrases, it doesn't cite precisely. This tries
    an exact URL match first (candidate['sources'] against a signal's
    url), then falls back to token overlap between the candidate's own
    text and a signal's detail, the same style of match src/framebank.py
    already uses for frame search rather than an embedding lookup that
    would be overkill for a handful of short strings.

    No match found is a real, documented answer -- most candidates will
    have none, because the digest often synthesises across several
    signals rather than lifting one -- not a failure."""
    sources = set(candidate.get("sources") or [])
    own_tokens = _tokens((candidate.get("spark") or "") + " " + (candidate.get("evidence") or ""))
    best = None  # (strength, detail)

    for s in signals:
        parsed = _parse_metric(s.get("metric", ""))
        if not parsed:
            continue
        count, unit = parsed
        matched = bool(s.get("url")) and s["url"] in sources
        if not matched:
            overlap = own_tokens & _tokens(s.get("detail", ""))
            matched = len(overlap) >= 3
        if not matched:
            continue
        strength = _metric_strength(count, unit)
        if best is None or strength > best[0]:
            plural = "" if count == 1 else "s"
            best = (strength, f"{count:,} {unit}{plural} — {(s.get('detail') or '')[:60]}")

    if best is None:
        return {"score": 0.0, "detail": "no measurable signal linked"}
    return {"score": round(best[0], 3), "detail": best[1]}


def blend(story_score, virality_score: float) -> float:
    """story_score is None when the judge didn't run or couldn't --
    in that case the caller's own self-score stands and this is not
    consulted for the final number, only virality_signal's detail is
    still worth recording. When the judge did run, it dominates: the
    weighting is 65/35 story/virality because "is this a story" is the
    thing that was actually broken; virality is corroborating evidence,
    not the primary signal."""
    if story_score is None:
        return virality_score
    return STORY_WEIGHT * story_score + VIRALITY_WEIGHT * virality_score
