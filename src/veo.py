#!/usr/bin/env python3
"""
The Veo connector: prompt -> video -> pipeline. Same SDK and key as
every other stage (google-genai + GEMINI_API_KEY), no new secret.

Two layers, youtube.py's shape:
- generate_video      -- the thin wrapper. Submit, poll the long-running
                         operation, download to out_path. Raises on
                         failure or timeout; its caller catches.
- generate_candidates -- the never-raises edge you actually use:
                         N candidate clips for one prompt, every attempt
                         logged through generative.record_generation
                         (the genlog data attempts_to_keeper and the
                         tool scoreboard read), files under
                         footage/generated/. Nothing is ever
                         auto-selected: keeping a candidate is a human
                         action through genlog, because the pick is the
                         label.

EVERY CALL COSTS REAL MONEY. Three guardrails live here, not in callers:
- VEO_SPEND_OK=1 must be set or generate_video raises (added 2026-09-02,
  runway.py's exact shape). Until then this was the most expensive tool
  in the repo -- estimate_cost(6) is $19.20 -- and the only one with no
  per-run approval: the cap was the whole wall. Set it per run, never
  in .env, so every Veo spend is an explicit human yes.
- DAILY_CAP: a hard per-UTC-day cap on generations (default 6,
  VEO_DAILY_CAP to change) counted from the generations table, so a
  runaway loop hits a wall the DB enforces.
- estimate_cost(): surfaced in every dry-run preview so "N candidates"
  reads as dollars before anyone approves.

Model ids + config verified against Google's Veo docs 2026-08 (see
task-veo-generate.md's sources): veo-3.1-generate-preview is current,
veo-3 / veo-3-fast stable; aspect_ratio 16:9|9:16, resolution
720p|1080p|4k (1080p/4k force 8s), duration 4|6|8. Files live on
Google's server ~2 days, so download immediately. Re-verify before a
live run -- Google versions these.
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Optional

from google import genai
from google.genai import types

from . import generative
from .shot import Shot

MODELS = ("veo-3.1-generate-preview", "veo-3", "veo-3-fast")
DEFAULT_MODEL = os.environ.get("VEO_MODEL", "veo-3-fast")   # cheapest first spend
DEFAULT_RESOLUTION = os.environ.get("VEO_RESOLUTION", "720p")
DAILY_CAP = int(os.environ.get("VEO_DAILY_CAP", "6"))
# The installation-wide wall, beside the per-account one. Defaults to the
# SAME number, so a single-operator database behaves exactly as it did --
# admitting a second account is what forces a deliberate decision about
# whose card is paying, instead of the total quietly doubling.
GLOBAL_DAILY_CAP = int(os.environ.get("VEO_GLOBAL_DAILY_CAP", str(DAILY_CAP)))

SPEND_ENV = "VEO_SPEND_OK"

# Rough per-clip estimate for the previews (8s, 720p, audio included),
# from Veo API pricing pages 2026-08. An estimate for a confirm dialog,
# not an invoice -- verify against Google's pricing before live spend.
COST_PER_CLIP_USD = 3.20


def _safe_error(e: Exception) -> str:
    """The key must never reach a page, a log line, or a DB row."""
    text = str(e)
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        value = os.environ.get(name)
        if value:
            text = text.replace(value, f"<{name}>")
    return re.sub(r"key=[A-Za-z0-9_\-]+", "key=<redacted>", text)


def spend_approved() -> bool:
    """The human approval for a Veo spend. Per-run by design: set
    VEO_SPEND_OK=1 on the command, not in .env -- an approval that's
    always on isn't an approval."""
    return (os.environ.get(SPEND_ENV) or "").strip() == "1"


def estimate_cost(n: int) -> float:
    return round(n * COST_PER_CLIP_USD, 2)


def generations_today(db_path=None, *, account_id=None, everyone: bool = False) -> int:
    """This account's veo generations since UTC midnight -- what
    DAILY_CAP counts against. `everyone=True` gives the installation-wide
    count that GLOBAL_DAILY_CAP counts against."""
    return generative.used_today(
        "veo", db_path,
        account_id=account_id, everyone=everyone,
    )


def _make_client() -> genai.Client:
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY (or GOOGLE_API_KEY) not set")
    return genai.Client(api_key=key)


def generate_video(prompt: str, out_path, *, model: str = DEFAULT_MODEL,
                   aspect_ratio: str = "9:16", resolution: str = DEFAULT_RESOLUTION,
                   duration: int = 8, image=None, client=None,
                   poll_delay: float = 10.0, timeout_s: float = 600.0) -> Path:
    """
    The thin wrapper: submit -> poll until done or timeout -> download.
    Raises on anything; generate_candidates is the layer that catches.
    Latency runs ~11s to ~6min, so polling is the contract, not an edge
    case.

    Config field names verified against the INSTALLED google-genai
    (1.x, 2026-08): the SDK takes duration_seconds (int), not the
    docs-snippet "duration" string.

    The spend gate is checked HERE, before the client is even built, so
    no caller can spend around it -- runway.generate_video's rule.
    """
    if not spend_approved():
        raise RuntimeError(
            f"credit spend not approved: set {SPEND_ENV}=1 on this run to "
            f"approve Veo spend (~${COST_PER_CLIP_USD:.2f} per clip)"
        )
    client = client or _make_client()
    kwargs = {"image": image} if image is not None else {}
    operation = client.models.generate_videos(
        model=model,
        prompt=prompt,
        config=types.GenerateVideosConfig(
            aspect_ratio=aspect_ratio,
            resolution=resolution,
            duration_seconds=int(duration),
        ),
        **kwargs,
    )

    deadline = time.monotonic() + timeout_s
    while not operation.done:
        if time.monotonic() > deadline:
            raise TimeoutError(f"Veo job did not finish within {timeout_s:.0f}s")
        time.sleep(poll_delay)
        operation = client.operations.get(operation)

    videos = getattr(operation.response, "generated_videos", None) or []
    if not videos:
        raise RuntimeError("Veo job finished with no video in the response")

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    video = videos[0]
    # download NOW -- Google keeps the file ~2 days, the repo keeps it forever
    client.files.download(file=video.video)
    video.video.save(str(out_path))
    return out_path


def _shot_row_for_prompt(prompt: str, db_path, account_id: Optional[int] = None) -> int:
    """A generations row needs a shot to hang off. The interactive path
    has one from promptgen; the graph's AI shots don't, so synthesize a
    minimal Shot -- the row exists to make the attempt countable, and
    its notes say where it came from."""
    kwargs = {"dsn": db_path} if db_path is not None else {}
    generative.init(**kwargs)
    shot = Shot(subject=prompt[:100], action="as prompted")
    return generative.add_shot(shot, notes="auto-created by veo.generate_candidates",
                               **kwargs, account_id=account_id)


def generate_candidates(prompt: str, out_dir, n: int = 3, *, shot_id: Optional[int] = None,
                        db_path=None, client=None, model: str = DEFAULT_MODEL,
                        account_id: Optional[int] = None, **cfg) -> dict:
    """
    Never raises. {"ok", "candidates": [{path, generation_id, model}],
    "error"} -- a missing key, a failed job, or the daily cap is a
    result the caller can show, not an exception that takes the run
    down. Partial success is success: three asked, one landed, you still
    get the one (with the error noted).
    """
    n = int(os.environ.get("VEO_CANDIDATES", n))
    kwargs = {"dsn": db_path} if db_path is not None else {}

    try:
        if not spend_approved():
            return {"ok": False, "candidates": [],
                    "error": f"credit spend not approved: set {SPEND_ENV}=1 to "
                             f"approve ~${estimate_cost(n)} of Veo spend for this run"}

        refusal = generative.cap_error(
            "veo", n, account_id=account_id,
            per_account=DAILY_CAP, ceiling=GLOBAL_DAILY_CAP,
            dsn=db_path,
            env_prefix="VEO", phrase="generations used",
            used=generations_today(db_path=db_path, account_id=account_id),
            used_everywhere=generations_today(db_path=db_path, everyone=True),
        )
        if refusal:
            return {"ok": False, "candidates": [], "error": refusal}

        if shot_id is None:
            shot_id = _shot_row_for_prompt(prompt, db_path)

        out_dir = Path(out_dir)
        candidates, errors = [], []
        for i in range(1, n + 1):
            out_path = out_dir / f"cand{i}.mp4"
            try:
                generate_video(prompt, out_path, model=model, client=client, **cfg)
            except Exception as e:
                errors.append(f"candidate {i}: {_safe_error(e)}")
                continue
            generation_id = generative.record_generation(
                shot_id, "veo", prompt,
                params={"model": model, **cfg},
                output_path=str(out_path),
                cost_usd=COST_PER_CLIP_USD,
                notes=None,
                **kwargs,
             account_id=account_id)
            candidates.append({"path": str(out_path),
                               "generation_id": generation_id, "model": model})

        return {"ok": bool(candidates), "candidates": candidates, "shot_id": shot_id,
                "error": "; ".join(errors) if errors else None}
    except Exception as e:
        return {"ok": False, "candidates": [], "error": _safe_error(e)}
