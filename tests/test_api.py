"""
Tests for app/api.py -- the JSON layer behind /ui. Same discipline as
test_app.py: the store is unreachable by default, anything billed is
patched at the function the route actually calls, and background jobs
are polled to completion so a silently-dead thread fails loudly.
"""
import time

import pytest
from fastapi.testclient import TestClient

from app import api as api_mod
from app import jobs
from app.main import app
from src import autonomy, db, entities, evalstore, preprod

client = TestClient(app)


@pytest.fixture(autouse=True)
def no_real_rag_store(monkeypatch):
    def refused(db_url=None):
        raise ConnectionError("no rag store in tests")

    monkeypatch.setattr(api_mod.rag, "connect", refused)


@pytest.fixture(autouse=True)
def signed_in(monkeypatch):
    """Every /api route now sits behind the session gate (app/auth.py).
    These tests exercise API behaviour, not the gate -- the gate has its
    own suite in test_auth.py -- so a stub session is welded on here."""
    from app import auth
    stub = {"id": 1, "email": "test@example.com", "display_name": "Test"}
    monkeypatch.setattr(auth, "current_user", lambda request: stub)
    monkeypatch.setattr(
        auth, "current_account",
        lambda request, user=None: {"slug": "antihero", "display_name": "ANTIHERO"})


@pytest.fixture(autouse=True)
def fresh_jobs():
    jobs.clear_all_for_tests()
    yield
    jobs.clear_all_for_tests()


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    path = tmp_path / "test.db"
    db.init_db(path)
    preprod.init(path)
    entities.init(path)
    autonomy.init(path)
    evalstore.init(path)
    monkeypatch.setattr(db, "DB_PATH", path)
    return path


def wait_for_job(job_id, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed", "cancelled"):
            return job
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} never finished")


# --- capabilities -----------------------------------------------------------

def test_capabilities_reflect_missing_key_and_dead_store(tmp_db, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    caps = client.get("/api/capabilities").json()
    assert caps["retrieve"] is False        # store refused above
    assert caps["pipeline.run"] is False    # no key
    assert caps["holds"] is True            # SQLite is always there


def test_capabilities_light_up_with_key_and_store(tmp_db, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")

    class FakeConn:
        def close(self):
            pass

    monkeypatch.setattr(api_mod.rag, "connect", lambda db_url=None: FakeConn())
    caps = client.get("/api/capabilities").json()
    assert caps["retrieve"] is True
    assert caps["evals.run"] is True


# --- assets -----------------------------------------------------------------

def test_assets_empty_and_counts_come_from_db(tmp_db):
    data = client.get("/api/assets").json()
    assert data["items"] == []
    assert data["counts"] == {"all": 0, "location": 0, "character": 0, "prop": 0}


def test_assets_unify_locations_characters_props(tmp_db):
    preprod.add_location("garage", {"space": "low key garage"}, path=tmp_db)
    entities.add_character(name="Michael", role="rider", path=tmp_db)
    entities.add_prop(name="Ducati 959", category="vehicle", path=tmp_db)

    data = client.get("/api/assets").json()
    assert data["counts"] == {"all": 3, "location": 1, "character": 1, "prop": 1}
    cats = {i["id"]: i["category"] for i in data["items"]}
    assert set(cats.values()) == {"location", "character", "prop"}

    filtered = client.get("/api/assets?category=character").json()
    assert [i["name"] for i in filtered["items"]] == ["Michael"]
    # counts stay set totals even when the page is filtered
    assert filtered["counts"]["all"] == 3

    searched = client.get("/api/assets?q=ducati").json()
    assert [i["name"] for i in searched["items"]] == ["Ducati 959"]


def test_asset_detail_404_for_missing(tmp_db):
    response = client.get("/api/assets/location/99")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


# --- retrieval --------------------------------------------------------------

def test_retrieve_surfaces_store_failure_as_503(tmp_db):
    response = client.post("/api/retrieve", json={"query": "night ride"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "retrieval_unavailable"


def test_retrieve_returns_hits_and_latency(tmp_db, monkeypatch):
    class FakeConn:
        def close(self):
            pass

    hits = [{"source": "prompts/brief.txt", "chunk": "noir", "domain": "personal_brand",
             "project": None, "source_ref": None, "score": 0.91}]
    monkeypatch.setattr(api_mod.rag, "connect", lambda db_url=None: FakeConn())
    monkeypatch.setattr(api_mod.rag, "make_client", lambda: object())
    monkeypatch.setattr(api_mod.rag, "query",
                        lambda text, client_, conn, k=5, domain=None: hits)
    data = client.post("/api/retrieve", json={"query": "night ride"}).json()
    assert data["hits"] == hits
    assert isinstance(data["latency_ms"], int)
    assert data["model"] == api_mod.rag.EMBED_MODEL


def test_retrieve_rejects_empty_query(tmp_db):
    assert client.post("/api/retrieve", json={"query": "  "}).status_code == 400


# --- pipeline ---------------------------------------------------------------

def seed_concept(path, title="Vault", shots=None):
    return preprod.save_concept(
        {"title": title, "hook": "hook", "logline": "log",
         "duration": "30s", "shots": shots or []},
        brand="antihero", spark="spark", path=path,
    )


def test_pipeline_concepts_derive_status(tmp_db):
    idea_id = seed_concept(tmp_db, "Idea One")
    planned_id = seed_concept(
        tmp_db, "Planned One",
        shots=[{"n": 1, "type": "BROLL", "source": "AI", "location": "garage",
                "tool": "RUNWAY", "prompt": "x"}])
    data = client.get("/api/pipeline/concepts").json()
    by_id = {c["id"]: c for c in data["items"]}
    assert by_id[idea_id]["status"] == "idea"
    assert by_id[planned_id]["status"] == "planned"
    assert by_id[planned_id]["shot_count"] == 1
    assert data["deny_reasons"] == list(api_mod.DENY_REASONS)


def test_pipeline_run_generates_through_a_job(tmp_db, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    import src.shootgen as shootgen
    monkeypatch.setattr(shootgen, "reference_block", lambda **k: "")
    monkeypatch.setattr(
        shootgen, "generate_concept",
        lambda **k: {"concept_id": 7, "concept": {"title": "Generated"}, "warnings": []})
    monkeypatch.setattr(api_mod, "_gemini_key", lambda: "k")

    job_id = client.post("/api/pipeline/run",
                         data={"prompt": "night ride"}).json()["job_id"]
    job = wait_for_job(job_id)
    assert job["status"] == "done"
    assert job["ref_id"] == 7
    assert "Generated" in job["detail"]


def test_pipeline_run_refuses_without_key(tmp_db, monkeypatch):
    monkeypatch.setattr(api_mod, "_gemini_key", lambda: None)
    response = client.post("/api/pipeline/run", data={"prompt": "x"})
    assert response.status_code == 503


@pytest.fixture
def photo_root(tmp_path, monkeypatch):
    """A throwaway locations dir with one real photo, wired into the API's
    photo roots so /api/media and picked-attachment resolution see it."""
    import io

    from PIL import Image
    root = tmp_path / "locations"
    (root / "garage").mkdir(parents=True)
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (200, 30, 40)).save(buf, "JPEG")
    (root / "garage" / "plate.jpg").write_bytes(buf.getvalue())
    monkeypatch.setattr(api_mod, "LOCATIONS_DIR", root)
    monkeypatch.setattr(api_mod, "_PHOTO_ROOTS", {"locations": root})
    return root


def test_media_lists_photos_with_real_dates(tmp_db, photo_root):
    preprod.add_location("garage", {"space": "the garage"}, path=tmp_db)
    media = client.get("/api/media").json()
    assert media["counts"] == {"all": 1, "location": 1, "character": 0, "prop": 0}
    item = media["items"][0]
    assert item["asset_name"] == "garage"
    assert item["url"].startswith("/locations/garage/photo/plate.jpg")
    assert len(item["date"]) == 10   # a real ISO date from the file's mtime


def test_pipeline_run_carries_picked_media_as_image_refs(tmp_db, photo_root,
                                                         monkeypatch):
    preprod.add_location("garage", {"space": "the garage"}, path=tmp_db)
    seen = {}
    import src.shootgen as shootgen
    monkeypatch.setattr(shootgen, "reference_block", lambda **k: "")

    def fake_generate(**kwargs):
        seen.update(kwargs)
        return {"concept_id": 1, "concept": {"title": "T"}, "warnings": []}

    monkeypatch.setattr(shootgen, "generate_concept", fake_generate)
    monkeypatch.setattr(api_mod, "_gemini_key", lambda: "k")

    response = client.post("/api/pipeline/run", data={
        "prompt": "night ride",
        "asset_photos": ["/locations/garage/photo/plate.jpg?thumb=1",
                         "/locations/../../etc/photo/passwd"],   # traversal: dropped
    })
    assert response.json()["image_refs"] == 1
    wait_for_job(response.json()["job_id"])
    refs = seen["image_refs"]
    assert len(refs) == 1 and refs[0][1] == "image/jpeg"


def test_deny_records_correction_and_deletes_even_when_store_is_down(tmp_db):
    concept_id = seed_concept(tmp_db)
    response = client.post(
        f"/api/concepts/{concept_id}/deny",
        json={"reasons": ["off-tone"], "note": "wrong mood"})
    assert response.status_code == 200
    body = response.json()
    assert body["chunks_written"] == 0 and body["chunk_error"]  # store down, said so
    # the correction landed regardless -- the label is never lost
    notes = [c["note"] for c in autonomy.pending_corrections(path=tmp_db)]
    assert any("off-tone" in n and "wrong mood" in n for n in notes)
    assert preprod.get_concept(concept_id, path=tmp_db) is None


def test_deny_validates_reasons(tmp_db):
    concept_id = seed_concept(tmp_db)
    response = client.post(f"/api/concepts/{concept_id}/deny",
                           json={"reasons": ["not a reason"]})
    assert response.status_code == 400
    assert preprod.get_concept(concept_id, path=tmp_db) is not None


def test_approve_plans_shot_list_via_job(tmp_db, monkeypatch):
    concept_id = seed_concept(tmp_db)
    import src.shootgen as shootgen
    monkeypatch.setattr(api_mod, "_gemini_key", lambda: "k")
    monkeypatch.setattr(
        shootgen, "generate_shot_list",
        lambda cid, gemini_client=None, db_path=None:
            {"concept_id": cid, "plan": {"shots": [1, 2, 3]}, "warnings": []})
    job_id = client.post(f"/api/concepts/{concept_id}/approve").json()["job_id"]
    job = wait_for_job(job_id)
    assert job["status"] == "done"
    assert "3 shots" in job["detail"]


def test_concept_detail_carries_prompts_for_the_scene_board(tmp_db):
    concept_id = seed_concept(
        tmp_db, "Vault",
        shots=[{"n": 1, "type": "BROLL", "source": "AI", "location": "garage",
                "tool": "RUNWAY", "prompt": "low key garage, single bulb",
                "desc": "the bike revealed", "light": "one overhead"},
               {"n": 2, "type": "CHARACTER", "source": "CAMERA", "cam": "BMPCC",
                "location": "garage", "desc": "hands on the wrench"}])
    d = client.get(f"/api/concepts/{concept_id}").json()
    assert d["title"] == "Vault"
    assert len(d["shots"]) == 2
    ai_shot = d["shots"][0]
    assert ai_shot["prompt"] == "low key garage, single bulb"
    # every shot carries the director_prompt field; its text arrives with
    # the in-flight shootgen.director_prompt work and may be empty until
    # that lands -- the endpoint degrades rather than crashing
    assert all(isinstance(s["director_prompt"], str) for s in d["shots"])
    import src.shootgen as shootgen
    if hasattr(shootgen, "director_prompt"):
        assert all(s["director_prompt"] for s in d["shots"])
    assert client.get("/api/concepts/999").status_code == 404


def test_concept_detail_degrades_without_director_prompt(tmp_db, monkeypatch):
    """CI runs the committed tree, where shootgen.director_prompt may not
    exist yet -- the scene board must still load, prompts intact."""
    import src.shootgen as shootgen
    monkeypatch.delattr(shootgen, "director_prompt", raising=False)
    concept_id = seed_concept(
        tmp_db, "Vault",
        shots=[{"n": 1, "type": "BROLL", "source": "AI", "location": "garage",
                "tool": "RUNWAY", "prompt": "low key"}])
    d = client.get(f"/api/concepts/{concept_id}").json()
    assert d["shots"][0]["prompt"] == "low key"
    assert d["shots"][0]["director_prompt"] == ""


def test_shot_media_attach_roundtrip(tmp_db):
    concept_id = seed_concept(
        tmp_db, "Vault",
        shots=[{"n": 1, "type": "BROLL", "source": "AI", "location": "garage",
                "tool": "RUNWAY", "prompt": "x"}])
    response = client.post(f"/api/concepts/{concept_id}/shots/1/media",
                           json={"url": "https://cdn.example/clip.mp4"})
    assert response.status_code == 200
    d = client.get(f"/api/concepts/{concept_id}").json()
    assert d["shots"][0]["media_url"] == "https://cdn.example/clip.mp4"
    # a non-URL is refused, a missing shot 404s
    assert client.post(f"/api/concepts/{concept_id}/shots/1/media",
                       json={"url": "clip.mp4"}).status_code == 400
    assert client.post(f"/api/concepts/{concept_id}/shots/9/media",
                       json={"url": "https://x.example/a.mp4"}).status_code == 404


def test_direct_endpoint_revises_through_a_job(tmp_db, monkeypatch):
    concept_id = seed_concept(tmp_db)
    monkeypatch.setattr(api_mod, "_gemini_key", lambda: "k")
    import src.director as director
    monkeypatch.setattr(
        director, "direct_scene",
        lambda cid, note, gemini_client=None, db_path=None:
            {"ok": True, "summary": "revised shot(s) 1", "warnings": [], "error": None})
    job_id = client.post(f"/api/concepts/{concept_id}/direct",
                         json={"note": "shot 1 slower"}).json()["job_id"]
    job = wait_for_job(job_id)
    assert job["status"] == "done"
    assert "revised" in job["detail"]
    # an empty note is refused before any job exists
    assert client.post(f"/api/concepts/{concept_id}/direct",
                       json={"note": "  "}).status_code == 400


def test_refine_endpoint_surfaces_failure(tmp_db, monkeypatch):
    concept_id = seed_concept(tmp_db)
    monkeypatch.setattr(api_mod, "_gemini_key", lambda: "k")
    import src.director as director
    monkeypatch.setattr(
        director, "refine_shot_prompt",
        lambda cid, n, gemini_client=None, db_path=None:
            {"ok": False, "error": "no technique references reachable"})
    job_id = client.post(
        f"/api/concepts/{concept_id}/shots/1/refine").json()["job_id"]
    job = wait_for_job(job_id)
    assert job["status"] == "failed"
    assert "technique references" in job["error"]


def test_shot_generate_gated_on_the_runway_key(tmp_db, monkeypatch):
    concept_id = seed_concept(tmp_db)
    monkeypatch.delenv("RUNWAYML_API_SECRET", raising=False)
    caps = client.get("/api/capabilities").json()
    assert caps["runway.generate"] is False
    assert caps["runway.spend"] is False     # gate off unless set per run
    response = client.post(f"/api/concepts/{concept_id}/shots/1/generate")
    assert response.status_code == 503


def test_concept_detail_carries_runway_availability(tmp_db, monkeypatch):
    concept_id = seed_concept(tmp_db)
    monkeypatch.delenv("RUNWAYML_API_SECRET", raising=False)
    d = client.get(f"/api/concepts/{concept_id}").json()
    assert d["runway"]["available"] is False
    assert d["runway"]["estimate_usd"] > 0   # priced server-side either way


def test_shot_generate_runs_the_render_as_a_job(tmp_db, monkeypatch):
    concept_id = seed_concept(tmp_db)
    monkeypatch.setattr(api_mod.runway, "has_key", lambda: True)
    monkeypatch.setattr(
        api_mod.runway, "generate_for_shot",
        lambda cid, n, db_path=None: {"ok": True, "media_url": "/renders/runway/x.mp4",
                                      "generation_id": 1, "error": None})
    job_id = client.post(
        f"/api/concepts/{concept_id}/shots/1/generate").json()["job_id"]
    job = wait_for_job(job_id)
    assert job["status"] == "done"
    assert "shot 1" in job["detail"]


def test_shot_generate_surfaces_render_failure(tmp_db, monkeypatch):
    concept_id = seed_concept(tmp_db)
    monkeypatch.setattr(api_mod.runway, "has_key", lambda: True)
    monkeypatch.setattr(
        api_mod.runway, "generate_for_shot",
        lambda cid, n, db_path=None: {"ok": False, "error": "daily cap: 6/6"})
    job_id = client.post(
        f"/api/concepts/{concept_id}/shots/1/generate").json()["job_id"]
    job = wait_for_job(job_id)
    assert job["status"] == "failed"
    assert "daily cap" in job["error"]


# --- holds ------------------------------------------------------------------

def test_holds_resolve_roundtrip(tmp_db):
    hold_id = autonomy.to_hold("antihero", "shadow run", path=tmp_db)
    data = client.get("/api/holds").json()
    assert [h["id"] for h in data["items"]] == [hold_id]
    response = client.post(f"/api/holds/{hold_id}/resolve",
                           json={"status": "approved"})
    assert response.status_code == 200
    assert client.get("/api/holds").json()["items"] == []
    assert client.get("/api/holds").json()["agreement"]["approved"] == 1


def test_holds_resolve_rejects_bad_status(tmp_db):
    hold_id = autonomy.to_hold("antihero", "x", path=tmp_db)
    assert client.post(f"/api/holds/{hold_id}/resolve",
                       json={"status": "meh"}).status_code == 400


# --- evals ------------------------------------------------------------------

def test_golden_crud_and_seed(tmp_db):
    items = client.get("/api/evals/golden").json()["items"]
    assert items, "init should seed the golden set from eval_cases.json"
    new_id = client.post("/api/evals/golden", json={
        "query": "backlit rocks glass", "relevant": ["refs/bar.txt"],
        "source": "probe"}).json()["id"]
    queries = [g["query"] for g in client.get("/api/evals/golden").json()["items"]]
    assert "backlit rocks glass" in queries
    client.delete(f"/api/evals/golden/{new_id}")
    queries = [g["query"] for g in client.get("/api/evals/golden").json()["items"]]
    assert "backlit rocks glass" not in queries


def test_eval_run_computes_and_stores_metrics(tmp_db, monkeypatch):
    for g in evalstore.list_golden(path=tmp_db):
        evalstore.delete_golden(g["id"], path=tmp_db)
    evalstore.add_golden("find the brief", ["prompts/brief.txt"], path=tmp_db)
    evalstore.add_golden("find nothing", ["missing.txt"], path=tmp_db)

    class FakeConn:
        def close(self):
            pass

    monkeypatch.setattr(api_mod, "_gemini_key", lambda: "k")
    monkeypatch.setattr(api_mod, "_rag_reachable", lambda: True)
    monkeypatch.setattr(api_mod.rag, "connect", lambda db_url=None: FakeConn())
    monkeypatch.setattr(api_mod.rag, "make_client", lambda: object())
    monkeypatch.setattr(
        api_mod.rag, "query",
        lambda text, client_, conn, k=5, domain=None:
            [{"source": "prompts/brief.txt", "chunk": "x", "domain": "d",
              "project": None, "source_ref": None, "score": 0.9}])

    job_id = client.post("/api/evals/run", json={}).json()["job_id"]
    job = wait_for_job(job_id)
    assert job["status"] == "done"

    runs = client.get("/api/evals/runs").json()["items"]
    assert len(runs) == 1
    assert runs[0]["hit_rate"] == 0.5      # one hit, one miss
    detail = client.get(f"/api/evals/runs/{runs[0]['id']}").json()
    assert len(detail["per_query"]) == 2
    assert detail["config"]["k"] == api_mod.EVAL_K


def test_eval_run_refuses_empty_golden_set(tmp_db):
    for g in evalstore.list_golden(path=tmp_db):
        evalstore.delete_golden(g["id"], path=tmp_db)
    assert client.post("/api/evals/run", json={}).status_code == 400


# --- analytics --------------------------------------------------------------

def test_analytics_summary_and_posts(tmp_db):
    vid = db.add_video(title="Night ride", platform="youtube",
                       posted_at="2026-08-01", brand="antihero", path=tmp_db)
    db.record_metrics(vid, views=1200, likes=80, path=tmp_db)
    summary = client.get("/api/analytics/summary?brand=antihero").json()
    assert summary["tiles"]["views"] == 1200
    assert summary["tiles"]["videos"] == 1
    assert summary["platform_counts"]["youtube"] == 1
    posts = client.get("/api/analytics/posts?brand=antihero").json()["items"]
    assert posts[0]["title"] == "Night ride"
    assert posts[0]["pct"] == 100.0


def test_video_refresh_maps_failure_to_502(tmp_db, monkeypatch):
    vid = db.add_video(title="v", platform="youtube",
                       posted_at="2026-08-01", path=tmp_db)
    monkeypatch.setattr(api_mod.youtube, "refresh_metrics_for_video",
                        lambda video, api_key=None, db_path=None:
                            {"ok": False, "error": "no key"})
    response = client.post(f"/api/videos/{vid}/refresh")
    assert response.status_code == 502
    assert "no key" in response.json()["error"]["message"]


# --- jobs -------------------------------------------------------------------

def test_jobs_lifecycle_list_and_clear(tmp_db):
    job = jobs.start("test", "quick", lambda j: {"detail": "ok"})
    finished = wait_for_job(job["id"])
    assert finished["detail"] == "ok"
    items = client.get("/api/jobs").json()["items"]
    assert [j["id"] for j in items] == [job["id"]]
    assert client.delete(f"/api/jobs/{job['id']}").status_code == 200
    assert client.get("/api/jobs").json()["items"] == []


def test_running_job_cannot_be_cleared(tmp_db):
    import threading
    gate = threading.Event()
    job = jobs.start("test", "slow", lambda j: gate.wait(2) and None)
    try:
        assert client.delete(f"/api/jobs/{job['id']}").status_code == 409
    finally:
        gate.set()


def test_failed_job_reports_its_error(tmp_db):
    def boom(job):
        raise RuntimeError("model exploded")
    job = jobs.start("test", "boom", boom)
    finished = wait_for_job(job["id"])
    assert finished["status"] == "failed"
    assert "model exploded" in finished["error"]


def test_ui_page_serves_the_shell(tmp_db):
    response = client.get("/ui")
    assert response.status_code == 200
    assert "/static/zpf/app.js" in response.text
    assert "noindex" in response.text
    # the composer's + opens the media panel; picks land in the attach bar
    assert 'id="upmenu"' in response.text
    assert 'id="mgrid"' in response.text
    assert 'id="attachbar"' in response.text
