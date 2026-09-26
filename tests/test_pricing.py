"""src/pricing.py -- the one place a render intent becomes a price.

Each test here was checked the way the ledger's were: revert the line it
guards, watch it go red, put the line back. The comment above a test
names the line.
"""

import pytest

from src import accounts, db, fal, ledger, pricing, providers, timeline

RENDER_KEYS = ("FAL_KEY", "FAL_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY")


@pytest.fixture
def fal_keyed(monkeypatch):
    """The installation holds its fal key, whatever the machine's own .env
    says -- the only renderer since 2026-09-26."""
    for name in RENDER_KEYS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("FAL_KEY", "OPERATOR-FAL")


def scene(prompt="A man laces his boots in a cold garage.", refs=("/refs/a.jpg",), **extra):
    return {"n": 1, "tool": "LTX", "prompt": prompt, "refs": list(refs), **extra}


TIMED = ("BEATS (0-3s) he pulls the first lace tight. (3-7s) the bike's tank, rain on it. "
         "(7-10s) he stands and the light catches the visor.")


def planned(prompt=TIMED, done=()):
    shot = scene(prompt)
    windows = timeline.parse_windows(prompt)
    shot["timeline"] = {
        "source": timeline.source_hash(shot["prompt"], shot["refs"]),
        "parts": [{"n": i, "seconds": w["seconds"], "text": w["text"],
                   "media_url": "https://x/clip.mp4" if i in done else None}
                  for i, w in enumerate(windows, start=1)]}
    return shot


# --- money -----------------------------------------------------------------

def test_a_quote_is_deterministic(fal_keyed):
    ask = dict(account_id=None, shot=scene(), shot_id=361, provider="fal",
               model="ltx2.3", seconds=6)
    assert pricing.quote(**ask) == pricing.quote(**ask)
    assert hash(pricing.quote(**ask)) == hash(pricing.quote(**ask))


# guards: the max(..., CREDIT_FLOOR) in credits_for
def test_the_floor_binds_on_a_sub_cent_render():
    assert pricing.credits_for(4_000) == pricing.CREDIT_FLOOR == 10
    assert pricing.credits_for(0) == 10


# guards: the ceiling division in credits_for (floor division reads 25 / 25)
def test_rounding_is_up_at_every_boundary(monkeypatch):
    monkeypatch.setattr(pricing, "CREDIT_FLOOR", 0)
    monkeypatch.setattr(pricing, "MARKUP", "1.0")     # the boundaries, in plain cents
    assert pricing.credits_for(250_000) == 25
    assert pricing.credits_for(250_001) == 26
    assert pricing.credits_for(259_999) == 26
    assert pricing.credits_for(1) == 1

    assert pricing.usd_micros(0.29) == 290_000


# guards: MARKUP = "2.4" itself -- $1.00 of provider cost is 240 credits
def test_the_shipped_markup_is_two_point_four():
    assert pricing.MARKUP == "2.4"
    assert pricing.credits_for(1_000_000) == 240
    assert pricing.credits_for(360_000) == 87        # ltx2.3, 6s at 1080p
    assert pricing.credits_for(700_000) == 168       # kling3-turbo-pro, 5s
    assert pricing.credits_for(10_000) == pricing.CREDIT_FLOOR   # 2.4 credits -> the floor


def test_at_cost_it_charges_what_the_ledger_always_did(fal_keyed, monkeypatch):
    """AT 1.0x a quote moves no number: above the floor its credits are
    ledger.credits_for_usd of the provider's own estimate, for every
    model in the catalogue at its default length and frame. Pins the two
    together so hold_for_render (step 6) has one arithmetic, not two."""
    monkeypatch.setattr(pricing, "MARKUP", "1.0")
def test_the_quote_and_the_hold_share_one_conversion(fal_keyed):
    """MARKUP is 2.4 since 2026-09-18, and the number the card shows must
    be the number the ledger holds: for every model in the catalogue at
    its default length and frame, a quote's credits are
    ledger.charge_credits of the provider's own estimate -- the function
    hold_for_render and Charge.settle convert with -- and are 2.4x the
    at-cost peg above the floor."""
    assert pricing.MARKUP == "2.4"
    seen = 0
    for provider in providers.VIDEO_PROVIDERS:
        for spec in providers.models_for(provider):
            if not spec["available"]:
                continue
            priced = pricing.estimate(account_id=None, shot=scene(), provider=provider,
                                      model=spec["id"])
            choice = providers.check_render_choice(provider, spec["id"])
            assert priced.usd == pytest.approx(choice["estimate_usd"])
            quoted = pricing.credits_for(priced.provider_usd_micros)
            assert quoted == ledger.charge_credits(choice["estimate_usd"])
            at_cost = ledger.credits_for_usd(choice["estimate_usd"])
            assert quoted >= max(at_cost, pricing.CREDIT_FLOOR)
            if at_cost * 2.4 > pricing.CREDIT_FLOOR:
                assert quoted == pytest.approx(at_cost * 2.4, abs=1)
            seen += 1
    assert seen >= 4


# guards: every catalogue price through Fraction at the shipped markup --
# exact, so the ceiling never fires on float dust
def test_the_shipped_markup_is_exact_on_every_catalogue_price(fal_keyed):
    from fractions import Fraction
    from math import ceil
    seen = 0
    for provider in providers.VIDEO_PROVIDERS:
        for spec in providers.models_for(provider):
            if not spec["available"]:
                continue
            priced = pricing.estimate(account_id=None, shot=scene(), provider=provider,
                                      model=spec["id"])
            exact = ceil(Fraction(priced.provider_usd_micros, 10_000) * Fraction(pricing.MARKUP))
            assert pricing.credits_for(priced.provider_usd_micros) == max(exact, pricing.CREDIT_FLOOR)
            seen += 1
    assert seen >= 4


# --- seconds ---------------------------------------------------------------

def test_a_whole_scene_prices_the_models_default_length(fal_keyed):
    priced = pricing.estimate(account_id=None, shot=scene())
    spec = providers.model_options("fal", priced.model)
    assert (priced.provider, priced.seconds) == ("fal", spec["duration"]["default"])
    assert priced.part is None


# guards: fit_seconds in estimate() -- a 3s window is a 6s LTX render
def test_a_part_prices_its_window_fitted_up(fal_keyed):
    shot = planned("BEATS (0-7s) he laces both boots, slowly. (7-10s) the visor drops.")
    lengths = [pricing.estimate(account_id=None, shot=shot, part=n, provider="fal",
                                model="ltx2.3").seconds for n in (1, 2)]
    assert lengths == [8, 6]                # 7s -> 8, 3s -> 6: up, never down
    with pytest.raises(pricing.PricingRefused) as refused:
        pricing.estimate(account_id=None, shot=shot, part=9, provider="fal")
    assert refused.value.reason == "no_such_part"


def test_an_illegal_length_is_refused_not_clamped(fal_keyed):
    with pytest.raises(ValueError, match="7"):
        pricing.estimate(account_id=None, shot=scene(), provider="fal",
                         model="ltx2.3", seconds=7)


# guards: the `todo` filter in windows_to_render -- approving again
# resumes, so a part that already has its clip is not priced twice
def test_a_scene_prices_only_the_shots_still_without_a_clip(fal_keyed):
    shot = planned(done=(1,))
    assert [w["n"] for w in pricing.windows_to_render(shot)] == [2, 3]
    shown = pricing.display(account_id=None, shot=shot, shot_id=7, provider="fal",
                            model="ltx2.3")
    assert shown["timed"] and shown["durations"] == [6, 6]
    one = pricing.estimate(account_id=None, shot=shot, part=2, provider="fal",
                           model="ltx2.3")
    assert shown["estimate_usd"] == pytest.approx(2 * one.usd)
    assert shown["credits"] == 2 * pricing.credits_for(one.provider_usd_micros)


def test_an_unplanned_timed_scene_prices_the_windows_its_prompt_carries(fal_keyed):
    shot = scene(TIMED)                     # no timeline yet: planned inside the job
    assert [w["seconds"] for w in pricing.windows_to_render(shot)] == [3, 4, 3]
    assert pricing.windows_to_render(scene()) is None
    assert pricing.display(account_id=None, shot=shot, shot_id=7)["durations"] == [6, 6, 6]


# --- the renderer ----------------------------------------------------------

# guards: _resolve keeping an explicit pick. A named model is priced as
# named, never swapped for a cheaper one.
def test_a_named_model_is_never_swapped_for_a_cheaper_one(fal_keyed):
    priced = pricing.estimate(account_id=None, shot=scene(), provider="fal",
                              model="seedance2")
    assert (priced.provider, priced.model) == ("fal", "seedance2")


def test_a_retired_renderer_is_refused_not_priced(fal_keyed):
    with pytest.raises(ValueError, match="unknown renderer"):
        pricing.estimate(account_id=None, shot=scene(), provider="runway")


def test_nothing_named_prices_what_the_card_opens_on(fal_keyed):
    shot = scene(tool="KLING")
    default = providers.render_default("KLING", None)
    priced = pricing.estimate(account_id=None, shot=shot)
    assert (priced.provider, priced.model) == (default["provider"], default["model"])
    assert (priced.provider, priced.model) == ("fal", fal.PLATFORM_MODELS["kling"])


# --- bands -----------------------------------------------------------------

def test_every_model_in_the_catalogue_is_banded():
    for provider in providers.VIDEO_PROVIDERS:
        for spec in providers.models_for(provider):
            assert (provider, spec["id"]) in providers.BANDS, (provider, spec["id"])
    for band in providers.BANDS.values():
        assert band.tier in providers.TIERS


# guards: the tier comparison in _check_band. Asserts the MESSAGE: a
# silent downgrade passing for a refusal is the bug.
def test_a_premium_model_on_a_standard_account_refuses_and_names_the_tier(fal_keyed):
    premium = next(key for key, band in providers.BANDS.items() if band.tier == "premium"
                   and providers.model_options(*key)["available"])
    with pytest.raises(pricing.PricingRefused) as refused:
        pricing.estimate(account_id=None, shot=scene(), provider=premium[0],
                         model=premium[1], tier="standard")
    assert refused.value.reason == "tier"
    assert "premium-tier" in str(refused.value) and "standard tier" in str(refused.value)
    assert premium[1] in str(refused.value)
    # the same ask with the tier to match, or with no tier known, prices
    for tier in ("premium", None):
        assert pricing.estimate(account_id=None, shot=scene(), provider=premium[0],
                                model=premium[1], tier=tier).provider == premium[0]


# guards: the max_seconds comparison in _check_band
def test_a_band_caps_the_quote(fal_keyed, monkeypatch):
    monkeypatch.setitem(providers.BANDS, ("fal", "ltx2.3"),
                        providers.Band(tier="standard", max_seconds=6))
    assert pricing.estimate(account_id=None, shot=scene(), provider="fal",
                            model="ltx2.3", seconds=6).seconds == 6
    with pytest.raises(pricing.PricingRefused) as refused:
        pricing.estimate(account_id=None, shot=scene(), provider="fal",
                         model="ltx2.3", seconds=10)
    assert refused.value.reason == "band_seconds"


# --- the content hash ------------------------------------------------------

def test_the_content_hash_is_timelines_own():
    shot = planned()
    assert pricing.content_hash(shot) == shot["timeline"]["source"]
    assert pricing.content_hash(shot, 2) == pricing.content_hash(shot)


# guards: content_hash reading the LIVE prompt. Read off
# shot["timeline"]["source"] it survives this edit, which is the one edit
# a quote exists to catch: the stored source only moves at the next re-plan.
def test_editing_the_prompt_changes_the_hash_before_any_replan():
    shot = planned()
    before = pricing.content_hash(shot)
    shot["prompt"] = shot["prompt"].replace("boots", "gloves") + " He looks up."
    assert not timeline.is_current(shot)
    assert pricing.content_hash(shot) != before
    shot["refs"].append("/refs/b.jpg")
    assert pricing.content_hash(shot) != before


# --- every account is charged (BYOK removed 2026-09-26) ---------------------

@pytest.fixture
def two_accounts(pg, monkeypatch, fal_keyed):
    monkeypatch.setenv("DATABASE_URL", pg)
    accounts.seed("mike@example.com", dsn=pg)
    with db.connect(pg) as conn:
        ids = [r["id"] for r in conn.execute("SELECT id FROM accounts ORDER BY id").fetchall()]
    assert len(ids) >= 2
    return ids


# guards: billable() and display(). There is no render "already paid for at
# the provider" any more, so every account gets a price and a charge.
def test_every_account_is_quoted_and_the_display_carries_no_byok(two_accounts):
    ask = dict(shot=scene(), shot_id=361, provider="fal", model="ltx2.3", seconds=6)
    for account_id in two_accounts:
        charged = pricing.quote(account_id=account_id, **ask)
        assert charged is not None and charged.credits >= pricing.CREDIT_FLOOR
        assert charged.account_id == account_id
        shown = pricing.display(account_id=account_id, **ask)
        assert "byok" not in shown
        assert shown["credits"] == charged.credits
    assert pricing.billable(two_accounts[0], "fal") is True


# guards: resolution as a pricing input (step 13). Seedance 2.0 is
# $0.3034/s at 720p and $0.682/s at 1080p on fal; a 10s 1080p clip must not
# quote as 720p, and 1080p Seedance is the premium band.
def test_the_same_model_quotes_differently_at_720p_and_1080p(fal_keyed):
    ask = dict(account_id=None, shot=scene(), shot_id=361, provider="fal",
               model="seedance2", seconds=10)
    at_720 = pricing.quote(frame="720p", **ask)
    at_1080 = pricing.quote(frame="1080p", **ask)
    assert (at_720.frame, at_1080.frame) == ("720p", "1080p")
    assert at_720.provider_usd_micros == 3_034_000
    assert at_1080.provider_usd_micros == 6_820_000
    assert at_720.credits == 729                    # ceil(303.4 * 2.4)
    assert at_1080.credits == 1637                  # ceil(682 * 2.4)
    assert providers.band_for("fal", "seedance2", "720p").tier == "creator"
    assert providers.band_for("fal", "seedance2", "1080p").tier == "premium"
    with pytest.raises(pricing.PricingRefused) as refused:
        pricing.quote(frame="1080p", tier="creator", **ask)
    assert refused.value.reason == "tier"
    # 720p is the default resolution where a model offers it
    assert pricing.quote(**ask).frame == "720p"


def test_a_quote_carries_only_ints_and_strings(fal_keyed):
    """Step 4 signs this. A float in a signed body is a signature that
    breaks on another Python."""
    q = pricing.quote(account_id=None, shot=planned(), shot_id=361, part=2,
                      provider="fal", model="ltx2.3")
    flat = [q.pricing_version, q.shot_id, q.part, q.provider, q.model, q.seconds, q.frame,
            q.provider_usd_micros, q.credits, q.content_hash, *q.line_items[0]]
    assert all(isinstance(v, (int, str)) and not isinstance(v, bool) for v in flat)
    assert q.line_items[0][1] == q.credits


def test_account_id_is_keyword_only_with_no_default():
    with pytest.raises(TypeError):
        pricing.quote(shot=scene(), shot_id=1)
    with pytest.raises(TypeError):
        pricing.estimate(None, scene())
