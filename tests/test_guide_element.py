"""The Guide makes an element (2026-10-03).

Mike asked the composer "Can we create an Element sheet of the sugar free
redbull can" with the can's photo attached and got a Nano still of a can:
the box was in Create, and even the Guide could only SAY that a product
becomes an Element on another page. `add_element` is the one write that
makes something: proposed by the model like every write, confirmed on
the card, and run by the app with the photos the turn was handed -- the
model never touches a URL.
"""
import hashlib
import json
import time
import types as pytypes
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import api, auth
from app.main import app
from src import assistant_brain, creative_guide, entities, gemini_utils, guide_tools, preprod, scene_chain, scout


@pytest.fixture
def tmp_db(pg, monkeypatch):
    preprod.init(pg)
    entities.init(pg)
    scout.init(pg)
    monkeypatch.setenv("DATABASE_URL", pg)
    return pg


# ---------- the bridge's policy ----------

def test_add_element_is_a_local_write_with_a_card_label():
    assert guide_tools.is_write(guide_tools.ELEMENT_TOOL)
    assert guide_tools.is_local(guide_tools.ELEMENT_TOOL)
    assert guide_tools.WRITE_LABELS[guide_tools.ELEMENT_TOOL]
    spec = next(s for s in assistant_brain.LOCAL_SPECS if s["name"] == "add_element")
    assert spec["write"] is True
    assert spec["input_schema"]["properties"]["kind"]["enum"] == list(guide_tools.ELEMENT_KINDS)
    assert "NO photo" in spec["description"]            # the model is told not to call it bare


@pytest.mark.parametrize("args", [
    {"kind": "vehicle", "name": "Ducati"},                      # not a kind
    {"kind": "prop", "name": "   "},                            # no name
    {"kind": "product", "name": "Can", "notes": "see https://x.y/can.jpg"},   # a URL
    {"kind": "product", "name": "https://x.y/can.jpg"},
])
def test_check_args_refuses(args):
    with pytest.raises(guide_tools.Refused):
        guide_tools.check_args("add_element", args)


def test_check_args_clamps_and_defaults():
    out = guide_tools.check_args("add_element", {
        "kind": " Product ", "name": "  Red Bull   Sugar Free can ", "sheet": "no",
        "detail": "x" * 500, "notes": "  matte silver, blue stripe  ", "stray": "dropped"})
    assert out == {"kind": "product", "name": "Red Bull Sugar Free can", "sheet": False,
                   "detail": "x" * guide_tools.MAX_ELEMENT_DETAIL,
                   "notes": "matte silver, blue stripe"}
    assert guide_tools.check_args("add_element", {"kind": "prop", "name": "A"}) == {
        "kind": "prop", "name": "A", "detail": "", "notes": "", "sheet": True}


def test_published_with_the_local_set_and_never_run_from_the_model(monkeypatch):
    monkeypatch.setattr(guide_tools, "available", lambda: False)
    specs, run_tool = guide_tools.session(local=True, brand="zeropage")
    assert "add_element" in {s["name"] for s in specs}
    with pytest.raises(guide_tools.Refused):
        run_tool("add_element", {"kind": "product", "name": "Can"})


def test_run_has_no_library_side_runner():
    """`guide_tools.run` is the CLI/test door; the element's home is the
    act route, which holds the photo folders. A call here is a clear
    error, never a half-saved row."""
    with pytest.raises(ValueError, match="confirm card"):
        guide_tools.run("add_element", {"kind": "product", "name": "Can"})


# ---------- the turn ----------

class _Resp:
    def __init__(self, text=None, calls=()):
        self.text = text
        self.function_calls = [pytypes.SimpleNamespace(name=n, args=a) for n, a in calls]
        self.candidates = [pytypes.SimpleNamespace(content=pytypes.SimpleNamespace(role="model", parts=[]))]


def test_the_ask_becomes_a_proposal_and_nothing_is_saved(monkeypatch):
    responses = [_Resp(calls=[("add_element", {"kind": "product", "name": "Red Bull Sugar Free can",
                                                "notes": "blue and silver, sugar free band"})])]
    monkeypatch.setattr(gemini_utils, "generate_with_retry",
                        lambda c, m, contents, **k: responses.pop(0))

    def run_tool(name, args):
        pytest.fail("a write ran from the model")
    run_tool.attachments = {}

    reply = creative_guide.respond(
        creative_guide.Conversation(messages=[{"role": "user", "content":
                                               "Can we create an Element sheet of the sugar free redbull can"}]),
        client=object(), brand="zeropage", grounding={},
        tools=[dict(assistant_brain.ELEMENT_SPEC)], run_tool=run_tool)
    assert reply["proposal"]["tool"] == "add_element"
    assert reply["proposal"]["args"] == {"kind": "product", "name": "Red Bull Sugar Free can",
                                         "detail": "", "notes": "blue and silver, sugar free band",
                                         "sheet": True}
    assert reply["proposal"]["label"] == guide_tools.WRITE_LABELS["add_element"]
    assert reply["proposal"]["photos"] == []            # the ROUTE stamps these, not the model
    assert "Confirm" in reply["message"]


@pytest.mark.parametrize("message, photos, expect", [
    ("Can we create an Element sheet of the sugar free redbull can", 1, "call add_element NOW"),
    ("make the can an element", 2, "2 photos are attached"),
    ("turnaround of this please", 1, "call add_element NOW"),
    ("Can we create an Element sheet of the can", 0, "NO photo is attached"),
    ("a bartender closes the bar at 2am", 3, ""),
    ("the element of surprise", 1, ""),
    ("", 1, ""),
])
def test_element_note_reads_the_ask_and_the_photos(message, photos, expect):
    note = assistant_brain.element_note(message, photos)
    assert (expect in note) if expect else note == ""


def test_the_note_reaches_the_model_on_the_turn(monkeypatch):
    seen = {}

    def generate(client, model, contents, **kwargs):
        seen["contents"] = contents
        return json.dumps({"message": "ok", "choices": [], "brief": ""})

    monkeypatch.setattr(gemini_utils, "generate_with_retry", generate)
    creative_guide.respond(
        creative_guide.Conversation(messages=[{"role": "user", "content": "make it an element"}]),
        client=object(), brand="zeropage", grounding={},
        note=assistant_brain.element_note("make it an element", 1))
    texts = [part.text for part in seen["contents"][-1].parts if getattr(part, "text", None)]
    assert any("call add_element NOW" in t for t in texts)


def test_the_route_computes_the_note_off_its_own_refs(client, monkeypatch):
    monkeypatch.setattr(api, "_gemini_key", lambda a=None: "k")

    async def refs(form, **kwargs):
        return [], ["/refs/abc.jpg", "/refs/def.jpg"], []

    monkeypatch.setattr(api, "_collect_refs", refs)
    monkeypatch.setattr(scene_chain, "ground", lambda *a, **k: {})
    monkeypatch.setattr(api, "_guide_tools", lambda account_id, **k: ([], None))
    seen = {}
    monkeypatch.setattr(creative_guide, "respond",
                        lambda conversation, **kw: seen.update(kw) or {"message": "ok"})
    r = client.post("/api/creative-guide", data={
        "conversation": json.dumps({"messages": [{"role": "user", "content":
                                                   "Can we create an Element sheet of the can"}]})})
    _wait(client, r.json()["job_id"])
    assert "2 photos are attached" in seen["note"]


def test_the_prompt_tells_the_model_the_rules():
    text = Path("prompts/creative_guide_tools.txt").read_text()
    assert "add_element" in text
    assert "NO photo attached, do not call it" in text
    assert "never pass one" in text
    base = Path("prompts/creative_guide.txt").read_text()
    assert "Never write a scene" in base and "Never create" not in base
    assert "spec ad" in base


# ---------- the route stamps the photos the turn was handed ----------

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(auth, "current_user", lambda request: {"id": "guide-user"})
    monkeypatch.setattr(auth, "current_account", lambda request: {"slug": "zeropage"})
    app.dependency_overrides[auth.current_account_id] = lambda: None
    yield TestClient(app, headers={"X-ZPF-Model-Connection": "1"})
    app.dependency_overrides.pop(auth.current_account_id, None)


def _wait(client, job_id):
    for _ in range(200):
        body = client.get(f"/api/jobs/{job_id}").json()
        if body.get("status") in ("done", "error", "failed"):
            return body
        time.sleep(0.03)
    pytest.fail("job never finished")


def test_the_turn_puts_the_attached_photos_on_the_card(client, monkeypatch):
    monkeypatch.setattr(api, "_gemini_key", lambda a=None: "k")

    async def refs(form, **kwargs):
        return [(b"jpg", "image/jpeg", "the can")], ["/refs/abc.jpg"], []

    monkeypatch.setattr(api, "_collect_refs", refs)
    monkeypatch.setattr(scene_chain, "ground", lambda *a, **k: {})
    monkeypatch.setattr(api, "_guide_tools", lambda account_id, **k: ([], None))
    monkeypatch.setattr(creative_guide, "respond", lambda conversation, **kw: {
        "message": "I can save it.", "choices": [], "brief": "",
        "proposal": {"tool": "add_element", "args": {"kind": "product", "name": "Can"},
                     "label": "x", "photos": []}})
    r = client.post("/api/creative-guide", data={
        "conversation": json.dumps({"messages": [{"role": "user", "content": "make it an element"}]})})
    assert r.status_code == 200, r.text
    job = _wait(client, r.json()["job_id"])
    assert job["status"] == "done", job
    assert job["reply"]["proposal"]["photos"] == ["/refs/abc.jpg"]


def test_other_proposals_are_not_stamped(client, monkeypatch):
    monkeypatch.setattr(api, "_gemini_key", lambda a=None: "k")

    async def refs(form, **kwargs):
        return [], ["/refs/abc.jpg"], []

    monkeypatch.setattr(api, "_collect_refs", refs)
    monkeypatch.setattr(scene_chain, "ground", lambda *a, **k: {})
    monkeypatch.setattr(api, "_guide_tools", lambda account_id, **k: ([], None))
    monkeypatch.setattr(creative_guide, "respond", lambda conversation, **kw: {
        "message": "ok", "proposal": {"tool": "add_spark", "args": {"spark": "x"}, "label": "y",
                                      "photos": []}})
    r = client.post("/api/creative-guide", data={
        "conversation": json.dumps({"messages": [{"role": "user", "content": "bank it"}]})})
    job = _wait(client, r.json()["job_id"])
    assert job["reply"]["proposal"]["photos"] == []


# ---------- the click saves the element and draws the sheet ----------

@pytest.fixture
def element_world(tmp_db, tmp_path, monkeypatch):
    """Everything the save touches, stood in: the photo folders, the
    bytes behind a /refs URL, the vision describe, the sheet draw, R2 and
    the RAG shelf. Nothing here reaches a key or a network."""
    import src.locations as locations_mod

    monkeypatch.setattr(api, "PROPS_DIR", tmp_path / "props")
    monkeypatch.setattr(api, "CHARACTERS_DIR", tmp_path / "characters")
    monkeypatch.setattr(api, "LOCATIONS_DIR", tmp_path / "locations")
    monkeypatch.setattr(api, "_gemini_key", lambda a=None: "k")
    monkeypatch.setattr(api, "_mirror_photos_to_r2", lambda *a, **k: None)
    monkeypatch.setattr(api.rag, "connect", lambda db_url=None: (_ for _ in ()).throw(ConnectionError("no rag")))
    monkeypatch.setattr(api, "_photo_bytes",
                        lambda url: b"can-jpeg" if url == "/refs/can.jpg" else None)
    seen = {"vision": [], "drawn": []}
    monkeypatch.setattr(locations_mod, "describe_entity",
                        lambda client, kind, name, photos: seen["vision"].append((kind, name, len(photos)))
                        or {"appearance": "a blue and silver can"})
    monkeypatch.setattr(locations_mod, "describe_location",
                        lambda client, slug, photos: {"space": "a kitchen"})

    def draw(kind, name, photos, out_dir, **kw):
        seen["drawn"].append((kind, name, [p.name for p in photos], kw))
        target = out_dir / "sheet.jpg"
        target.write_bytes(b"sheet")
        return {"ok": True, "path": target, "generation_id": 1, "error": None}

    monkeypatch.setattr(api.element_sheet, "draw", draw)
    return seen


def _act(client, args, photos):
    return client.post("/api/creative-guide/act",
                       json={"tool": "add_element", "args": args, "photos": photos})


def test_confirm_saves_a_product_from_the_turns_photos_and_draws_its_sheet(client, element_world, tmp_db):
    r = _act(client, {"kind": "product", "name": "Red Bull Sugar Free can",
                      "notes": "blue and silver"}, ["/refs/can.jpg?thumb=1", "/refs/can.jpg"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] and body["tool"] == "add_element"
    assert body["result"].startswith("saved Red Bull Sugar Free can as a product with 1 photo")
    assert "drawing its reference sheet" in body["result"]
    el = body["element"]
    assert el["kind"] == "product" and el["slug"] == "red-bull-sugar-free-can"
    saved_name = f"gen-{hashlib.sha1(b'can-jpeg').hexdigest()[:16]}.jpg"
    assert [u.rsplit("/", 1)[-1].split("?")[0] for u in el["photos"]] == [saved_name]
    # a product is a prop filed under the product category, like the modal's
    [row] = entities.list_props(tmp_db, account_id=None)
    assert row["name"] == "Red Bull Sugar Free can" and row["category"] == "product"
    assert row["notes"] == "blue and silver" and row["photo_count"] == 1
    assert element_world["vision"] == [("prop", "Red Bull Sugar Free can", 1)]
    job = _wait(client, el["sheet_job"])
    assert job["status"] == "done", job
    assert job["output"].endswith("/sheet.jpg")
    [(kind, name, files, kw)] = element_world["drawn"]
    assert kind == "prop" and name == "Red Bull Sugar Free can" and len(files) == 1
    assert kw["detail"] == "product" and kw["notes"] == "blue and silver"


def test_a_character_and_a_place_go_to_their_own_tables(client, element_world, tmp_db):
    r = _act(client, {"kind": "character", "name": "Michael", "detail": "rider", "sheet": False},
             ["/refs/can.jpg"])
    assert r.status_code == 200, r.text
    assert r.json()["element"]["sheet_job"] is None
    assert "no sheet" not in r.json()["result"]          # not asked for, not reported missing
    [row] = entities.list_characters(tmp_db, account_id=None)
    assert row["name"] == "Michael" and row["role"] == "rider"
    r = _act(client, {"kind": "place", "name": "The Kitchen"}, ["/refs/can.jpg"])
    assert r.status_code == 200, r.text
    assert r.json()["element"]["kind"] == "place"
    assert [row["name"] for row in preprod.list_locations(tmp_db, account_id=None)] == ["the-kitchen"]


@pytest.mark.parametrize("photos", [[], None, "not-a-list", ["/refs/nobody-has-this.jpg"]])
def test_no_readable_photo_means_no_element(client, element_world, tmp_db, photos):
    r = _act(client, {"kind": "product", "name": "Can"}, photos)
    assert r.status_code == 400 and r.json()["error"]["code"] == "no_photos"
    assert entities.list_props(tmp_db, account_id=None) == []
    assert element_world["drawn"] == []


def test_the_click_still_refuses_a_url_in_the_args(client, element_world, tmp_db):
    r = _act(client, {"kind": "product", "name": "Can", "notes": "https://x/y.jpg"}, ["/refs/can.jpg"])
    assert r.status_code == 400 and r.json()["error"]["code"] == "refused"
    assert entities.list_props(tmp_db, account_id=None) == []


def test_the_click_needs_the_header(monkeypatch):
    monkeypatch.setattr(auth, "current_user", lambda request: {"id": "u"})
    app.dependency_overrides[auth.current_account_id] = lambda: None
    try:
        r = TestClient(app).post("/api/creative-guide/act",
                                 json={"tool": "add_element", "args": {}, "photos": ["/refs/a.jpg"]})
        assert r.status_code == 403
    finally:
        app.dependency_overrides.pop(auth.current_account_id, None)
