"""
A render that dies at the provider still leaves a generations row
(BACKLOG #18, found 2026-09-18 on the live site: approving #361 on
Higgsfield answered 200, the submit came back `HTTP Error 423: Locked`,
and the newest generations row was still the previous day's. The only
record was the in-process jobs registry, which a restart clears.)

What each test guards, in the video adapter (fal, the only one since
2026-09-26) and through every never-raises edge that spends:
- a submit that raises leaves ONE row: no output_path (the shape
  ledger.reap already reads as "found and failed"), the error on it,
  cost 0, the key_source and the hold's ledger_ref beside it
- the hold is RELEASED and nothing is SETTLED -- the customer pays nothing
- a refusal from BEFORE the submit (an empty balance, the spend gate) is
  not an attempt and leaves no row
- generate_candidates' hold ref is unique per attempt: `cand1.mp4`
  repeats every run and ledger.hold is idempotent on the ref, so the
  second run was handed the first's settled hold and rendered for nothing
"""

import json
import urllib.error

import pytest

from src import accounts, db, fal, generative, ledger, preprod

PROMPT = "a man walks into a rain-lit bar and does not look back " * 2
LOCKED = "HTTP Error 423: Locked"


def _locked(*a, **k):
    raise urllib.error.HTTPError("https://provider.test/submit", 423, "Locked", {}, None)


ADAPTERS = {
    "fal": (fal, {"http": _locked}, fal.model_spec(fal.DEFAULT_MODEL)["platform"]),
}


@pytest.fixture
def studio(pg, monkeypatch, tmp_path):
    """A funded, NOT exempt account rendering on the installation's keys,
    so the ledger is its business and a hold is really taken."""
    monkeypatch.setenv("DATABASE_URL", pg)
    for name in ("FAL_KEY", "GEMINI_API_KEY"):
        monkeypatch.setenv(name, "OPERATOR-SECRET")
    generative.init(pg)
    preprod.init(pg)
    accounts.seed("mike@example.com", dsn=pg)
    ledger.init(pg)
    with db.connect(pg) as conn:
        account_id = int(conn.execute(
            "SELECT id FROM accounts WHERE slug = 'zeropage'").fetchone()["id"])
    ledger.grant(account_id, 100000, "purchase", dsn=pg)
    monkeypatch.setattr(fal, "RENDER_DIR", tmp_path / "renders")
    return {"dsn": pg, "account_id": account_id, "funded": 100000}


def _rows(studio):
    with db.connect(studio["dsn"]) as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM generations ORDER BY id").fetchall()]


def _kinds(studio):
    return [e["kind"] for e in ledger.entries(studio["account_id"], studio["dsn"])]


def _assert_failed_and_refunded(studio, tool):
    rows = _rows(studio)
    assert len(rows) == 1, rows                          # the attempt is a row
    row = rows[0]
    assert row["tool"] == tool
    assert row["account_id"] == studio["account_id"]
    assert row["output_path"] is None                   # what reap reads as failed
    assert row["reject_reason"] is None                 # not a person's verdict
    assert row["cost_usd"] == 0                         # never NULL: NULL is a free lane
    assert row["kept"] in (0, None)
    assert "423" in row["notes"]
    params = json.loads(row["params_json"])
    assert params["failed"] is True and "423" in params["error"]
    assert params["key_source"]
    kinds = _kinds(studio)
    assert "hold" in kinds and "release" in kinds
    assert "settle" not in kinds                        # nothing was charged
    assert ledger.outstanding(studio["account_id"], studio["dsn"]) == 0
    assert ledger.available(studio["account_id"], studio["dsn"]) == studio["funded"]
    # the row names the hold it would have paid for
    holds = [e for e in ledger.entries(studio["account_id"], studio["dsn"])
             if e["kind"] == "hold"]
    assert params[ledger.GENERATION_REF_KEY] == holds[0]["ref"]


def _concept(studio):
    return preprod.save_concept(
        {"title": "The Crimson Descent", "hook": "h", "logline": "l",
         "shots": [{"n": 1, "type": "BROLL", "source": "AI", "tool": "KLING",
                    "prompt": PROMPT, "refs": ["/refs/seed.jpg"]}]},
        "antihero", dsn=studio["dsn"], account_id=studio["account_id"])


@pytest.mark.parametrize("name", sorted(ADAPTERS))
def test_a_submit_that_raises_leaves_a_row_from_the_queue_path(studio, name):
    """generate_for_shot is what Queue approve calls -- the #361 path."""
    module, seam, tool = ADAPTERS[name]
    concept_id = _concept(studio)
    result = module.generate_for_shot(
        concept_id, 1, db_path=studio["dsn"], approved=True,
        account_id=studio["account_id"], **seam)
    assert result["ok"] is False and "423" in result["error"]
    _assert_failed_and_refunded(studio, tool)
    params = json.loads(_rows(studio)[0]["params_json"])
    assert params["concept_id"] == concept_id and params["shot_n"] == 1
    concept = preprod.get_concept(concept_id, dsn=studio["dsn"],
                                  account_id=studio["account_id"])
    assert not concept["shots"][0].get("media_url")


@pytest.mark.parametrize("name", sorted(ADAPTERS))
def test_a_submit_that_raises_leaves_a_row_from_the_director_path(studio, name):
    module, seam, tool = ADAPTERS[name]
    result = module.generate_from_prompt(
        PROMPT, db_path=studio["dsn"], approved=True,
        account_id=studio["account_id"], **seam)
    assert result["ok"] is False and "423" in result["error"]
    _assert_failed_and_refunded(studio, tool)


@pytest.mark.parametrize("name", sorted(ADAPTERS))
def test_a_submit_that_raises_leaves_a_row_from_the_nightly_path(studio, name, tmp_path):
    module, seam, tool = ADAPTERS[name]
    result = module.generate_candidates(
        PROMPT, tmp_path / "shot1", n=1, db_path=studio["dsn"], approved=True,
        account_id=studio["account_id"], **seam)
    assert result["ok"] is False and "423" in result["error"]
    _assert_failed_and_refunded(studio, tool)


@pytest.mark.parametrize("name", sorted(ADAPTERS))
def test_a_refusal_before_the_submit_is_not_an_attempt(studio, name, monkeypatch):
    """The spend gate raises inside generate_video BEFORE the hold and the
    submit. Nothing reached the provider, so there is nothing to record."""
    module, seam, _tool = ADAPTERS[name]
    monkeypatch.delenv(module.SPEND_ENV, raising=False)
    concept_id = _concept(studio)
    result = module.generate_for_shot(
        concept_id, 1, db_path=studio["dsn"], approved=False,
        account_id=studio["account_id"], **seam)
    assert result["ok"] is False
    assert _rows(studio) == []
    assert _kinds(studio) == ["grant"]


def test_an_empty_balance_is_not_an_attempt(studio):
    with db.connect(studio["dsn"]) as conn:
        conn.execute("UPDATE credit_lots SET credits_remaining = 0")
        conn.execute("DELETE FROM credit_entries")
    result = fal.generate_from_prompt(
        PROMPT, db_path=studio["dsn"], approved=True,
        account_id=studio["account_id"], http=_locked)
    assert result["ok"] is False and "out of credits" in result["error"]
    assert _rows(studio) == []


def test_recording_the_failure_can_never_replace_the_providers_error(studio, monkeypatch):
    """record_failure runs inside an except. If IT fails, the caller must
    still hear about the 423, not about bookkeeping."""
    def broken(*a, **k):
        raise RuntimeError("the database is on fire")
    monkeypatch.setattr(generative, "record_generation", broken)
    result = fal.generate_from_prompt(
        PROMPT, db_path=studio["dsn"], approved=True,
        account_id=studio["account_id"], http=_locked)
    assert result["ok"] is False and "423" in result["error"]
    assert "release" in _kinds(studio)


def test_a_failed_row_counts_against_the_daily_cap_like_any_attempt(studio):
    fal.generate_from_prompt(
        PROMPT, db_path=studio["dsn"], approved=True,
        account_id=studio["account_id"], http=_locked)
    assert fal.generations_today(
        db_path=studio["dsn"], account_id=studio["account_id"]) == 1


@pytest.mark.parametrize("name", sorted(ADAPTERS))
def test_two_nights_of_candidates_take_two_holds(studio, name, tmp_path):
    """`cand1.mp4` in `shot1/` is the same name every run, and ledger.hold
    hands a repeated ref its first hold back. The ref must not be the name."""
    module, seam, _tool = ADAPTERS[name]
    for _night in range(2):
        module.generate_candidates(
            PROMPT, tmp_path / "shot1", n=1, db_path=studio["dsn"], approved=True,
            account_id=studio["account_id"], **seam)
    holds = [e for e in ledger.entries(studio["account_id"], studio["dsn"])
             if e["kind"] == "hold"]
    assert len({e["ref"] for e in holds}) == 2
    assert len(_rows(studio)) == 2
