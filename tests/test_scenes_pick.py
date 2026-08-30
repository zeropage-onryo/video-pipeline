"""Several scenes off one idea, and the pick that follows.

A scene IS a one-shot concept (2026-08-26), so there is no second data
model here -- what's new is that one idea produces SEVERAL of them and
the human pick is recorded as the label, the way `shots != []` used to
be back when the decision was "is this idea worth planning".
"""
import json
import time

import pytest
from fastapi.testclient import TestClient

from app.main import app
from src import db, preprod, shootgen

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
    path = tmp_path / "test.db"
    db.init_db(path)
    preprod.init(path)
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


def a_scene(path, title="Cold Open", refs=None, prompt="P"):
    return preprod.save_concept(
        {"title": title, "hook": "", "logline": "",
         "shots": [{"n": 1, "type": "BROLL", "source": "AI", "tool": "RUNWAY",
                    "desc": title, "prompt": prompt, "refs": list(refs or [])}]},
        brand="zeropage", prompt_template="T", path=path)


# --- generating several to pick between -------------------------------------

def test_one_idea_writes_several_one_shot_concepts(tmp_db, monkeypatch):
    captured = {}

    def fake_model(client_, model, contents, **_):
        captured["prompt"] = contents if isinstance(contents, str) else contents[-1]
        return json.dumps({"scenes": [
            {"title": "Cold Open", "location": "garage", "prompt": "P1"},
            {"title": "The Door", "location": "", "prompt": "P2"},
            {"title": "Empty", "prompt": "  "},          # dropped, not saved
        ]})

    monkeypatch.setattr("src.shootgen.generate_with_retry", fake_model)
    result = shootgen.generate_scene_concepts(
        "gearing up ritual", "zeropage", count=3, db_path=tmp_db,
        refs=["/locations/garage/photo/a.jpg"])

    assert [s["title"] for s in result["scenes"]] == ["Cold Open", "The Door"]
    # the idea reaches the model, and the takes are told to differ
    assert "gearing up ritual" in captured["prompt"]
    assert "STANDALONE" in captured["prompt"]

    saved = [preprod.get_concept(s["concept_id"], path=tmp_db) for s in result["scenes"]]
    for concept in saved:
        assert concept["is_scene"]                   # exactly one shot each
        assert len(concept["shots"]) == 1
        assert concept["picked"] is False            # unjudged until picked
        # the references ride ON the shot, so they reach every node later
        assert concept["refs"] == ["/locations/garage/photo/a.jpg"]
        assert concept["spark"] == "gearing up ritual"
    assert saved[0]["shots"][0]["location"] == "garage"


def test_the_run_route_refuses_an_empty_idea_and_a_missing_key(tmp_db, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    assert client.post("/api/scenes/run", data={"idea": "  "}).status_code == 400
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    assert client.post("/api/scenes/run", data={"idea": "x"}).status_code == 503


def test_the_run_route_saves_and_reports(tmp_db, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr("google.genai.Client", lambda api_key=None: object())
    monkeypatch.setattr("src.shootgen.reference_block",
                        lambda spark=None, client=None, db_path=None: "REFS")
    monkeypatch.setattr(
        "src.shootgen.generate_with_retry",
        lambda c, m, p, **_: json.dumps({"scenes": [
            {"title": f"S{i}", "prompt": f"P{i}"} for i in range(3)]}))

    job = wait_for_job(client.post(
        "/api/scenes/run",
        data={"idea": "night ride", "count": 3, "brand": "zeropage"},
    ).json()["job_id"])
    assert job["status"] == "done", job.get("error")
    assert "3 concept(s)" in job["detail"]

    body = client.get("/api/pipeline/concepts?brand=zeropage").json()
    scenes = [c for c in body["items"] if c["is_scene"]]
    assert len(scenes) == 3
    assert all(c["prompt"] for c in scenes)          # the card carries the prompt


def test_the_composer_caps_the_count_at_four(tmp_db, monkeypatch):
    """The Studio composer offers 1-4. A hand-rolled request asking for
    forty does not get to bill forty."""
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr("google.genai.Client", lambda api_key=None: object())
    monkeypatch.setattr("src.shootgen.reference_block",
                        lambda spark=None, client=None, db_path=None: "")
    asked = {}

    def fake_model(client_, model, contents, **_):
        asked["prompt"] = contents if isinstance(contents, str) else contents[-1]
        return json.dumps({"scenes": [{"title": "S", "prompt": "P"}]})

    monkeypatch.setattr("src.shootgen.generate_with_retry", fake_model)
    job = wait_for_job(client.post(
        "/api/scenes/run",
        data={"idea": "night ride", "count": "40", "brand": "zeropage"},
    ).json()["job_id"])
    assert job["status"] == "done", job.get("error")
    assert "40" not in asked["prompt"].split("night ride")[0]


# --- the pick ---------------------------------------------------------------

def test_picking_is_recorded_and_counted(tmp_db):
    ids = [a_scene(tmp_db, f"S{i}") for i in range(4)]

    res = client.post(f"/api/concepts/{ids[0]}/pick", json={"picked": True})
    assert res.json()["pick"]["picked"] == 1
    assert res.json()["pick"]["generated"] == 4
    assert res.json()["pick"]["rate"] == 0.25

    concept = preprod.get_concept(ids[0], path=tmp_db)
    assert concept["picked"] is True
    assert concept["picked_at"]                       # windowable, not a bare flag

    # unpicking clears it again
    client.post(f"/api/concepts/{ids[0]}/pick", json={"picked": False})
    assert preprod.get_concept(ids[0], path=tmp_db)["picked_at"] is None


def test_pick_rate_ignores_legacy_multi_shot_concepts(tmp_db):
    """A six-shot concept was never a single scene to pick between, so
    counting it would compare two different decisions."""
    a_scene(tmp_db, "a scene")
    preprod.save_concept(
        {"title": "old", "hook": "", "logline": "",
         "shots": [{"n": 1, "type": "BROLL", "source": "AI", "prompt": "x"},
                   {"n": 2, "type": "BROLL", "source": "AI", "prompt": "y"}]},
        brand="zeropage", path=tmp_db)
    assert preprod.pick_rate(path=tmp_db)["generated"] == 1


def test_picking_something_that_does_not_exist_is_a_404(tmp_db):
    assert client.post("/api/concepts/9999/pick", json={"picked": True}).status_code == 404


def test_pick_rate_on_an_empty_table_is_none_not_a_crash(tmp_db):
    assert preprod.pick_rate(path=tmp_db)["rate"] is None


# --- the references a scene carries -----------------------------------------

def test_refs_round_trip_on_the_shot(tmp_db):
    scene_id = a_scene(tmp_db)
    res = client.post(f"/api/concepts/{scene_id}/refs",
                      json={"refs": ["/a/face.jpg", "/b/jacket.jpg"]})
    assert res.json()["refs"] == ["/a/face.jpg", "/b/jacket.jpg"]
    concept = preprod.get_concept(scene_id, path=tmp_db)
    assert concept["refs"] == ["/a/face.jpg", "/b/jacket.jpg"]
    assert concept["shots"][0]["prompt"] == "P"       # the prompt is untouched
    # and the card surfaces them for the board
    card = [c for c in client.get("/api/pipeline/concepts?brand=zeropage").json()["items"]
            if c["id"] == scene_id][0]
    assert card["refs"] == ["/a/face.jpg", "/b/jacket.jpg"]


# --- leaving the board ------------------------------------------------------
# Archiving hides a concept; it never deletes one. The row is the label:
# pick_rate is generated-vs-picked, so the ones passed over are half the
# measurement, and they stay in the Dev Studio's ungraded pool besides.

def test_archiving_hides_the_card_but_keeps_the_row(tmp_db):
    ids = [a_scene(tmp_db, f"S{i}") for i in range(3)]

    assert client.post(f"/api/concepts/{ids[0]}/archive",
                       json={"archived": True}).json()["archived"] is True

    open_board = client.get("/api/pipeline/concepts?brand=zeropage").json()["items"]
    assert [c["id"] for c in open_board] == [ids[2], ids[1]]      # newest first

    # still there, still counted, still ungraded
    everything = client.get(
        "/api/pipeline/concepts?brand=zeropage&archived=true").json()
    assert len(everything["items"]) == 3
    assert everything["pick"]["generated"] == 3
    archived = preprod.get_concept(ids[0], path=tmp_db)
    assert archived["archived"] is True
    assert archived["archived_at"]
    assert archived["graded"] is False        # the Dev Studio still owes it a grade


def test_archiving_is_reversible(tmp_db):
    scene_id = a_scene(tmp_db)
    client.post(f"/api/concepts/{scene_id}/archive", json={"archived": True})
    client.post(f"/api/concepts/{scene_id}/archive", json={"archived": False})
    assert preprod.get_concept(scene_id, path=tmp_db)["archived"] is False
    assert len(client.get("/api/pipeline/concepts?brand=zeropage").json()["items"]) == 1


def test_archiving_something_that_does_not_exist_is_a_404(tmp_db):
    assert client.post("/api/concepts/9999/archive",
                       json={"archived": True}).status_code == 404


def test_archive_batch_keeps_the_ones_you_name(tmp_db):
    """One idea's concepts share its spark, which is what makes them a
    batch worth resolving together."""
    kept = preprod.save_concept(
        {"title": "keep", "shots": [{"n": 1, "source": "AI", "prompt": "p"}]},
        brand="zeropage", spark="night ride", path=tmp_db)
    others = [preprod.save_concept(
        {"title": f"other{i}", "shots": [{"n": 1, "source": "AI", "prompt": "p"}]},
        brand="zeropage", spark="night ride", path=tmp_db) for i in range(2)]
    unrelated = preprod.save_concept(
        {"title": "different idea", "shots": [{"n": 1, "source": "AI", "prompt": "p"}]},
        brand="zeropage", spark="garage", path=tmp_db)

    assert preprod.archive_batch("night ride", keep_ids=[kept],
                                 brand="zeropage", path=tmp_db) == 2
    assert preprod.get_concept(kept, path=tmp_db)["archived"] is False
    assert all(preprod.get_concept(i, path=tmp_db)["archived"] for i in others)
    assert preprod.get_concept(unrelated, path=tmp_db)["archived"] is False


# --- the approval gate ------------------------------------------------------
# Rendering is the only step that spends money, so it is the only one
# with a gate. Two ways in: the Studio chain PARKS a scene once its
# keyframe is rendered, or you pick a text-only one off the board.
# Approving in the Queue is the click that calls Runway -- and on a
# parked scene, approving is also the pick.

def test_pending_is_what_is_picked_and_not_yet_rendered(tmp_db):
    picked = a_scene(tmp_db, "picked")
    a_scene(tmp_db, "unpicked")
    rendered = a_scene(tmp_db, "already rendered")
    archived = a_scene(tmp_db, "archived")
    for scene_id in (picked, rendered, archived):
        client.post(f"/api/concepts/{scene_id}/pick", json={"picked": True})
    preprod.set_shot_media_url(rendered, 1, "https://x/clip.mp4", path=tmp_db)
    client.post(f"/api/concepts/{archived}/archive", json={"archived": True})

    body = client.get("/api/queue/pending?brand=zeropage").json()
    assert [c["id"] for c in body["items"]] == [picked]
    assert "spend_ok" in body["runway"]       # the gate is stated, not guessed at


def test_a_parked_scene_is_pending_but_a_merely_keyframed_one_is_not(tmp_db):
    """The queue asks "is this waiting on me to spend", and only the
    chain's explicit park answers it. A reference_image alone must NOT:
    the Director canvas attaches one mid-work, and inferring from it
    would drag every scene anyone ever keyframed into the spend queue.
    """
    parked = a_scene(tmp_db, "parked by the chain")
    preprod.set_shot_reference_image(parked, 1, "https://cdn/key.png", path=tmp_db)
    preprod.set_shot_parked(parked, 1, "keyframe rendered", path=tmp_db)

    mid_work = a_scene(tmp_db, "keyframed in Director")
    preprod.set_shot_reference_image(mid_work, 1, "https://cdn/other.png", path=tmp_db)

    items = client.get("/api/queue/pending?brand=zeropage").json()["items"]
    assert [c["id"] for c in items] == [parked]
    card = items[0]
    assert card["parked"] is True
    assert card["park_reason"] == "keyframe rendered"
    assert card["reference_image"] == "https://cdn/key.png"
    assert card["picked"] is False            # approving is what picks it


def test_approving_something_not_in_the_queue_is_refused(tmp_db, monkeypatch):
    """The gate did not go away when approval became the pick: a concept
    that is neither parked by the chain nor picked on the board still
    cannot be rendered."""
    monkeypatch.setattr("src.runway.has_key", lambda: True)
    scene_id = a_scene(tmp_db)
    res = client.post(f"/api/queue/{scene_id}/approve")
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "not_queued"


def test_approving_one_take_leaves_its_siblings_in_the_queue(tmp_db, monkeypatch):
    """Approving used to archive every unpicked sibling from the same
    spark, inferring "you have answered this batch". That was safe while
    picking was a separate bulk step done first. Now that approval IS
    the pick, that inference would archive takes 2-4 out from under you
    the moment you approved take 1 -- and racily, since it ran after
    Runway returned. Rejecting is the only thing that archives now."""
    takes = [preprod.save_concept(
        {"title": f"take{i}", "shots": [{"n": 1, "source": "AI", "tool": "RUNWAY",
                                         "prompt": "p"}]},
        brand="zeropage", spark="night ride", path=tmp_db) for i in range(3)]
    for scene_id in takes:
        preprod.set_shot_parked(scene_id, 1, "keyframe rendered", path=tmp_db)

    monkeypatch.setattr("src.runway.has_key", lambda: True)
    rendered = {}

    def fake_render(concept_id, shot_n, db_path=None, resolve_photo=None):
        rendered["args"] = (concept_id, shot_n)
        preprod.set_shot_media_url(concept_id, shot_n, "https://x/clip.mp4",
                                   path=db_path)
        return {"ok": True}

    monkeypatch.setattr("src.runway.generate_for_shot", fake_render)

    job = wait_for_job(client.post(f"/api/queue/{takes[0]}/approve").json()["job_id"])
    assert job["status"] == "done", job.get("error")
    assert rendered["args"] == (takes[0], 1)

    # approving stamped the pick, and it stamped it before the spend
    assert preprod.get_concept(takes[0], path=tmp_db)["picked"] is True
    assert all(not preprod.get_concept(i, path=tmp_db)["archived"] for i in takes)
    # the rendered one leaves the queue on its own; the others stay
    pending = client.get("/api/queue/pending?brand=zeropage").json()["items"]
    assert sorted(c["id"] for c in pending) == takes[1:]   # newest-first listing


def test_approving_without_a_runway_key_says_so(tmp_db, monkeypatch):
    monkeypatch.setattr("src.runway.has_key", lambda: False)
    scene_id = a_scene(tmp_db)
    client.post(f"/api/concepts/{scene_id}/pick", json={"picked": True})
    assert client.post(f"/api/queue/{scene_id}/approve").status_code == 503


def test_rejecting_unpicks_and_archives(tmp_db):
    """Rejected at the spend gate means it was generated and not picked,
    which is exactly what pick_rate should read."""
    scene_id = a_scene(tmp_db)
    client.post(f"/api/concepts/{scene_id}/pick", json={"picked": True})
    res = client.post(f"/api/queue/{scene_id}/reject")
    assert res.json()["pick"]["picked"] == 0
    concept = preprod.get_concept(scene_id, path=tmp_db)
    assert concept["picked"] is False and concept["archived"] is True
