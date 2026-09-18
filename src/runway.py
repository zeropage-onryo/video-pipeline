#!/usr/bin/env python3
"""
The Runway connector: prompt -> video -> pipeline. veo.py's exact shape
(thin raising wrapper under a never-raises edge), one extra gate.

Two layers:
- generate_video      -- the thin wrapper. Create the task via the
                         runwayml SDK, wait for it, download the output
                         URL immediately (Runway's output URLs are
                         signed and ephemeral). Raises on failure; its
                         caller catches.
- generate_candidates -- the never-raises edge: N candidate clips for
                         one prompt, every attempt logged through
                         generative.record_generation. Nothing is ever
                         auto-kept -- the pick is the label.

THE SPEND GATE, and why it's here and not in callers: the Runway API
has no Explore Mode. Unlimited generation is a web-app feature of the
Unlimited/Max plan; API calls always burn API credits, a separate
balance from the app subscription ("web app credits will never appear
in your API credits" -- help.runwayml.com, checked 2026-08-12). So the
cheap path is the app, and the API is a deliberate spend:
- THE APPROVAL IS THE CLICK (2026-09-09, Mike's call). generate_video
  refuses unless the caller passes approved=True, which the routes a
  person drives do and nothing else does. RUNWAY_SPEND_OK=1 still satisfies
  the gate when no caller says otherwise -- that is what keeps the
  unattended paths (orchestrator, autopilot, the CLI) needing a
  deliberate arming of their own. See spend_approved().
  The free path is still the honest default answer to "should this be an
  API render at all": Explore Mode in the Runway app costs nothing on
  the Unlimited plan, and the refusal still says so.
- DAILY_CAP (RUNWAY_DAILY_CAP, default 6) counted from the generations
  table, same wall veo.py has.
- estimate_cost() prices a plan before anyone approves it.

SDK verified against docs.dev.runwayml.com 2026-08-12: package
`runwayml`, key in RUNWAYML_API_SECRET, client.image_to_video.create
(omit prompt_image for text-to-video), models gen4_turbo (5 credits/s)
and gen4.5 (12 credits/s) at $0.01/credit, ratio "720:1280" for 9:16,
wait_for_task_output() polls and raises TaskFailedError. Re-verify on
SDK bump -- Runway versions these.

THE REFERENCE LANE (2026-09-12). Neither gen4 model can be handed a
reference image: the SDK types their promptImage entries as
`position: Required[Literal["first"]]` and gives them no reference
field, so on those two a shot's `refs` reach the clip only as pixels
Nano baked into the keyframe. seedance2_5 is registered beside them
because it takes references directly -- "omit position for reference
images", with the API's own warning that "the two modes cannot be
mixed", which is why build_prompt_image is the one place that decides
and reference_mode() decides it by the shot's position in the scene.
It is dearer by a lot (20/30/68 credits/s at 480p/720p/1080p against
gen4_turbo's flat 5, 80-credit floor per generation) and roomier by a
lot (15000 prompt characters against 1000). Nothing switches to it on
its own: the Queue passes a model a person picked, and RUNWAY_MODEL
is what changes the default.
"""
from __future__ import annotations

import base64
import os
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from . import account_keys, generative, ledger, render_assets, render_specs
from . import charge as charging
from .shot import Shot

# The model list, the frame and the legal durations all come from
# src/render_specs.py, which imports nothing at all -- so ops/render_queue.py
# can check what a by-hand render CLAIMS against the same numbers this
# adapter renders by, without importing this module (google-genai comes in
# here through render_assets, and that script must run on a bare python3).
# Before 2026-09-08 the manual lane held a second copy of the ratio and a
# test asserted the two had not drifted; a shared constant cannot drift.
MODELS = tuple(render_specs.RUNWAY_MODELS)
DEFAULT_MODEL = os.environ.get("RUNWAY_MODEL", "gen4_turbo")   # cheapest first spend
DEFAULT_RATIO = render_specs.RATIO_9_16   # 9:16, the platform vertical
# The model a render switches to when the point of the shot is its
# reference photos. NOT applied automatically: the Queue passes an
# explicit `model=` that a person chose, and overriding that from inside
# the adapter is the silent-substitution failure this repo keeps writing
# tests against. Set RUNWAY_MODEL=seedance2_5 to make the reference lane
# the default for everything instead.
REFERENCE_MODEL = os.environ.get("RUNWAY_REFERENCE_MODEL", "seedance2_5")
DEFAULT_DURATION = 5
DAILY_CAP = int(os.environ.get("RUNWAY_DAILY_CAP", "6"))
# The installation-wide wall, beside the per-account one. Defaults to the
# SAME number, so a single-operator database behaves exactly as it did --
# admitting a second account is what forces a deliberate decision about
# whose card is paying, instead of the total quietly doubling.
GLOBAL_DAILY_CAP = int(os.environ.get("RUNWAY_GLOBAL_DAILY_CAP", str(DAILY_CAP)))

SPEND_ENV = "RUNWAY_SPEND_OK"

# $0.01/credit; credits/second per model, dev-portal pricing 2026-08-12.
CREDIT_USD = 0.01
CREDITS_PER_SECOND = {"gen4_turbo": 5, "gen4.5": 12}

# Seedance 2.5 prices by OUTPUT RESOLUTION, not by model name
# (docs.dev.runwayml.com/guides/pricing, checked 2026-09-12): 20 credits/s
# at 480p, 30 at 720p, 68 at 1080p, with an 80-credit floor on any single
# generation. A flat entry in CREDITS_PER_SECOND would have priced a
# 1080p reference render at under half its real cost, which is the number
# a person reads before approving the spend. The frame names its tier
# through render_specs.seedance_tier -- NOT through the short side of the
# ratio, which does not identify it: 992:432 is a 480p frame and 752:560
# is another, so any arithmetic shortcut here misprices real frames.
SEEDANCE_CREDITS_BY_TIER = {"480p": 20, "720p": 30, "1080p": 68}
SEEDANCE_MIN_CREDITS = 80
# Which registered models bill off that table. Derived from the registry
# rather than listed twice: a model added to render_specs without a rate
# here would otherwise price at the gen4 ceiling and read as plausible.
SEEDANCE_MODELS = frozenset(
    name for name in render_specs.RUNWAY_MODELS if name.startswith("seedance"))

# promptText caps, straight off the runwayml SDK's own type definitions.
# Both models this project uses take 1000 characters; the roomier ones
# (seedance2 at 3500, seedance2_5 at 15000) are named in the error so a
# prompt that will not fit says where it WOULD fit. This matters because
# a director's prompt here runs 1400-1500 characters and puts its Avoid
# list LAST -- silently truncating would drop exactly the constraints
# the look depends on, so an over-long prompt refuses instead, before
# any credit is spent (2026-08-29).
PROMPT_LIMITS = {"gen4_turbo": 1000, "gen4.5": 1000, "seedance2_5": 15000}
DEFAULT_PROMPT_LIMIT = 1000


def prompt_limit(model: str = DEFAULT_MODEL) -> int:
    return PROMPT_LIMITS.get(model, DEFAULT_PROMPT_LIMIT)


def check_prompt_length(prompt: str, model: str = DEFAULT_MODEL) -> None:
    """Raise before spending if promptText will not fit.

    Measured in UTF-16 code units, which is what the API counts -- an
    emoji or an accented character is not always one unit, and a prompt
    that passes a len() check can still be rejected by the API."""
    limit = prompt_limit(model)
    used = len((prompt or "").encode("utf-16-le")) // 2
    if used > limit:
        raise ValueError(
            f"prompt is {used} characters, {model} takes {limit} "
            f"(cut {used - limit}). Trim the shot description before the "
            f"Avoid list -- the negatives are what hold the look. Roomier "
            f"models: seedance2 (3500), seedance2_5 (15000)."
        )


def render_aliases(db_path=None, account_id: Optional[int] = None) -> dict:
    """Asset name -> the phrase to use instead when talking to Runway.

    Runway's moderation reads a NAME, not your intent: "Cyclops" is a
    Marvel character to a classifier however Homeric yours is, and the
    whole prompt is refused for "referencing third party content"
    (2026-08-29). The name was never doing the work anyway -- the
    keyframe carries the look -- so it costs nothing to describe the
    thing instead.

    Explicit per asset (`description.render_alias`), never guessed: no
    list of trademarks could be complete, and swapping every asset name
    for its full description would blow a 1000-character budget on the
    first sentence. Set it on the assets that actually get flagged.
    """
    import json

    try:
        from . import entities
        kwargs = {"dsn": db_path} if db_path is not None else {}
        rows = (entities.list_characters(**kwargs, account_id=account_id)
                + entities.list_props(**kwargs, account_id=account_id))
    except Exception:
        return {}          # sanitising is a courtesy, never a gate
    out = {}
    for row in rows:
        name = (row.get("name") or "").strip()
        raw = row.get("description") or ""
        try:
            alias = (json.loads(raw) or {}).get("render_alias")
        except (ValueError, TypeError):
            alias = None
        if name and isinstance(alias, str) and alias.strip():
            out[name] = alias.strip()
    return out


def safe_prompt(prompt: str, db_path=None) -> str:
    """The prompt with flagged asset names swapped for their aliases."""
    text = prompt or ""
    for name, alias in render_aliases(db_path).items():
        text = re.sub(r"(?<![\w])" + re.escape(name) + r"(?![\w])",
                      alias, text, flags=re.IGNORECASE)
    return text


def spend_approved(approved: Optional[bool] = None) -> bool:
    """Is this ONE call approved to spend?

    THE APPROVAL IS THE CLICK NOW (2026-09-09, Mike's call). It used to
    be RUNWAY_SPEND_OK=1 in the process environment, set per run on the command
    and never in .env -- "an approval that's always on isn't an
    approval". That reasoning was right about what an approval IS and
    wrong about where this one lives: the person approving a render is
    standing at the Queue pressing a priced button, and making them
    restart the server with an environment variable to make that button
    work meant the variable ended up set for the whole session anyway --
    an approval that was always on, arrived at the long way round.

    So the approval became an ARGUMENT. `approved=True` is passed by the
    routes a human drives and by nothing else, which is what the env var
    was really standing in for. The check still lives inside
    generate_video, so no caller can spend around it.

    The environment variable still satisfies the gate when no caller
    says otherwise. That is deliberate and it is what keeps the
    unattended paths exactly as safe as they were: orchestrator.py and
    autopilot.py pass no approval, so a nightly run still needs
    RUNWAY_SPEND_OK=1 set for it on purpose, on top of its own flags. Same for
    the CLI and the ops scripts.
    """
    if approved is not None:
        return bool(approved)
    return (os.environ.get(SPEND_ENV) or "").strip() == "1"


def _safe_error(e: Exception, account_id: Optional[int] = None) -> str:
    """The key must never reach a page, a log line, or a DB row -- and
    since BYOK the key that would leak is often NOT the one in the
    environment. So redact whatever this account actually rendered on
    (its own stored secret when it has one, the env fallback otherwise)
    as well as the env value, then any Bearer token the text still
    carries. Resolving the account key is best-effort: redaction runs on
    the failure path and must never be the thing that raises there."""
    text = str(e)
    secrets = [os.environ.get("RUNWAYML_API_SECRET")]
    try:
        creds = account_keys.key_for(account_id, "runway")
    except Exception:
        creds = None
    if creds:
        secrets.append(creds.get("api_secret"))
    for secret in secrets:
        if secret:
            text = text.replace(secret, "<RUNWAYML_API_SECRET>")
    return re.sub(r"(Bearer\s+)[A-Za-z0-9_\-.]+", r"\1<redacted>", text)


def takes_references(model: str = DEFAULT_MODEL) -> bool:
    """Whether this model can be handed reference images at all."""
    return render_specs.takes_references("runway", model)


def credits_per_second(model: str = DEFAULT_MODEL, ratio: str = DEFAULT_RATIO) -> int:
    """The rate one second of this render bills at.

    A flat per-model number for the gen4 pair, a per-resolution one for
    Seedance. An unknown model costs the MOST this module knows about
    rather than the least: an estimate a person approves against should
    err high, because the failure mode of erring low is a spend that was
    never really agreed to."""
    flat = CREDITS_PER_SECOND.get(model)
    if flat is not None:
        return flat
    if model in SEEDANCE_MODELS:
        tier = render_specs.seedance_tier(ratio)
        return SEEDANCE_CREDITS_BY_TIER.get(
            tier, max(SEEDANCE_CREDITS_BY_TIER.values()))
    return max(max(CREDITS_PER_SECOND.values()),
               max(SEEDANCE_CREDITS_BY_TIER.values()))


def estimate_cost(n: int, *, model: str = DEFAULT_MODEL,
                  duration: int = DEFAULT_DURATION,
                  ratio: str = DEFAULT_RATIO) -> float:
    """What `n` clips of this shape cost, in dollars, before anyone
    approves them. `ratio` is accepted (and defaulted) rather than
    required so every existing caller keeps working -- it only changes
    the answer on a model whose rate card is per-resolution."""
    credits = duration * credits_per_second(model, ratio)
    if model in SEEDANCE_MODELS:
        credits = max(credits, SEEDANCE_MIN_CREDITS)
    return round(n * credits * CREDIT_USD, 2)


def generations_today(db_path=None, *, account_id=None, everyone: bool = False) -> int:
    """This account's runway generations since UTC midnight -- what
    DAILY_CAP counts against. `everyone=True` gives the installation-wide
    count that GLOBAL_DAILY_CAP counts against."""
    return generative.used_today(
        "runway", db_path,
        account_id=account_id, everyone=everyone,
    )


def _make_client(account_id: Optional[int] = None):
    """
    account_id's own stored key (BYOK, backlog #10) if it has one, else
    RUNWAYML_API_SECRET from the environment -- account_keys.key_for()
    does that fallback, so an account with nothing stored renders on
    Mike's key exactly as before BYOK existed.
    """
    creds = account_keys.key_for(account_id, "runway")
    key = creds["api_secret"] if creds else None
    if not key:
        raise RuntimeError("RUNWAYML_API_SECRET not set")
    try:
        from runwayml import RunwayML
    except ImportError as e:
        raise RuntimeError("runwayml SDK not installed -- it's in requirements.txt") from e
    return RunwayML(api_key=key)


def _download(url: str, out_path: Path) -> None:
    """Runway's output URLs are signed and expire; download the moment
    the task finishes, the repo keeps the file forever."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=120) as response, open(out_path, "wb") as f:
        while True:
            chunk = response.read(1024 * 256)
            if not chunk:
                break
            f.write(chunk)


def generate_video(prompt: str, out_path, *, model: str = DEFAULT_MODEL,
                   ratio: str = DEFAULT_RATIO, duration: int = DEFAULT_DURATION,
                   prompt_image=None, references=None, client=None, db_path=None,
                   approved: Optional[bool] = None,
                   account_id: Optional[int] = None,
                   charge: Optional[charging.Charge] = None) -> Path:
    """
    The thin wrapper: create -> wait -> download. Raises on anything --
    including a missing spend approval, which is checked HERE so no
    caller can spend a credit around the gate, and an empty credit
    balance (ledger.InsufficientCredit), checked here for the same
    reason (src/charge.py, 2026-09-18): the hold is taken AFTER the gate
    and BEFORE the submit, so a refusal means no HTTP call was made.
    `charge` is the caller's Charge when it will record the generation
    and settle with its id; without one this call holds and settles its
    own, at the estimate. generate_candidates is the layer that catches.
    """
    if not spend_approved(approved):
        raise RuntimeError(
            f"credit spend not approved: this call was not approved by a person. "
            f"Render it in the Runway app instead (Explore Mode, free on the "
            f"Unlimited plan), approve it at the Queue, or set {SPEND_ENV}=1 for "
            f"an unattended run."
        )
    # Name-swap first, THEN measure: an alias changes the length, and
    # what we check has to be what we send.
    prompt = safe_prompt(prompt, db_path)
    check_prompt_length(prompt, model)
    client = client or _make_client(account_id)
    payload = build_prompt_image(prompt_image, references, model=model)
    kwargs = {"prompt_image": payload} if payload is not None else {}
    out_path = Path(out_path)
    own = charge is None
    if own:
        charge = charging.Charge(
            account_id, provider="runway", ref=out_path.name,
            estimate_usd=estimate_cost(1, model=model, duration=duration, ratio=ratio),
            key_source=account_keys.key_source(account_id, "runway", db_path),
            dsn=db_path)
    charge.take()          # InsufficientCredit raises HERE: nothing submitted
    charge.submitted()     # the last line before the provider call
    try:
        task = client.image_to_video.create(
            model=model,
            prompt_text=prompt,
            ratio=ratio,
            duration=int(duration),
            **kwargs,
        ).wait_for_task_output()

        outputs = getattr(task, "output", None) or []
        if not outputs:
            raise RuntimeError("Runway task finished with no output URL")

        _download(outputs[0], out_path)
    except Exception as e:
        charge.release(f"runway: {type(e).__name__}")
        raise
    if own:
        charge.settle()
    return out_path


def _shot_row_for_prompt(prompt: str, db_path, account_id: Optional[int] = None) -> int:
    """A generations row needs a shot to hang off. The graph's AI shots
    don't have one, so synthesize a minimal Shot -- the row exists to
    make the attempt countable, and its notes say where it came from."""
    kwargs = {"dsn": db_path} if db_path is not None else {}
    generative.init(**kwargs)
    shot = Shot(subject=prompt[:100], action="as prompted")
    return generative.add_shot(shot, notes="auto-created by runway.generate_candidates",
                               **kwargs, account_id=account_id)


def generate_candidates(prompt: str, out_dir, n: int = 3, *, shot_id: Optional[int] = None,
                        db_path=None, client=None, model: str = DEFAULT_MODEL,
                        approved: Optional[bool] = None,
                        account_id: Optional[int] = None, **cfg) -> dict:
    """
    Never raises. {"ok", "candidates": [{path, generation_id, model}],
    "error"} -- a missing approval, a missing key, a failed job, or the
    daily cap is a result the caller can show, not an exception that
    takes the run down. Partial success is success.
    """
    n = int(os.environ.get("RUNWAY_CANDIDATES", n))
    kwargs = {"dsn": db_path} if db_path is not None else {}

    try:
        if not spend_approved(approved):
            return {"ok": False, "candidates": [],
                    "error": f"credit spend not approved: render in the Runway app "
                             f"(Explore Mode, free) or set {SPEND_ENV}=1 to approve "
                             f"~${estimate_cost(n, model=model, duration=int(cfg.get('duration', DEFAULT_DURATION)))} "
                             f"of API credits for this run"}

        refusal = generative.cap_error(
            "runway", n, account_id=account_id,
            per_account=DAILY_CAP, ceiling=GLOBAL_DAILY_CAP,
            dsn=db_path,
            env_prefix="RUNWAY", phrase="generations used",
            used=generations_today(db_path=db_path, account_id=account_id),
            used_everywhere=generations_today(db_path=db_path, everyone=True),
        )
        if refusal:
            return {"ok": False, "candidates": [], "error": refusal}

        if shot_id is None:
            shot_id = _shot_row_for_prompt(prompt, db_path, account_id)

        out_dir = Path(out_dir)
        duration = int(cfg.get("duration", DEFAULT_DURATION))
        candidates, errors = [], []
        for i in range(1, n + 1):
            out_path = out_dir / f"cand{i}.mp4"
            try:
                generate_video(prompt, out_path, model=model, client=client,
                               db_path=db_path, approved=approved,
                               account_id=account_id, **cfg)
            except Exception as e:
                errors.append(f"candidate {i}: {_safe_error(e, account_id)}")
                continue
            generation_id = generative.record_generation(
                shot_id, "runway", prompt,
                params={"model": model,
                        "key_source": account_keys.key_source(account_id, "runway", db_path),
                        **cfg},
                output_path=str(out_path),
                cost_usd=estimate_cost(1, model=model, duration=duration),
                notes=None,
                **kwargs,
             account_id=account_id)
            candidates.append({"path": str(out_path),
                               "generation_id": generation_id, "model": model})

        return {"ok": bool(candidates), "candidates": candidates, "shot_id": shot_id,
                "error": "; ".join(errors) if errors else None}
    except Exception as e:
        return {"ok": False, "candidates": [], "error": _safe_error(e, account_id)}


# --- the scene board's one-click render (added 2026-08-21) -----------------

RENDER_DIR = Path(__file__).resolve().parent.parent / "data" / "renders" / "runway"


def has_key(account_id: Optional[int] = None) -> bool:
    return account_keys.key_for(account_id, "runway") is not None


RENDERS_ROOT = Path(__file__).resolve().parent.parent / "data" / "renders"


def _local_render_bytes(value: str):
    """A site-relative /renders/ URL -> that file's bytes, or None.

    A render is a local file no model provider can fetch by URL, and the
    path comes out of a stored shot, so anything escaping data/renders/
    is refused. Mirrors app/workflow_runner.render_bytes, which does the
    same job for the canvas; this copy exists so src/ never imports app/.
    """
    try:
        root = RENDERS_ROOT.resolve()
        target = (root / value[len("/renders/"):]).resolve()
        if root in target.parents and target.is_file():
            return target.read_bytes()
    except OSError:
        return None
    return None


def as_prompt_image(value, *, resolve_photo=None):
    """Anything we might have stored as a reference -> something Runway
    can actually anchor on, or None.

    Runway takes ONE frame, and it must be a public URL or an inline
    data: URI -- it cannot fetch /renders/nano/x.png or /refs/y.jpg off
    a local app. Until this existed, generate_for_shot dropped every
    non-http reference silently (`prompt_image = reference if
    reference.startswith("http")`), so a keyframe rendered on a machine
    without R2 anchored nothing while the Queue card said "anchors on
    the attached reference" and the credit was spent on the lie.

    The mime comes from the magic number, not a guess: Nano writes PNG,
    and the old bytes path hardcoded image/jpeg.
    """
    if isinstance(value, (bytes, bytearray)):
        data = bytes(value)
        if not data:
            return None
        from .gemini_utils import sniff_mime
        return ("data:" + sniff_mime(data) + ";base64,"
                + base64.b64encode(data).decode("ascii"))
    if not value or not isinstance(value, str):
        return None
    value = value.strip()
    if value.startswith(("http://", "https://", "data:image/")):
        return value
    data = None
    if value.startswith("/renders/"):
        data = _local_render_bytes(value)
    elif resolve_photo is not None:
        try:
            target = resolve_photo(value)
        except Exception:
            target = None
        if target is not None:
            try:
                data = Path(target).read_bytes()
            except OSError:
                data = None
    # a reference that cannot be resolved is dropped, never fatal --
    # an unanchored clip is worse than no clip only if nobody is told,
    # and generate_for_shot records prompt_image=False either way
    return as_prompt_image(data) if data else None


def reference_mode(part) -> bool:
    """Whether this shot renders in REFERENCE mode rather than anchored on
    its keyframe. The API makes this either/or -- "use position first/last
    for keyframe mode, or omit position for reference images; the two
    modes cannot be mixed" -- so something has to decide, once, per shot.

    The split (2026-09-12, Mike's call) is by position in the scene:

    - A single-shot scene (`part is None`) and the FIRST part of a
      timeline render in reference mode. Nothing upstream of them has to
      match, so what the photos show is worth more than a locked frame.
    - Part 2 and after keep the keyframe. `_keyframe_timeline` draws each
      part's still from the previous one (CONTINUITY_REF_LABEL) precisely
      so shot four still looks like shot one; handing those parts loose
      references instead would throw away the chain that exists to stop
      the look drifting, which is the failure the timeline was built to
      fix in the first place."""
    if part is None:
        return True
    try:
        return int(part) <= 1
    except (TypeError, ValueError):
        return False


def build_prompt_image(anchor=None, references=None, *, model: str = DEFAULT_MODEL):
    """The `promptImage` payload for one call, and the single place the
    API's either/or is enforced.

    No references -> the bare string every gen4 render has always sent,
    unchanged down to the type, so the keyframe path is byte-for-byte what
    it was. With references -> the array form with NO `position` on any
    entry, because one positioned entry would put the request in keyframe
    mode and the API rejects the mix.

    The anchor is not discarded in reference mode, it is demoted: it rides
    along as the FIRST reference. It is still the only image composed for
    this shot specifically, so it is worth more than the photos it was
    composed from -- it just stops being a guarantee about frame one.
    Raises on a model that cannot read references at all: that is a
    programming error at the call site, not a render to attempt and
    silently under-deliver."""
    refs = [r for r in (references or []) if r]
    if not refs:
        return anchor
    if not takes_references(model):
        raise ValueError(
            f"{model} cannot take reference images -- its promptImage entries are "
            f"position:'first' only. Render on {REFERENCE_MODEL} (or any model "
            f"render_specs marks references:True), or pass references=None and "
            f"let the keyframe carry the look.")
    uris, seen = [], set()
    for uri in ([anchor] if anchor else []) + refs:
        if uri and uri not in seen:
            seen.add(uri)
            uris.append(uri)
    return [{"uri": uri} for uri in uris]


def reference_uris(target: dict, part, model: str, *, resolve_photo=None) -> list:
    """This shot's stored refs as things the API can read -- empty
    whenever they would not actually be sent, so the caller can record the
    count and have it mean what it says.

    Empty on a model that cannot carry them and empty in keyframe mode:
    in both cases the photos still reach the render, just through the
    keyframe's pixels the way they always have. A ref that will not
    resolve is dropped here exactly as as_prompt_image drops an anchor."""
    if not takes_references(model) or not reference_mode(part):
        return []
    out = []
    for url in target.get("refs") or []:
        uri = as_prompt_image(url, resolve_photo=resolve_photo)
        if uri:
            out.append(uri)
    return out


def generate_for_shot(concept_id: int, shot_n, *, db_path=None,
                      model: str = DEFAULT_MODEL, client=None,
                      duration: int = DEFAULT_DURATION,
                      ratio: str = DEFAULT_RATIO,
                      resolve_photo=None,
                      approved: Optional[bool] = None,
                      account_id: Optional[int] = None,
                      part: Optional[int] = None,
) -> dict:
    """
    `part` (2026-09-10) renders ONE shot of a timed scene -- its composed
    prompt, anchored on its own still, attached to that part (see
    src/timeline.py). None is the whole scene, exactly as before.

    Never raises: {"ok", "media_url", "generation_id", "error"}. One
    render for one concept shot, through every wall this module already
    has -- the spend gate lives inside generate_video, so this layer
    cannot spend around it; the cap is checked before any call; the
    attempt is a generations row either way the pick later goes.

    Reads the shot's stored prompt and anchors on its reference_image
    (what the reference is FOR) through as_prompt_image, so a keyframe
    that never reached R2 still anchors as inline bytes instead of
    silently rendering text-to-video. `resolve_photo` is the caller's
    asset-path resolver -- the web app passes its own; without one, a
    picked asset photo is simply dropped. Downloads the clip
    to data/renders/runway/, uploads to R2 when configured (Instagram
    needs a public URL), else leaves it served from the app's /renders
    mount -- and attaches the result via preprod.set_shot_media_url,
    the field autopilot.build_plan requires before it will ever emit a
    post action.
    """
    from . import preprod, storage
    kwargs = {"dsn": db_path} if db_path is not None else {}

    try:
        refusal = generative.cap_error(
            "runway", 1, account_id=account_id,
            per_account=DAILY_CAP, ceiling=GLOBAL_DAILY_CAP,
            dsn=db_path,
            env_prefix="RUNWAY", phrase="generations used",
            used=generations_today(db_path=db_path, account_id=account_id),
            used_everywhere=generations_today(db_path=db_path, everyone=True),
        )
        if refusal:
            return {"ok": False, "error": refusal}

        concept = preprod.get_concept(concept_id, **kwargs, account_id=account_id)
        if concept is None:
            return {"ok": False, "error": f"no concept {concept_id}"}
        shot = next((s for s in concept.get("shots") or []
                     if s.get("n") == shot_n), None)
        if shot is None:
            return {"ok": False, "error": f"concept {concept_id} has no shot {shot_n}"}
        from . import timeline
        target = timeline.render_target(shot, part)
        if target is None:
            return {"ok": False, "error": f"shot {shot_n} has no part {part}"}
        prompt = target["prompt"]
        if not prompt:
            return {"ok": False,
                    "error": f"shot {shot_n} has no AI prompt to render from"}

        # the keyframe (or picked photo) this shot anchors on, turned
        # into something the API can read -- see as_prompt_image
        prompt_image = as_prompt_image(target["reference_image"],
                                       resolve_photo=resolve_photo)
        # The shot's own reference photos, carried into the render itself
        # rather than only into the keyframe that was drawn from them.
        # Empty in keyframe mode and on a gen4 model -- see reference_uris.
        references = reference_uris(target, part, model,
                                    resolve_photo=resolve_photo)

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        out_path = RENDER_DIR / f"c{concept_id}-s{shot_n}{f'-p{part}' if part else ''}-{stamp}.mp4"
        key_source = account_keys.key_source(account_id, "runway", db_path)
        charge = charging.Charge(
            account_id, provider="runway", ref=out_path.name,
            estimate_usd=estimate_cost(1, model=model, duration=duration, ratio=ratio),
            key_source=key_source, dsn=db_path)
        generate_video(prompt, out_path, model=model,
                       duration=duration, ratio=ratio,
                       prompt_image=prompt_image, references=references,
                       client=client, db_path=db_path, approved=approved,
                       account_id=account_id, charge=charge)

        shot_row_id = _shot_row_for_prompt(prompt, db_path, account_id)
        # what was ACTUALLY asked for, not the module defaults: the
        # Queue lets a person pick a length and a frame per approve, and
        # a row that records the default instead would make the tool
        # scoreboard a measurement of a render nobody ran
        generation_params = {"model": model, "ratio": ratio,
                             "duration": duration,
                             "concept_id": concept_id, "shot_n": shot_n,
                             **({"part": part} if part else {}),
                             "prompt_image": bool(prompt_image),
                             # How many photos actually rode along, and
                             # whether the anchor was a locked first frame
                             # or demoted to a reference. A row reading 0
                             # on a shot that HAS refs is the honest record
                             # of a gen4 render, not a silence.
                             "references": len(references),
                             "reference_mode": bool(references),
                             "key_source": key_source,
                             **charge.params()}
        generation_id = generative.record_generation(
            shot_row_id, "runway", prompt,
            params=generation_params,
            output_path=str(out_path),
            cost_usd=estimate_cost(1, model=model, duration=duration, ratio=ratio),
            **kwargs,
         account_id=account_id)
        # the link from money to clip: closed at the estimate, which is
        # what cost_usd above records, never above what was held
        charge.settle(generation_id=generation_id)

        if storage.configured():
            media_url = storage.upload_file(
                out_path, key=f"renders/runway/{out_path.name}",
                content_type="video/mp4")
        else:
            media_url = f"/renders/runway/{out_path.name}"

        if part:
            timeline.attach_part(concept_id, shot_n, part, "media_url", media_url,
                                 db_path=db_path, account_id=account_id)
        else:
            preprod.set_shot_media_url(concept_id, shot_n, media_url, **kwargs, account_id=account_id)
        asset = render_assets.record_best_effort(
            account_id=account_id,
            generation_id=generation_id, tool="runway", model=model,
            media_kind="video", prompt=prompt, media_url=media_url,
            output_path=str(out_path), project=concept.get("brand"),
            concept_id=concept_id, shot_n=shot_n,
            metadata=generation_params,
            dsn=db_path,
        )
        return {"ok": True, "media_url": media_url,
                "generation_id": generation_id, "path": str(out_path),
                "asset_id": asset["id"], "asset_rag": asset["rag"],
                "error": None}
    except ledger.InsufficientCredit as e:
        return {"ok": False, "error": charging.refusal(e)}
    except Exception as e:
        return {"ok": False, "error": _safe_error(e, account_id)}


def generate_from_prompt(prompt: str, *, reference_image=None, db_path=None,
                         model: str = DEFAULT_MODEL, client=None,
                         approved: Optional[bool] = None,
                         account_id: Optional[int] = None,
) -> dict:
    """
    Never raises: {"ok", "media_url", "generation_id", "path", "error"}.
    The free-standing render behind the Workflows canvas's Generate
    node: a prompt plus an optional reference, no concept/shot row
    required -- generate_for_shot's walls without its coupling. The
    spend gate lives inside generate_video, so this layer cannot spend
    around it either; the cap is checked first; the attempt is a
    generations row via the same synthesized-shot path the graph uses.

    `reference_image` anchors the render through as_prompt_image: a
    public http(s) URL or a data: URI passes straight through, raw
    image bytes and a local /renders/ path become a data URI with the
    mime read off the magic number. Anything else is dropped -- a
    reference is an enhancement, never a gate.
    """
    from . import storage
    kwargs = {"dsn": db_path} if db_path is not None else {}

    try:
        prompt = (prompt or "").strip()
        if not prompt:
            return {"ok": False, "error": "an empty prompt renders nothing"}

        # a fresh DB has no generations table until something inits it;
        # the cap count below must not be the thing that discovers that
        generative.init(**kwargs)
        refusal = generative.cap_error(
            "runway", 1, account_id=account_id,
            per_account=DAILY_CAP, ceiling=GLOBAL_DAILY_CAP,
            dsn=db_path,
            env_prefix="RUNWAY", phrase="generations used",
            used=generations_today(db_path=db_path, account_id=account_id),
            used_everywhere=generations_today(db_path=db_path, everyone=True),
        )
        if refusal:
            return {"ok": False, "error": refusal}

        prompt_image = as_prompt_image(reference_image)

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        out_path = RENDER_DIR / f"wf-{stamp}.mp4"
        key_source = account_keys.key_source(account_id, "runway", db_path)
        charge = charging.Charge(
            account_id, provider="runway", ref=out_path.name,
            estimate_usd=estimate_cost(1, model=model),
            key_source=key_source, source="workflow", dsn=db_path)
        generate_video(prompt, out_path, model=model,
                       prompt_image=prompt_image, client=client,
                       db_path=db_path, approved=approved, account_id=account_id,
                       charge=charge)

        shot_row_id = _shot_row_for_prompt(prompt, db_path, account_id)
        generation_params = {"model": model, "ratio": DEFAULT_RATIO,
                             "duration": DEFAULT_DURATION,
                             "source": "workflow",
                             "prompt_image": bool(prompt_image),
                             "key_source": key_source,
                             **charge.params()}
        generation_id = generative.record_generation(
            shot_row_id, "runway", prompt,
            params=generation_params,
            output_path=str(out_path),
            cost_usd=estimate_cost(1, model=model),
            **kwargs,
         account_id=account_id)
        charge.settle(generation_id=generation_id)

        if storage.configured():
            media_url = storage.upload_file(
                out_path, key=f"renders/runway/{out_path.name}",
                content_type="video/mp4")
        else:
            media_url = f"/renders/runway/{out_path.name}"

        asset = render_assets.record_best_effort(
            account_id=account_id,
            generation_id=generation_id, tool="runway", model=model,
            media_kind="video", prompt=prompt, media_url=media_url,
            output_path=str(out_path), metadata=generation_params,
            dsn=db_path,
        )

        return {"ok": True, "media_url": media_url,
                "generation_id": generation_id, "path": str(out_path),
                "asset_id": asset["id"], "asset_rag": asset["rag"],
                "error": None}
    except ledger.InsufficientCredit as e:
        return {"ok": False, "error": charging.refusal(e)}
    except Exception as e:
        return {"ok": False, "error": _safe_error(e, account_id)}
