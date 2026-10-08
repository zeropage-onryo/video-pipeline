"""The board behind the Guide (src/guide_tools.py, 2026-09-18).

Read tools run inside a turn; write tools come back as a proposal and
run only on the click; the engine is never reachable; no URL gets
through. The bridge is exercised against the REAL in-process server,
the way tests/test_research_agent.py does -- no subprocess, no key.
"""
import json
import types as pytypes

import pytest
from fastapi.testclient import TestClient

from app import api, auth
from app.main import app
from src import creative_guide, entities, gemini_utils, guide_tools, mcp_server, preprod, scout

pytest.importorskip("mcp")


@pytest.fixture
def tmp_db(pg, monkeypatch):
    preprod.init(pg)
    entities.init(pg)
    scout.init(pg)
    monkeypatch.setenv("DATABASE_URL", pg)
    return pg


# ---------- the closed set ----------

def test_only_the_closed_set_is_published(tmp_db, monkeypatch):
    """With the engine gate ON in the environment (Mike's .env), the
    Guide's server still publishes no engine tool, and nothing outside
    READ_TOOLS + WRITE_TOOLS: not pick (spends cents), not archive,
    not capture -- Pipeline decides, this proposes."""
    monkeypatch.setenv(mcp_server.ENGINE_ENV, "1")
    from mcp import Client

    async def go():
        async with Client(guide_tools.build(dsn=tmp_db)) as client:
            return await guide_tools.specs(client), (await client.list_tools()).tools

    published, everything = guide_tools._sync(go())
    names = {t["name"] for t in published}
    assert names == set(guide_tools.TOOLS)
    assert {t.name for t in everything}.isdisjoint({"research", "generate"})
    assert {t["name"] for t in published if t["write"]} == set(guide_tools.WRITE_TOOLS)
    # names, descriptions and schemas come off the server, never restated
    board = next(t for t in published if t["name"] == "board")
    assert "brand" in board["input_schema"]["properties"]
    assert board["description"]


def test_engine_flag_is_explicit_not_inherited(tmp_db, monkeypatch):
    monkeypatch.setenv(mcp_server.ENGINE_ENV, "1")
    from mcp import Client

    async def names(server):
        async with Client(server) as client:
            return {t.name for t in (await client.list_tools()).tools}

    assert "research" in guide_tools._sync(names(mcp_server.build_server(dsn=tmp_db)))
    assert "research" not in guide_tools._sync(names(mcp_server.build_server(dsn=tmp_db, engine=False)))


# ---------- reads run, writes wait ----------

def test_read_tool_runs_and_write_tool_is_refused_from_the_model(tmp_db):
    specs, run_tool = guide_tools.session(dsn=tmp_db)
    assert {s["name"] for s in specs} == set(guide_tools.TOOLS)
    text = run_tool("stats", {})
    assert "pick" in text.lower()
    with pytest.raises(guide_tools.Refused):
        run_tool("add_spark", {"brand": "zeropage", "spark": "a dinner plate set for three"})


def test_run_banks_a_spark_only_when_called_directly(tmp_db):
    before = len(scout.list_findings(brand="zeropage", dsn=tmp_db))
    text = guide_tools.run("add_spark", {"brand": "zeropage",
                                         "spark": "a dinner plate set for three, one seat wet"},
                           dsn=tmp_db)
    assert len(scout.list_findings(brand="zeropage", dsn=tmp_db)) == before + 1
    assert "spark" in text.lower() or "id" in text.lower()


# ---------- no URL, no stranger ----------

@pytest.mark.parametrize("name,args", [
    ("reference", {"finding_id": 1, "image_url": "https://images.unsplash.com/x.jpg"}),
    ("reference", {"finding_id": 1, "candidate_id": "https://cdn.example/photo.jpg"}),
    ("add_spark", {"brand": "zeropage", "spark": "see www.example.com/moodboard"}),
    ("add_spark", {"brand": "zeropage", "spark": "x", "evidence": "shot.png"}),
    ("reference", {"finding_id": 1}),                       # no candidate at all
    ("pick", {"idea_id": 1}),                               # outside the set
    ("research", {"brand": "zeropage"}),                    # the engine
])
def test_check_args_refuses(name, args):
    with pytest.raises(guide_tools.Refused):
        guide_tools.check_args(name, args)


def test_check_args_passes_a_candidate_id():
    assert guide_tools.check_args("reference", {"finding_id": 3, "candidate_id": "c_9f"}) == {
        "finding_id": 3, "candidate_id": "c_9f"}


# ---------- the turn ----------

class _Resp:
    """The shape of a google-genai response this code reads: `.text`,
    `.function_calls`, `.candidates[0].content`."""
    def __init__(self, text=None, calls=()):
        self.text = text
        self.function_calls = [pytypes.SimpleNamespace(name=n, args=a) for n, a in calls]
        content = pytypes.SimpleNamespace(role="model", parts=[])
        self.candidates = [pytypes.SimpleNamespace(content=content)]


def _turn(monkeypatch, responses, run_tool):
    calls = []

    def generate(client, model, contents, **kwargs):
        calls.append(kwargs)
        r = responses.pop(0)
        return r if kwargs.get("raw") else r.text

    monkeypatch.setattr(gemini_utils, "generate_with_retry", generate)
    obj = lambda **props: {"type": "object", "properties": props}          # noqa: E731
    specs = [{"name": "board", "description": "the board", "write": False,
              "input_schema": obj(brand={"type": "string"})},
             {"name": "add_spark", "description": "bank", "write": True,
              "input_schema": obj(brand={"type": "string"}, spark={"type": "string"})}]
    reply = creative_guide.respond(
        creative_guide.Conversation(messages=[{"role": "user", "content": "what is on the board?"}]),
        client=object(), brand="zeropage", grounding={}, tools=specs, run_tool=run_tool)
    return reply, calls


def test_a_read_call_runs_and_the_answer_names_it(monkeypatch):
    ran = []

    def run_tool(name, args):
        ran.append((name, args))
        return json.dumps({"items": [{"id": 7, "title": "The Other Lane"}]})

    answer = json.dumps({"message": "One open concept: The Other Lane.", "choices": [], "brief": ""})
    reply, calls = _turn(monkeypatch, [_Resp(calls=[("board", {"brand": "zeropage"})]), _Resp(text=answer)], run_tool)
    assert ran == [("board", {"brand": "zeropage"})]
    assert reply["message"].startswith("One open concept")
    assert reply["tool_runs"] == [{"tool": "board", "args": {"brand": "zeropage"}, "ok": True}]
    assert reply["proposal"] is None
    assert calls[0]["raw"] is True and calls[0]["config"].tools   # declarations were sent


def test_a_write_call_becomes_a_proposal_and_does_not_run(monkeypatch):
    def run_tool(name, args):
        pytest.fail(f"{name} ran from the model's say-so")

    proposal = _Resp(calls=[("add_spark", {"brand": "zeropage", "spark": "a wet seat"})])
    reply, calls = _turn(monkeypatch, [proposal], run_tool)
    assert reply["proposal"] == {"tool": "add_spark", "args": {"brand": "zeropage", "spark": "a wet seat"},
                                 "label": guide_tools.WRITE_LABELS["add_spark"]}
    assert "Confirm" in reply["message"]
    assert len(calls) == 1


def test_a_proposal_with_a_url_is_refused_not_carried(monkeypatch):
    with pytest.raises(guide_tools.Refused):
        _turn(monkeypatch, [_Resp(calls=[("add_spark", {"brand": "zeropage", "spark": "https://x.y/z.jpg"})])],
              lambda n, a: "")


def test_unparseable_answer_gets_one_schema_call(monkeypatch):
    answer = json.dumps({"message": "Nothing open.", "choices": [], "brief": ""})
    reply, calls = _turn(monkeypatch, [_Resp(text="Sure! Nothing is open right now."), _Resp(text=answer)],
                         lambda n, a: "{}")
    assert reply["message"] == "Nothing open."
    assert len(calls) == 2 and calls[1]["config"].tools is None
    assert calls[1]["config"].response_json_schema


def test_tool_budget_ends_the_loop(monkeypatch):
    n = creative_guide.MAX_TOOL_CALLS
    responses = [_Resp(calls=[("board", {})]) for _ in range(n + 1)]
    responses.append(_Resp(text=json.dumps({"message": "done", "choices": [], "brief": ""})))
    reply, calls = _turn(monkeypatch, responses, lambda name, args: "{}")
    assert reply["message"] == "done"
    assert sum(1 for r in reply["tool_runs"] if r["ok"]) == n


def test_without_tools_the_turn_is_unchanged(monkeypatch):
    seen = {}

    def generate(client, model, contents, **kwargs):
        seen.update(kwargs)
        return json.dumps({"message": "Who is waiting?", "choices": [], "brief": ""})

    monkeypatch.setattr(gemini_utils, "generate_with_retry", generate)
    reply = creative_guide.respond(creative_guide.Conversation(messages=[{"role": "user", "content": "x"}]),
                                   client=object(), brand="zeropage", grounding={})
    assert reply["proposal"] is None and reply["tool_runs"] == []
    assert "raw" not in seen and seen["config"].tools is None
    assert "add_spark" not in seen["config"].system_instruction


# ---------- the click ----------

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(auth, "current_user", lambda request: {"id": "guide-user"})
    monkeypatch.setattr(auth, "current_account", lambda request: {"slug": "zeropage"})
    app.dependency_overrides[auth.current_account_id] = lambda: 42
    yield TestClient(app, headers={"X-ZPF-Model-Connection": "1"})
    app.dependency_overrides.pop(auth.current_account_id, None)


def test_act_needs_the_header(monkeypatch):
    monkeypatch.setattr(auth, "current_user", lambda request: {"id": "u"})
    app.dependency_overrides[auth.current_account_id] = lambda: 42
    try:
        r = TestClient(app).post("/api/creative-guide/act", json={"tool": "add_spark", "args": {}})
        assert r.status_code == 403
    finally:
        app.dependency_overrides.pop(auth.current_account_id, None)


@pytest.mark.parametrize("body", [
    {"tool": "pick", "args": {"idea_id": 1}},
    {"tool": "board", "args": {}},
    {"tool": "research", "args": {"brand": "zeropage"}},
    {"tool": "", "args": {}},
])
def test_act_refuses_anything_but_a_write_tool(client, monkeypatch, body):
    monkeypatch.setattr(guide_tools, "run", lambda *a, **k: pytest.fail("ran"))
    assert client.post("/api/creative-guide/act", json=body).status_code == 400


def test_act_refuses_a_url_before_running(client, monkeypatch):
    monkeypatch.setattr(guide_tools, "run", guide_tools.run)   # the real one, up to check_args
    r = client.post("/api/creative-guide/act",
                    json={"tool": "reference", "args": {"finding_id": 1, "image_url": "https://a/b.jpg"}})
    assert r.status_code == 400 and r.json()["error"]["code"] == "refused"


def test_act_runs_the_write_as_the_signed_in_account(client, monkeypatch):
    seen = {}

    def run(tool, args, *, dsn=None, account_id=None):
        seen.update(tool=tool, args=args, account_id=account_id)
        return "banked spark 12"

    monkeypatch.setattr(guide_tools, "run", run)
    r = client.post("/api/creative-guide/act",
                    json={"tool": "add_spark", "args": {"brand": "zeropage", "spark": "a wet seat"}})
    assert r.status_code == 200 and r.json() == {"ok": True, "tool": "add_spark", "result": "banked spark 12"}
    assert seen == {"tool": "add_spark", "args": {"brand": "zeropage", "spark": "a wet seat"}, "account_id": 42}


def test_turn_degrades_without_tools(monkeypatch):
    monkeypatch.setattr(guide_tools, "available", lambda: False)
    assert api._guide_tools(42) == (None, None)
    monkeypatch.setattr(guide_tools, "available", lambda: True)
    monkeypatch.setattr(guide_tools, "session", lambda **k: (_ for _ in ()).throw(RuntimeError("no db")))
    assert api._guide_tools(42) == (None, None)


# --- the brain makes (2026-10-04) --------------------------------------------
# The composer has no Guide toggle: every send is a Guide turn, and the
# model decides between talking and making through make_image /
# make_video. Those are proposals the STUDIO runs; this module never does.

def test_make_tools_are_published_only_to_a_maker_turn(monkeypatch):
    monkeypatch.setattr(guide_tools, "available", lambda: False)
    specs, _ = guide_tools.session(local=True)
    assert {s["name"] for s in specs}.isdisjoint(guide_tools.MAKE_TOOLS)
    specs, run_tool = guide_tools.session(local=True, maker=True)
    names = {s["name"] for s in specs}
    assert set(guide_tools.MAKE_TOOLS) <= names
    assert all(s["write"] for s in specs if s["name"] in guide_tools.MAKE_TOOLS)
    # a make is a write: the model's own call is refused mid-turn like any write
    with pytest.raises(guide_tools.Refused):
        run_tool("make_image", {"prompt": "a can"})


def test_the_pill_is_handed_the_still_and_never_the_scene(monkeypatch):
    """The assistant pill (2026-10-08) draws a still behind the same Approve
    card the composer shows; a scene stays the composer's."""
    monkeypatch.setattr(guide_tools, "available", lambda: False)
    specs, _ = guide_tools.session(local=True, maker=True, makes=("make_image",))
    names = {s["name"] for s in specs}
    assert "make_image" in names and "make_video" not in names
    from src import creative_guide
    assert creative_guide.MAKES_FOR["still"] == ("make_image",)
    assert creative_guide.MAKES_FOR["image"] is None and creative_guide.MAKES_FOR["video"] is None
    assert "make_image" in creative_guide.OUTPUT_NOTES["still"]


def test_a_make_call_ends_the_turn_as_a_proposal_with_a_clean_prompt(monkeypatch):
    calls = []
    proposal = _Resp(calls=[("make_image", {"prompt": "  a wet   steel counter ", "aspect": "4:5",
                                             "seconds": 9})])
    reply, _ = _turn(monkeypatch, [proposal], lambda n, a: calls.append(n))
    assert calls == []
    assert reply["proposal"] == {"tool": "make_image", "args": {"prompt": "a wet steel counter",
                                                               "aspect": "4:5"},
                                 "label": guide_tools.WRITE_LABELS["make_image"]}
    # the line above the composer's Approve is what will be drawn, never the
    # stock "I can ...: {json}. Confirm on the card" a board write carries
    assert reply["message"] == "a wet steel counter"


def test_a_board_write_keeps_its_confirm_line(monkeypatch):
    proposal = _Resp(calls=[("add_spark", {"brand": "zeropage", "spark": "a wet seat"})])
    reply, _ = _turn(monkeypatch, [proposal], lambda n, a: None)
    assert reply["message"].startswith("I can bank this spark") and "Confirm" in reply["message"]


@pytest.mark.parametrize("args, clean", [
    ({"prompt": "a scene", "seconds": 90, "shots": 0}, {"prompt": "a scene", "seconds": 30, "shots": 1}),
    ({"prompt": "a scene", "seconds": "9", "shots": True}, {"prompt": "a scene"}),
])
def test_make_video_args_are_clamped_to_the_scenes_own_bounds(args, clean):
    assert guide_tools.check_args("make_video", args) == clean


@pytest.mark.parametrize("name, args", [
    ("make_image", {}),
    ("make_video", {"prompt": "   "}),
    ("make_image", {"prompt": "draw https://x.y/z.jpg"}),
])
def test_a_make_without_a_prompt_or_with_a_url_is_refused(name, args):
    with pytest.raises(guide_tools.Refused):
        guide_tools.check_args(name, args)


def test_run_never_makes(tmp_db):
    with pytest.raises(guide_tools.Refused, match="studio"):
        guide_tools.run("make_image", {"prompt": "a can"}, dsn=tmp_db)


def test_act_refuses_a_make_tool(client, monkeypatch):
    from src import assistant_brain
    monkeypatch.setattr(assistant_brain, "run_local", lambda *a, **k: pytest.fail("ran"))
    res = client.post("/api/creative-guide/act", json={"tool": "make_video", "args": {"prompt": "x"}})
    assert res.status_code == 400
    assert "send" in res.json()["error"]["message"]
