"""
Tests for the scout's Studio surface -- /api/scout/spark, /api/scout/run,
and the claim that rides with /api/scenes/run.

The behaviour worth pinning here is the CLAIM. A researched spark is
banked once and should seed exactly one generation, but loading it onto
the composer and changing your mind must not burn it -- so the stamp
happens when a run writes something, not when the spark is fetched.
Getting that backwards is silent: the bank just appears to empty itself.

Also pinned: the bin's URL shape. A scouted image is only useful because
it is an ordinary /refs/<sha>.jpg that resolves through the same
_resolve_asset_photo every composer upload does. If that ever diverges,
scouted references stop reaching the render with no error anywhere.
"""
import io
import time

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import api as api_mod
from app import jobs
from app.main import app
from src import db, entities, preprod, refbin, scout

client = TestClient(app)


@pytest.fixture(autouse=True)
def no_real_rag_store(monkeypatch):
    def refused(db_url=None):
        raise ConnectionError("no rag store in tests")
    monkeypatch.setattr(api_mod.rag, "connect", refused)


@pytest.fixture(autouse=True)
def signed_in(monkeypatch):
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
    scout.init(path)
    monkeypatch.setattr(db, "DB_PATH", path)
    return path


def wait_for_job(job_id, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = jobs.get(job_id)
        if job and job["status"] in ("done", "failed", "cancelled"):
            return job
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} never finished")


# ---------- GET /api/scout/spark ----------

def test_an_empty_bank_is_a_200_with_a_null_spark(tmp_db):
    """Not a 404: "nothing researched yet" is a normal state of this
    surface, and the composer renders it as an invitation."""
    res = client.get("/api/scout/spark?brand=zeropage")
    assert res.status_code == 200
    assert res.json()["spark"] is None


def test_spark_comes_back_with_its_reasoning_and_its_bin(tmp_db):
    finding_id = scout.record(
        "zeropage",
        {"spark": "the last check before leaving", "rationale": "night rituals land",
         "evidence": "three top posts this week were pre-ride rituals",
         "sources": ["https://example.com/a"], "score": 0.82},
        pass_id="pass-1", path=tmp_db)
    scout.stash_images("zeropage", "pass-1",
                       [{"lane": "shorts", "detail": "a night ride",
                         "url": "https://yt/watch?v=1", "image": "https://img/1.jpg",
                         "metric": "1,000 views"}],
                       path=tmp_db, fetch=lambda u: "/refs/abc.jpg")

    body = client.get("/api/scout/spark?brand=zeropage").json()

    assert body["spark"] == "the last check before leaving"
    assert body["finding_id"] == finding_id
    assert body["evidence"].startswith("three top posts")
    assert body["sources"] == ["https://example.com/a"]
    assert body["bin"][0]["url"] == "/refs/abc.jpg"
    assert body["bin"][0]["source_url"] == "https://yt/watch?v=1"


def test_a_bin_image_url_is_the_same_shape_a_composer_upload_gets(tmp_db):
    """The whole reason the scout writes into data/refs: a scouted image
    has to resolve through the one resolver every reference goes
    through, or it silently never reaches the render."""
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (20, 20, 24)).save(buf, "JPEG")
    url = refbin.save(buf.getvalue())

    assert url.startswith("/refs/") and url.endswith(".jpg")
    assert api_mod._resolve_asset_photo(url) is not None


def test_fetching_a_spark_does_not_claim_it(tmp_db):
    scout.record("zeropage", {"spark": "a researched idea", "score": 0.9},
                 pass_id="p", path=tmp_db)

    client.get("/api/scout/spark?brand=zeropage")
    client.get("/api/scout/spark?brand=zeropage")

    # still servable -- reading is not deciding
    assert scout.next_spark("zeropage", path=tmp_db)["spark"] == "a researched idea"


def test_the_brand_scopes_the_bank(tmp_db):
    scout.record("zeropage", {"spark": "a faceless one", "score": 0.9},
                 pass_id="p", path=tmp_db)
    assert client.get("/api/scout/spark?brand=antihero").json()["spark"] is None
    assert client.get("/api/scout/spark?brand=zeropage").json()["spark"]


# ---------- POST /api/scout/run ----------

def test_run_without_a_key_is_a_503_not_a_dead_job(tmp_db, monkeypatch):
    monkeypatch.setattr(api_mod, "_gemini_key", lambda: None)
    res = client.post("/api/scout/run", json={"brand": "zeropage"})
    assert res.status_code == 503
    assert res.json()["error"]["code"] == "generation_unavailable"


def test_run_banks_what_the_pass_found(tmp_db, monkeypatch):
    monkeypatch.setattr(api_mod, "_gemini_key", lambda: "test-key")
    monkeypatch.setattr(api_mod.scout, "scout", lambda brand, count, path=None: {
        "ok": True, "signals": 5, "pass_id": "p",
        "findings": [{"spark": "a crawled idea", "score": 0.8}],
        "bin": [{"url": "/refs/a.jpg"}], "errors": []})

    job_id = client.post("/api/scout/run", json={"brand": "zeropage"}).json()["job_id"]
    job = wait_for_job(job_id)

    assert job["status"] == "done"
    assert "1 spark(s)" in job["detail"] and "1 image(s)" in job["detail"]


def test_a_crawl_that_finds_nothing_fails_the_job_loudly(tmp_db, monkeypatch):
    """A silent empty crawl looks exactly like a healthy one."""
    monkeypatch.setattr(api_mod, "_gemini_key", lambda: "test-key")
    monkeypatch.setattr(api_mod.scout, "scout", lambda brand, count, path=None: {
        "ok": False, "signals": 0, "pass_id": "p", "findings": [], "bin": [],
        "errors": ["every lane came back empty"]})

    job_id = client.post("/api/scout/run", json={"brand": "zeropage"}).json()["job_id"]
    job = wait_for_job(job_id)

    assert job["status"] == "failed"
    assert "every lane came back empty" in (job.get("error") or "")


# ---------- the claim, on the way through Create ----------

def test_create_claims_the_spark_it_actually_generated_from(tmp_db, monkeypatch):
    finding_id = scout.record("zeropage", {"spark": "a researched idea", "score": 0.9},
                              pass_id="p", path=tmp_db)
    monkeypatch.setattr(api_mod, "_gemini_key", lambda: "test-key")

    from src import scene_chain
    monkeypatch.setattr(scene_chain, "run", lambda *a, **k: {
        "scenes": [{"concept_id": 77}], "notes": [], "prompt_template": "t"})

    job_id = client.post("/api/scenes/run", data={
        "idea": "a researched idea", "brand": "zeropage", "count": "1",
        "scout_finding_id": str(finding_id)}).json()["job_id"]
    assert wait_for_job(job_id)["status"] == "done"

    assert scout.next_spark("zeropage", path=tmp_db) is None
    [row] = [r for r in scout.list_findings(path=tmp_db) if r["id"] == finding_id]
    assert row["run_id"] == "concept:77"


def test_create_without_a_finding_id_claims_nothing(tmp_db, monkeypatch):
    scout.record("zeropage", {"spark": "a researched idea", "score": 0.9},
                 pass_id="p", path=tmp_db)
    monkeypatch.setattr(api_mod, "_gemini_key", lambda: "test-key")

    from src import scene_chain
    monkeypatch.setattr(scene_chain, "run", lambda *a, **k: {
        "scenes": [{"concept_id": 78}], "notes": [], "prompt_template": "t"})

    job_id = client.post("/api/scenes/run", data={
        "idea": "something Mike typed himself", "brand": "zeropage",
        "count": "1"}).json()["job_id"]
    assert wait_for_job(job_id)["status"] == "done"

    assert scout.next_spark("zeropage", path=tmp_db) is not None


def test_a_generation_that_writes_nothing_leaves_the_spark_unclaimed(tmp_db, monkeypatch):
    finding_id = scout.record("zeropage", {"spark": "a researched idea", "score": 0.9},
                              pass_id="p", path=tmp_db)
    monkeypatch.setattr(api_mod, "_gemini_key", lambda: "test-key")

    from src import scene_chain
    def no_scene(*a, **k):
        raise RuntimeError("the model returned no usable scene")
    monkeypatch.setattr(scene_chain, "run", no_scene)

    job_id = client.post("/api/scenes/run", data={
        "idea": "a researched idea", "brand": "zeropage", "count": "1",
        "scout_finding_id": str(finding_id)}).json()["job_id"]
    assert wait_for_job(job_id)["status"] == "failed"

    assert scout.next_spark("zeropage", path=tmp_db) is not None


# ---------- capability gating ----------

def test_scout_capability_follows_the_gemini_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    assert api_mod.compute_capabilities()["scout"] is False

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    assert api_mod.compute_capabilities()["scout"] is True


# ---------- the two paths stay separate at the route ----------

def test_a_typed_idea_never_consults_the_scout(tmp_db, monkeypatch):
    """Create is Mike's own path. Even with a full bank, nothing about
    the scout may touch the idea he typed."""
    scout.record("zeropage", {"spark": "a crawled idea", "score": 0.99},
                 pass_id="p", path=tmp_db)
    monkeypatch.setattr(api_mod, "_gemini_key", lambda: "test-key")

    consulted = []
    monkeypatch.setattr(api_mod.scout, "next_spark",
                        lambda *a, **k: consulted.append(1) or None)

    seen = {}
    from src import scene_chain
    monkeypatch.setattr(scene_chain, "run", lambda idea, brand, **k: seen.update(
        idea=idea, refs=list(k.get("refs") or [])) or {
            "scenes": [{"concept_id": 90}], "notes": [], "prompt_template": "t"})

    job_id = client.post("/api/scenes/run", data={
        "idea": "a monster in the garage at 3am", "brand": "zeropage",
        "count": "1"}).json()["job_id"]
    assert wait_for_job(job_id)["status"] == "done"

    assert consulted == []                                  # bank untouched
    assert seen["idea"] == "a monster in the garage at 3am"  # idea unaltered
    assert seen["refs"] == []                                # no research images
    # read the bank directly -- next_spark is the stub above, so asking it
    # would only prove the stub still returns what the stub returns
    assert scout.list_findings(brand="zeropage", unused_only=True, path=tmp_db)


def test_a_stale_finding_id_cannot_burn_a_spark_he_did_not_use(tmp_db, monkeypatch):
    """The leak this closes. Load a researched spark, type your own idea
    over it, press Create: the composer's id is stale, and trusting it
    would claim a spark that never wrote anything -- silently, out of the
    one place research is kept. The server compares before claiming."""
    finding_id = scout.record("zeropage", {"spark": "the last check before leaving",
                                           "score": 0.9}, pass_id="p", path=tmp_db)
    monkeypatch.setattr(api_mod, "_gemini_key", lambda: "test-key")

    from src import scene_chain
    monkeypatch.setattr(scene_chain, "run", lambda *a, **k: {
        "scenes": [{"concept_id": 91}], "notes": [], "prompt_template": "t"})

    job_id = client.post("/api/scenes/run", data={
        "idea": "a monster in the garage at 3am",      # NOT the spark
        "brand": "zeropage", "count": "1",
        "scout_finding_id": str(finding_id)}).json()["job_id"]
    assert wait_for_job(job_id)["status"] == "done"

    assert scout.next_spark("zeropage", path=tmp_db)["spark"] == \
        "the last check before leaving"


def test_the_spark_is_still_claimed_when_he_only_fixed_the_capitals(tmp_db, monkeypatch):
    finding_id = scout.record("zeropage", {"spark": "the last check before leaving",
                                           "score": 0.9}, pass_id="p", path=tmp_db)
    monkeypatch.setattr(api_mod, "_gemini_key", lambda: "test-key")

    from src import scene_chain
    monkeypatch.setattr(scene_chain, "run", lambda *a, **k: {
        "scenes": [{"concept_id": 92}], "notes": [], "prompt_template": "t"})

    job_id = client.post("/api/scenes/run", data={
        "idea": "The Last Check, Before Leaving.", "brand": "zeropage",
        "count": "1", "scout_finding_id": str(finding_id)}).json()["job_id"]
    assert wait_for_job(job_id)["status"] == "done"

    assert scout.next_spark("zeropage", path=tmp_db) is None


def test_his_own_idea_does_not_inherit_the_research_images(tmp_db, monkeypatch):
    """The second half of the boundary, and the one with teeth: those
    photos become the shot's `refs`, and refs[0] is the frame Runway
    anchors the clip on. An idea he typed himself, anchored on a
    stranger's thumbnail, is not his idea."""
    finding_id = scout.record("zeropage", {"spark": "the last check before leaving",
                                           "score": 0.9}, pass_id="p", path=tmp_db)
    scout.stash_images("zeropage", "p",
                       [{"lane": "shorts", "detail": "a clip", "image": "https://i/1.jpg"}],
                       path=tmp_db, fetch=lambda u: "/refs/research.jpg")
    monkeypatch.setattr(api_mod, "_gemini_key", lambda: "test-key")

    seen = {}
    from src import scene_chain
    monkeypatch.setattr(scene_chain, "run", lambda idea, brand, **k: seen.update(
        refs=list(k.get("refs") or [])) or {
            "scenes": [{"concept_id": 93}], "notes": [], "prompt_template": "t"})

    job_id = client.post("/api/scenes/run", data={
        "idea": "a monster in the garage at 3am",         # his own
        "brand": "zeropage", "count": "1",
        "scout_finding_id": str(finding_id),
        "asset_photos": "/refs/research.jpg"}).json()["job_id"]
    assert wait_for_job(job_id)["status"] == "done"

    assert seen["refs"] == []


def test_his_own_photos_survive_when_the_research_is_dropped(tmp_db, monkeypatch):
    """Only the scouted pass's images are refused. A photo he picked out
    of his own asset bank in the same submission is his, and stays."""
    finding_id = scout.record("zeropage", {"spark": "the last check before leaving",
                                           "score": 0.9}, pass_id="p", path=tmp_db)
    scout.stash_images("zeropage", "p",
                       [{"lane": "shorts", "detail": "a clip", "image": "https://i/1.jpg"}],
                       path=tmp_db, fetch=lambda u: "/refs/research.jpg")
    monkeypatch.setattr(api_mod, "_gemini_key", lambda: "test-key")
    monkeypatch.setattr(api_mod, "_resolve_asset_photo", lambda url: None)

    seen = {}
    from src import scene_chain
    monkeypatch.setattr(scene_chain, "run", lambda idea, brand, **k: seen.update(
        refs=list(k.get("refs") or [])) or {
            "scenes": [{"concept_id": 94}], "notes": [], "prompt_template": "t"})

    res = client.post("/api/scenes/run", data={
        "idea": "a monster in the garage at 3am",
        "brand": "zeropage", "count": "1",
        "scout_finding_id": str(finding_id),
        "asset_photos": ["/refs/research.jpg",                   # the scout's
                         "/characters/michael/photo/a.jpg"],     # his own
    })
    assert wait_for_job(res.json()["job_id"])["status"] == "done"

    assert seen["refs"] == ["/characters/michael/photo/a.jpg"]


def test_the_research_images_ride_along_when_the_spark_is_used(tmp_db, monkeypatch):
    """The other direction: using the spark as written keeps its bin."""
    finding_id = scout.record("zeropage", {"spark": "the last check before leaving",
                                           "score": 0.9}, pass_id="p", path=tmp_db)
    scout.stash_images("zeropage", "p",
                       [{"lane": "shorts", "detail": "a clip", "image": "https://i/1.jpg"}],
                       path=tmp_db, fetch=lambda u: "/refs/research.jpg")
    monkeypatch.setattr(api_mod, "_gemini_key", lambda: "test-key")
    monkeypatch.setattr(api_mod, "_resolve_asset_photo", lambda url: None)

    seen = {}
    from src import scene_chain
    monkeypatch.setattr(scene_chain, "run", lambda idea, brand, **k: seen.update(
        refs=list(k.get("refs") or [])) or {
            "scenes": [{"concept_id": 95}], "notes": [], "prompt_template": "t"})

    job_id = client.post("/api/scenes/run", data={
        "idea": "the last check before leaving",
        "brand": "zeropage", "count": "1",
        "scout_finding_id": str(finding_id),
        "asset_photos": "/refs/research.jpg"}).json()["job_id"]
    assert wait_for_job(job_id)["status"] == "done"

    assert seen["refs"] == ["/refs/research.jpg"]
