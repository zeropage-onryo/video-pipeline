"""The price a card shows and the price an approve answers with are ONE
computation (src/pricing.py, steps 2-3 of docs/tasks/task-pricing-and-quotes.md).

Same standard as tests/test_pricing.py: each test names the line it
guards, and was seen to fail with that line reverted.
"""
import pathlib
import time

import pytest
from fastapi.testclient import TestClient

from app import auth
from app.main import app
from src import accounts, db, fal, higgsfield, preprod, pricing, runway, timeline

client = TestClient(app)

RENDER_KEYS = ("RUNWAYML_API_SECRET", "FAL_KEY", "FAL_API_KEY", "HIGGSFIELD_API_KEY_ID",
               "HF_API_KEY_ID", "HIGGSFIELD_API_KEY_SECRET", "HF_API_KEY_SECRET",
               "GEMINI_API_KEY", "GOOGLE_API_KEY")
TIMED = ("BEATS (0-7s) he laces both boots, slowly, in the cold garage light. "
         "(7-10s) the visor drops and the engine catches.")


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
    return pg


def a_queued_scene(path, *, prompt="a long enough prompt to render", tool="RUNWAY",
                   account_id=None):
    concept_id = preprod.save_concept(
        {"title": "scene", "hook": "", "logline": "",
         "shots": [{"n": 1, "type": "BROLL", "source": "AI", "tool": tool, "desc": "d",
                    "prompt": prompt, "refs": ["/refs/seed.jpg"]}]},
        brand="zeropage", prompt_template="T", dsn=path, account_id=account_id)
    preprod.set_shot_parked(concept_id, 1, "keyframe rendered", dsn=path,
                            account_id=account_id)
    return concept_id


def wait_for_job(job_id, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed", "cancelled"):
            return job
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} never finished")


def card_for(scene):
    items = client.get("/api/queue/pending").json()["items"]
    return next(c for c in items if c["id"] == scene)


# guards: `"quote": _card_quote(...)` on the pending payload
def test_every_pending_card_carries_the_servers_price(tmp_db):
    scene = a_queued_scene(tmp_db)
    quote = card_for(scene)["quote"]
    assert quote["provider"] == "runway" and quote["timed"] is False
    assert quote["durations"] == [runway.DEFAULT_DURATION]
    assert quote["estimate_usd"] == pytest.approx(
        runway.estimate_cost(1, model=quote["model"], duration=runway.DEFAULT_DURATION,
                             ratio=quote["frame"]))
    assert quote["credits"] == pricing.credits_for(pricing.usd_micros(quote["estimate_usd"]))
    assert quote["byok"] is False


# guards: queue_approve pricing through pricing.display. THE POINT OF
# STEP 2: what the card printed and what the approve answers cannot differ.
def test_the_card_and_an_empty_approve_agree(tmp_db, monkeypatch):
    seen = {}
    monkeypatch.setattr(runway, "generate_for_shot",
                        lambda *a, **kw: seen.update(kw) or {"ok": True, "media_url": "https://x/c.mp4"})
    scene = a_queued_scene(tmp_db)
    shown = card_for(scene)["quote"]
    body = client.post(f"/api/queue/{scene}/approve").json()
    assert wait_for_job(body["job_id"])["status"] == "done"
    assert body["quote"] == shown
    assert body["render"]["estimate_usd"] == shown["estimate_usd"]
    assert (seen["model"], seen["duration"]) == (shown["model"], shown["durations"][0])


# guards: the timed branch reading pricing.windows_to_render -- a 7s and a
# 3s window are a 10s and a 5s Runway render, fitted on the SERVER
def test_a_timed_scene_is_priced_per_shot_by_the_server(tmp_db):
    scene = a_queued_scene(tmp_db, prompt=TIMED)
    quote = card_for(scene)["quote"]
    assert quote["timed"] is True and quote["durations"] == [10, 5]
    each = [runway.estimate_cost(1, model=quote["model"], duration=d, ratio=quote["frame"])
            for d in (10, 5)]
    assert quote["estimate_usd"] == pytest.approx(sum(each))
    assert [r["part"] for r in quote["renders"]] == [1, 2]
    # another pick is asked of the same function, not computed in the browser
    other = client.get(f"/api/queue/{scene}/quote",
                       params={"provider": "fal", "model": "ltx2.3"}).json()
    assert other["provider"] == "fal" and other["durations"] == [7, 3]
    assert other["estimate_usd"] == pytest.approx(
        sum(fal.estimate_cost(1, model="ltx2.3", duration=d, resolution=other["frame"])
            for d in (7, 3)))


def test_a_pick_the_model_cannot_render_is_refused_with_the_reason(tmp_db):
    scene = a_queued_scene(tmp_db)
    res = client.get(f"/api/queue/{scene}/quote",
                     params={"provider": "runway", "model": "gen4_turbo", "duration": 7})
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "bad_render_choice"
    assert client.get("/api/queue/999999/quote").status_code == 404


# guards: `account_id=account_id` on queue_quote's get_concept. Under
# conftest's None override this is green whatever the route does, so it
# seeds two real accounts and sets its own.
def test_another_accounts_concept_has_no_price(tmp_db):
    accounts.seed("mike@example.com", dsn=tmp_db)
    with db.connect(tmp_db) as conn:
        ids = [r["id"] for r in conn.execute("SELECT id FROM accounts ORDER BY id").fetchall()]
    owner, stranger = ids[0], ids[1]
    scene = a_queued_scene(tmp_db, account_id=owner)
    try:
        app.dependency_overrides[auth.current_account_id] = lambda: stranger
        assert client.get(f"/api/queue/{scene}/quote").status_code == 404
        app.dependency_overrides[auth.current_account_id] = lambda: owner
        assert client.get(f"/api/queue/{scene}/quote").status_code == 200
    finally:
        app.dependency_overrides[auth.current_account_id] = lambda: None


# guards: `"generate": _generate_node_quote(...)` on the concept. The
# Director chip read runway.estimate_usd on every account, including one
# that can only render -- and only be billed -- somewhere else.
def test_the_director_prices_the_renderer_the_node_would_actually_use(tmp_db, monkeypatch):
    monkeypatch.delenv("RUNWAYML_API_SECRET")
    monkeypatch.setenv("HIGGSFIELD_API_KEY_ID", "id")
    monkeypatch.setenv("HIGGSFIELD_API_KEY_SECRET", "secret")
    assert higgsfield.has_key(None)
    scene = a_queued_scene(tmp_db, prompt=TIMED)
    detail = client.get(f"/api/concepts/{scene}").json()
    gen = detail["generate"]
    assert gen["provider"] == "higgsfield"
    # ONE clip, whatever windows the prompt carries: that is what Run renders
    assert gen["timed"] is False and len(gen["durations"]) == 1
    assert gen["estimate_usd"] == pytest.approx(
        higgsfield.estimate_cost(1, model=gen["model"], duration=gen["durations"][0]))
    assert detail["runway"]["estimate_usd"] is not None      # the old shape is still served


def test_no_keyed_renderer_is_said_not_priced(tmp_db, monkeypatch):
    monkeypatch.delenv("RUNWAYML_API_SECRET")
    scene = a_queued_scene(tmp_db)
    assert "error" in client.get(f"/api/concepts/{scene}").json()["generate"]


# step 3: two implementations of a price is how a person is shown one
# number and charged another
def test_the_queue_js_does_no_window_fitting_of_its_own():
    js = pathlib.Path("app/static/zpf/queue.js").read_text()
    assert "function fitSeconds" not in js and "fitSeconds(" not in js
    assert "/quote?" in js and "card.quote" in js


def test_the_content_hash_on_a_card_moves_with_its_prompt(tmp_db):
    scene = a_queued_scene(tmp_db)
    before = card_for(scene)["quote"]["content_hash"]
    assert before == timeline.source_hash("a long enough prompt to render", ["/refs/seed.jpg"])


# --- step 4: the price approved is the price rendered ------------------------

SECRET = "dGVzdC1zZWNyZXQtdGhpcnR5LXR3by1ieXRlcy1sb25nLW9r"


@pytest.fixture
def signing(tmp_db, monkeypatch):
    monkeypatch.setenv(pricing.SIGNING_ENV, SECRET)
    return tmp_db


def never_submits(monkeypatch, module):
    """An adapter whose submit must not be entered. Raising is not enough
    on its own -- the route runs it in a job -- so it also records."""
    entered = {}

    def fake(*a, **kw):
        entered["called"] = True
        raise AssertionError("the adapter was entered")
    monkeypatch.setattr(module, "generate_for_shot", fake)
    return entered


def test_the_listing_signs_and_the_approve_verifies(signing, monkeypatch):
    seen = {}
    monkeypatch.setattr(runway, "generate_for_shot",
                        lambda *a, **kw: seen.update(kw) or {"ok": True, "media_url": "https://x/c.mp4"})
    scene = a_queued_scene(signing, prompt=TIMED)
    quote = card_for(scene)["quote"]
    tokens = [r["token"] for r in quote["renders"]]
    assert quote["signed"] is True and all(t and t.startswith("zpfq.") for t in tokens)
    assert client.get("/api/capabilities").json()["quote.sign"] is True
    res = client.post(f"/api/queue/{scene}/approve",
                      json={"provider": "runway", "model": "gen4_turbo", "tokens": tokens})
    assert res.status_code == 200, res.text
    assert wait_for_job(res.json()["job_id"])["status"] == "done"


# guards: `_verify_tokens(...)` in queue_approve. THE ONE THAT MATTERS: a
# refused quote means the adapter was never entered.
def test_a_scene_edited_after_quoting_does_not_render(signing, monkeypatch):
    entered = never_submits(monkeypatch, runway)
    scene = a_queued_scene(signing)
    tokens = [r["token"] for r in card_for(scene)["quote"]["renders"]]
    concept = preprod.get_concept(scene, account_id=None)
    shots = concept["shots"]
    shots[0]["prompt"] += " He looks up."
    preprod.update_concept_shots(scene, {"shots": shots}, account_id=None)
    res = client.post(f"/api/queue/{scene}/approve",
                      json={"provider": "runway", "model": "gen4_turbo", "duration": 5,
                            "tokens": tokens})
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "stale_content"
    assert "called" not in entered
    # and the fresh price signs again
    fresh = [r["token"] for r in card_for(scene)["quote"]["renders"]]
    assert fresh != tokens


def test_a_quote_for_another_pick_does_not_render(signing, monkeypatch):
    entered = never_submits(monkeypatch, fal)
    monkeypatch.setenv("FAL_KEY", "fake")
    scene = a_queued_scene(signing)
    tokens = [r["token"] for r in card_for(scene)["quote"]["renders"]]   # priced on runway
    res = client.post(f"/api/queue/{scene}/approve",
                      json={"provider": "fal", "model": "ltx2.3", "tokens": tokens})
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "wrong_render"
    assert "called" not in entered


def test_a_timed_scene_needs_a_quote_for_every_shot(signing, monkeypatch):
    entered = never_submits(monkeypatch, runway)
    scene = a_queued_scene(signing, prompt=TIMED)
    tokens = [r["token"] for r in card_for(scene)["quote"]["renders"]]
    res = client.post(f"/api/queue/{scene}/approve",
                      json={"provider": "runway", "model": "gen4_turbo", "tokens": tokens[:1]})
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "missing_quote"
    assert "called" not in entered


def test_another_tenants_quote_is_refused_and_named(signing, monkeypatch, capsys):
    entered = never_submits(monkeypatch, runway)
    scene = a_queued_scene(signing)
    concept = preprod.get_concept(scene, account_id=None)
    stranger = pricing.sign(pricing.quote(account_id=77, shot=concept["shots"][0], shot_id=scene,
                                          provider="runway", model="gen4_turbo", seconds=5))
    res = client.post(f"/api/queue/{scene}/approve",
                      json={"provider": "runway", "model": "gen4_turbo", "duration": 5,
                            "tokens": [stranger]})
    assert res.status_code == 400 and res.json()["error"]["code"] == "wrong_account"
    assert "wrong_account" in capsys.readouterr().err
    assert "called" not in entered


# guards: the SigningUnconfigured branch of _quote_refusal -- 503 with the
# command, never a 500, never a default secret
def test_a_token_with_no_secret_is_503_with_the_command(signing, monkeypatch):
    entered = never_submits(monkeypatch, runway)
    scene = a_queued_scene(signing)
    tokens = [r["token"] for r in card_for(scene)["quote"]["renders"]]
    monkeypatch.delenv(pricing.SIGNING_ENV)
    assert card_for(scene)["quote"]["signed"] is False
    res = client.post(f"/api/queue/{scene}/approve",
                      json={"provider": "runway", "model": "gen4_turbo", "duration": 5,
                            "tokens": tokens})
    assert res.status_code == 503
    assert res.json()["error"]["code"] == "signing_unconfigured"
    assert pricing.SIGNING_COMMAND in res.json()["error"]["message"]
    assert "called" not in entered


def test_an_approve_without_tokens_still_works_for_now(signing, monkeypatch):
    """Step 4 accepts a missing token (the front ends catch up); step 5
    makes it required, in one commit with the markup."""
    seen = {}
    monkeypatch.setattr(runway, "generate_for_shot",
                        lambda *a, **kw: seen.update(kw) or {"ok": True, "media_url": "https://x/c.mp4"})
    scene = a_queued_scene(signing)
    res = client.post(f"/api/queue/{scene}/approve")
    assert res.status_code == 200 and wait_for_job(res.json()["job_id"])["status"] == "done"


# guards: the token branch in workflow_exec_generate
def test_the_director_run_carries_its_quote(signing, monkeypatch):
    from app import workflow_runner
    entered = {}
    monkeypatch.setattr(workflow_runner, "render_generate_node",
                        lambda *a, **kw: entered.update(ok=True) or {"ok": True, "media_url": "https://x/c.mp4"})
    scene = a_queued_scene(signing)
    gen = client.get(f"/api/concepts/{scene}").json()["generate"]
    token = gen["renders"][0]["token"]
    assert token
    body = {"prompt": "a long enough prompt to render", "concept_id": scene, "shot_n": 1,
            "token": token}
    res = client.post("/api/workflows/exec/generate", json=body)
    assert res.status_code == 200, res.text
    assert wait_for_job(res.json()["job_id"])["status"] == "done" and entered
    # the scene moved: the same token no longer runs it
    entered.clear()
    concept = preprod.get_concept(scene, account_id=None)
    shots = concept["shots"]
    shots[0]["prompt"] += " He looks up."
    preprod.update_concept_shots(scene, {"shots": shots}, account_id=None)
    res = client.post("/api/workflows/exec/generate", json=body)
    assert res.status_code == 400 and res.json()["error"]["code"] == "stale_content"
    assert not entered
    # a free-standing node cannot carry one
    res = client.post("/api/workflows/exec/generate", json={"prompt": "p", "token": token})
    assert res.status_code == 400 and res.json()["error"]["code"] == "wrong_render"
