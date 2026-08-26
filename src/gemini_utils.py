import re
import sys
import time

from google import genai

MAX_RETRIES = 6
DEFAULT_RETRY_DELAY = 20


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


def generate_with_retry(client: genai.Client, model: str, contents) -> str:
    """Retries transient errors on `model`; if it stays unavailable for the
    whole retry budget, falls through to FALLBACK_MODELS in order rather
    than failing the run outright."""
    models_to_try = [model] + [m for m in FALLBACK_MODELS if m != model]

    for model_index, current_model in enumerate(models_to_try):
        for attempt in range(MAX_RETRIES):
            try:
                response = client.models.generate_content(model=current_model, contents=contents)
                if current_model != model:
                    print(f"  (used fallback model {current_model})", file=sys.stderr)
                return response.text.strip()
            except Exception as e:
                retriable = "RESOURCE_EXHAUSTED" in str(e) or "UNAVAILABLE" in str(e)
                if not retriable:
                    raise
                if attempt == MAX_RETRIES - 1:
                    if model_index == len(models_to_try) - 1:
                        raise
                    print(f"  {current_model} still unavailable, trying fallback model...", file=sys.stderr)
                    break
                match = re.search(r"retry in ([\d.]+)s", str(e))
                delay = float(match.group(1)) + 2 if match else DEFAULT_RETRY_DELAY
                print(f"  request failed, waiting {delay:.0f}s before retry...", file=sys.stderr)
                time.sleep(delay)
