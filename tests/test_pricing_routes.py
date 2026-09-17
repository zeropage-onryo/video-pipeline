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
