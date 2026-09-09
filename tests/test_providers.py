"""
The aggregator registry: every real adapter matches the shared contract,
usable() reads keys/approval correctly, choose_provider() ranks on real
cost-per-keeper before falling back to sticker price.
"""
from __future__ import annotations

import pytest

from src import generative, higgsfield, providers, runway, veo


@pytest.fixture
def tmp_db(pg):
    path = pg
    generative.init(path)
    return path


def test_every_registered_adapter_matches_the_contract():
    """The whole point of the registry: nothing in VIDEO_PROVIDERS may be
    missing a piece of the shape a router depends on. This is what would
    have caught veo.has_key() being absent before 2026-09-04, instead of
    a router silently treating veo as never usable."""
    for name, module in providers.VIDEO_PROVIDERS.items():
        missing = providers.conforms(module)
        assert missing == [], f"{name} is missing {missing}"


def test_usable_requires_both_a_key_and_approval(monkeypatch):
    monkeypatch.setattr(runway, "has_key", lambda account_id=None: True)
    monkeypatch.setattr(runway, "spend_approved", lambda: False)
    monkeypatch.setattr(veo, "has_key", lambda account_id=None: False)
    monkeypatch.setattr(veo, "spend_approved", lambda: True)
    monkeypatch.setattr(higgsfield, "has_key", lambda account_id=None: True)
    monkeypatch.setattr(higgsfield, "spend_approved", lambda: True)

    assert providers.usable() == ["higgsfield"]


def test_usable_can_be_scoped_to_a_subset():
    result = providers.usable(tools=["runway"])
    assert result in ([], ["runway"])  # depends on real env keys/approval
    assert all(t == "runway" for t in result)


def test_choose_provider_none_when_nothing_is_usable(monkeypatch):
    for mod in providers.VIDEO_PROVIDERS.values():
        monkeypatch.setattr(mod, "has_key", lambda account_id=None: False)
    assert providers.choose_provider() is None


def test_choose_provider_falls_back_to_default_order_with_no_history(
    monkeypatch, tmp_db,
):
    for mod in providers.VIDEO_PROVIDERS.values():
        monkeypatch.setattr(mod, "has_key", lambda account_id=None: True)
        monkeypatch.setattr(mod, "spend_approved", lambda: True)

    # empty generations table -> tool_scoreboard has nothing -> DEFAULT_ORDER
    assert providers.choose_provider(db_path=tmp_db) == providers.DEFAULT_ORDER[0]


def test_choose_provider_prefers_the_cheapest_actual_keeper(monkeypatch, tmp_db):
    for mod in providers.VIDEO_PROVIDERS.values():
        monkeypatch.setattr(mod, "has_key", lambda account_id=None: True)
        monkeypatch.setattr(mod, "spend_approved", lambda: True)

    # veo is last in DEFAULT_ORDER (most expensive sticker price), but if
    # this account's own history shows it's actually the cheapest per KEPT
    # clip, the router should prefer it over runway/higgsfield anyway.
    from src.shot import Shot

    shot_id = generative.add_shot(
        Shot(subject="x", action="y"), dsn=tmp_db, account_id=None,
    )
    veo_gen_id = generative.record_generation(
        shot_id, "veo", "prompt", output_path="/tmp/a.mp4",
        cost_usd=0.10, dsn=tmp_db, account_id=None,
    )
    generative.mark_kept(veo_gen_id, dsn=tmp_db, account_id=None)
    runway_gen_id = generative.record_generation(
        shot_id, "runway", "prompt", output_path="/tmp/b.mp4",
        cost_usd=5.00, dsn=tmp_db, account_id=None,
    )
    generative.mark_kept(runway_gen_id, dsn=tmp_db, account_id=None)

    assert providers.choose_provider(db_path=tmp_db) == "veo"


def test_choose_provider_honours_exclude(monkeypatch, tmp_db):
    for mod in providers.VIDEO_PROVIDERS.values():
        monkeypatch.setattr(mod, "has_key", lambda account_id=None: True)
        monkeypatch.setattr(mod, "spend_approved", lambda: True)

    first = providers.choose_provider(db_path=tmp_db)
    second = providers.choose_provider(db_path=tmp_db, exclude=(first,))
    assert second != first
    assert second in providers.VIDEO_PROVIDERS


# --- the render options catalogue -------------------------------------------
# What the Queue's picker is allowed to offer, and the one number in it
# that is computed twice on purpose.

def test_every_provider_offers_at_least_one_model():
    options = providers.render_options()
    assert set(options) == set(providers.VIDEO_PROVIDERS)
    for name, entry in options.items():
        assert entry["models"], f"{name} projected no models"
        assert entry["default_model"] in [m["id"] for m in entry["models"]]
        assert entry["frame_axis"] in ("ratio", "resolution")


def test_the_catalogue_is_a_projection_not_a_copy():
    """Every model offered has to exist in the adapter's own table. A
    catalogue that can name a model the adapter cannot render is the
    manual lane's drifted-ratio bug wearing a different hat."""
    from src import fal
    assert {m["id"] for m in providers.models_for("fal")} == set(fal.VIDEO_MODELS)
    assert {m["id"] for m in providers.models_for("higgsfield")} == set(higgsfield.VIDEO_MODELS)
    assert {m["id"] for m in providers.models_for("veo")} == set(veo.MODELS)
    assert {m["id"] for m in providers.models_for("runway")} == set(runway.MODELS)


def test_the_cards_price_label_equals_the_adapters_invoice():
    """THE DUPLICATION THIS FILE EXISTS TO POLICE.

    The card multiplies a rate card client-side so dragging a duration
    does not cost a request per keystroke. That is a second
    implementation of estimate_cost, in JavaScript, where nothing can
    import the first one -- so the shape it multiplies is asserted here
    against the adapter's own answer, for every model, every legal
    duration and every legal frame. The day a vendor's price stops being
    linear in seconds, this fails and providers._price_for has to learn
    the new shape rather than the card quietly lying about the bill.
    """
    for name in providers.VIDEO_PROVIDERS:
        for spec in providers.models_for(name):
            if not spec["available"]:
                continue
            price = spec["price"]
            duration = spec["duration"]
            seconds = ([duration["min"], duration["max"]]
                       if duration["kind"] == "range" else duration["values"])
            for frame in spec["frame"]["values"]:
                for length in seconds:
                    label = (price["usd"] if price["kind"] == "flat"
                             else (price.get("usd_by_frame", {}).get(frame,
                                   price.get("usd")) * length))
                    invoice = providers.check_render_choice(
                        name, spec["id"], length, frame)["estimate_usd"]
                    assert round(label, 2) == pytest.approx(invoice, abs=0.011), (
                        f"{name}/{spec['id']} {length}s {frame}: card says "
                        f"{label}, adapter says {invoice}")


def test_a_length_outside_the_model_is_refused_not_rounded():
    """render_specs' rule, at the picker: a value outside the legal set is
    evidence the card and the model have come apart, and rounding it
    spends real money on something nobody chose."""
    with pytest.raises(ValueError, match="does not render"):
        providers.check_render_choice("runway", "gen4_turbo", 7)   # 5 or 10, nothing between
    with pytest.raises(ValueError, match="renders 1-20s"):
        providers.check_render_choice("fal", "ltx2.3", 40)
    # ...but a real in-range value on a clamping vendor is a real request
    assert providers.check_render_choice("fal", "ltx2.3", 7)["duration"] == 7


def test_an_unknown_renderer_or_model_says_what_is_legal():
    with pytest.raises(ValueError, match="unknown renderer"):
        providers.check_render_choice("sora")
    with pytest.raises(ValueError, match="has no model"):
        providers.check_render_choice("runway", "gen9_ultra")


def test_a_fixed_axis_refuses_a_value_and_says_why_it_is_fixed():
    """Veo's durations and Higgsfield's resolutions are not published
    anywhere this repo has verified. Offering the adapter's own default
    and refusing the rest is deliberate -- a guessed list refuses values
    that are real and admits values that are not."""
    with pytest.raises(ValueError, match="fixed at"):
        providers.check_render_choice("veo", veo.DEFAULT_MODEL, 5)
    assert providers.check_render_choice(
        "veo", veo.DEFAULT_MODEL)["duration"] == veo.DEFAULT_DURATION


def test_a_shots_planned_tool_resolves_to_the_same_model_the_graph_uses():
    """The Queue and the nightly graph have to agree about what "KLING"
    means. orchestrator.generate_render binds fal.connector("kling");
    the card defaults through platform_default -- both read
    fal.PLATFORM_MODELS, and this is the assertion that keeps it so."""
    from src import fal
    for platform, model in fal.PLATFORM_MODELS.items():
        assert providers.platform_default(platform) == ("fal", model)
    assert providers.platform_default("RUNWAY") == ("runway", runway.DEFAULT_MODEL)
    assert providers.platform_default("veo") == ("veo", veo.DEFAULT_MODEL)
    assert providers.platform_default("") is None
    assert providers.platform_default("sora") is None


def test_default_model_never_offers_something_the_catalogue_lacks(monkeypatch):
    """RUNWAY_MODEL and friends are env vars, so one can name a model the
    spec table has never heard of -- and offering that as the default
    would mean every approve refused."""
    monkeypatch.setattr(runway, "DEFAULT_MODEL", "gen9_ultra")
    assert providers.default_model("runway") in [m["id"] for m in providers.models_for("runway")]
