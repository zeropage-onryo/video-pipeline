"""
Tests for the Workflows surface: the saved-graph store
(src/workflows.py), the free-standing Runway wrapper
(runway.generate_from_prompt), the server-side executor
(app/workflow_runner.py), and the /api/workflows routes.

Hermetic throughout: Gemini and Runway are patched at the function the
code actually calls, the spend gate is exercised for real (refusal is
the default, exactly as production), and jobs are polled to completion
so a silently-dead thread fails loudly.
"""
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import jobs, workflow_runner
from app.main import app
from src import db, generative, imagery, render_assets, runway, workflows

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
def generated_asset_rag(monkeypatch):
    """Rendering tests exercise Asset Bank persistence, not Postgres."""
    monkeypatch.setattr(
        render_assets, "_ingest",
        lambda *a, **k: {"ok": True, "chunks": 1, "error": None})


@pytest.fixture(autouse=True)
def fresh_jobs():
    jobs.clear_all_for_tests()
    yield
    jobs.clear_all_for_tests()


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    path = tmp_path / "test.db"
    db.init_db(path)
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


# --- graph fixtures ---------------------------------------------------------

def node(node_id, node_type, inputs=None, properties=None):
    return {"id": node_id, "type": node_type, "pos": [0, 0],
            "inputs": inputs or [], "outputs": [],
            "properties": properties or {}, "title": node_type}


def slot(name, kind, link):
    return {"name": name, "type": kind, "link": link}


def reference_shape_graph():
    """The screenshot's exact shape: System Prompt + User Prompt ->
    LLM Enhance -> Generate."""
    return {
        "nodes": [
            node(1, "zpf/system_prompt", properties={"text": "SYS"}),
            node(2, "zpf/user_prompt", properties={"text": "USER"}),
            node(3, "zpf/enhance", inputs=[
                slot("system", "text", 1), slot("user", "text", 2),
                slot("image", "image", None)]),
            node(4, "zpf/generate", inputs=[
                slot("prompt", "text", 3), slot("image", "image", None)]),
        ],
        "links": [
            [1, 1, 0, 3, 0, "text"],
            [2, 2, 0, 3, 1, "text"],
            [3, 3, 0, 4, 0, "text"],
        ],
    }


# --- src/workflows.py -------------------------------------------------------

def test_workflow_crud_roundtrip(tmp_db):
    graph = {"nodes": [node(1, "zpf/user_prompt")], "links": []}
    wf_id = workflows.create_workflow("night ride", graph,
                                      brand="antihero", path=tmp_db, account_id=None)

    listed = workflows.list_workflows(path=tmp_db, account_id=None)
    assert [w["name"] for w in listed] == ["night ride"]
    assert listed[0]["node_count"] == 1
    assert "graph" not in listed[0]          # the list stays light

    loaded = workflows.get_workflow(wf_id, path=tmp_db, account_id=None)
    assert loaded["graph"] == graph

    assert workflows.update_workflow(wf_id, name="garage ritual", path=tmp_db, account_id=None)
    assert workflows.get_workflow(wf_id, path=tmp_db, account_id=None)["name"] == "garage ritual"
    # graph untouched by a name-only update
    assert workflows.get_workflow(wf_id, path=tmp_db, account_id=None)["graph"] == graph

    assert workflows.delete_workflow(wf_id, path=tmp_db, account_id=None)
    assert workflows.get_workflow(wf_id, path=tmp_db, account_id=None) is None
    assert not workflows.delete_workflow(wf_id, path=tmp_db, account_id=None)


def test_workflow_list_scopes_by_brand(tmp_db):
    workflows.create_workflow("a", {}, brand="antihero", path=tmp_db, account_id=None)
    workflows.create_workflow("z", {}, brand="zeropage", path=tmp_db, account_id=None)
    assert [w["name"] for w in
            workflows.list_workflows(brand="zeropage", path=tmp_db, account_id=None)] == ["z"]
    assert len(workflows.list_workflows(path=tmp_db, account_id=None)) == 2


# --- runway.generate_from_prompt --------------------------------------------

class FakeClient:
    def __init__(self, outputs=("https://fake.runway/clip.mp4",)):
        self.calls = []
        self._outputs = list(outputs)
        self.image_to_video = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        task = SimpleNamespace(output=self._outputs)
        return SimpleNamespace(wait_for_task_output=lambda: task)


@pytest.fixture
def fake_download(monkeypatch):
    def _fake(url, out_path):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"\x00" * 2048)

    monkeypatch.setattr(runway, "_download", _fake)


def test_generate_from_prompt_refuses_without_spend_approval(tmp_db, tmp_path,
                                                             monkeypatch):
    monkeypatch.delenv(runway.SPEND_ENV, raising=False)
    monkeypatch.setattr(runway, "RENDER_DIR", tmp_path / "renders")
    fake = FakeClient()
    result = runway.generate_from_prompt("x", db_path=tmp_db, client=fake)
    assert result["ok"] is False
    assert "not approved" in result["error"]
    assert fake.calls == []
    with generative.connect(tmp_db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM generations").fetchone()[0] == 0


def test_generate_from_prompt_honours_the_daily_cap(tmp_db, tmp_path, monkeypatch):
    monkeypatch.setenv(runway.SPEND_ENV, "1")
    monkeypatch.setattr(runway, "RENDER_DIR", tmp_path / "renders")
    monkeypatch.setattr(runway, "generations_today",
                        lambda db_path=None, account_id=None, everyone=False:
                        runway.DAILY_CAP)
    result = runway.generate_from_prompt("x", db_path=tmp_db, client=FakeClient())
    assert result["ok"] is False
    assert "daily cap" in result["error"]


def test_generate_from_prompt_renders_and_logs(tmp_db, tmp_path, monkeypatch,
                                               fake_download):
    monkeypatch.setenv(runway.SPEND_ENV, "1")
    monkeypatch.setattr(runway, "RENDER_DIR", tmp_path / "renders")
    monkeypatch.setattr("src.storage.configured", lambda: False)
    fake = FakeClient()
    result = runway.generate_from_prompt("a drawer closing", db_path=tmp_db,
                                         client=fake)
    assert result["ok"] is True
    assert result["media_url"].startswith("/renders/runway/wf-")
    assert "prompt_image" not in fake.calls[0]      # no reference, none sent
    with generative.connect(tmp_db) as conn:
        row = conn.execute("SELECT tool, params_json FROM generations").fetchone()
    assert row["tool"] == "runway"
    assert '"source": "workflow"' in row["params_json"]
    asset = render_assets.list_all(path=tmp_db, account_id=None)[0]
    assert result["asset_id"] == asset["id"]
    assert asset["media_kind"] == "video"
    assert asset["prompt"] == "a drawer closing"
    assert asset["model"] == runway.DEFAULT_MODEL


def test_generate_from_prompt_turns_bytes_into_a_data_uri(tmp_db, tmp_path,
                                                          monkeypatch, fake_download):
    monkeypatch.setenv(runway.SPEND_ENV, "1")
    monkeypatch.setattr(runway, "RENDER_DIR", tmp_path / "renders")
    monkeypatch.setattr("src.storage.configured", lambda: False)
    fake = FakeClient()
    result = runway.generate_from_prompt("x", reference_image=b"\xff\xd8jpg",
                                         db_path=tmp_db, client=fake)
    assert result["ok"] is True
    assert fake.calls[0]["prompt_image"].startswith("data:image/jpeg;base64,")
    # an http URL passes straight through
    runway.generate_from_prompt("x", reference_image="https://x.test/a.jpg",
                                db_path=tmp_db, client=fake)
    assert fake.calls[1]["prompt_image"] == "https://x.test/a.jpg"


def test_generate_from_prompt_refuses_an_empty_prompt(tmp_db):
    result = runway.generate_from_prompt("  ", db_path=tmp_db)
    assert result["ok"] is False
    assert "empty prompt" in result["error"]


# --- app/workflow_runner ----------------------------------------------------

def test_topo_order_runs_sources_before_dependents():
    order, leftover = workflow_runner.topo_order(reference_shape_graph())
    assert leftover == []
    assert order.index(1) < order.index(3)
    assert order.index(2) < order.index(3)
    assert order.index(3) < order.index(4)


def test_topo_order_flags_a_cycle():
    graph = {
        "nodes": [node(1, "zpf/enhance", inputs=[slot("user", "text", 2)]),
                  node(2, "zpf/enhance", inputs=[slot("user", "text", 1)])],
        "links": [[1, 1, 0, 2, 0, "text"], [2, 2, 0, 1, 0, "text"]],
    }
    order, leftover = workflow_runner.topo_order(graph)
    assert order == []
    assert set(leftover) == {1, 2}


def test_execute_graph_flows_values_through_the_reference_shape(tmp_db, monkeypatch):
    calls = []

    def fake_enhance(system, user, images=None, *, gemini_client,
                     resolve_photo=None, model=None):
        calls.append(("enhance", system, user))
        return f"ENHANCED[{system}|{user}]"

    def fake_generate(prompt, *, reference_image=None, db_path=None, **kw):
        calls.append(("generate", prompt))
        return {"ok": True, "media_url": "/renders/runway/wf-1.mp4",
                "generation_id": 1, "path": "x", "error": None}

    monkeypatch.setattr(workflow_runner, "enhance", fake_enhance)
    monkeypatch.setattr(runway, "generate_from_prompt", fake_generate)
    # this test is "a CONFIGURED Runway renders" -- an unconfigured one
    # is skipped, not run (see the unarmed-connector test below)
    monkeypatch.setenv("RUNWAYML_API_SECRET", "k")

    emitted = []
    result = workflow_runner.execute_graph(
        reference_shape_graph(), gemini_client=object(), db_path=tmp_db,
        emit=lambda states, frac, detail: emitted.append(detail))

    assert result["ok"] is True
    assert calls == [("enhance", "SYS", "USER"),
                     ("generate", "ENHANCED[SYS|USER]")]
    assert result["nodes"]["4"] == {"status": "done", "kind": "media",
                                    "output": "/renders/runway/wf-1.mp4",
                                    "error": None}
    assert emitted  # progress was pushed along the way


def test_execute_graph_skips_downstream_of_a_failure(tmp_db, monkeypatch):
    called = []
    monkeypatch.setattr(runway, "generate_from_prompt",
                        lambda *a, **k: called.append(a) or {"ok": True})
    # no gemini client -> the enhance node fails, generate must be skipped
    result = workflow_runner.execute_graph(reference_shape_graph(),
                                           gemini_client=None, db_path=tmp_db)
    assert result["ok"] is False
    assert result["nodes"]["3"]["status"] == "failed"
    assert "GEMINI_API_KEY" in result["nodes"]["3"]["error"]
    assert result["nodes"]["4"]["status"] == "skipped"
    assert called == []                    # runway was never touched
    # the pure nodes upstream still ran
    assert result["nodes"]["1"]["status"] == "done"


def test_execute_graph_ground_node_calls_reference_block(tmp_db, monkeypatch):
    seen = {}

    def fake_block(spark=None, client=None, db_path=None):
        seen["spark"] = spark
        return "REFS"

    monkeypatch.setattr("src.shootgen.reference_block", fake_block)
    graph = {
        "nodes": [node(1, "zpf/user_prompt", properties={"text": "gearing up"}),
                  node(2, "zpf/ground", inputs=[slot("spark", "text", 1)])],
        "links": [[1, 1, 0, 2, 0, "text"]],
    }
    result = workflow_runner.execute_graph(graph, db_path=tmp_db)
    assert result["nodes"]["2"]["output"] == "REFS"
    assert seen["spark"] == "gearing up"


# --- /api/workflows ---------------------------------------------------------

def test_api_workflow_crud(tmp_db):
    created = client.post("/api/workflows", json={
        "name": "shape", "graph": reference_shape_graph()}).json()
    wf_id = created["id"]

    listed = client.get("/api/workflows").json()["items"]
    assert [w["id"] for w in listed] == [wf_id]
    assert listed[0]["node_count"] == 4

    loaded = client.get(f"/api/workflows/{wf_id}").json()
    assert loaded["graph"]["nodes"][0]["type"] == "zpf/system_prompt"

    assert client.put(f"/api/workflows/{wf_id}",
                      json={"name": "renamed"}).json()["id"] == wf_id
    assert client.get(f"/api/workflows/{wf_id}").json()["name"] == "renamed"

    assert client.delete(f"/api/workflows/{wf_id}").json()["deleted"] == wf_id
    assert client.get(f"/api/workflows/{wf_id}").status_code == 404


def test_api_run_executes_pure_graph_and_publishes_node_states(tmp_db):
    graph = {"nodes": [node(1, "zpf/system_prompt", properties={"text": "hi"})],
             "links": []}
    wf_id = client.post("/api/workflows",
                        json={"name": "pure", "graph": graph}).json()["id"]
    job_id = client.post(f"/api/workflows/{wf_id}/run").json()["job_id"]
    job = wait_for_job(job_id)
    assert job["status"] == "done"
    assert job["node_states"]["1"]["status"] == "done"
    assert job["node_states"]["1"]["output"] == "hi"


def test_api_run_refuses_an_empty_graph(tmp_db):
    wf_id = client.post("/api/workflows", json={"name": "empty"}).json()["id"]
    res = client.post(f"/api/workflows/{wf_id}/run")
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "empty_graph"


def test_api_run_generate_node_hits_the_spend_gate(tmp_db, monkeypatch):
    """The acceptance line: a Workflows render does NOT fire without
    RUNWAY_SPEND_OK=1 -- the run fails with the module's own refusal,
    and the Runway SDK is never reached (the network guard would scream
    if it were)."""
    monkeypatch.delenv(runway.SPEND_ENV, raising=False)
    monkeypatch.setenv("RUNWAYML_API_SECRET", "k")
    graph = {
        "nodes": [node(1, "zpf/user_prompt", properties={"text": "night ride"}),
                  node(2, "zpf/generate", inputs=[slot("prompt", "text", 1),
                                                  slot("image", "image", None)])],
        "links": [[1, 1, 0, 2, 0, "text"]],
    }
    wf_id = client.post("/api/workflows",
                        json={"name": "spend", "graph": graph}).json()["id"]
    job = wait_for_job(client.post(f"/api/workflows/{wf_id}/run").json()["job_id"])
    assert job["status"] == "failed"
    assert "not approved" in job["node_states"]["2"]["error"]


def test_api_exec_ground(tmp_db, monkeypatch):
    monkeypatch.setattr("src.shootgen.reference_block",
                        lambda spark=None, client=None, db_path=None: "REFS")
    res = client.post("/api/workflows/exec/ground", json={"spark": "x"}).json()
    assert res == {"references": "REFS"}


def test_api_exec_enhance_needs_the_key(tmp_db, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    res = client.post("/api/workflows/exec/enhance", json={"user": "x"})
    assert res.status_code == 503


def test_api_exec_enhance_runs_as_a_job(tmp_db, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr(workflow_runner, "enhance",
                        lambda system, user, images=None, **kw: f"E[{user}]")
    job_id = client.post("/api/workflows/exec/enhance",
                         json={"user": "night ride"}).json()["job_id"]
    job = wait_for_job(job_id)
    assert job["status"] == "done"
    assert job["output"] == "E[night ride]"


def test_enhance_defaults_to_the_enhancement_instruction(monkeypatch):
    """No wired system prompt no longer means an uninstructed model:
    the vivid-details instruction (prompts/enhance_system.txt) is the
    default, so a bare user prompt is actually ENHANCED."""
    captured = {}

    def fake_generate(client, model, parts):
        captured["text"] = parts[-1]
        return "OUT"

    monkeypatch.setattr("src.gemini_utils.generate_with_retry", fake_generate)
    out = workflow_runner.enhance("", "night ride", gemini_client=object())
    assert out == "OUT"
    assert captured["text"].startswith(workflows._enhance_system_text())
    assert "night ride" in captured["text"]


def test_enhance_folds_references_as_grounding_not_instruction(monkeypatch):
    captured = {}

    def fake_generate(client, model, parts):
        captured["text"] = parts[-1]
        return "OUT"

    monkeypatch.setattr("src.gemini_utils.generate_with_retry", fake_generate)
    workflow_runner.enhance("SYS", "USER", references="THE SHELF",
                            gemini_client=object())
    assert captured["text"].startswith("SYS")
    assert "REFERENCES — ground the prompt in these:\nTHE SHELF" in captured["text"]
    assert captured["text"].endswith("USER")


def test_enhance_still_refuses_nothing_at_all():
    with pytest.raises(ValueError):
        workflow_runner.enhance("", "", gemini_client=object())


def test_execute_graph_enhance_auto_grounds_on_the_backend(tmp_db, monkeypatch):
    """The Director shot chain's shape: no Ground node on the canvas --
    the enhance node's auto_ground property pulls the RAG block
    server-side, and image_url carries the shot's reference invisibly."""
    calls = []

    def fake_enhance(system, user, images=None, *, gemini_client,
                     resolve_photo=None, model=None, references=""):
        calls.append((system, user, images, references))
        return "E"

    monkeypatch.setattr(workflow_runner, "enhance", fake_enhance)
    monkeypatch.setattr("src.shootgen.reference_block",
                        lambda spark=None, client=None, db_path=None: "REFS")
    graph = {
        "nodes": [
            node(1, "zpf/user_prompt", properties={"text": "night ride"}),
            node(3, "zpf/enhance",
                 inputs=[slot("system", "text", None),
                         slot("user", "text", 2),
                         slot("image", "image", None),
                         slot("references", "text", None)],
                 properties={"auto_ground": True,
                             "image_url": "https://example.com/ref.jpg"}),
        ],
        "links": [[2, 1, 0, 3, 1, "text"]],
    }
    result = workflow_runner.execute_graph(graph, gemini_client=object(),
                                           db_path=tmp_db)
    assert result["ok"] is True
    assert calls == [("", "night ride", ["https://example.com/ref.jpg"], "REFS")]


def test_api_presets_carries_the_enhance_instruction(tmp_db):
    """The enhance instruction is asserted on what it PROTECTS, not on
    its wording (2026-08-28). The original told the model to "expand the
    user's simple prompt", which on a finished director's prompt made it
    summarise: a real run dropped every "(reference photos on file)"
    lock, the whole Avoid list, the beat order and the no-music rule,
    and handed the renderer a paraphrase. Those four are the contract."""
    res = client.get("/api/presets").json()
    text = res["enhance_system"].lower()
    assert "output only the prompt" in text
    for protected in ("reference photos on file", "avoid", "order", "music"):
        assert protected in text, f"the instruction no longer protects {protected!r}"
    # and it must steer AWAY from the glossy render, not toward it
    assert "do not add" in text
    assert "cinematic" in text.split("do not add", 1)[1]


def test_execute_graph_wires_ground_into_enhance_references(tmp_db, monkeypatch):
    """The Director shot chain's shape: Ground's output feeds the
    enhance node's references port, not its system port."""
    calls = []

    def fake_enhance(system, user, images=None, *, gemini_client,
                     resolve_photo=None, model=None, references=""):
        calls.append((system, user, references))
        return "E"

    monkeypatch.setattr(workflow_runner, "enhance", fake_enhance)
    monkeypatch.setattr("src.shootgen.reference_block",
                        lambda spark=None, client=None, db_path=None: "REFS")
    graph = {
        "nodes": [
            node(1, "zpf/user_prompt", properties={"text": "night ride"}),
            node(2, "zpf/ground", inputs=[slot("spark", "text", 1)]),
            node(3, "zpf/enhance",
                 inputs=[slot("system", "text", None),
                         slot("user", "text", 2),
                         slot("image", "image", None),
                         slot("references", "text", 3)]),
        ],
        "links": [[1, 1, 0, 2, 0, "text"], [2, 1, 0, 3, 1, "text"],
                  [3, 2, 0, 3, 3, "text"]],
    }
    result = workflow_runner.execute_graph(graph, gemini_client=object(),
                                           db_path=tmp_db)
    assert result["ok"] is True
    assert calls == [("", "night ride", "REFS")]


def test_api_exec_generate_needs_the_runway_key(tmp_db, monkeypatch):
    monkeypatch.delenv("RUNWAYML_API_SECRET", raising=False)
    res = client.post("/api/workflows/exec/generate", json={"prompt": "x"})
    assert res.status_code == 503


def test_api_exec_generate_respects_the_spend_gate(tmp_db, monkeypatch):
    monkeypatch.setenv("RUNWAYML_API_SECRET", "k")
    monkeypatch.delenv(runway.SPEND_ENV, raising=False)
    job = wait_for_job(client.post("/api/workflows/exec/generate",
                                   json={"prompt": "x"}).json()["job_id"])
    assert job["status"] == "failed"
    assert "not approved" in job["error"]


# --- the shell + the dev page ----------------------------------------------

def test_ui_shell_is_one_board_per_rail_view(tmp_db):
    """The 2026-08-28 merge: Pipeline has no tabs left. Scenes and
    concepts were always the same row, so they are one board; the idea
    is typed on Studio and the spend is approved in Queue. The node
    canvas stays its OWN rail view, Director -- the nodes must never be
    buried behind a tab -- and the canvas (LiteGraph) still ships with
    the shell."""
    html = client.get("/ui").text
    assert 'data-view="workflows"' not in html
    assert 'data-view="director"' in html
    assert 'data-view="queue"' in html
    assert "data-ptab=" not in html            # the tab strip is gone entirely
    assert 'data-view="evals"' not in html
    assert "vendor/litegraph.js" in html


def test_the_idea_composer_lives_only_on_studio(tmp_db):
    """One place to type an idea. The Pipeline composer is gone, and
    Studio's Create carries the 1-4 count that replaced it."""
    html = client.get("/ui").text
    assert html.count('id="ccount"') == 1
    assert 'id="sceneidea"' not in html        # the Pipeline composer
    assert 'id="genprompt"' not in html        # the Generate tab composer
    assert '<option value="4" selected>4 concepts</option>' in html
    assert '<option value="5"' not in html     # 4 is the cap the API enforces


def test_the_queue_is_the_approval_gate(tmp_db):
    """Rendering is the only step that spends, so it is the only one
    with a gate -- and the gate is in Queue, not on the board."""
    html = client.get("/ui").text
    assert 'id="pendlist"' in html
    assert "Awaiting approval" in html


def test_evals_url_redirects_into_the_dev_studio(tmp_db):
    """Evals folded into the Dev Studio's Stats tab (2026-08-26); the
    old URL keeps working as a redirect. The tab's own rendering (same
    evals_dev.js + /api/evals endpoints) is asserted in test_app.py."""
    res = client.get("/evals", follow_redirects=False)
    assert res.status_code == 308
    assert res.headers["location"] == "/studio?tab=stats"


# --- the seeded default template --------------------------------------------

def test_seed_default_plants_the_template_once(tmp_db):
    wf_id = workflows.seed_default(path=tmp_db)
    assert wf_id is not None
    assert workflows.seed_default(path=tmp_db) is None   # idempotent

    template = workflows.get_workflow(wf_id, path=tmp_db, account_id=None)
    assert template["name"] == "Prompt enhancement"
    assert template["brand"] is None                     # shared across brands
    types = [n["type"] for n in template["graph"]["nodes"]]
    assert types == ["zpf/system_prompt", "zpf/user_prompt",
                     "zpf/enhance", "zpf/nano_banana"]
    # pre-wired: system+user feed enhance, enhance feeds the image node
    assert [(link[1], link[3]) for link in template["graph"]["links"]] \
        == [(1, 3), (2, 3), (3, 4)]
    # the System Prompt ships with the prompts/ text, not empty
    seeded = template["graph"]["nodes"][0]["properties"]["text"]
    assert "output only the prompt" in seeded.lower()
    assert len(seeded) > 200


def test_seed_default_respects_an_intentionally_emptied_slate(tmp_db):
    wf_id = workflows.seed_default(path=tmp_db)
    workflows.create_workflow("mine", {}, brand="antihero", path=tmp_db, account_id=None)
    workflows.delete_workflow(wf_id, path=tmp_db, account_id=None)
    # other workflows exist -> the deleted template stays deleted
    assert workflows.seed_default(path=tmp_db) is None


def test_brandless_template_shows_up_under_every_brand(tmp_db):
    workflows.seed_default(path=tmp_db)
    workflows.create_workflow("z", {}, brand="zeropage", path=tmp_db, account_id=None)
    for brand in ("antihero", "zeropage"):
        names = [w["name"] for w in workflows.list_workflows(brand=brand, path=tmp_db, account_id=None)]
        assert "Prompt enhancement" in names


def test_default_template_executes_end_to_end(tmp_db, monkeypatch):
    """The seeded graph is a runnable drawing, not a picture of one:
    walk it through the real executor with both model calls stubbed."""
    from src import nano_banana

    monkeypatch.setattr(workflow_runner, "enhance",
                        lambda system, user, **kw: f"ENHANCED[{user}]")
    calls = {}

    def fake_generate(prompt, **kwargs):
        calls["prompt"] = prompt
        return {"ok": True, "media_url": "/renders/nano/wf-test.png",
                "generation_id": 1, "path": "x", "error": None}

    monkeypatch.setattr(nano_banana, "generate_from_prompt", fake_generate)

    graph = workflows.default_template()
    graph["nodes"][1]["properties"]["text"] = "a red bike"
    result = workflow_runner.execute_graph(graph, gemini_client=object(),
                                           db_path=tmp_db)
    assert result["ok"]
    assert calls["prompt"] == "ENHANCED[a red bike]"
    assert result["nodes"]["4"]["output"] == "/renders/nano/wf-test.png"


# --- nano_banana.generate_from_prompt ---------------------------------------

class FakeGeminiImageClient:
    """The google-genai response shape for an image model: parts with
    inline_data bytes."""
    def __init__(self, image=b"\x89PNG fake"):
        inline = SimpleNamespace(data=image, mime_type="image/png")
        part = SimpleNamespace(inline_data=inline)
        content = SimpleNamespace(parts=[part])
        candidate = SimpleNamespace(content=content)
        response = SimpleNamespace(candidates=[candidate], text=None)
        self.calls = []

        def generate_content(model, contents, config=None):
            self.calls.append({"model": model, "contents": contents,
                               "config": config})
            return response

        self.models = SimpleNamespace(generate_content=generate_content)


def test_nano_generate_renders_and_logs(tmp_db, tmp_path, monkeypatch):
    from src import nano_banana

    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr(nano_banana, "RENDER_DIR", tmp_path / "nano")
    monkeypatch.setattr("src.storage.configured", lambda: False)
    fake = FakeGeminiImageClient()
    result = nano_banana.generate_from_prompt("a red bike", db_path=tmp_db,
                                              client=fake)
    assert result["ok"], result["error"]
    assert result["media_url"].startswith("/renders/nano/")
    assert (tmp_path / "nano" / result["media_url"].split("/")[-1]).read_bytes() \
        == b"\x89PNG fake"
    with generative.connect(tmp_db) as conn:
        rows = conn.execute("SELECT tool FROM generations").fetchall()
    assert [r[0] for r in rows] == ["nano"]
    assert nano_banana.generations_today(db_path=tmp_db) == 1
    asset = render_assets.list_all(path=tmp_db, account_id=None)[0]
    assert result["asset_id"] == asset["id"]
    assert asset["media_kind"] == "image"
    assert asset["prompt"] == "a red bike"
    assert asset["model"] == nano_banana.MODEL


def test_nano_generate_honours_the_daily_cap(tmp_db, tmp_path, monkeypatch):
    from src import nano_banana

    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr(nano_banana, "RENDER_DIR", tmp_path / "nano")
    monkeypatch.setattr("src.storage.configured", lambda: False)
    monkeypatch.setattr(nano_banana, "DAILY_CAP", 1)
    fake = FakeGeminiImageClient()
    assert nano_banana.generate_from_prompt("one", db_path=tmp_db, client=fake)["ok"]
    second = nano_banana.generate_from_prompt("two", db_path=tmp_db, client=fake)
    assert not second["ok"] and "daily cap" in second["error"]
    assert len(fake.calls) == 1                          # capped before the call


def test_nano_generate_refuses_an_empty_prompt_and_missing_key(tmp_db, monkeypatch):
    from src import nano_banana

    monkeypatch.setenv("GEMINI_API_KEY", "k")
    assert not nano_banana.generate_from_prompt("  ", db_path=tmp_db)["ok"]
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    result = nano_banana.generate_from_prompt("a bike", db_path=tmp_db)
    assert not result["ok"] and "GEMINI_API_KEY" in result["error"]


def test_nano_generate_surfaces_a_textonly_refusal(tmp_db, tmp_path, monkeypatch):
    from src import nano_banana

    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr(nano_banana, "RENDER_DIR", tmp_path / "nano")
    fake = FakeGeminiImageClient()
    fake.models = SimpleNamespace(
        generate_content=lambda model, contents, config=None:
        SimpleNamespace(candidates=[], text="no can do"))
    result = nano_banana.generate_from_prompt("a bike", db_path=tmp_db, client=fake)
    assert not result["ok"] and "no image" in result["error"]


def test_nano_asks_for_the_shape_it_needs(tmp_db, tmp_path, monkeypatch):
    """Every render here is vertical, and saying "9:16" inside the prompt
    does not make it so — the model infers a shape from the references
    unless the request configures one, and returned 3:4 for a shot whose
    prompt opened with "9:16" (2026-08-29). The keyframe is what Runway
    anchors the clip on, so the wrong shape there crops the clip."""
    from src import nano_banana

    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr(nano_banana, "RENDER_DIR", tmp_path / "nano")
    monkeypatch.setattr("src.storage.configured", lambda: False)
    fake = FakeGeminiImageClient()
    assert nano_banana.generate_from_prompt("a red bike", db_path=tmp_db,
                                            client=fake)["ok"]
    config = fake.calls[0]["config"]
    assert config is not None
    assert config.image_config.aspect_ratio == "9:16"


def test_nano_leaves_the_shape_alone_when_nothing_is_asked_for(tmp_db, tmp_path,
                                                              monkeypatch):
    """Empty means "don't configure it" — the behaviour every render had
    before this, still reachable."""
    from src import nano_banana

    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr(nano_banana, "RENDER_DIR", tmp_path / "nano")
    monkeypatch.setattr("src.storage.configured", lambda: False)
    fake = FakeGeminiImageClient()
    assert nano_banana.generate_from_prompt("a red bike", db_path=tmp_db,
                                            client=fake, aspect_ratio="",
                                            image_size="")["ok"]
    assert fake.calls[0]["config"] is None


def test_a_config_the_endpoint_rejects_still_renders(tmp_db, tmp_path, monkeypatch):
    """A wrongly-shaped frame is a far better outcome than losing a
    billed call to an INVALID_ARGUMENT, so an unsupported image_config
    retries once without it. NANO_IMAGE_SIZE is the reason this exists:
    2K is not offered by every model on this endpoint."""
    from src import nano_banana

    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr(nano_banana, "RENDER_DIR", tmp_path / "nano")
    monkeypatch.setattr("src.storage.configured", lambda: False)
    fake = FakeGeminiImageClient()
    inner = fake.models.generate_content

    def picky(model, contents, config=None):
        if config is not None:
            raise RuntimeError("400 INVALID_ARGUMENT: image_size not supported")
        return inner(model, contents, config=config)

    fake.models = SimpleNamespace(generate_content=picky)
    result = nano_banana.generate_from_prompt("a red bike", db_path=tmp_db,
                                              client=fake, image_size="2K")
    assert result["ok"], result["error"]
    assert [c["config"] for c in fake.calls] == [None]    # the retry landed


def test_a_real_failure_is_not_swallowed_by_the_shape_retry(tmp_db, tmp_path,
                                                            monkeypatch):
    """Only INVALID_ARGUMENT degrades. Anything else still surfaces —
    the image IS the deliverable here."""
    from src import nano_banana

    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr(nano_banana, "RENDER_DIR", tmp_path / "nano")
    fake = FakeGeminiImageClient()

    def broken(model, contents, config=None):
        raise RuntimeError("500 INTERNAL")

    fake.models = SimpleNamespace(generate_content=broken)
    result = nano_banana.generate_from_prompt("a red bike", db_path=tmp_db,
                                              client=fake)
    assert not result["ok"] and "INTERNAL" in result["error"]


# --- the nano node in the executor and the API ------------------------------

def test_image_bytes_for_gemini_resolves_renders_and_data_uris(tmp_path):
    import base64
    assert imagery.image_bytes_for_gemini(
        "data:image/png;base64," + base64.b64encode(b"PIX").decode()) == b"PIX"
    photo = tmp_path / "p.jpg"
    photo.write_bytes(b"JPEGBYTES")
    assert imagery.image_bytes_for_gemini(
        "/assets/antihero/p.jpg", resolve_photo=lambda v: photo) == b"JPEGBYTES"
    assert imagery.image_bytes_for_gemini("https://x/y.png") is None


# --- the keyframe -> clip chain ---------------------------------------------

def test_still_framing_keeps_the_prompt_and_drops_the_motion_instruction():
    """The bug this exists for: a video prompt handed to an image model
    gets answered in prose ("Understood, I will apply these
    guidelines...") instead of rendered. Pure, so it is checkable
    without spending a call."""
    from src import nano_banana

    framed = nano_banana.as_still_frame(
        "Vertical 9:16 video — the camera follows the subject, handheld drift")
    # every word of the original survives -- the detail is the value
    assert "the camera follows the subject, handheld drift" in framed
    # ...under an instruction that makes one frame the deliverable
    assert "single photorealistic still image" in framed
    assert "never as a sequence" in framed
    assert nano_banana.as_still_frame("   ") == ""


def test_nano_sends_the_framed_prompt_but_logs_what_the_person_wrote(
        tmp_db, tmp_path, monkeypatch):
    import json

    from src import nano_banana

    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr(nano_banana, "RENDER_DIR", tmp_path / "nano")
    monkeypatch.setattr("src.storage.configured", lambda: False)
    fake = FakeGeminiImageClient()
    assert nano_banana.generate_from_prompt("a red bike, camera pushes in",
                                            db_path=tmp_db, client=fake)["ok"]
    sent = fake.calls[0]["contents"][-1]
    assert "single photorealistic still image" in sent
    assert "a red bike, camera pushes in" in sent
    with generative.connect(tmp_db) as conn:
        prompt, params = conn.execute(
            "SELECT prompt, params_json FROM generations").fetchone()
    assert prompt == "a red bike, camera pushes in"       # not the wrapper
    assert json.loads(params)["framing"] == "still"


# --- references actually reaching the models --------------------------------

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"pixels"
R2_URL = "https://cdn.example/renders/nano/wf-1.png"


def test_a_remote_reference_reaches_gemini_as_vision_not_as_a_url(monkeypatch):
    """The regression this exists for: once R2 was configured every
    reference image became an https URL, and Gemini cannot fetch a URL.
    The reference looked attached on the canvas and reached no model --
    silently dropped for Nano, and reduced to a line of TEXT naming the
    URL for enhance, which is indistinguishable from no reference."""
    monkeypatch.setattr(imagery, "fetch_image_bytes",
                        lambda url: PNG_BYTES if url == R2_URL else None)
    captured = {}
    monkeypatch.setattr("src.gemini_utils.generate_with_retry",
                        lambda client, model, contents:
                        captured.setdefault("parts", contents) and "ENHANCED")

    workflow_runner.enhance("SYS", "a watch macro", images=[R2_URL],
                            gemini_client=object(), resolve_photo=lambda v: None)
    parts = captured["parts"]
    assert len(parts) == 2                       # an image Part, then the text
    assert parts[0].inline_data.data == PNG_BYTES
    assert parts[0].inline_data.mime_type == "image/png"   # sniffed, not assumed
    assert R2_URL not in parts[-1]               # no longer a URL the model can't use


def test_an_unreachable_reference_says_so_instead_of_pretending(monkeypatch):
    monkeypatch.setattr(imagery, "fetch_image_bytes", lambda url: None)
    captured = {}
    monkeypatch.setattr("src.gemini_utils.generate_with_retry",
                        lambda client, model, contents:
                        captured.setdefault("parts", contents) and "E")
    workflow_runner.enhance("SYS", "a watch macro", images=[R2_URL],
                            gemini_client=object(), resolve_photo=lambda v: None)
    assert "could not be loaded" in captured["parts"][-1]


def test_image_bytes_for_gemini_fetches_a_public_url(monkeypatch):
    monkeypatch.setattr(imagery, "fetch_image_bytes",
                        lambda url: PNG_BYTES)
    assert imagery.image_bytes_for_gemini(R2_URL) == PNG_BYTES


def test_the_reference_fetch_refuses_private_addresses():
    """The URL comes out of user-controlled graph JSON and the fetch runs
    server-side, so the SSRF guard is the wall. Literal IPs, so no DNS
    (and no network) is needed to check it."""
    for host in ("127.0.0.1", "10.0.0.5", "169.254.169.254", "192.168.1.1"):
        assert imagery._public_host(host) is False
    assert imagery.fetch_image_bytes("http://169.254.169.254/latest/meta-data") is None
    assert imagery.fetch_image_bytes("file:///etc/passwd") is None


def test_sniff_mime_reads_the_magic_number():
    from src.gemini_utils import sniff_mime

    assert sniff_mime(PNG_BYTES) == "image/png"
    assert sniff_mime(b"\xff\xd8\xff\xe0stuff") == "image/jpeg"
    assert sniff_mime(b"RIFF1234WEBPmore") == "image/webp"
    assert sniff_mime(b"") == "image/jpeg"          # a safe default, never a crash


def test_nano_tells_the_model_what_the_reference_is_for(tmp_db, tmp_path, monkeypatch):
    """Bytes with no instruction leave the model guessing between copy
    this / continue this / ignore this."""
    from src import nano_banana

    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr(nano_banana, "RENDER_DIR", tmp_path / "nano")
    monkeypatch.setattr("src.storage.configured", lambda: False)
    fake = FakeGeminiImageClient()
    assert nano_banana.generate_from_prompt("a watch macro", reference_image=PNG_BYTES,
                                            db_path=tmp_db, client=fake)["ok"]
    parts = fake.calls[0]["contents"]
    assert parts[0].inline_data.mime_type == "image/png"   # not the old blanket jpeg
    assert "THE ATTACHED IMAGE is reference material" in parts[-1]
    assert "Do NOT copy its framing" in parts[-1]
    # ...and no reference means no note about one
    assert "THE ATTACHED IMAGE" not in nano_banana.as_still_frame("a watch macro")


# --- references, plural, into every node that runs -------------------------

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"pixels"


def test_a_scenes_references_inform_every_node_that_runs(tmp_db, monkeypatch):
    """The ask: 'the reference images inform gemini flash, nano banana
    and generate whenever they are run'. They ride on the node as
    ref_urls (grounding stays on the backend), and every billed node
    grounds on the same list."""
    JPEG = b"\xff\xd8\xff\xe0face"
    refs = ["https://cdn.test/face.jpg", "https://cdn.test/jacket.jpg"]
    monkeypatch.setattr(imagery, "fetch_image_bytes", lambda url: JPEG)
    monkeypatch.setattr(runway, "has_key", lambda: True)

    seen = {}
    monkeypatch.setattr(workflow_runner, "enhance",
                        lambda system, user, images=None, **kw:
                        seen.__setitem__("enhance", images) or "ENHANCED")
    monkeypatch.setattr("src.nano_banana.generate_from_prompt",
                        lambda prompt, *, reference_image=None, **kw:
                        seen.__setitem__("nano", reference_image) or
                        {"ok": True, "media_url": "https://cdn.test/key.png",
                         "generation_id": 1, "path": "k", "error": None})
    monkeypatch.setattr(runway, "generate_from_prompt",
                        lambda prompt, *, reference_image=None, **kw:
                        seen.__setitem__("runway", reference_image) or
                        {"ok": True, "media_url": "/c.mp4", "generation_id": 2,
                         "path": "c", "error": None})

    graph = {
        "nodes": [
            node(1, "zpf/user_prompt", properties={"text": "night ride"}),
            node(2, "zpf/enhance",
                 inputs=[slot("system", "text", None), slot("user", "text", 1),
                         slot("image", "image", None),
                         slot("references", "text", None)],
                 properties={"ref_urls": refs}),
            node(3, "zpf/nano_banana",
                 inputs=[slot("prompt", "text", 2), slot("image", "image", None)],
                 properties={"ref_urls": refs}),
            node(4, "zpf/generate",
                 inputs=[slot("prompt", "text", 3), slot("image", "image", None)],
                 properties={"ref_urls": refs}),
        ],
        "links": [[1, 1, 0, 2, 1, "text"], [2, 2, 0, 3, 0, "text"],
                  [3, 2, 0, 4, 0, "text"]],
    }
    workflow_runner.execute_graph(graph, gemini_client=object(), db_path=tmp_db)

    assert seen["enhance"] == refs                 # Flash sees both
    # Nano gets both, as (label, bytes). These two are plain CDN URLs
    # rather than asset-bank paths, so there is no asset to name and the
    # caption is empty -- see test_a_reference_url_names_its_asset for
    # the /characters/... case that carries a name.
    assert seen["nano"] == [("", JPEG), ("", JPEG)]
    # Runway's API anchors on ONE frame, so it takes the first only
    assert seen["runway"] == "https://cdn.test/face.jpg"


def test_nano_attaches_every_reference_and_says_how_many(tmp_db, tmp_path, monkeypatch):
    from src import nano_banana

    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr(nano_banana, "RENDER_DIR", tmp_path / "nano")
    monkeypatch.setattr("src.storage.configured", lambda: False)
    fake = FakeGeminiImageClient()
    png, jpeg = PNG_BYTES, b"\xff\xd8\xff\xe0j"
    assert nano_banana.generate_from_prompt("a watch macro",
                                            reference_image=[png, jpeg],
                                            db_path=tmp_db, client=fake)["ok"]
    parts = fake.calls[0]["contents"]
    assert len(parts) == 3                              # two images, then the text
    assert [p.inline_data.mime_type for p in parts[:2]] == ["image/png", "image/jpeg"]
    assert "THE ATTACHED 2 IMAGES are reference material" in parts[-1]
    assert "do NOT copy their framing".lower() in parts[-1].lower()


def test_one_reference_still_reads_as_singular(tmp_db, tmp_path, monkeypatch):
    from src import nano_banana

    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr(nano_banana, "RENDER_DIR", tmp_path / "nano")
    monkeypatch.setattr("src.storage.configured", lambda: False)
    fake = FakeGeminiImageClient()
    nano_banana.generate_from_prompt("x", reference_image=PNG_BYTES,
                                     db_path=tmp_db, client=fake)
    assert "THE ATTACHED IMAGE is reference material" in fake.calls[0]["contents"][-1]


def test_nano_retries_a_transient_overload(tmp_db, tmp_path, monkeypatch):
    """Measured live: an image model under load answers 503 UNAVAILABLE
    often enough that one attempt is not enough. Retried like every
    other Gemini call in the project -- but on the SAME model, since the
    text fallbacks in gemini_utils cannot draw."""
    from src import nano_banana

    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr(nano_banana, "RENDER_DIR", tmp_path / "nano")
    monkeypatch.setattr(nano_banana.time, "sleep", lambda s: None)
    monkeypatch.setattr("src.storage.configured", lambda: False)

    fake = FakeGeminiImageClient()
    good = fake.models.generate_content
    attempts = []

    def flaky(model, contents, config=None):
        attempts.append(model)
        if len(attempts) < 3:
            raise RuntimeError("503 UNAVAILABLE. high demand")
        return good(model=model, contents=contents, config=config)

    fake.models = SimpleNamespace(generate_content=flaky)
    result = nano_banana.generate_from_prompt("a bike", db_path=tmp_db, client=fake)
    assert result["ok"], result["error"]
    assert len(attempts) == 3
    assert set(attempts) == {nano_banana.MODEL}      # never a text fallback


def test_nano_does_not_retry_a_real_refusal(tmp_db, tmp_path, monkeypatch):
    """A refusal is an answer, not a blip -- retrying it would spend
    twice to be told no twice. Note the status: the output-shape
    degrade also keys on INVALID_ARGUMENT, so it has to be narrow
    enough to leave a bare content refusal alone."""
    from src import nano_banana

    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr(nano_banana, "RENDER_DIR", tmp_path / "nano")
    calls = []

    def refuse(model, contents, config=None):
        calls.append(model)
        raise RuntimeError("400 INVALID_ARGUMENT")

    fake = FakeGeminiImageClient()
    fake.models = SimpleNamespace(generate_content=refuse)
    result = nano_banana.generate_from_prompt("a bike", db_path=tmp_db, client=fake)
    assert not result["ok"] and len(calls) == 1


def test_image_for_runway_carries_an_upstream_keyframe(tmp_path, monkeypatch):
    """The Nano keyframe feeds Generate's image port, but /renders/ is
    local until R2 is configured -- Runway could never fetch it, so it
    must arrive as bytes or the anchor is silently lost."""
    renders = tmp_path / "data" / "renders" / "nano"
    renders.mkdir(parents=True)
    (renders / "wf-1.png").write_bytes(b"KEYFRAME")
    monkeypatch.setattr(imagery, "render_bytes",
                        lambda v: (tmp_path / "data" / "renders"
                                   / v[len("/renders/"):]).read_bytes())
    assert workflow_runner.image_for_runway("/renders/nano/wf-1.png") == b"KEYFRAME"
    # public URLs still pass straight through as prompt_image
    assert workflow_runner.image_for_runway(
        "https://cdn.test/a.jpg") == "https://cdn.test/a.jpg"


def test_render_bytes_refuses_a_path_that_escapes_the_render_dir():
    # pyproject.toml is tracked, so it definitely exists -- the guard is
    # what refuses it, not a missing file
    assert (Path(__file__).resolve().parent.parent / "pyproject.toml").is_file()
    assert imagery.render_bytes("/renders/../../pyproject.toml") is None


def test_generate_falls_back_to_the_shots_reference_like_the_other_nodes(
        tmp_db, monkeypatch):
    """One graph must not render two different clips depending on which
    button was pressed: the per-node Run sends properties.image_url, so
    Run all has to honour the same fallback enhance and nano already do."""
    seen = {}
    monkeypatch.setattr(runway, "has_key", lambda: True)
    monkeypatch.setattr(runway, "generate_from_prompt",
                        lambda prompt, *, reference_image=None, **kw:
                        seen.__setitem__("ref", reference_image) or
                        {"ok": True, "media_url": "/x.mp4", "generation_id": 1,
                         "path": "p", "error": None})
    graph = {
        "nodes": [node(1, "zpf/user_prompt", properties={"text": "night ride"}),
                  node(2, "zpf/generate",
                       inputs=[slot("prompt", "text", 1),
                               slot("image", "image", None)],   # unwired
                       properties={"image_url": "https://cdn.test/plate.jpg"})],
        "links": [[1, 1, 0, 2, 0, "text"]],
    }
    workflow_runner.execute_graph(graph, gemini_client=object(), db_path=tmp_db)
    assert seen["ref"] == "https://cdn.test/plate.jpg"


def test_an_unconfigured_runway_node_is_skipped_not_failed(tmp_db, monkeypatch):
    """A chain whose keyframe rendered must not report itself failed
    just because Runway was never set up. The spend gate is the
    opposite case and still fails loudly -- see
    test_api_run_generate_node_hits_the_spend_gate."""
    monkeypatch.delenv("RUNWAYML_API_SECRET", raising=False)
    graph = {
        "nodes": [node(1, "zpf/user_prompt", properties={"text": "night ride"}),
                  node(2, "zpf/generate", inputs=[slot("prompt", "text", 1),
                                                  slot("image", "image", None)])],
        "links": [[1, 1, 0, 2, 0, "text"]],
    }
    result = workflow_runner.execute_graph(graph, gemini_client=object(),
                                           db_path=tmp_db)
    assert result["nodes"]["2"]["status"] == "skipped"
    assert "RUNWAYML_API_SECRET" in result["nodes"]["2"]["error"]
    assert result["nodes"]["1"]["status"] == "done"       # the rest still ran


def test_api_exec_nano_needs_the_key(tmp_db, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    response = client.post("/api/workflows/exec/nano",
                           json={"prompt": "a bike"})
    assert response.status_code == 503


def test_api_exec_nano_runs_as_a_job(tmp_db, monkeypatch):
    from src import nano_banana

    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr(nano_banana, "generate_from_prompt",
                        lambda prompt, **kw: {"ok": True,
                                              "media_url": "/renders/nano/x.png",
                                              "generation_id": 1, "path": "x",
                                              "error": None})
    response = client.post("/api/workflows/exec/nano", json={"prompt": "a bike"})
    assert response.status_code == 200
    job = wait_for_job(response.json()["job_id"])
    assert job["status"] == "done" and job["output"] == "/renders/nano/x.png"


def test_api_exec_nano_sends_every_reference_the_canvas_posted(
        tmp_db, monkeypatch):
    """The canvas posts a node's whole reference list as `images`
    (workflows.js referenceUrls), but the body model declared only
    `image` -- so pydantic dropped the field without a word and a
    per-node Run on Nano Banana rendered with NO references at all.
    The face, the jacket and the bike arrived as a sentence and never
    as pixels (2026-08-28)."""
    from src import nano_banana

    seen = {}

    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr(nano_banana, "generate_from_prompt",
                        lambda prompt, **kw: seen.update(kw) or {
                            "ok": True, "media_url": "/renders/nano/x.png",
                            "generation_id": 1, "path": "x", "error": None})
    monkeypatch.setattr("src.imagery.image_bytes_for_gemini",
                        lambda url, resolve_photo=None: url.encode())

    response = client.post("/api/workflows/exec/nano", json={
        "prompt": "a bike",
        "images": ["/characters/michael/photo/a.jpg",
                   "/props/motorcycle/photo/b.jpg"]})
    assert response.status_code == 200
    assert wait_for_job(response.json()["job_id"])["status"] == "done"
    assert seen["reference_image"] == [b"/characters/michael/photo/a.jpg",
                                       b"/props/motorcycle/photo/b.jpg"]


def test_api_exec_generate_anchors_on_the_first_reference(tmp_db, monkeypatch):
    """Runway takes exactly one prompt_image, so of the list the canvas
    posts only the first is usable -- the same rule the graph runner's
    Generate branch follows."""
    seen = {}

    monkeypatch.setattr(runway, "has_key", lambda: True)
    monkeypatch.setattr(runway, "generate_from_prompt",
                        lambda prompt, **kw: seen.update(kw) or {
                            "ok": True, "media_url": "/renders/clip.mp4"})
    monkeypatch.setattr("app.workflow_runner.image_for_runway",
                        lambda url, resolve_photo=None: url)

    response = client.post("/api/workflows/exec/generate", json={
        "prompt": "a ride",
        "images": ["/characters/michael/photo/a.jpg",
                   "/props/motorcycle/photo/b.jpg"]})
    assert response.status_code == 200
    assert wait_for_job(response.json()["job_id"])["status"] == "done"
    assert seen["reference_image"] == "/characters/michael/photo/a.jpg"


def test_capabilities_report_nano(tmp_db, monkeypatch):
    from app import api as api_mod

    monkeypatch.setattr(api_mod.rag, "connect",
                        lambda db_url=None: (_ for _ in ()).throw(ConnectionError()))
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    assert client.get("/api/capabilities").json()["nano.generate"] is True
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    assert client.get("/api/capabilities").json()["nano.generate"] is False
