"""
Tests for the Pipeline restructure (2026-08-25): Concept / Generate /
Director as three faces onto one engine.

Covers the new backend this brought: the presets file + loader, the
`@`-mention cross-category asset search, Director's chat-first landing
payload, the Generate tab's one-shot run (Ground -> Enhance -> saved
one-shot concept -> honestly-gated render), the Director save-back
routes (per-shot prompt + reference), and video references (inline
bytes vs the Gemini Files API).

Hermetic throughout, the test_workflows.py discipline: every model-
touching function is patched at the function the code actually calls
(the network guard screams otherwise), and jobs are polled to
completion so a silently-dead thread fails loudly.
"""
import time

import pytest
from fastapi.testclient import TestClient

from app import api, jobs
from app.main import app
from src import db, entities, generative, preprod, presets, shootgen, workflows

client = TestClient(app)


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
    workflows.init(path)
    generative.init(path)
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


def seed_concept(path, shots=None, brand="antihero"):
    concept = {"title": "Night ride", "hook": "the hook", "logline": "the log",
               "shots": shots if shots is not None else [
                   {"n": 1, "type": "BROLL", "source": "AI", "tool": "RUNWAY",
                    "desc": "tank badge macro", "prompt": "macro of the tank badge"}]}
    return preprod.save_concept(concept, brand=brand, spark="spark", path=path)


# --- presets ----------------------------------------------------------------

def test_presets_file_loads_real_scaffolds():
    items = presets.load_presets()
    assert items, "prompts/presets.json should ship non-empty"
    for p in items:
        assert p["id"] and p["label"] and p["how"]
    assert presets.get_preset(items[0]["id"]) == items[0]
    assert presets.get_preset("nope") is None
    assert presets.get_preset(None) is None


def test_presets_loader_degrades_on_a_broken_file(tmp_path):
    broken = tmp_path / "presets.json"
    broken.write_text("{not json")
    assert presets.load_presets(path=broken) == []
    assert presets.load_presets(path=tmp_path / "absent.json") == []


def test_api_presets(tmp_db):
    res = client.get("/api/presets").json()
    assert res["items"] == presets.load_presets()


# --- @ mention asset search -------------------------------------------------

def test_assets_search_is_cross_category_and_prefix_first(tmp_db):
    preprod.add_location("garage", {"space": "a dim garage"}, path=tmp_db)
    entities.add_character("Juno", role="the dog", path=tmp_db)
    entities.add_prop("Ducati Monster", category="vehicle", path=tmp_db)

    res = client.get("/api/assets/search?q=ju").json()
    assert [i["name"] for i in res["items"]] == ["Juno"]
    assert res["items"][0]["category"] == "character"
    assert "thumb" in res["items"][0]

    # substring matches rank after prefix matches
    res = client.get("/api/assets/search?q=a").json()
    names = [i["name"] for i in res["items"]]
    assert set(names) == {"garage", "Ducati Monster"}
    # empty q lists everything (capped)
    res = client.get("/api/assets/search").json()
    assert {i["category"] for i in res["items"]} == {"location", "character", "prop"}


# --- director landing -------------------------------------------------------

def test_director_landing_zeropage_chips_are_the_real_formats(tmp_db):
    res = client.get("/api/director/landing?brand=zeropage").json()
    assert res["brand"] == "zeropage"
    assert [c["label"] for c in res["chips"]] == \
        [name for name, _ in shootgen.ZEROPAGE_FORMATS[:4]]
    assert res["chips"][0]["text"] == shootgen.ZEROPAGE_FORMATS[0][1]


def test_director_landing_antihero_has_sample_but_no_chips(tmp_db):
    res = client.get("/api/director/landing?brand=antihero").json()
    assert res["chips"] == []
    # the sample brief is the gold-standard exemplar's opening blocks,
    # not invented placeholder copy
    gold = shootgen.gold_standard_example()
    assert res["sample_prompt"]
    assert res["sample_prompt"] in gold


# --- director save-back: per-shot prompt + reference ------------------------

def test_shot_prompt_update_persists_and_leaves_the_pick_alone(tmp_db):
    concept_id = seed_concept(tmp_db)
    res = client.post(f"/api/concepts/{concept_id}/shots/1/prompt",
                      json={"prompt": "a much better prompt"})
    assert res.status_code == 200
    stored = preprod.get_concept(concept_id, path=tmp_db, account_id=None)
    assert stored["shots"][0]["prompt"] == "a much better prompt"
    assert stored["title"] == "Night ride"          # the pick is never rewritten
    assert stored["hook"] == "the hook"


def test_shot_prompt_update_refuses_empty_and_404s(tmp_db):
    concept_id = seed_concept(tmp_db)
    assert client.post(f"/api/concepts/{concept_id}/shots/1/prompt",
                       json={"prompt": "  "}).status_code == 400
    assert client.post(f"/api/concepts/{concept_id}/shots/9/prompt",
                       json={"prompt": "x"}).status_code == 404
    assert client.post("/api/concepts/999/shots/1/prompt",
                       json={"prompt": "x"}).status_code == 404


def test_shot_reference_attach_and_clear(tmp_db):
    concept_id = seed_concept(tmp_db)
    res = client.post(f"/api/concepts/{concept_id}/shots/1/reference",
                      json={"url": "https://example.com/frame.png"})
    assert res.status_code == 200
    assert preprod.get_concept(concept_id, path=tmp_db, account_id=None)["shots"][0][
        "reference_image"] == "https://example.com/frame.png"
    # empty clears -- a reference is an enhancement, never a gate
    client.post(f"/api/concepts/{concept_id}/shots/1/reference", json={"url": ""})
    assert "reference_image" not in \
        preprod.get_concept(concept_id, path=tmp_db, account_id=None)["shots"][0]
    assert client.post(f"/api/concepts/{concept_id}/shots/1/reference",
                       json={"url": "ftp://nope"}).status_code == 400


# --- the generate tab -------------------------------------------------------

@pytest.fixture
def hermetic_generate(monkeypatch):
    """Patch every model-touching call the generate run makes."""
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr("src.shootgen.reference_block",
                        lambda spark=None, client=None, db_path=None: "REFS")
    calls = {}

    def fake_enhance(gemini_client, prompt, *, preset=None, references="",
                     image_refs=None, video_refs=None):
        calls["preset"] = preset
        calls["references"] = references
        calls["image_refs"] = list(image_refs or [])
        calls["video_refs"] = list(video_refs or [])
        return f"ENHANCED[{prompt}]"

    monkeypatch.setattr(api, "_enhance_generate_prompt", fake_enhance)
    # genai.Client would try to build a real client from the fake key
    import google.genai as genai_mod
    monkeypatch.setattr(genai_mod, "Client", lambda api_key=None: object())
    return calls


def test_generate_run_saves_a_real_one_shot_concept(tmp_db, hermetic_generate,
                                                    monkeypatch):
    monkeypatch.setattr("src.nano_banana.generate_from_prompt",
                        lambda prompt, reference_image=None, db_path=None:
                        {"ok": True, "media_url": "/renders/frame.png"})
    job_id = client.post("/api/generate/run", data={
        "prompt": "the Ducati tank badge, low key",
        "preset": "slow_push_in", "output": "image",
    }).json()["job_id"]
    job = wait_for_job(job_id)
    assert job["status"] == "done"

    concept = preprod.get_concept(job["ref_id"], path=tmp_db, account_id=None)
    assert concept is not None
    assert len(concept["shots"]) == 1
    shot = concept["shots"][0]
    assert shot["source"] == "AI" and shot["tool"] == "RUNWAY"
    assert shot["prompt"] == "ENHANCED[the Ducati tank badge, low key]"
    assert shot["desc"] == "the Ducati tank badge, low key"
    # the Nano image lands as the shot's reference anchor
    assert shot["reference_image"] == "/renders/frame.png"
    assert concept["spark"] == "the Ducati tank badge, low key"
    assert concept["warnings"] == []
    # the preset actually reached the enhance step
    assert hermetic_generate["preset"]["id"] == "slow_push_in"
    assert hermetic_generate["references"] == "REFS"
    assert job["output"].startswith("ENHANCED[")


def test_generate_run_attaches_to_an_existing_concept(tmp_db, hermetic_generate):
    concept_id = seed_concept(tmp_db)
    job = wait_for_job(client.post("/api/generate/run", data={
        "prompt": "one more angle", "output": "prompt",
        "concept_id": str(concept_id),
    }).json()["job_id"])
    assert job["status"] == "done"
    assert job["ref_id"] == concept_id
    concept = preprod.get_concept(concept_id, path=tmp_db, account_id=None)
    assert [s["n"] for s in concept["shots"]] == [1, 2]
    assert concept["shots"][1]["prompt"] == "ENHANCED[one more angle]"
    assert concept["title"] == "Night ride"


def test_generate_run_video_degrades_without_runway(tmp_db, hermetic_generate,
                                                    monkeypatch):
    monkeypatch.delenv("RUNWAYML_API_SECRET", raising=False)
    job = wait_for_job(client.post("/api/generate/run", data={
        "prompt": "night ride", "output": "video",
    }).json()["job_id"])
    assert job["status"] == "done"                    # the concept still saved
    assert "skipped" in job["detail"]
    shot = preprod.get_concept(job["ref_id"], path=tmp_db, account_id=None)["shots"][0]
    assert "media_url" not in shot


def test_generate_run_carries_video_references(tmp_db, hermetic_generate):
    res = client.post("/api/generate/run",
                      data={"prompt": "match this clip", "output": "prompt"},
                      files=[("files", ("take.mp4", b"0000", "video/mp4"))])
    assert res.json()["video_refs"] == 1
    wait_for_job(res.json()["job_id"])
    assert hermetic_generate["video_refs"] == [(b"0000", "video/mp4")]


def test_generate_run_guards(tmp_db, monkeypatch):
    assert client.post("/api/generate/run",
                       data={"prompt": " "}).status_code == 400
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    assert client.post("/api/generate/run",
                       data={"prompt": "x"}).status_code == 503
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    assert client.post("/api/generate/run",
                       data={"prompt": "x", "concept_id": "999"}).status_code == 404


# --- video references: inline vs the Files API ------------------------------

def test_video_mime_recognises_video_suffixes():
    assert api._video_mime("clip.mp4") == "video/mp4"
    assert api._video_mime("Clip.MOV") == "video/quicktime"
    assert api._video_mime("photo.jpg") is None
    assert api._video_mime("") is None


def test_video_part_inline_for_small_clips():
    part = api.video_part(object(), b"tiny", "video/mp4")
    assert part is not None
    assert part.inline_data.mime_type == "video/mp4"


def test_video_part_uses_files_api_over_the_inline_limit(monkeypatch):
    monkeypatch.setattr(api, "INLINE_VIDEO_LIMIT", 2)

    class Handle:
        name = "files/abc"

        class state:
            name = "ACTIVE"

    class Files:
        def upload(self, file=None, config=None):
            assert config == {"mime_type": "video/mp4"}
            return Handle()

    class Client:
        files = Files()

    part = api.video_part(Client(), b"bigger-than-two", "video/mp4")
    assert part is not None and part.name == "files/abc"


def test_video_part_never_raises(monkeypatch):
    monkeypatch.setattr(api, "INLINE_VIDEO_LIMIT", 2)

    class Client:
        class files:
            @staticmethod
            def upload(file=None, config=None):
                raise RuntimeError("boom")

    assert api.video_part(Client(), b"bigger-than-two", "video/mp4") is None
