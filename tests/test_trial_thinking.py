"""
The trial's thinking is included once, not forever (2026-10-08, Mike: "fix
the trial then. keep the first approach").

On a plan the brain is free -- the Guide, Create and the rest cost no
credits, their cost carried by the render markup. The sign-up trial has
no plan to carry it, so an account that has never had credit the trial did
not give it may spend pricing.trial_thinking_usd() of model text, ONCE,
and is then refused 402 `trial_thinking_used`. What each test guards:

- the trial thinks freely up to the cap and is refused at it
- stills do not count: they are charged in credits already
- a paying account, a lapsed subscriber and an operator-vouched pilot are
  never held to it; a plan or the exempt flag skips it outright
- the cap is configurable, and a read error fails open
- the route answers with the trial's own code, before any job starts
"""
import json

import pytest
from fastapi.testclient import TestClient

from src import accounts, charge, db, ledger, pricing, spend


@pytest.fixture
def trial(pg, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", pg)
    monkeypatch.delenv(pricing.TRIAL_THINKING_ENV, raising=False)
    accounts.seed("mike@example.com", dsn=pg)
    ledger.init(pg)
    spend.init(pg)
    with db.connect(pg) as conn:
        account_id = int(conn.execute(
            "SELECT id FROM accounts WHERE slug = 'zeropage'").fetchone()["id"])
    ledger.grant(account_id, 100, "promo", source_ref=f"signup:{account_id}", dsn=pg)
    return {"dsn": pg, "account_id": account_id}


def _think(trial, usd, stage="creative_guide"):
    assert spend.record_call(stage=stage, model_asked="gemini-3-flash-preview", usage={},
                             cost_usd=usd, account_id=trial["account_id"],
                             dsn=trial["dsn"]) is not None


def _refused(trial):
    return charge.create_refusal_code(trial["account_id"], dsn=trial["dsn"])


def test_the_trial_thinks_freely_up_to_its_cap_and_no_further(trial):
    assert pricing.trial_thinking_usd() == pricing.TRIAL_THINKING_USD == 1.00
    _think(trial, 0.60)
    assert _refused(trial) is None
    _think(trial, 0.40)
    assert _refused(trial) == (charge.TRIAL_CODE, charge.TRIAL_THINKING_REFUSAL)
    # the balance is untouched: thinking is never debited, only capped
    assert ledger.available(trial["account_id"], dsn=trial["dsn"]) == 100


def test_stills_are_not_thinking(trial):
    _think(trial, 5.00, stage="nano_image")
    assert _refused(trial) is None


@pytest.mark.parametrize("kind", ["purchase", "subscription", "adjustment"])
def test_an_account_past_the_trial_is_never_capped(trial, kind):
    """Paid (a purchase, a subscription -- still held after the plan lapsed)
    or vouched for by the operator (an adjustment): the brain is free."""
    ledger.grant(trial["account_id"], 500, kind, source_ref=f"{kind}:1", dsn=trial["dsn"])
    _think(trial, 50.00)
    assert accounts.plan_of(trial["account_id"], dsn=trial["dsn"]) is None
    assert _refused(trial) is None


def test_a_plan_or_the_exempt_flag_skips_the_cap(trial):
    _think(trial, 50.00)
    assert _refused(trial)[0] == charge.TRIAL_CODE
    accounts.set_plan(trial["account_id"], "starter", dsn=trial["dsn"])
    assert _refused(trial) is None
    accounts.set_plan(trial["account_id"], None, dsn=trial["dsn"])
    accounts.set_credit_exempt("zeropage", True, dsn=trial["dsn"])
    assert _refused(trial) is None


def test_no_balance_is_still_the_no_plan_refusal(trial):
    """The trial's cap is the second question; an account with nothing to
    spend gets the answer it always got."""
    broke = accounts.upsert_account("broke", "Broke", dsn=trial["dsn"])
    assert ledger.available(broke, dsn=trial["dsn"]) == 0
    assert charge.create_refusal_code(broke, dsn=trial["dsn"])[0] == charge.NO_PLAN_CODE


def test_the_cap_is_configurable(trial, monkeypatch):
    monkeypatch.setenv(pricing.TRIAL_THINKING_ENV, "0")
    assert _refused(trial)[0] == charge.TRIAL_CODE             # a trial that thinks not at all
    monkeypatch.setenv(pricing.TRIAL_THINKING_ENV, "5")
    _think(trial, 2.00)
    assert _refused(trial) is None
    monkeypatch.setenv(pricing.TRIAL_THINKING_ENV, "not a number")
    assert pricing.trial_thinking_usd() == pricing.TRIAL_THINKING_USD


def test_a_read_error_fails_open(trial, monkeypatch):
    _think(trial, 50.00)

    def boom(*a, **k):
        raise RuntimeError("meter unreachable")

    monkeypatch.setattr(spend, "thinking_spent", boom)
    assert _refused(trial) is None


def test_another_accounts_thinking_is_not_this_trials(trial):
    other = accounts.upsert_account("other", "Other", dsn=trial["dsn"])
    spend.record_call(stage="creative_guide", model_asked="m", usage={}, cost_usd=50.0,
                      account_id=other, dsn=trial["dsn"])
    assert _refused(trial) is None


def test_the_route_answers_with_the_trials_own_code(trial, monkeypatch):
    from app import auth, jobs
    from app.main import app
    started = []
    monkeypatch.setattr(jobs, "start", lambda *a, **k: started.append(a) or {"id": 1})
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr(auth, "current_user", lambda request: {"id": 1, "email": "t@e.com"})
    monkeypatch.setattr(auth, "current_account",
                        lambda request: {"id": trial["account_id"], "slug": "zeropage"})
    app.dependency_overrides[auth.current_account_id] = lambda: trial["account_id"]
    try:
        client = TestClient(app, headers={"X-ZPF-Model-Connection": "1"})
        turn = {"conversation": json.dumps({"messages": [{"role": "user", "content": "hi"}]})}
        assert client.post("/api/creative-guide", data=turn).status_code == 200
        _think(trial, 1.00)
        res = client.post("/api/creative-guide", data=turn)
        assert res.status_code == 402
        assert res.json()["error"]["code"] == "trial_thinking_used"
        assert len(started) == 1                                  # only the first turn ran
    finally:
        app.dependency_overrides[auth.current_account_id] = lambda: None
