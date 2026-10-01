"""The editor's server half (phase B of docs/CUT_EDITOR.md): projects,
the ops route, undo/redo, the bin, uploads, previews and export -- through
/api/cut, the way the React editor reaches them.

Most of it needs no ffmpeg: the media a timeline is checked against is
MEASURED ONCE and cached (cut_media_cache), so a test seeds the cache and
nothing is probed. The tests that do run ffmpeg (uploads, a real preview
build, a real export with a still in it) skip on a machine without it.
Nothing here spends: no model call, no ledger hold.
"""
import json
import shutil
import subprocess
import time

import pytest
from conftest import seed_two  # noqa: E402

from src import db, preprod, render_assets
from src.cut import doc as d
from src.cut import ops, preview, sources, store

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg/ffprobe not installed")


def _ff(*args):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


# --------------------------------------------------------------------------
# a database with renders on it, measured already
# --------------------------------------------------------------------------

def _bank(conn, n, account_id, kind="video", url=None, deleted=False, output_path=None):
    url = url or f"/renders/runway/clip{n}.mp4"
    row = conn.execute(
        "INSERT INTO generated_assets (created_at, generation_id, tool, model, media_kind, "
        "prompt, media_url, output_path, account_id, deleted_at) "
        "VALUES (%s, %s, 'runway', 'gen4_turbo', %s, 'a prompt', %s, %s, %s, %s) RETURNING id",
        (f"2026-09-{10 + n:02d}T00:00:00+00:00", n, kind, url, output_path, account_id,
         "t" if deleted else None)).fetchone()
    return f"gen:{row['id']}", url


def _measured(dsn, handle, url, account_id, seconds, video=True, audio=True, still=False,
              w=720, h=1280):
    store.put_probe(handle, url, {"seconds": seconds, "video": video, "audio": audio,
                                  "still": still, "width": w, "height": h},
                    account_id=account_id, size_bytes=1234, dsn=dsn)


@pytest.fixture
def world(pg):
    preprod.init(pg)
    render_assets.init(pg)
    store.init(pg)
    seed_two("mike@example.com", dsn=pg)
    with db.connect(pg) as conn:
        a = conn.execute("SELECT id FROM accounts WHERE slug='zeropage'").fetchone()["id"]
        b = conn.execute("SELECT id FROM accounts WHERE slug='antihero'").fetchone()["id"]
        g1, u1 = _bank(conn, 1, a)
        g2, u2 = _bank(conn, 2, a)
        g3, u3 = _bank(conn, 3, a, kind="image", url="/renders/nano/still3.png")
        g4, _ = _bank(conn, 4, a, deleted=True)
        g5, u5 = _bank(conn, 5, a)                     # never measured, file nowhere
        gb, ub = _bank(conn, 6, b)                     # the other account's render
    _measured(pg, g1, u1, a, 5.0)
    _measured(pg, g2, u2, a, 4.0)
    _measured(pg, g3, u3, a, 600, audio=False, still=True, w=800, h=600)
    _measured(pg, gb, ub, b, 5.0)
    bed = store.add_media(account_id=a, kind="audio", filename="bed.m4a",
                          media_url="/renders/cut/media/bed.m4a", output_path=None,
                          seconds=30, sha256=None, dsn=pg)
    music = f"asset:{bed['id']}"
    _measured(pg, music, bed["media_url"], a, 30.0, video=False)
    return {"dsn": pg, "a": a, "b": b, "g1": g1, "g2": g2, "g3": g3, "g4": g4, "g5": g5,
            "gb": gb, "music": music}


@pytest.fixture
def api(world, monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    import app.main as app_main
    from app import auth

    monkeypatch.setenv("DATABASE_URL", world["dsn"])
    monkeypatch.setattr(auth, "current_user",
                        lambda request: {"id": "u1", "email": "x@example.com"})
    monkeypatch.setattr(preview, "PREVIEW_DIR", tmp_path / "preview")
    import app.cut_routes as cut_routes
    monkeypatch.setattr(cut_routes, "MEDIA_DIR", tmp_path / "media")
    app_main.app.dependency_overrides[auth.current_account_id] = lambda: world["a"]
    yield TestClient(app_main.app), world
    app_main.app.dependency_overrides[auth.current_account_id] = lambda: None


def _as(account_id):
    import app.main as app_main
    from app import auth
    app_main.app.dependency_overrides[auth.current_account_id] = lambda: account_id


def _wait(client, job_id, timeout=60):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] not in ("queued", "running"):
            return job
        time.sleep(0.1)
    raise AssertionError(f"job {job_id} still running")


def _new(client, **body):
    res = client.post("/api/cut/projects", json=body)
    assert res.status_code == 200, res.text
    return res.json()["project"]


def _open(client, pid):
    res = client.get(f"/api/cut/projects/{pid}")
    assert res.status_code == 200, res.text
    return res.json()


def _op(client, pid, base, op, **args):
    return client.post(f"/api/cut/projects/{pid}/ops", json={"base_id": base, "op": op,
                                                             "args": args})


def _ok(res):
    assert res.status_code == 200, res.text
    return res.json()


P_KEYS = {"id", "title", "timeline_key", "concept_id", "fps", "size", "aspect", "duration",
          "version", "poster", "export_url", "created_at", "updated_at"}
H_KEYS = {"id", "version", "parent_id", "author", "op_summary", "created_at", "export_url", "doc"}


# --------------------------------------------------------------------------
# projects
# --------------------------------------------------------------------------

def test_a_scratch_project_is_a_blank_starter_cut(api):
    client, w = api
    p = _new(client, title="Night run", aspect="9:16")
    assert set(p) == P_KEYS
    assert p["timeline_key"] == f"cut:{p['id']}" and p["concept_id"] is None
    assert (p["size"], p["aspect"], p["fps"], p["duration"], p["version"]) == (
        [720, 1280], "9:16", 30, 0, 1)
    assert p["poster"] is None and p["export_url"] is None

    got = _open(client, p["id"])
    assert set(got) == {"project", "head", "versions", "can_undo", "can_redo", "media"}
    assert set(got["head"]) == H_KEYS
    assert (got["head"]["author"], got["head"]["op_summary"]) == ("user", "new project")
    assert [(t["id"], t["kind"], t.get("role")) for t in got["head"]["doc"]["tracks"]] == [
        ("V1", "video", None), ("A1", "audio", "sfx"), ("A2", "audio", "music")]
    assert "duck_under" not in got["head"]["doc"]["tracks"][2]
    assert got["versions"] == [{k: got["head"][k] for k in H_KEYS - {"doc"}}]
    assert (got["can_undo"], got["can_redo"], got["media"]) == (False, False, {})


@pytest.mark.parametrize("aspect,size", [("16:9", [1280, 720]), ("1:1", [1080, 1080])])
def test_the_canvas_follows_the_aspect(api, aspect, size):
    client, _ = api
    p = _new(client, aspect=aspect)
    assert p["size"] == size and p["aspect"] == aspect
    assert client.post("/api/cut/projects", json={"aspect": "4:3"}).status_code == 422


def test_the_list_is_newest_edited_first_and_rename_and_delete_work(api):
    client, w = api
    first = _new(client, title="First")
    second = _new(client, title="Second")
    head = _open(client, first["id"])["head"]
    time.sleep(1.1)                                   # updated_at has 1s resolution
    _ok(_op(client, first["id"], head["id"], "add_marker", frame=0, label="go"))
    listed = client.get("/api/cut/projects").json()["projects"]
    assert [p["id"] for p in listed] == [first["id"], second["id"]]
    assert all(set(p) == P_KEYS for p in listed) and listed[0]["version"] == 2

    renamed = _ok(client.patch(f"/api/cut/projects/{second['id']}", json={"title": "Better"}))
    assert renamed["project"]["title"] == "Better"
    assert _ok(client.delete(f"/api/cut/projects/{second['id']}")) == {"ok": True}
    assert [p["id"] for p in client.get("/api/cut/projects").json()["projects"]] == [first["id"]]
    assert client.get(f"/api/cut/projects/{second['id']}").status_code == 404
    assert client.delete(f"/api/cut/projects/{second['id']}").status_code == 404
    # soft: the versions are still there
    assert store.history(second["timeline_key"], account_id=w["a"], dsn=w["dsn"])


def test_the_card_poster_is_the_first_picture(api):
    client, w = api
    p = _new(client)
    head = _open(client, p["id"])["head"]
    _ok(_op(client, p["id"], head["id"], "insert", track_id="V1",
            clip={"media": w["g3"], "src_in": 0, "src_out": 60}))
    card = client.get("/api/cut/projects").json()["projects"][0]
    assert card["poster"] == "/renders/nano/still3.png" and card["duration"] == 60


# --------------------------------------------------------------------------
# a concept's cut (D2)
# --------------------------------------------------------------------------

def _concept(dsn, account_id, shots, title="Neon City Ascent"):
    with db.connect(dsn) as conn:
        return conn.execute(
            "INSERT INTO shoot_concepts (created_at, brand, title, shots_json, account_id) "
            "VALUES ('t', 'zeropage', %s, %s, %s) RETURNING id",
            (title, json.dumps(shots), account_id)).fetchone()["id"]


def test_a_concept_project_is_assembled_from_the_cached_probes_without_rendering(api):
    client, w = api
    shot = {"n": 1, "timeline": {"parts": [{"n": 1, "media_url": "/renders/runway/clip1.mp4"},
                                           {"n": 2, "media_url": "/renders/runway/clip2.mp4"}]}}
    cid = _concept(w["dsn"], w["a"], [shot])
    p = _new(client, concept_id=cid)
    assert p["timeline_key"] == f"concept:{cid}" and p["concept_id"] == cid
    assert p["title"] == "Neon City Ascent" and p["duration"] == 270
    got = _open(client, p["id"])
    assert (got["head"]["author"], got["head"]["op_summary"]) == ("assemble", "assembled 2 clip(s)")
    assert [c["media"] for c in d.track(got["head"]["doc"], "V1")["clips"]] == [w["g1"], w["g2"]]
    assert d.track(got["head"]["doc"], "A2")["clips"] == []
    assert got["media"][w["g1"]] == {"frames": 150, "video": True, "audio": True, "seconds": 5.0}
    # create-or-return: the same project, not a second one
    assert _new(client, concept_id=cid)["id"] == p["id"]
    assert len(client.get("/api/cut/projects").json()["projects"]) == 1


def test_a_concept_with_a_cut_already_reuses_its_history(api):
    client, w = api
    cid = _concept(w["dsn"], w["a"], [{"n": 1, "media_url": "/renders/runway/clip1.mp4"}])
    doc = d.starter_doc()
    doc = ops.insert(doc, "V1", {"media": w["g2"], "src_in": 0, "src_out": 30})
    v1 = store.save_version(f"concept:{cid}", doc, account_id=w["a"], author="assemble",
                            op_summary="assembled 1 clip(s)", dsn=w["dsn"])
    p = _new(client, concept_id=cid)
    got = _open(client, p["id"])
    assert got["head"]["id"] == v1["id"] and len(got["versions"]) == 1
    # the Export button's own route sees the editor's edits: one history
    _ok(_op(client, p["id"], v1["id"], "add_marker", frame=0, label="x"))
    assert client.get(f"/api/cut/{cid}/timeline").json()["head"]["version"] == 2


def test_a_half_rendered_concept_opens_on_an_empty_timeline(api):
    client, w = api
    shot = {"n": 1, "timeline": {"parts": [{"n": 1, "media_url": "/renders/runway/clip1.mp4"},
                                           {"n": 2, "media_url": None}]}}
    p = _new(client, concept_id=_concept(w["dsn"], w["a"], [shot]))
    got = _open(client, p["id"])
    assert got["head"]["op_summary"] == "new project" and got["head"]["doc"]["duration"] == 0


def test_a_concept_that_is_not_yours_is_not_found(api):
    client, w = api
    theirs = _concept(w["dsn"], w["b"], [{"n": 1}])
    res = client.post("/api/cut/projects", json={"concept_id": theirs})
    assert res.status_code == 404 and res.json()["error"]["code"] == "not_found"
    assert client.post("/api/cut/projects", json={"concept_id": 999999}).status_code == 404


# --------------------------------------------------------------------------
# the ops route: every op, the refusals
# --------------------------------------------------------------------------

def test_every_op_is_reachable_through_the_route(api):
    client, w = api
    p = _new(client)
    pid = p["id"]
    base = _open(client, pid)["head"]["id"]
    used = []

    def step(op, **args):
        nonlocal base
        body = _ok(_op(client, pid, base, op, **args))
        assert set(body) == {"head", "can_undo", "can_redo", "media"}
        assert body["head"]["parent_id"] == base and body["head"]["author"] == "user"
        assert body["head"]["op_summary"] == ops.describe(op, args, 30)
        assert body["can_undo"] is True and body["can_redo"] is False
        base = body["head"]["id"]
        used.append(op)
        return body["head"]["doc"]

    doc = step("insert", track_id="V1", clip={"media": w["g1"], "src_in": 0, "src_out": 150},
               sound_track="A1")
    step("insert", track_id="V1", clip={"media": w["g2"], "src_in": 0, "src_out": 120},
         sound_track="A1")
    doc = step("insert", track_id="A2", clip={"media": w["music"], "src_in": 0, "src_out": 270},
               at=0, ripple=False)
    c1, c2 = [c["id"] for c in d.track(doc, "V1")["clips"]]
    doc = step("split", clip_id=c1, frame=60)
    tail = [c for c in d.track(doc, "V1")["clips"] if c["at"] == 60][0]["id"]
    step("trim", clip_id=tail, tail=10, ripple=True)
    step("add_transition", clip_id=c2, frames=6)
    step("set_transition", clip_id=c2, style="slideup", frames=8)
    step("remove_transition", clip_id=c2)
    step("add_transition", clip_id=c2, frames=6, style="circleopen")
    step("move", clip_id=c1, at=0)
    sfx = d.track(doc, "A1")["clips"][0]["id"]
    step("set_gain", clip_id=sfx, db=-3)
    step("set_fade", clip_id=sfx, fade_in=10, fade_out=10)
    step("set_key", clip_id=sfx, path="volume", frame=0, value=-6)
    step("set_track_mix", track_id="A1", gain_db=-2, pan=0.25)
    step("duck", track_id="A2", under="sfx")
    doc = step("add_caption_track", cues=[])
    step("set_cue", track_id="T1", start=0, end=30, text="first")
    doc = step("set_cue", track_id="T1", start=0, end=45, text="first, longer", cue_id="q1")
    assert d.track(doc, "T1")["cues"][0]["end"] == 45
    step("set_cue", track_id="T1", start=60, end=90, text="second")
    step("delete_cue", track_id="T1", cue_id="q1")
    step("set_caption_style", track_id="T1", style="preset:lower_third")
    step("add_marker", frame=30, label="beat")
    step("set_marker", frame=30, label="the beat", to=36)
    step("add_marker", frame=40, label="gone")
    step("delete_marker", frame=40)
    step("lift", clip_id=tail)
    step("ripple_delete", clip_id=c2)
    doc = step("overwrite", track_id="V1", clip={"media": w["g1"], "src_in": 0, "src_out": 30},
               at=0, sound_track="A1")
    assert d.track(doc, "V1")["clips"][0]["src_out"] == 30
    pic = d.track(doc, "V1")["clips"][0]["id"]
    step("set_key", clip_id=pic, path="zoom", frame=0, value=1.2)
    step("set_key", clip_id=pic, path="zoom", frame=20, value=1.4, ease="ease")
    step("delete_key", clip_id=pic, path="zoom", frame=20)
    step("clear_lane", clip_id=pic, path="zoom")
    step("set_crop", clip_id=pic, left=0.1, right=0.05)
    doc = step("set_opacity", clip_id=pic, value=0.6)
    step("set_grade", clip_id=pic, exposure=0.5, temperature=-0.3)
    doc = step("set_speed", clip_id=pic, speed=2)
    doc = step("set_reverse", clip_id=pic, on=True)
    assert d.track(doc, "V1")["clips"][0]["opacity"] == 0.6
    doc = step("set_canvas", width=1080, height=1080)
    assert doc["size"] == [1080, 1080]
    doc = step("add_track", kind="audio", role="voice")
    assert d.track(doc, "A3")["role"] == "voice"
    assert set(used) == set(ops.OPS), set(ops.OPS) - set(used)
    got = _open(client, pid)
    assert got["project"]["aspect"] == "1:1"
    assert set(got["media"]) == {w["g1"], w["music"]}


def test_a_stale_base_is_409_with_the_head_to_refetch(api):
    client, _ = api
    p = _new(client)
    base = _open(client, p["id"])["head"]["id"]
    head = _ok(_op(client, p["id"], base, "add_marker", frame=0, label="a"))["head"]
    res = _op(client, p["id"], base, "add_marker", frame=0, label="b")
    assert res.status_code == 409
    err = res.json()["error"]
    assert err["code"] == "stale" and err["head_id"] == head["id"] and err["message"]


def test_a_bad_op_is_422_with_every_problem(api):
    client, w = api
    p = _new(client)
    base = _open(client, p["id"])["head"]["id"]
    res = _op(client, p["id"], base, "insert", track_id="V1",
              clip={"media": w["g1"], "src_in": 0, "src_out": 900})
    assert res.status_code == 422
    err = res.json()["error"]
    assert err["code"] == "invalid" and any("past the end" in x for x in err["problems"])
    res = _op(client, p["id"], base, "explode")
    assert res.status_code == 422 and "unknown op" in res.json()["error"]["message"]
    res = _op(client, p["id"], base, "split", clip_id="c9", frame=3)
    assert res.status_code == 422 and res.json()["error"]["problems"] == ["no clip c9"]
    res = _op(client, p["id"], base, "add_marker", frame=0)            # a missing argument
    assert res.status_code == 422
    # nothing was saved by any of them
    assert len(_open(client, p["id"])["versions"]) == 1


def test_an_insert_of_media_that_is_not_yours_or_cannot_be_read_is_refused(api):
    client, w = api
    p = _new(client)
    base = _open(client, p["id"])["head"]["id"]
    for handle, words in ((w["gb"], "unknown media handle"), ("gen:99999", "unknown media handle"),
                          (w["g5"], "could not read")):
        res = _op(client, p["id"], base, "insert", track_id="V1",
                  clip={"media": handle, "src_in": 0, "src_out": 30})
        assert res.status_code == 422, handle
        assert words in res.json()["error"]["problems"][0], handle
    res = _op(client, p["id"], base, "insert", track_id="V1",
              clip={"media": "https://example.com/x.mp4", "src_in": 0, "src_out": 30})
    assert res.status_code == 422


def test_a_clip_already_on_the_timeline_does_not_freeze_the_cut_when_its_file_goes_missing(api):
    client, w = api
    p = _new(client)
    base = _open(client, p["id"])["head"]["id"]
    base = _ok(_op(client, p["id"], base, "insert", track_id="V1",
                   clip={"media": w["g1"], "src_in": 0, "src_out": 60}))["head"]["id"]
    # the cache forgets it and its file is nowhere: unmeasured, not unknown
    with db.connect(w["dsn"]) as conn:
        conn.execute("DELETE FROM cut_media_cache WHERE handle = %s AND account_id = %s",
                     (w["g1"], w["a"]))
    body = _ok(_op(client, p["id"], base, "add_marker", frame=10, label="still editable"))
    assert w["g1"] not in body["media"]


def test_a_repointed_render_is_measured_again_not_trusted(api, monkeypatch):
    client, w = api
    calls = []
    monkeypatch.setattr(sources, "probe", lambda path, fps: calls.append(path) or {
        "frames": 60, "seconds": 2.0, "video": True, "audio": False, "still": False,
        "width": 720, "height": 1280})
    def fetched(h, row, a, wd):
        (wd / "x.mp4").write_bytes(b"x")
        return wd / "x.mp4"

    monkeypatch.setattr(sources, "file_for", fetched)
    got = sources.measure([w["g1"]], account_id=w["a"], fps=30, dsn=w["dsn"])
    assert got[w["g1"]]["frames"] == 150 and calls == []           # a cache hit
    with db.connect(w["dsn"]) as conn:
        conn.execute("UPDATE generated_assets SET media_url = '/renders/runway/new.mp4' "
                     "WHERE id = %s AND account_id = %s", (int(w["g1"][4:]), w["a"]))
    got = sources.measure([w["g1"]], account_id=w["a"], fps=30, dsn=w["dsn"])
    assert got[w["g1"]]["frames"] == 60 and len(calls) == 1
    assert sources.measure([w["g1"]], account_id=w["a"], fps=24, dsn=w["dsn"])[w["g1"]][
        "frames"] == 48                                            # cached seconds, any fps


# --------------------------------------------------------------------------
# undo / redo / rollback
# --------------------------------------------------------------------------

def test_undo_and_redo_walk_the_chain_both_ways(api):
    client, _ = api
    p = _new(client)
    pid = p["id"]
    v1 = _open(client, pid)["head"]["id"]
    v2 = _ok(_op(client, pid, v1, "add_marker", frame=0, label="a"))["head"]["id"]
    v3 = _ok(_op(client, pid, v2, "add_marker", frame=0, label="b"))["head"]["id"]

    body = _ok(client.post(f"/api/cut/projects/{pid}/undo"))
    assert set(body) == {"head", "can_undo", "can_redo", "media"}
    assert (body["head"]["id"], body["can_undo"], body["can_redo"]) == (v2, True, True)
    body = _ok(client.post(f"/api/cut/projects/{pid}/undo"))
    assert (body["head"]["id"], body["can_undo"], body["can_redo"]) == (v1, False, True)
    res = client.post(f"/api/cut/projects/{pid}/undo")
    assert res.status_code == 409 and res.json()["error"]["code"] == "nothing_to_undo"

    assert _ok(client.post(f"/api/cut/projects/{pid}/redo"))["head"]["id"] == v2
    body = _ok(client.post(f"/api/cut/projects/{pid}/redo"))
    assert (body["head"]["id"], body["can_redo"]) == (v3, False)
    res = client.post(f"/api/cut/projects/{pid}/redo")
    assert res.status_code == 409 and res.json()["error"]["code"] == "nothing_to_redo"
    # undo, then a new edit: the old future is gone from redo (not from history)
    _ok(client.post(f"/api/cut/projects/{pid}/undo"))
    v4 = _ok(_op(client, pid, v2, "add_marker", frame=0, label="c"))
    assert v4["can_redo"] is False and v4["head"]["parent_id"] == v2
    assert client.post(f"/api/cut/projects/{pid}/redo").status_code == 409
    assert len(_open(client, pid)["versions"]) == 4


def test_rollback_puts_any_version_on_top_and_clears_redo(api):
    client, _ = api
    p = _new(client)
    pid = p["id"]
    v1 = _open(client, pid)["head"]["id"]
    v2 = _ok(_op(client, pid, v1, "add_marker", frame=0, label="a"))["head"]["id"]
    _ok(client.post(f"/api/cut/projects/{pid}/undo"))
    body = _ok(client.post(f"/api/cut/projects/{pid}/rollback", json={"timeline_id": v2}))
    assert body["head"]["id"] == v2 and body["can_redo"] is False
    assert set(body) == {"head", "can_undo", "can_redo", "media"}
    other = _new(client)
    other_v = _open(client, other["id"])["head"]["id"]
    res = client.post(f"/api/cut/projects/{pid}/rollback", json={"timeline_id": other_v})
    assert res.status_code == 404


# --------------------------------------------------------------------------
# the bin
# --------------------------------------------------------------------------

M_KEYS = {"handle", "kind", "name", "seconds", "width", "height", "has_video", "has_audio",
          "size_bytes", "url", "poster", "created_at", "source"}


def test_the_bin_lists_renders_and_uploads_and_nothing_deleted_or_foreign(api):
    client, w = api
    p = _new(client)
    items = _ok(client.get(f"/api/cut/projects/{p['id']}/media"))["items"]
    assert all(set(i) == M_KEYS for i in items)
    by = {i["handle"]: i for i in items}
    assert set(by) == {w["g1"], w["g2"], w["g3"], w["g5"], w["music"]}
    expected = {"kind": "video", "seconds": 5.0, "width": 720, "height": 1280,
                "has_video": True, "has_audio": True, "size_bytes": 1234,
                "url": "/renders/runway/clip1.mp4", "source": "render"}
    assert {k: by[w["g1"]][k] for k in expected} == expected
    assert by[w["g3"]]["kind"] == "image" and by[w["g3"]]["seconds"] is None
    assert by[w["g3"]]["poster"] == by[w["g3"]]["url"] and by[w["g3"]]["has_audio"] is False
    assert by[w["g5"]]["seconds"] is None and by[w["g5"]]["has_audio"] is None  # not measured yet
    assert by[w["music"]]["source"] == "upload" and by[w["music"]]["kind"] == "audio"
    assert (by[w["music"]]["has_video"], by[w["music"]]["has_audio"]) == (False, True)
    assert by[w["music"]]["name"] == "bed.m4a" and by[w["music"]]["poster"] is None
    assert "#" in by[w["g1"]]["name"]
    stamps = [i["created_at"] for i in items]
    assert stamps == sorted(stamps, reverse=True)


# --------------------------------------------------------------------------
# tenancy
# --------------------------------------------------------------------------

def test_another_accounts_project_and_media_answer_like_missing_ones(api):
    client, w = api
    p = _new(client)
    base = _open(client, p["id"])["head"]["id"]
    _as(w["b"])
    pid = p["id"]
    for method, path, body in (
            ("get", f"/api/cut/projects/{pid}", None),
            ("patch", f"/api/cut/projects/{pid}", {"title": "mine now"}),
            ("delete", f"/api/cut/projects/{pid}", None),
            ("post", f"/api/cut/projects/{pid}/ops",
             {"base_id": base, "op": "add_marker", "args": {"frame": 0, "label": "x"}}),
            ("post", f"/api/cut/projects/{pid}/undo", None),
            ("post", f"/api/cut/projects/{pid}/redo", None),
            ("post", f"/api/cut/projects/{pid}/rollback", {"timeline_id": base}),
            ("get", f"/api/cut/projects/{pid}/media", None),
            ("post", f"/api/cut/projects/{pid}/export", {}),
            ("get", f"/api/cut/projects/{pid}/exports", None),
            ("get", f"/api/cut/media/{w['g1']}/preview", None),
            ("get", "/api/cut/projects/not-a-uuid", None)):
        kwargs = {"json": body} if body is not None else {}
        res = getattr(client, method)(path, **kwargs)
        assert res.status_code == 404, (method, path, res.text)
        assert res.json()["error"]["code"] == "not_found"
    assert client.get("/api/cut/projects").json()["projects"] == []
    theirs = _new(client)
    items = client.get(f"/api/cut/projects/{theirs['id']}/media").json()["items"]
    assert [i["handle"] for i in items] == [w["gb"]]
    _as(w["a"])
    assert _open(client, pid)["head"]["id"] == base            # untouched by any of it


# --------------------------------------------------------------------------
# previews through the route
# --------------------------------------------------------------------------

def test_the_preview_is_unavailable_without_ffmpeg(api, monkeypatch):
    client, w = api
    monkeypatch.setattr(sources, "ffmpeg_bin", lambda: None)
    body = _ok(client.get(f"/api/cut/media/{w['g1']}/preview"))
    assert body["status"] == "unavailable" and body["proxy"] is None and body["note"]
    assert client.get("/api/cut/media/not-a-handle/preview").status_code == 404


def test_a_preview_build_is_claimed_once_and_a_failure_says_why(api, monkeypatch):
    client, w = api
    started = []
    import app.cut_routes as cut_routes
    monkeypatch.setattr(cut_routes.jobs, "start",
                        lambda kind, label, fn, **kw: started.append(label) or {"id": 1})
    body = _ok(client.get(f"/api/cut/media/{w['g1']}/preview"))
    assert body == {"status": "pending", "proxy": None, "filmstrip": None, "waveform": None}
    _ok(client.get(f"/api/cut/media/{w['g1']}/preview"))
    assert len(started) == 1                                   # the second poll did not rebuild
    # the build runs (for real, on a file that is not there) and fails with its reason
    out = preview.ensure(w["g1"], account_id=w["a"], dsn=w["dsn"])
    assert out["status"] == "failed"
    body = _ok(client.get(f"/api/cut/media/{w['g1']}/preview"))
    assert body["status"] == "failed" and "not on this machine" in body["note"]
    _ok(client.get(f"/api/cut/media/{w['g1']}/preview"))
    assert len(started) == 1                                   # failed is not retried by a poll


def test_a_ready_preview_is_minted_and_reused_for_the_same_bytes(api):
    client, w = api
    strip = {"url": "/renders/cut/preview/abc/filmstrip.jpg", "frame_width": 50,
             "frame_height": 90, "count": 5, "interval": 1}
    store.claim_preview(w["g2"], "/renders/runway/clip2.mp4", account_id=w["a"],
                        stale_before="0", dsn=w["dsn"])
    store.set_preview(w["g2"], account_id=w["a"], status="ready", sha256="f" * 64,
                      proxy_url="/renders/cut/preview/abc/proxy.mp4", filmstrip=strip,
                      waveform={"url": "/renders/cut/preview/abc/waveform.json",
                                "per_second": 50}, dsn=w["dsn"])
    body = _ok(client.get(f"/api/cut/media/{w['g2']}/preview"))
    assert body == {"status": "ready", "proxy": "/renders/cut/preview/abc/proxy.mp4",
                    "filmstrip": strip, "waveform": {"url": "/renders/cut/preview/abc/waveform.json",
                                                     "per_second": 50}}
    twin = store.preview_by_sha("f" * 64, account_id=w["a"], dsn=w["dsn"])
    assert twin["handle"] == w["g2"]
    assert store.preview_by_sha("f" * 64, account_id=w["b"], dsn=w["dsn"]) is None


# --------------------------------------------------------------------------
# uploads (ffmpeg)
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def files(tmp_path_factory):
    if not HAS_FFMPEG:
        pytest.skip("ffmpeg/ffprobe not installed")
    root = tmp_path_factory.mktemp("uploads")
    enc = ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast"]
    _ff("-f", "lavfi", "-i", "testsrc2=s=720x1280:r=30:d=3", "-f", "lavfi",
        "-i", "sine=f=440:d=3", "-shortest", *enc, "-c:a", "aac", str(root / "clip.mp4"))
    _ff("-f", "lavfi", "-i", "testsrc=s=640x480:d=1", "-frames:v", "1", str(root / "still.jpg"))
    _ff("-f", "lavfi", "-i", "sine=f=220:d=2", "-c:a", "aac", str(root / "vo.m4a"))
    _ff("-f", "lavfi", "-i", "sine=f=220:d=2", "-c:a", "aac", str(root / "sound_only.mp4"))
    return root


def _upload(client, path, name=None):
    with open(path, "rb") as fh:
        return client.post("/api/cut/media", files={"file": (name or path.name, fh)})


def _wait_preview(client, handle, timeout=60):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        body = client.get(f"/api/cut/media/{handle}/preview").json()
        if body["status"] != "pending":
            return body
        time.sleep(0.2)
    raise AssertionError(f"{handle} preview still pending")


@needs_ffmpeg
def test_uploading_footage_gives_a_handle_an_item_and_previews(api, files):
    client, w = api
    body = _ok(_upload(client, files / "clip.mp4"))
    assert body["kind"] == "video" and body["handle"].startswith("asset:")
    assert body["seconds"] == pytest.approx(3, abs=0.1) and body["filename"] == "clip.mp4"
    item = body["item"]
    assert set(item) == M_KEYS and item["handle"] == body["handle"]
    assert (item["has_video"], item["has_audio"], item["source"]) == (True, True, "upload")
    assert (item["width"], item["height"]) == (720, 1280) and item["size_bytes"] > 0

    pv = _wait_preview(client, body["handle"])
    assert pv["status"] == "ready", pv
    assert pv["proxy"].startswith("/renders/cut/preview/") and pv["proxy"].endswith("proxy.mp4")
    assert pv["filmstrip"]["count"] == 3 and pv["filmstrip"]["frame_height"] == 90
    assert pv["waveform"]["per_second"] == 50
    # it is in the bin, and it can go straight onto a timeline -- measured at upload
    p = _new(client)
    listed = client.get(f"/api/cut/projects/{p['id']}/media").json()["items"]
    tile = next(i for i in listed if i["handle"] == body["handle"])
    assert tile["poster"] and tile["poster"].endswith("poster.jpg")
    base = _open(client, p["id"])["head"]["id"]
    _ok(_op(client, p["id"], base, "insert", track_id="V1",
            clip={"media": body["handle"], "src_in": 0, "src_out": 90}, sound_track="A1"))


@needs_ffmpeg
def test_uploading_a_still_and_a_voiceover(api, files):
    client, w = api
    still = _ok(_upload(client, files / "still.jpg"))
    assert still["kind"] == "image" and still["seconds"] is None
    assert (still["item"]["has_video"], still["item"]["has_audio"]) == (True, False)
    pv = _wait_preview(client, still["handle"])
    assert pv["status"] == "ready" and pv["proxy"] is None and pv["waveform"] is None
    assert pv["filmstrip"]["count"] == 1

    vo = _ok(_upload(client, files / "vo.m4a"))
    assert vo["kind"] == "audio" and vo["seconds"] == pytest.approx(2, abs=0.1)
    pv = _wait_preview(client, vo["handle"])
    assert pv["status"] == "ready" and pv["proxy"] is None and pv["filmstrip"] is None
    assert pv["waveform"]["per_second"] == 50

    # a still holds for as long as the cut needs: 20s of it is fine
    p = _new(client)
    base = _open(client, p["id"])["head"]["id"]
    body = _ok(_op(client, p["id"], base, "insert", track_id="V1",
                   clip={"media": still["handle"], "src_in": 0, "src_out": 600}))
    assert body["media"][still["handle"]]["frames"] == d.STILL_SECONDS * 30


@needs_ffmpeg
def test_an_upload_that_is_not_what_its_name_says_is_refused(api, files):
    client, _ = api
    res = _upload(client, files / "sound_only.mp4")
    assert res.status_code == 400 and res.json()["error"]["code"] == "no_video"
    res = _upload(client, files / "clip.mp4", name="clip.jpg")
    assert res.status_code == 400 and res.json()["error"]["code"] == "not_an_image"
    res = client.post("/api/cut/media", files={"file": ("x.mov", b"garbage")})
    assert res.status_code == 400 and res.json()["error"]["code"] == "unreadable"


# --------------------------------------------------------------------------
# export
# --------------------------------------------------------------------------

def test_export_renders_a_version_in_a_job_and_lists_it(api, monkeypatch):
    client, w = api
    import app.cut_routes as cut_routes
    rendered = []

    def fake_render(doc, *, account_id, name, paths, media, fmt="mp4", frame=0):
        rendered.append((doc["size"], name))
        return {"stored": f"/renders/cut/{name}.mp4", "url": f"/renders/cut/{name}.mp4",
                "seconds": doc["duration"] / doc["fps"], "notes": [], "path": "x", "bytes": 1}

    monkeypatch.setattr(cut_routes.cut_render, "render", fake_render)
    monkeypatch.setattr(cut_routes.cut_sources, "gather", lambda *a, **k: ({}, {}))
    monkeypatch.setattr(cut_routes.cut_sources, "ffmpeg_bin", lambda: "/usr/bin/ffmpeg")
    p = _new(client)
    pid = p["id"]
    base = _open(client, pid)["head"]["id"]
    res = client.post(f"/api/cut/projects/{pid}/export", json={})
    assert res.status_code == 409 and res.json()["error"]["code"] == "empty"
    v2 = _ok(_op(client, pid, base, "insert", track_id="V1",
                 clip={"media": w["g1"], "src_in": 0, "src_out": 90}))["head"]

    out = _ok(client.post(f"/api/cut/projects/{pid}/export", json={}))
    assert set(out) == {"job_id", "timeline_id", "version"}
    assert (out["timeline_id"], out["version"]) == (v2["id"], 2)
    job = _wait(client, out["job_id"])
    assert job["status"] == "done", job
    assert (job["timeline_id"], job["version"], job["seconds"]) == (v2["id"], 2, 3.0)
    assert job["mp4_url"].endswith(f"-v2-{v2['id']}.mp4")

    # another aspect: a NEW user version (set_canvas) is what renders
    out = _ok(client.post(f"/api/cut/projects/{pid}/export", json={"aspect": "16:9"}))
    assert out["version"] == 3
    assert _wait(client, out["job_id"])["status"] == "done"
    got = _open(client, pid)
    assert got["head"]["id"] == out["timeline_id"] and got["head"]["doc"]["size"] == [1280, 720]
    assert got["head"]["op_summary"].startswith("canvas 1280x720") and rendered[-1][0] == [1280, 720]

    # an older version exports as itself, with no new version
    out = _ok(client.post(f"/api/cut/projects/{pid}/export", json={"timeline_id": v2["id"]}))
    assert out["version"] == 2
    _wait(client, out["job_id"])
    exports = _ok(client.get(f"/api/cut/projects/{pid}/exports"))["exports"]
    assert [e["version"] for e in exports] == [3, 2]
    assert set(exports[0]) == {"timeline_id", "version", "export_url", "created_at", "op_summary"}
    assert client.get("/api/cut/projects").json()["projects"][0]["export_url"] == \
        exports[0]["export_url"]

    other = _new(client)
    other_v = _open(client, other["id"])["head"]["id"]
    res = client.post(f"/api/cut/projects/{pid}/export", json={"timeline_id": other_v})
    assert res.status_code == 404
    assert client.post(f"/api/cut/projects/{pid}/export",
                       json={"aspect": "3:2"}).status_code == 422


@needs_ffmpeg
def test_a_real_export_holds_a_still_and_cuts_to_a_clip(api, files):
    client, w = api
    still = _ok(_upload(client, files / "still.jpg"))["handle"]
    clip = _ok(_upload(client, files / "clip.mp4"))["handle"]
    p = _new(client)
    pid = p["id"]
    base = _open(client, pid)["head"]["id"]
    base = _ok(_op(client, pid, base, "insert", track_id="V1",
                   clip={"media": still, "src_in": 0, "src_out": 45}))["head"]["id"]
    base = _ok(_op(client, pid, base, "insert", track_id="V1",
                   clip={"media": clip, "src_in": 0, "src_out": 60}, sound_track="A1"))["head"]["id"]
    base = _ok(_op(client, pid, base, "add_caption_track",
                   cues=[{"start": 0, "end": 40, "text": "a name"}],
                   style="preset:lower_third"))["head"]["id"]
    job = _wait(client, _ok(client.post(f"/api/cut/projects/{pid}/export", json={}))["job_id"],
                timeout=120)
    assert job["status"] == "done", job
    assert job["seconds"] == pytest.approx(3.5, abs=0.1)
    # let the upload's preview builds finish inside this test's database
    for handle in (still, clip):
        _wait_preview(client, handle)


def test_export_makes_the_sound_a_still_or_an_editable_project(api, monkeypatch, tmp_path):
    client, w = api
    import app.cut_routes as cut_routes
    calls = []

    def fake_render(doc, *, account_id, name, paths, media, fmt="mp4", frame=0):
        calls.append((fmt, frame, name))
        ext = {"audio": "m4a", "still": "png"}[fmt]
        return {"stored": f"/renders/cut/{name}.{ext}", "url": f"/renders/cut/{name}.{ext}",
                "seconds": 3.0, "notes": [], "path": "x", "bytes": 1}

    monkeypatch.setattr(cut_routes.cut_render, "render", fake_render)
    monkeypatch.setattr(cut_routes.cut_render, "CUT_DIR", tmp_path)
    monkeypatch.setattr(cut_routes.cut_sources, "gather", lambda *a, **k: ({}, {}))
    monkeypatch.setattr(cut_routes.cut_sources, "ffmpeg_bin", lambda: "/usr/bin/ffmpeg")
    import src.media as media_mod
    monkeypatch.setattr(media_mod, "mirror", lambda *a, **k: None)
    pid = _new(client)["id"]
    base = _open(client, pid)["head"]["id"]
    _ok(_op(client, pid, base, "insert", track_id="V1", sound_track="A1",
            clip={"media": w["g1"], "src_in": 0, "src_out": 90}))

    job = _wait(client, _ok(client.post(f"/api/cut/projects/{pid}/export", json={"format": "audio"}))["job_id"])
    assert job["format"] == "audio" and job["file_url"].endswith(".m4a") and job["mp4_url"] is None
    job = _wait(client, _ok(client.post(f"/api/cut/projects/{pid}/export",
                                        json={"format": "still", "frame": 45}))["job_id"])
    assert job["file_url"].endswith("-f45.png") and calls[-1][:2] == ("still", 45)
    res = client.post(f"/api/cut/projects/{pid}/export", json={"format": "still", "frame": 900})
    assert res.status_code == 422
    # none of them is the version's export of record
    assert _ok(client.get(f"/api/cut/projects/{pid}/exports"))["exports"] == []

    # the editable project needs no ffmpeg at all
    monkeypatch.setattr(cut_routes.cut_sources, "ffmpeg_bin", lambda: None)
    job = _wait(client, _ok(client.post(f"/api/cut/projects/{pid}/export", json={"format": "project"}))["job_id"])
    assert job["status"] == "done", job
    written = json.loads(next(tmp_path.glob("*.otio")).read_text())
    assert written["OTIO_SCHEMA"] == "Timeline.1"
    assert [t["kind"] for t in written["tracks"]["children"]] == ["Video", "Audio", "Audio"]
    assert job["otio_url"].endswith(".otio") and job["srt_url"] is None
