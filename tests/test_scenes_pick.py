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

    def fake_model(client_, model, contents):
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
    assert client.post("/api/scenes/run", json={"idea": "  "}).status_code == 400
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    assert client.post("/api/scenes/run", json={"idea": "x"}).status_code == 503


def test_the_run_route_saves_and_reports(tmp_db, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr("google.genai.Client", lambda api_key=None: object())
    monkeypatch.setattr("src.shootgen.reference_block",
                        lambda spark=None, client=None, db_path=None: "REFS")
    monkeypatch.setattr(
        "src.shootgen.generate_with_retry",
        lambda c, m, p: json.dumps({"scenes": [
            {"title": f"S{i}", "prompt": f"P{i}"} for i in range(3)]}))

    job = wait_for_job(client.post(
        "/api/scenes/run",
        json={"idea": "night ride", "count": 3, "brand": "zeropage"},
    ).json()["job_id"])
    assert job["status"] == "done", job.get("error")
    assert "3 scene(s)" in job["detail"]

    body = client.get("/api/pipeline/concepts?brand=zeropage").json()
    scenes = [c for c in body["items"] if c["is_scene"]]
    assert len(scenes) == 3
    assert all(c["prompt"] for c in scenes)          # the card carries the prompt


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
