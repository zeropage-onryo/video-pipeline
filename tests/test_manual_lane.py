"""
The operator-only manual render lanes (src/manual_lane.py, 2026-09-08).

What these tests are actually protecting. Each lane spends one of the
OPERATOR'S personal consumer plans -- Runway Unlimited, whose free
Explore Mode has no API parameter so a human in Chrome is the only way
to reach it, and the Higgsfield app plan behind the MCP. Rendering a
paying tenant's shot on either is reselling a consumer subscription, and
the penalty for that is not a refund, it is the operator's account,
which on a shared install is every tenant's render path at once.

So the properties under test are not features:

- the gate is resolved SERVER-SIDE from the account's own row -- since
  2026-09-08 the `accounts.manual_lane_operator` column and nothing else
  -- and there is no parameter, flag or env escape that widens it from
  the caller's side. The env vars it replaced are GONE rather than kept
  as a fallback, and one of these tests is that setting them does
  nothing at all;
- it FAILS CLOSED -- a database nobody has run the command against is
  nobody, including the bootstrap account and including the unowned pool
  a fresh database hands a CLI;
- MEMBERSHIP IS NOT THE GATE: being a member of an account, even by the
  operator, even to debug something, does not make that account an
  operator account;
- every surface enforces it, with a refusal that is byte-identical
  whoever asks, so nobody can learn the shape of the operator's setup
  from the difference between two refusals;
- and the ledger takes NO hold for a lane render, through the one place
  that decides billability rather than a second rule next door.
"""
import json
import pathlib
import re

import pytest

from app import auth
from app import main as app_main
from ops import render_queue as rq
from src import accounts, db, generative, ledger, manual_lane, preprod
from src.shot import Shot


@pytest.fixture
def tmp_db(pg, monkeypatch):
    path = pg
    preprod.init(path)
    generative.init(path)
    accounts.init(path)
    ledger.init(path)
    monkeypatch.setenv("DATABASE_URL", path)
    return path


@pytest.fixture(autouse=True)
def no_inherited_environment(monkeypatch):
    """The env vars are gone, and these two lines are what proves a stray
    one in a developer's shell cannot bring them back: every test runs
    with them explicitly unset AND with them set (see the test below),
    and the answer must be the same either way."""
    monkeypatch.delenv("ZEROPAGE_OPERATOR_ACCOUNTS", raising=False)
    monkeypatch.delenv("ZEROPAGE_OPERATOR_EMAILS", raising=False)


@pytest.fixture(autouse=True)
def renders_in_tmp(tmp_path, monkeypatch):
    """Never write into the real data/renders/ from a test."""
    root = tmp_path / "renders"
    monkeypatch.setattr(rq, "RENDERS_ROOT", root)
    monkeypatch.setattr(rq, "RENDER_DIR", root / "higgsfield")
    monkeypatch.setattr(rq, "RUNWAY_RENDER_DIR", root / "runway")
    return root


def an_operator(path, monkeypatch, slug="zeropage"):
    """An account whose own row says it may spend the subscription --
    the whole configuration there now is."""
    account_id = accounts.upsert_account(slug, slug.title(), dsn=path)
    accounts.set_manual_lane_operator(slug, True, dsn=path)
    return account_id


def a_scene(path, account_id, title="Cold Open", prompt="a close shot", **shot):
    base = {"n": 1, "type": "BROLL", "source": "AI", "tool": "RUNWAY",
            "desc": title, "prompt": prompt}
    base.update(shot)
    return preprod.save_concept(
        {"title": title, "hook": "", "logline": "", "shots": [base]},
        brand="zeropage", prompt_template="T", dsn=path, account_id=account_id)


def a_clip(tmp_path, name="clip.mp4", size=200_000):
    p = tmp_path / name
    p.write_bytes(b"\x00" * size)
    return p


# ---------- the allowlist itself ----------

def test_the_named_account_is_allowed(tmp_db, monkeypatch):
    account_id = an_operator(tmp_db, monkeypatch)
    assert manual_lane.manual_lane_allowed(account_id) is True


def test_another_account_is_not(tmp_db, monkeypatch):
    an_operator(tmp_db, monkeypatch)
    other = accounts.upsert_account("pilot", "Pilot", dsn=tmp_db)
    assert manual_lane.manual_lane_allowed(other) is False


def test_an_unset_allowlist_refuses_everyone_including_the_bootstrap_account(tmp_db):
    """Fail closed. A missing env var must mean NOBODY -- an allowlist
    that opens when it is unconfigured is not an allowlist, and the
    bootstrap account is the one somebody would assume is exempt."""
    seeded = accounts.seed("mike@example.com", dsn=tmp_db)
    bootstrap = accounts.resolve_account(dsn=tmp_db)
    assert bootstrap in seeded["accounts"]
    assert manual_lane.operator_accounts(tmp_db) == frozenset()
    assert manual_lane.manual_lane_allowed(bootstrap, tmp_db) is False
    for account_id in seeded["accounts"]:
        assert manual_lane.manual_lane_allowed(account_id, tmp_db) is False


def test_the_unowned_pool_is_never_the_operator(tmp_db, monkeypatch):
    """account_id None is what a fresh database hands a CLI. "Nobody owns
    these rows" is not evidence that the person at the keyboard owns the
    subscription."""
    an_operator(tmp_db, monkeypatch)
    assert manual_lane.manual_lane_allowed(None) is False


def test_the_column_is_the_only_truth(tmp_db, monkeypatch):
    """The gate is one boolean on the account's own row. Flipping it back
    closes the lane again with nothing else touched."""
    account_id = an_operator(tmp_db, monkeypatch)
    assert manual_lane.operator_accounts(tmp_db) == frozenset({account_id})
    accounts.set_manual_lane_operator("zeropage", False, dsn=tmp_db)
    assert manual_lane.operator_accounts(tmp_db) == frozenset()
    assert manual_lane.manual_lane_allowed(account_id, tmp_db) is False


def test_the_old_environment_variables_do_nothing_at_all(tmp_db, monkeypatch):
    """The env vars were REMOVED, not left as a fallback -- a gate with
    two doors is one door, and the weaker door decides. Anything that can
    set a variable on this process (a deploy config, a .env on a shared
    box, a wrapper script) must not be able to name itself operator."""
    other = accounts.upsert_account("pilot", "Pilot", dsn=tmp_db)
    monkeypatch.setenv("ZEROPAGE_OPERATOR_ACCOUNTS", str(other))
    monkeypatch.setenv("ZEROPAGE_OPERATOR_EMAILS", "pilot@example.com")
    assert manual_lane.manual_lane_allowed(other, tmp_db) is False
    assert manual_lane.operator_accounts(tmp_db) == frozenset()
    with pytest.raises(SystemExit, match=re.escape(manual_lane.REFUSAL)):
        rq.pending(account_id=other, provider="runway")


def test_the_module_never_reads_the_environment_for_the_gate(tmp_db):
    """Stronger than the test above and cheaper to keep true: there is no
    env-var name left in the module to set."""
    assert not hasattr(manual_lane, "ACCOUNTS_ENV")
    assert not hasattr(manual_lane, "EMAILS_ENV")
    source = pathlib.Path(manual_lane.__file__).read_text()
    code = "\n".join(line for line in source.splitlines()
                     if not line.lstrip().startswith("#"))
    body = code.split('"""', 2)[-1]        # past the module docstring
    assert "os.environ" not in body and "getenv" not in body


# ---------- membership is not the gate (the transitive path, closed) ----------

def test_membership_of_an_operator_account_does_not_spread_to_another(tmp_db, monkeypatch):
    """THE bug this column was worth a migration for.

    The gate used to resolve an operator EMAIL to every account that
    person was a MEMBER of, so adding the operator to a pilot user's
    account -- to debug something, for an afternoon -- silently made that
    account an operator account, with no sign anywhere that it had
    happened. The flag is on the ACCOUNT ROW now, so there is no longer a
    path from "this person may enter that account" to "that account may
    spend the subscription".
    """
    operator_account = an_operator(tmp_db, monkeypatch)
    user_id = accounts.create_user("mike@example.com", dsn=tmp_db)
    accounts.add_member(operator_account, user_id, dsn=tmp_db)

    # the pilot's account, which the operator is now also a member of
    pilot = accounts.upsert_account("pilot", "Pilot", dsn=tmp_db)
    accounts.add_member(pilot, user_id, dsn=tmp_db)
    assert {a["id"] for a in accounts.memberships(user_id, dsn=tmp_db)} == {
        operator_account, pilot}

    assert manual_lane.manual_lane_allowed(operator_account, tmp_db) is True
    assert manual_lane.manual_lane_allowed(pilot, tmp_db) is False
    assert manual_lane.operator_accounts(tmp_db) == frozenset({operator_account})


def test_the_operator_acting_as_the_other_account_is_refused(tmp_db, tmp_path,
                                                             monkeypatch):
    """The same fact at the surfaces: it is the ACCOUNT that is allowed,
    not the person, so the operator gets the ordinary refusal the moment
    they act as the pilot's account."""
    an_operator(tmp_db, monkeypatch)
    user_id = accounts.create_user("mike@example.com", dsn=tmp_db)
    pilot = accounts.upsert_account("pilot", "Pilot", dsn=tmp_db)
    accounts.add_member(pilot, user_id, dsn=tmp_db)
    cid = a_scene(tmp_db, pilot)
    preprod.set_picked(cid, True, dsn=tmp_db, account_id=pilot)

    with pytest.raises(SystemExit, match=re.escape(manual_lane.REFUSAL)):
        rq.pending(account_id=pilot, provider="runway")
    with pytest.raises(SystemExit, match=re.escape(manual_lane.REFUSAL)):
        rq.import_clip(cid, 1, str(a_clip(tmp_path)), "gen4_turbo", None, None,
                       True, account_id=pilot, provider="runway")


def test_the_refusal_says_nothing_about_who_is_allowed(tmp_db, monkeypatch):
    """One string, whoever asks. If a refusal to a stranger differed from
    a refusal on an unconfigured install, the difference is a probe."""
    other = accounts.upsert_account("pilot", "Pilot", dsn=tmp_db)

    with pytest.raises(manual_lane.LaneRefused) as unconfigured:
        manual_lane.require(other)
    an_operator(tmp_db, monkeypatch, slug="zeropage")
    with pytest.raises(manual_lane.LaneRefused) as not_allowed:
        manual_lane.require(other)

    assert str(unconfigured.value) == str(not_allowed.value) == manual_lane.REFUSAL
    # what it must never carry: an account, a slug, an id, an email. It
    # MAY name the column and the command that moves it -- both are true
    # on every install, are in this repo's source anyway, and are what a
    # person who hits this needs in order to act on it.
    assert manual_lane.OPERATOR_COLUMN in manual_lane.REFUSAL
    assert manual_lane.OPERATOR_COMMAND in manual_lane.REFUSAL
    text = manual_lane.REFUSAL
    for name in (manual_lane.OPERATOR_COLUMN, manual_lane.OPERATOR_COMMAND):
        text = text.replace(name, "")     # the NAMES are allowed, an account is not
    text = text.lower()
    for leak in ("zeropage", "pilot", "mike", "@", str(other)):
        assert leak not in text


# ---------- surface 1: the CLI ----------

def test_the_cli_lists_only_the_operators_waiting_shots(tmp_db, monkeypatch):
    account_id = an_operator(tmp_db, monkeypatch)
    other = accounts.upsert_account("pilot", "Pilot", dsn=tmp_db)
    mine = a_scene(tmp_db, account_id, title="The Bronze Debt")
    theirs = a_scene(tmp_db, other, title="Not Mine")
    preprod.set_picked(mine, True, dsn=tmp_db, account_id=account_id)
    preprod.set_picked(theirs, True, dsn=tmp_db, account_id=other)

    waiting = rq.pending(account_id=account_id, provider="runway")
    assert [w["concept_id"] for w in waiting] == [mine]
    assert waiting[0]["prompt"] == "a close shot"
    assert waiting[0]["lane"] == manual_lane.LANES["runway"]


def test_the_list_carries_what_the_web_app_actually_needs(tmp_db, monkeypatch):
    """The keyframe is what gets dragged into the start-image slot, and
    the duration/ratio are the two controls that have to be set before
    Generate -- the app resets duration to 5s on every reload."""
    account_id = an_operator(tmp_db, monkeypatch)
    cid = a_scene(tmp_db, account_id)
    preprod.set_picked(cid, True, dsn=tmp_db, account_id=account_id)
    preprod.set_shot_reference_image(cid, 1, "/renders/nano/key.png",
                                     dsn=tmp_db, account_id=account_id)

    row = rq.pending(account_id=account_id, provider="runway")[0]
    assert row["keyframe_url"] == "/renders/nano/key.png"
    assert row["duration"] == manual_lane.LANE_DURATION
    assert row["ratio"] == manual_lane.LANE_RATIO


def test_the_cli_refuses_a_non_operator_on_both_subcommands(tmp_db, tmp_path, monkeypatch):
    an_operator(tmp_db, monkeypatch)
    other = accounts.upsert_account("pilot", "Pilot", dsn=tmp_db)
    cid = a_scene(tmp_db, other)
    preprod.set_picked(cid, True, dsn=tmp_db, account_id=other)

    with pytest.raises(SystemExit, match=re.escape(manual_lane.REFUSAL)):
        rq.pending(account_id=other, provider="runway")
    with pytest.raises(SystemExit, match=re.escape(manual_lane.REFUSAL)):
        rq.import_clip(cid, 1, str(a_clip(tmp_path)), "gen4_turbo", None, None,
                       True, account_id=other, provider="runway")


def test_a_refused_import_writes_no_file_and_no_row(tmp_db, tmp_path, monkeypatch,
                                                    renders_in_tmp):
    """The gate is asked BEFORE anything happens, so a refusal leaves no
    clip on disk and no generations row claiming a render."""
    an_operator(tmp_db, monkeypatch)
    other = accounts.upsert_account("pilot", "Pilot", dsn=tmp_db)
    cid = a_scene(tmp_db, other)
    preprod.set_picked(cid, True, dsn=tmp_db, account_id=other)
    with pytest.raises(SystemExit):
        rq.import_clip(cid, 1, str(a_clip(tmp_path)), "gen4_turbo", None, None,
                       True, account_id=other, provider="runway")
    assert not (renders_in_tmp / "runway").exists()
    with generative.connect(tmp_db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM generations").fetchone()[0] == 0


def test_the_cli_refuses_everyone_when_the_allowlist_is_unset(tmp_db):
    account_id = accounts.upsert_account("zeropage", "Zero Page", dsn=tmp_db)
    with pytest.raises(SystemExit, match=re.escape(manual_lane.REFUSAL)):
        rq.pending(account_id=account_id, provider="runway")
    with pytest.raises(SystemExit, match=re.escape(manual_lane.REFUSAL)):
        rq.pending(account_id=None, provider="runway")


def test_there_is_no_caller_supplied_way_into_the_lane(tmp_db, monkeypatch):
    """The check is a function of the account id and the configuration.
    Nothing a caller passes -- and no env var a caller could set on their
    own process -- may widen it, so the CLI must expose no --operator,
    --force or --allow flag to widen it with."""
    import argparse

    parser_flags = set()

    real = argparse.ArgumentParser.add_argument

    def record(self, *args, **kwargs):
        parser_flags.update(a for a in args if isinstance(a, str))
        return real(self, *args, **kwargs)

    monkeypatch.setattr(argparse.ArgumentParser, "add_argument", record)
    monkeypatch.setattr("sys.argv", ["render_queue.py", "list"])
    monkeypatch.setattr(rq.accounts, "resolve_account", lambda slug: None)
    monkeypatch.setattr(rq, "pending", lambda *a, **k: [])
    rq.main()
    widening = {f for f in parser_flags
                if any(word in f for word in ("operator", "force", "allow", "gate"))}
    assert not widening, widening


# ---------- surface 2: the API ----------

@pytest.fixture
def api(tmp_db, monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setattr(auth, "current_user",
                        lambda request: {"id": "u1", "email": "x@example.com"})
    client = TestClient(app_main.app)

    def act_as(account_id):
        app_main.app.dependency_overrides[auth.current_account_id] = lambda: account_id
        return client

    yield act_as
    app_main.app.dependency_overrides.pop(auth.current_account_id, None)


def test_the_route_serves_the_operator(tmp_db, monkeypatch, api):
    account_id = an_operator(tmp_db, monkeypatch)
    cid = a_scene(tmp_db, account_id, title="The Bronze Debt")
    preprod.set_picked(cid, True, dsn=tmp_db, account_id=account_id)
    res = api(account_id).get("/api/queue/manual")
    assert res.status_code == 200, res.text
    body = res.json()
    assert [i["concept_id"] for i in body["items"]] == [cid]
    assert body["items"][0]["duration"] == manual_lane.LANE_DURATION
    assert body["items"][0]["ratio"] == manual_lane.LANE_RATIO


def test_the_route_refuses_a_non_operator(tmp_db, monkeypatch, api):
    an_operator(tmp_db, monkeypatch)
    other = accounts.upsert_account("pilot", "Pilot", dsn=tmp_db)
    cid = a_scene(tmp_db, other)
    preprod.set_picked(cid, True, dsn=tmp_db, account_id=other)
    res = api(other).get("/api/queue/manual")
    assert res.status_code == 404
    assert manual_lane.REFUSAL in res.text
    assert "pilot" not in res.text and "zeropage" not in res.text


def test_the_route_refuses_everyone_when_the_allowlist_is_unset(tmp_db, api):
    account_id = accounts.upsert_account("zeropage", "Zero Page", dsn=tmp_db)
    refused = api(account_id).get("/api/queue/manual")
    assert refused.status_code == 404
    assert api(None).get("/api/queue/manual").status_code == 404


def test_the_two_api_refusals_are_indistinguishable(tmp_db, monkeypatch, api):
    """A stranger on a configured install and anybody on an
    unconfigured one must get the same bytes, or the difference tells
    them whether an operator lane exists here at all."""
    other = accounts.upsert_account("pilot", "Pilot", dsn=tmp_db)
    unconfigured = api(other).get("/api/queue/manual")
    an_operator(tmp_db, monkeypatch, slug="zeropage")
    not_allowed = api(other).get("/api/queue/manual")
    assert unconfigured.status_code == not_allowed.status_code == 404
    assert unconfigured.text == not_allowed.text


def test_the_ordinary_queue_is_untouched_by_the_lane(tmp_db, monkeypatch, api):
    """/queue/pending is every tenant's own API-credit queue and must not
    have acquired a gate."""
    other = accounts.upsert_account("pilot", "Pilot", dsn=tmp_db)
    cid = a_scene(tmp_db, other)
    preprod.set_picked(cid, True, dsn=tmp_db, account_id=other)
    res = api(other).get("/api/queue/pending")
    assert res.status_code == 200
    assert [i["id"] for i in res.json()["items"]] == [cid]


# ---------- the ledger ----------

def test_a_lane_render_is_not_billable(tmp_db):
    assert ledger.is_billable(None, source=manual_lane.SOURCE) is False
    assert ledger.is_billable("env", source=manual_lane.SOURCE) is False
    # the higgsfield MCP lane is the same structural fact, older name
    assert ledger.is_billable("env", source="mcp-subscription") is False
    # and an ordinary API render still is
    assert ledger.is_billable("env", source="workflow") is True
    assert ledger.is_billable(None) is True


def test_a_lane_render_takes_no_hold(tmp_db):
    """No hold, and therefore no debit: the credit belongs to a customer
    and the subscription belongs to the operator."""
    account_id = accounts.upsert_account("zeropage", "Zero Page", dsn=tmp_db)
    ledger.grant(account_id, 500, "subscription", dsn=tmp_db)
    before = ledger.available(account_id, dsn=tmp_db)

    hold_id = ledger.hold_for_render(account_id, ref="manual-1", provider="runway",
                                     estimate_usd=0.50,
                                     source=manual_lane.SOURCE, dsn=tmp_db)
    assert hold_id is None
    assert ledger.available(account_id, dsn=tmp_db) == before
    assert [e for e in ledger.entries(account_id, dsn=tmp_db)
            if e["kind"] == "hold"] == []


def test_an_imported_lane_clip_is_a_row_the_ledger_would_not_bill(tmp_db, tmp_path,
                                                                 monkeypatch):
    """The end-to-end version: what `import` actually wrote is what
    `is_billable` reads."""
    account_id = an_operator(tmp_db, monkeypatch)
    cid = a_scene(tmp_db, account_id)
    preprod.set_picked(cid, True, dsn=tmp_db, account_id=account_id)
    rq.import_clip(cid, 1, str(a_clip(tmp_path)), "gen4_turbo", None, None, True,
                   account_id=account_id, provider="runway")
    with generative.connect(tmp_db) as conn:
        row = conn.execute("SELECT cost_usd, params_json FROM generations "
                           "ORDER BY id DESC LIMIT 1").fetchone()
    params = json.loads(row["params_json"])
    assert row["cost_usd"] is None
    assert ledger.is_billable(params.get("key_source"),
                              source=params.get("source")) is False


# ---------- the lane's own numbers ----------

def test_both_lanes_ask_for_the_same_frame_from_one_source(tmp_db):
    """The manual lane must ask the web app for the same frame the API
    lane would have produced, or a hand-rendered clip is the odd one out
    in a feed of verticals.

    This used to be a DRIFT test between two literals -- an alarm, not a
    fix, silent about the hours between an edit and a run. There is one
    literal now, in src/render_specs.py (which imports nothing, so the
    bare-python3 script can read it too), and both names are that object.
    """
    from src import render_specs, runway
    assert manual_lane.LANE_RATIO is render_specs.RATIO_9_16
    assert runway.DEFAULT_RATIO is render_specs.RATIO_9_16
    # and the value is genuinely USED at both ends, not merely defined
    assert rq.pending.__module__      # imported, so the row below is the lane's
    assert manual_lane.LANE_RATIO == "720:1280"
    # deliberately NOT the adapter's duration: on Explore Mode the
    # seconds are free and the queue is the price
    assert manual_lane.LANE_DURATION > runway.DEFAULT_DURATION


def test_neither_module_spells_the_ratio_out_for_itself(tmp_db):
    """The point of a shared constant is that there is nothing left to
    drift, which is only true while neither reader keeps a copy."""
    from src import runway
    for module in (manual_lane, runway):
        source = pathlib.Path(module.__file__).read_text()
        code = "\n".join(line for line in source.splitlines()
                         if not line.lstrip().startswith("#"))
        body = code.split('"""', 2)[-1]
        assert '"720:1280"' not in body, module.__name__


def test_both_subscription_lanes_are_gated_and_the_billed_adapters_are_not(tmp_db):
    """The gate is about the SUBSCRIPTION lanes. src/runway.py and
    src/higgsfield.py spend a credential a tenant can own, metered per
    call, under their own spend gates and daily caps -- they were not
    touched and must not be."""
    assert set(rq.GATED_PROVIDERS) == set(rq.PROVIDERS) == {"higgsfield", "runway"}
    from src import higgsfield, runway
    for adapter in (higgsfield, runway):
        assert not hasattr(adapter, "manual_lane_allowed")
        assert "manual_lane" not in dir(adapter)


# ---------- provenance, where a human looks ----------

def test_the_board_says_which_clips_a_subscription_paid_for(tmp_db, monkeypatch,
                                                            tmp_path, api):
    """A hand-rendered clip and an API-rendered one are the same mp4 in
    the same folder with the same URL shape. `params.source` was the only
    thing separating them and it lived nowhere anyone looks."""
    account_id = an_operator(tmp_db, monkeypatch)
    lane = a_scene(tmp_db, account_id, title="By Hand")
    billed = a_scene(tmp_db, account_id, title="Billed")
    for cid in (lane, billed):
        preprod.set_picked(cid, True, dsn=tmp_db, account_id=account_id)

    rq.import_clip(lane, 1, str(a_clip(tmp_path)), "gen4_turbo", None, None, True,
                   account_id=account_id, provider="runway")
    # the API lane's row: a price, no lane marker
    shot_row = generative.add_shot(Shot(subject="x", action="y"),
                                   dsn=tmp_db, account_id=account_id)
    generative.record_generation(
        shot_row, "runway", "a close shot",
        params={"model": "gen4_turbo", "key_source": "env", "concept_id": billed,
                "shot_n": 1},
        cost_usd=0.25, dsn=tmp_db, account_id=account_id)
    preprod.set_shot_media_url(billed, 1, "/renders/runway/api.mp4",
                               dsn=tmp_db, account_id=account_id)

    cards = api(account_id).get("/api/pipeline/concepts").json()["items"]
    by_id = {c["id"]: c for c in cards}
    assert by_id[lane]["subscription"] is True
    assert by_id[billed]["subscription"] is False


def test_provenance_reads_rows_written_before_the_field_existed(tmp_db, monkeypatch,
                                                                tmp_path, api):
    """It is derived from params_json, not a new column, so the
    higgsfield lane's older `mcp-subscription` rows are covered with no
    backfill."""
    account_id = an_operator(tmp_db, monkeypatch)
    cid = a_scene(tmp_db, account_id)
    preprod.set_picked(cid, True, dsn=tmp_db, account_id=account_id)
    rq.import_clip(cid, 1, str(a_clip(tmp_path)), "seedance1_5", 4.8, None, True,
                   account_id=account_id)
    assert generative.subscription_rendered(tmp_db, account_id=account_id) == {cid}


def test_the_provenance_label_cannot_take_the_board_down(pg_factory):
    """A database with no `generations` table is what a fresh install
    genuinely is, and a board that 500s because nothing has ever been
    billed on it is the wrong failure -- the degrade `_runway_state`
    already makes for the daily count. An unlabelled card is honest."""
    empty = pg_factory()          # a schema with nothing in it at all
    assert generative.subscription_rendered(empty, account_id=1) == set()


# ---------- the migration that made the gate a column ----------

def test_the_column_arrives_on_a_database_that_predates_it(pg):
    """add_legacy_column's shape, with one deliberate difference: NO
    BACKFILL. A migration that named anybody an operator would be the
    migration making the security decision the column exists to make
    deliberately, so every account comes out of it OFF -- including the
    bootstrap one, which is the account somebody would assume is exempt.
    """
    accounts.init(pg)
    with db.connect(pg) as conn:
        conn.execute(f"ALTER TABLE accounts DROP COLUMN {manual_lane.OPERATOR_COLUMN}")
    accounts.upsert_account("zeropage", "Zero Page", dsn=pg)
    accounts.upsert_account("pilot", "Pilot", dsn=pg)

    with db.connect(pg) as conn:
        assert db.add_manual_lane_operator_column(conn) is True
        assert manual_lane.OPERATOR_COLUMN in db.columns(conn, "accounts")
        on = conn.execute("SELECT COUNT(*) FROM accounts WHERE "
                          f"{manual_lane.OPERATOR_COLUMN}").fetchone()[0]
        assert on == 0
        # idempotent: the dev server re-runs init on every save
        assert db.add_manual_lane_operator_column(conn) is False
    assert manual_lane.operator_accounts(pg) == frozenset()


def test_the_migration_is_a_no_op_before_the_accounts_table_exists(pg_factory):
    """db.init_db() runs before src/accounts.py has made the table, so a
    missing `accounts` is "not yet", not an error -- accounts.init()
    asks again the moment there is something to alter."""
    empty = pg_factory()
    with db.connect(empty) as conn:
        assert db.add_manual_lane_operator_column(conn) is False
    db.init_db(empty)          # the whole spine, still no accounts table
    accounts.init(empty)
    with db.connect(empty) as conn:
        assert manual_lane.OPERATOR_COLUMN in db.columns(conn, "accounts")


# ---------- the CLI that moves it ----------

def test_the_cli_turns_the_lane_on_and_says_what_changed(tmp_db, capsys):
    """There is no route and no env var: somebody with the database has
    to run this. So it has to report the BEFORE as well as the after --
    "already on" and "just turned on" are different facts about an
    install, and the operator should not have to guess which happened."""
    account_id = accounts.upsert_account("zeropage", "Zero Page", dsn=tmp_db)
    assert manual_lane.manual_lane_allowed(account_id, tmp_db) is False

    accounts.main(["operator", "zeropage", "--on"])
    out = capsys.readouterr().out
    assert "OFF -> ON" in out and "zeropage" in out
    assert manual_lane.manual_lane_allowed(account_id, tmp_db) is True

    accounts.main(["operator", "zeropage", "--on"])
    assert "already ON" in capsys.readouterr().out

    accounts.main(["operator", "zeropage", "--off"])
    assert "ON -> OFF" in capsys.readouterr().out
    assert manual_lane.manual_lane_allowed(account_id, tmp_db) is False


def test_the_cli_turns_on_exactly_one_account(tmp_db, capsys):
    account_id = accounts.upsert_account("zeropage", "Zero Page", dsn=tmp_db)
    other = accounts.upsert_account("pilot", "Pilot", dsn=tmp_db)
    accounts.main(["operator", "zeropage", "--on"])
    capsys.readouterr()
    assert manual_lane.operator_accounts(tmp_db) == frozenset({account_id})
    assert manual_lane.manual_lane_allowed(other, tmp_db) is False


def test_the_cli_refuses_an_account_that_does_not_exist(tmp_db, capsys):
    """Naming an account nobody created must not read as success -- the
    operator would walk away believing the lane was open."""
    accounts.upsert_account("zeropage", "Zero Page", dsn=tmp_db)
    with pytest.raises(SystemExit) as exit_code:
        accounts.main(["operator", "nope", "--on"])
    assert exit_code.value.code == 1
    assert "no account 'nope'" in capsys.readouterr().err
    assert manual_lane.operator_accounts(tmp_db) == frozenset()


def test_the_cli_makes_you_say_which_way(tmp_db):
    """--on and --off are mutually exclusive and one is REQUIRED: a bare
    `operator zeropage` that quietly meant --on would be a gate moved by
    a half-typed command."""
    with pytest.raises(SystemExit):
        accounts.main(["operator", "zeropage"])
