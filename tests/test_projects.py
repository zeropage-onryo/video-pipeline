"""Studio projects (src/projects.py, 2026-09-28): one brief and one memory
per piece of work, read into every Create run inside the project.

Each test names the line it guards.
"""
import time

import pytest
from fastapi.testclient import TestClient

from app import auth
from app.main import app
from src import accounts, db, preprod, project_context, projects, shootgen

GUARDED = {"x-zpf-model-connection": "1"}

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


# ---------------------------------------------------------------------------
# One Projects board (2026-10-07): the chat history, delete, covers, the
# project tools behind the Guide, and a solo render's place on the wall.
# ---------------------------------------------------------------------------

def _turns():
    return [{"role": "user", "content": "a watch ad, dusk, one take"},
            {"role": "assistant", "content": "Three directions.",
             "tool_calls": {"directions": [{"title": "Tide", "logline": "x"}]}}]


# guards: append_message / messages -- order, paging, the extras round trip
def test_a_projects_history_is_kept_in_order_and_pages_back(tmp_db):
    project = projects.create("Watch ad", "", tmp_db, account_id=None)
    for i in range(5):
        projects.append_message(project["id"], "user", f"ask {i}", tmp_db, account_id=None)
        projects.append_message(project["id"], "assistant", f"answer {i}", tmp_db,
                                account_id=None, tool_calls={"nudge": f"next {i}"})
    page = projects.messages(project["id"], tmp_db, account_id=None, limit=4)
    assert [m["content"] for m in page["items"]] == ["ask 3", "answer 3", "ask 4", "answer 4"]
    assert page["has_more"] is True
    assert page["items"][1]["tool_calls"] == {"nudge": "next 3"}
    older = projects.messages(project["id"], tmp_db, account_id=None, limit=4,
                              before=page["items"][0]["id"])
    assert [m["content"] for m in older["items"]] == ["ask 1", "answer 1", "ask 2", "answer 2"]
    assert older["has_more"] is True
    with pytest.raises(ValueError):
        projects.append_message(project["id"], "system", "no", tmp_db, account_id=None)
    assert projects.append_message(project["id"], "user", "   ", tmp_db, account_id=None) is None


# guards: the account predicate on project_messages
def test_another_account_cannot_read_or_write_a_projects_history(tmp_db):
    seeded = accounts.seed("mike@example.com", dsn=tmp_db)
    mine = seeded["accounts"][0]
    theirs = accounts.upsert_account("other", "Other", dsn=tmp_db)
    project = projects.create("Mine", "", tmp_db, account_id=mine)
    projects.append_message(project["id"], "user", "hello", tmp_db, account_id=mine)
    assert projects.append_message(project["id"], "user", "hi", tmp_db, account_id=theirs) is None
    assert projects.messages(project["id"], tmp_db, account_id=theirs)["items"] == []
    assert len(projects.messages(project["id"], tmp_db, account_id=mine)["items"]) == 1
    with pytest.raises(ValueError):
        projects.delete(project["id"], tmp_db, account_id=theirs)


# guards: delete -- history gone, scenes detached, renders untouched
def test_deleting_a_project_removes_its_chat_and_detaches_its_scenes(tmp_db, monkeypatch):
    from src import render_assets
    monkeypatch.setattr(render_assets, "_ingest",
                        lambda *a, **k: {"ok": True, "chunks": 1, "error": None})
    project = projects.create("Perfume", "gold", tmp_db, account_id=None)
    rendered = preprod.save_concept(
        {"title": "Bottle", "hook": "", "logline": "",
         "shots": [{"n": 1, "type": "BROLL", "source": "AI", "tool": "RUNWAY", "desc": "d",
                    "prompt": "p", "refs": ["/refs/a.jpg"], "media_url": "https://r2/clip.mp4"}]},
        brand="zeropage", prompt_template="T", dsn=tmp_db, account_id=None)
    unrendered = a_scene(tmp_db, title="Spritz")
    projects.tag_concepts([rendered, unrendered], project["id"], tmp_db, account_id=None)
    asset = render_assets.record(generation_id=7, tool="fal", model="ltx", media_kind="video",
                                 prompt="p", media_url="https://r2/clip.mp4",
                                 concept_id=rendered, dsn=tmp_db, account_id=None)
    projects.copy_messages(project["id"], _turns(), tmp_db, account_id=None)

    left = projects.scenes_to_detach(project["id"], tmp_db, account_id=None)
    assert {(s["title"], s["rendered"]) for s in left} == {("Bottle", True), ("Spritz", False)}

    counts = projects.delete(project["id"], tmp_db, account_id=None)
    assert counts == {"detached": 2, "messages": 2}
    assert projects.get(project["id"], tmp_db, account_id=None) is None
    assert preprod.get_concept(rendered, dsn=tmp_db, account_id=None)["project_id"] is None
    assert preprod.get_concept(unrendered, dsn=tmp_db, account_id=None)["project_id"] is None
    assert any(r["id"] == asset["id"] for r in render_assets.list_all(dsn=tmp_db, account_id=None))
    with db.connect(tmp_db) as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM project_messages").fetchone()["n"] == 0


# guards: the routes -- DELETE needs the header, lists what it will detach
def test_the_delete_route_is_guarded_and_lists_the_scenes_first(tmp_db):
    project = client.post("/api/projects", json={"title": "Doomed"}).json()
    scene = a_scene(tmp_db, title="Only scene")
    projects.tag_concepts([scene], project["id"], tmp_db, account_id=None)
    listed = client.get(f"/api/projects/{project['id']}/scenes").json()["items"]
    assert listed == [{"id": scene, "title": "Only scene", "rendered": False}]
    assert client.delete(f"/api/projects/{project['id']}").status_code == 403
    r = client.delete(f"/api/projects/{project['id']}", headers=GUARDED)
    assert r.status_code == 200 and r.json()["detached"] == 1
    assert client.get(f"/api/projects/{project['id']}").status_code == 404
    assert client.delete("/api/projects/999", headers=GUARDED).status_code == 404


# guards: list_projects' cover -- the newest scene's still, else its first ref
def test_the_board_card_carries_a_cover_from_the_newest_scene(tmp_db):
    project = projects.create("Covered", "", tmp_db, account_id=None)
    assert projects.list_projects(tmp_db, account_id=None)[0]["cover"] is None
    older = a_scene(tmp_db, title="first")
    projects.tag_concepts([older], project["id"], tmp_db, account_id=None)
    assert projects.list_projects(tmp_db, account_id=None)[0]["cover"] == "/refs/seed.jpg"
    newer = preprod.save_concept(
        {"title": "second", "hook": "", "logline": "",
         "shots": [{"n": 1, "type": "BROLL", "source": "AI", "tool": "RUNWAY", "desc": "d",
                    "prompt": "p", "refs": ["/refs/b.jpg"], "reference_image": "/renders/k.png"}]},
        brand="zeropage", prompt_template="T", dsn=tmp_db, account_id=None)
    projects.tag_concepts([newer], project["id"], tmp_db, account_id=None)
    assert projects.list_projects(tmp_db, account_id=None)[0]["cover"] == "/renders/k.png"


# guards: the Guide's project tools -- create_project, save_as_project
def test_the_guide_makes_projects_through_the_act_route(tmp_db):
    from src import guide_tools
    assert {"create_project", "save_as_project"} <= {s["name"] for s in guide_tools.PROJECT_SPECS}
    assert all(guide_tools.is_write(t) for t in guide_tools.PROJECT_TOOLS)
    r = client.post("/api/creative-guide/act", headers=GUARDED,
                    json={"tool": "create_project", "args": {"title": " Nike spot ", "brief": "FOR: runners"}})
    assert r.status_code == 200, r.text
    made = r.json()["project"]
    assert made["title"] == "Nike spot" and made["brief"] == "FOR: runners"
    assert projects.messages(made["id"], tmp_db, account_id=None)["items"] == []

    scene = a_scene(tmp_db, title="Made in chat")
    r = client.post("/api/creative-guide/act", headers=GUARDED,
                    json={"tool": "save_as_project", "args": {"title": "Watch ad"},
                          "conversation": _turns(), "scenes": [scene, 999]})
    assert r.status_code == 200, r.text
    saved = r.json()["project"]
    history = projects.messages(saved["id"], tmp_db, account_id=None)["items"]
    assert [m["role"] for m in history] == ["user", "assistant"]
    assert history[1]["tool_calls"] == {"directions": [{"title": "Tide", "logline": "x"}]}
    assert preprod.get_concept(scene, dsn=tmp_db, account_id=None)["project_id"] == saved["id"]
    assert "2 turns" in r.json()["result"] and "1 scene" in r.json()["result"]
    # a title is required, and a URL never gets through
    assert client.post("/api/creative-guide/act", headers=GUARDED,
                       json={"tool": "create_project", "args": {"title": ""}}).status_code == 400
    assert client.post("/api/creative-guide/act", headers=GUARDED,
                       json={"tool": "create_project",
                             "args": {"title": "https://x.test/a"}}).status_code == 400
    with pytest.raises(guide_tools.Refused):
        guide_tools.run("create_project", {"title": "x"}, account_id=None)


# guards: the project tools are offered on a local turn, with a project note
def test_a_local_turn_offers_the_project_tools_and_names_the_project():
    from src import creative_guide, guide_tools
    specs, _ = guide_tools.session(local=True) if guide_tools.available() else ([], None)
    if specs:
        assert {"create_project", "save_as_project"} <= {s["name"] for s in specs}
    note = creative_guide.project_note({"title": "Car launch"})
    assert "Car launch" in note and "do not propose" in note
    assert creative_guide.project_note(None) == ""


# guards: a Guide turn inside a project writes its history (remember=1)
def test_a_guide_turn_inside_a_project_is_remembered(tmp_db, monkeypatch):
    import json as _json

    from app import api
    from src import creative_guide, scene_chain

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    project = client.post("/api/projects", json={"title": "Remembered"}).json()

    async def refs(form):
        return [], [], []

    monkeypatch.setattr(api, "_collect_refs", refs)
    monkeypatch.setattr(scene_chain, "ground", lambda *a, **k: {"references": ""})
    seen = {}

    def respond(conversation, **kwargs):
        seen.update(kwargs)
        return {"message": "Continuing the story.", "choices": [], "brief": "",
                "nudge": "Next: pick one"}

    monkeypatch.setattr(creative_guide, "respond", respond)
    conversation = _json.dumps({"messages": [{"role": "user", "content": "continue the story"}]})
    r = client.post("/api/creative-guide", headers=GUARDED,
                    data={"conversation": conversation, "project_id": str(project["id"]),
                          "remember": "1"})
    assert r.status_code == 200, r.text
    assert wait_for_job(r.json()["job_id"])["status"] == "done"
    assert seen["project"]["id"] == project["id"]
    history = client.get(f"/api/projects/{project['id']}/messages").json()
    assert [(m["role"], m["content"]) for m in history["items"]] == [
        ("user", "continue the story"), ("assistant", "Continuing the story.")]
    assert history["items"][1]["tool_calls"] == {"nudge": "Next: pick one"}
    # outside a project, or without remember, nothing is written anywhere
    r = client.post("/api/creative-guide", headers=GUARDED,
                    data={"conversation": conversation, "remember": "1"})
    assert wait_for_job(r.json()["job_id"])["status"] == "done"
    assert len(client.get(f"/api/projects/{project['id']}/messages").json()["items"]) == 2
    assert client.post("/api/creative-guide", headers=GUARDED,
                       data={"conversation": conversation, "project_id": "999"}).status_code == 404


# guards: a render made outside any project reaches the wall, labelled so
def test_a_solo_render_lands_on_the_assets_wall_with_no_project(tmp_db, monkeypatch):
    from src import render_assets
    monkeypatch.setattr(render_assets, "_ingest",
                        lambda *a, **k: {"ok": True, "chunks": 1, "error": None})
    project = projects.create("Filed", "", tmp_db, account_id=None)
    filed = a_scene(tmp_db, title="in a project")
    projects.tag_concepts([filed], project["id"], tmp_db, account_id=None)
    solo = a_scene(tmp_db, title="solo")
    assert preprod.get_concept(solo, dsn=tmp_db, account_id=None)["project_id"] is None
    render_assets.record(generation_id=11, tool="fal", model="ltx", media_kind="video",
                         prompt="p", media_url="https://r2/solo.mp4", concept_id=solo,
                         dsn=tmp_db, account_id=None)
    render_assets.record(generation_id=12, tool="fal", model="ltx", media_kind="video",
                         prompt="p", media_url="https://r2/filed.mp4", concept_id=filed,
                         dsn=tmp_db, account_id=None)
    wall = client.get("/api/media?kind=all&scope=generated").json()["items"]
    by_url = {i["url"]: i for i in wall}
    assert by_url["https://r2/solo.mp4"]["project_id"] is None
    assert by_url["https://r2/solo.mp4"]["project_title"] is None
    assert by_url["https://r2/filed.mp4"]["project_id"] == project["id"]
    assert by_url["https://r2/filed.mp4"]["project_title"] == "Filed"
    # the board of projects knows nothing of the solo scene
    assert projects.list_projects(tmp_db, account_id=None)[0]["concepts"] == 1
    # and the card says which project a scene sits in, or none
    cards = {c["id"]: c for c in client.get("/api/pipeline/concepts").json()["items"]}
    assert cards[solo]["project_id"] is None and cards[filed]["project_id"] == project["id"]
