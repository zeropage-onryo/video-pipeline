"""
The credit hold, wired (2026-09-18, phase 1 + 3 of
docs/tasks/task-stripe-billing.md, src/charge.py).

What each test guards:
- the hold is taken BEFORE the submit, so an empty balance means the
  provider was never called (the fake client records every create)
- a successful render settles the hold at the CHARGE, linked to the
  generations row, and leaves nothing outstanding
- a failed render releases the hold: the customer pays nothing
- the unowned pool, the manual lane and a credit-exempt account take no
  hold -- and a render stamped with a customer's key does NOT any more
  (BYOK was removed 2026-09-26: every render holds)
- the exemption is a column with a CLI verb, fails closed, and is
  applied inside hold_for_render (the only place)
- a plan's tier reaches the band check: a Starter account is refused a
  premium model BY NAME, never quietly downgraded
"""

from types import SimpleNamespace

import pytest

from src import accounts, db, fal, generative, ledger, pricing, providers
from src import charge as charging


@pytest.fixture
def studio(pg, monkeypatch):
    """A seeded account on a fresh schema, rendering on the operator's fal
    key, with a fake fal queue that records every submit and never
    touches the network."""
    monkeypatch.setenv("DATABASE_URL", pg)
    monkeypatch.setenv("FAL_KEY", "OPERATOR-SECRET")
    monkeypatch.setenv(fal.SPEND_ENV, "1")
    generative.init(pg)
    accounts.seed("mike@example.com", dsn=pg)
    ledger.init(pg)
    with db.connect(pg) as conn:
        account_id = conn.execute(
            "SELECT id FROM accounts WHERE slug = 'zeropage'").fetchone()["id"]

    submits = []
    state = {"fail": False}

    def request(url, payload=None, *, account_id=None):
        if payload is not None:                     # the submit
            submits.append(payload)
            if state["fail"]:
                raise RuntimeError("provider fell over")
            return {"status_url": "https://q.test/status",
                    "response_url": "https://q.test/result"}
        if url.endswith("/status"):
            return {"status": "COMPLETED"}
        return {"video": {"url": "https://cdn.test/clip.mp4"}}

    monkeypatch.setattr(fal, "_request", request)

    def download(url, out_path):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"\x00" * 2048)

    monkeypatch.setattr(fal, "_download", download)
    import src.storage as storage
    monkeypatch.setattr(storage, "configured", lambda: False)
    return {"dsn": pg, "account_id": int(account_id), "submits": submits, "state": state}


PROMPT = "a man walks into a rain-lit bar and does not look back " * 2


def _entries(studio, kind):
    return [e for e in ledger.entries(studio["account_id"], studio["dsn"]) if e["kind"] == kind]


# --- the sandwich ------------------------------------------------------------

def test_an_empty_balance_is_refused_before_anything_is_submitted(studio, tmp_path):
    result = fal.generate_from_prompt(PROMPT, db_path=studio["dsn"],
                                         account_id=studio["account_id"])
    assert result["ok"] is False
    assert "out of credits" in result["error"]
    assert "needs" in result["error"]
    assert studio["submits"] == []                      # no HTTP call was made
    assert ledger.outstanding(studio["account_id"], studio["dsn"]) == 0
    with db.connect(studio["dsn"]) as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM generations").fetchone()["n"] == 0


def test_a_render_holds_then_settles_at_the_charge_linked_to_its_row(studio, tmp_path, monkeypatch):
    monkeypatch.setattr(fal, "RENDER_DIR", tmp_path / "renders")
    ledger.grant(studio["account_id"], 1000, "purchase", dsn=studio["dsn"])
    price = ledger.charge_credits(fal.estimate_cost(1))
    assert price == pricing.credits_for(pricing.usd_micros(fal.estimate_cost(1)))

    result = fal.generate_from_prompt(PROMPT, db_path=studio["dsn"],
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

    studio["state"]["fail"] = True
    result = fal.generate_from_prompt(PROMPT, db_path=studio["dsn"],
                                         account_id=studio["account_id"])
    assert result["ok"] is False
    assert len(studio["submits"]) == 1                  # the hold did not stop the attempt
    assert ledger.available(studio["account_id"], studio["dsn"]) == 1000
    assert ledger.outstanding(studio["account_id"], studio["dsn"]) == 0
    assert _entries(studio, "release")


def test_the_settle_never_exceeds_what_was_held(studio):
    """A provider that bills above the estimate is our estimator's error."""
    ledger.grant(studio["account_id"], 1000, "purchase", dsn=studio["dsn"])
    c = charging.Charge(studio["account_id"], provider="fal", ref="cap-1",
                        estimate_usd=1.00, key_source="env", dsn=studio["dsn"])
    c.take()
    c.submitted()
    debited = c.settle(actual_usd=9.00)
    assert debited == c.held == ledger.charge_credits(1.00) == 240
    assert ledger.available(studio["account_id"], studio["dsn"]) == 1000 - 240


# --- who is not charged ------------------------------------------------------

def test_the_pool_the_lane_and_the_operator_take_no_hold(studio):
    dsn, acct = studio["dsn"], studio["account_id"]

    pool = charging.Charge(None, provider="fal", ref="p", estimate_usd=1.0,
                           key_source="env", dsn=dsn)
    assert pool.take() is None

    lane = charging.Charge(acct, provider="fal", ref="l", estimate_usd=1.0,
                           key_source="env", source=next(iter(ledger.SUBSCRIPTION_SOURCES)),
                           dsn=dsn)
    assert lane.take() is None

    assert accounts.set_credit_exempt("zeropage", True, dsn=dsn)["now"] is True
    ours = charging.Charge(acct, provider="fal", ref="o", estimate_usd=1.0,
                           key_source="env", dsn=dsn)
    assert ours.take() is None                            # exempt: no hold, no entry
    assert ours.settle() == 0 and ours.release("x") == 0
    assert ledger.entries(acct, dsn) == []


def test_a_render_stamped_with_a_customers_key_holds_all_the_same(studio):
    """BYOK is gone (2026-09-26). A caller that still labels a render
    `key_source="account"` does not buy a free render with the word: every
    render holds, and settles or releases."""
    dsn, acct = studio["dsn"], studio["account_id"]
    ledger.grant(acct, 1000, "purchase", dsn=dsn)
    c = charging.Charge(acct, provider="fal", ref="was-byok", estimate_usd=1.0,
                        key_source="account", dsn=dsn)
    assert c.take() is not None and c.billed
    assert c.params() == ledger.ref_params("was-byok")
    c.submitted()
    assert c.settle() == 240
    assert ledger.available(acct, dsn) == 1000 - 240
    assert ledger.is_billable("account") is True


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
    monkeypatch.setattr(fal, "RENDER_DIR", tmp_path / "renders")
    accounts.set_credit_exempt("zeropage", True, dsn=studio["dsn"])
    result = fal.generate_from_prompt(PROMPT, db_path=studio["dsn"],
                                         account_id=studio["account_id"])
    assert result["ok"] is True, result
    assert ledger.entries(studio["account_id"], studio["dsn"]) == []
    with db.connect(studio["dsn"]) as conn:
        row = conn.execute("SELECT cost_usd FROM generations WHERE id = %s",
                           (result["generation_id"],)).fetchone()
    assert row["cost_usd"] == pytest.approx(fal.estimate_cost(1))


# --- tiers -------------------------------------------------------------------

def _scene():
    return {"n": 1, "type": "BROLL", "source": "AI", "tool": "LTX",
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
    premium = ("fal", "veo3.1")                   # Veo, through fal
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


# --- the hold is the verified Quote's, not a re-derivation (2026-09-21) ------

def _quote(studio, *, credits, provider="fal", account_id="own"):
    return pricing.Quote(
        pricing_version=pricing.PRICING_VERSION,
        account_id=studio["account_id"] if account_id == "own" else account_id,
        shot_id=1, part=None, provider=provider, model=fal.DEFAULT_MODEL,
        seconds=6, frame="1080p", provider_usd_micros=360000,
        credits=credits, content_hash="0" * 16, line_items=())


def test_a_quote_in_hand_is_what_is_held_and_settled(studio, tmp_path, monkeypatch):
    """A number the estimate could never produce, so the two cannot agree
    by coincidence -- which is all that made them agree before."""
    monkeypatch.setattr(fal, "RENDER_DIR", tmp_path / "renders")
    monkeypatch.delenv(fal.SPEND_ENV)                   # the Quote is the approval
    ledger.grant(studio["account_id"], 1000, "purchase", dsn=studio["dsn"])
    assert ledger.charge_credits(fal.estimate_cost(1)) != 777
    result = fal.generate_from_prompt(PROMPT, db_path=studio["dsn"],
                                         account_id=studio["account_id"],
                                         quote=_quote(studio, credits=777))
    assert result["ok"] is True, result
    assert -sum(e["delta"] for e in _entries(studio, "hold")) == 777
    assert ledger.available(studio["account_id"], studio["dsn"]) == 1000 - 777
    assert ledger.outstanding(studio["account_id"], studio["dsn"]) == 0
    assert all(e["generation_id"] == result["generation_id"] for e in _entries(studio, "settle"))


def test_without_a_quote_the_estimate_is_still_the_fallback(studio, tmp_path, monkeypatch):
    monkeypatch.setattr(fal, "RENDER_DIR", tmp_path / "renders")
    ledger.grant(studio["account_id"], 1000, "purchase", dsn=studio["dsn"])
    result = fal.generate_from_prompt(PROMPT, db_path=studio["dsn"],
                                         account_id=studio["account_id"])
    assert result["ok"] is True, result
    price = ledger.charge_credits(fal.estimate_cost(1))
    assert ledger.available(studio["account_id"], studio["dsn"]) == 1000 - price


@pytest.mark.parametrize("wrong", [{"account_id": 999999}, {"provider": "runway"}])
def test_somebody_elses_quote_holds_nothing_and_submits_nothing(studio, wrong):
    ledger.grant(studio["account_id"], 1000, "purchase", dsn=studio["dsn"])
    result = fal.generate_from_prompt(PROMPT, db_path=studio["dsn"], approved=True,
                                         account_id=studio["account_id"],
                                         quote=_quote(studio, credits=5, **wrong))
    assert result["ok"] is False
    assert studio["submits"] == []
    assert _entries(studio, "hold") == []
    assert ledger.available(studio["account_id"], studio["dsn"]) == 1000


def test_spend_approved_changed_shape_not_location(monkeypatch):
    module = providers.VIDEO_PROVIDERS["fal"]
    monkeypatch.delenv(module.SPEND_ENV, raising=False)
    mine = SimpleNamespace(provider="fal")
    theirs = SimpleNamespace(provider="somebody-else")
    assert module.spend_approved() is False                       # unattended, unarmed
    assert module.spend_approved(quote=mine) is True              # a verified, priced click
    assert module.spend_approved(False, quote=mine) is False      # an explicit no is a no
    assert module.spend_approved(True, quote=theirs) is False     # a price for another render
    assert module.spend_approved(True) is True                    # the click, unquoted server
    monkeypatch.setenv(module.SPEND_ENV, "1")
    assert module.spend_approved() is True                        # the nightly, armed on purpose


@pytest.mark.parametrize("edge", ["generate_for_shot", "generate_from_prompt"])
def test_every_person_driven_edge_hands_its_quote_to_the_charge(studio, monkeypatch, edge):
    """The Quote has to arrive where the hold is taken: a keyword accepted
    and then dropped would hold the estimate again and nothing else in the
    suite would notice."""
    from src import preprod
    module = providers.VIDEO_PROVIDERS["fal"]
    seen = []

    def stop(prompt, out_path, **kw):
        seen.append(kw["charge"].quote)
        raise RuntimeError("stop before anything is submitted")
    monkeypatch.setattr(module, "generate_video", stop)
    quote = _quote(studio, credits=321)
    if edge == "generate_for_shot":
        preprod.init(studio["dsn"])
        concept_id = preprod.save_concept(
            {"title": "t", "hook": "h", "logline": "l", "shots": [_scene()]},
            "zeropage", dsn=studio["dsn"], account_id=studio["account_id"])
        result = module.generate_for_shot(concept_id, 1, db_path=studio["dsn"],
                                          account_id=studio["account_id"], quote=quote)
    else:
        result = module.generate_from_prompt(PROMPT, db_path=studio["dsn"],
                                             account_id=studio["account_id"], quote=quote)
    assert result["ok"] is False
    assert seen == [quote]


def test_generate_video_asks_the_gate_with_the_charges_quote(tmp_path, monkeypatch):
    """The gate did not move: it is still inside generate_video, and it is
    shown the Quote the Charge carries. A price for another renderer is
    refused there even on an approved click -- before anything is held."""
    module = providers.VIDEO_PROVIDERS["fal"]
    monkeypatch.setenv(module.SPEND_ENV, "1")
    charge = charging.Charge(None, provider="fal", ref="x.mp4", estimate_usd=0.25,
                             quote=SimpleNamespace(provider="somebody-else",
                                                   account_id=None, credits=5))
    with pytest.raises(RuntimeError, match="not approved"):
        module.generate_video(PROMPT, tmp_path / "x.mp4", approved=True, charge=charge)
    assert charge.hold_id is None and charge.held == 0


# --- no key, no hold ---------------------------------------------------------

def test_a_render_with_no_fal_key_refuses_before_any_http_call_and_holds_nothing(
        studio, tmp_path, monkeypatch):
    """The operator's key is the only one. With FAL_KEY unset a render is
    refused before the hold -- not after it, which would take credit from
    somebody for the moment a release takes to give it back -- and before
    any HTTP call, injected or not."""
    for name in fal.KEY_ENV:
        monkeypatch.delenv(name, raising=False)
    ledger.grant(studio["account_id"], 1000, "purchase", dsn=studio["dsn"])
    calls = []

    def http(url, payload=None):
        calls.append(url)
        return {}
    charge = charging.Charge(studio["account_id"], provider="fal", ref="nokey.mp4",
                             estimate_usd=0.36, dsn=studio["dsn"])
    with pytest.raises(RuntimeError, match="FAL_KEY not set"):
        fal.generate_video(PROMPT, tmp_path / "nokey.mp4", approved=True,
                           http=http, charge=charge, account_id=studio["account_id"],
                           db_path=studio["dsn"])
    assert calls == []
    assert charge.hold_id is None
    assert _entries(studio, "hold") == []
    assert ledger.available(studio["account_id"], studio["dsn"]) == 1000
    # and the never-raises edge a door calls says so without a hold either
    result = fal.generate_from_prompt(PROMPT, db_path=studio["dsn"], approved=True,
                                      account_id=studio["account_id"], http=http)
    assert result["ok"] is False and "FAL_KEY" in result["error"]
    assert calls == [] and _entries(studio, "hold") == []
