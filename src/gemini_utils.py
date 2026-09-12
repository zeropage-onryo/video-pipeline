import os
import re
import sys
import time

from google import genai
from google.genai import types

from . import spend

# The budget for the LAST model in the chain, which has nowhere to fall
# through to and may as well keep asking.
MAX_RETRIES = 6
# The budget for one that has a fallback waiting behind it. A preview
# endpoint is the first thing squeezed when a model is busy, and six
# attempts at it before trying a stable sibling is backwards: measured
# 2026-08-29, gemini-3-flash-preview answered 503 while
# gemini-3.1-flash-lite answered in 1.2s.
FALLTHROUGH_RETRIES = 3
# Backoff, not a flat wait. A 503 body carries no "retry in Xs" hint the
# way a 429 does, so every overload used to take the full 20 seconds --
# and the one measured cleared on a retry 1.5s later. Six attempts at 20s
# across three models was five minutes of a job spent asleep, invisibly.
FIRST_RETRY_DELAY = 1.0
MAX_RETRY_DELAY = 20.0


def strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    return text.strip()


def sniff_mime(data) -> str:
    """The mime type for inline image bytes, read from the magic number
    rather than a filename. Reference bytes reach us from a fetch or a
    render file, neither carrying a trustworthy extension, and handing
    a model a PNG labelled image/jpeg is a needless way to lose a
    reference."""
    if not data:
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:2] == b"\xff\xd8":
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return "image/jpeg"


FALLBACK_MODELS = ["gemini-3.1-flash-lite", "gemini-pro-latest"]


class SubstitutionRefused(RuntimeError):
    """The asked-for model stayed down and this call would not take a
    cheaper one instead.

    Only raised for a caller that passed an EMPTY `fallbacks` list, which
    is a deliberate statement rather than a default: see BRAINS below.
    Everything else keeps the old behaviour of falling through, because
    for an ordinary call a slightly worse answer beats no answer."""


# --- WHICH BRAIN WRITES (2026-09-09, Mike's call) -------------------------
# A named tier, not a free-text model id, for the reason providers.py
# gives about render models: a menu the UI can render, checked
# server-side, resolving in ONE place to the model + the thinking
# config + what may stand in for it. Three copies of "which model does
# the composer use" is how the composer, the night and the tests end up
# quietly disagreeing.
#
# Model ids verified live against this account's own models.list on
# 2026-09-09; prices from ai.google.dev/gemini-api/docs/pricing the same
# day (3.1 Pro $2/$12 per 1M at <=200k prompt, Flash $0.50/$3), and
# mirrored into spend.DEFAULT_PRICES so /costs prices a reasoning run
# instead of leaving it UNPRICED. Re-check both before trusting them.
#
# NOTE both models think: gemini-3-flash-preview reports thinking:true
# too. What the reasoning tier buys is the bigger model AND an explicit
# HIGH level, not the existence of thought.
FAST_MODEL = "gemini-3-flash-preview"
REASONING_MODEL = os.environ.get("ZEROPAGE_REASONING_MODEL",
                                 "gemini-3.1-pro-preview")
DEFAULT_BRAIN = "fast"

# `substitute` is the whole disagreement between the two rows. The
# fallback chain exists so a 503 does not lose a night -- but the first
# model in it is gemini-3.1-flash-lite, the LEAST capable model in the
# repo, and a scene asked for on the reasoning tier and quietly answered
# by flash-lite still saves, still lands on the board, and reads
# identically to one that was not. That is the failure mode this project
# keeps writing tests around. So the reasoning tier refuses (Mike's call,
# 2026-09-09): fail loudly, a person is standing at the composer.
BRAINS = {
    "fast": {
        "label": "Fast",
        "note": "gemini 3 flash — the default, and what the night runs on",
        "model": lambda: FAST_MODEL,
        "level": None,
        "substitute": True,
    },
    "reasoning": {
        "label": "Reasoning",
        "note": "gemini 3.1 pro, thinking HIGH — slower, ~4x the tokens, no fallback",
        "model": lambda: REASONING_MODEL,
        "level": "HIGH",
        "substitute": False,
    },
}


def resolve_brain(name=None) -> dict:
    """A tier name -> the three things a call needs: `model`, `config`
    (None on the fast tier, so its request is byte-for-byte the one this
    module has always sent) and `fallbacks`.

    Unknown or empty falls back to DEFAULT_BRAIN rather than raising:
    every caller of this reaches it from a form field or an env var, and
    a typo should write a cheap scene, not fail a run. The SERVER
    clamping to this table is the gate -- the select is not (the
    SCENE_COUNT_MAX rule).

    Resolved per call, never at import, so ZEROPAGE_REASONING_MODEL can
    be changed without a restart (the src/settings.py convention)."""
    key = (name or DEFAULT_BRAIN).strip().lower()
    spec = BRAINS.get(key) or BRAINS[DEFAULT_BRAIN]
    if key not in BRAINS:
        key = DEFAULT_BRAIN
    config = None
    if spec["level"]:
        config = types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(thinking_level=spec["level"]))
    return {"brain": key, "model": spec["model"](), "config": config,
            "fallbacks": None if spec["substitute"] else []}


def brain_options() -> list:
    """The menu, for the composer's select. A PROJECTION of BRAINS, never
    a second list -- a hardcoded <option> in a template is a copy that
    goes stale the first time a tier is added."""
    return [{"id": key, "label": spec["label"], "note": spec["note"],
             "default": key == DEFAULT_BRAIN}
            for key, spec in BRAINS.items()]


# The 429 that is not a rate limit. Google returns RESOURCE_EXHAUSTED for
# both "you are going too fast" (waits it out) and "the card is empty"
# (waiting changes nothing). The strings below are the billing half,
# read off the owner's own 2026-09-07 log -- one depleted account cost
# six retries per call across all sixteen runs of the walk, which is
# every model call in a night spent asleep waiting for a payment nobody
# was making at 3am.
DEPLETED_MARKERS = (
    "prepayment credits are depleted",
    "billing account",
    "billing is not enabled",
    # deliberately NOT "quota exceeded for quota metric": that is Google's
    # wording for an ordinary per-minute limit, which is exactly the 429
    # that DOES clear by waiting. Only the money strings belong here.
    "check your plan and billing details",
)


def is_depleted(error) -> bool:
    """A 429 that says the money ran out rather than that we are early.

    Kept separate from is_retriable because the two need opposite
    behaviour from the same status code, and because the nightly
    breaker (src/nightly.py) asks the same question to decide whether
    the whole walk is pointless -- one opinion, two callers.
    """
    text = str(error).lower()
    return any(marker in text for marker in DEPLETED_MARKERS)


def is_retriable(error) -> bool:
    """Transient, so waiting is worth it -- a busy model (UNAVAILABLE) or a
    spent quota (RESOURCE_EXHAUSTED). Everything else (a bad key, a
    malformed request, a refusal) is a fact about the call and retrying it
    only spends the same failure again.

    Lifted out of generate_with_retry 2026-09-02 so the embedding path can
    hold the same opinion. Two copies of "which errors are worth a second
    try" is the shape of bug where one of them quietly forgets 429.

    A DEPLETED 429 is the exception (2026-09-07): it wears the retriable
    status code and is the least retriable error there is -- no wait
    tops up a card, and the fallback models bill the same account. It
    raises on the first attempt so the caller learns the truth in one
    second instead of five minutes.
    """
    text = str(error)
    if is_depleted(error):
        return False
    return "RESOURCE_EXHAUSTED" in text or "UNAVAILABLE" in text


def retry_delay(error, attempt: int) -> float:
    """How long to wait before attempt N+1.

    An explicit "retry in Xs" wins outright -- a 429 states its own
    cooldown and guessing under it just earns another 429. Everything
    else backs off from one second, because the common case is a 503
    that clears in about that long and the old flat 20 spent twenty."""
    match = re.search(r"retry in ([\d.]+)s", str(error))
    if match:
        return float(match.group(1)) + 2
    return min(FIRST_RETRY_DELAY * (2 ** attempt), MAX_RETRY_DELAY)


def generate_with_retry(client: genai.Client, model: str, contents,
                        *, on_retry=None, stage: str = "unknown",
                        account_id=None, run_id=None,
                        config=None, fallbacks=None) -> str:
    """Retries transient errors on `model`; if it stays unavailable for the
    whole retry budget, falls through to FALLBACK_MODELS in order rather
    than failing the run outright.

    Every answer is metered (src/spend.py: one llm_calls row with the
    model that ACTUALLY replied, which after a fallback is not the one
    asked for -- the reason the meter is here and not at the callers).
    `stage` labels the call (spend.STAGES; "unknown" until a caller is
    labelled); `account_id`/`run_id` default to whatever spend.bind()
    attached to this job or graph run. The meter never raises.

    `on_retry` is called with a one-line note each time this decides to
    wait or to change models. Optional and keyword-only, so every
    existing caller is unaffected -- but a job that does pass one stops
    being a spinner that means both "thinking" and "asleep for the next
    twenty seconds". The notes went only to stderr before, which is
    nowhere if the person is looking at a progress bar (2026-08-29).

    `config` is a types.GenerateContentConfig -- the seam a thinking
    level needs (2026-09-09). Passed to generate_content ONLY when it is
    not None, deliberately: every fake client in this suite implements
    generate_content(model=, contents=) and nothing else, so sending a
    keyword nobody asked for would break all of them to express "no
    config", which is what omitting it already says.

    `fallbacks` overrides FALLBACK_MODELS for this call. An EMPTY list
    means take no substitute: the model asked for answers, or the call
    raises SubstitutionRefused. That is the reasoning tier's posture,
    and the reason `fallbacks=[]` and `fallbacks=None` are different
    things -- None is "no opinion", which still means the default
    chain."""
    chain = FALLBACK_MODELS if fallbacks is None else list(fallbacks)
    models_to_try = [model] + [m for m in chain if m != model]
    no_substitute = fallbacks is not None and not chain

    def note(text: str) -> None:
        print(f"  {text}", file=sys.stderr)
        if on_retry is not None:
            try:
                on_retry(text)
            except Exception:
                pass          # telling someone is never worth failing a run

    for model_index, current_model in enumerate(models_to_try):
        last = model_index == len(models_to_try) - 1
        budget = MAX_RETRIES if last else FALLTHROUGH_RETRIES
        for attempt in range(budget):
            started = time.monotonic()
            try:
                response = (
                    client.models.generate_content(model=current_model, contents=contents)
                    if config is None else
                    client.models.generate_content(model=current_model,
                                                   contents=contents, config=config))
                if current_model != model:
                    print(f"  (used fallback model {current_model})", file=sys.stderr)
                spend.record_call(stage=stage, model_asked=model, model_used=current_model,
                                  response=response, account_id=account_id, run_id=run_id,
                                  ms=int((time.monotonic() - started) * 1000))
                return response.text.strip()
            except Exception as e:
                if not is_retriable(e):
                    spend.record_call(stage=stage, model_asked=model, model_used=current_model,
                                      ok=False, account_id=account_id, run_id=run_id,
                                      ms=int((time.monotonic() - started) * 1000))
                    raise
                if attempt == budget - 1:
                    if last:
                        spend.record_call(stage=stage, model_asked=model,
                                          model_used=current_model, ok=False,
                                          account_id=account_id, run_id=run_id)
                        if no_substitute:
                            raise SubstitutionRefused(
                                f"{model} is unavailable and this call takes no "
                                f"substitute -- a reasoning run answered by a "
                                f"cheaper model reads identically on the board, "
                                f"which is the whole reason to refuse it") from e
                        raise
                    note(f"{current_model} still unavailable, trying a fallback model...")
                    break
                delay = retry_delay(e, attempt)
                note(f"{current_model} busy, retrying in {delay:.0f}s "
                     f"({attempt + 2}/{budget})")
                time.sleep(delay)
