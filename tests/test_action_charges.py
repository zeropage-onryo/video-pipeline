"""
Writing a scene and drawing a still cost credits, not just the clip
(2026-09-28, Mike's call: InVideo charges for "agent processing" too, and
the live meter put a Create at ~$0.04 and a still at ~$0.04 of Gemini that
nobody was paying for).

What each test guards:
- the prices come off the meter's own numbers at the render markup and
  floor, and an unknown brain or image model never prices as the cheap one
- Create HOLDS before any job starts: an empty balance is a 402 and the
  scene writer is never called
- a Create that wrote a scene SETTLES at its price; one that wrote nothing,
  or raised, RELEASES -- nobody pays for nothing
- a still settles on its generations row (the ledger_ref reap reads), an
  empty balance refuses before the image model is called, and a failed
  image is released
- the operator's exempt account and the unowned pool move no money
"""

import time

import pytest
from fastapi.testclient import TestClient

from src import accounts, db, generative, ledger, nano_banana, preprod, pricing

# --- the prices -------------------------------------------------------------


def test_prices_are_the_meters_numbers_at_the_render_markup():
    assert pricing.action_credits("create:fast") == 15        # $0.06 x 2.4, up
    assert pricing.action_credits("create:reasoning") == 44   # $0.18 x 2.4, up
    assert pricing.still_credits("gemini-2.5-flash-image") == 10    # $0.039 -> floor
    assert pricing.still_credits("gemini-3-pro-image-preview") == 33  # $0.134 x 2.4
    # the non-preview name the .env and refgen actually ask for
    assert pricing.still_credits("gemini-3-pro-image") == 33


def test_an_unknown_brain_or_model_never_prices_as_the_cheap_one():
    assert pricing.create_action("fast") == "create:fast"
    assert pricing.create_action(None) == "create:fast"
    assert pricing.create_action("genius") == "create:reasoning"
    assert pricing.still_credits("some-new-image-model") == \
        pricing.still_credits("gemini-3-pro-image-preview")


def test_the_public_catalog_prints_the_same_numbers():
    actions = pricing.public_catalog()["actions"]
    assert actions == {"create": {"fast": 15, "reasoning": 44},
                       "still": {"standard": 10, "pro": 33}}


# --- a funded account --------------------------------------------------------


@pytest.fixture
def studio(pg, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", pg)
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    generative.init(pg)
    preprod.init(pg)
    accounts.seed("mike@example.com", dsn=pg)
    ledger.init(pg)
    with db.connect(pg) as conn:
        account_id = int(conn.execute(
            "SELECT id FROM accounts WHERE slug = 'zeropage'").fetchone()["id"])
    return {"dsn": pg, "account_id": account_id}


def _fund(studio, credits=1000):
    ledger.grant(studio["account_id"], credits, "purchase", dsn=studio["dsn"])


def _kinds(studio):
    return [e["kind"] for e in ledger.entries(studio["account_id"], studio["dsn"])]


def _spent(studio):
    return -sum(e["delta"] for e in ledger.entries(studio["account_id"], studio["dsn"])
                if e["kind"] != "grant")


# --- Create -----------------------------------------------------------------


@pytest.fixture
def client(studio, monkeypatch):
    from app import auth
    from app.main import app
    monkeypatch.setattr(auth, "current_user",
                        lambda request: {"id": 1, "email": "t@e.com", "display_name": "T"})
    app.dependency_overrides[auth.current_account_id] = lambda: studio["account_id"]
    yield TestClient(app)
    app.dependency_overrides[auth.current_account_id] = lambda: None


@pytest.fixture
def writer(monkeypatch):
    """scene_chain.run replaced and counted -- the charge is the subject,
    not the writing."""
    from src import scene_chain
    calls = {"n": 0, "scenes": [{"concept_id": 1}], "raise": None}

    def fake_run(idea, brand, **kw):
        calls["n"] += 1
        if calls["raise"]:
            raise calls["raise"]
        return {"scenes": calls["scenes"], "notes": []}

    monkeypatch.setattr(scene_chain, "run", fake_run)
    return calls


def _wait(client, job_id):
    deadline = time.time() + 5
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed", "cancelled"):
            return job
        time.sleep(0.02)
    raise AssertionError("job never finished")


def _create(client, **extra):
    return client.post("/api/scenes/run",
                       data={"idea": "gearing up ritual", "brand": "zeropage", **extra})


def test_an_empty_balance_refuses_create_before_anything_runs(client, studio, writer):
    res = _create(client)
    assert res.status_code == 402
    body = res.json()["error"]
    assert body["code"] == "out_of_credits"
    assert "this scene needs 15" in body["message"]
    assert writer["n"] == 0                       # no job, no model call
    assert _kinds(studio) == []


def test_a_create_that_wrote_a_scene_is_charged_its_price(client, studio, writer):
    _fund(studio)
    res = _create(client)
    assert res.status_code == 200, res.text
    assert _wait(client, res.json()["job_id"])["status"] == "done"
    assert writer["n"] == 1
    assert _spent(studio) == 15
    assert "settle" in _kinds(studio) and "release" not in _kinds(studio)
    assert ledger.outstanding(studio["account_id"], studio["dsn"]) == 0


def test_the_reasoning_brain_costs_more(client, studio, writer):
    _fund(studio)
    res = _create(client, brain="reasoning")
    assert _wait(client, res.json()["job_id"])["status"] == "done"
    assert _spent(studio) == 44


def test_a_create_that_wrote_nothing_or_failed_is_free(client, studio, writer):
    _fund(studio)
    writer["scenes"] = []
    _wait(client, _create(client).json()["job_id"])
    writer["raise"] = RuntimeError("model down")
    job = _wait(client, _create(client).json()["job_id"])
    assert job["status"] == "failed"
    assert _spent(studio) == 0
    assert _kinds(studio).count("release") == 2
    assert ledger.outstanding(studio["account_id"], studio["dsn"]) == 0


def test_the_director_brief_is_charged_like_create(client, studio, monkeypatch):
    from app import api
    from src import shootgen
    monkeypatch.setattr(api, "scene_grounding", lambda *a, **k: "")
    monkeypatch.setattr(shootgen, "generate_scene_concept",
                        lambda **kw: {"concept_id": 7, "concept": {"title": "T"}})
    res = client.post("/api/pipeline/run", data={"prompt": "a rider", "brand": "zeropage"})
    assert res.status_code == 402
    _fund(studio)
    res = client.post("/api/pipeline/run", data={"prompt": "a rider", "brand": "zeropage"})
    assert _wait(client, res.json()["job_id"])["status"] == "done"
    assert _spent(studio) == 15


def test_the_owner_is_never_charged(client, studio, writer):
    accounts.set_credit_exempt("zeropage", True, dsn=studio["dsn"])
    res = _create(client)                          # no credit at all
    assert res.status_code == 200, res.text
    assert _wait(client, res.json()["job_id"])["status"] == "done"
    assert _kinds(studio) == []


# --- a still -----------------------------------------------------------------


@pytest.fixture
def nano(studio, monkeypatch, tmp_path):
    calls = {"n": 0, "raise": None}

    def fake_image(prompt, out_path, **kw):
        calls["n"] += 1
        if calls["raise"]:
            raise calls["raise"]
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"\x89PNG")
        return out_path

    import src.storage as storage
    monkeypatch.setattr(nano_banana, "generate_image", fake_image)
    monkeypatch.setattr(nano_banana, "RENDER_DIR", tmp_path / "nano")
    monkeypatch.setattr(storage, "configured", lambda: False)
    monkeypatch.setattr(nano_banana.render_assets, "record_best_effort",
                        lambda **kw: {"id": None, "rag": None})
    return calls


def _still(studio, **kw):
    # the model pinned: a developer's .env may set NANO_BANANA_MODEL to Pro
    kw.setdefault("model", "gemini-2.5-flash-image")
    return nano_banana.generate_from_prompt(
        "a rider suits up in a cold garage", db_path=studio["dsn"],
        account_id=studio["account_id"], **kw)


def test_a_still_is_charged_on_its_generations_row(studio, nano):
    import json
    _fund(studio)
    result = _still(studio)
    assert result["ok"], result["error"]
    assert _spent(studio) == 10
    settle = [e for e in ledger.entries(studio["account_id"], studio["dsn"])
              if e["kind"] == "settle"][0]
    assert settle["generation_id"] == result["generation_id"]
    with db.connect(studio["dsn"]) as conn:
        params = json.loads(conn.execute(
            "SELECT params_json FROM generations WHERE id = %s",
            (result["generation_id"],)).fetchone()["params_json"])
    assert params[ledger.GENERATION_REF_KEY] == settle["ref"]


def test_a_pro_still_costs_the_pro_price(studio, nano):
    _fund(studio)
    assert _still(studio, model="gemini-3-pro-image-preview")["ok"]
    assert _spent(studio) == 33


def test_an_empty_balance_refuses_a_still_before_the_model(studio, nano):
    result = _still(studio)
    assert result["ok"] is False
    assert "this still needs 10" in result["error"]
    assert nano["n"] == 0
    assert _kinds(studio) == []


def test_a_failed_still_is_released(studio, nano):
    _fund(studio)
    nano["raise"] = RuntimeError("no image in the response")
    assert _still(studio)["ok"] is False
    assert _spent(studio) == 0
    assert "release" in _kinds(studio)


def test_every_still_on_a_timed_scene_is_its_own_charge(studio, nano):
    """A pick draws one still per shot, often inside the same second --
    the hold ref must still be unique, or the second still reuses the
    first's settled hold and is drawn for free."""
    _fund(studio)
    for _ in range(3):
        assert _still(studio, concept_id=5)["ok"]
    assert _spent(studio) == 30


def test_the_unowned_nightly_pool_is_not_charged(studio, nano):
    result = nano_banana.generate_from_prompt(
        "a rider suits up", db_path=studio["dsn"], account_id=None,
        model="gemini-2.5-flash-image")
    assert result["ok"], result["error"]
    assert _kinds(studio) == []
