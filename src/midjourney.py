#!/usr/bin/env python3
"""
The Midjourney connector: prompt -> still image -> pipeline. runway.py's
exact shape (thin raising wrapper under a never-raises edge), the same
per-run spend gate -- mirrored deliberately so this reads like the same
codebase, not a bolted-on side quest.

Two layers:
- generate_image   -- the thin wrapper. Submit the prompt to AceDataCloud's
                      Midjourney relay, poll until it finishes, download the
                      image immediately (same "the CDN URL may not last"
                      posture as Runway's signed-URL download). Raises on
                      failure; its caller catches.
- generate_stills  -- the never-raises edge: one still for one prompt,
                      the attempt logged through generative.record_generation
                      same as every other tool. Nothing is ever auto-posted --
                      landing in the hold queue is the gate, same contract
                      generate_render already holds for video.

THE SPEND GATE, mirrored from runway.py: a Midjourney render is a real
credit spend (~$0.27/image on AceDataCloud, 2026-08 pricing), so it gets
the same deliberate, per-run approval Runway's video spend gets:
- MIDJOURNEY_SPEND_OK=1 must be set or generate_image raises. Set it per
  run, never in .env, so every credit spend is an explicit human approval.
- MIDJOURNEY_DAILY_CAP (default 10) counted from the generations table,
  same wall runway.py has.

CONTRACT VERIFIED AGAINST PUBLIC DOCS ONLY (2026-08-20) -- there is no
ACEDATA_API_KEY in this repo's .env yet (sign up at platform.acedata.cloud
to get one), so this has not been exercised against a live key. The
endpoint/response shape below (POST /midjourney/imagine, Bearer auth,
{"task_id", "image_url", "raw_image_url", "success", "progress"}) matches
AceDataCloud's published Midjourney API and this repo's own AI-shot still
prompts (_midjourney_still in orchestrator.py) came back from the same CDN
(platform2.cdn.acedata.cloud / midjourney.cdn.acedata.cloud) during manual
testing. The polling endpoint path (GET /midjourney/tasks/{id}) is a
best-effort guess at their convention, not directly confirmed. Re-verify
against a real key on first run -- same policy runway.py holds for its SDK
after a version bump.
"""
from __future__ import annotations

import json as _json
import os
import re
import time
import urllib.request
from pathlib import Path
from typing import Optional

from . import generative
from .db import DB_PATH
from .shot import Shot

API_BASE = "https://api.acedata.cloud/midjourney"
DAILY_CAP = int(os.environ.get("MIDJOURNEY_DAILY_CAP", "10"))
# The installation-wide wall, beside the per-account one. Defaults to the
# SAME number, so a single-operator database behaves exactly as it did --
# admitting a second account is what forces a deliberate decision about
# whose card is paying, instead of the total quietly doubling.
GLOBAL_DAILY_CAP = int(os.environ.get("MIDJOURNEY_GLOBAL_DAILY_CAP", str(DAILY_CAP)))
SPEND_ENV = "MIDJOURNEY_SPEND_OK"
COST_USD = 0.27  # AceDataCloud per-image, 2026-08 -- recheck platform.acedata.cloud billing
POLL_INTERVAL = 15
MAX_POLL_ATTEMPTS = 24  # ~6 minutes, matches the MCP connector's own default budget


def spend_approved() -> bool:
    """The human approval for burning API credits. Per-run by design:
    set MIDJOURNEY_SPEND_OK=1 on the command, not in .env -- an approval
    that's always on isn't an approval."""
    return (os.environ.get(SPEND_ENV) or "").strip() == "1"


def _safe_error(e: Exception) -> str:
    """The key must never reach a page, a log line, or a DB row."""
    text = str(e)
    key = os.environ.get("ACEDATA_API_KEY")
    if key:
        text = text.replace(key, "<ACEDATA_API_KEY>")
    return re.sub(r"(Bearer\s+)[A-Za-z0-9_\-.]+", r"\1<redacted>", text)


def generations_today(db_path=None, *, account_id=None, everyone: bool = False) -> int:
    """This account's midjourney generations since UTC midnight -- what
    DAILY_CAP counts against. `everyone=True` gives the installation-wide
    count that GLOBAL_DAILY_CAP counts against."""
    return generative.used_today(
        "midjourney", db_path if db_path is not None else DB_PATH,
        account_id=account_id, everyone=everyone,
    )


def _request(path: str, payload: Optional[dict] = None, method: str = "POST") -> dict:
    key = os.environ.get("ACEDATA_API_KEY")
    if not key:
        raise RuntimeError("ACEDATA_API_KEY not set -- sign up at platform.acedata.cloud")
    req = urllib.request.Request(
        f"{API_BASE}{path}",
        data=_json.dumps(payload).encode() if payload is not None else None,
        headers={"content-type": "application/json", "accept": "application/json",
                 "Authorization": f"Bearer {key}"},
        method=method,
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return _json.loads(resp.read().decode())


def _download(url: str, out_path: Path) -> None:
    """AceDataCloud's CDN URLs are the durable artifact here; download
    promptly the same way runway.py treats Runway's signed URLs."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=120) as response, open(out_path, "wb") as f:
        while True:
            chunk = response.read(1024 * 256)
            if not chunk:
                break
            f.write(chunk)


def generate_image(prompt: str, out_path, *, poll_interval: int = POLL_INTERVAL,
                   max_attempts: int = MAX_POLL_ATTEMPTS) -> Path:
    """
    The thin wrapper: submit -> poll until done -> download. Raises on
    anything -- including a missing spend approval, checked HERE so no
    caller can spend a credit around the gate. generate_stills is the
    layer that catches.
    """
    if not spend_approved():
        raise RuntimeError(
            f"credit spend not approved: set {SPEND_ENV}=1 on this run to "
            f"approve ~${COST_USD} of AceDataCloud credits for this still"
        )
    result = _request("/imagine", {"prompt": prompt, "action": "generate"})
    for _ in range(max_attempts):
        if result.get("success") and result.get("image_url"):
            break
        task_id = result.get("task_id")
        if not task_id:
            raise RuntimeError(f"Midjourney task submission had no task_id: {result}")
        time.sleep(poll_interval)
        result = _request(f"/tasks/{task_id}", method="GET")
    if not (result.get("success") and result.get("image_url")):
        raise RuntimeError(f"Midjourney render did not finish in time: {result}")

    out_path = Path(out_path)
    _download(result.get("raw_image_url") or result["image_url"], out_path)
    return out_path


def _shot_row_for_prompt(prompt: str, db_path, account_id: Optional[int] = None) -> int:
    """A generations row needs a shot to hang off. The graph's AI shots
    don't have one, so synthesize a minimal Shot -- same pattern
    runway.py uses, the row exists to make the attempt countable."""
    kwargs = {"path": db_path} if db_path is not None else {}
    generative.init(**kwargs)
    shot = Shot(subject=prompt[:100], action="still frame")
    return generative.add_shot(shot, notes="auto-created by midjourney.generate_stills",
                               **kwargs, account_id=account_id)


def generate_stills(prompt: str, out_dir, *, shot_id: Optional[int] = None,
                    db_path=None,
                    account_id: Optional[int] = None,
) -> dict:
    """
    Never raises. {"ok", "candidates": [{path, generation_id}], "error"}
    -- a missing approval, a missing key, a failed job, or the daily cap
    is a result the caller can show, not an exception that takes the run
    down. Mirrors runway.generate_candidates exactly; one candidate per
    call, since a still is a single frame, not N takes.
    """
    kwargs = {"path": db_path} if db_path is not None else {}
    try:
        if not spend_approved():
            return {"ok": False, "candidates": [],
                    "error": f"credit spend not approved: set {SPEND_ENV}=1 to approve "
                             f"~${COST_USD} of AceDataCloud credits for this still"}

        refusal = generative.cap_error(
            "midjourney", 1, account_id=account_id,
            per_account=DAILY_CAP, ceiling=GLOBAL_DAILY_CAP,
            path=db_path if db_path is not None else DB_PATH,
            env_prefix="MIDJOURNEY", phrase="stills used",
            used=generations_today(db_path=db_path, account_id=account_id),
            used_everywhere=generations_today(db_path=db_path, everyone=True),
        )
        if refusal:
            return {"ok": False, "candidates": [], "error": refusal}

        if shot_id is None:
            shot_id = _shot_row_for_prompt(prompt, db_path)

        out_path = Path(out_dir) / "still.png"
        try:
            generate_image(prompt, out_path)
        except Exception as e:
            return {"ok": False, "candidates": [], "shot_id": shot_id,
                    "error": _safe_error(e)}

        generation_id = generative.record_generation(
            shot_id, "midjourney", prompt, params={},
            output_path=str(out_path), cost_usd=COST_USD, notes=None, **kwargs,
        
            account_id=account_id,)
        return {"ok": True, "shot_id": shot_id, "error": None,
                "candidates": [{"path": str(out_path), "generation_id": generation_id}]}
    except Exception as e:
        return {"ok": False, "candidates": [], "error": _safe_error(e)}
