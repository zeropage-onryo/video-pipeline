"""
The credit hold, wired (2026-09-18, phase 1 + 3 of
docs/tasks/task-stripe-billing.md, src/charge.py).

What each test guards:
- the hold is taken BEFORE the submit, so an empty balance means the
  provider was never called (the fake client records every create)
- a successful render settles the hold at the CHARGE, linked to the
  generations row, and leaves nothing outstanding
- a failed render releases the hold: the customer pays nothing
- BYOK, the unowned pool and a credit-exempt account take no hold
- the exemption is a column with a CLI verb, fails closed, and is
  applied inside hold_for_render (the only place)
- a plan's tier reaches the band check: a Starter account is refused a
  premium model BY NAME, never quietly downgraded
"""

from types import SimpleNamespace

import pytest

from src import accounts, db, generative, ledger, pricing, providers, runway
from src import charge as charging


@pytest.fixture
def studio(pg, monkeypatch):
    """A seeded account on a fresh schema, rendering on the INSTALLATION's
    key (so the ledger is its business), with a fake Runway SDK that
    records every submit and never touches the network."""
    monkeypatch.setenv("DATABASE_URL", pg)
    monkeypatch.setenv("RUNWAYML_API_SECRET", "OPERATOR-SECRET")
    monkeypatch.setenv(runway.SPEND_ENV, "1")
    generative.init(pg)
    accounts.seed("mike@example.com", dsn=pg)
    ledger.init(pg)
    with db.connect(pg) as conn:
        account_id = conn.execute(
            "SELECT id FROM accounts WHERE slug = 'zeropage'").fetchone()["id"]

    submits = []

    class FakeTask:
        output = ["https://cdn.test/clip.mp4"]

    def create(**kw):
        submits.append(kw)
        return SimpleNamespace(wait_for_task_output=lambda: FakeTask())

    monkeypatch.setattr(runway, "_make_client",
                        lambda *a, **k: SimpleNamespace(image_to_video=SimpleNamespace(create=create)))

    def download(url, out_path):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"\x00" * 2048)

    monkeypatch.setattr(runway, "_download", download)
    import src.storage as storage
    monkeypatch.setattr(storage, "configured", lambda: False)
    return {"dsn": pg, "account_id": int(account_id), "submits": submits}


PROMPT = "a man walks into a rain-lit bar and does not look back " * 2


def _entries(studio, kind):
    return [e for e in ledger.entries(studio["account_id"], studio["dsn"]) if e["kind"] == kind]


# --- the sandwich ------------------------------------------------------------

def test_an_empty_balance_is_refused_before_anything_is_submitted(studio, tmp_path):
    result = runway.generate_from_prompt(PROMPT, db_path=studio["dsn"],
                                         account_id=studio["account_id"])
    assert result["ok"] is False
    assert "out of credits" in result["error"]
    assert "needs" in result["error"]
    assert studio["submits"] == []                      # no HTTP call was made
    assert ledger.outstanding(studio["account_id"], studio["dsn"]) == 0
    with db.connect(studio["dsn"]) as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM generations").fetchone()["n"] == 0


def test_a_render_holds_then_settles_at_the_charge_linked_to_its_row(studio, tmp_path, monkeypatch):
    monkeypatch.setattr(runway, "RENDER_DIR", tmp_path / "renders")
    ledger.grant(studio["account_id"], 1000, "purchase", dsn=studio["dsn"])
    price = ledger.charge_credits(runway.estimate_cost(1))
    assert price == pricing.credits_for(pricing.usd_micros(runway.estimate_cost(1)))

    result = runway.generate_from_prompt(PROMPT, db_path=studio["dsn"],
                                         account_id=studio["account_id"])
    assert result["ok"] is True, result
    assert len(studio["submits"]) == 1
    assert ledger.available(studio["account_id"], studio["dsn"]) == 1000 - price
    assert ledger.outstanding(studio["account_id"], studio["dsn"]) == 0
    settles = _entries(studio, "settle")
    assert settles and all(e["generation_id"] == result["generation_id"] for e in settles)
    holds = _entries(studio, "hold")
    assert holds and all(e["submitted_at"] for e in holds)   # mark_submitted ran
    # the row carries the ref the reaper matches on
    with db.connect(studio["dsn"]) as conn:
        params = conn.execute("SELECT params_json FROM generations WHERE id = %s",
                              (result["generation_id"],)).fetchone()["params_json"]
    import json
    assert json.loads(params)[ledger.GENERATION_REF_KEY] == holds[0]["ref"]


def test_a_failed_render_releases_the_hold(studio, monkeypatch):
    ledger.grant(studio["account_id"], 1000, "purchase", dsn=studio["dsn"])

    def boom(**kw):
        studio["submits"].append(kw)
        raise RuntimeError("provider fell over")

    monkeypatch.setattr(runway, "_make_client",
                        lambda *a, **k: SimpleNamespace(image_to_video=SimpleNamespace(create=boom)))
    result = runway.generate_from_prompt(PROMPT, db_path=studio["dsn"],
                                         account_id=studio["account_id"])
    assert result["ok"] is False
    assert len(studio["submits"]) == 1                  # the hold did not stop the attempt
    assert ledger.available(studio["account_id"], studio["dsn"]) == 1000
    assert ledger.outstanding(studio["account_id"], studio["dsn"]) == 0
    assert _entries(studio, "release")


def test_the_settle_never_exceeds_what_was_held(studio):
    """A provider that bills above the estimate is our estimator's error."""
    ledger.grant(studio["account_id"], 1000, "purchase", dsn=studio["dsn"])
    c = charging.Charge(studio["account_id"], provider="runway", ref="cap-1",
                        estimate_usd=1.00, key_source="env", dsn=studio["dsn"])
    c.take()
    c.submitted()
    debited = c.settle(actual_usd=9.00)
    assert debited == c.held == ledger.charge_credits(1.00) == 240
    assert ledger.available(studio["account_id"], studio["dsn"]) == 1000 - 240


# --- who is not charged ------------------------------------------------------

def test_byok_the_pool_and_the_operator_take_no_hold(studio):
    dsn, acct = studio["dsn"], studio["account_id"]
    byok = charging.Charge(acct, provider="runway", ref="b", estimate_usd=1.0,
                           key_source="account", dsn=dsn)
    assert byok.take() is None and not byok.billed and byok.params() == {}

    pool = charging.Charge(None, provider="runway", ref="p", estimate_usd=1.0,
                           key_source="env", dsn=dsn)
    assert pool.take() is None

    lane = charging.Charge(acct, provider="runway", ref="l", estimate_usd=1.0,
                           key_source="env", source=next(iter(ledger.SUBSCRIPTION_SOURCES)),
                           dsn=dsn)
    assert lane.take() is None

    assert accounts.set_credit_exempt("zeropage", True, dsn=dsn)["now"] is True
    ours = charging.Charge(acct, provider="runway", ref="o", estimate_usd=1.0,
                           key_source="env", dsn=dsn)
    assert ours.take() is None                            # exempt: no hold, no entry
    assert ours.settle() == 0 and ours.release("x") == 0
    assert ledger.entries(acct, dsn) == []


def test_the_exemption_is_a_column_with_a_verb_and_fails_closed(studio, capsys):
    dsn, acct = studio["dsn"], studio["account_id"]
    assert accounts.is_credit_exempt(acct, dsn=dsn) is False      # every account starts FALSE
    assert accounts.is_credit_exempt(None, dsn=dsn) is False
    assert ledger.credit_exempt(acct, dsn=dsn) is False

    on = accounts.set_credit_exempt("zeropage", True, dsn=dsn)
    assert on == {"slug": "zeropage", "account_id": acct, "was": False, "now": True, "changed": True}
    assert accounts.is_credit_exempt(acct, dsn=dsn) is True
    assert accounts.credit_exempt_accounts(dsn=dsn) == [{"account_id": acct, "slug": "zeropage"}]
    again = accounts.set_credit_exempt("zeropage", True, dsn=dsn)
    assert again["changed"] is False
    off = accounts.set_credit_exempt("zeropage", False, dsn=dsn)
    assert off["now"] is False and accounts.is_credit_exempt(acct, dsn=dsn) is False
    with pytest.raises(ValueError, match="no account 'nobody'"):
        accounts.set_credit_exempt("nobody", True, dsn=dsn)

    # the CLI verb, same shape as `operator`
    accounts.main(["credits", "zeropage", "--on"])
    assert "OFF -> ON" in capsys.readouterr().out
    assert accounts.is_credit_exempt(acct, dsn=dsn) is True
    accounts.main(["credits", "zeropage", "--off"])
    assert "ON -> OFF" in capsys.readouterr().out


def test_an_exempt_render_still_writes_the_generations_row(studio, tmp_path, monkeypatch):
    """Exempt from the charge, not from the record."""
    monkeypatch.setattr(runway, "RENDER_DIR", tmp_path / "renders")
    accounts.set_credit_exempt("zeropage", True, dsn=studio["dsn"])
    result = runway.generate_from_prompt(PROMPT, db_path=studio["dsn"],
                                         account_id=studio["account_id"])
    assert result["ok"] is True, result
    assert ledger.entries(studio["account_id"], studio["dsn"]) == []
    with db.connect(studio["dsn"]) as conn:
        row = conn.execute("SELECT cost_usd FROM generations WHERE id = %s",
                           (result["generation_id"],)).fetchone()
    assert row["cost_usd"] == pytest.approx(runway.estimate_cost(1))


# --- tiers -------------------------------------------------------------------

def _scene():
    return {"n": 1, "type": "BROLL", "source": "AI", "tool": "RUNWAY",
            "prompt": PROMPT, "refs": ["/characters/michael/a.jpg"]}


def test_a_plan_puts_a_tier_on_the_account_and_the_band_check_reads_it(studio, monkeypatch):
    dsn, acct = studio["dsn"], studio["account_id"]
    monkeypatch.setenv("FAL_KEY", "x")
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    assert pricing.tier_for(acct, dsn=dsn) is None                  # no plan: no tier
    assert accounts.plan_of(acct, dsn=dsn) is None

    accounts.set_plan(acct, "starter", dsn=dsn)
    assert accounts.plan_of(acct, dsn=dsn) == "starter"
    assert pricing.tier_for(acct, dsn=dsn) == "standard"
    premium = ("veo", "veo-3")                    # veo.py's own model, no probe
    creator = ("fal", "kling3-turbo-pro")
    assert providers.band_for(*premium).tier == "premium"
    assert providers.band_for(*creator).tier == "creator"
    with pytest.raises(pricing.PricingRefused) as refused:
        pricing.estimate(account_id=acct, shot=_scene(), provider=premium[0], model=premium[1])
    assert refused.value.reason == "tier"
    assert "premium-tier" in str(refused.value) and "standard tier" in str(refused.value)
    with pytest.raises(pricing.PricingRefused):
        pricing.estimate(account_id=acct, shot=_scene(), provider=creator[0], model=creator[1])

    accounts.set_plan(acct, "studio", dsn=dsn)
    assert pricing.tier_for(acct, dsn=dsn) == "premium"
    priced = pricing.estimate(account_id=acct, shot=_scene(), provider=premium[0], model=premium[1])
    assert priced.model == premium[1]

    accounts.set_plan(acct, "retired-plan", dsn=dsn)              # a plan this module no longer lists
    assert pricing.tier_for(acct, dsn=dsn) is None
    accounts.set_plan(acct, None, dsn=dsn)
    assert accounts.plan_of(acct, dsn=dsn) is None


def test_the_plans_are_the_three_tiers_in_ascending_order():
    assert [p.tier for p in pricing.PLANS.values()] == list(providers.TIERS)
    prices = [p.monthly_usd for p in pricing.PLANS.values()]
    credits = [p.credits for p in pricing.PLANS.values()]
    assert prices == sorted(prices) and credits == sorted(credits)
    # the peg on the page: a dollar of plan buys 100 credits of charge
    for p in pricing.PLANS.values():
        assert p.credits == p.monthly_usd * 100
    assert pricing.TOPUP.credits == pricing.TOPUP.usd * 100
    assert sum(1 for p in pricing.PLANS.values() if p.popular) == 1
