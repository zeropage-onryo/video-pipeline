"""src/pricing.py -- the one place a render intent becomes a price.

Each test here was checked the way the ledger's were: revert the line it
guards, watch it go red, put the line back. The comment above a test
names the line.
"""

import pytest
from cryptography.fernet import Fernet

from src import account_keys, accounts, db, ledger, pricing, providers, timeline

RENDER_KEYS = ("RUNWAYML_API_SECRET", "FAL_KEY", "HF_API_KEY", "HF_API_SECRET",
               "HIGGSFIELD_API_KEY_ID", "HIGGSFIELD_API_KEY_SECRET",
               "GEMINI_API_KEY", "GOOGLE_API_KEY")


@pytest.fixture
def runway_only(monkeypatch):
    """The installation holds a Runway key and nothing else, whatever the
    machine's own .env says."""
    for name in RENDER_KEYS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("RUNWAYML_API_SECRET", "OPERATOR-RUNWAY")


def scene(prompt="A man laces his boots in a cold garage.", refs=("/refs/a.jpg",), **extra):
    return {"n": 1, "tool": "RUNWAY", "prompt": prompt, "refs": list(refs), **extra}


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

def test_a_quote_is_deterministic(runway_only):
    ask = dict(account_id=None, shot=scene(), shot_id=361, provider="runway",
               model="gen4_turbo", seconds=5)
    assert pricing.quote(**ask) == pricing.quote(**ask)
    assert hash(pricing.quote(**ask)) == hash(pricing.quote(**ask))


# guards: the max(..., CREDIT_FLOOR) in credits_for
def test_the_floor_binds_on_a_sub_cent_render():
    assert pricing.credits_for(4_000) == pricing.CREDIT_FLOOR == 10
    assert pricing.credits_for(0) == 10


# guards: the ceiling division in credits_for (floor division reads 25 / 25)
def test_rounding_is_up_at_every_boundary(monkeypatch):
    monkeypatch.setattr(pricing, "CREDIT_FLOOR", 0)
    assert pricing.credits_for(250_000) == 25
    assert pricing.credits_for(250_001) == 26
    assert pricing.credits_for(259_999) == 26
    assert pricing.credits_for(1) == 1


# guards: MARKUP being read at all, and being read EXACTLY. As a float,
# 100000 * 1.1 == 110000.00000000001 and the ceiling is 12.
def test_markup_is_honoured_and_is_not_a_float(monkeypatch):
    monkeypatch.setattr(pricing, "MARKUP", "1.0")
    at_cost = pricing.credits_for(350_000)
    monkeypatch.setattr(pricing, "MARKUP", "2.4")
    marked_up = pricing.credits_for(350_000)
    assert (at_cost, marked_up) == (35, 84)
    monkeypatch.setattr(pricing, "MARKUP", "1.1")
    assert pricing.credits_for(100_000) == 11
    monkeypatch.setattr(pricing, "MARKUP", 1.1)      # somebody will type it this way
    assert pricing.credits_for(100_000) == 11


def test_float_noise_from_an_estimator_does_not_buy_a_credit():
    assert pricing.usd_micros(0.1 + 0.2) == 300_000
    assert pricing.usd_micros(0.29) == 290_000


def test_at_cost_it_charges_what_the_ledger_always_did(runway_only):
    """MARKUP 1.0 must move no number: above the floor, a quote's credits
    are ledger.credits_for_usd of the provider's own estimate, for every
    model in the catalogue at its default length and frame."""
    assert pricing.MARKUP == "1.0"
    seen = 0
    for provider in providers.VIDEO_PROVIDERS:
        for spec in providers.models_for(provider):
            if not spec["available"]:
                continue
            priced = pricing.estimate(account_id=None, shot=scene(), provider=provider,
                                      model=spec["id"])
            choice = providers.check_render_choice(provider, spec["id"])
            assert priced.usd == pytest.approx(choice["estimate_usd"])
            expected = max(ledger.credits_for_usd(choice["estimate_usd"]), pricing.CREDIT_FLOOR)
            assert pricing.credits_for(priced.provider_usd_micros) == expected
            seen += 1
    assert seen >= 4


# --- seconds ---------------------------------------------------------------

def test_a_whole_scene_prices_the_models_default_length(runway_only):
    priced = pricing.estimate(account_id=None, shot=scene())
    spec = providers.model_options("runway", priced.model)
    assert (priced.provider, priced.seconds) == ("runway", spec["duration"]["default"])
    assert priced.part is None


# guards: fit_seconds in estimate() -- a 3s window is a 5s Runway render
def test_a_part_prices_its_window_fitted_up(runway_only):
    shot = planned("BEATS (0-7s) he laces both boots, slowly. (7-10s) the visor drops.")
    lengths = [pricing.estimate(account_id=None, shot=shot, part=n, provider="runway",
                                model="gen4_turbo").seconds for n in (1, 2)]
    assert lengths == [10, 5]               # 7s -> 10, 3s -> 5: up, never down
    with pytest.raises(pricing.PricingRefused) as refused:
        pricing.estimate(account_id=None, shot=shot, part=9, provider="runway")
    assert refused.value.reason == "no_such_part"


def test_an_illegal_length_is_refused_not_clamped(runway_only):
    with pytest.raises(ValueError, match="7"):
        pricing.estimate(account_id=None, shot=scene(), provider="runway",
                         model="gen4_turbo", seconds=7)


# guards: the `todo` filter in windows_to_render -- approving again
# resumes, so a part that already has its clip is not priced twice
def test_a_scene_prices_only_the_shots_still_without_a_clip(runway_only):
    shot = planned(done=(1,))
    assert [w["n"] for w in pricing.windows_to_render(shot)] == [2, 3]
    shown = pricing.display(account_id=None, shot=shot, shot_id=7, provider="runway",
                            model="gen4_turbo")
    assert shown["timed"] and shown["durations"] == [5, 5]
    one = pricing.estimate(account_id=None, shot=shot, part=2, provider="runway",
                           model="gen4_turbo")
    assert shown["estimate_usd"] == pytest.approx(2 * one.usd)
    assert shown["credits"] == 2 * pricing.credits_for(one.provider_usd_micros)


def test_an_unplanned_timed_scene_prices_the_windows_its_prompt_carries(runway_only):
    shot = scene(TIMED)                     # no timeline yet: planned inside the job
    assert [w["seconds"] for w in pricing.windows_to_render(shot)] == [3, 4, 3]
    assert pricing.windows_to_render(scene()) is None
    assert pricing.display(account_id=None, shot=shot, shot_id=7)["durations"] == [5, 5, 5]


# --- the renderer ----------------------------------------------------------

# guards: _resolve keeping an explicit provider. Through renderer_for's
# preference-with-fallback this would come back priced on Runway.
def test_a_named_renderer_is_never_swapped_for_a_cheaper_one(runway_only):
    priced = pricing.estimate(account_id=None, shot=scene(), provider="fal")
    assert priced.provider == "fal"


def test_nothing_named_prices_what_the_card_opens_on(runway_only):
    shot = scene(tool="KLING")              # planned for a vendor with no key here
    default = providers.render_default("KLING", None)
    priced = pricing.estimate(account_id=None, shot=shot)
    assert (priced.provider, priced.model) == (default["provider"], default["model"])
    assert priced.provider == "runway"


# --- bands -----------------------------------------------------------------

def test_every_model_in_the_catalogue_is_banded():
    for provider in providers.VIDEO_PROVIDERS:
        for spec in providers.models_for(provider):
            assert (provider, spec["id"]) in providers.BANDS, (provider, spec["id"])
    for band in providers.BANDS.values():
        assert band.tier in providers.TIERS


# guards: the tier comparison in _check_band. Asserts the MESSAGE: a
# silent downgrade passing for a refusal is the bug.
def test_a_premium_model_on_a_standard_account_refuses_and_names_the_tier(runway_only):
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
def test_a_band_caps_the_quote(runway_only, monkeypatch):
    monkeypatch.setitem(providers.BANDS, ("runway", "gen4_turbo"),
                        providers.Band(tier="standard", max_seconds=5))
    assert pricing.estimate(account_id=None, shot=scene(), provider="runway",
                            model="gen4_turbo", seconds=5).seconds == 5
    with pytest.raises(pricing.PricingRefused) as refused:
        pricing.estimate(account_id=None, shot=scene(), provider="runway",
                         model="gen4_turbo", seconds=10)
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


# --- BYOK ------------------------------------------------------------------

@pytest.fixture
def two_accounts(pg, monkeypatch, runway_only):
    """Two real accounts on one installation key: `byok` stored its own
    Runway secret, `plain` did not."""
    monkeypatch.setenv("DATABASE_URL", pg)
    monkeypatch.setenv("ACCOUNT_KEYS_SECRET", Fernet.generate_key().decode())
    accounts.seed("mike@example.com", dsn=pg)
    with db.connect(pg) as conn:
        ids = [r["id"] for r in conn.execute("SELECT id FROM accounts ORDER BY id").fetchall()]
    assert len(ids) >= 2
    account_keys.set_key(ids[0], "runway", "TENANT-RUNWAY", dsn=pg)
    return {"byok": ids[0], "plain": ids[1]}


# guards: the `if not billable(...)` in quote(). THE ONE THAT STOPS A
# DOUBLE CHARGE: that account's provider already billed it.
def test_byok_takes_no_quote(two_accounts):
    ask = dict(shot=scene(), shot_id=361, provider="runway", model="gen4_turbo", seconds=5)
    assert pricing.quote(account_id=two_accounts["byok"], **ask) is None
    charged = pricing.quote(account_id=two_accounts["plain"], **ask)
    assert charged is not None and charged.credits >= pricing.CREDIT_FLOOR
    assert charged.account_id == two_accounts["plain"]
    # ... and still learns what its own provider will bill
    shown = pricing.display(account_id=two_accounts["byok"], **ask)
    assert shown["byok"] is True and shown["credits"] is None
    assert shown["renders"][0]["credits"] is None
    assert shown["estimate_usd"] == pytest.approx(charged.provider_usd_micros / 1_000_000)
    # and on a vendor it holds no key of its own for, it is charged like anyone
    assert pricing.quote(account_id=two_accounts["byok"], shot=scene(), shot_id=361,
                         provider="fal") is not None


def test_a_quote_carries_only_ints_and_strings(runway_only):
    """Step 4 signs this. A float in a signed body is a signature that
    breaks on another Python."""
    q = pricing.quote(account_id=None, shot=planned(), shot_id=361, part=2,
                      provider="runway", model="gen4_turbo")
    flat = [q.pricing_version, q.shot_id, q.part, q.provider, q.model, q.seconds, q.frame,
            q.provider_usd_micros, q.credits, q.content_hash, *q.line_items[0]]
    assert all(isinstance(v, (int, str)) and not isinstance(v, bool) for v in flat)
    assert q.line_items[0][1] == q.credits


def test_account_id_is_keyword_only_with_no_default():
    with pytest.raises(TypeError):
        pricing.quote(shot=scene(), shot_id=1)
    with pytest.raises(TypeError):
        pricing.estimate(None, scene())
