"""The subscription lane (2026-09-12): a clip rendered by hand in Runway
Explore, filed onto a shot through the Queue. Two things are load-bearing
and both are tested here -- the gate is a column an operator sets from a
shell (never an env var, never a browser route), and the row it writes is
FREE (cost NULL), never $0.

The shared test client resolves to NO account (tests/conftest.py), which
is exactly the state the gate must refuse; the `lane` fixture seeds the
real accounts and acts as the zeropage one, so the open lane can be
exercised too."""
import inspect
import io

import pytest

from app import api as api_mod
from app import auth
from app.main import app
from src import accounts, db, preprod, runway
from tests.test_api import (  # noqa: F401  (the shared client, its stubs, the throwaway schema)
    client,
    fresh_jobs,
    no_real_rag_store,
    signed_in,
    tmp_db,
)

MP4 = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 2048
MOV = b"\x00\x00\x00\x14ftypqt  " + b"\x00" * 2048
SHOT = [{"n": 1, "type": "BROLL", "source": "AI", "tool": "RUNWAY",
         "prompt": "low key garage, single bulb"}]


@pytest.fixture
def lane(tmp_db):  # noqa: F811
    """(path, account_id, slug): the seeded zeropage account, and the
    client acting as it for the test's duration."""
    seeded = accounts.seed("mike@example.com", dsn=tmp_db)
    account_id = seeded["accounts"][0]
    app.dependency_overrides[auth.current_account_id] = lambda: account_id
    try:
        yield tmp_db, account_id, "zeropage"
    finally:
        app.dependency_overrides[auth.current_account_id] = lambda: None


def scene(path, account_id):
    return preprod.save_concept(
        {"title": "Vault", "hook": "", "logline": "", "shots": SHOT},
        brand="zeropage", dsn=path, account_id=account_id)


def generation_row(path, generation_id):
    import json
    with db.connect(path) as conn:
        row = conn.execute("SELECT cost_usd, params_json FROM generations WHERE id = %s",
                           (generation_id,)).fetchone()
    return {"cost_usd": row["cost_usd"], "params": json.loads(row["params_json"] or "{}")}


# --- the gate ----------------------------------------------------------------

def test_the_lane_is_closed_for_an_account_nobody_opened_it_for(lane):
    path, account_id, _ = lane
    assert accounts.is_manual_lane_operator(account_id, dsn=path) is False
    assert client.get("/api/queue/pending").json()["manual_lane"] is False
    concept_id = scene(path, account_id)
    res = client.post(f"/api/queue/{concept_id}/clip",
                      files={"clip": ("c.mp4", io.BytesIO(MP4), "video/mp4")})
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "lane_closed"


def test_the_lane_is_closed_with_no_account_at_all(tmp_db):  # noqa: F811
    """The shared client's state: signed in, no tenant. Never open."""
    assert client.get("/api/queue/pending").json()["manual_lane"] is False
    assert accounts.is_manual_lane_operator(None, dsn=tmp_db) is False


def test_the_operator_toggle_is_by_slug_and_refuses_an_unknown_one(lane):
    path, account_id, slug = lane
    assert accounts.set_manual_lane_operator(slug, True, dsn=path) == account_id
    assert accounts.is_manual_lane_operator(account_id, dsn=path) is True
    assert client.get("/api/queue/pending").json()["manual_lane"] is True
    accounts.set_manual_lane_operator(slug, False, dsn=path)
    assert accounts.is_manual_lane_operator(account_id, dsn=path) is False
    with pytest.raises(ValueError):
        accounts.set_manual_lane_operator("nobody", True, dsn=path)


def test_the_gate_is_a_column_not_an_environment_variable():
    """A gate with two doors is one door: neither side of the toggle
    consults the environment."""
    for fn in (accounts.is_manual_lane_operator, accounts.set_manual_lane_operator):
        assert "environ" not in inspect.getsource(fn)


def test_no_browser_route_grants_the_lane():
    """An account able to open the lane for itself would defeat it."""
    paths = [getattr(r, "path", "") for r in app.routes]
    assert not any("operator" in p for p in paths), paths
    assert "set_manual_lane_operator" not in inspect.getsource(api_mod)


def test_the_cli_opens_and_closes_the_lane(lane, capsys, monkeypatch):
    path, account_id, slug = lane
    monkeypatch.setenv("DATABASE_URL", path)
    accounts.main(["operator", slug, "--on"])
    assert "OPEN" in capsys.readouterr().out
    assert accounts.is_manual_lane_operator(account_id, dsn=path) is True
    accounts.main(["operator", slug, "--off"])
    assert accounts.is_manual_lane_operator(account_id, dsn=path) is False
    with pytest.raises(SystemExit):
        accounts.main(["operator", "nobody", "--on"])


# --- filing a clip -------------------------------------------------------------

def test_is_mp4_reads_the_magic_number_not_the_extension():
    assert runway.is_mp4(MP4[:12]) is True
    assert runway.is_mp4(MOV[:12]) is False        # QuickTime brand
    assert runway.is_mp4(b"RIFF....WEBP") is False
    assert runway.is_mp4(b"") is False


@pytest.fixture
def open_lane(lane, monkeypatch, tmp_path):
    import src.storage as storage
    path, account_id, slug = lane
    accounts.set_manual_lane_operator(slug, True, dsn=path)
    monkeypatch.setattr(runway, "RENDER_DIR", tmp_path / "renders")
    monkeypatch.setattr(storage, "configured", lambda: False)
    return path, account_id, tmp_path / "renders"


def test_a_filed_clip_lands_on_the_shot_as_a_free_row(open_lane):
    path, account_id, render_dir = open_lane
    concept_id = scene(path, account_id)
    res = client.post(f"/api/queue/{concept_id}/clip",
                      files={"clip": ("whatever i called it.mp4", io.BytesIO(MP4), "video/mp4")})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["cost_usd"] is None                 # FREE, never $0
    assert body["media_url"].startswith("/renders/runway/c")
    assert "manual" in body["media_url"]             # server-named, not the upload's name
    concept = preprod.get_concept(concept_id, dsn=path, account_id=account_id)
    assert concept["shots"][0]["media_url"] == body["media_url"]
    row = generation_row(path, body["generation_id"])
    assert row["cost_usd"] is None
    assert row["params"]["source"] == runway.MANUAL_SOURCE
    assert (render_dir / body["media_url"].split("/")[-1]).exists()


def test_a_filed_clip_leaves_the_pending_list(open_lane):
    path, account_id, _ = open_lane
    concept_id = scene(path, account_id)
    preprod.set_picked(concept_id, True, dsn=path, account_id=account_id)
    assert concept_id in [c["id"] for c in client.get("/api/queue/pending").json()["items"]]
    client.post(f"/api/queue/{concept_id}/clip",
                files={"clip": ("a.mp4", io.BytesIO(MP4), "video/mp4")})
    assert concept_id not in [c["id"] for c in client.get("/api/queue/pending").json()["items"]]


def test_a_second_drop_is_refused_not_applied(open_lane):
    path, account_id, render_dir = open_lane
    concept_id = scene(path, account_id)
    first = client.post(f"/api/queue/{concept_id}/clip",
                        files={"clip": ("a.mp4", io.BytesIO(MP4), "video/mp4")})
    assert first.status_code == 200
    second = client.post(f"/api/queue/{concept_id}/clip",
                         files={"clip": ("b.mp4", io.BytesIO(MP4), "video/mp4")})
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "has_clip"
    assert len(list(render_dir.glob("*.mp4"))) == 1    # one file, one row


def test_a_mov_and_an_empty_upload_are_refused(open_lane):
    path, account_id, _ = open_lane
    concept_id = scene(path, account_id)
    res = client.post(f"/api/queue/{concept_id}/clip",
                      files={"clip": ("c.mov", io.BytesIO(MOV), "video/quicktime")})
    assert res.status_code == 415
    res = client.post(f"/api/queue/{concept_id}/clip", data={})
    assert res.status_code == 400


def test_an_oversized_upload_is_refused_while_streaming(open_lane, monkeypatch):
    path, account_id, _ = open_lane
    monkeypatch.setattr(api_mod, "MANUAL_CLIP_MAX_BYTES", 1000)
    concept_id = scene(path, account_id)
    res = client.post(f"/api/queue/{concept_id}/clip",
                      files={"clip": ("big.mp4", io.BytesIO(MP4), "video/mp4")})
    assert res.status_code == 413
