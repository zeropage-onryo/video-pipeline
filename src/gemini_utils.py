import re
import sys
import time

from google import genai

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


def is_retriable(error) -> bool:
    """Transient, so waiting is worth it -- a busy model (UNAVAILABLE) or a
    spent quota (RESOURCE_EXHAUSTED). Everything else (a bad key, a
    malformed request, a refusal) is a fact about the call and retrying it
    only spends the same failure again.

    Lifted out of generate_with_retry 2026-09-02 so the embedding path can
    hold the same opinion. Two copies of "which errors are worth a second
    try" is the shape of bug where one of them quietly forgets 429."""
    text = str(error)
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
                        account_id=None, run_id=None) -> str:
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
    nowhere if the person is looking at a progress bar (2026-08-29)."""
    models_to_try = [model] + [m for m in FALLBACK_MODELS if m != model]

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
                response = client.models.generate_content(model=current_model, contents=contents)
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
                        raise
                    note(f"{current_model} still unavailable, trying a fallback model...")
                    break
                delay = retry_delay(e, attempt)
                note(f"{current_model} busy, retrying in {delay:.0f}s "
                     f"({attempt + 2}/{budget})")
                time.sleep(delay)
