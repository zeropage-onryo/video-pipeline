"""
One codebase, two deployment postures (DEV_TOOLS in app/main.py).

Dev posture (DEV_TOOLS=1, the suite's default via conftest): /ui plus
the whole legacy dev console. Public posture (unset/0): only /, /signin,
/ui and /api exist -- the dev console is never registered, so /studio
404s exactly like any undefined route.

The flag is read once at app.main import, so the public posture is
tested by reloading the module under DEV_TOOLS=0 and restoring the dev
posture on teardown. "0" rather than delenv: the reload re-runs
load_dotenv(), which would re-set a *deleted* DEV_TOOLS from the local
.env, while an existing value always wins.
"""
import importlib

import pytest
from fastapi.testclient import TestClient

import app.main as app_main
from app import api as api_mod
from app import auth

# Every dev-console GET page. Not exhaustive of the router (53 routes),
# but one per screen family -- the include is all-or-nothing anyway.
DEV_PAGES = (
    "/dashboard", "/studio", "/concepts", "/assets", "/holds",
    "/winners", "/library", "/analytics", "/locations", "/characters",
    "/props", "/references/pick", "/post-image", "/videos/new",
    # the Dev Studio's own ungated JSON surface: it reads every stat
    # without a session, so a public deployment must not register it
    "/studio/api/evals/runs",
    "/studio/api/evals/requeries",
)


@pytest.fixture
def public_app(monkeypatch):
    monkeypatch.setenv("DEV_TOOLS", "0")
    module = importlib.reload(app_main)
    yield module.app
    # Restore the dev posture for the rest of the suite before
    # monkeypatch undoes the env (dependent fixtures tear down first).
    monkeypatch.setenv("DEV_TOOLS", "1")
    importlib.reload(app_main)


@pytest.fixture
def signed_in(monkeypatch):
    """Same weld as test_api.py: these tests exercise the posture, not
    the session gate, which has its own suite in test_auth.py."""
    stub = {"id": 1, "email": "test@example.com", "display_name": "Test"}
    monkeypatch.setattr(auth, "current_user", lambda request: stub)
    monkeypatch.setattr(
        auth, "current_account",
        lambda request, user=None: {"slug": "antihero", "display_name": "ANTIHERO"})


@pytest.fixture(autouse=True)
def no_real_rag_store(monkeypatch):
    """capabilities() probes the store with a real rag.connect(), and
    psycopg dials below the socket module where conftest's network guard
    can't see it -- refuse it explicitly."""
    def refused(db_url=None):
        raise ConnectionError("no rag store in tests")

    monkeypatch.setattr(api_mod.rag, "connect", refused)


def test_public_posture_dev_console_does_not_exist(public_app):
    client = TestClient(public_app)
    for page in DEV_PAGES:
        assert client.get(page).status_code == 404, page
    # POSTs 404 too (a registered path would answer 405 to a bad method)
    assert client.post("/kill").status_code == 404
    assert client.post("/concepts/generate").status_code == 404


def test_public_posture_keeps_the_public_surface(public_app):
    client = TestClient(public_app)
    assert client.get("/").status_code == 200
    assert client.get("/robots.txt").status_code == 200
    assert client.get("/llms.txt").status_code == 200
    assert client.get("/sitemap.xml").status_code == 200
    assert client.get("/signin").status_code == 200
    # /ui still gates on a session, /brand still flips the cookie
    r = client.get("/ui", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/signin"
    r = client.post("/brand/zeropage", data={"next": "/ui"}, follow_redirects=False)
    assert r.status_code == 303


def test_public_landing_cta_points_at_ui_not_a_404(public_app):
    page = TestClient(public_app).get("/").text
    assert 'href="/ui"' in page
    assert 'href="/studio"' not in page


def test_public_capabilities_report_dev_tools_off(public_app, signed_in):
    caps = TestClient(public_app).get("/api/capabilities").json()
    assert caps["dev_tools"] is False


def test_dev_posture_registers_the_dev_console():
    # Behavioral proof the include ran (FastAPI nests included routers,
    # so app.routes doesn't list their paths directly): /dashboard is the
    # one dev route that answers without touching the DB.
    r = TestClient(app_main.app).get("/dashboard", follow_redirects=False)
    assert r.status_code == 308 and r.headers["location"] == "/studio"
    # ...and the dev router itself carries every page family. The
    # console pages' own behavior is covered in test_app.py and friends.
    paths = {route.path for route in app_main.dev.routes}
    for page in DEV_PAGES:
        assert page in paths, page


def test_dev_posture_landing_cta_points_at_studio():
    page = TestClient(app_main.app).get("/").text
    assert 'href="/studio"' in page


def test_dev_capabilities_report_dev_tools_on(signed_in):
    caps = TestClient(app_main.app).get("/api/capabilities").json()
    assert caps["dev_tools"] is True


def test_ui_legacy_link_is_capability_gated(signed_in):
    """The rail's legacy link rides the existing data-cap convention, so
    applyCaps() hides it wherever /studio doesn't exist -- and it ships
    hidden, unhidden only when capabilities land with the flag on."""
    page = TestClient(app_main.app).get("/ui").text
    assert 'data-cap="dev_tools"' in page
