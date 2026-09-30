"""ops/backfill_render_assets.py -- a clip filed before its Asset Bank row
existed gets that row, and nothing is guessed."""
import json

import pytest
from conftest import seed_two  # noqa: E402

from ops import backfill_render_assets as bf
from src import db, generative, preprod, render_assets
from src.cut import assemble


@pytest.fixture
def live(pg, monkeypatch):
    preprod.init(pg)
    generative.init(pg)
    render_assets.init(pg)
    seed_two("mike@example.com", dsn=pg)
    monkeypatch.setenv("DATABASE_URL", pg)
    # record() also files a RAG chunk; best-effort, and not what is under test
    monkeypatch.setattr(render_assets, "_ingest", lambda *a, **k: {"ok": False})
    with db.connect(pg) as conn:
        a = conn.execute("SELECT id FROM accounts WHERE slug='zeropage'").fetchone()["id"]
        b = conn.execute("SELECT id FROM accounts WHERE slug='antihero'").fetchone()["id"]
        shot = conn.execute("INSERT INTO shots (created_at, spec_json, subject, account_id) "
                            "VALUES ('t', '{}', 'x', %s) RETURNING id", (a,)).fetchone()["id"]
    return pg, a, b, shot


def _concept(conn, account, media_url, title="Neon City Ascent"):
    return conn.execute(
        "INSERT INTO shoot_concepts (created_at, brand, title, shots_json, account_id) "
        "VALUES ('t', 'zeropage', %s, %s, %s) RETURNING id",
        (title, json.dumps([{"n": 1, "media_url": media_url}]), account)).fetchone()["id"]


def _gen(conn, account, shot, path, concept_id):
    return conn.execute(
        "INSERT INTO generations (shot_id, created_at, tool, attempt, prompt, params_json, "
        "output_path, kept, account_id) VALUES (%s, 't', 'runway', 1, 'the prompt', %s, %s, 1, %s) "
        "RETURNING id",
        (shot, json.dumps({"model": "gen4_turbo", "concept_id": concept_id}), path,
         account)).fetchone()["id"]


def test_a_clip_filed_before_its_row_existed_gets_one_and_becomes_cuttable(live):
    pg, a, _, shot = live
    with db.connect(pg) as conn:
        cid = _concept(conn, a, "/renders/runway/concept375-shot1.mp4")
        gid = _gen(conn, a, shot, "/app/data/renders/runway/concept375-shot1.mp4", cid)
    assert assemble.plan(cid, account_id=a, dsn=pg)["missing"]
    items = bf.plan(pg)
    assert [(i["concept_id"], i["generation"]["id"]) for i in items] == [(cid, gid)]
    asset_id = bf.write(items[0], pg)
    row = render_assets.get(asset_id, pg, account_id=a)
    assert (row["generation_id"], row["model"], row["concept_id"], row["shot_n"]) == (gid, "gen4_turbo", cid, 1)
    assert row["metadata"]["backfilled"]
    planned = assemble.plan(cid, account_id=a, dsn=pg)
    assert planned["missing"] == [] and planned["clips"][0]["handle"] == f"gen:{asset_id}"
    assert bf.plan(pg) == []                       # idempotent: nothing left to do


def test_no_row_two_rows_or_another_concepts_row_is_left_alone(live):
    pg, a, b, shot = live
    with db.connect(pg) as conn:
        none = _concept(conn, a, "/renders/runway/orphan.mp4", "orphan")
        twice = _concept(conn, a, "/renders/runway/twice.mp4", "twice")
        _gen(conn, a, shot, "/x/twice.mp4", twice)
        _gen(conn, a, shot, "/y/twice.mp4", twice)
        other = _concept(conn, a, "/renders/runway/theirs.mp4", "theirs")
        _gen(conn, a, shot, "/x/theirs.mp4", other + 1000)     # names a different concept
        foreign = _concept(conn, b, "/renders/runway/b.mp4", "b's")
        _gen(conn, a, shot, "/x/b.mp4", foreign)               # right file, wrong account
    skips = {i["concept_id"]: i.get("skip") for i in bf.plan(pg)}
    assert skips == {none: "no generations row names this file",
                     twice: "2 generations rows name this file",
                     other: "no generations row names this file",
                     foreign: "no generations row names this file"}
