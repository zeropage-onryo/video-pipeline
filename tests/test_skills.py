"""The skill shelf (src/skills.py, 2026-10-10).

A skill is a recipe the brain reads before a kind of work. These hold the
three things that make that safe: the shelf is exactly its files, a recipe
names only tools that exist and never a URL, and a turn with no skill in it
is the turn it was.
"""
import json
import re
import time
import types as pytypes

import pytest
from fastapi.testclient import TestClient

from app import api, auth
from app.main import app
from src import assistant_brain, charge, creative_guide, gemini_utils, guide_tools, scene_chain, skills

SHELF = ["character-sheet", "single-shot", "multi-shot", "product-still", "mood-board"]

# every tool a Guide turn can be handed, by any door
KNOWN_TOOLS = (set(guide_tools.TOOLS) | set(guide_tools.LOCAL_TOOLS)
               | set(guide_tools.MAKE_TOOLS) | set(guide_tools.PROJECT_TOOLS))
# a word that is shaped like one of them: make_x, find_x, keep_x, load_x ...
_TOOLISH = re.compile(r"\b(?:make|find|keep|load|search|create|save|add|apply|generate)_[a-z_]+\b")


# ---------- the shelf ----------

def test_the_shelf_is_its_files_in_order():
    shelf = skills.catalogue()
    assert [s["name"] for s in shelf] == SHELF == skills.names()
    for s in shelf:
        assert set(s) == {"name", "title", "summary", "output"}     # never the recipe
        assert s["title"] and s["summary"] and s["output"] in skills.OUTPUTS


@pytest.mark.parametrize("name", SHELF)
def test_a_recipe_names_only_real_tools_and_no_address(name):
    """A recipe that tells the brain to call a tool it is not handed, or
    carries an address, teaches it to do the two things the bridge refuses."""
    skill = skills.get(name)
    body = skill["body"]
    assert len(body) < skills.MAX_BODY                      # whole, not cut off
    assert not guide_tools._URL.search(body)
    assert set(_TOOLISH.findall(body)) <= KNOWN_TOOLS
    # the recipe is the studio's words: nothing left to fill in
    assert "{" not in body and "TODO" not in body


def test_a_name_is_cleaned_against_the_shelf():
    assert skills.clean_name(" Mood-Board ") == "mood-board"
    assert skills.clean_name("nope") == "" and skills.clean_name(None) == ""
    assert skills.get("../creative_guide") is None
    assert skills.title_of("multi-shot") == "Multi-shot scene"


@pytest.mark.parametrize("text", [
    "no header at all",
    "---\nname: other\ntitle: T\nfor: f\n---\nbody",          # not the file's own name
    "---\nname: thing\nfor: f\n---\nbody",                     # no title
    "---\nname: thing\ntitle: T\nfor: f\n---\n",               # nothing to follow
])
def test_a_file_that_is_not_a_skill_is_not_on_the_shelf(tmp_path, monkeypatch, text):
    (tmp_path / "thing.md").write_text(text)
    monkeypatch.setattr(skills, "SKILLS_DIR", tmp_path)
    assert skills.catalogue() == []


def test_an_empty_shelf_changes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(skills, "SKILLS_DIR", tmp_path / "missing")
    assert skills.catalogue() == [] and skills.index_block() == "" and skills.load_spec() is None
    monkeypatch.setattr(guide_tools, "available", lambda: False)
    specs, _ = guide_tools.session(local=True)
    assert skills.TOOL not in {s["name"] for s in specs}
    assert creative_guide.instructions("zeropage", with_tools=True, with_skills=True) == \
        creative_guide.instructions("zeropage", with_tools=True)


# ---------- the tool ----------

def test_load_skill_is_a_read_published_with_the_assistants_own_tools(monkeypatch):
    monkeypatch.setattr(guide_tools, "available", lambda: False)
    specs, run_tool = guide_tools.session(local=True)
    spec = next(s for s in specs if s["name"] == skills.TOOL)
    assert spec["write"] is False and not guide_tools.is_write(skills.TOOL)
    assert spec["input_schema"]["properties"]["name"]["enum"] == SHELF
    recipe = run_tool(skills.TOOL, {"name": "multi-shot"})
    assert recipe.startswith("SKILL: Multi-shot scene") and "make_video" in recipe
    assert "does not override" in recipe                       # guidance, not permission
    # the model's own tools are the only place it lives: not on the board's set
    assert skills.TOOL not in guide_tools.TOOLS


def test_an_unknown_skill_is_refused_with_the_shelf():
    with pytest.raises(guide_tools.Refused, match="mood-board"):
        guide_tools.check_args(skills.TOOL, {"name": "storyboard"})
    assert guide_tools.check_args(skills.TOOL, {"name": "Single-Shot", "extra": 1}) == \
        {"name": "single-shot"}
    assert "the shelf is" in skills.load_for_model("storyboard")


def test_the_status_line_names_the_skill():
    assert guide_tools.step_note(skills.TOOL, {"name": "character-sheet"}) == \
        "read the Character sheet skill"
    assert guide_tools.step_note("board", {}) == "looked at board"
    assert guide_tools.step_note(skills.TOOL, {"name": "nope"}) == "looked at load_skill"
    assert assistant_brain.run_local(skills.TOOL, {"name": "mood-board"}).startswith("SKILL: Mood board")


# ---------- the turn ----------

class _Resp:
    def __init__(self, text=None, calls=()):
        self.text = text
        self.function_calls = [pytypes.SimpleNamespace(name=n, args=a) for n, a in calls]
        self.candidates = [pytypes.SimpleNamespace(
            content=pytypes.SimpleNamespace(role="model", parts=[]))]


_ANSWER = json.dumps({"message": "Here is the cut.", "choices": [], "brief": ""})


def _respond(monkeypatch, responses, *, tools, run_tool=None, skill=None, on_retry=None):
    seen = []

    def generate(client, model, contents, **kwargs):
        seen.append({"contents": contents, **kwargs})
        r = responses.pop(0)
        return r if kwargs.get("raw") else r.text

    monkeypatch.setattr(gemini_utils, "generate_with_retry", generate)
    reply = creative_guide.respond(
        creative_guide.Conversation(messages=[{"role": "user", "content": "cut it into 3 shots"}]),
        client=object(), brand="zeropage", grounding={}, tools=tools, run_tool=run_tool,
        skill=skill, on_retry=on_retry)
    return reply, seen


def _last_text(call) -> str:
    return "\n".join(p.text for p in call["contents"][-1].parts if getattr(p, "text", None))


def test_the_index_rides_only_where_the_tool_is_offered(monkeypatch):
    load = skills.load_spec()
    _, seen = _respond(monkeypatch, [_Resp(text=_ANSWER)], tools=[load], run_tool=lambda n, a: "")
    system = seen[0]["config"].system_instruction
    assert "The skills on the shelf:" in system and "- multi-shot: " in system
    assert "{skills}" not in system
    # a turn handed tools but not this one, and a turn with none: unchanged
    board = {"name": "board", "description": "the board", "write": False,
             "input_schema": {"type": "object", "properties": {}}}
    _, seen = _respond(monkeypatch, [_Resp(text=_ANSWER)], tools=[board], run_tool=lambda n, a: "")
    assert "skills on the shelf" not in seen[0]["config"].system_instruction
    reply, seen = _respond(monkeypatch, [_Resp(text=_ANSWER)], tools=None)
    assert "skills on the shelf" not in seen[0]["config"].system_instruction
    assert reply["tool_runs"] == [] and "PICKED" not in _last_text(seen[0])


def test_the_model_loads_a_skill_and_the_thread_can_say_which(monkeypatch):
    monkeypatch.setattr(guide_tools, "available", lambda: False)
    specs, run_tool = guide_tools.session(local=True)
    notes = []
    reply, seen = _respond(
        monkeypatch, [_Resp(calls=[(skills.TOOL, {"name": "multi-shot"})]), _Resp(text=_ANSWER)],
        tools=specs, run_tool=run_tool, on_retry=notes.append)
    assert reply["tool_runs"] == [{"tool": skills.TOOL, "args": {"name": "multi-shot"}, "ok": True}]
    assert reply["message"] == "Here is the cut." and reply["proposal"] is None
    assert "read the Multi-shot scene skill" in notes
    # the recipe went back to the model as the tool's result
    sent = seen[1]["contents"][-1].parts[0].function_response.response["result"]
    assert sent.startswith("SKILL: Multi-shot scene")


def test_a_picked_skill_is_already_loaded_and_named_once(monkeypatch):
    reply, seen = _respond(monkeypatch, [_Resp(text=_ANSWER)], tools=None, skill="product-still")
    said = _last_text(seen[0])
    assert "PICKED the Product still skill" in said and "Write the prompt" in said
    assert reply["tool_runs"] == [{"tool": skills.TOOL, "args": {"name": "product-still"}, "ok": True}]
    # the model loading the same one anyway is one use, not two
    monkeypatch.setattr(guide_tools, "available", lambda: False)
    specs, run_tool = guide_tools.session(local=True)
    reply, _ = _respond(
        monkeypatch, [_Resp(calls=[(skills.TOOL, {"name": "product-still"})]), _Resp(text=_ANSWER)],
        tools=specs, run_tool=run_tool, skill="product-still")
    assert [r["args"]["name"] for r in reply["tool_runs"]] == ["product-still"]
    # a name that is not on the shelf is no pick at all
    reply, seen = _respond(monkeypatch, [_Resp(text=_ANSWER)], tools=None, skill="storyboard")
    assert reply["tool_runs"] == [] and "PICKED" not in _last_text(seen[0])


def test_a_picked_skill_still_ends_on_the_make_as_a_proposal(monkeypatch):
    """The skill tells the brain HOW; the make still waits for the person."""
    monkeypatch.setattr(guide_tools, "available", lambda: False)
    specs, run_tool = guide_tools.session(local=True, maker=True)
    reply, _ = _respond(
        monkeypatch, [_Resp(calls=[("make_image", {"prompt": "the exact can on wet steel"})])],
        tools=specs, run_tool=run_tool, skill="product-still")
    assert reply["proposal"]["tool"] == "make_image"
    assert reply["tool_runs"] == [{"tool": skills.TOOL, "args": {"name": "product-still"}, "ok": True}]


def test_a_personal_plan_gets_the_picked_skill_in_its_prompt(monkeypatch):
    from src import personal_models
    seen = {}

    def claude(scope, prompt, system, schema, image_refs, model):
        seen.update(prompt=json.loads(prompt), system=system)
        return json.dumps({"message": "ok", "choices": [], "brief": ""})

    monkeypatch.setattr(personal_models, "claude_generate", claude)
    reply = creative_guide.respond_personal(
        creative_guide.Conversation(messages=[{"role": "user", "content": "a board for the bar"}]),
        provider="claude", scope="s", model=None, brand="zeropage", grounding={},
        skill="mood-board")
    assert "PICKED the Mood board skill" in seen["prompt"]["picked_skill"]
    assert "skills on the shelf" not in seen["system"]          # no tool, so no index
    assert reply["tool_runs"][0]["args"] == {"name": "mood-board"}


# ---------- the routes ----------

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(auth, "current_user", lambda request: {"id": "guide-user"})
    monkeypatch.setattr(auth, "current_account", lambda request: {"slug": "zeropage"})
    monkeypatch.setattr(charge, "create_refusal", lambda *a, **k: None)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    app.dependency_overrides[auth.current_account_id] = lambda: 42
    yield TestClient(app, headers={"X-ZPF-Model-Connection": "1"})
    app.dependency_overrides.pop(auth.current_account_id, None)


def test_the_menu_is_a_projection_of_the_shelf(client):
    body = client.get("/api/skills").json()
    assert body == {"items": skills.catalogue()}
    assert "body" not in body["items"][0]


@pytest.mark.parametrize("sent, expect", [("multi-shot", "multi-shot"), ("MULTI-SHOT", "multi-shot"),
                                          ("storyboard", ""), ("", "")])
def test_the_route_hands_respond_only_a_skill_on_the_shelf(client, monkeypatch, sent, expect):
    seen = {}

    async def refs(form):
        return [], [], []

    monkeypatch.setattr(api, "_collect_refs", refs)
    monkeypatch.setattr(scene_chain, "ground", lambda *a, **k: {})
    monkeypatch.setattr(creative_guide, "respond",
                        lambda conversation, **kw: seen.update(kw) or {"message": "ok", "choices": [], "brief": ""})
    response = client.post("/api/creative-guide", data={"skill": sent, "conversation": json.dumps({
        "messages": [{"role": "user", "content": "A mirror"}]})})
    assert response.status_code == 200
    job_id = response.json()["job_id"]
    for _ in range(100):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            break
        time.sleep(.01)
    assert job["status"] == "done", job
    assert seen["skill"] == expect
