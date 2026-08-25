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
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import jobs, workflow_runner
from app.main import app
from src import db, generative, runway, workflows

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
                                      brand="antihero", path=tmp_db)

    listed = workflows.list_workflows(path=tmp_db)
    assert [w["name"] for w in listed] == ["night ride"]
    assert listed[0]["node_count"] == 1
    assert "graph" not in listed[0]          # the list stays light

    loaded = workflows.get_workflow(wf_id, path=tmp_db)
    assert loaded["graph"] == graph

    assert workflows.update_workflow(wf_id, name="garage ritual", path=tmp_db)
    assert workflows.get_workflow(wf_id, path=tmp_db)["name"] == "garage ritual"
    # graph untouched by a name-only update
    assert workflows.get_workflow(wf_id, path=tmp_db)["graph"] == graph

    assert workflows.delete_workflow(wf_id, path=tmp_db)
    assert workflows.get_workflow(wf_id, path=tmp_db) is None
    assert not workflows.delete_workflow(wf_id, path=tmp_db)


def test_workflow_list_scopes_by_brand(tmp_db):
    workflows.create_workflow("a", {}, brand="antihero", path=tmp_db)
    workflows.create_workflow("z", {}, brand="zeropage", path=tmp_db)
    assert [w["name"] for w in
            workflows.list_workflows(brand="zeropage", path=tmp_db)] == ["z"]
    assert len(workflows.list_workflows(path=tmp_db)) == 2


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
    monkeypatch.setattr(runway, "generations_today", lambda db_path=None: runway.DAILY_CAP)
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

def test_ui_shell_has_workflows_and_no_evals(tmp_db):
    html = client.get("/ui").text
    assert 'data-view="workflows"' in html
    assert 'data-view="evals"' not in html
    assert "vendor/litegraph.js" in html


def test_evals_dev_page_renders_open(tmp_db, monkeypatch):
    """The dev page is a legacy page: no session required for the shell
    itself (its API calls surface the 401 with a pointer to /signin)."""
    from app import auth
    monkeypatch.setattr(auth, "current_user", lambda request: None)
    res = client.get("/evals")
    assert res.status_code == 200
    assert "evals_dev.js" in res.text
    assert "GOLDEN SET" in res.text


# --- the seeded default template --------------------------------------------

def test_seed_default_plants_the_template_once(tmp_db):
    wf_id = workflows.seed_default(path=tmp_db)
    assert wf_id is not None
    assert workflows.seed_default(path=tmp_db) is None   # idempotent

    template = workflows.get_workflow(wf_id, path=tmp_db)
    assert template["name"] == "Prompt enhancement"
    assert template["brand"] is None                     # shared across brands
    types = [n["type"] for n in template["graph"]["nodes"]]
    assert types == ["zpf/system_prompt", "zpf/user_prompt",
                     "zpf/enhance", "zpf/nano_banana"]
    # pre-wired: system+user feed enhance, enhance feeds the image node
    assert [(link[1], link[3]) for link in template["graph"]["links"]] \
        == [(1, 3), (2, 3), (3, 4)]
    # the System Prompt ships with the prompts/ text, not empty
    assert "enhance" in template["graph"]["nodes"][0]["properties"]["text"].lower()


def test_seed_default_respects_an_intentionally_emptied_slate(tmp_db):
    wf_id = workflows.seed_default(path=tmp_db)
    workflows.create_workflow("mine", {}, brand="antihero", path=tmp_db)
    workflows.delete_workflow(wf_id, path=tmp_db)
    # other workflows exist -> the deleted template stays deleted
    assert workflows.seed_default(path=tmp_db) is None


def test_brandless_template_shows_up_under_every_brand(tmp_db):
    workflows.seed_default(path=tmp_db)
    workflows.create_workflow("z", {}, brand="zeropage", path=tmp_db)
    for brand in ("antihero", "zeropage"):
        names = [w["name"] for w in workflows.list_workflows(brand=brand, path=tmp_db)]
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

        def generate_content(model, contents):
            self.calls.append({"model": model, "contents": contents})
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
    fake.models = SimpleNamespace(generate_content=lambda model, contents:
                                  SimpleNamespace(candidates=[], text="no can do"))
    result = nano_banana.generate_from_prompt("a bike", db_path=tmp_db, client=fake)
    assert not result["ok"] and "no image" in result["error"]


# --- the nano node in the executor and the API ------------------------------

def test_image_bytes_for_gemini_resolves_renders_and_data_uris(tmp_path):
    import base64
    assert workflow_runner.image_bytes_for_gemini(
        "data:image/png;base64," + base64.b64encode(b"PIX").decode()) == b"PIX"
    photo = tmp_path / "p.jpg"
    photo.write_bytes(b"JPEGBYTES")
    assert workflow_runner.image_bytes_for_gemini(
        "/assets/antihero/p.jpg", resolve_photo=lambda v: photo) == b"JPEGBYTES"
    assert workflow_runner.image_bytes_for_gemini("https://x/y.png") is None


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


def test_capabilities_report_nano(tmp_db, monkeypatch):
    from app import api as api_mod

    monkeypatch.setattr(api_mod.rag, "connect",
                        lambda db_url=None: (_ for _ in ()).throw(ConnectionError()))
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    assert client.get("/api/capabilities").json()["nano.generate"] is True
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    assert client.get("/api/capabilities").json()["nano.generate"] is False
