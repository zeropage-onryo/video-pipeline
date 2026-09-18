"""GET /api/queue/pending asks its per-ACCOUNT questions once per request.

Which vendors the account holds a key for, whose key each is, and today's
count per vendor are facts about the account. Until 2026-09-18 every card
asked them again, per vendor, each on its own connection: four cards were
~45 connections and ~45s from a laptop against Supabase. These tests count
connections and key/cap lookups for a listing of one card and of several,
and fail if either grows with the number of cards.
"""
import psycopg
import pytest
from fastapi.testclient import TestClient

import app.main as app_main
from app import api, auth
from app.main import app
from src import account_keys, accounts, db, generative, preprod, pricing, providers

client = TestClient(app)

RENDER_KEYS = ("RUNWAYML_API_SECRET", "FAL_KEY", "FAL_API_KEY", "HIGGSFIELD_API_KEY_ID",
               "HF_API_KEY_ID", "HIGGSFIELD_API_KEY_SECRET", "HF_API_KEY_SECRET",
               "GEMINI_API_KEY", "GOOGLE_API_KEY")


@pytest.fixture(autouse=True)
def signed_in(monkeypatch):
    stub = {"id": 1, "email": "test@example.com", "display_name": "Test"}
    monkeypatch.setattr(auth, "current_user", lambda request: stub)
    monkeypatch.setattr(
        auth, "current_account",
        lambda request, user=None: {"slug": "zeropage", "display_name": "ZERO PAGE"})


@pytest.fixture
def tmp_db(pg, monkeypatch):
    preprod.init(pg)
    monkeypatch.setenv("DATABASE_URL", pg)
    for name in RENDER_KEYS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("RUNWAYML_API_SECRET", "OPERATOR-RUNWAY")
    monkeypatch.setenv("FAL_KEY", "OPERATOR-FAL")
    return pg


def acting_as(account_id):
    # conftest's autouse fixture set these to None and pops them afterwards
    for target in (app, app_main.app):
        target.dependency_overrides[auth.current_account_id] = lambda: account_id
        target.dependency_overrides[auth.dev_account_id] = lambda: account_id


def queue_scene(path, account_id, tool):
    concept_id = preprod.save_concept(
        {"title": "scene", "hook": "", "logline": "",
         "shots": [{"n": 1, "type": "BROLL", "source": "AI", "tool": tool, "desc": "d",
                    "prompt": "a long enough prompt to render",
                    "refs": ["/refs/seed.jpg"]}]},
        brand="zeropage", prompt_template="T", dsn=path, account_id=account_id)
    preprod.set_shot_parked(concept_id, 1, "keyframe rendered", dsn=path,
                            account_id=account_id)
    return concept_id


class Counters:
    def __init__(self, monkeypatch):
        # connections are the cost that was measured; cap reads are counted
        # beside them because a pooled server hides a connection and not a
        # query. (A key lookup answered from the request's snapshot is still
        # a CALL to account_keys, so calls to it are not the thing to count
        # -- a lookup that reads shows up as a connection.)
        self.connects = self.cap_reads = 0
        real_connect = psycopg.connect
        real_used = generative.used_today

        def connect(*a, **kw):
            self.connects += 1
            return real_connect(*a, **kw)

        def used_today(*a, **kw):
            self.cap_reads += 1
            return real_used(*a, **kw)

        monkeypatch.setattr(psycopg, "connect", connect)
        monkeypatch.setattr(generative, "used_today", used_today)

    def during(self, fn):
        before = (self.connects, self.cap_reads)
        out = fn()
        after = (self.connects, self.cap_reads)
        return out, tuple(b - a for a, b in zip(before, after))


def listing():
    res = client.get("/api/queue/pending")
    assert res.status_code == 200, res.text
    return res.json()


# guards: `ctx = providers.render_context(account_id)` in queue_pending, and
# the ctx handed to render_default / _card_quote / _renderers_state
def test_the_listing_does_not_pay_per_card(tmp_db, monkeypatch):
    assert db._pool is None   # else psycopg.connect is not what is being counted
    # an OWNED account: with account_id None a key lookup never touches the
    # database at all, and there would be nothing here to count
    account_id = accounts.upsert_account("zeropage", "Zero Page", dsn=tmp_db)
    acting_as(account_id)
    # a planned tool the account can render, one it cannot (falls to the
    # cheapest keyed renderer -- the path that asked every vendor), one unplanned
    tools = ["RUNWAY", "KLING", "VEO", "SEEDANCE", None, "RUNWAY"]
    counters = Counters(monkeypatch)

    queue_scene(tmp_db, account_id, tools[0])
    one, cost_of_one = counters.during(listing)
    assert len(one["items"]) == 1

    for tool in tools[1:]:
        queue_scene(tmp_db, account_id, tool)
    many, cost_of_many = counters.during(listing)
    assert len(many["items"]) == len(tools)

    assert cost_of_many == cost_of_one, (
        f"(connections, cap reads): 1 card {cost_of_one}, "
        f"{len(tools)} cards {cost_of_many}")
    # and every card is still priced and defaulted
    for card in many["items"]:
        assert "error" not in card["quote"], card["quote"]
        assert card["render_default"]["provider"] in providers.VIDEO_PROVIDERS


# the counter itself: with the snapshot taken away the same listing DOES pay
# per card, so a pass above is the context working and not a blind counter
def test_without_the_context_the_same_listing_pays_per_card(tmp_db, monkeypatch):
    account_id = accounts.upsert_account("zeropage", "Zero Page", dsn=tmp_db)
    acting_as(account_id)
    monkeypatch.setattr(providers, "render_context", lambda account_id=None, db_path=None: None)
    counters = Counters(monkeypatch)
    queue_scene(tmp_db, account_id, "RUNWAY")
    _, (one, _caps) = counters.during(listing)
    for tool in ("KLING", "VEO", None):
        queue_scene(tmp_db, account_id, tool)
    _, (many, _caps) = counters.during(listing)
    assert many > one


# guards: the context changing WHERE an answer is read, never the answer
def test_the_listing_says_what_the_uncached_calls_say(tmp_db, monkeypatch):
    from cryptography.fernet import Fernet
    monkeypatch.delenv(pricing.SIGNING_ENV, raising=False)   # tokens carry a timestamp
    monkeypatch.setenv("ACCOUNT_KEYS_SECRET", Fernet.generate_key().decode())
    account_id = accounts.upsert_account("zeropage", "Zero Page", dsn=tmp_db)
    acting_as(account_id)
    # the account's OWN fal key: that vendor is BYOK, runway is the operator's
    account_keys.set_key(account_id, "fal", "THEIR-FAL", dsn=tmp_db)
    concepts = [queue_scene(tmp_db, account_id, tool)
                for tool in ("RUNWAY", "KLING", "VEO", None)]
    payload = listing()
    assert payload["renderers"] == providers.render_options(account_id)
    by_id = {c["id"]: c for c in payload["items"]}
    for concept_id in concepts:
        concept = preprod.get_concept(concept_id, dsn=tmp_db, account_id=account_id)
        card = by_id[concept_id]
        assert card["render_default"] == providers.render_default(card.get("tool"), account_id)
        assert card["quote"] == api._card_quote(concept, account_id)
    byok = {by_id[c]["quote"]["provider"]: by_id[c]["quote"]["byok"] for c in concepts}
    assert byok == {"runway": False, "fal": True}


# guards: _held -- a context is honoured only for the account it was built for
def test_a_context_built_for_another_account_is_ignored(tmp_db, monkeypatch):
    theirs = providers.RenderContext(account_id=7, db_path=None,
                                     keyed={name: False for name in providers.VIDEO_PROVIDERS},
                                     today={name: 99 for name in providers.VIDEO_PROVIDERS})
    assert providers.render_default("RUNWAY", None, theirs) == \
        providers.render_default("RUNWAY", None)
    assert providers.render_options(None, ctx=theirs) == providers.render_options(None)


# guards: the `not everyone` test in used_today -- the installation-wide
# count, which the ceiling reads, is never answered from a listing's snapshot
def test_the_snapshot_never_answers_the_installation_wide_count(tmp_db, monkeypatch):
    generative.init(tmp_db)
    with generative.counted_today(None, tmp_db):
        monkeypatch.setattr(generative, "connect",
                            lambda dsn=None: (_ for _ in ()).throw(RuntimeError("read")))
        assert generative.used_today("runway", tmp_db, account_id=None) == 0
        with pytest.raises(RuntimeError):
            generative.used_today("runway", tmp_db, everyone=True)
