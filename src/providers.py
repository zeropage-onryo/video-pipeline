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

kling, seedance, ltx and wan already have prompt-compilation support in
shot.PLATFORMS (the vocabulary a Shot renders into) but no execution
adapter -- they are not registered here until one exists. Adding one is
"write the module to this shape, add one line to VIDEO_PROVIDERS", not
"invent a new interface".

Not wired into the render path yet. orchestrator.py and scene_chain.py
still name a tool explicitly (from a shot's Platform or a config default);
choose_provider() is the piece a caller can start using in place of that,
not a change to what they do today.
"""
from __future__ import annotations

from types import ModuleType
from typing import Optional

from . import generative, higgsfield, runway, veo

# The contract: every callable a router or a future BYOK/cap check needs.
# estimate_cost is checked with arity 1 in mind (n) -- runway and
# higgsfield accept extra keyword-only params with defaults, veo takes
# only n, so calling provider.estimate_cost(n) works uniformly across all
# three; a caller that wants a specific model/duration still calls the
# module directly.
REQUIRED = (
    "generate_video",
    "generate_candidates",
    "estimate_cost",
    "spend_approved",
    "has_key",
    "generations_today",
)

VIDEO_PROVIDERS: dict[str, ModuleType] = {
    "runway": runway,
    "veo": veo,
    "higgsfield": higgsfield,
}

# Cheapest-first static fallback for a provider choose_provider() has no
# history for yet. Real per-clip figures (2026-08/09 dev-portal pricing,
# see each module's own COST_PER_CLIP_USD / CREDITS_PER_SECOND):
# runway ~$0.25 (gen4_turbo, 5s), higgsfield ~$0.40+ (duration-scaled),
# veo $3.20 flat. Not used once an account has real kept/rejected data --
# tool_scoreboard's cost_per_keeper replaces guessed sticker price with
# what this account actually paid per usable clip.
DEFAULT_ORDER: tuple[str, ...] = ("runway", "higgsfield", "veo")


def conforms(module: ModuleType) -> list[str]:
    """Which REQUIRED names this module is missing (empty = matches the
    contract). Run this against a new adapter before adding it to
    VIDEO_PROVIDERS, or against the registry itself as a standing check --
    see tests/test_providers.py."""
    return [name for name in REQUIRED if not callable(getattr(module, name, None))]


def usable(account_id: Optional[int] = None, *,
           tools: Optional[list[str]] = None) -> list[str]:
    """Tool names with a resolvable key (this account's own, per BYOK, or
    the environment fallback) AND spend approved for this run. Does NOT
    check the daily cap -- that's a per-attempt decision each provider's
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
