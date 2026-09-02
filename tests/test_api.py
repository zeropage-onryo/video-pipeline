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
    preprod.add_location("garage", {"space": "low key garage"}, path=tmp_db, account_id=None)
    entities.add_character(name="Michael", role="rider", path=tmp_db, account_id=None)
    entities.add_prop(name="Ducati 959", category="vehicle", path=tmp_db, account_id=None)

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
    
        account_id=None,)


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
    # the Create button writes ONE scene prompt per concept now
    monkeypatch.setattr(
        shootgen, "generate_scene_concept",
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
    preprod.add_location("garage", {"space": "the garage"}, path=tmp_db, account_id=None)
    media = client.get("/api/media").json()
    assert media["counts"] == {"all": 1, "location": 1, "character": 0, "prop": 0}
    item = media["items"][0]
    assert item["asset_name"] == "garage"
    assert item["url"].startswith("/locations/garage/photo/plate.jpg")
    assert len(item["date"]) == 10   # a real ISO date from the file's mtime


def test_pipeline_run_carries_picked_media_as_image_refs(tmp_db, photo_root,
                                                         monkeypatch):
    preprod.add_location("garage", {"space": "the garage"}, path=tmp_db, account_id=None)
    seen = {}
    import src.shootgen as shootgen
    monkeypatch.setattr(shootgen, "reference_block", lambda **k: "")

    def fake_generate(**kwargs):
        seen.update(kwargs)
        return {"concept_id": 1, "concept": {"title": "T"}, "warnings": []}

    monkeypatch.setattr(shootgen, "generate_scene_concept", fake_generate)
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
    assert preprod.get_concept(concept_id, path=tmp_db, account_id=None) is None


def test_deny_validates_reasons(tmp_db):
    concept_id = seed_concept(tmp_db)
    response = client.post(f"/api/concepts/{concept_id}/deny",
                           json={"reasons": ["not a reason"]})
    assert response.status_code == 400
    assert preprod.get_concept(concept_id, path=tmp_db, account_id=None) is not None


def test_approve_writes_the_scene_via_job(tmp_db, monkeypatch):
    """Approve on an idea writes ITS one scene prompt (2026-08-26) --
    stage two used to explode it into a shot list."""
    import src.shootgen as shootgen
    monkeypatch.setattr(shootgen, "reference_block", lambda **k: "")
    seen = {}

    def fake(concept_id, **kwargs):
        seen["concept_id"] = concept_id
        return {"concept_id": concept_id, "shots": [{"n": 1}], "warnings": []}

    monkeypatch.setattr(shootgen, "write_scene_for_concept", fake)
    monkeypatch.setattr(api_mod, "_gemini_key", lambda: "k")
    monkeypatch.setattr("google.genai.Client", lambda **k: object())
    concept_id = seed_concept(tmp_db, "An Idea")      # no shots yet

    job_id = client.post(f"/api/concepts/{concept_id}/approve").json()["job_id"]
    job = wait_for_job(job_id)
    assert job["status"] == "done"
    assert seen["concept_id"] == concept_id
    assert "scene written" in job["detail"]


def test_approve_refuses_a_concept_that_already_has_its_scene(tmp_db):
    """Nothing to write, and re-writing would silently replace the
    prompt someone may already have graded."""
    concept_id = seed_concept(tmp_db, "Done", shots=[
        {"n": 1, "type": "BROLL", "source": "AI", "tool": "RUNWAY", "prompt": "p"}])
    response = client.post(f"/api/concepts/{concept_id}/approve")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "already_written"

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
        lambda cid, n, db_path=None, resolve_photo=None: {
            "ok": True, "media_url": "/renders/runway/x.mp4",
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
        lambda cid, n, db_path=None, resolve_photo=None: {
            "ok": False, "error": "daily cap: 6/6"})
    job_id = client.post(
        f"/api/concepts/{concept_id}/shots/1/generate").json()["job_id"]
    job = wait_for_job(job_id)
    assert job["status"] == "failed"
    assert "daily cap" in job["error"]


# --- holds ------------------------------------------------------------------

def test_holds_resolve_roundtrip(tmp_db):
    hold_id = autonomy.to_hold("antihero", "shadow run", path=tmp_db, account_id=None)
    data = client.get("/api/holds").json()
    assert [h["id"] for h in data["items"]] == [hold_id]
    response = client.post(f"/api/holds/{hold_id}/resolve",
                           json={"status": "approved"})
    assert response.status_code == 200
    assert client.get("/api/holds").json()["items"] == []
    assert client.get("/api/holds").json()["agreement"]["approved"] == 1


def test_holds_resolve_rejects_bad_status(tmp_db):
    hold_id = autonomy.to_hold("antihero", "x", path=tmp_db, account_id=None)
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
    assert detail["config"]["k"] == api_mod._eval_k()


def test_eval_run_refuses_empty_golden_set(tmp_db):
    for g in evalstore.list_golden(path=tmp_db):
        evalstore.delete_golden(g["id"], path=tmp_db)
    assert client.post("/api/evals/run", json={}).status_code == 400


# --- analytics --------------------------------------------------------------

def test_analytics_summary_and_posts(tmp_db):
    vid = db.add_video(title="Night ride", platform="youtube",
                       posted_at="2026-08-01", brand="antihero", path=tmp_db, account_id=None)
    db.record_metrics(vid, views=1200, likes=80, path=tmp_db, account_id=None)
    summary = client.get("/api/analytics/summary?brand=antihero").json()
    assert summary["tiles"]["views"] == 1200
    assert summary["tiles"]["videos"] == 1
    assert summary["platform_counts"]["youtube"] == 1
    posts = client.get("/api/analytics/posts?brand=antihero").json()["items"]
    assert posts[0]["title"] == "Night ride"
    assert posts[0]["pct"] == 100.0


def test_video_refresh_maps_failure_to_502(tmp_db, monkeypatch):
    vid = db.add_video(title="v", platform="youtube",
                       posted_at="2026-08-01", path=tmp_db, account_id=None)
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


# --- asset creation + the RAG assets shelf ----------------------------------
# The always-on create path: /ui's Assets view posts here, and every
# save also lands a chunk on the "assets" shelf so the new entity is
# retrievable through the same grounding path reference_block uses.

TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
    b"\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05"
    b"\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


class _RagConn:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


@pytest.fixture
def rag_recorder(monkeypatch):
    """A reachable fake store: every ingest_records call is recorded so
    the tests can assert what actually landed on the shelf."""
    records = []
    # api_mod.rag and asset_shelf.rag are the same module object, so one
    # patch covers the route and the shelf writer underneath it.
    monkeypatch.setattr(api_mod.rag, "connect", lambda db_url=None: _RagConn())
    monkeypatch.setattr(api_mod.rag, "init_store", lambda c: None)
    monkeypatch.setattr(api_mod.rag, "make_client", lambda: object())
    monkeypatch.setattr(api_mod.rag, "ingest_records",
                        lambda recs, client_, conn: records.extend(recs) or len(recs))
    return records


ENTITY_VISION = {
    "look": "a man in a cracked black leather jacket",
    "features": ["scar through the left eyebrow"],
    "materials": ["black leather"],
    "continuity": "jacket zipped to mid-chest",
}


@pytest.fixture
def fake_vision(monkeypatch):
    """The cast/prop vision step, patched at the function the route
    actually calls. Without this the route builds a real Gemini client
    and the network guard fires inside a try/except that swallows it --
    green, but proving nothing."""
    import src.locations as locations_mod
    seen = []

    def fake(client, kind, name, photos):
        seen.append({"kind": kind, "name": name, "photos": len(photos)})
        return ENTITY_VISION

    monkeypatch.setattr(locations_mod, "describe_entity", fake)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    return seen


def test_create_character_describes_its_photos_and_shelves_the_look(
        tmp_db, tmp_path, monkeypatch, rag_recorder, fake_vision):
    """The photos are the point: an undescribed character retrieves on
    its typed name alone, never on how it looks."""
    monkeypatch.setattr(api_mod, "CHARACTERS_DIR", tmp_path / "characters")
    res = client.post("/api/assets/characters",
                      data={"name": "Mike", "role": "protagonist",
                            "notes": "leather jacket, deadpan"},
                      files=[("photos", ("a.png", TINY_PNG, "image/png"))])
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] and body["described"] is True and body["rag"]["ok"]
    assert (tmp_path / "characters" / "mike" / "a.png").exists()
    # the vision step saw the photo that was just written
    assert fake_vision == [{"kind": "character", "name": "Mike", "photos": 1}]

    [row] = entities.list_characters(path=tmp_db, account_id=None)
    assert row["name"] == "Mike" and row["photo_count"] == 1
    assert row["description"]["look"].startswith("a man in a cracked")
    assert row["description"]["notes"] == "leather jacket, deadpan"

    [record] = rag_recorder
    assert record["domain"] == "assets"
    assert record["source"] == "assets/character-mike"
    assert "protagonist" in record["text"]
    assert "scar through the left eyebrow" in record["text"]   # searchable


def test_create_character_survives_a_failed_vision_call(
        tmp_db, tmp_path, monkeypatch, rag_recorder):
    """Degrade, don't break: the photos and the row must survive a dead
    vision call -- the locations contract, applied to cast."""
    import src.locations as locations_mod
    monkeypatch.setattr(api_mod, "CHARACTERS_DIR", tmp_path / "characters")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    def boom(client, kind, name, photos):
        raise RuntimeError("vision unavailable")

    monkeypatch.setattr(locations_mod, "describe_entity", boom)
    res = client.post("/api/assets/characters",
                      data={"name": "Mike", "role": "protagonist"},
                      files=[("photos", ("a.png", TINY_PNG, "image/png"))])
    body = res.json()
    assert body["ok"] is True and body["described"] is False
    assert "vision unavailable" in body["note"]
    assert (tmp_path / "characters" / "mike" / "a.png").exists()
    assert entities.list_characters(path=tmp_db, account_id=None)[0]["name"] == "Mike"
    assert rag_recorder                       # still shelved, just thinner


def test_create_prop_saves_and_teaches_the_assets_shelf(
        tmp_db, tmp_path, monkeypatch, rag_recorder, fake_vision):
    monkeypatch.setattr(api_mod, "PROPS_DIR", tmp_path / "props")
    res = client.post("/api/assets/props",
                      data={"name": "Ducati Panigale", "category": "vehicle",
                            "notes": "red, scuffed left fairing"})
    body = res.json()
    assert body["ok"]
    assert body["described"] is False and body["note"] == "no photos to describe"
    assert fake_vision == []                  # nothing to look at, no billed call
    [record] = rag_recorder
    assert record["source"] == "assets/prop-ducati-panigale"
    assert "vehicle" in record["text"] and "scuffed" in record["text"]


def test_assets_backfill_runs_as_a_job(tmp_db, monkeypatch):
    """The catch-up for assets created before the shelf existed."""
    calls = {}

    def fake_backfill(db_path=None, describe=False, gemini_client=None):
        calls.update(describe=describe, client=gemini_client)
        return {"ingested": 3, "described": 0, "failed": 0,
                "skipped_no_photos": 0, "errors": []}

    monkeypatch.setattr(api_mod.asset_shelf, "backfill", fake_backfill)
    job_id = client.post("/api/assets/backfill", json={}).json()["job_id"]
    job = wait_for_job(job_id)
    assert job["status"] == "done"
    assert "3 on the shelf" in job["detail"]
    assert calls["describe"] is False and calls["client"] is None


def test_assets_backfill_describe_needs_a_key(tmp_db, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    res = client.post("/api/assets/backfill", json={"describe": True})
    assert res.status_code == 503


def test_create_location_describes_and_teaches(tmp_db, tmp_path, monkeypatch,
                                               rag_recorder):
    import src.locations as locations_mod
    monkeypatch.setattr(api_mod, "LOCATIONS_DIR", tmp_path / "locations")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(locations_mod, "describe_location",
                        lambda client_, name, photos:
                        {"space": f"{name} described from {len(photos)}"})
    res = client.post("/api/assets/locations",
                      data={"name": "garage"},
                      files=[("photos", ("a.png", TINY_PNG, "image/png")),
                             ("photos", ("b.png", TINY_PNG, "image/png"))])
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] and body["described"] is True
    saved = preprod.get_location_by_name("garage", path=tmp_db, account_id=None)
    assert saved is not None and saved["photo_count"] == 2
    [record] = rag_recorder
    assert record["source"] == "assets/location-garage"
    assert "described from 2" in record["text"]
    assert record["domain"] == "assets"


def test_create_location_without_a_key_keeps_the_photos(tmp_db, tmp_path,
                                                        monkeypatch, rag_recorder):
    monkeypatch.setattr(api_mod, "LOCATIONS_DIR", tmp_path / "locations")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    res = client.post("/api/assets/locations",
                      data={"name": "garage"},
                      files=[("photos", ("a.png", TINY_PNG, "image/png"))])
    body = res.json()
    assert body["ok"] and body["described"] is False
    assert "GEMINI_API_KEY" in body["note"]
    assert (tmp_path / "locations" / "garage" / "a.png").exists()


def test_create_location_requires_name_and_photo(tmp_db, tmp_path, monkeypatch):
    monkeypatch.setattr(api_mod, "LOCATIONS_DIR", tmp_path / "locations")
    no_name = client.post("/api/assets/locations", data={"name": "  "},
                          files=[("photos", ("a.png", TINY_PNG, "image/png"))])
    assert no_name.status_code == 400
    no_photo = client.post("/api/assets/locations", data={"name": "garage"})
    assert no_photo.status_code == 400


def test_create_location_sanitises_the_name(tmp_db, tmp_path, monkeypatch,
                                            rag_recorder):
    monkeypatch.setattr(api_mod, "LOCATIONS_DIR", tmp_path / "locations")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    client.post("/api/assets/locations", data={"name": "../../etc/evil"},
                files=[("photos", ("a.png", TINY_PNG, "image/png"))])
    assert not (tmp_path / "etc").exists()
    assert not (tmp_path.parent / "etc").exists()


def test_delete_character_drops_the_shelf_chunk(tmp_db, monkeypatch):
    dropped = []
    monkeypatch.setattr(api_mod.rag, "connect", lambda db_url=None: _RagConn())
    monkeypatch.setattr(api_mod.rag, "delete_source",
                        lambda conn, source: dropped.append(source) or 1)
    cid = entities.add_character("Mike", role="protagonist", path=tmp_db, account_id=None)
    res = client.delete(f"/api/assets/characters/{cid}")
    assert res.json()["deleted"] == cid
    assert entities.list_characters(path=tmp_db, account_id=None) == []
    assert dropped == ["assets/character-mike"]
    assert client.delete(f"/api/assets/characters/{cid}").status_code == 404


def test_create_asset_survives_a_down_store(tmp_db, tmp_path, monkeypatch):
    """The degrade contract: the save always lands; the shelf chunk is
    best-effort and its failure is reported, not raised."""
    monkeypatch.setattr(api_mod, "PROPS_DIR", tmp_path / "props")
    # autouse fixture already makes rag.connect raise
    res = client.post("/api/assets/props", data={"name": "Helmet"})
    body = res.json()
    assert body["ok"] is True
    assert body["rag"]["ok"] is False
    assert entities.list_props(path=tmp_db, account_id=None)[0]["name"] == "Helmet"


def test_holds_resolve_writes_the_prompt_verdict(tmp_db):
    """One tap grades both trust numbers: the hold row AND the credit
    gate's prompt_scores for the run (moved from the retired /holds
    page's route to the API twin)."""
    autonomy.log_prompt_scores("runX", [
        {"prompt": "p", "score": 9, "pass": True, "reason": "", "dims": {}}],
        path=tmp_db)
    hold_id = autonomy.to_hold("zeropage", "shadow", payload={"run_id": "runX"},
                               path=tmp_db, account_id=None)
    client.post(f"/api/holds/{hold_id}/resolve", json={"status": "rejected"})
    gate = autonomy.prompt_gate_agreement(path=tmp_db)
    assert gate["graded"] == 1
    assert gate["passed_but_rejected"] == 1
