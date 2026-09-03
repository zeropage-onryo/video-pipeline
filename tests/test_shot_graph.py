"""A concept's canvas outlives the visit.

Run all used to save the node tree to a throwaway workflow row purely so
the runner had something to execute, then reopening the concept rebuilt
the canvas from the shot and cleared every node's output. Re-running a
paid Gemini enhance was the only way to see the enhanced prompt again
(fixed 2026-08-28).
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from src import entities, preprod, workflows

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
def tmp_db(pg, monkeypatch):
    path = pg
    preprod.init(path)
    entities.init(path)
    workflows.init(path)
    monkeypatch.setenv("DATABASE_URL", path)
    return path


def a_concept(path, prompt="the scene as written"):
    return preprod.save_concept(
        {"title": "The Garage Guest", "hook": "", "logline": "",
         "shots": [{"n": 1, "type": "BROLL", "source": "AI", "tool": "RUNWAY",
                    "desc": "d", "prompt": prompt}]},
        brand="zeropage", dsn=path, account_id=None)


GRAPH = {"nodes": [{"id": 3, "type": "zpf/enhance", "pos": [640, 370],
                    "properties": {"shot_n": 1}}],
         "links": []}
STATES = {"3": {"status": "done", "kind": "text",
                "output": "9:16 raw handheld cinematography, 16mm gritty film grain."}}


# --- the drawing AND what it produced ---------------------------------------

def test_a_saved_canvas_comes_back_with_its_outputs(tmp_db):
    """The whole point. serialize() carries a node's config and position
    but never its output, so a graph restored without states is the
    right shape with every box empty — which is what made re-running
    feel mandatory."""
    cid = a_concept(tmp_db)
    res = client.put(f"/api/concepts/{cid}/shots/1/graph",
                     json={"graph": GRAPH, "states": STATES})
    assert res.json()["ok"] is True

    back = client.get(f"/api/concepts/{cid}/shots/1/graph").json()
    assert back["graph"]["nodes"][0]["pos"] == [640, 370]     # where he left it
    assert back["states"]["3"]["output"].startswith("9:16 raw handheld")
    assert back["stale"] is False


def test_nothing_saved_yet_says_build_a_fresh_one(tmp_db):
    cid = a_concept(tmp_db)
    back = client.get(f"/api/concepts/{cid}/shots/1/graph").json()
    assert back["graph"] is None and back["states"] is None


def test_saving_twice_updates_one_row_instead_of_piling_up(tmp_db):
    """Run all POSTed a brand-new workflow row every session and read
    none of them back. One row per (concept, shot) now."""
    cid = a_concept(tmp_db)
    first = client.put(f"/api/concepts/{cid}/shots/1/graph",
                       json={"graph": GRAPH}).json()["id"]
    second = client.put(f"/api/concepts/{cid}/shots/1/graph",
                        json={"graph": GRAPH, "states": STATES}).json()["id"]
    assert first == second
    rows = workflows.get_shot_graph(cid, 1, dsn=tmp_db, account_id=None)
    assert rows["states"] == STATES


def test_a_graph_only_save_never_blanks_the_last_run(tmp_db):
    """Switching shots saves the drawing without states. That must not
    erase the outputs the last run produced."""
    cid = a_concept(tmp_db)
    client.put(f"/api/concepts/{cid}/shots/1/graph",
               json={"graph": GRAPH, "states": STATES})
    client.put(f"/api/concepts/{cid}/shots/1/graph", json={"graph": GRAPH})
    assert client.get(f"/api/concepts/{cid}/shots/1/graph").json()["states"] == STATES


def test_each_shot_keeps_its_own_canvas(tmp_db):
    cid = preprod.save_concept(
        {"title": "two shots", "shots": [
            {"n": 1, "source": "AI", "prompt": "one"},
            {"n": 2, "source": "AI", "prompt": "two"}]},
        brand="zeropage", dsn=tmp_db, account_id=None)
    client.put(f"/api/concepts/{cid}/shots/1/graph", json={"graph": GRAPH})
    assert client.get(f"/api/concepts/{cid}/shots/2/graph").json()["graph"] is None


# --- staleness --------------------------------------------------------------

def test_a_prompt_change_underneath_retires_the_drawing(tmp_db):
    """A saved graph holds a COPY of the prompt in its User Prompt node.
    Direct the scene and that copy is a drawing of a shot that no longer
    says that — so it rebuilds rather than showing stale text."""
    cid = a_concept(tmp_db, prompt="the original scene")
    client.put(f"/api/concepts/{cid}/shots/1/graph",
               json={"graph": GRAPH, "states": STATES})
    assert client.get(f"/api/concepts/{cid}/shots/1/graph").json()["stale"] is False

    client.post(f"/api/concepts/{cid}/shots/1/prompt",
                json={"prompt": "a revised, slower, darker scene"})
    back = client.get(f"/api/concepts/{cid}/shots/1/graph").json()
    assert back["stale"] is True
    assert back["graph"] is None          # the client builds a fresh chain


def test_better_references_underneath_retire_the_drawing_too(tmp_db):
    """A graph freezes the shot's refs into `ref_urls` on every billed
    node. Re-attaching a scene's photos leaves the prompt untouched, so
    a hash over the prompt alone called the old drawing fresh and the
    next keyframe rendered against references nobody meant to use."""
    cid = a_concept(tmp_db)
    concept = preprod.get_concept(cid, dsn=tmp_db, account_id=None)
    shots = [dict(s) for s in concept["shots"]]
    shots[0]["refs"] = ["/characters/michael/photo/a.jpg"]
    preprod.update_concept_shots(cid, {"shots": shots}, dsn=tmp_db, account_id=None)

    client.put(f"/api/concepts/{cid}/shots/1/graph", json={"graph": GRAPH})
    assert client.get(f"/api/concepts/{cid}/shots/1/graph").json()["stale"] is False

    shots[0]["refs"] = ["/characters/michael/photo/a.jpg",
                        "/characters/michael/photo/b.jpg"]
    preprod.update_concept_shots(cid, {"shots": shots}, dsn=tmp_db, account_id=None)
    assert client.get(f"/api/concepts/{cid}/shots/1/graph").json()["stale"] is True


def test_staleness_is_checked_on_read_not_invalidated_on_write(tmp_db):
    """Comparing on read is self-healing: a route added later that
    rewrites a prompt cannot forget to invalidate anything."""
    cid = a_concept(tmp_db, prompt="original")
    client.put(f"/api/concepts/{cid}/shots/1/graph", json={"graph": GRAPH})
    # a write that bypasses every API route entirely
    concept = preprod.get_concept(cid, dsn=tmp_db, account_id=None)
    shots = [dict(s) for s in concept["shots"]]
    shots[0]["prompt"] = "changed behind the API's back"
    preprod.update_concept_shots(cid, {"shots": shots}, dsn=tmp_db, account_id=None)
    assert client.get(f"/api/concepts/{cid}/shots/1/graph").json()["stale"] is True


def test_the_reset_hatch_drops_every_saved_canvas(tmp_db):
    cid = preprod.save_concept(
        {"title": "two shots", "shots": [
            {"n": 1, "source": "AI", "prompt": "one"},
            {"n": 2, "source": "AI", "prompt": "two"}]},
        brand="zeropage", dsn=tmp_db, account_id=None)
    client.put(f"/api/concepts/{cid}/shots/1/graph", json={"graph": GRAPH})
    client.put(f"/api/concepts/{cid}/shots/2/graph", json={"graph": GRAPH})
    assert client.delete(f"/api/concepts/{cid}/graph").json()["removed"] == 2
    assert client.get(f"/api/concepts/{cid}/shots/1/graph").json()["graph"] is None


# --- it stays out of the workflow library -----------------------------------

def test_a_concept_canvas_is_not_a_library_workflow(tmp_db):
    """Otherwise the Open… picker fills with one entry per shot anyone
    has ever opened."""
    cid = a_concept(tmp_db)
    client.put(f"/api/concepts/{cid}/shots/1/graph", json={"graph": GRAPH})
    listed = client.get("/api/workflows?brand=zeropage").json()["items"]
    assert all(w["name"] != "The Garage Guest" for w in listed)


def test_the_saved_canvas_is_what_run_all_executes(tmp_db):
    """The graph that ran and the graph you come back to must be one
    row — otherwise they drift and the canvas lies about what produced
    the output sitting on it."""
    cid = a_concept(tmp_db)
    saved_id = client.put(f"/api/concepts/{cid}/shots/1/graph",
                          json={"graph": GRAPH}).json()["id"]
    ran = workflows.get_workflow(saved_id, dsn=tmp_db, account_id=None)
    assert ran["graph"]["nodes"][0]["id"] == 3


def test_an_empty_graph_is_refused_rather_than_stored(tmp_db):
    cid = a_concept(tmp_db)
    assert client.put(f"/api/concepts/{cid}/shots/1/graph",
                      json={"graph": {"nodes": []}}).status_code == 400


def test_saving_against_a_concept_that_does_not_exist_is_a_404(tmp_db):
    assert client.put("/api/concepts/9999/shots/1/graph",
                      json={"graph": GRAPH}).status_code == 404
