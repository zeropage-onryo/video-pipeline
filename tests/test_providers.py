"""
The renderer registry -- fal alone since 2026-09-26 (docs/tasks/
task-fal-only.md): the adapter matches the shared contract, usable() reads
key and approval, choose_provider() never retries the provider that just
failed, and the picker offers exactly what fal.VIDEO_MODELS can render.
"""
from __future__ import annotations

import pytest

from src import fal, generative, providers


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


def test_fal_is_the_only_video_renderer():
    assert set(providers.VIDEO_PROVIDERS) == {"fal"}
    assert providers.DEFAULT_ORDER == ("fal",)


def test_usable_requires_both_a_key_and_approval(monkeypatch):
    monkeypatch.setattr(fal, "has_key", lambda account_id=None: True)
    monkeypatch.setattr(fal, "spend_approved", lambda: False)
    assert providers.usable() == []
    monkeypatch.setattr(fal, "spend_approved", lambda: True)
    assert providers.usable() == ["fal"]
    monkeypatch.setattr(fal, "has_key", lambda account_id=None: False)
    assert providers.usable() == []


def test_usable_ignores_a_retired_name():
    assert providers.usable(tools=["runway"]) == []


def test_choose_provider_none_when_nothing_is_usable(monkeypatch):
    monkeypatch.setattr(fal, "has_key", lambda account_id=None: False)
    assert providers.choose_provider() is None


def test_choose_provider_is_fal_when_it_is_usable(monkeypatch, tmp_db):
    monkeypatch.setattr(fal, "has_key", lambda account_id=None: True)
    monkeypatch.setattr(fal, "spend_approved", lambda: True)
    assert providers.choose_provider(db_path=tmp_db) == "fal"


def test_choose_provider_never_retries_the_provider_that_failed(monkeypatch, tmp_db):
    """The graph's failover excludes the provider that just failed. With
    one renderer that means a fal failure is reported, not retried on fal
    through another door."""
    monkeypatch.setattr(fal, "has_key", lambda account_id=None: True)
    monkeypatch.setattr(fal, "spend_approved", lambda: True)
    assert providers.choose_provider(db_path=tmp_db, exclude=("fal",)) is None


# --- the render options catalogue -------------------------------------------
# What the Queue's picker is allowed to offer, and the one number in it
# that is computed twice on purpose.

def test_every_provider_offers_at_least_one_model():
    options = providers.render_options()
    assert set(options) == set(providers.VIDEO_PROVIDERS)
    for name, entry in options.items():
        assert entry["models"], f"{name} projected no models"
        assert entry["default_model"] in [m["id"] for m in entry["models"]]
        assert entry["frame_axis"] == "resolution"


def test_the_catalogue_is_a_projection_not_a_copy():
    """Every model offered has to exist in the adapter's own table. A
    catalogue that can name a model the adapter cannot render is the
    manual lane's drifted-ratio bug wearing a different hat."""
    assert {m["id"] for m in providers.models_for("fal")} == set(fal.VIDEO_MODELS)
    # Veo lives on as a fal model
    assert "veo3.1" in {m["id"] for m in providers.models_for("fal")}
    with pytest.raises(ValueError, match="unknown renderer"):
        providers.models_for("runway")


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
    """A value outside the legal set is evidence the card and the model
    have come apart, and rounding it spends real money on something nobody
    chose. LTX-2.3 takes an ENUM (6/8/10), Kling a span (3-15)."""
    with pytest.raises(ValueError, match="does not render"):
        providers.check_render_choice("fal", "ltx2.3", 7)
    with pytest.raises(ValueError, match="renders 3-15s"):
        providers.check_render_choice("fal", "kling3-turbo-pro", 40)
    # ...but a real in-range value is a real request
    assert providers.check_render_choice("fal", "kling3-turbo-pro", 7)["duration"] == 7
    assert providers.check_render_choice("fal", "ltx2.3", 8)["duration"] == 8


def test_a_resolution_the_model_does_not_render_is_refused():
    with pytest.raises(ValueError, match="does not render resolution"):
        providers.check_render_choice("fal", "seedance2-fast", 5, "1080p")


def test_an_unknown_renderer_or_model_says_what_is_legal():
    with pytest.raises(ValueError, match="unknown renderer"):
        providers.check_render_choice("sora")
    with pytest.raises(ValueError, match="unknown renderer"):
        providers.check_render_choice("runway", "gen4_turbo")
    with pytest.raises(ValueError, match="has no model"):
        providers.check_render_choice("fal", "gen9_ultra")


def test_a_fixed_axis_refuses_a_value_and_says_why_it_is_fixed():
    """Kling takes no resolution field: its frame is fixed, and the card
    prints why beside the disabled control."""
    with pytest.raises(ValueError, match="fixed at"):
        providers.check_render_choice("fal", "kling3-turbo-pro", 5, "720p")
    assert providers.check_render_choice(
        "fal", "kling3-turbo-pro")["frame"] == "1080p"


def test_a_shots_planned_tool_resolves_to_the_same_model_the_graph_uses():
    """The Queue and the nightly graph have to agree about what "KLING"
    means. orchestrator.generate_render binds fal.connector("kling");
    the card defaults through platform_default -- both read
    fal.PLATFORM_MODELS, and this is the assertion that keeps it so."""
    for platform, model in fal.PLATFORM_MODELS.items():
        assert providers.platform_default(platform) == ("fal", model)
    assert providers.platform_default("veo") == ("fal", "veo3.1")
    # a retired tool on an old row reads as the fal default
    assert providers.platform_default("RUNWAY") == ("fal", fal.DEFAULT_MODEL)
    assert providers.platform_default("higgsfield") == ("fal", fal.DEFAULT_MODEL)
    assert providers.platform_default("") is None
    assert providers.platform_default("sora") is None


def test_default_model_never_offers_something_the_catalogue_lacks(monkeypatch):
    """FAL_MODEL is an env var, so it can name a model the spec table has
    never heard of -- and offering that as the default would mean every
    approve refused."""
    monkeypatch.setattr(fal, "DEFAULT_MODEL", "gen9_ultra")
    assert providers.default_model("fal") in [m["id"] for m in providers.models_for("fal")]


def test_the_default_render_is_the_cheap_720p_or_the_models_floor():
    """Default resolution is 720p where a model offers it; LTX-2.3's floor
    is 1080p, and its shortest clip is 6s."""
    for spec in providers.models_for("fal"):
        if "720p" in spec["frame"]["values"]:
            assert spec["frame"]["default"] == "720p", spec["id"]
    ltx = providers.check_render_choice("fal", "ltx2.3")
    assert (ltx["duration"], ltx["frame"]) == (6, "1080p")
    assert ltx["estimate_usd"] == pytest.approx(0.36)
