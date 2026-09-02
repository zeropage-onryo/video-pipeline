"""The stages a scene goes through, and which caller runs which.

`src/scene_chain.py` holds one implementation of each stage. Pressing
Create runs ground -> write -> attach and STOPS on the concepts board;
the Director canvas and the nightly graph do the rest. The split matters
because the alternative is three copies of "render a keyframe" drifting
apart, which is how this project lost its references once already.

Every model seam is patched BY NAME and asserted called. A missed patch
here does not merely fail: the job runs in a daemon thread that can
outlive the test, monkeypatch tears the socket guard down with it, and a
real billed call escapes -- which is the exact failure conftest.py
exists for.
"""
import json
import time

import pytest
from fastapi.testclient import TestClient

from app.main import app
from src import db, imagery, nano_banana, preprod, scene_chain, shootgen

client = TestClient(app)


@pytest.fixture(autouse=True)
def signed_in(monkeypatch):
    from app import auth
    stub = {"id": 1, "email": "test@example.com", "display_name": "Test"}
    monkeypatch.setattr(auth, "current_user", lambda request: stub)
    monkeypatch.setattr(
        auth, "current_account",
        lambda request, user=None: {"slug": "zeropage", "display_name": "ZERO PAGE"})


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    from src import entities, generative
    path = tmp_path / "test.db"
    db.init_db(path)
    preprod.init(path)
    entities.init(path)
    generative.init(path)
    monkeypatch.setattr(db, "DB_PATH", path)
    return path


@pytest.fixture
def seams(monkeypatch):
    """Everything that would cost money or touch the network, replaced
    and counted."""
    calls = {"write": 0, "enhance": [], "nano": [], "ground": 0}

    def fake_model(client_, model, contents, **_):
        calls["write"] += 1
        return json.dumps({"scenes": [
            {"title": "Cold Open", "location": "", "prompt": "P1"},
            {"title": "The Door", "location": "", "prompt": "P2"},
        ]})

    def fake_ground(spark=None, client=None, db_path=None, **kw):
        calls["ground"] += 1
        return "THE SHELF"

    def fake_enhance(system, user, images=None, **kw):
        calls["enhance"].append(user)
        return f"ENHANCED[{user}]"

    def fake_nano(prompt, *, reference_image=None, db_path=None, concept_id=None,
                  **kw):
        calls["nano"].append({"prompt": prompt, "refs": list(reference_image or []),
                              "concept_id": concept_id})
        return {"ok": True, "media_url": f"https://cdn/key-{concept_id}.png",
                "generation_id": 1, "path": "x", "error": None}

    monkeypatch.setattr(shootgen, "generate_with_retry", fake_model)
    monkeypatch.setattr(shootgen, "reference_block", fake_ground)
    monkeypatch.setattr(imagery, "enhance", fake_enhance)
    monkeypatch.setattr(nano_banana, "generate_from_prompt", fake_nano)
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    return calls


def wait_for_job(job_id, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed", "cancelled"):
            return job
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} never finished")


def create(count="2"):
    res = client.post("/api/scenes/run",
                      data={"idea": "gearing up ritual", "count": count,
                            "brand": "zeropage"})
    assert res.status_code == 200, res.text
    return wait_for_job(res.json()["job_id"])


# --- Create stops at the concepts board -------------------------------------

def test_create_writes_concepts_and_stops(tmp_db, seams):
    """Mike's call, 2026-08-29: pressing Create is for reading concepts,
    not for a minute of billed work nobody asked for. The enhance and
    the keyframe belong to the Director canvas when a person is driving,
    and to the nightly graph when nobody is."""
    job = create()
    assert job["status"] == "done", job.get("error")

    concepts = preprod.list_concepts(path=tmp_db, account_id=None)
    assert len(concepts) == 2
    assert seams["write"] == 1          # ONE call for both takes, not two
    assert seams["enhance"] == []       # nothing enhanced
    assert seams["nano"] == []          # nothing rendered, nothing spent

    for c in concepts:
        assert c["shots"][0]["prompt"] in ("P1", "P2")
        assert "written_prompt" not in c["shots"][0]
        assert c["parked"] is False
        assert c["picked"] is False
    # unparked and unpicked: NOT waiting on a spend decision
    assert client.get("/api/queue/pending?brand=zeropage").json()["items"] == []


def test_no_scene_at_all_is_a_failed_run_not_a_silent_one(tmp_db, seams, monkeypatch):
    monkeypatch.setattr(shootgen, "generate_with_retry",
                        lambda c, m, contents, **_: json.dumps({"scenes": []}))
    job = create()
    assert job["status"] == "failed"
    assert "no usable scene" in (job["error"] or "")
    assert preprod.list_concepts(path=tmp_db, account_id=None) == []


# --- the stages the other two callers use -----------------------------------

def a_scene(path, prompt="a rider suits up", refs=None):
    return preprod.save_concept(
        {"title": "Cold Open", "hook": "", "logline": "",
         "shots": [{"n": 1, "type": "BROLL", "source": "AI", "tool": "RUNWAY",
                    "desc": "x", "prompt": prompt, "refs": list(refs or [])}]},
        brand="zeropage", prompt_template="T", path=path, account_id=None)


def test_persist_prompt_keeps_the_generators_own_words(tmp_db):
    """Whatever polished the prompt, the row has to end up holding it --
    or Runway renders the draft while the good version lives in a job
    payload. The model's original stays as written_prompt: the grade
    queue teaches on what the MODEL wrote, and the Director canvas seeds
    from it so pressing Run doesn't enhance an already-enhanced prompt.
    """
    scene_id = a_scene(tmp_db, prompt="the draft")
    assert scene_chain.persist_prompt(scene_id, 1, "the polished version",
                                      db_path=tmp_db) is True
    shot = preprod.get_concept(scene_id, path=tmp_db, account_id=None)["shots"][0]
    assert shot["prompt"] == "the polished version"
    assert shot["written_prompt"] == "the draft"

    # polishing twice must not lose the original under the first polish
    scene_chain.persist_prompt(scene_id, 1, "polished again", db_path=tmp_db)
    shot = preprod.get_concept(scene_id, path=tmp_db, account_id=None)["shots"][0]
    assert shot["prompt"] == "polished again"
    assert shot["written_prompt"] == "the draft"

    # nothing to store is not an error, and does not touch the row
    assert scene_chain.persist_prompt(scene_id, 1, "  ", db_path=tmp_db) is False
    assert scene_chain.persist_prompt(scene_id, 1, "polished again",
                                      db_path=tmp_db) is False
    assert scene_chain.persist_prompt(9999, 1, "x", db_path=tmp_db) is False


def test_keyframe_attaches_the_still_and_names_every_reference(tmp_db, seams,
                                                               monkeypatch):
    """The still is what the clip anchors on, so this is the frame the
    whole spend hangs off. References go in NAMED: four references are
    four named things the model can bind to the prompt's words, not four
    pictures it has to sort out."""
    photo = "/characters/michael/photo/a.jpg"
    monkeypatch.setattr(imagery, "image_bytes_for_gemini",
                        lambda value, resolve_photo=None: b"\xff\xd8jacket")
    scene_id = a_scene(tmp_db, refs=[photo])

    result = scene_chain.keyframe_scene(scene_id, 1, db_path=tmp_db)
    assert result["ok"]
    assert seams["nano"][0]["refs"] == [(shootgen.reference_label(photo),
                                         b"\xff\xd8jacket")]
    assert seams["nano"][0]["concept_id"] == scene_id     # names its own file
    shot = preprod.get_concept(scene_id, path=tmp_db, account_id=None)["shots"][0]
    assert shot["reference_image"] == f"https://cdn/key-{scene_id}.png"


def test_the_keyframe_prompt_names_only_references_that_resolved(
        tmp_db, seams, monkeypatch):
    """The prompt the keyframe renders from has to agree with the
    captions the images carry.

    The scene writers invent "@Image 1 / @Image 2" -- a syntax nothing
    here emits and no renderer receives -- so the sentence naming the
    face pointed at nothing while the jacket bound anyway off its own
    name. And a HEIC Pillow could not decode is dropped before the call,
    so naming it would promise a picture that never rode along.
    """
    monkeypatch.setattr(
        imagery, "image_bytes_for_gemini",
        lambda url, resolve_photo=None: (b"\xff\xd8ok"
                                         if url.lower().endswith(".jpg") else None))
    scene_id = a_scene(
        tmp_db,
        prompt=("REFERENCES: Use @Image 1 for Michael's face.\n\n"
                "ACTION: he waits by the @Image 2 bike."),
        refs=["/characters/michael/photo/a.jpg",
              "/props/motorcycle/photo/b.heic"])

    assert scene_chain.keyframe_scene(scene_id, 1, db_path=tmp_db)["ok"]
    prompt = seams["nano"][0]["prompt"]
    assert "@Image" not in prompt
    assert '"Michael"' in prompt
    assert "Motorcycle" not in prompt          # dropped, so never promised
    assert len(seams["nano"][0]["refs"]) == 1  # and never sent either
    # the stored shot keeps the writer's text; only the render is rebound
    shot = preprod.get_concept(scene_id, path=tmp_db, account_id=None)["shots"][0]
    assert "@Image 1" in shot["prompt"]


def test_a_failed_keyframe_is_a_result_not_an_exception(tmp_db, monkeypatch):
    monkeypatch.setattr(nano_banana, "generate_from_prompt",
                        lambda prompt, **kw: {"ok": False, "media_url": None,
                                              "error": "daily cap: 20/20 images"})
    scene_id = a_scene(tmp_db)
    result = scene_chain.keyframe_scene(scene_id, 1, db_path=tmp_db)
    assert result["ok"] is False and "daily cap" in result["error"]
    assert "reference_image" not in preprod.get_concept(scene_id,
                                                        path=tmp_db, account_id=None)["shots"][0]
    # a scene with no prompt has nothing to render, and says so
    empty = preprod.save_concept(
        {"title": "Empty", "shots": [{"n": 1, "source": "AI", "tool": "RUNWAY"}]},
        brand="zeropage", path=tmp_db, account_id=None)
    assert "no prompt" in scene_chain.keyframe_scene(empty, 1,
                                                     db_path=tmp_db)["error"]


def test_parking_is_what_puts_a_scene_in_the_queue(tmp_db):
    """Only the automation parks. A scene made by hand reaches the Queue
    by being picked -- and a scene that merely HAS a keyframe (the
    Director canvas attaches one mid-work) is not waiting on anybody."""
    parked = a_scene(tmp_db)
    scene_chain.park_scene(parked, "keyframe rendered", db_path=tmp_db)

    mid_work = a_scene(tmp_db)
    preprod.set_shot_reference_image(mid_work, 1, "https://cdn/other.png",
                                     path=tmp_db, account_id=None)

    items = client.get("/api/queue/pending?brand=zeropage").json()["items"]
    assert [c["id"] for c in items] == [parked]
    assert items[0]["park_reason"] == "keyframe rendered"
    assert items[0]["picked"] is False        # approving is what picks it


# --- the shape of the module itself -----------------------------------------

def test_the_stages_stay_callable_from_a_graph_and_from_a_request():
    """A guard on a decision (2026-08-29). These are plain functions so
    the request path can call them directly and src/orchestrator.py's
    StateGraph can call them from its nodes. If scene_chain ever grows
    its own graph, that is a real architectural change -- make it
    deliberately, and delete this test."""
    import pathlib
    source = pathlib.Path(scene_chain.__file__).read_text()
    assert "import langgraph" not in source
    assert "StateGraph(" not in source      # the prose names it; the code must not
    # and src/ never imports app/: the app-layer capabilities are injected
    assert "from app" not in source and "import app" not in source
    assert "attach_refs" in source and "resolve_photo" in source


# --- a scene with no references gets one generated (2026-09-02) -------------
#
# keyframe_scene passes reference_image=None when shot["refs"] is empty, so the
# still renders from prompt text alone. For Zero Page that is EVERY scene: no
# cast to attach, and the scout's image bin empty since Instagram's
# public-content endpoint started refusing. The brand built on grounded texture
# was the one keyframing blind.

def _scene_without_refs(tmp_db):
    return preprod.save_concept(
        {"title": "The Living Wall", "shots": [
            {"n": 1, "type": "BROLL", "source": "AI", "tool": "RUNWAY",
             "prompt": "a sponge on a wall that bruises under pressure"},
        ]},
        brand="zeropage", path=tmp_db, account_id=None)


def test_no_target_without_spend_approval(tmp_db, monkeypatch):
    """MIDJOURNEY_SPEND_OK is per-run by design -- "an approval that's
    always on isn't an approval". Unapproved, behaviour is unchanged."""
    monkeypatch.delenv("MIDJOURNEY_SPEND_OK", raising=False)
    cid = _scene_without_refs(tmp_db)
    shot = preprod.get_concept(cid, path=tmp_db, account_id=None)["shots"][0]

    assert scene_chain.visual_target(cid, shot, db_path=tmp_db,
                                     account_id=None) == ""


def test_an_approved_run_gets_a_target_attached(tmp_db, monkeypatch):
    """The target lands on the shot's refs, not in a local -- the Queue
    card reads refs to show what the spend is anchored on, and a target
    nobody can see is a target nobody can veto."""
    monkeypatch.setenv("MIDJOURNEY_SPEND_OK", "1")
    monkeypatch.setattr(scene_chain.shootgen, "still_prompt",
                        lambda *a, **k: "a bruised wall --ar 9:16 --style raw")

    from pathlib import Path

    from src import midjourney, refbin

    def fake_generate(prompt, out, **k):
        out = Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"jpegbytes")
        return out

    monkeypatch.setattr(midjourney, "generate_image", fake_generate)
    monkeypatch.setattr(refbin, "save", lambda data: "/refs/generated.jpg")

    cid = _scene_without_refs(tmp_db)
    shot = preprod.get_concept(cid, path=tmp_db, account_id=None)["shots"][0]

    url = scene_chain.visual_target(cid, shot, db_path=tmp_db, account_id=None)
    assert url == "/refs/generated.jpg"
    after = preprod.get_concept(cid, path=tmp_db, account_id=None)
    assert after["shots"][0]["refs"] == ["/refs/generated.jpg"]


def test_a_failed_target_is_never_fatal(tmp_db, monkeypatch):
    """A scene with no target is still a scene -- it keyframes the way
    it always did."""
    monkeypatch.setenv("MIDJOURNEY_SPEND_OK", "1")
    from src import midjourney
    monkeypatch.setattr(scene_chain.shootgen, "still_prompt",
                        lambda *a, **k: "a bruised wall")

    def boom(prompt, out, **k):
        raise RuntimeError("midjourney is down")

    monkeypatch.setattr(midjourney, "generate_image", boom)
    cid = _scene_without_refs(tmp_db)
    shot = preprod.get_concept(cid, path=tmp_db, account_id=None)["shots"][0]

    assert scene_chain.visual_target(cid, shot, db_path=tmp_db,
                                     account_id=None) == ""
