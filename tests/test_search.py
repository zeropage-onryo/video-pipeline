"""The ⌘K palette's global search (src/search.py, GET /api/search).

One question across projects, scenes (title and PROMPT), elements, renders
and cuts -- for ONE account. The things worth pinning: nobody sees another
account's rows, every word must match, a typed % is a literal, a title
match outranks a prompt match, gone things stay gone, and an empty query
is the recent list. Nothing here calls a model or spends.
"""
import pytest
from conftest import seed_two  # noqa: E402

from src import db, entities, preprod, projects, render_assets, search
from src.cut import store as cut_store


def _scene(dsn, account_id, title, prompt, **extra):
    return preprod.save_concept(
        {"title": title, "hook": "", "logline": f"{title}: a logline", "card_line": f"{title} in a line",
         "shots": [{"n": 1, "type": "BROLL", "source": "AI", "tool": "LTX", "desc": "d",
                    "prompt": prompt, "refs": ["/refs/a.jpg"], **extra}]},
        brand="zeropage", prompt_template="T", dsn=dsn, account_id=account_id)


def _cut(conn, account_id, title, deleted=False):
    conn.execute(
        "INSERT INTO cut_projects (id, created_at, updated_at, title, timeline_key, fps, deleted_at, account_id) "
        "VALUES (%s, '2026-10-08', '2026-10-08', %s, %s, 30, %s, %s)",
        (f"cut-{title}", title, f"cut:{title}", "t" if deleted else None, account_id))


@pytest.fixture
def world(pg, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", pg)
    for m in (preprod, entities, render_assets, projects, cut_store):
        m.init(pg)
    seeded = seed_two("mike@example.com", dsn=pg)
    a, b = seeded["accounts"][0], seeded["accounts"][1]
    monkeypatch.setattr(render_assets, "_ingest", lambda *x, **k: {"ok": True, "chunks": 0, "error": None})

    trail = projects.create("Nike trail spot", "FOR: trail runners at dawn\nNEVER: logos", pg, account_id=a)
    projects.create("Gold Hour perfume", "", pg, account_id=a)
    ridge = _scene(pg, a, "Ridge Line", "A runner crests a fogged ridge at dawn, 50% fog.")
    projects.tag_concepts([ridge], trail["id"], pg, account_id=a)
    valley = _scene(pg, a, "Valley Descent", "She drops into the valley past a ridge of pines.")
    passed = _scene(pg, a, "Ridge Two", "An older take on the ridge.")
    preprod.set_archived(passed, True, dsn=pg, account_id=a)
    theirs = _scene(pg, b, "Ridge Secret", "The other account's ridge.")

    entities.add_character("Ridge Runner", role="runner", notes="the trail runner", dsn=pg, account_id=a)
    entities.add_prop("Ghost can", category="product", notes="energy drink can", dsn=pg, account_id=a)
    preprod.add_location("Garage", notes="ridge light through the door", dsn=pg, account_id=a)
    entities.add_character("Ridge Spy", role="spy", dsn=pg, account_id=b)

    kept = render_assets.record(generation_id=1, tool="nano", model="gemini-3-pro-image-preview",
                                media_kind="image", prompt="ridge at dawn, wide", media_url="/renders/a.png",
                                dsn=pg, account_id=a)["id"]
    gone = render_assets.record(generation_id=2, tool="nano", model="gemini-3-pro-image-preview",
                                media_kind="image", prompt="ridge removed", media_url="/renders/b.png",
                                dsn=pg, account_id=a)["id"]
    render_assets.soft_delete(gone, pg, account_id=a)
    render_assets.record(generation_id=3, tool="nano", model="gemini-3-pro-image-preview",
                         media_kind="image", prompt="ridge for b", media_url="/renders/c.png",
                         dsn=pg, account_id=b)
    with db.connect(pg) as conn:
        _cut(conn, a, "Ridge teaser")
        _cut(conn, a, "Ridge deleted", deleted=True)
        _cut(conn, b, "Ridge for b")
    return {"dsn": pg, "a": a, "b": b, "trail": trail["id"], "ridge": ridge, "valley": valley,
            "passed": passed, "theirs": theirs, "kept": kept, "gone": gone}


def _ids(groups, name, key="id"):
    return [item[key] for item in groups[name]]


def test_every_group_answers_for_its_own_account_only(world):
    out = search.run("ridge", account_id=world["a"], dsn=world["dsn"])
    g = out["groups"]
    assert out["recent"] is False and out["q"] == "ridge"
    # the title match first, the prompt-only match after it, the archived one last
    assert _ids(g, "scenes") == [world["ridge"], world["valley"], world["passed"]]
    assert world["theirs"] not in _ids(g, "scenes")
    assert [e["name"] for e in g["elements"]] == ["Ridge Runner", "Garage"]
    assert {e["kind"] for e in g["elements"]} == {"character", "place"}
    assert _ids(g, "renders") == [world["kept"]]             # removed and foreign ones stay gone
    assert [c["title"] for c in g["cuts"]] == ["Ridge teaser"]
    assert g["projects"] == []                                 # no project says "ridge"

    theirs = search.run("ridge", account_id=world["b"], dsn=world["dsn"])["groups"]
    assert _ids(theirs, "scenes") == [world["theirs"]]
    assert [e["name"] for e in theirs["elements"]] == ["Ridge Spy"]
    assert [c["title"] for c in theirs["cuts"]] == ["Ridge for b"]


def test_a_title_match_outranks_a_prompt_match_and_archived_rows_sink(world):
    scenes = search.run("ridge", account_id=world["a"], dsn=world["dsn"])["groups"]["scenes"]
    ids = [s["id"] for s in scenes]
    assert ids.index(world["ridge"]) < ids.index(world["valley"])
    assert ids[-1] == world["passed"] and scenes[-1]["archived"] is True
    ridge = scenes[ids.index(world["ridge"])]
    assert ridge["n"] == f"SHOOT-{world['ridge']:02d}"
    assert ridge["project_id"] == world["trail"] and ridge["project_title"] == "Nike trail spot"
    # a prompt-only hit says WHERE in the prompt it matched
    valley = scenes[ids.index(world["valley"])]
    assert "ridge of pines" in valley["sub"]
    assert ridge["cover"] == "/refs/a.jpg"


def test_every_word_must_match_and_a_percent_is_literal(world):
    g = search.run("fogged dawn", account_id=world["a"], dsn=world["dsn"])["groups"]
    assert _ids(g, "scenes") == [world["ridge"]]
    assert search.run("fogged zebra", account_id=world["a"], dsn=world["dsn"])["groups"]["scenes"] == []
    assert _ids(search.run("50%", account_id=world["a"], dsn=world["dsn"])["groups"], "scenes") == [world["ridge"]]
    # "%" and "_" are literals, not wildcards: "%" finds the one prompt
    # that says "50%", and "_" finds nothing, where a wildcard would find all
    assert _ids(search.run("%", account_id=world["a"], dsn=world["dsn"])["groups"], "scenes") == [world["ridge"]]
    assert search.run("_", account_id=world["a"], dsn=world["dsn"])["groups"]["renders"] == []


def test_projects_match_on_their_brief_and_products_say_so(world):
    g = search.run("trail", account_id=world["a"], dsn=world["dsn"])["groups"]
    assert [p["title"] for p in g["projects"]] == ["Nike trail spot"]
    assert g["projects"][0]["sub"] == "FOR: trail runners at dawn"
    prods = search.run("energy", account_id=world["a"], dsn=world["dsn"])["groups"]["elements"]
    assert [(e["name"], e["kind"], e["id"].split("-")[0]) for e in prods] == [("Ghost can", "product", "prop")]


def test_an_empty_query_is_the_recent_list(world):
    out = search.run("  ", account_id=world["a"], dsn=world["dsn"])
    g = out["groups"]
    assert out["recent"] is True
    # newest-touched first: filing a scene under the trail spot touched it
    assert [p["title"] for p in g["projects"]] == ["Nike trail spot", "Gold Hour perfume"]
    assert world["passed"] not in _ids(g, "scenes")            # archived is not "recent"
    assert world["theirs"] not in _ids(g, "scenes")
    assert g["elements"] == g["renders"] == g["cuts"] == []


def test_the_limit_is_clamped(world):
    one = search.run("ridge", account_id=world["a"], limit=1, dsn=world["dsn"])["groups"]
    assert len(one["scenes"]) == 1 and len(one["elements"]) == 1
    assert len(search.run("ridge", account_id=world["a"], limit=999, dsn=world["dsn"])["groups"]["scenes"]) == 3


def test_snippet_shows_where_the_words_matched():
    text = "word " * 40 + "the fogged ridge at dawn " + "tail " * 40
    cut = search.snippet(text, ["fogged"])
    assert "fogged ridge" in cut and cut.startswith("…") and cut.endswith("…")
    assert len(cut) <= search._SNIPPET + 2
    assert search.snippet("short", ["x"]) == "short"
    assert search.tokens("  Ridge   AT dawn ") == ["ridge", "at", "dawn"]


def test_the_route_answers_as_the_signed_in_account(world, monkeypatch):
    from fastapi.testclient import TestClient

    import app.main as app_main
    from app import auth

    monkeypatch.setattr(auth, "current_user", lambda request: {"id": "u1", "email": "x@example.com"})
    client = TestClient(app_main.app)
    app_main.app.dependency_overrides[auth.current_account_id] = lambda: world["a"]
    try:
        res = client.get("/api/search", params={"q": "ridge"})
        assert res.status_code == 200
        body = res.json()
        assert set(body["groups"]) == set(search.GROUPS)
        scene = body["groups"]["scenes"][0]
        assert scene["id"] == world["ridge"] and "cover" not in scene and scene["thumb"]
        element = body["groups"]["elements"][0]
        assert element["frames"] == 0 and element["thumb"] is None   # no photos on file in a test
        assert body["groups"]["renders"][0]["thumb"] and "media_url" not in body["groups"]["renders"][0]
        app_main.app.dependency_overrides[auth.current_account_id] = lambda: world["b"]
        theirs = client.get("/api/search", params={"q": "ridge"}).json()["groups"]
        assert [s["id"] for s in theirs["scenes"]] == [world["theirs"]]
    finally:
        app_main.app.dependency_overrides[auth.current_account_id] = lambda: None
