"""
A still costs credits, not just the clip (2026-09-28, Mike's call); a
Create does not (2026-09-29, Mike's call: it is included in the
subscription, its cost priced into the plans rather than debited per
click).

What each test guards:
- a still's price comes off the meter's own number at the render markup
  and floor, and an unknown image model never prices as the cheap one
- a Create moves no money, but is REFUSED (402, before any job or model
  call) for an account with no plan and no credit balance -- and allowed
  for one with either, the trial grant included
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
    assert pricing.still_credits("gemini-2.5-flash-image") == 10    # $0.039 -> floor
    assert pricing.still_credits("gemini-3-pro-image-preview") == 33  # $0.134 x 2.4
    # the non-preview name the .env and refgen actually ask for
    assert pricing.still_credits("gemini-3-pro-image") == 33


def test_an_unknown_image_model_never_prices_as_the_cheap_one():
    assert pricing.still_credits("some-new-image-model") == \
        pricing.still_credits("gemini-3-pro-image-preview")


def test_the_public_catalog_prints_the_same_numbers():
    actions = pricing.public_catalog()["actions"]
    assert actions == {"create": 0, "still": {"standard": 10, "pro": 33}}


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


def test_no_plan_and_no_balance_refuses_create_before_anything_runs(client, studio,
                                                                   writer):
    res = _create(client)
    assert res.status_code == 402
    body = res.json()["error"]
    assert body["code"] == "subscribe_or_top_up"
    assert "subscribe or top up" in body["message"]
    assert writer["n"] == 0                       # no job, no model call
    assert _kinds(studio) == []


def test_a_create_moves_no_money(client, studio, writer):
    _fund(studio)
    for brain in ("fast", "reasoning"):
        res = _create(client, brain=brain)
        assert res.status_code == 200, res.text
        assert _wait(client, res.json()["job_id"])["status"] == "done"
    assert writer["n"] == 2
    assert _spent(studio) == 0
    assert _kinds(studio) == ["grant"]


def test_the_trial_grant_is_enough_to_create(client, studio, writer):
    ledger.grant(studio["account_id"], 100, "promo",
                 source_ref=f"signup:{studio['account_id']}", dsn=studio["dsn"])
    res = _create(client)
    assert res.status_code == 200, res.text


def test_a_plan_is_enough_to_create_with_no_balance(client, studio, writer):
    accounts.set_plan(studio["account_id"], "starter", dsn=studio["dsn"])
    res = _create(client)
    assert res.status_code == 200, res.text
    assert _wait(client, res.json()["job_id"])["status"] == "done"
    assert _spent(studio) == 0


def test_the_director_brief_is_gated_like_create(client, studio, monkeypatch):
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
    assert _spent(studio) == 0


def test_the_composers_image_door_is_gated_like_create(client, studio, monkeypatch):
    """/generate/run grounds, enhances and saves a concept before the
    still's own hold is reached (2026-10-02: the composer's Image button)."""
    from app import api
    from src import shootgen
    calls = {"enhance": 0}

    def fake_enhance(*a, **k):
        calls["enhance"] += 1
        return "ENHANCED"

    monkeypatch.setattr(shootgen, "reference_block", lambda **k: "")
    monkeypatch.setattr(api, "_enhance_generate_prompt", fake_enhance)
    monkeypatch.setattr(nano_banana, "generate_from_prompt",
                        lambda *a, **k: {"ok": True, "media_url": "/renders/f.png"})
    import google.genai as genai_mod
    monkeypatch.setattr(genai_mod, "Client", lambda api_key=None: object())
    form = {"prompt": "a still", "output": "image", "brand": "zeropage"}
    res = client.post("/api/generate/run", data=form)
    assert res.status_code == 402
    assert res.json()["error"]["code"] == "subscribe_or_top_up"
    assert calls["enhance"] == 0                  # no job, no model call
    _fund(studio)
    res = client.post("/api/generate/run", data=form)
    assert _wait(client, res.json()["job_id"])["status"] == "done"
    assert calls["enhance"] == 1


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



# --- keyframes behind a priced approve (2026-09-29) -------------------------


@pytest.fixture
def drawn(monkeypatch):
    """keyframe_scene replaced and counted: the gate is the subject."""
    from src import scene_chain
    calls = []
    monkeypatch.delenv("ZEROPAGE_KEYFRAME_ON_PICK", raising=False)
    monkeypatch.setattr("google.genai.Client", lambda api_key=None: object())
    monkeypatch.setattr(scene_chain, "keyframe_scene",
                        lambda cid, n=None, **kw: calls.append(cid) or
                        {"ok": True, "media_url": "https://example.test/k.jpg", "frames": []})
    return calls


def _timed_scene(studio, parts=3):
    """A one-shot scene whose CURRENT timeline has `parts` shots, none drawn."""
    from src import timeline
    shot = {"n": 1, "type": "BROLL", "source": "AI", "tool": "LTX",
            "prompt": "(0-3s) a. (3-6s) b. (6-9s) c.", "refs": ["/refs/x.jpg"]}
    shot["timeline"] = {
        "seconds": 9, "planner": "split", "continuity": "",
        "source": timeline.source_hash(shot["prompt"], shot["refs"]),
        "parts": [{"n": i + 1, "start": 3 * i, "end": 3 * i + 3, "seconds": 3,
                   "text": "x", "prompt": "x", "refs": shot["refs"]} for i in range(parts)]}
    return preprod.save_concept({"title": "T", "hook": "", "logline": "", "shots": [shot]},
                                brand="zeropage", prompt_template="T", dsn=studio["dsn"],
                                account_id=studio["account_id"])


def test_drawing_keyframes_needs_the_whole_strip_in_the_balance(client, studio, drawn):
    from src import nano_banana
    cid = _timed_scene(studio)
    each = pricing.still_credits(nano_banana.MODEL)
    _fund(studio, 2 * each)                    # two of three stills
    res = client.post(f"/api/concepts/{cid}/keyframes")
    assert res.status_code == 402
    body = res.json()["error"]
    assert body["code"] == "out_of_credits"
    assert f"needs {3 * each}" in body["message"] and "top up" in body["message"]
    assert drawn == []                          # never a partial strip

    _fund(studio, each)
    res = client.post(f"/api/concepts/{cid}/keyframes")
    assert res.status_code == 200, res.text
    assert res.json()["keyframes"]["stills"] == 3
    assert _wait(client, res.json()["job_id"])["status"] == "done"
    assert drawn == [cid]


def test_an_exempt_account_draws_with_no_balance(client, studio, drawn):
    accounts.set_credit_exempt("zeropage", True, dsn=studio["dsn"])
    cid = _timed_scene(studio, parts=1)
    res = client.post(f"/api/concepts/{cid}/keyframes")
    assert res.status_code == 200, res.text


def test_the_balance_carries_the_still_price(client, studio):
    from src import nano_banana
    prices = client.get("/api/billing/balance").json()["prices"]
    assert prices == {"still": pricing.still_credits(nano_banana.MODEL)}


# --- the doors that draw a still charge THEIR account (2026-09-30) -----------
# Found by the first real keyframe approve on a non-exempt account: the
# keyframe paths, the Director's Nano node, /api/generate/run's image branch
# and Run all passed no account into nano_banana, so every one of those stills
# was drawn FREE and its generations row was filed under the bootstrap
# account. These drive the real paths with only the image model faked.


def _gen_owners(studio):
    with db.connect(studio["dsn"]) as conn:
        return [r["account_id"] for r in conn.execute(
            "SELECT account_id FROM generations WHERE tool = 'nano' ORDER BY id")]


def test_the_keyframe_approve_charges_every_still_to_the_account(client, studio, nano,
                                                                 monkeypatch):
    from src import nano_banana
    monkeypatch.delenv("ZEROPAGE_KEYFRAME_ON_PICK", raising=False)
    cid = _timed_scene(studio)
    each = pricing.still_credits(nano_banana.MODEL)
    _fund(studio, 3 * each)
    res = client.post(f"/api/concepts/{cid}/keyframes")
    assert res.status_code == 200, res.text
    assert _wait(client, res.json()["job_id"])["status"] == "done"
    assert nano["n"] == 3
    assert _spent(studio) == 3 * each
    assert _kinds(studio).count("settle") == 3
    assert ledger.outstanding(studio["account_id"], studio["dsn"]) == 0
    assert _gen_owners(studio) == [studio["account_id"]] * 3


def test_the_director_nano_node_charges_the_account(client, studio, nano):
    from src import nano_banana
    each = pricing.still_credits(nano_banana.MODEL)
    _fund(studio, each)
    res = client.post("/api/workflows/exec/nano", json={"prompt": "a bench in fog"})
    assert res.status_code == 200, res.text
    assert _wait(client, res.json()["job_id"])["status"] == "done"
    assert _spent(studio) == each
    assert _gen_owners(studio) == [studio["account_id"]]


def test_every_nano_caller_forwards_the_account():
    """The shape of the bug, asserted on the source: a generate_from_prompt
    call that does not pass account_id is a still nobody pays for."""
    import ast
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent
    missing = []
    for rel in ("src/scene_chain.py", "src/element_sheet.py", "app/api.py",
                "app/workflow_runner.py"):
        tree = ast.parse((root / rel).read_text())
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "generate_from_prompt"
                    and getattr(node.func.value, "id", None) == "nano_banana"
                    and not any(k.arg == "account_id" for k in node.keywords)):
                missing.append(f"{rel}:{node.lineno}")
    assert not missing, f"nano_banana.generate_from_prompt without account_id: {missing}"


# --- the composer picks the image model (2026-10-04) --------------------------

def test_image_models_is_a_projection_of_the_keys_on_file(client, monkeypatch):
    from src import fal, nano_banana, pricing
    monkeypatch.delenv("FAL_KEY", raising=False)
    monkeypatch.setattr(nano_banana, "has_key", lambda account_id=None: True)
    res = client.get("/api/image-models")
    assert res.status_code == 200
    body = res.json()
    assert [i["id"] for i in body["items"]] == ["nano"] and body["default"] == "nano"
    assert body["items"][0]["credits"] == pricing.still_credits(nano_banana.MODEL)
    monkeypatch.setenv("FAL_KEY", "k")
    body = client.get("/api/image-models").json()
    assert [i["id"] for i in body["items"]] == ["nano", *fal.IMAGE_MODELS]
    seedream = next(i for i in body["items"] if i["id"] == "seedream4")
    assert seedream["provider"] == "fal" and seedream["references"] is True
    assert seedream["credits"] == pricing.credits_for(pricing.usd_micros(fal.image_usd("seedream4")))


def test_the_composers_image_door_draws_on_the_picked_fal_model(client, studio, monkeypatch):
    from app import api
    from src import fal, shootgen
    seen = {}
    monkeypatch.setattr(shootgen, "reference_block", lambda **k: "")
    monkeypatch.setattr(api, "_enhance_generate_prompt", lambda *a, **k: "ENHANCED")
    monkeypatch.setattr(nano_banana, "generate_from_prompt",
                        lambda *a, **k: pytest.fail("Nano drew a still the person asked fal for"))

    def fake_fal(prompt, **kw):
        seen.update(kw, prompt=prompt)
        return {"ok": True, "media_url": "/renders/fal/x.jpg", "references": 0}

    monkeypatch.setattr(fal, "generate_image_from_prompt", fake_fal)
    import google.genai as genai_mod
    monkeypatch.setattr(genai_mod, "Client", lambda api_key=None: object())
    _fund(studio)
    form = {"prompt": "a still", "output": "image", "brand": "zeropage",
            "image_model": "seedream4", "aspect": "4:5"}
    # no fal key: refused before the job, no enhance paid for
    monkeypatch.delenv("FAL_KEY", raising=False)
    res = client.post("/api/generate/run", data=form)
    assert res.status_code == 503
    res = client.post("/api/generate/run", data={**form, "image_model": "dall-e"})
    assert res.status_code == 400 and res.json()["error"]["code"] == "bad_model"
    monkeypatch.setenv("FAL_KEY", "k")
    res = client.post("/api/generate/run", data=form)
    assert res.status_code == 200, res.text
    job = _wait(client, res.json()["job_id"])
    assert job["status"] == "done", job
    assert seen["prompt"] == "ENHANCED" and seen["model"] == "seedream4"
    assert seen["aspect"] == "4:5" and seen["approved"] is True
    assert seen["account_id"] == studio["account_id"]
    assert "Seedream 4.0" in job["detail"]
