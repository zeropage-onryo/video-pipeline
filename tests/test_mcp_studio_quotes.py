"""
The studio MCP's approval, in credits, with a signed single-use quote
(2026-10-08, docs/tasks/task-mcp-studio-v2.md step 1).

Before it, `approval_gate` compared dollars Claude repeated back: any call
that named a high enough number spent, the same yes could be spent twice,
and the person was shown dollars while the studio bills credits. Now the
quote is credits with the balance before and after, the yes is a token the
server signed over THIS tool and THESE arguments, and a token is spent
once. What each test guards is in its name; the conversations the task
asked for as evals are the last block (approve then retry, change the
model after the yes, an expired quote, a short balance).
"""

import asyncio
import json
import time
import types
from pathlib import Path

import pytest

from src import accounts, db, generative, ledger, mcp_server, pricing, quote_redemptions

SECRET = "test-quote-secret"


@pytest.fixture
def signed(monkeypatch):
    monkeypatch.setenv(pricing.SIGNING_ENV, SECRET)


# --------------------------------------------------------------------------
# the token
# --------------------------------------------------------------------------

ARGS = {"prompt": "a can", "model": "seedream4.5", "aspect": None, "references": [],
        "project_id": None}


def _token(signed_quote):
    return pricing.sign_studio(signed_quote)


def _quote(**kw):
    base = dict(account_id=7, tool="generate_image", provider="fal", args=ARGS, usd=0.04)
    return pricing.studio_quote(**{**base, **kw})


def test_a_studio_token_round_trips_to_what_was_quoted(signed):
    q = _quote()
    back = pricing.verify_studio(_token(q), account_id=7, tool="generate_image", args=ARGS)
    assert back == q
    assert q.credits == ledger.charge_credits(0.04)       # the one conversion holds use


@pytest.mark.parametrize("change, reason", [
    ({"account_id": 8}, "wrong_account"),
    ({"tool": "generate_video"}, "wrong_render"),
    ({"args": {**ARGS, "model": "flux2-pro"}}, "stale_content"),
    ({"args": {**ARGS, "prompt": "a can, closer"}}, "stale_content"),
    ({"args": {**ARGS, "project_id": 3}}, "stale_content"),
])
def test_anything_changed_after_the_yes_is_refused(signed, change, reason):
    token = _token(_quote())
    want = {"account_id": 7, "tool": "generate_image", "args": ARGS, **change}
    with pytest.raises(pricing.QuoteRefused) as e:
        pricing.verify_studio(token, **want)
    assert e.value.reason == reason


def test_an_hour_old_token_has_expired(signed):
    token = _token(_quote(now=int(time.time()) - pricing.QUOTE_TTL - 5))
    with pytest.raises(pricing.QuoteRefused) as e:
        pricing.verify_studio(token, account_id=7, tool="generate_image", args=ARGS)
    assert e.value.reason == "expired"


def test_a_forged_or_foreign_token_is_a_bad_signature(signed, monkeypatch):
    token = _token(_quote())
    for bad in (token[:-3] + "AAA", "zpfq.x.y", "", "sk-something"):
        with pytest.raises(pricing.QuoteRefused) as e:
            pricing.verify_studio(bad, account_id=7, tool="generate_image", args=ARGS)
        assert e.value.reason == "bad_signature"
    monkeypatch.setenv(pricing.SIGNING_ENV, "another-environment")
    with pytest.raises(pricing.QuoteRefused, match="valid"):
        pricing.verify_studio(token, account_id=7, tool="generate_image", args=ARGS)


def test_a_studio_token_never_passes_as_a_shots_price_or_back(signed, monkeypatch):
    studio = _token(_quote(account_id=None))
    shot = {"n": 1, "prompt": "p", "refs": []}
    with pytest.raises(pricing.QuoteRefused) as e:
        pricing.verify(studio, account_id=None, shot=shot, shot_id=1)
    assert e.value.reason == "wrong_render"
    shot_token = pricing.sign(pricing.Quote(
        pricing_version=pricing.PRICING_VERSION, account_id=None, shot_id=1, part=None,
        provider="fal", model="ltx2.3", seconds=6, frame="1080p",
        provider_usd_micros=360_000, credits=87, content_hash="h", line_items=()))
    with pytest.raises(pricing.QuoteRefused) as e:
        pricing.verify_studio(shot_token, account_id=None, tool="generate_image", args=ARGS)
    assert e.value.reason == "wrong_render"


def test_every_token_is_its_own(signed):
    assert _quote().token_id != _quote().token_id


# --------------------------------------------------------------------------
# the gate, without a database (the unowned pool, or a stubbed wallet)
# --------------------------------------------------------------------------

def _gate(token="", account_id=None, usd=0.04, args=ARGS):
    return mcp_server.approval_gate(usd, token, tool="generate_image", args=args,
                                    what="This image", account_id=account_id, dsn=None)


def _wallet(monkeypatch, balance=1000, exempt=False):
    monkeypatch.setattr(ledger, "credit_exempt", lambda a, dsn=None: exempt)
    monkeypatch.setattr(mcp_server, "_balance",
                        lambda a, dsn: balance if a is not None else None)


def test_with_no_signing_secret_it_quotes_but_cannot_be_approved(monkeypatch):
    monkeypatch.delenv(pricing.SIGNING_ENV, raising=False)
    stop, approved, price = _gate()
    assert stop["needs_approval"] and stop["can_approve"] is False and approved is None
    assert price["quote_token"] is None and price["credits"] == ledger.charge_credits(0.04)
    assert pricing.SIGNING_ENV in stop["note"]
    with pytest.raises(mcp_server.Refused, match="signing secret"):
        _gate(token="zpfq.a.b")


def test_a_short_balance_is_a_structured_refusal_with_no_token(monkeypatch, signed):
    _wallet(monkeypatch, balance=5)
    stop, approved, price = _gate(account_id=7)
    assert stop["refused"] == "insufficient_credits" and approved is None
    assert stop["needs"] == ledger.charge_credits(0.04) and stop["available"] == 5
    assert "quote_token" not in price and "top up" in stop["note"]


def test_an_exempt_account_is_quoted_but_not_charged(monkeypatch, signed):
    _wallet(monkeypatch, balance=0, exempt=True)
    stop, _, price = _gate(account_id=7)
    assert stop["can_approve"] and price["charged"] is False
    assert price["balance"] == price["balance_after"] == 0       # nothing moves
    assert "not charged" in stop["note"]
    _, approved, _ = _gate(token=price["quote_token"], account_id=7)
    assert approved.credits == price["credits"]                   # what it would have cost


def test_a_price_that_moved_since_the_yes_is_refused(monkeypatch, signed):
    _, _, price = _gate(account_id=None)
    with pytest.raises(ValueError, match="stale_content: the price changed"):
        _gate(token=price["quote_token"], usd=0.08)


# --------------------------------------------------------------------------
# single use (src/quote_redemptions.py)
# --------------------------------------------------------------------------

@pytest.fixture
def owned(pg):
    accounts.seed("mike@example.com", dsn=pg)
    quote_redemptions.init(pg)
    with db.connect(pg) as conn:
        account_id = int(conn.execute("SELECT MIN(id) AS id FROM accounts").fetchone()["id"])
    return {"dsn": pg, "account_id": account_id}


def test_a_token_is_claimed_once(owned):
    dsn, acct = owned["dsn"], owned["account_id"]
    assert quote_redemptions.claim("t1", acct, tool="generate_image", credits=10, dsn=dsn) is None
    quote_redemptions.record("t1", acct, {"job_id": 41, "status": "running"}, dsn=dsn)
    again = quote_redemptions.claim("t1", acct, tool="generate_image", credits=10, dsn=dsn)
    assert again["job_id"] == 41 and again["response"]["status"] == "running"


def test_a_claim_whose_work_never_started_is_given_back(owned):
    dsn, acct = owned["dsn"], owned["account_id"]
    assert quote_redemptions.claim("t2", acct, tool="generate_image", dsn=dsn) is None
    quote_redemptions.forget("t2", acct, dsn=dsn)
    assert quote_redemptions.claim("t2", acct, tool="generate_image", dsn=dsn) is None


def test_another_accounts_redemption_says_nothing_about_it(owned):
    dsn, acct = owned["dsn"], owned["account_id"]
    quote_redemptions.claim("t3", acct, tool="generate_image", dsn=dsn)
    quote_redemptions.record("t3", acct, {"job_id": 7, "secret": "theirs"}, dsn=dsn)
    other = quote_redemptions.claim("t3", None, tool="generate_image", dsn=dsn)
    assert other["response"] is None and other["job_id"] is None


def test_start_approved_starts_once_and_keeps_a_refused_token_unspent(owned, monkeypatch, signed):
    dsn, acct = owned["dsn"], owned["account_id"]
    wallet = {"balance": 5}
    monkeypatch.setattr(ledger, "credit_exempt", lambda a, dsn=None: False)
    monkeypatch.setattr(mcp_server, "_balance", lambda a, dsn: wallet["balance"])
    ran = []

    def fn(dry_run=False, **args):
        stop, approved, price = mcp_server.approval_gate(
            0.04, args["quote_token"], tool="generate_image", args=ARGS, what="This image",
            account_id=args["account_id"], dsn=args["dsn"])
        if stop is not None:
            return {**stop, "quote": price}
        if dry_run:
            return {"ok": True, "dry_run": True, "quote": price, "approved": approved}
        ran.append(approved.credits)
        return {"ok": True}

    wallet["balance"] = 1000
    token = fn(quote_token="", account_id=acct, dsn=dsn)["quote"]["quote_token"]
    wallet["balance"] = 5                     # spent elsewhere between the quote and the yes
    args = {"quote_token": token, "account_id": acct, "dsn": dsn}
    starts = []

    def start():
        starts.append(1)
        return {"job_id": 41, "status": "running"}

    short = mcp_server.start_approved(fn, args, start)
    assert short["refused"] == "insufficient_credits" and starts == []
    wallet["balance"] = 1000                  # topped up: the same yes still works
    first = mcp_server.start_approved(fn, args, start)
    second = mcp_server.start_approved(fn, args, start)
    assert first["job_id"] == second["job_id"] == 41 and starts == [1]
    assert second["already_used"] is True and "Nothing new" in second["note"]


def test_a_job_that_could_not_start_leaves_the_token_usable(owned, monkeypatch, signed):
    dsn = owned["dsn"]
    monkeypatch.setattr(ledger, "credit_exempt", lambda a, dsn=None: True)

    def fn(dry_run=False, **args):
        stop, approved, price = mcp_server.approval_gate(
            0.04, args["quote_token"], tool="generate_image", args=ARGS, what="x",
            account_id=None, dsn=dsn)
        if stop is not None:
            return {**stop, "quote": price}
        return {"ok": True, "quote": price, "approved": approved}

    token = fn(quote_token="")["quote"]["quote_token"]

    def broken():
        raise RuntimeError("registry down")

    with pytest.raises(RuntimeError):
        mcp_server.start_approved(fn, {"quote_token": token, "dsn": dsn}, broken)
    out = mcp_server.start_approved(fn, {"quote_token": token, "dsn": dsn},
                                    lambda: {"job_id": 9, "status": "running"})
    assert out["job_id"] == 9


# --------------------------------------------------------------------------
# the conversations (the task's evals): through the server, the real
# ledger, the real image door -- only fal's HTTP call is stood in for
# --------------------------------------------------------------------------

@pytest.fixture
def funded(pg, monkeypatch):
    from src import fal, preprod, render_assets
    monkeypatch.setenv("DATABASE_URL", pg)
    generative.init(pg)
    preprod.init(pg)
    accounts.seed("mike@example.com", dsn=pg)
    ledger.init(pg)
    render_assets.init(pg)
    quote_redemptions.init(pg)
    with db.connect(pg) as conn:
        account_id = int(conn.execute("SELECT MIN(id) AS id FROM accounts").fetchone()["id"])
    ledger.grant(account_id, 1000, "purchase", dsn=pg)
    calls = []

    def fake_image(prompt, out_path, **kw):
        calls.append(prompt)
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_bytes(b"\xff\xd8 jpeg")

    monkeypatch.setattr(fal, "generate_image", fake_image)
    monkeypatch.setattr(fal, "_publish", lambda path, ctype, acct: "https://r2/still.jpg")
    monkeypatch.setattr(render_assets, "_ingest",
                        lambda *a, **k: {"ok": True, "chunks": 1, "error": None})
    started = []

    def start_job(kind, label, fn, cancellable=False, account_id=None):
        started.append(label)
        result = fn({})            # inline: the job's body, in this thread
        return {"id": 40 + len(started), "status": "done", "result": result}

    server = mcp_server.build_server(dsn=pg, surface="studio", start_job=start_job,
                                     job_status=lambda i, account_id=None: None,
                                     account_id=account_id)
    return types.SimpleNamespace(dsn=pg, account_id=account_id, server=server,
                                 fal_calls=calls, started=started)


def _call(server, tool, args):
    out = asyncio.run(server.call_tool(tool, args))
    return json.loads(out.content[0].text)


def _balance(w):
    return ledger.available(w.account_id, dsn=w.dsn)


IMAGE = {"prompt": "a dented can on wet tile", "model": "seedream4.5", "aspect": "4:5"}


def test_approve_then_retry_charges_once(funded, signed):
    from src import fal
    q = _call(funded.server, "generate_image", IMAGE)["quote"]
    credits = ledger.charge_credits(fal.image_usd("seedream4.5", "4:5"))
    assert q["credits"] == credits and q["balance"] == 1000
    assert q["balance_after"] == 1000 - credits
    assert funded.fal_calls == [] and _balance(funded) == 1000      # a quote spends nothing

    first = _call(funded.server, "generate_image", {**IMAGE, "quote_token": q["quote_token"]})
    assert first["job_id"] == 41 and funded.fal_calls == [IMAGE["prompt"]]
    assert _balance(funded) == 1000 - credits                       # held and settled, as quoted

    retry = _call(funded.server, "generate_image", {**IMAGE, "quote_token": q["quote_token"]})
    assert retry["job_id"] == 41 and retry["already_used"] is True
    assert len(funded.fal_calls) == 1 and _balance(funded) == 1000 - credits
    assert funded.started == ["image seedream4.5"]


def test_changing_the_model_after_the_yes_is_refused(funded, signed):
    from mcp.server.mcpserver.exceptions import ToolError
    q = _call(funded.server, "generate_image", IMAGE)["quote"]
    with pytest.raises(ToolError, match="stale_content"):
        _call(funded.server, "generate_image",
              {**IMAGE, "model": "flux2-pro", "quote_token": q["quote_token"]})
    assert funded.fal_calls == [] and funded.started == [] and _balance(funded) == 1000


def test_an_expired_quote_is_refused_and_says_to_requote(funded, signed, monkeypatch):
    from mcp.server.mcpserver.exceptions import ToolError
    q = _call(funded.server, "generate_image", IMAGE)["quote"]
    later = time.time() + pricing.QUOTE_TTL + 60
    monkeypatch.setattr(pricing, "time", types.SimpleNamespace(time=lambda: later))
    with pytest.raises(ToolError, match="expired.*WITHOUT quote_token"):
        _call(funded.server, "generate_image", {**IMAGE, "quote_token": q["quote_token"]})
    assert funded.fal_calls == [] and _balance(funded) == 1000


def test_too_few_credits_stops_with_the_numbers(funded, signed):
    q = _call(funded.server, "generate_image", IMAGE)["quote"]
    ledger.hold(funded.account_id, 995, ref="elsewhere", provider="fal",
                dsn=funded.dsn)                   # spent down to 5 elsewhere since
    out = _call(funded.server, "generate_image", {**IMAGE, "quote_token": q["quote_token"]})
    assert out["ok"] is False and out["refused"] == "insufficient_credits"
    assert out["needs"] == q["credits"] and out["available"] == 5
    assert funded.fal_calls == [] and funded.started == []
    fresh = _call(funded.server, "generate_image", IMAGE)
    assert fresh["refused"] == "insufficient_credits" and "quote_token" not in fresh["quote"]
