"""
The video renderer registry -- and since 2026-09-26 it has ONE entry.

fal is the only video renderer (Mike's call, docs/tasks/task-fal-only.md):
one key, one balance, one adapter, one billing path. Runway, Veo (on the
Gemini key) and Higgsfield's video path were retired; Veo lives on as a
MODEL through fal (`veo3.1`). The registry shape stays because every door
that spends -- the Queue's approve, approve-all, the Director's Generate
node, the board's per-shot render, the nightly graph -- asks it the same
questions, and the answers must not come apart between doors:

- render_options()      the menu a card may offer, projected off
                        fal.VIDEO_MODELS (never a second copy of it)
- check_render_choice() a pick checked against that menu, REFUSED rather
                        than clamped when it is outside it
- platform_default()    a shot's planned tool -> the fal model it renders
                        on. A tool fal does not host (RUNWAY, HIGGSFIELD on
                        a row written before 2026-09-26) reads as the fal
                        default at read time; the row is never rewritten.
- renderer_for() / render_default() / choose_provider()
                        which renderer a door uses: fal, when the operator
                        key is set; None when it is not, which is the one
                        case a door refuses.

REQUIRED is still the contract an adapter has to meet, and conforms() is
still what checks it -- the next renderer, if there is one, is "write the
module to this shape and add one line to VIDEO_PROVIDERS".
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from types import ModuleType
from typing import Optional

from . import fal, generative

# The contract: every callable a router or a cap check needs. estimate_cost
# is called with n alone by the routers; a caller that wants a specific
# model/duration still calls the module directly.
REQUIRED = (
    "generate_video",
    "generate_candidates",
    # ONE render for ONE concept shot, attached to the shot when it lands.
    # In the contract so an adapter cannot arrive without it and quietly be
    # unreachable from the one surface that spends money.
    "generate_for_shot",
    "estimate_cost",
    "spend_approved",
    "has_key",
    "generations_today",
)

VIDEO_PROVIDERS: dict[str, ModuleType] = {
    "fal": fal,
}

# The failover's static order for a renderer with no history. One entry.
DEFAULT_ORDER: tuple[str, ...] = ("fal",)

DEFAULT_PROVIDER = "fal"

RENDER_LABELS: dict[str, str] = {"fal": "fal.ai"}

# What the third control IS: a resolution tier ("720p"). The key stays a
# lookup rather than a constant because the card reads it per renderer.
FRAME_AXIS: dict[str, str] = {"fal": "resolution"}

# The tool a shot planned before 2026-09-26 may still carry, which no
# renderer hosts any more. Read as the fal default (see platform_default);
# the stored row keeps its word.
RETIRED_PLATFORMS = frozenset({"runway", "higgsfield"})


def conforms(module: ModuleType) -> list[str]:
    """Which REQUIRED names this module is missing (empty = matches the
    contract). See tests/test_providers.py."""
    return [name for name in REQUIRED if not callable(getattr(module, name, None))]


def usable(account_id: Optional[int] = None, *,
           tools: Optional[list[str]] = None) -> list[str]:
    """Renderer names with a key AND spend approved for this run.

    Deliberately the ENVIRONMENT approval, not the per-call one: its only
    caller is choose_provider(), whose only caller is the nightly graph's
    failover -- an unattended path, where "approved" has to mean somebody
    armed this night on purpose. Does NOT check the daily cap; the
    adapter's own generate_candidates makes that per-attempt decision."""
    names = tools if tools is not None else list(VIDEO_PROVIDERS)
    return [
        name for name in names
        if name in VIDEO_PROVIDERS
        and VIDEO_PROVIDERS[name].has_key(account_id)
        and VIDEO_PROVIDERS[name].spend_approved()
    ]


def choose_provider(account_id: Optional[int] = None, *,
                     exclude: tuple[str, ...] = (),
                     db_path=None) -> Optional[str]:
    """The renderer a caller should try next for a shot, or None.

    With one renderer this is "fal, unless fal is excluded or unusable" --
    and the graph excludes the provider that just failed, so a fal failure
    is not retried on fal through a different door. Ranked by this
    account's cost-per-keeper (generative.tool_scoreboard) when there is
    more than one candidate, which there is not today. Never raises."""
    candidates = [t for t in usable(account_id) if t not in exclude]
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    scoreboard = {
        row["tool"]: row["cost_per_keeper"]
        for row in generative.tool_scoreboard(db_path, account_id=account_id)
        if row["cost_per_keeper"] is not None
    }

    def rank(tool: str):
        scored = scoreboard.get(tool)
        default_rank = DEFAULT_ORDER.index(tool) if tool in DEFAULT_ORDER else len(DEFAULT_ORDER)
        return (scored is None, scored if scored is not None else 0.0, default_rank, tool)

    return sorted(candidates, key=rank)[0]


# --------------------------------------------------------------------------
# the render options catalogue -- what the Queue's picker may offer
# --------------------------------------------------------------------------
# A PROJECTION, NEVER A TABLE. Every number below lives in fal.VIDEO_MODELS,
# dated against the vendor's own schema page. A second copy here would be
# the day the card offers a length the adapter refuses.
#
# Two kinds of duration: a model with a span of legal lengths ("range")
# and a model that takes an enum of them ("choices": LTX-2.3's 6/8/10,
# Veo's 4/6/8). Flattening both into one list would either hide legal
# lengths or invent illegal ones, so the KIND travels with the values.

def _choices(values, default, *, note: str = "") -> dict:
    values = [v for v in values]
    return {"kind": "choices", "values": values,
            "default": default if default in values else (values[0] if values else None),
            "note": note}


def _span(low, high, default, *, note: str = "") -> dict:
    low, high = int(low), int(high)
    return {"kind": "range", "min": low, "max": high,
            "default": int(min(max(int(default), low), high)), "note": note}


def _fixed(value, *, note: str) -> dict:
    """One legal value and a stated reason there is only one. The card
    prints the note beside the disabled control."""
    return {"kind": "fixed", "values": [value], "default": value, "note": note}


def _fal_models() -> list[dict]:
    out = []
    for name, spec in sorted(fal.VIDEO_MODELS.items()):
        low, high = spec["durations"]
        default_seconds = fal.fit_duration(name, fal.DEFAULT_DURATION)
        values = spec.get("duration_values")
        duration = (_choices(list(values), default_seconds) if values
                    else _span(low, high, default_seconds))
        resolutions = [r for r in spec.get("resolutions") or ()]
        default_res = spec.get("default_resolution") or (resolutions[0] if resolutions else None)
        takes_resolution = "resolution" in (spec.get("params") or ())
        out.append({
            "id": name,
            "label": f"{name} ({spec['platform']})",
            "platform": spec["platform"],
            "available": True,
            "duration": duration,
            "frame": (_choices(resolutions, default_res) if takes_resolution
                      else _fixed(default_res,
                                  note=f"{name} takes no resolution field -- it "
                                       f"renders at {default_res}")),
            "verified": spec.get("checked"),
        })
    return out


_MODEL_PROJECTIONS = {"fal": _fal_models}

# Per-clip cost, asked of the adapter that owns the rate card. fal's is
# close to an invoice: a published per-second rate per model and resolution.
ESTIMATORS = {
    "fal": lambda model, duration, frame: fal.estimate_cost(
        1, model=model, duration=duration, resolution=frame),
}

# --------------------------------------------------------------------------
# price bands -- which tier a render belongs to, and how long it may be
# QUOTED for (src/pricing.py reads these; nothing here prices)
# --------------------------------------------------------------------------
# THREE TIERS (the plans in pricing.PLANS): standard is what a Starter plan
# renders, creator adds the Kling and Seedance family, premium adds Veo and
# 1080p Seedance. An account with no plan has no tier and is not refused
# here -- with no credit it cannot hold (pricing.tier_for).
#
# THE BAND IS A PROPERTY OF THE RENDER, NOT ONLY OF THE MODEL (2026-09-26):
# Seedance 2.0 at 1080p costs $0.682/s against $0.3034/s at 720p, so the
# same model sits in two bands by resolution. BANDS maps (provider, model)
# to its band, and BAND_BY_FRAME overrides it for one resolution.
#
# max_seconds caps the QUOTE, never the render. None means the model's own
# legal maximum.
TIERS = ("standard", "creator", "premium")      # ascending: a tier may use itself and below


@dataclass(frozen=True)
class Band:
    tier: str
    max_seconds: Optional[int] = None


BANDS: dict[tuple[str, str], Band] = {
    ("fal", "ltx2.3"): Band("standard"),
    ("fal", "wan3"): Band("standard"),
    ("fal", "kling3-turbo-pro"): Band("creator"),
    ("fal", "seedance2-fast"): Band("creator"),
    ("fal", "seedance2"): Band("creator"),
    ("fal", "veo3.1"): Band("premium", max_seconds=8),
}

BAND_BY_FRAME: dict[tuple[str, str, str], Band] = {
    ("fal", "seedance2", "1080p"): Band("premium"),
}


def band_for(provider: str, model: str, frame: Optional[str] = None) -> Band:
    """The band one render sits in. A model nobody banded is PREMIUM: a new
    entry in the spec table must not become quotable on every plan by being
    forgotten here (tests/test_pricing.py also fails on the omission)."""
    if frame is not None:
        by_frame = BAND_BY_FRAME.get((provider, model, str(frame)))
        if by_frame is not None:
            return by_frame
    return BANDS.get((provider, model), Band("premium"))


def platform_default(platform: Optional[str]) -> Optional[tuple[str, str]]:
    """(provider, model) for a shot's planned tool, or None when it names
    nothing at all. The fal platforms resolve through fal.PLATFORM_MODELS --
    the same binding orchestrator.generate_render holds. A RETIRED platform
    (RUNWAY, HIGGSFIELD on a shot written before 2026-09-26) is read as the
    fal default: the row keeps its word, the render goes where renders go."""
    name = (platform or "").strip().lower()
    if not name:
        return None
    if name in fal.PLATFORM_MODELS:
        return ("fal", fal.PLATFORM_MODELS[name])
    if name in RETIRED_PLATFORMS:
        return ("fal", default_model("fal"))
    return None


def default_model(provider: str) -> str:
    """What the card offers first: the adapter's DEFAULT_MODEL when the
    catalogue knows it (FAL_MODEL can name anything), else the first model
    it does."""
    known = [m["id"] for m in models_for(provider)]
    fallback = getattr(VIDEO_PROVIDERS[provider], "DEFAULT_MODEL", None)
    if fallback in known:
        return fallback
    usable_first = [m["id"] for m in models_for(provider) if m["available"]]
    return (usable_first or known or [fallback])[0]


def _price_for(provider: str, spec: dict) -> dict:
    """The rate card a CARD can multiply, so moving a duration slider does
    not cost a round trip per keystroke. {"kind": "per_second",
    "usd_by_frame": {...}} -- tests/test_providers.py asserts that product
    equals the adapter's OWN estimate_cost for every model, legal duration
    and frame. The card's figure is a LABEL; check_render_choice computes
    the authoritative estimate server-side."""
    if provider == "fal":
        return {"kind": "per_second",
                "usd_by_frame": {res: fal.price_per_second(spec["id"], res)
                                 for res in spec["frame"]["values"]}}
    return {"kind": "unknown"}


def models_for(provider: str) -> list[dict]:
    """This provider's legal render options, projected off its own spec
    table. Raises ValueError on a provider that is not registered."""
    if provider not in _MODEL_PROJECTIONS:
        raise ValueError(
            f"unknown renderer {provider!r} -- one of {sorted(VIDEO_PROVIDERS)}")
    return [dict(spec, price=_price_for(provider, spec))
            for spec in _MODEL_PROJECTIONS[provider]()]


def model_options(provider: str, model: str) -> dict:
    for spec in models_for(provider):
        if spec["id"] == model:
            return spec
    raise ValueError(
        f"{RENDER_LABELS.get(provider, provider)} has no model {model!r} -- "
        f"one of {[m['id'] for m in models_for(provider)]}")


def _check_axis(axis: dict, value, *, what: str, model: str):
    """One control's claim against its own legal set. REFUSES rather than
    clamping: a value outside the set is evidence that the card and the
    model have come apart, and rounding it silently spends money on
    something nobody chose. (The adapter fits internally -- that is its
    contract with the graph, which has no human to refuse to.)"""
    if value is None:
        return axis["default"]
    kind = axis["kind"]
    if kind == "range":
        try:
            seconds = int(value)
        except (TypeError, ValueError):
            raise ValueError(f"{what} {value!r} is not a number") from None
        if not (axis["min"] <= seconds <= axis["max"]):
            raise ValueError(
                f"{model} renders {axis['min']}-{axis['max']}s, not {seconds}s")
        return seconds
    legal = axis["values"]
    picked = value
    # a duration arrives from a JSON body as either 6 or "6"; a resolution
    # never does. Coerce only when the legal set is numeric.
    if legal and isinstance(legal[0], int):
        try:
            picked = int(value)
        except (TypeError, ValueError):
            raise ValueError(f"{what} {value!r} is not a number") from None
    if picked not in legal:
        if kind == "fixed":
            raise ValueError(
                f"{model} is fixed at {what} {axis['default']!r} here -- {axis['note']}")
        raise ValueError(f"{model} does not render {what} {value!r} -- one of {legal}")
    return picked


def check_render_choice(provider: Optional[str] = None, model: Optional[str] = None,
                        duration=None, frame=None) -> dict:
    """The whole picked combination, resolved and checked, or ValueError.

    Returns {"provider", "model", "duration", "frame", "estimate_usd"} --
    every field filled in, so a caller that passed nothing gets the
    defaults and a caller that passed a lie gets told which part of it
    was the lie before anything is spent."""
    provider = (provider or DEFAULT_PROVIDER).strip().lower()
    if provider not in VIDEO_PROVIDERS:
        raise ValueError(
            f"unknown renderer {provider!r} -- one of {sorted(VIDEO_PROVIDERS)}")
    model = (model or default_model(provider))
    spec = model_options(provider, model)
    if not spec["available"]:
        raise ValueError(f"{model} is not reachable -- pick another model")
    seconds = _check_axis(spec["duration"], duration,
                          what="duration", model=model)
    framed = _check_axis(spec["frame"], frame,
                         what=FRAME_AXIS.get(provider, "resolution"), model=model)
    return {"provider": provider, "model": model,
            "duration": seconds, "frame": framed,
            "estimate_usd": ESTIMATORS[provider](model, seconds, framed)}


@dataclass(frozen=True)
class RenderContext:
    """What ONE account holds right now, asked once: whether each renderer
    is keyed, what each has rendered today, and the account's plan.

    A listing builds one and hands it to render_default / render_options /
    pricing.display for every card, so the per-account questions are asked
    per REQUEST and not per card. A snapshot for drawing a page and nothing
    else: no gate reads one. A context is only honoured for the account
    (and database) it was built for -- see _held."""
    account_id: Optional[int]
    db_path: Optional[str]
    keyed: dict
    today: dict
    # accounts.plan_of's answer (a pricing.PLANS key or None). `plan_known`
    # is what says it was asked: None is a real answer, "no plan".
    plan: Optional[str] = None
    plan_known: bool = False


def render_context(account_id: Optional[int] = None, db_path=None) -> RenderContext:
    """Build the snapshot through the same seams that answer each question
    alone (has_key, generations_today), with the same degrade."""
    keyed, today = {}, {}
    for name in VIDEO_PROVIDERS:
        keyed[name] = _keyed(name, account_id)
    with generative.counted_today(account_id, db_path):
        for name, module in VIDEO_PROVIDERS.items():
            try:
                today[name] = module.generations_today(db_path, account_id=account_id)
            except Exception:
                today[name] = None
    from . import accounts  # lazily, as pricing.tier_for does
    return RenderContext(account_id=account_id, db_path=db_path,
                         keyed=keyed, today=today,
                         plan=accounts.plan_of(account_id, dsn=db_path),
                         plan_known=True)


def _held(ctx: Optional[RenderContext], account_id: Optional[int],
          db_path=None) -> Optional[RenderContext]:
    """`ctx` when it answers for this account and database, else None --
    a context built for somebody else is ignored, never trusted."""
    if ctx is not None and ctx.account_id == account_id and ctx.db_path == db_path:
        return ctx
    return None


@contextmanager
def key_scope(ctx: Optional[RenderContext], account_id: Optional[int]):
    """Kept for callers written when a context carried stored key rows.
    There are no stored keys since 2026-09-26, so it is a no-op."""
    yield


def provider_state(provider: str, account_id: Optional[int] = None,
                   db_path=None, ctx: Optional[RenderContext] = None) -> dict:
    """Whether approving on this renderer could happen, and what it has
    spent today. The daily count degrades to None on a database that has
    never rendered anything -- a Queue that 500s because nothing has been
    billed on it is the wrong failure."""
    module = VIDEO_PROVIDERS[provider]
    held = _held(ctx, account_id, db_path)
    if held is not None and provider in held.today and provider in held.keyed:
        today, available = held.today[provider], held.keyed[provider]
    else:
        try:
            today = module.generations_today(db_path, account_id=account_id)
        except Exception:
            today = None
        try:
            available = bool(module.has_key(account_id))
        except Exception:
            available = False
    return {
        "label": RENDER_LABELS.get(provider, provider),
        "available": available,
        # A KEY IS THE WHOLE GATE ON THIS SURFACE (2026-09-09): the click is
        # the approval, and the route passes it explicitly.
        "spend_ok": available,
        # The env override an unattended run (orchestrator, autopilot, the
        # CLI) needs, reported so a person can see whether it is armed. NOT
        # a gate on anything a person clicks.
        "env_override": bool(module.spend_approved()),
        "spend_env": getattr(module, "SPEND_ENV", None),
        "cap": getattr(module, "DAILY_CAP", None),
        "today": today,
        "frame_axis": FRAME_AXIS.get(provider, "resolution"),
    }


def render_options(account_id: Optional[int] = None, db_path=None,
                   ctx: Optional[RenderContext] = None) -> dict:
    """Every renderer the Queue may offer, with its gates and its legal
    options, in one call so the menu answers from one moment."""
    out = {}
    for name in VIDEO_PROVIDERS:
        try:
            models = models_for(name)
        except Exception:
            models = []
        out[name] = {
            **provider_state(name, account_id, db_path, ctx),
            "models": models,
            "default_model": default_model(name) if models else None,
        }
    return out


# --------------------------------------------------------------------------
# which renderer a door uses -- one answer for every door
# --------------------------------------------------------------------------

def _keyed(provider: str, account_id: Optional[int],
           ctx: Optional[RenderContext] = None) -> bool:
    """Is this renderer's operator key set? Never raises: a renderer whose
    key lookup breaks is one nobody can use right now."""
    held = _held(ctx, account_id)
    if held is not None and provider in held.keyed:
        return held.keyed[provider]
    try:
        return bool(VIDEO_PROVIDERS[provider].has_key(account_id))
    except Exception:
        return False


def renderer_for(account_id: Optional[int] = None,
                 provider: Optional[str] = None,
                 model: Optional[str] = None, *,
                 needs: str = "generate_for_shot",
                 ctx: Optional[RenderContext] = None) -> Optional[dict]:
    """{"provider", "model"} this door can render on, or None.

    `provider`/`model` are the preference -- the shot's plan, or what a
    caller asked for. A preference for a renderer that is not registered
    (a retired one) is read as fal. The model is kept when fal has it and
    replaced by fal's default when it does not. None means the operator
    key is not set -- the one case where a door should refuse, and say so.
    `needs` is the adapter entry point the door will call."""
    name = (provider or DEFAULT_PROVIDER).strip().lower()
    if name not in VIDEO_PROVIDERS:
        name, model = DEFAULT_PROVIDER, None
    module = VIDEO_PROVIDERS[name]
    if not hasattr(module, needs) or not _keyed(name, account_id, ctx):
        return None
    try:
        spec = model_options(name, model or default_model(name))
    except ValueError:
        spec = model_options(name, default_model(name))
    if not spec["available"]:
        return None
    return {"provider": name, "model": spec["id"]}


def render_default(tool: Optional[str],
                   account_id: Optional[int] = None,
                   ctx: Optional[RenderContext] = None) -> dict:
    """The Queue's default for a shot planned for `tool`: the fal model
    that platform binds to, else fal's default. Both the listing and an
    approve with an empty body resolve through here, so what the card
    offers first and what an empty approve spends on cannot come apart.
    Unkeyed, it still names the pick -- the card then says the key is
    missing rather than naming nothing."""
    want = platform_default(tool) or (DEFAULT_PROVIDER, default_model(DEFAULT_PROVIDER))
    usable_pick = renderer_for(account_id, want[0], want[1], ctx=ctx)
    if usable_pick:
        return usable_pick
    return {"provider": want[0], "model": want[1]}
