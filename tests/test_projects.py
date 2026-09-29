"""Studio projects (src/projects.py, 2026-09-28): one brief and one memory
per piece of work, read into every Create run inside the project.

Each test names the line it guards.
"""
import time

import pytest
from fastapi.testclient import TestClient

from app import auth
from app.main import app
from src import accounts, preprod, project_context, projects, shootgen

client = TestClient(app)


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
    return pg


def a_scene(path, *, account_id=None, title="scene", prompt="a woman lifts the lid"):
    return preprod.save_concept(
        {"title": title, "hook": "", "logline": "",
         "shots": [{"n": 1, "type": "BROLL", "source": "AI", "tool": "RUNWAY",
                    "desc": "d", "prompt": prompt, "refs": ["/refs/seed.jpg"]}]},
        brand="zeropage", prompt_template="T", dsn=path, account_id=account_id)


def wait_for_job(job_id, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed", "cancelled"):
            return job
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} never finished")


# guards: the account predicate on every projects query
def test_a_project_is_invisible_to_another_account(tmp_db):
    seeded = accounts.seed("mike@example.com", dsn=tmp_db)
    mine = seeded["accounts"][0]
    theirs = accounts.upsert_account("other", "Other", dsn=tmp_db)
    project = projects.create("Perfume ad", "gold, slow", tmp_db, account_id=mine)
    assert projects.get(project["id"], tmp_db, account_id=theirs) is None
    assert projects.list_projects(tmp_db, account_id=theirs) == []
    with pytest.raises(ValueError):
        projects.update(project["id"], tmp_db, account_id=theirs, brief="stolen")
    with pytest.raises(ValueError):
        projects.tag_concepts([a_scene(tmp_db, account_id=theirs)], project["id"],
                              tmp_db, account_id=theirs)


# guards: remember's replace-and-cancel rule
def test_memory_keeps_the_last_decision_per_concept(tmp_db):
    project = projects.create("Horror short", "", tmp_db, account_id=None)
    scene = a_scene(tmp_db)
    projects.tag_concepts([scene], project["id"], tmp_db, account_id=None)
    concept = preprod.get_concept(scene, dsn=tmp_db, account_id=None)

    projects.remember_decision(concept, "pick", tmp_db, account_id=None)
    projects.remember_decision(concept, "pick", tmp_db, account_id=None)
    memory = projects.get(project["id"], tmp_db, account_id=None)["memory"]
    assert [m["kind"] for m in memory] == ["pick"]          # re-pick replaces

    projects.remember_decision(concept, "pass", tmp_db, account_id=None, reason="boring")
    memory = projects.get(project["id"], tmp_db, account_id=None)["memory"]
    assert [m["kind"] for m in memory] == ["pass"]          # a pass cancels the pick
    assert "(boring)" in memory[0]["text"]


# guards: remember_decision's "a concept outside any project teaches nothing"
def test_a_concept_outside_a_project_writes_no_memory(tmp_db):
    project = projects.create("Ad", "", tmp_db, account_id=None)
    concept = preprod.get_concept(a_scene(tmp_db), dsn=tmp_db, account_id=None)
    projects.remember_decision(concept, "pick", tmp_db, account_id=None)
    assert projects.get(project["id"], tmp_db, account_id=None)["memory"] == []


# guards: load_brand appending project_context.block()
def test_the_brand_block_carries_the_project_only_inside_it():
    project = {"title": "Sneaker drop", "brief": "LOOK: sodium orange, 50mm",
               "memory": [{"kind": "pick", "text": "PICKED “Rooftop” — a runner on wet tar"}]}
    plain = shootgen.load_brand("zeropage")
    with project_context.active(project):
        inside = shootgen.load_brand("zeropage")
    assert "Sneaker drop" not in plain
    assert "Sneaker drop" in inside and "sodium orange" in inside
    assert "a runner on wet tar" in inside
    assert shootgen.load_brand("zeropage") == plain            # reset after


# guards: the pick/archive hooks in app/api.py
def test_picking_and_passing_on_the_board_teach_the_project(tmp_db):
    project = client.post("/api/projects", json={"title": "Watch ad"}).json()
    scene = a_scene(tmp_db, title="Wrist close-up")
    projects.tag_concepts([scene], project["id"], tmp_db, account_id=None)

    client.post(f"/api/concepts/{scene}/pick", json={"picked": True})
    memory = client.get(f"/api/projects/{project['id']}").json()["memory"]
    assert memory and memory[-1]["kind"] == "pick" and "Wrist close-up" in memory[-1]["text"]

    client.post(f"/api/concepts/{scene}/pick", json={"picked": False})
    assert client.get(f"/api/projects/{project['id']}").json()["memory"] == []


# guards: the /scenes/run project branch -- context set, concepts filed
def test_create_inside_a_project_writes_against_it_and_files_the_scenes(tmp_db, monkeypatch):
    from src import scene_chain

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    project = client.post("/api/projects",
                          json={"title": "Car launch", "brief": "chrome, dusk"}).json()
    seen = {}

    def fake_run(idea, brand, **kw):
        seen["block"] = shootgen.load_brand(brand)
        cid = a_scene(tmp_db)
        return {"scenes": [{"concept_id": cid}], "notes": []}

    monkeypatch.setattr(scene_chain, "run", fake_run)
    r = client.post("/api/scenes/run", data={"idea": "a car wakes up",
                                               "project_id": str(project["id"])})
    assert r.status_code == 200 and r.json()["project_id"] == project["id"]
    assert wait_for_job(r.json()["job_id"])["status"] == "done"
    assert "chrome, dusk" in seen["block"]
    board = client.get(f"/api/pipeline/concepts?project={project['id']}").json()["items"]
    assert len(board) == 1


# guards: the unknown-project refusal in /scenes/run
def test_create_with_an_unknown_project_is_refused(tmp_db, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    r = client.post("/api/scenes/run", data={"idea": "x", "project_id": "999"})
    assert r.status_code == 404


# guards: seed() creating ONE account (the rerun-setup fix)
def test_rerunning_setup_does_not_bring_antihero_back(tmp_db):
    accounts.seed("mike@example.com", dsn=tmp_db)
    accounts.seed("mike@example.com", dsn=tmp_db)
    user = accounts.get_user_by_email("mike@example.com", dsn=tmp_db)
    assert [m["slug"] for m in accounts.memberships(user["id"], dsn=tmp_db)] == ["zeropage"]
