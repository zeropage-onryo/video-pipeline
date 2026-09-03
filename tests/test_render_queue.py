"""
ops/render_queue.py -- the repo side of rendering on SUBSCRIPTION credits.

The split it serves: a Claude session picks shots and calls the Higgsfield
MCP (which spends the app plan's credits, not API credits), and this file
tells that session what is waiting and files what came back. These tests
guard the three things that would silently corrupt the pipeline:

- `pending` must mean exactly what /queue/pending means, or the session
  renders things that were never queued;
- a clip must land somewhere /renders can actually serve, or the Queue
  card shows a broken video for a render that really happened;
- the attempt must be logged with credits, not invented dollars.
"""
import json

import pytest

from ops import render_queue as rq
from src import generative, preprod


@pytest.fixture
def tmp_db(pg, monkeypatch):
    path = pg
    preprod.init(path)
    generative.init(path)
    monkeypatch.setenv("DATABASE_URL", path)
    return path


@pytest.fixture(autouse=True)
def renders_in_tmp(tmp_path, monkeypatch):
    """Never write into the real data/renders/ from a test."""
    root = tmp_path / "renders"
    monkeypatch.setattr(rq, "RENDERS_ROOT", root)
    monkeypatch.setattr(rq, "RENDER_DIR", root / "higgsfield")
    return root


def a_scene(path, title="Cold Open", prompt="a close shot"):
    return preprod.save_concept(
        {"title": title, "hook": "", "logline": "",
         "shots": [{"n": 1, "type": "BROLL", "source": "AI", "tool": "HIGGSFIELD",
                    "desc": title, "prompt": prompt}]},
        brand="zeropage", prompt_template="T", dsn=path, account_id=None)


def a_clip(tmp_path, name="clip.mp4", size=200_000):
    p = tmp_path / name
    p.write_bytes(b"\x00" * size)
    return p


# ---------- what counts as waiting ----------

def test_an_unpicked_concept_is_not_waiting(tmp_db):
    a_scene(tmp_db)
    assert rq.pending() == []


def test_a_picked_scene_is_waiting(tmp_db):
    cid = a_scene(tmp_db, title="The Bronze Debt")
    preprod.set_picked(cid, True, dsn=tmp_db, account_id=None)
    waiting = rq.pending()
    assert [w["concept_id"] for w in waiting] == [cid]
    assert waiting[0]["title"] == "The Bronze Debt"
    assert waiting[0]["prompt"] == "a close shot"


def test_an_archived_scene_is_not_waiting(tmp_db):
    cid = a_scene(tmp_db)
    preprod.set_picked(cid, True, dsn=tmp_db, account_id=None)
    preprod.set_archived(cid, True, dsn=tmp_db, account_id=None)
    assert rq.pending() == []


def test_a_scene_that_already_has_a_clip_is_not_waiting(tmp_db, tmp_path):
    cid = a_scene(tmp_db)
    preprod.set_picked(cid, True, dsn=tmp_db, account_id=None)
    preprod.set_shot_media_url(cid, 1, "/renders/higgsfield/x.mp4", dsn=tmp_db, account_id=None)
    assert rq.pending() == []


def test_brand_filter(tmp_db):
    cid = a_scene(tmp_db)
    preprod.set_picked(cid, True, dsn=tmp_db, account_id=None)
    assert rq.pending(brand="zeropage")
    assert rq.pending(brand="antihero") == []


# ---------- filing what came back ----------

def test_a_clip_lands_where_renders_can_serve_it(tmp_db, tmp_path, renders_in_tmp):
    """app/main.py mounts /renders on data/renders/. A clip left anywhere
    else 404s in the Queue however real the render was."""
    cid = a_scene(tmp_db)
    preprod.set_picked(cid, True, dsn=tmp_db, account_id=None)
    out = rq.import_clip(cid, 1, str(a_clip(tmp_path)), "seedance1_5", 4.8, None, True)
    assert out["media_url"] == "/renders/higgsfield/clip.mp4"
    assert (renders_in_tmp / "higgsfield" / "clip.mp4").is_file()


def test_a_second_clip_does_not_overwrite_the_first(tmp_db, tmp_path, renders_in_tmp):
    cid = a_scene(tmp_db)
    preprod.set_picked(cid, True, dsn=tmp_db, account_id=None)
    rq.import_clip(cid, 1, str(a_clip(tmp_path)), "seedance1_5", 4.8, None, True)
    cid2 = a_scene(tmp_db, title="Second")
    preprod.set_picked(cid2, True, dsn=tmp_db, account_id=None)
    out = rq.import_clip(cid2, 1, str(a_clip(tmp_path)), "seedance1_5", 4.8, None, True)
    assert out["media_url"] == "/renders/higgsfield/clip-1.mp4"


def test_the_attempt_is_logged_in_credits_not_invented_dollars(tmp_db, tmp_path):
    """The clip came out of a subscription already paid for. A cost_usd
    here would be a number nobody spent."""
    cid = a_scene(tmp_db)
    preprod.set_picked(cid, True, dsn=tmp_db, account_id=None)
    rq.import_clip(cid, 1, str(a_clip(tmp_path)), "seedance1_5", 4.8, None, True)
    with generative.connect(tmp_db) as conn:
        row = conn.execute("SELECT tool, cost_usd, params_json FROM generations "
                           "ORDER BY id DESC LIMIT 1").fetchone()
    assert row["tool"] == "higgsfield"
    assert row["cost_usd"] is None
    params = json.loads(row["params_json"])
    assert params["credits"] == 4.8
    assert params["source"] == "mcp-subscription"
    assert params["model"] == "seedance1_5"


def test_importing_takes_the_scene_out_of_the_queue(tmp_db, tmp_path):
    cid = a_scene(tmp_db)
    preprod.set_picked(cid, True, dsn=tmp_db, account_id=None)
    assert len(rq.pending()) == 1
    rq.import_clip(cid, 1, str(a_clip(tmp_path)), "seedance1_5", 4.8, None, True)
    assert rq.pending() == []


def test_a_truncated_download_is_refused(tmp_db, tmp_path):
    """A 200-byte 'mp4' is a failed download, and logging it as a render
    would put a broken clip on the board with a row saying it worked."""
    cid = a_scene(tmp_db)
    preprod.set_picked(cid, True, dsn=tmp_db, account_id=None)
    with pytest.raises(SystemExit, match="not a video"):
        rq.import_clip(cid, 1, str(a_clip(tmp_path, size=200)), "seedance1_5",
                       4.8, None, True)


def test_an_unknown_concept_refuses(tmp_db, tmp_path):
    with pytest.raises(SystemExit, match="no concept"):
        rq.import_clip(9999, 1, str(a_clip(tmp_path)), "seedance1_5", 4.8, None, True)


def test_the_anchor_is_recorded_as_what_was_actually_sent(tmp_db, tmp_path):
    cid = a_scene(tmp_db)
    preprod.set_picked(cid, True, dsn=tmp_db, account_id=None)
    rq.import_clip(cid, 1, str(a_clip(tmp_path)), "seedance1_5", 4.8, None, False)
    with generative.connect(tmp_db) as conn:
        params = json.loads(conn.execute(
            "SELECT params_json FROM generations ORDER BY id DESC LIMIT 1"
        ).fetchone()[0])
    assert params["prompt_image"] is False


# ---------- the stdlib-only contract ----------

def test_render_queue_imports_without_third_party_packages():
    """It runs under a Claude session's plain python3 -- the repo venvs
    are macOS builds and that shell is Linux. One boto3 import here and
    the whole subscription path stops working."""
    import ast
    import pathlib

    source = pathlib.Path(rq.__file__).with_suffix(".py").read_text()
    tree = ast.parse(source)
    allowed = {"argparse", "json", "sqlite3", "sys", "pathlib", "src", "ops",
               "__future__"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] in allowed, alias.name
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            assert node.module.split(".")[0] in allowed, node.module
