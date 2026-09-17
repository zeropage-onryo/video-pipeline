"""
The only code in the repo that turns a render intent into a price
(docs/tasks/task-pricing-and-quotes.md, steps 1-3 of 6, 2026-09-17).

Everything that SHOWS a price or, later, TAKES money asks here: the Queue
card, an approve with an empty body, the Director's Generate node. Before
this module the same number was computed in four places -- providers'
check_render_choice, check_timeline_choice, the Queue's JS (twice) and
the Director's chip, which priced every node at Runway's default whatever
renderer the account would actually spend on. Two implementations of a
price is how a person is shown one number and charged another.

TWO LAYERS, and the split is the BYOK rule:

  estimate()  what the PROVIDER will charge for this render. Always
              answers, because a customer rendering on their own key
              still wants to know what their own provider will bill.
  quote()     what WE will charge, in credits. None on BYOK: that render
              is already paid for at the provider, and a price on a page
              that never becomes a ledger entry is a lie with a number
              in it (ledger.is_billable is the one rule; this asks it).

What this module deliberately does NOT do:

- NO DB WRITES. A quote is a price, not a permission. The daily cap
  (generative.cap_error, counted from the generations table so a stuck
  loop hits a database wall) and the balance (ledger.hold, the only place
  that can check it without a race) stay where they are. Conflating them
  means a person near their cap sees no price instead of a price and a
  reason.
- NO SECOND RESOLVER. Which renderer an account can use is
  providers.render_default / renderer_for. An explicit provider is
  honoured EXACTLY and refused if it cannot render -- never swapped for a
  cheaper one, which would be spending on something nobody chose.
- NO SECOND CONTENT HASH. content_hash() below is timeline.source_hash,
  the staleness-on-read hash that already exists; nothing else may
  compute one.
- NO SIGNING YET. sign()/verify() are step 4, and they are driven
  interactively. Every field of Quote is already an int, a str or a
  tuple of them so that the day it is signed, nothing in it is a float
  that round-trips badly.

MARKUP is 1.0: credits are the provider's estimate in cents, rounded up,
which is what ledger.credits_for_usd has always charged. Raising it is
the first real pricing decision in the repo and it is Mike's (the spec
argues for 2.4). It lands in ONE commit with making the signed token
required, because a raised markup beside an unsigned path silently
undercharges.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from fractions import Fraction
from typing import Optional

from . import account_keys, ledger, providers, timeline

PRICING_VERSION = "2026-09-17-video-v1"

# One credit is one cent of CHARGE -- the ledger's existing unit.
CREDIT_CENTS = 1
# charge / provider cost. A STRING, read through Fraction, because a
# markup is a decimal and a float is not: 100000 * 1.1 is
# 110000.00000000001, and ceil() of that in cents is 12 credits for an
# 11-credit render. Move this constant, never the call sites.
MARKUP = "1.0"
# per render, per part: the least any billable render costs
CREDIT_FLOOR = 10

_MICROS = 1_000_000
_MICROS_PER_CENT = 10_000


class PricingRefused(ValueError):
    """This intent has no price, and `reason` says which kind of no.

    A ValueError on purpose: every door already turns a ValueError from
    check_render_choice into a 400 with the message, and a band refusal
    is the same event -- the card and the model have come apart."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class Estimate:
    """What the provider will charge. `frame` is the one field the spec's
    Quote does not list and the estimators cannot work without: Seedance
    and fal bill per resolution tier."""
    provider: str
    model: str
    seconds: int
    frame: str
    part: Optional[int]
    provider_usd_micros: int

    @property
    def usd(self) -> float:
        return self.provider_usd_micros / _MICROS


@dataclass(frozen=True)
class Quote:
    pricing_version: str
    account_id: Optional[int]
    shot_id: int
    part: Optional[int]
    provider: str
    model: str
    seconds: int
    frame: str
    provider_usd_micros: int
    credits: int
    content_hash: str
    line_items: tuple


# --------------------------------------------------------------------------
# money
# --------------------------------------------------------------------------

def usd_micros(usd) -> int:
    """A provider estimate (a float, from the adapter's own rate card) ->
    integer micro-dollars. Rounded to the NEAREST micro, via str(), for
    credits_for_usd's reason: this step exists to shed float noise, and
    the rounding that favours the house happens exactly once, in
    credits_for()."""
    if usd is None:
        raise PricingRefused("unpriced", "this renderer has no estimate to price")
    try:
        micros = (Decimal(str(usd)) * _MICROS).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        raise PricingRefused("unpriced", f"not a price: {usd!r}") from None
    if micros < 0:
        raise PricingRefused("unpriced", f"negative price: {usd!r}")
    return int(micros)


def credits_for(provider_usd_micros: int) -> int:
    """Micro-dollars of provider cost -> credits: marked up, rounded UP to
    the cent, never under the floor. Integer arithmetic throughout."""
    scaled = Fraction(int(provider_usd_micros)) * Fraction(str(MARKUP)) * CREDIT_CENTS
    cents = -((-scaled.numerator) // (scaled.denominator * _MICROS_PER_CENT))
    return max(int(cents), CREDIT_FLOOR)


# --------------------------------------------------------------------------
# the content hash -- one function, and it is timeline's
# --------------------------------------------------------------------------

def content_hash(shot: dict, part: Optional[int] = None) -> str:
    """What a price is ABOUT: the scene's prompt and its reference set.

    Computed LIVE from the shot through timeline.source_hash, never read
    off shot["timeline"]["source"]. The stored value is what the timeline
    was PLANNED from, and it is only refreshed when timeline.ensure next
    runs -- so between a prompt edit and the re-plan it still names the
    old prompt, and a quote compared against it would survive exactly the
    edit it exists to catch. When the timeline is current the two are the
    same string (timeline.is_current is this comparison).

    `part` is accepted and does not change the answer: a part's prompt
    and refs are derived from the scene's, so the scene's hash covers
    every part, and the part number rides beside it in the quote."""
    shot = shot or {}
    return timeline.source_hash(shot.get("prompt") or "", shot.get("refs") or [])


# --------------------------------------------------------------------------
# the estimate
# --------------------------------------------------------------------------

def _resolve(account_id: Optional[int], shot: dict,
             provider: Optional[str], model: Optional[str]) -> tuple[str, Optional[str]]:
    """(provider, model-or-None). An explicit provider is the caller's
    choice and is kept as-is; nothing named means the card's own default,
    through the same call the card made."""
    planned = providers.platform_default((shot or {}).get("tool"))
    if provider:
        name = provider.strip().lower()
        if model is None and planned and name == planned[0]:
            model = planned[1]
        return name, model
    default = providers.render_default((shot or {}).get("tool"), account_id)
    return default["provider"], model or default["model"]


def windows_to_render(shot: dict) -> Optional[list[dict]]:
    """[{"n", "seconds"}] for every timed shot an approve would render, or
    None when the scene renders whole. The card's own view of it
    (api._timeline_card): the planned parts still without a clip when the
    timeline is current, else the bare windows the prompt carries -- a
    stale or missing timeline is re-planned inside the render job, before
    the first clip, from those same windows."""
    shot = shot or {}
    if timeline.is_current(shot):
        return [{"n": p.get("n"), "seconds": p.get("seconds")}
                for p in timeline.pending_parts(shot)]
    windows = timeline.parse_windows(shot.get("prompt") or "")
    if not windows:
        return None
    return [{"n": i, "seconds": w["seconds"]} for i, w in enumerate(windows, start=1)]


def _part_window(shot: dict, part: int):
    if timeline.is_current(shot or {}):
        listed = shot["timeline"]["parts"]
    else:
        listed = windows_to_render(shot) or []
    for entry in listed:
        if entry.get("n") == part:
            return entry.get("seconds")
    raise PricingRefused("no_such_part", f"this scene has no shot {part}")


def _check_band(provider: str, model: str, seconds: int, tier: Optional[str]) -> None:
    band = providers.band_for(provider, model)
    if tier is not None and providers.TIERS.index(band.tier) > providers.TIERS.index(tier):
        # REFUSED WITH THE TIER NAMED, never quietly downgraded: a silent
        # downgrade is a cheaper render than the one that was picked, and
        # nobody told the person who picked it.
        raise PricingRefused(
            "tier", f"{model} is a {band.tier}-tier model and this account is on "
                    f"the {tier} tier -- pick a {tier}-tier model")
    if band.max_seconds is not None and seconds > band.max_seconds:
        raise PricingRefused(
            "band_seconds", f"{model} is priced up to {band.max_seconds}s a render, "
                            f"not {seconds}s")


def estimate(*, account_id: Optional[int], shot: dict, part: Optional[int] = None,
             provider: Optional[str] = None, model: Optional[str] = None,
             seconds=None, frame=None, tier: Optional[str] = None) -> Estimate:
    """One render, resolved, checked and priced at the provider's rate.

    `seconds` None derives it: a PART renders at its own window fitted UP
    to what the model can make (timeline.fit_seconds -- a 3s window is a
    5s Runway clip); a whole scene renders at the model's default length,
    which is what the Queue card opens on. A length or a frame outside
    the model's legal set is REFUSED, not clamped (check_render_choice's
    rule). Raises ValueError / PricingRefused."""
    if tier is not None and tier not in providers.TIERS:
        raise PricingRefused("tier", f"unknown tier {tier!r} -- one of {list(providers.TIERS)}")
    name, wanted = _resolve(account_id, shot, provider, model)
    if part is not None and seconds is None:
        window = _part_window(shot, part)
        base = providers.check_render_choice(name, wanted, None, frame)
        axis = providers.model_options(base["provider"], base["model"])["duration"]
        seconds = timeline.fit_seconds(axis, window)
    choice = providers.check_render_choice(name, wanted, seconds, frame)
    _check_band(choice["provider"], choice["model"], int(choice["duration"]), tier)
    return Estimate(provider=choice["provider"], model=choice["model"],
                    seconds=int(choice["duration"]), frame=str(choice["frame"]),
                    part=part, provider_usd_micros=usd_micros(choice["estimate_usd"]))


def estimate_scene(*, account_id: Optional[int], shot: dict,
                   provider: Optional[str] = None, model: Optional[str] = None,
                   seconds=None, frame=None, tier: Optional[str] = None) -> list[Estimate]:
    """What approving this scene would render, in order: one estimate per
    timed shot STILL WITHOUT A CLIP (windows_to_render -- approving again
    resumes, so it prices only what is left), or the single
    whole-scene render when the scene has no timeline. `seconds` applies
    to a whole-scene render only; a part's length is its window's."""
    todo = windows_to_render(shot)
    if todo is not None:
        return [estimate(account_id=account_id, shot=shot, part=w["n"],
                         provider=provider, model=model, frame=frame, tier=tier)
                for w in todo]
    return [estimate(account_id=account_id, shot=shot, provider=provider,
                     model=model, seconds=seconds, frame=frame, tier=tier)]


# --------------------------------------------------------------------------
# the quote
# --------------------------------------------------------------------------

def billable(account_id: Optional[int], provider: str) -> bool:
    """Would a render on this vendor be debited? False on the account's
    own stored key. The rule itself is ledger.is_billable's; an
    unreadable credential reads as billable there, on purpose."""
    return ledger.is_billable(account_keys.key_source(account_id, provider))


def quote(*, account_id: Optional[int], shot: dict, shot_id: int,
          part: Optional[int] = None, provider: Optional[str] = None,
          model: Optional[str] = None, seconds=None, frame=None,
          tier: Optional[str] = None) -> Optional[Quote]:
    """The price of one render in credits, or None when there is nothing
    to charge (BYOK). `shot_id` is the concept's id: a scene is one row
    and its shot lives inside it, so that is the id a render is filed
    under everywhere else. Raises ValueError / PricingRefused."""
    priced = estimate(account_id=account_id, shot=shot, part=part, provider=provider,
                      model=model, seconds=seconds, frame=frame, tier=tier)
    # after the resolve, not before it: whose key it is can only be asked
    # of a vendor, and with no provider named there is not one yet
    if not billable(account_id, priced.provider):
        return None
    credits = credits_for(priced.provider_usd_micros)
    label = f"{priced.model} · {priced.seconds}s" + (
        f" · shot {part}" if part is not None else "")
    return Quote(pricing_version=PRICING_VERSION, account_id=account_id,
                 shot_id=int(shot_id), part=part, provider=priced.provider,
                 model=priced.model, seconds=priced.seconds, frame=priced.frame,
                 provider_usd_micros=priced.provider_usd_micros, credits=credits,
                 content_hash=content_hash(shot, part),
                 line_items=((label, credits, 1, "render"),))


# --------------------------------------------------------------------------
# what a card shows
# --------------------------------------------------------------------------

def display(*, account_id: Optional[int], shot: dict, shot_id: int,
            provider: Optional[str] = None, model: Optional[str] = None,
            seconds=None, frame=None, tier: Optional[str] = None) -> dict:
    """The priced plan for one approve, as JSON a card can print without
    doing arithmetic: every render it would make, its length, the
    provider's estimate, and the credits it would cost (None on BYOK).

    `estimate_usd` stays the PROVIDER's estimate -- the label the Queue
    has always shown -- so that while MARKUP is 1.0 no number on any
    screen moves. Raises ValueError / PricingRefused."""
    parts = estimate_scene(account_id=account_id, shot=shot, provider=provider,
                           model=model, seconds=seconds, frame=frame, tier=tier)
    if not parts:
        raise PricingRefused("nothing_to_render", "every shot of this scene has a clip")
    head = parts[0]
    charged = billable(account_id, head.provider)
    renders = [{"part": p.part, "seconds": p.seconds,
                "estimate_usd": round(p.usd, 4),
                "credits": credits_for(p.provider_usd_micros) if charged else None}
               for p in parts]
    micros = sum(p.provider_usd_micros for p in parts)
    return {"pricing_version": PRICING_VERSION,
            "shot_id": int(shot_id),
            "provider": head.provider, "model": head.model, "frame": head.frame,
            "timed": head.part is not None,
            "durations": [p.seconds for p in parts],
            "estimate_usd": round(micros / _MICROS, 4),
            "byok": not charged,
            "credits": sum(r["credits"] for r in renders) if charged else None,
            "content_hash": content_hash(shot),
            "renders": renders}


__all__ = ["PRICING_VERSION", "CREDIT_CENTS", "MARKUP", "CREDIT_FLOOR",
           "PricingRefused", "Estimate", "Quote",
           "usd_micros", "credits_for", "content_hash",
           "windows_to_render", "estimate", "estimate_scene", "billable", "quote", "display"]
