"""
Every route that spends model text asks Create's gate (2026-10-08, 1a of
docs/tasks/task-spend-holes-and-credits.md).

Each stays free per click (Mike's 2026-09-29 call); what changed is that an
account with NO plan and NO credit balance is refused -- 402
`subscribe_or_top_up`, before any job starts and before any model call --
where it used to run on the studio's key for nothing. One test per door,
plus the twin that matters: the same account with credit gets through.

`jobs.start` is replaced by a recorder, so a refused route that started a
job anyway fails here instead of quietly spending; the conftest network
guard is the second net under any inline model call.
"""
import json

import pytest
from fastapi.testclient import TestClient

from src import accounts, db, ledger, preprod, projects, workflows

GUARD = {"X-ZPF-Model-Connection": "1"}


@pytest.fixture
def studio(pg, monkeypatch, tmp_path):
    from app import api
    monkeypatch.setenv("DATABASE_URL", pg)
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    preprod.init(pg)
    projects.init(pg)
    workflows.init(pg)
    accounts.seed("mike@example.com", dsn=pg)
    ledger.init(pg)
    with db.connect(pg) as conn:
        account_id = int(conn.execute(
            "SELECT id FROM accounts WHERE slug = 'zeropage'").fetchone()["id"])
    # an element save that slipped past the gate must not write into the
    # real asset folders
    for name in ("LOCATIONS_DIR", "CHARACTERS_DIR", "PROPS_DIR"):
        monkeypatch.setattr(api, name, tmp_path / name.lower())
    scene = preprod.save_concept(
        {"title": "Garage", "shots": [{"n": 1, "type": "BROLL", "source": "AI",
                                       "tool": "RUNWAY", "prompt": "a rider suits up"}]},
        brand="zeropage", dsn=pg, account_id=account_id)
    idea = preprod.save_concept({"title": "An idea", "shots": []}, brand="zeropage",
                                dsn=pg, account_id=account_id)
    flow = workflows.create_workflow("flow", {"nodes": [{"id": 1, "type": "zpf/text"}]},
                                     dsn=pg, account_id=account_id)
    return {"dsn": pg, "account_id": account_id, "scene": scene, "idea": idea,
            "flow": flow}


@pytest.fixture
def started(monkeypatch):
    from app import jobs
    calls = []

    def start(kind, label, fn, **kw):
        calls.append(kind)
        return {"id": len(calls)}

    monkeypatch.setattr(jobs, "start", start)
    return calls


@pytest.fixture
def client(studio, started, monkeypatch):
    from app import auth
    from app.main import app
    monkeypatch.setattr(auth, "current_user",
                        lambda request: {"id": 1, "email": "t@e.com", "display_name": "T"})
    monkeypatch.setattr(auth, "current_account",
                        lambda request: {"id": studio["account_id"], "slug": "zeropage"})
    app.dependency_overrides[auth.current_account_id] = lambda: studio["account_id"]
    yield TestClient(app, headers=GUARD)
    app.dependency_overrides[auth.current_account_id] = lambda: None


def _fund(studio):
    ledger.grant(studio["account_id"], 1000, "purchase", dsn=studio["dsn"])


def _refused(res):
    assert res.status_code == 402, res.text
    assert res.json()["error"]["code"] == "subscribe_or_top_up"


def _conversation():
    return json.dumps({"messages": [{"role": "user", "content": "a cold garage at dawn"}]})


# Each door as (name, how to call it). The job-starting ones: refused with
# no job, and with credit they start exactly one.
JOB_DOORS = {
    "guide": lambda c, s: c.post("/api/creative-guide",
                                 data={"conversation": _conversation()}),
    "backfill": lambda c, s: c.post("/api/assets/backfill", json={"describe": False}),
    "scout": lambda c, s: c.post("/api/scout/run", json={"brand": "zeropage"}),
    "direct": lambda c, s: c.post(f"/api/concepts/{s['scene']}/direct",
                                  json={"note": "make it colder"}),
    "refine": lambda c, s: c.post(f"/api/concepts/{s['scene']}/shots/1/refine"),
    "write_scene": lambda c, s: c.post(f"/api/concepts/{s['idea']}/approve"),
    "enhance": lambda c, s: c.post("/api/workflows/exec/enhance", json={"user": "a rider"}),
    "run_all": lambda c, s: c.post(f"/api/workflows/{s['flow']}/run"),
    "cut_index": lambda c, s: c.post("/api/cut/index", json={}),
}


@pytest.mark.parametrize("door", sorted(JOB_DOORS))
def test_no_plan_and_no_balance_is_refused_before_any_job(client, studio, started, door):
    _refused(JOB_DOORS[door](client, studio))
    assert started == []


@pytest.mark.parametrize("door", sorted(set(JOB_DOORS) - {"cut_index"}))
def test_the_same_door_with_credit_starts_its_job(client, studio, started, door):
    _fund(studio)
    res = JOB_DOORS[door](client, studio)
    assert res.status_code == 200, res.text
    assert len(started) == 1


def test_a_plan_with_no_balance_is_enough(client, studio, started):
    accounts.set_plan(studio["account_id"], "starter", dsn=studio["dsn"])
    res = JOB_DOORS["guide"](client, studio)
    assert res.status_code == 200, res.text
    assert started == ["guide"]


def test_the_owner_is_never_refused(client, studio, started):
    accounts.set_credit_exempt("zeropage", True, dsn=studio["dsn"])
    assert JOB_DOORS["guide"](client, studio).status_code == 200


# --- the inline doors: refused before the model call they make in-request ----

def test_the_brief_draft_is_refused_before_its_model_call(client, studio, monkeypatch):
    calls = []
    monkeypatch.setattr(projects, "draft_brief", lambda *a, **k: calls.append(1) or "brief")
    body = {"title": "Ad", "answers": {projects.QUESTIONS[0][0]: "a cold garage"}}
    _refused(client.post("/api/projects/draft-brief", json=body))
    assert calls == []
    _fund(studio)
    assert client.post("/api/projects/draft-brief", json=body).json() == {"brief": "brief"}


@pytest.mark.parametrize("kind", ["locations", "characters", "props"])
def test_an_element_save_is_refused_before_a_photo_is_written(client, studio, kind,
                                                              monkeypatch, tmp_path):
    from app import api
    described = []
    monkeypatch.setattr(api, "describe_entity_photos",
                        lambda *a, **k: described.append(1) or {"ok": False, "description": None,
                                                                "error": "stub"})
    res = client.post(f"/api/assets/{kind}", data={"name": "Old Garage", "sheet": "0"},
                      files={"photos": ("a.jpg", b"\xff\xd8\xff", "image/jpeg")})
    _refused(res)
    assert described == []
    assert not any(tmp_path.rglob("a.jpg"))               # nothing written


def test_the_ground_node_is_refused_before_its_embedding(client, studio, monkeypatch):
    from src import shootgen
    calls = []
    monkeypatch.setattr(shootgen, "reference_block", lambda **k: calls.append(1) or "refs")
    _refused(client.post("/api/workflows/exec/ground", json={"spark": "a garage"}))
    assert calls == []
    _fund(studio)
    assert client.post("/api/workflows/exec/ground",
                       json={"spark": "a garage"}).json() == {"references": "refs"}


def test_the_evals_run_is_refused(client, studio, started, monkeypatch):
    from app import api
    monkeypatch.setattr(api.evalstore, "list_golden",
                        lambda *a, **k: [{"query": "q", "relevant": ["r"]}])
    monkeypatch.setattr(api, "_rag_reachable", lambda: True)
    _refused(client.post("/api/evals/run", json={}))
    assert started == []


# --- the cut: the agent and the project's index ---------------------------------

@pytest.fixture
def a_cut(monkeypatch):
    from app import cut_routes
    project = {"id": "p1", "title": "A cut", "timeline_key": "cut:p1"}
    monkeypatch.setattr(cut_routes, "_project_or_404", lambda pid, aid: (project, None))
    monkeypatch.setattr(cut_routes, "_head_or_409",
                        lambda p, aid: ({"id": 1, "doc": {"tracks": []}}, None))
    monkeypatch.setattr(cut_routes.cut_doc, "handles", lambda doc: ["gen:1"])
    monkeypatch.setattr(cut_routes.cut_moments, "indexed", lambda h, account_id=None: None)
    monkeypatch.setattr(cut_routes.cut_sources, "ffmpeg_bin", lambda: "/usr/bin/ffmpeg")
    return project


def test_the_cut_agent_is_refused_before_its_turn(client, studio, started, a_cut):
    _refused(client.post("/api/cut/projects/p1/agent", json={"message": "tighten it"}))
    assert started == []
    _fund(studio)
    assert client.post("/api/cut/projects/p1/agent",
                       json={"message": "tighten it"}).status_code == 200
    assert started == ["cut_agent"]


def test_the_cut_projects_index_is_refused(client, studio, started, a_cut):
    _refused(client.post("/api/cut/projects/p1/index"))
    assert started == []
    _fund(studio)
    assert client.post("/api/cut/projects/p1/index").status_code == 200
    assert len(started) == 1
