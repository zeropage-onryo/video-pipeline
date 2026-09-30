"""ops/stripe_setup.py against a fake Stripe: prices, webhook, .env, Fly.

No network (tests/conftest.py blocks it) -- `stripe` is swapped for an
in-memory stand-in that holds Products, Prices and WebhookEndpoints the
way the account would.
"""

from __future__ import annotations

import itertools
from dataclasses import replace
from types import SimpleNamespace

import pytest

from ops import stripe_setup as setup
from src import billing, pricing


class FakeStripe:
    api_version = "2026-08-26.dahlia"

    def __init__(self):
        ids = itertools.count(1)
        self.products, self.prices, self.hooks = [], [], []
        self.deleted_hooks = []
        fake = self

        def obj(prefix, **kw):
            return SimpleNamespace(id=f"{prefix}_{next(ids)}", **kw)

        class Product:
            @staticmethod
            def list(active=True, limit=100):
                return SimpleNamespace(auto_paging_iter=lambda: iter(list(fake.products)))

            @staticmethod
            def create(name, metadata):
                p = obj("prod", name=name, metadata=metadata)
                fake.products.append(p)
                return p

            @staticmethod
            def search(**_):  # eventually consistent: must not be relied on
                raise AssertionError("Product.search used")

        class Price:
            @staticmethod
            def list(lookup_keys, active=True, limit=1):
                hit = [p for p in fake.prices if p.lookup_key in lookup_keys and p.active]
                return SimpleNamespace(data=hit[:limit])

            @staticmethod
            def create(product, currency, unit_amount, lookup_key, transfer_lookup_key,
                       metadata, recurring=None):
                if transfer_lookup_key:
                    for p in fake.prices:
                        if p.lookup_key == lookup_key:
                            p.lookup_key = None
                p = obj("price", product=product, unit_amount=unit_amount, active=True,
                        lookup_key=lookup_key, recurring=recurring, metadata=metadata)
                fake.prices.append(p)
                return p

            @staticmethod
            def modify(pid, active):
                next(p for p in fake.prices if p.id == pid).active = active

        class WebhookEndpoint:
            @staticmethod
            def list(limit=100):
                return SimpleNamespace(data=list(fake.hooks))

            @staticmethod
            def create(url, enabled_events, api_version, description):
                h = obj("we", url=url, enabled_events=enabled_events,
                        api_version=api_version, secret=f"whsec_{next(ids)}")
                fake.hooks.append(h)
                return h

            @staticmethod
            def modify(hid, enabled_events):
                next(h for h in fake.hooks if h.id == hid).enabled_events = enabled_events

            @staticmethod
            def delete(hid):
                fake.hooks[:] = [h for h in fake.hooks if h.id != hid]
                fake.deleted_hooks.append(hid)

        self.Product, self.Price, self.WebhookEndpoint = Product, Price, WebhookEndpoint
        self.api_key = None


@pytest.fixture
def env(tmp_path, monkeypatch):
    fake = FakeStripe()
    path = tmp_path / ".env"
    path.write_text("GEMINI_API_KEY=g\nSTRIPE_SECRET_KEY=sk_test_abc\n")
    monkeypatch.setattr(setup, "ENV", path)
    monkeypatch.setattr(setup, "stripe", fake)
    return SimpleNamespace(path=path, fake=fake)


def values(path):
    return dict(line.split("=", 1) for line in path.read_text().splitlines()
                if line and not line.startswith("#"))


def test_first_run_creates_seven_prices_and_one_webhook(env):
    setup.main([])
    v = values(env.path)
    assert len(env.fake.prices) == 7
    assert len(env.fake.products) == 4          # three plans + the top-up
    for plan in pricing.PLANS.values():
        month = next(p for p in env.fake.prices if p.id == v[plan.price_env])
        year = next(p for p in env.fake.prices if p.id == v[plan.price_env_yearly])
        assert month.unit_amount == plan.monthly_usd * 100
        assert month.recurring == {"interval": "month"}
        assert year.unit_amount == plan.yearly_usd * 100
        assert year.recurring == {"interval": "year"}
    topup = next(p for p in env.fake.prices if p.id == v[pricing.TOPUP.price_env])
    assert topup.unit_amount == pricing.TOPUP.usd * 100 and topup.recurring is None
    (hook,) = env.fake.hooks
    assert hook.url == setup.WEBHOOK_URL
    assert sorted(hook.enabled_events) == sorted(billing.HANDLED_EVENTS)
    assert hook.api_version == FakeStripe.api_version
    assert v["STRIPE_WEBHOOK_SECRET"] == hook.secret
    assert v[setup.ENDPOINT_ENV] == hook.id
    assert v["BILLING_RETURN_URL"] == setup.RETURN_URL
    assert v["GEMINI_API_KEY"] == "g"           # nothing else touched
    assert list(env.path.parent.glob(".env.bak.stripe.*"))


def test_rerun_reuses_everything(env):
    setup.main([])
    before = values(env.path)
    setup.main([])
    assert len(env.fake.prices) == 7 and len(env.fake.products) == 4
    assert len(env.fake.hooks) == 1 and not env.fake.deleted_hooks
    assert values(env.path) == before


def test_amount_change_moves_the_lookup_key_and_archives_the_old(env, monkeypatch):
    setup.main([])
    old = values(env.path)[pricing.TOPUP.price_env]
    monkeypatch.setattr(pricing, "TOPUP", replace(pricing.TOPUP, usd=pricing.TOPUP.usd + 1))
    setup.main([])
    new = values(env.path)[pricing.TOPUP.price_env]
    assert new != old
    assert next(p for p in env.fake.prices if p.id == old).active is False
    assert len(env.fake.products) == 4          # same Product, new Price


def test_a_secret_for_another_endpoint_is_not_kept(env):
    """The --live trap: .env still holds the TEST endpoint's secret."""
    setup.main([])
    stale = values(env.path)["STRIPE_WEBHOOK_SECRET"]
    env.fake.hooks[0].id = "we_other_mode"      # the endpoint here is not the one .env names
    setup.main([])
    assert env.fake.deleted_hooks == ["we_other_mode"]
    assert values(env.path)["STRIPE_WEBHOOK_SECRET"] != stale


def test_live_key_needs_live_flag_and_vice_versa(env):
    env.path.write_text("STRIPE_SECRET_KEY=sk_live_x\n")
    with pytest.raises(SystemExit, match="LIVE key"):
        setup.main([])
    env.path.write_text("STRIPE_SECRET_KEY=sk_test_x\n")
    with pytest.raises(SystemExit, match="test key"):
        setup.main(["--live"])
    assert not env.fake.prices


def test_no_key_changes_nothing(env):
    env.path.write_text("GEMINI_API_KEY=g\n")
    with pytest.raises(SystemExit, match="STRIPE_SECRET_KEY"):
        setup.main([])
    assert env.path.read_text() == "GEMINI_API_KEY=g\n"


def test_fly_push_goes_through_stdin(env, monkeypatch):
    calls = []

    def run(argv, input, text, capture_output):
        calls.append((argv, input))
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(setup.subprocess, "run", run)
    setup.main(["--fly"])
    ((argv, body),) = calls
    assert argv == ["fly", "secrets", "import", "-a", setup.FLY_APP]
    assert "sk_test_abc" not in " ".join(argv)
    pushed = dict(line.split("=", 1) for line in body.splitlines())
    assert pushed["STRIPE_SECRET_KEY"] == "sk_test_abc"
    assert pushed["STRIPE_WEBHOOK_SECRET"].startswith("whsec_")
    assert setup.ENDPOINT_ENV not in pushed
    assert pricing.TOPUP.price_env in pushed
