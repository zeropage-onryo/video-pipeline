"""The LOOK belongs to the project, not the brand (2026-10-02, Mike's call).

`looks.look_block` is the one place the look resolves: the project's own
look -> the brand file -> "". A project in scope answers by itself, and a
project with no look typed gets NO look -- falling back to the brand file
there is exactly how a house style comes back without anybody noticing.

Each test names the line it guards.
"""
import pytest
from fastapi.testclient import TestClient

from app import auth
from app.main import app
from src import looks, preprod, project_context, projects, shootgen

client = TestClient(app)

# The words the old zeropage look forced onto every run. None of them may
# reach a scene prompt written inside a project that has no look.
HOUSE_GENRE = ("horror", "creature", "wrongness", "drizzle", "teal")
DAYLIGHT = "bright daylight product spot, white cyc, no shadows"


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


def a_project(look=""):
    return {"id": 1, "title": "Untitled", "brief": "", "memory": [], "look": look}


# guards: a project in scope never falls through to the brand file
def test_a_project_with_no_look_gets_no_look():
    assert looks.look_block("zeropage"), "the brand file is the no-project answer"
    assert looks.look_block("zeropage", project=a_project()) == ""
    assert looks.look_block("zeropage", project={"title": "row from before"}) == ""
    with project_context.active(a_project("   ")):
        assert looks.look_block("zeropage") == ""
        assert looks.look_block("antihero") == ""


# guards: the order -- project look first
def test_a_project_look_wins_over_the_brand_file():
    brand_file = looks.look_block("zeropage")
    assert looks.look_block("zeropage", project=a_project(DAYLIGHT)) == DAYLIGHT
    with project_context.active(a_project(DAYLIGHT)):
        assert looks.look_block("zeropage") == DAYLIGHT
    assert looks.look_block("zeropage") == brand_file            # reset after


# guards: look_block's degrade-never-raise contract
def test_a_missing_brand_file_or_a_bad_project_is_no_look():
    assert looks.look_block("no_such_brand") == ""
    assert looks.look_block("zeropage", project=a_project(None)) == ""
    assert looks.look_block("zeropage", project=a_project(42)) == ""


def build_scene_brief(brand):
    return shootgen.build_scene_brief_prompt(brand, spark="a can of soda on a table")


def build_scenes(brand):
    return shootgen.build_scenes_prompt("a can of soda on a table", brand, 1, [])


# guards: the regression this whole change exists for, on BOTH writers --
# the Studio Create (scenes_prompt) and the graph/Director brief
@pytest.mark.parametrize("build", [build_scene_brief, build_scenes])
@pytest.mark.parametrize("brand", ["zeropage", "antihero"])
def test_a_scene_prompt_in_a_look_less_project_carries_no_house_genre(build, brand):
    with project_context.active(a_project()):
        prompt = build(brand)
    found = [w for w in HOUSE_GENRE if w in prompt.lower()]
    assert found == [], f"house genre leaked into the scene prompt: {found}"
    assert looks.unset_note() in prompt


# guards: the house style everywhere ELSE a scene writer reads it from --
# the templates' own defaults, the zeropage brand note ("dark, contrasty")
# and the gold-standard exemplar (a dark comedy with a monster). Both
# verification Creates copied the template defaults verbatim, and a
# look-less Create still went "gritty ... deep blacks" off the other two.
HOUSE_STYLE_DEFAULTS = ("raw handheld, close wide-angle", "muted colour", "wet surfaces",
                        "wet physics", "second red accent", "daylight flatness",
                        "heavy colour grading", "smooth commercial camera movement",
                        "physical comedy or tension", "dark, contrasty", "dark comedy",
                        "monster", "portal")


@pytest.mark.parametrize("build", [build_scene_brief, build_scenes])
def test_the_scene_writers_carry_no_default_style_of_their_own(build):
    with project_context.active(a_project()):
        prompt = build("zeropage")
    found = [w for w in HOUSE_STYLE_DEFAULTS if w in prompt.lower()]
    assert found == [], f"a default would fight the project's look: {found}"


# guards: the {look} slot in BOTH writers carrying the project's look
@pytest.mark.parametrize("build", [build_scene_brief, build_scenes])
def test_a_scene_prompt_in_a_project_carries_its_look(build):
    with project_context.active(a_project(DAYLIGHT)):
        prompt = build("zeropage")
    assert DAYLIGHT in prompt
    assert looks.unset_note() not in prompt


# guards: the nightly walk (no project) still reads the brand note
@pytest.mark.parametrize("build", [build_scene_brief, build_scenes])
def test_with_no_project_the_brand_note_is_the_look(build):
    prompt = build("zeropage")
    assert looks.look_block("zeropage") in prompt


# guards: the column, and resolution per project rather than per account
def test_two_projects_on_one_account_resolve_their_own_looks(tmp_db):
    ad = projects.create("Soda ad", "", tmp_db, account_id=None, look=DAYLIGHT)
    short = projects.create("Basement short", "", tmp_db, account_id=None)
    assert short["look"] == ""
    short = projects.update(short["id"], tmp_db, account_id=None,
                            look="sodium streetlight, 50mm, grain")

    ad = projects.get(ad["id"], tmp_db, account_id=None)
    short = projects.get(short["id"], tmp_db, account_id=None)
    bare = projects.create("No look yet", "", tmp_db, account_id=None)
    seen = {}
    for project in (ad, short, bare):
        with project_context.active(project):
            seen[project["title"]] = (looks.look_block("zeropage"),
                                      shootgen.build_scenes_prompt("x", "zeropage", 1, []))
    assert seen["Soda ad"][0] == DAYLIGHT
    assert seen["Basement short"][0] == "sodium streetlight, 50mm, grain"
    assert seen["No look yet"][0] == ""
    assert "sodium streetlight" not in seen["Soda ad"][1]
    assert DAYLIGHT not in seen["Basement short"][1]
    assert DAYLIGHT not in seen["No look yet"][1]
    # updating one look leaves the other alone, and the brief is untouched
    projects.update(ad["id"], tmp_db, account_id=None, brief="for the launch")
    assert projects.get(ad["id"], tmp_db, account_id=None)["look"] == DAYLIGHT


# guards: the routes take and return `look`
def test_the_projects_api_takes_a_look(tmp_db):
    made = client.post("/api/projects", json={"title": "Soda ad", "look": DAYLIGHT}).json()
    assert made["look"] == DAYLIGHT
    bare = client.post("/api/projects", json={"title": "Short"}).json()
    assert bare["look"] == ""
    patched = client.patch(f"/api/projects/{bare['id']}", json={"look": "  overcast, 35mm  "})
    assert patched.json()["look"] == "overcast, 35mm"
    # a PATCH that names only the brief leaves the look where it was
    client.patch(f"/api/projects/{bare['id']}", json={"brief": "a short"})
    assert client.get(f"/api/projects/{bare['id']}").json()["look"] == "overcast, 35mm"
    cleared = client.patch(f"/api/projects/{bare['id']}", json={"look": ""}).json()
    assert cleared["look"] == ""


# guards: /scenes/run sets the project, so the writer sees ITS look
def test_create_inside_a_project_writes_with_its_look(tmp_db, monkeypatch):
    from src import scene_chain

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    made = client.post("/api/projects", json={"title": "Soda ad", "look": DAYLIGHT}).json()
    seen = {}

    def fake_run(idea, brand, **kw):
        seen["look"] = looks.look_block(brand)
        seen["prompt"] = shootgen.build_scenes_prompt(idea, brand, 1, [])
        cid = preprod.save_concept(
            {"title": "t", "hook": "", "logline": "",
             "shots": [{"n": 1, "type": "BROLL", "source": "AI", "tool": "RUNWAY",
                        "desc": "d", "prompt": "p", "refs": ["/refs/seed.jpg"]}]},
            brand="zeropage", prompt_template="T", dsn=tmp_db, account_id=None)
        return {"scenes": [{"concept_id": cid}], "notes": []}

    monkeypatch.setattr(scene_chain, "run", fake_run)
    r = client.post("/api/scenes/run", data={"idea": "a can on a table",
                                               "project_id": str(made["id"])})
    assert r.status_code == 200
    job_id = r.json()["job_id"]
    import time
    deadline = time.time() + 5
    while client.get(f"/api/jobs/{job_id}").json()["status"] not in ("done", "failed"):
        assert time.time() < deadline, "job never finished"
        time.sleep(0.02)
    assert seen["look"] == DAYLIGHT and DAYLIGHT in seen["prompt"]
