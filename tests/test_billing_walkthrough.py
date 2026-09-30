"""
ops/billing_walkthrough.py: the two things that must hold for the test-mode
walk to mean anything -- and to be safe to run at all.

- `relay` signs an event the way Stripe does, so the REAL verifier
  (billing.verify -> stripe.Webhook.construct_event) accepts it; a relay the
  server rejected would test nothing, and one it accepted unsigned would mean
  the server's check was off.
- a live key is refused before any request: this walk never touches money.
"""

import json

import pytest

from ops import billing_walkthrough as walk
from src import billing


def test_the_relay_signature_passes_the_servers_own_verification(monkeypatch):
    secret = "whsec_walk_test"
    monkeypatch.setenv(billing.WEBHOOK_ENV, secret)
    payload = json.dumps({"id": "evt_1", "type": "invoice.paid",
                          "data": {"object": {"id": "in_1"}}}).encode()
    event = billing.verify(payload, walk._sign(payload, secret))
    assert event["id"] == "evt_1"
    with pytest.raises(ValueError):
        billing.verify(payload, walk._sign(payload, "whsec_someone_else"))


@pytest.mark.parametrize("key", ["sk_live_abc", "rk_live_abc", "pk_test_abc", ""])
def test_anything_but_a_test_secret_key_is_refused(monkeypatch, key):
    monkeypatch.setattr(walk, "read_env", lambda: {"STRIPE_SECRET_KEY": key})
    with pytest.raises(SystemExit):
        walk._stripe()


def test_the_walk_never_runs_on_database_url(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://live.example/prod")
    assert "live.example" not in walk.dsn()
    assert "search_path%3Dbillwalk" in walk.dsn()
