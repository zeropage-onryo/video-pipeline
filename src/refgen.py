"""Generated references: a still rendered from a spark's hook frame.

Mike, 2026-09-06: the web lanes return real photographs of real streets;
a spark set in an invented world has nothing on the internet that looks
like it. So the reference for it is rendered from the spark's own hook
frame -- Midjourney first (his call), Gemini's image model as the
fallback that needs no extra key and no per-run approval. No house look
and no likeness path since 2026-10-04 (Mike's call): the hook frame
names its own light, and nobody's face is special-cased.

ONE STILL PER SPARK, CAPPED. `render_for_finding` is the only entry:
it renders once, normalises through refbin like every other reference,
and banks the result on the finding's OWN pass (gen-<id>, read ahead of
the crawl pass by scout.bin_for_finding) with lane="generated" so
`spark_images` shows the credit ("generated: midjourney") and nothing
downstream has to know it was not fetched. The cap is counted from
those rows (REFGEN_DAILY_CAP, default 8 across both brands) so no new
table and no new counter; a night that renders eight and stops is the
designed behaviour.

IT COSTS THE CALLER CREDITS (2026-09-29, Mike's call). With an
`account_id`, a render holds credits before any provider is called --
priced at the dearest provider this render could reach (`hold_usd`), so
the balance is checked for the worst case -- and settles at the price of
the one that actually drew (`provider_usd`: Midjourney's AceDataCloud
price, or the Nano still's), at the render markup and floor like every
other still (src/charge.py, pricing). Nothing rendered, or nothing could
be saved: released. A crawl someone RAN (the Studio's research button, the
MCP `research` tool) passes their account and is charged like any other
caller (2026-10-08); the operator's exempt accounts and the unowned pool
(the CLI's crawl, which passes no account) are never charged, exactly as
for renders. An empty balance comes back as a note, never an
error -- an agent that sees an error retries, and the retry is what would
spend twice.

MIDJOURNEY'S OWN GATE STILL HOLDS. midjourney.generate_image refuses
without MIDJOURNEY_SPEND_OK=1 and ACEDATA_API_KEY -- that gate was
built so every AceData credit is an explicit approval, and this does
not go around it. Export it for a run if Mike wants that run to spend
there; without it, this falls straight to Gemini and says so in the
note.
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from . import db, refbin, scout

DAILY_CAP = int(os.environ.get("REFGEN_DAILY_CAP", "8"))
PROVIDERS = ("midjourney", "nano")

def enabled() -> bool:
    return (os.environ.get("REFGEN_LANE", "1") or "").strip().lower() not in ("", "0", "no", "off", "false")


def provider_order() -> tuple:
    """Midjourney first (Mike's call); REFGEN_PROVIDERS overrides it."""
    chosen = [p.strip() for p in (os.environ.get("REFGEN_PROVIDERS") or "").split(",") if p.strip()]
    return tuple(p for p in chosen if p in PROVIDERS) or PROVIDERS


def rendered_today(dsn=None) -> int:
    """Generated references banked since UTC midnight, both brands."""
    since = datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00")
    try:
        with db.connect(dsn) as conn:
            return int(conn.execute(
                "SELECT COUNT(*) FROM scout_bin WHERE lane = 'generated' AND created_at >= %s",
                (since,)).fetchone()[0])
    except Exception:
        return 0


def build_prompt(hook_frame: str, brand: str = "") -> str:
    """The hook frame is the whole subject, light included -- there is no
    house look to add. Kept short and concrete because a still model reads
    the first clause hardest, and Midjourney parameters go last."""
    return (f"{hook_frame.strip().rstrip('.')}. "
            "Cinematic film still, vertical 9:16, photorealistic, no text, no logo.")


def _midjourney(prompt: str, out: Path) -> Path:
    from . import midjourney
    return midjourney.generate_image(prompt + " --ar 9:16 --style raw --s 150", out)


def _nano(prompt: str, out: Path) -> Path:
    from . import nano_banana
    if not nano_banana.has_key():
        raise RuntimeError("no GEMINI_API_KEY")
    return nano_banana.generate_image(prompt, out, aspect_ratio="9:16")


_RENDERERS = {"midjourney": _midjourney, "nano": _nano}


def provider_usd(name: str) -> float:
    """What one still costs at the provider -- the number a charge settles
    at. Midjourney is its AceDataCloud per-image price; Nano is the meter's
    image price for its model."""
    if name == "midjourney":
        from . import midjourney
        return float(midjourney.COST_USD)
    from . import nano_banana, pricing
    return pricing.still_usd(nano_banana.MODEL)


def _reachable(name: str) -> bool:
    """Could this provider actually render right now? Midjourney refuses
    without its per-run approval and its key, so a hold must not be sized
    for a provider that will be skipped."""
    if name == "midjourney":
        from . import midjourney
        return midjourney.spend_approved() and bool(os.environ.get("ACEDATA_API_KEY"))
    return True


def hold_usd() -> float:
    """The most one render could cost: the dearest provider it could reach."""
    names = [p for p in provider_order() if _reachable(p)] or ["nano"]
    return max(provider_usd(p) for p in names)


def render(prompt: str) -> dict:
    """Try the providers in order; first image wins. Never raises.
    Returns {"path", "provider", "tried": [(provider, error), ...]}."""
    tried = []
    for name in provider_order():
        out = Path(tempfile.mkdtemp(prefix="refgen-")) / f"{name}.jpg"
        try:
            _RENDERERS[name](prompt, out)
            if out.is_file() and out.stat().st_size > 0:
                return {"path": out, "provider": name, "tried": tried}
            tried.append((name, "no file"))
        except Exception as e:                       # noqa: BLE001
            tried.append((name, f"{type(e).__name__}: {str(e)[:120]}"))
    return {"path": None, "provider": "", "tried": tried}


def render_for_finding(finding_id: int, hook_frame: str, dsn=None,
                       cap: int = DAILY_CAP,
                       account_id: Optional[int] = None) -> dict:
    """One generated reference for one spark. The public contract for
    both the MCP tool and the crawl. `account_id` is who pays (see the
    module docstring); None -- the CLI's crawl -- is nobody's bill."""
    if not enabled():
        return {"ok": False, "note": "generated references are off (REFGEN_LANE=0)"}
    finding = scout.get_finding(int(finding_id), dsn=dsn)
    if finding is None:
        return {"ok": False, "note": f"no finding {finding_id}"}
    if not (hook_frame or "").strip():
        return {"ok": False, "note": "a hook frame is required -- what is on screen in frame one"}
    used = rendered_today(dsn=dsn)
    if used >= cap:
        return {"ok": False, "note": f"generated-reference cap reached ({used}/{cap} today, REFGEN_DAILY_CAP)"}
    pass_id = scout.generated_pass_id(finding_id)   # its own bin, read first
    prompt = build_prompt(hook_frame)

    import uuid

    from . import charge as charging
    from . import ledger
    charge = charging.Charge(account_id, provider="refgen",
                             ref=f"refgen-{int(finding_id)}-{uuid.uuid4().hex}",
                             estimate_usd=hold_usd(), dsn=dsn)
    try:
        charge.take()              # a no-op for the unowned pool and exempt accounts
    except ledger.InsufficientCredit as e:
        return {"ok": False, "note": charging.refusal(e, "this reference")}
    charge.submitted()
    try:
        result = render(prompt)
        if not result["path"]:
            why = "; ".join(f"{p}: {e}" for p, e in result["tried"]) or "no provider configured"
            return {"ok": False, "note": f"nothing rendered -- {why}", "prompt": prompt}
        jpeg = refbin.to_jpeg(Path(result["path"]).read_bytes())
        stored = refbin.save(jpeg) if jpeg else None
        if not stored:
            return {"ok": False, "note": "render could not be normalised to JPEG", "prompt": prompt}
        row = scout.bin_add(finding["brand"], pass_id, stored,
                            source_url=f"generated://{result['provider']}/{Path(stored).stem}",
                            title=f"generated: {result['provider']} -- {hook_frame.strip()[:140]}",
                            lane="generated", dsn=dsn)
        if row is None:
            return {"ok": False, "note": "the pass is full or the write failed", "prompt": prompt}
        credits = charge.settle(provider_usd(result["provider"]))
    finally:
        charge.release("refgen: nothing banked")   # a no-op once settled
    print(f"refgen: {result['provider']} rendered a reference for finding {finding_id}",
          file=sys.stderr)
    return {"ok": True, "finding_id": int(finding_id), "pass_id": pass_id,
            "provider": result["provider"], "url": stored, "prompt": prompt,
            "fell_back_from": [p for p, _ in result["tried"]],
            "rendered_today": used + 1, "cap": cap, "credits": credits}
