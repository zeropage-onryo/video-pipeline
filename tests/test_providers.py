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
