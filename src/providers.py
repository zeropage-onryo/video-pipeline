"""
The aggregator's registry: what video providers exist, whether one is
usable right now for a given account, and which one a router should pick
when several could render the same shot.

This formalizes a shape three modules already share by convention, not
contract: runway.py, veo.py and higgsfield.py each independently grew
generate_video, generate_candidates, estimate_cost, spend_approved,
has_key and generations_today with the same signatures. Nothing enforced
that shape until now -- conforms() below is what catches the next one
drifting the way veo.has_key() was simply missing until 2026-09-04.

kling, seedance, ltx and wan had prompt-compilation support in
shot.PLATFORMS (the vocabulary a Shot renders into) and no execution
adapter, for as long as this file has existed. fal.py (2026-09-08) is
that adapter: ONE entry here, because fal is one vendor, one key and one
queue API -- the four platform names are bindings of it
(fal.connector(name)) that orchestrator.generate_render holds, not four
registry entries pretending to be four vendors. Adding the next provider
is still "write the module to this shape, add one line to
VIDEO_PROVIDERS", not "invent a new interface".

WIRED INTO THE SPEND GATE since 2026-09-08 (Mike's call). The Queue's
approve button dispatches through VIDEO_PROVIDERS -- render_options()
below is the menu it offers, check_render_choice() is what it validates a
pick against, and platform_default() is how a shot's planned tool becomes
the card's default. Before that, `queue_approve` named runway in the route
body, so the one surface in this project that spends money could reach
exactly one of four working adapters: a concept shootgen planned for KLING
rendered on Kling at 3:30am and on Runway if a human approved the same row
by hand, with nothing anywhere saying so.

Still NOT wired on the generation side: orchestrator.py and
scene_chain.py name a tool explicitly (from a shot's Platform or a config
default), and choose_provider() is what a caller could start using in
place of that -- orchestrator.generate_render uses it only as the
failover after a named connector fails, which is deliberate. Picking the
vendor is a human decision at the spend gate; picking it FOR an
unattended run is a different question nobody has answered yet.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import ModuleType
from typing import Optional

from . import fal, generative, higgsfield, runway, veo

# The contract: every callable a router or a future BYOK/cap check needs.
# estimate_cost is checked with arity 1 in mind (n) -- runway and
# higgsfield accept extra keyword-only params with defaults, veo takes
# only n, so calling provider.estimate_cost(n) works uniformly across all
# three; a caller that wants a specific model/duration still calls the
# module directly.
REQUIRED = (
    "generate_video",
    "generate_candidates",
    # ONE render for ONE concept shot, attached to the shot when it lands
    # (2026-09-08). Runway and Higgsfield had grown this independently and
    # fal and Veo had not, which is exactly why the Queue's approve button
    # could only ever call Runway -- it was not a policy about which vendor
    # may spend, it was the only one that had this function. It is in the
    # contract now so the next adapter cannot arrive without it and quietly
    # be unreachable from the one surface that spends money.
    "generate_for_shot",
    "estimate_cost",
    "spend_approved",
    "has_key",
    "generations_today",
)

VIDEO_PROVIDERS: dict[str, ModuleType] = {
    "runway": runway,
    "veo": veo,
    "higgsfield": higgsfield,
    "fal": fal,
}

# Cheapest-first static fallback for a provider choose_provider() has no
# history for yet. Real per-clip figures (2026-08/09 dev-portal pricing,
# see each module's own COST_PER_CLIP_USD / CREDITS_PER_SECOND):
# runway ~$0.25 (gen4_turbo, 5s), fal ~$0.30 (LTX-2.3 at $0.06/s x 5s,
# its DEFAULT_MODEL and the cheapest clip in the repo), higgsfield ~$0.40+
# (duration-scaled), veo $3.20 flat. fal sits second on that number and
# nothing else: its per-second rate card is published and dated in
# fal.VIDEO_MODELS, so this is one of the few entries here that is a price
# rather than an estimate. Not used once an account has real
# kept/rejected data -- tool_scoreboard's cost_per_keeper replaces guessed
# sticker price with what this account actually paid per usable clip.
DEFAULT_ORDER: tuple[str, ...] = ("runway", "fal", "higgsfield", "veo")


def conforms(module: ModuleType) -> list[str]:
    """Which REQUIRED names this module is missing (empty = matches the
    contract). Run this against a new adapter before adding it to
    VIDEO_PROVIDERS, or against the registry itself as a standing check --
    see tests/test_providers.py."""
    return [name for name in REQUIRED if not callable(getattr(module, name, None))]


def usable(account_id: Optional[int] = None, *,
           tools: Optional[list[str]] = None) -> list[str]:
    """Tool names with a resolvable key (this account's own, per BYOK, or
    the environment fallback) AND spend approved for this run.

    Deliberately still the ENVIRONMENT approval, not the per-call one
    (2026-09-09). Its only caller is choose_provider(), whose only
    caller is orchestrator.generate_render's failover -- an unattended
    path, where "approved" has to mean somebody armed this night on
    purpose. The Queue's picker does not come through here; it asks
    render_options() and gates on a key.

    Does NOT check the daily cap -- that's a per-attempt decision each provider's
    own generate_candidates already makes, because it also has to log the
    attempt either way the check comes out."""
    names = tools if tools is not None else list(VIDEO_PROVIDERS)
    return [
        name for name in names
        if VIDEO_PROVIDERS[name].has_key(account_id)
        and VIDEO_PROVIDERS[name].spend_approved()
    ]


def choose_provider(account_id: Optional[int] = None, *,
                     exclude: tuple[str, ...] = (),
                     db_path=None) -> Optional[str]:
    """The provider a caller should try next for a shot.

    Ranked by this account's own cost-per-keeper from
    generative.tool_scoreboard() where history exists (cheapest usable
    clip first -- not cheapest sticker price, cheapest clip that was
    actually KEPT), DEFAULT_ORDER for tools with no history yet. `exclude`
    is for retrying after a failure: choose_provider(exclude=("runway",))
    picks the next-best tool instead of the one that just failed.

    None if nothing is usable right now -- no key for this account (its
    own or the environment fallback), or spend not approved for this run.
    Never raises; a caller with nothing usable gets the same shape a
    provider's own generate_candidates already returns for "not
    configured", just one level up.
    """
    candidates = [t for t in usable(account_id) if t not in exclude]
    if not candidates:
        return None

    scoreboard = {
        row["tool"]: row["cost_per_keeper"]
        for row in generative.tool_scoreboard(
            db_path,
            account_id=account_id,
        )
        if row["cost_per_keeper"] is not None
    }

    def rank(tool: str):
        scored = scoreboard.get(tool)
        default_rank = DEFAULT_ORDER.index(tool) if tool in DEFAULT_ORDER else len(DEFAULT_ORDER)
        # (has no score yet?, cost-per-keeper if scored, static fallback
        # position, name) -- scored tools sort before unscored ones,
        # cheapest-per-keeper first among those; unscored tools fall back
        # to DEFAULT_ORDER, then alphabetical as a last, stable tiebreak.
        return (scored is None, scored if scored is not None else 0.0, default_rank, tool)

    return sorted(candidates, key=rank)[0]


# --------------------------------------------------------------------------
# the render options catalogue -- what the Queue's picker may offer
# --------------------------------------------------------------------------
# WHY THIS IS A PROJECTION AND NEVER A TABLE. Every number below already
# lives in exactly one place: render_specs.RUNWAY_MODELS, fal.VIDEO_MODELS,
# higgsfield.VIDEO_MODELS, veo.MODELS -- each dated against the vendor's own
# page by the adapter that renders through it. A second copy here would be
# render_specs' own origin story one size up (the manual lane's ratio was a
# second literal with a drift test guarding it, and a drift test is a smoke
# alarm, not a fix): the day somebody edits one side, the card starts
# offering a model or a length the adapter refuses, and the person finds
# that out after the queue wait, having already been charged for nothing.
#
# THE TWO KINDS OF LEGAL VALUE, and why this is not simply a list. Runway
# generates 5s or 10s and NOTHING between -- render_specs.check_duration
# refuses 7 rather than rounding it, on purpose. fal and Higgsfield publish
# a min and a max and their build_body CLAMPS into it, so 7 is a real
# request there. Flattening both into "a list of durations" would either
# hide eighteen legal fal lengths or invent eight illegal Runway ones, so
# the KIND travels with the values and every reader -- the card, and
# check_render_choice below -- branches on it.
#
# "fixed" is the third kind, and it is an admission rather than a limit.
# Veo's legal durations and Higgsfield's resolutions are published nowhere
# this repo has verified. render_specs' docstring already settled what to do
# about that (HIGGSFIELD_LANE_MODELS is None for the same reason): offer the
# adapter's own default, say the list was never checked, and do not invent
# one -- a guessed list refuses values that are perfectly real and admits
# values that are not, and it lies in both directions at once.

RENDER_LABELS: dict[str, str] = {
    "runway": "Runway", "fal": "fal.ai",
    "higgsfield": "Higgsfield", "veo": "Veo",
}

# What the third control IS on each vendor. Runway takes a frame SIZE
# ("720:1280"); the other three take a resolution tier ("720p"). Same axis,
# two vocabularies, and the card has to say which one it is showing or the
# operator reads "720" as a promise about the frame it is not making.
FRAME_AXIS: dict[str, str] = {
    "runway": "ratio", "fal": "resolution",
    "higgsfield": "resolution", "veo": "resolution",
}

DEFAULT_PROVIDER = "runway"


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
    """One legal value and a stated reason there is only one. The note is
    not decoration: it is the difference between 'this vendor offers one
    option' and 'nobody here has verified what the options are', and the
    card prints it beside the disabled control."""
    return {"kind": "fixed", "values": [value], "default": value, "note": note}


def _runway_models() -> list[dict]:
    from . import render_specs
    out = []
    for name, spec in sorted((render_specs.RUNWAY_MODELS or {}).items()):
        legal_durations = [int(d) for d in spec.get("durations") or ()]
        if legal_durations:
            # a SET of two, not a span -- see check_duration in render_specs
            duration = _choices(legal_durations, runway.DEFAULT_DURATION)
        else:
            # Seedance's SDK type declares a bare `duration: int` and Runway
            # publishes no list of legal lengths, so there is nothing to
            # offer as THE options. Offering none would leave the card with
            # an empty control and a null default; offering an invented span
            # would claim a verification nobody did. So the card gets the two
            # lengths this pipeline actually renders, and the note says that
            # is what they are.
            duration = _choices(
                [runway.DEFAULT_DURATION, render_specs.LANE_DURATION],
                runway.DEFAULT_DURATION,
                note="Runway publishes no duration list for this model; "
                     "these are the two lengths this pipeline renders.")
        out.append({
            "id": name,
            "label": name,
            "available": True,
            "duration": duration,
            "frame": _choices(list(spec.get("ratios") or ()), runway.DEFAULT_RATIO),
            # Whether a render on this model can carry the shot's reference
            # photos, or whether they only reach it baked into the keyframe.
            "references": render_specs.takes_references("runway", name),
            "verified": spec.get("verified"),
        })
    return out


def _fal_models() -> list[dict]:
    out = []
    for name, spec in sorted(fal.VIDEO_MODELS.items()):
        low, high = spec["durations"]
        resolutions = [r for r in spec.get("resolutions") or ()]
        default_res = spec.get("default_resolution") or (resolutions[0] if resolutions else None)
        takes_resolution = "resolution" in (spec.get("params") or ())
        out.append({
            "id": name,
            "label": f"{name} ({spec['platform']})",
            "available": True,
            "duration": _span(low, high, fal.DEFAULT_DURATION),
            "frame": (_choices(resolutions, default_res) if takes_resolution
                      else _fixed(default_res,
                                  note=f"{name} takes no resolution field -- on a "
                                       f"keyframe the frame comes from the still")),
            "verified": spec.get("checked"),
        })
    return out


def _higgsfield_models() -> list[dict]:
    out = []
    for name, spec in sorted(higgsfield.VIDEO_MODELS.items()):
        low, high = spec["durations"]
        out.append({
            "id": name,
            # 404 model_not_found on this account when probed -- carried
            # through rather than filtered out here, so the card can say
            # why a model is missing instead of silently not having it
            "available": bool(spec.get("available")),
            "label": name,
            "duration": _span(low, high, higgsfield.DEFAULT_DURATION),
            "frame": _fixed(higgsfield.DEFAULT_RESOLUTION,
                            note="Higgsfield publishes no per-model resolution "
                                 "list this repo has verified -- the adapter's "
                                 "own default is the only checked value"),
            "verified": spec.get("verified"),
        })
    return out


def _veo_models() -> list[dict]:
    return [{
        "id": name,
        "label": name,
        "available": True,
        "duration": _fixed(veo.DEFAULT_DURATION,
                           note="Veo's legal durations are not recorded in this "
                                "repo -- generate_video's own default is the only "
                                "value verified against the installed SDK"),
        "frame": _fixed(veo.DEFAULT_RESOLUTION,
                        note="VEO_RESOLUTION is the adapter's default; no checked "
                             "list of the rest exists here"),
        "verified": None,
    } for name in veo.MODELS]


_MODEL_PROJECTIONS = {
    "runway": _runway_models, "fal": _fal_models,
    "higgsfield": _higgsfield_models, "veo": _veo_models,
}

# Per-clip cost, asked of the adapter that owns the rate card rather than
# recomputed here. Veo takes neither argument (one flat preview price);
# Higgsfield scales an estimate by duration; only fal's is close to an
# invoice, because only fal publishes a per-second rate per model.
ESTIMATORS = {
    # `frame` IS the ratio on this lane, and Seedance bills per resolution
    # tier -- so a 1080p reference render prices at 68 credits/s here
    # instead of silently quoting the 720p rate on the approve button.
    "runway": lambda model, duration, frame: runway.estimate_cost(
        1, model=model, duration=duration, ratio=frame),
    "fal": lambda model, duration, frame: fal.estimate_cost(
        1, model=model, duration=duration, resolution=frame),
    "higgsfield": lambda model, duration, frame: higgsfield.estimate_cost(
        1, model=model, duration=duration),
    "veo": lambda model, duration, frame: veo.estimate_cost(1),
}

# --------------------------------------------------------------------------
# price bands -- which tier a model belongs to, and how long a render of it
# may be QUOTED for (src/pricing.py reads these; nothing here prices)
# --------------------------------------------------------------------------
# One table beside the estimators, because the two answer the same
# question from both ends: what a render costs, and whether that is a cost
# this account's plan was sold. A 5s clip is ~$0.25 on gen4_turbo and ~$3
# on Veo; on a bundled-credit plan, six of the second kind is the month.
#
# max_seconds caps the QUOTE, never the render (the render's length comes
# from timeline.fit_seconds). None means the model's own legal maximum:
# every length legal today still prices, and tightening one is a one-line
# decision made here. WHICH TIER AN ACCOUNT IS ON IS NOT RECORDED ANYWHERE
# YET -- pricing takes it as an argument and enforces nothing when it is
# not given, so this table changes no behaviour until a plan exists.
# THREE TIERS SINCE 2026-09-18 (the plans in pricing.PLANS): standard is
# what a Starter plan renders, creator adds the Kling and Seedance family,
# premium adds Veo. An account with no plan has no tier and is not
# refused here -- with no credit it cannot hold, and a BYOK render is the
# provider's business (pricing.tier_for).
TIERS = ("standard", "creator", "premium")      # ascending: a tier may use itself and below


@dataclass(frozen=True)
class Band:
    tier: str
    max_seconds: Optional[int] = None


BANDS: dict[tuple[str, str], Band] = {
    ("runway", "gen4_turbo"): Band("standard"),
    ("runway", "gen4.5"): Band("standard"),
    ("runway", "seedance2_5"): Band("creator"),
    ("fal", "ltx2.3"): Band("standard"),
    ("fal", "wan3"): Band("standard"),
    ("fal", "kling3-turbo-pro"): Band("creator"),
    ("fal", "seedance2-fast"): Band("creator"),
    ("fal", "seedance2"): Band("creator"),
    ("higgsfield", "seedance-pro"): Band("creator"),
    ("higgsfield", "seedance-lite"): Band("creator"),
    ("higgsfield", "kling2.5"): Band("creator"),
    ("higgsfield", "kling2.1"): Band("creator"),
    ("higgsfield", "veo3.1-fast"): Band("premium", max_seconds=8),
    ("higgsfield", "veo3.1"): Band("premium", max_seconds=8),
    ("veo", "veo-3.1-generate-preview"): Band("premium", max_seconds=8),
    ("veo", "veo-3"): Band("premium", max_seconds=8),
    ("veo", "veo-3-fast"): Band("premium", max_seconds=8),
}


def band_for(provider: str, model: str) -> Band:
    """A model nobody banded is PREMIUM: a new entry in a vendor's spec
    table must not become quotable on every plan by being forgotten here
    (tests/test_pricing.py also fails on the omission)."""
    return BANDS.get((provider, model), Band("premium"))


# shot.PLATFORMS name -> (provider, the model that platform renders on).
# This is what lets a card default to the tool shootgen actually planned
# for instead of to whatever is alphabetically first.
def platform_default(platform: Optional[str]) -> Optional[tuple[str, str]]:
    """(provider, model) for a shot's planned tool, or None when nothing
    in the registry renders it. The four fal platforms resolve through
    fal.PLATFORM_MODELS -- the same binding orchestrator.generate_render
    holds, not a second opinion about which model is 'the' kling."""
    name = (platform or "").strip().lower()
    if not name:
        return None
    if name in fal.PLATFORM_MODELS:
        return ("fal", fal.PLATFORM_MODELS[name])
    direct = {"runway": runway.DEFAULT_MODEL,
              "veo": veo.DEFAULT_MODEL,
              "higgsfield": higgsfield.DEFAULT_MODEL}
    if name in direct:
        return (name, direct[name])
    return None


def default_model(provider: str) -> str:
    """What the card offers first for a provider: the adapter's own
    DEFAULT_MODEL when the catalogue actually knows it, else the first
    model it does. The defaults are env vars (RUNWAY_MODEL, FAL_MODEL,
    ...), so one can name something the spec table has never heard of --
    and offering that would mean every approve refused."""
    known = [m["id"] for m in models_for(provider)]
    fallback = getattr(VIDEO_PROVIDERS[provider], "DEFAULT_MODEL", None)
    if fallback in known:
        return fallback
    usable_first = [m["id"] for m in models_for(provider) if m["available"]]
    return (usable_first or known or [fallback])[0]


def _price_for(provider: str, spec: dict) -> dict:
    """The rate card a CARD can multiply, so moving a duration slider does
    not cost a round trip per keystroke.

    This is the one number in the catalogue that is not simply forwarded,
    and it is a deliberate, tested duplication rather than a happy one:
    {"kind": "per_second", "usd": x} means the card may show x * seconds,
    and tests/test_providers.py asserts that product equals the adapter's
    OWN estimate_cost for every model, every legal duration and every
    frame. The day a vendor's pricing stops being linear in seconds, that
    test fails and this function has to learn the new shape -- which is
    the entire point of writing it down as a shape instead of a number.

    The card's figure is a LABEL. check_render_choice computes the
    authoritative estimate server-side on the way in, and the approve
    response carries it back.
    """
    model = spec["id"]
    if provider == "veo":
        # one flat preview price, duration-independent
        return {"kind": "flat", "usd": veo.estimate_cost(1)}
    if provider == "runway":
        # Seedance bills per resolution tier, so ONE per-second number
        # cannot label it: a card multiplying the 720p rate would under-
        # quote a 1080p render by more than half. usd_by_frame is fal's
        # shape, reached for here for fal's reason -- and `usd` stays
        # beside it so the gen4 pair, whose rate really is one number,
        # keeps labelling exactly as before.
        frames = spec["frame"]["values"] or [runway.DEFAULT_RATIO]
        by_frame = {frame: runway.credits_per_second(model, frame) * runway.CREDIT_USD
                    for frame in frames}
        default = runway.credits_per_second(
            model, spec["frame"]["default"]) * runway.CREDIT_USD
        if len(set(by_frame.values())) > 1:
            return {"kind": "per_second", "usd": default, "usd_by_frame": by_frame}
        return {"kind": "per_second", "usd": default}
    if provider == "higgsfield":
        # an ESTIMATE scaled off a per-clip base at the default length --
        # higgsfield.estimate_cost's own arithmetic, not a second guess
        return {"kind": "per_second",
                "usd": higgsfield.COST_PER_CLIP_USD / higgsfield.DEFAULT_DURATION}
    if provider == "fal":
        # the only real rate card in the repo: published per second, per
        # model, per resolution, and dated in fal.VIDEO_MODELS
        return {"kind": "per_second",
                "usd_by_frame": {res: fal.price_per_second(model, res)
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
    clamping, for render_specs' reason: a value outside the set is
    evidence that the card and the model have come apart, and rounding it
    silently spends money on something nobody chose. (The adapters clamp
    internally -- that is their contract with the graph, which has no
    human to refuse to. This layer has one.)"""
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
    # a duration arrives from a JSON body as either 5 or "5"; a ratio
    # never does. Coerce only when the legal set is numeric, so "720p"
    # is never quietly turned into anything.
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
        raise ValueError(
            f"{model} is not reachable on this account "
            f"(probed {spec.get('verified') or 'and 404'}) -- pick another model")
    seconds = _check_axis(spec["duration"], duration,
                          what="duration", model=model)
    framed = _check_axis(spec["frame"], frame,
                         what=FRAME_AXIS.get(provider, "resolution"), model=model)
    return {"provider": provider, "model": model,
            "duration": seconds, "frame": framed,
            "estimate_usd": ESTIMATORS[provider](model, seconds, framed)}


def provider_state(provider: str, account_id: Optional[int] = None,
                   db_path=None) -> dict:
    """Whether approving on this renderer could even happen, and what it
    has already spent today. The daily count reads the generations log,
    which a database that has never rendered anything does not have yet --
    a queue that 500s because nothing has been billed on it is the wrong
    failure, so the count degrades to None and the gates are still
    reported (_runway_state's rule, now for four vendors)."""
    module = VIDEO_PROVIDERS[provider]
    try:
        today = module.generations_today(db_path, account_id=account_id)
    except Exception:
        today = None
    try:
        # BYOK reads account_keys, which a database nobody has stored a
        # key in yet may not have a table for. Same degrade as the count
        # above: report the gate as shut, never take the Queue down with
        # it -- a page that 500s because nothing is configured is the
        # wrong failure for "nothing is configured".
        available = bool(module.has_key(account_id))
    except Exception:
        available = False
    return {
        "label": RENDER_LABELS.get(provider, provider),
        "available": available,
        # A KEY IS THE WHOLE GATE ON THIS SURFACE (2026-09-09, Mike's
        # call). `spend_ok` used to be `module.spend_approved()` -- the
        # *_SPEND_OK environment variable -- and the card dimmed Approve
        # whenever it was unset, so the button that IS the approval
        # could not be pressed until somebody restarted the server with
        # a variable that then stayed set all session. The approval is
        # the click; the route passes it explicitly.
        "spend_ok": available,
        # The env override, reported because it is still what an
        # unattended run (orchestrator, autopilot, the CLI) needs and
        # the one place a person can see whether it is armed. It is NOT
        # a gate on anything a person clicks.
        "env_override": bool(module.spend_approved()),
        "spend_env": getattr(module, "SPEND_ENV", None),
        "cap": getattr(module, "DAILY_CAP", None),
        "today": today,
        "frame_axis": FRAME_AXIS.get(provider, "resolution"),
    }


def render_options(account_id: Optional[int] = None, db_path=None) -> dict:
    """Every renderer the Queue may offer, with its gates and its legal
    options. One call, because the card has to render the whole menu
    before the operator picks -- asking per provider would let two of
    them answer from different moments."""
    out = {}
    for name in VIDEO_PROVIDERS:
        try:
            models = models_for(name)
        except Exception:
            models = []
        out[name] = {
            **provider_state(name, account_id, db_path),
            "models": models,
            "default_model": default_model(name) if models else None,
        }
    return out


# --------------------------------------------------------------------------
# which renderer THIS account can actually use -- one answer for every door
# --------------------------------------------------------------------------
# 2026-09-11, Mike: "the render button doesn't work ... it said Runway key
# not set", then "make it whatever I can use". Every door that spends on a
# clip -- the Queue card's default, an empty approve body, the Director
# Generate node's own Run and its Run all -- used to start from a fixed
# vendor (the shot's planned tool, or Runway), so an account holding a
# Higgsfield key and no Runway key opened every one of them on a dead
# button. The plan still leads when the account can render it; when it
# cannot, the door falls to the cheapest thing the account CAN render
# instead of refusing. One function so the doors cannot disagree -- the
# same reason platform_default is one function.

def _keyed(provider: str, account_id: Optional[int]) -> bool:
    """Has this account a key for this vendor (its own BYOK secret or the
    installation's environment one)? Never raises: a vendor whose key
    lookup breaks is a vendor this account cannot use right now."""
    try:
        return bool(VIDEO_PROVIDERS[provider].has_key(account_id))
    except Exception:
        return False


def _default_cost(provider: str, spec: dict) -> float:
    """What one clip of this model costs at its own default length and
    frame -- the ranking key for the fallback. Unpriced sorts last."""
    try:
        usd = ESTIMATORS[provider](spec["id"], spec["duration"]["default"],
                                    spec["frame"]["default"])
        return float(usd) if usd is not None else float("inf")
    except Exception:
        return float("inf")


def renderer_for(account_id: Optional[int] = None,
                 provider: Optional[str] = None,
                 model: Optional[str] = None, *,
                 needs: str = "generate_for_shot") -> Optional[dict]:
    """{"provider", "model"} this account can render on, or None.

    `provider`/`model` are the preference -- the shot's plan, or what a
    caller asked for. It wins whenever the account holds that vendor's key
    and the model is reachable. Otherwise: the CHEAPEST reachable model
    (at its default length) on any vendor the account holds a key for.

    `needs` is the adapter entry point the door will call. Veo has no
    generate_from_prompt, so the Director's Generate node must never be
    handed it; the Queue calls generate_for_shot, which all four have.

    None means the account holds no key for any vendor that can do the
    job -- the one case where a door should refuse, and say so."""
    name = (provider or "").strip().lower()
    if name in VIDEO_PROVIDERS and hasattr(VIDEO_PROVIDERS[name], needs) \
            and _keyed(name, account_id):
        try:
            spec = model_options(name, model or default_model(name))
        except ValueError:
            spec = None
        if spec and spec["available"]:
            return {"provider": name, "model": spec["id"]}

    best = None
    for candidate in VIDEO_PROVIDERS:
        if not hasattr(VIDEO_PROVIDERS[candidate], needs):
            continue
        if not _keyed(candidate, account_id):
            continue
        try:
            specs = models_for(candidate)
        except Exception:
            continue
        for spec in specs:
            if not spec.get("available"):
                continue
            cost = _default_cost(candidate, spec)
            if best is None or cost < best[0]:
                best = (cost, candidate, spec["id"])
    return {"provider": best[1], "model": best[2]} if best else None


def render_default(tool: Optional[str],
                   account_id: Optional[int] = None) -> dict:
    """The Queue's default for a shot planned for `tool`: the plan when
    this account can render it, else the cheapest renderer it can, else
    the plan anyway (nothing is keyed, and the card then says which key
    is missing rather than naming a vendor nobody chose).

    Both the listing (`render_default` on each card) and an approve with
    an empty body resolve through here, so what the card offers first and
    what an empty approve spends on cannot come apart."""
    planned = platform_default(tool)
    want = planned or (DEFAULT_PROVIDER, default_model(DEFAULT_PROVIDER))
    usable_pick = renderer_for(account_id, want[0], want[1])
    if usable_pick:
        return usable_pick
    return {"provider": want[0], "model": want[1]}
