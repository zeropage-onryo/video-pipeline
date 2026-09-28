"""The editing agent's server half (phase E of docs/CUT_EDITOR.md): the
agent turn, Keep, Clean up, Captions, indexing a cut's media -- and phase
F's "start a cut from these" -- through /api/cut, the way the React
panel reaches them.

No model is ever asked: `agent_tools.call_model` is THE seam and every
agent test replaces it with a script (the loop, the tools and the
validation all run for real around it). Clean up and Captions call no
model at all -- they read word timings seeded straight into
media_moments. Media is measured once into cut_media_cache, as in
test_cut_projects.py, so nothing is probed. Every op sequence a proposal
carries is re-applied here from its base and must land on its doc.
"""
import time

import pytest

from src import accounts, db, preprod, render_assets
from src.cut import agent_tools, moments, ops, projects, store
from src.cut import doc as d
from src.cut import validate as v

FPS = 30


def _bank(conn, n, account_id, kind="video", url=None):
    url = url or f"/renders/runway/clip{n}.mp4"
    row = conn.execute(
        "INSERT INTO generated_assets (created_at, generation_id, tool, model, media_kind, "
        "prompt, media_url, account_id) VALUES (%s, %s, 'runway', 'gen4_turbo', %s, "
        "'a man on a rooftop', %s, %s) RETURNING id",
        (f"2026-09-{10 + n:02d}T00:00:00+00:00", n, kind, url, account_id)).fetchone()
    return f"gen:{row['id']}", url


def _measured(dsn, handle, url, account_id, seconds, video=True, audio=True, still=False):
    store.put_probe(handle, url, {"seconds": seconds, "video": video, "audio": audio,
                                  "still": still, "width": 720, "height": 1280},
                    account_id=account_id, size_bytes=1234, dsn=dsn)


@pytest.fixture
def world(pg):
    preprod.init(pg)
    render_assets.init(pg)
    store.init(pg)
    moments.init(pg)
    accounts.seed("mike@example.com", dsn=pg)
    with db.connect(pg) as conn:
        a = conn.execute("SELECT id FROM accounts WHERE slug='zeropage'").fetchone()["id"]
        b = conn.execute("SELECT id FROM accounts WHERE slug='antihero'").fetchone()["id"]
        g1, u1 = _bank(conn, 1, a)
        g2, u2 = _bank(conn, 2, a)
        g3, u3 = _bank(conn, 3, a, kind="image", url="/renders/nano/still3.png")
        g4, u4 = _bank(conn, 4, a)                      # footage with no sound
        gb, ub = _bank(conn, 6, b)                      # the other account's render
    _measured(pg, g1, u1, a, 5.0)
    _measured(pg, g2, u2, a, 4.0)
    _measured(pg, g3, u3, a, 600, audio=False, still=True)
    _measured(pg, g4, u4, a, 3.0, audio=False)
    _measured(pg, gb, ub, b, 5.0)
    bed = store.add_media(account_id=a, kind="audio", filename="bed.m4a",
                          media_url="/renders/cut/media/bed.m4a", output_path=None,
                          seconds=30, sha256=None, dsn=pg)
    music = f"asset:{bed['id']}"
    _measured(pg, music, bed["media_url"], a, 30.0, video=False)
    return {"dsn": pg, "a": a, "b": b, "g1": g1, "g2": g2, "g3": g3, "g4": g4, "gb": gb,
            "music": music}


@pytest.fixture
def api(world, monkeypatch):
    from fastapi.testclient import TestClient

    import app.main as app_main
    from app import auth

    monkeypatch.setenv("DATABASE_URL", world["dsn"])
    monkeypatch.setattr(auth, "current_user",
                        lambda request: {"id": "u1", "email": "x@example.com"})
    app_main.app.dependency_overrides[auth.current_account_id] = lambda: world["a"]
    yield TestClient(app_main.app), world
    app_main.app.dependency_overrides[auth.current_account_id] = lambda: None


def _as(account_id):
    import app.main as app_main
    from app import auth
    app_main.app.dependency_overrides[auth.current_account_id] = lambda: account_id


def _wait(client, job_id, timeout=30):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] not in ("queued", "running"):
            return job
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} still running")


def _ok(res):
    assert res.status_code == 200, res.text
    return res.json()


def _open(client, pid):
    return _ok(client.get(f"/api/cut/projects/{pid}"))


def _op(client, pid, base, op, **args):
    return _ok(client.post(f"/api/cut/projects/{pid}/ops",
                           json={"base_id": base, "op": op, "args": args}))


def _cut(client, *handles, **extra):
    """A project whose v1 holds `handles` (phase F's door), opened."""
    p = _ok(client.post("/api/cut/projects", json={"handles": list(handles), **extra}))["project"]
    return p, _open(client, p["id"])


def _words(dsn, handle, account_id, words, frames=150):
    moments.write(handle, "sha-" + handle, account_id=account_id, fps=FPS, frames=frames,
                  has_audio=True, speech=True, dsn=dsn,
                  moments=[{"kind": "word", "start_f": a, "end_f": b, "text": t}
                           for a, b, t in words])


# "Hello um, world ........ again done." -- a filler at 18-24, a 40f silence
# at 40-80 (air of 4f each side leaves 44-76 to cut)
G1_WORDS = [(0, 15, "Hello"), (18, 24, "um,"), (27, 40, "world"), (80, 95, "again"),
            (98, 110, "done.")]
G2_WORDS = [(0, 10, "next"), (12, 25, "shot")]


def _replays(doc, proposal, account_id, dsn):
    """The proposal's ops, applied in order from its base, land exactly on
    the doc it shows -- and that doc is valid against the measured media."""
    media = projects.media_for(doc, proposal["ops"], account_id=account_id, dsn=dsn)
    after = projects.apply_all(doc, proposal["ops"], media=media)
    assert after == proposal["doc"]
    assert v.problems(after, media) == []
    return after


# --------------------------------------------------------------------------
# phase F: a cut started from a selection
# --------------------------------------------------------------------------

def test_a_cut_from_handles_lays_them_out_in_order(api):
    client, w = api
    p, got = _cut(client, w["g1"], w["g3"], w["music"], w["g4"])
    doc = got["head"]["doc"]
    assert p["title"].endswith(f"#{w['g1'].split(':')[1]}") and p["version"] == 1
    assert got["head"]["op_summary"] == "new project from 4 clips"
    v1 = d.track(doc, "V1")["clips"]
    assert [(c["media"], c["at"], d.clip_length(c)) for c in v1] == [
        (w["g1"], 0, 150), (w["g3"], 150, 5 * FPS), (w["g4"], 300, 90)]
    a1 = d.track(doc, "A1")["clips"]
    assert [(c["media"], c["at"], c["link"]) for c in a1] == [(w["g1"], 0, v1[0]["id"])]
    assert [(c["media"], c["at"], d.clip_length(c)) for c in d.track(doc, "A2")["clips"]] == [
        (w["music"], 0, 900)]
    assert doc["duration"] == 900 and v.problems(doc) == []


def test_a_cut_from_handles_takes_a_title_and_refuses_what_is_not_yours(api):
    client, w = api
    p, _ = _cut(client, w["g2"], title="Rooftop")
    assert p["title"] == "Rooftop"
    before = len(client.get("/api/cut/projects").json()["projects"])
    for bad in (w["gb"], "gen:99999", "https://x.example/a.mp4"):
        res = client.post("/api/cut/projects", json={"handles": [w["g1"], bad]})
        assert res.status_code == 404 and res.json()["error"]["code"] == "bad_media", bad
    assert len(client.get("/api/cut/projects").json()["projects"]) == before
    too_many = client.post("/api/cut/projects", json={"handles": [w["g1"]] * 21})
    assert too_many.status_code == 422


# --------------------------------------------------------------------------
# what the model is shown
# --------------------------------------------------------------------------

def test_the_catalogue_is_every_op_with_its_args_and_a_line():
    text = agent_tools.op_catalogue()
    assert set(agent_tools.OP_NOTES) == set(ops.OPS)
    for name in ops.OPS:
        assert f"- {name}(" in text
    assert "split(clip_id: str, frame: int)" in text
    assert "trim(clip_id: str, head: int = 0, tail: int = 0, ripple: bool = false)" in text
    assert "sound_track: str = null" in text


def test_the_timeline_reads_as_ids_frames_and_names():
    doc = d.starter_doc()
    doc = ops.insert(doc, "V1", {"media": "gen:5", "src_in": 0, "src_out": 90},
                     sound_track="A1")
    doc = ops.add_marker(doc, 30, "beat")
    text = agent_tools.read_timeline(doc, {"gen:5": {"name": "Runway #5", "about": "rain"}})
    assert "duration 90f (3.0s)" in text and "V1 (video):" in text and "A2 (audio, music):" in text
    assert 'c1 gen:5 "Runway #5" (rain) at 0f-90f' in text
    assert "linked to c1" in text and '30f (1.0s) "beat"' in text and "(empty)" in text


# --------------------------------------------------------------------------
# the agent turn (a faked model)
# --------------------------------------------------------------------------

class Script:
    """A model that answers from a list, and remembers what it was shown."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.seen = []

    def __call__(self, system, turns, tools, *, account_id=None):
        self.seen.append({"system": system, "turns": [dict(t) for t in turns],
                          "tools": [t["name"] for t in tools], "account_id": account_id})
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def _propose(summary, *op_list):
    return {"text": "", "calls": [{"name": "propose_ops",
                                   "args": {"summary": summary,
                                            "ops": [{"op": o, "args": a} for o, a in op_list]}}]}


def _turn(client, pid, message="tighten it", **extra):
    res = _ok(client.post(f"/api/cut/projects/{pid}/agent", json={"message": message, **extra}))
    assert set(res) == {"job_id"}
    job = _wait(client, res["job_id"])
    assert job["status"] == "done", job
    return job


def test_a_valid_proposal_is_shown_and_nothing_is_saved(api, monkeypatch):
    client, w = api
    p, got = _cut(client, w["g1"], w["g2"])
    head, doc = got["head"], got["head"]["doc"]
    c1 = d.track(doc, "V1")["clips"][0]["id"]
    # 60.0: Gemini's function args arrive as doubles; a whole one is a frame
    script = Script(_propose("Split the first shot", ("split", {"clip_id": c1, "frame": 60.0})))
    monkeypatch.setattr(agent_tools, "call_model", script)
    job = _turn(client, p["id"], "split the first shot at 2s", playhead=60, selection=[c1])

    prop = job["proposal"]
    assert set(prop) == {"summary", "ops", "base_id", "region", "duration_delta", "doc", "kind"}
    assert (prop["summary"], prop["base_id"], prop["kind"]) == (
        "Split the first shot", head["id"], "agent")
    assert prop["ops"] == [{"op": "split", "args": {"clip_id": c1, "frame": 60}}]
    assert prop["region"] == {"from": 0, "to": 150} and prop["duration_delta"] == 0
    assert len(d.track(prop["doc"], "V1")["clips"]) == 3
    _replays(doc, prop, w["a"], w["dsn"])
    assert job["reply"] == "Split the first shot" and job["notes"] == [] and job["ref_id"] is None
    assert job["tool_runs"] == [{"tool": "propose_ops", "args": job["tool_runs"][0]["args"],
                                 "ok": True}]
    # nothing happened to the cut
    again = _open(client, p["id"])
    assert again["head"]["id"] == head["id"] and len(again["versions"]) == 1

    shown = script.seen[0]
    assert shown["tools"] == ["read_timeline", "search_footage", "propose_ops"]
    assert shown["account_id"] == w["a"]
    first = shown["turns"][0]["text"]
    assert f"{c1} {w['g1']}" in first and "PLAYHEAD: frame 60 (2.0s)" in first
    assert f"SELECTED: {c1}" in first and "- ripple_delete(clip_id: str)" in first
    assert first.endswith("split the first shot at 2s")


def test_a_refused_proposal_goes_back_once_with_the_reasons(api, monkeypatch):
    client, w = api
    p, got = _cut(client, w["g1"], w["g2"])
    doc = got["head"]["doc"]
    c2 = d.track(doc, "V1")["clips"][1]["id"]
    script = Script(_propose("cut", ("split", {"clip_id": c2, "frame": 999})),
                    _propose("Removed the second shot, −0:04", ("ripple_delete", {"clip_id": c2})))
    monkeypatch.setattr(agent_tools, "call_model", script)
    job = _turn(client, p["id"], "drop the second shot")

    back = script.seen[1]["turns"][-1]
    assert back["role"] == "tool" and back["results"][0]["name"] == "propose_ops"
    assert "REFUSED" in back["results"][0]["result"]
    assert f"frame 999 is not inside clip {c2}" in back["results"][0]["result"]
    prop = job["proposal"]
    assert prop["duration_delta"] == -120 and prop["region"] == {"from": 150, "to": 270}
    assert prop["doc"]["duration"] == 150 and d.find_clip(prop["doc"], c2) is None
    _replays(doc, prop, w["a"], w["dsn"])
    assert [(r["tool"], r["ok"]) for r in job["tool_runs"]] == [
        ("propose_ops", False), ("propose_ops", True)]


def test_twice_refused_is_no_proposal_and_the_reasons_as_notes(api, monkeypatch):
    client, w = api
    p, _ = _cut(client, w["g1"])
    bad = ("ripple_delete", {"clip_id": "c99"})
    monkeypatch.setattr(agent_tools, "call_model", Script(_propose("x", bad), _propose("x", bad)))
    job = _turn(client, p["id"])
    assert job["proposal"] is None
    assert job["notes"] == ["op 1 (ripple_delete): no clip c99"]
    assert job["reply"].startswith("I couldn't make a valid edit")


def test_a_question_is_just_answered(api, monkeypatch):
    client, w = api
    p, _ = _cut(client, w["g1"])
    monkeypatch.setattr(agent_tools, "call_model",
                        Script({"text": "It runs 5 seconds, one shot.", "calls": []}))
    job = _turn(client, p["id"], "how long is this?")
    assert (job["reply"], job["proposal"], job["tool_runs"]) == (
        "It runs 5 seconds, one shot.", None, [])


def test_the_agent_can_search_the_footage_then_propose(api, monkeypatch):
    client, w = api
    p, got = _cut(client, w["g1"])
    from src.cut import index
    monkeypatch.setattr(index, "find", lambda q, **kw: {"results": [
        {"media": w["g2"], "concept_id": None, "concept_title": None, "start_s": 0.0,
         "end_s": 2.0, "kind": "shot", "speaker": None, "text": "the rooftop wide",
         "media_url": "https://pub.r2.dev/x.mp4"}], "notes": []})
    script = Script({"text": "", "calls": [{"name": "search_footage",
                                            "args": {"query": "rooftop"}}]},
                    _propose("Added the rooftop wide", (
                        "insert", {"track_id": "V1", "sound_track": "A1",
                                   "clip": {"media": w["g2"], "src_in": 0, "src_out": 60}})))
    monkeypatch.setattr(agent_tools, "call_model", script)
    job = _turn(client, p["id"], "add the rooftop wide at the end")
    result = script.seen[1]["turns"][-1]["results"][0]["result"]
    assert w["g2"] in result and "http" not in result
    assert [(r["tool"], r["ok"]) for r in job["tool_runs"]] == [
        ("search_footage", True), ("propose_ops", True)]
    assert job["proposal"]["duration_delta"] == 60
    _replays(got["head"]["doc"], job["proposal"], w["a"], w["dsn"])


def test_the_agent_cannot_add_media_that_is_not_yours(api, monkeypatch):
    client, w = api
    p, _ = _cut(client, w["g1"])
    step = ("insert", {"track_id": "V1", "clip": {"media": w["gb"], "src_in": 0, "src_out": 30}})
    monkeypatch.setattr(agent_tools, "call_model", Script(_propose("x", step), _propose("x", step)))
    job = _turn(client, p["id"])
    assert job["proposal"] is None and f"unknown media handle {w['gb']}" in job["notes"][0]


@pytest.mark.parametrize("failure,said", [
    (agent_tools.AgentUnavailable("this server has no Gemini key"), "no Gemini key"),
    (RuntimeError("503 UNAVAILABLE"), "unavailable right now")])
def test_a_dead_model_still_finishes_the_turn(api, monkeypatch, failure, said):
    client, w = api
    p, _ = _cut(client, w["g1"])
    monkeypatch.setattr(agent_tools, "call_model", Script(failure))
    job = _turn(client, p["id"])
    assert said in job["reply"] and job["proposal"] is None and job["notes"]


def test_no_key_is_answered_without_a_call(api, monkeypatch):
    client, w = api
    p, _ = _cut(client, w["g1"])
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    job = _turn(client, p["id"])                          # the real call_model
    assert "no Gemini key" in job["reply"] and job["proposal"] is None


def test_the_agent_turn_is_scoped_and_refuses_an_empty_ask(api, monkeypatch):
    client, w = api
    p, _ = _cut(client, w["g1"])
    assert client.post(f"/api/cut/projects/{p['id']}/agent", json={"message": "   "}).status_code == 400
    assert client.post(f"/api/cut/projects/{p['id']}/agent", json={"message": ""}).status_code == 422
    _as(w["b"])
    for path, body in (("agent", {"message": "hi"}), ("cleanup", {}), ("captions", {}),
                       ("index", None),
                       ("agent/keep", {"base_id": 1, "ops": [{"op": "add_marker",
                                                              "args": {"frame": 0, "label": "x"}}]})):
        res = client.post(f"/api/cut/projects/{p['id']}/{path}", json=body)
        assert res.status_code == 404, path


# --------------------------------------------------------------------------
# Keep
# --------------------------------------------------------------------------

def _keep(client, pid, base_id, op_list, summary="Removed the second shot"):
    return client.post(f"/api/cut/projects/{pid}/agent/keep",
                       json={"base_id": base_id, "ops": op_list, "summary": summary,
                             "kind": "agent"})


def test_keep_saves_one_version_by_the_agent_and_clears_redo(api):
    client, w = api
    p, got = _cut(client, w["g1"], w["g2"])
    base = got["head"]
    marked = _op(client, p["id"], base["id"], "add_marker", frame=0, label="go")
    undone = _ok(client.post(f"/api/cut/projects/{p['id']}/undo"))
    assert undone["can_redo"] is True and undone["head"]["id"] == base["id"]

    c2 = d.track(base["doc"], "V1")["clips"][1]["id"]
    long = "x" * 300
    kept = _ok(_keep(client, p["id"], base["id"],
                     [{"op": "split", "args": {"clip_id": c2, "frame": 200}},
                      {"op": "ripple_delete", "args": {"clip_id": c2}}], summary=long))
    assert set(kept) == {"head", "can_undo", "can_redo", "media"}
    assert kept["head"]["author"] == "agent" and kept["head"]["op_summary"] == "x" * 200
    assert kept["head"]["parent_id"] == base["id"]
    assert kept["can_undo"] is True and kept["can_redo"] is False
    assert kept["head"]["doc"]["duration"] == 220
    versions = _open(client, p["id"])["versions"]
    assert len(versions) == 3 and versions[0]["author"] == "agent"
    assert marked["head"]["id"] in [v_["id"] for v_ in versions]


def test_keep_on_a_moved_head_is_stale_and_a_bad_op_is_invalid(api):
    client, w = api
    p, got = _cut(client, w["g1"])
    base = got["head"]
    moved = _op(client, p["id"], base["id"], "add_marker", frame=0, label="go")
    res = _keep(client, p["id"], base["id"], [{"op": "add_marker",
                                               "args": {"frame": 1, "label": "x"}}])
    assert res.status_code == 409 and res.json()["error"]["code"] == "stale"
    assert res.json()["error"]["head_id"] == moved["head"]["id"]

    res = _keep(client, p["id"], moved["head"]["id"],
                [{"op": "add_marker", "args": {"frame": 1, "label": "ok"}},
                 {"op": "split", "args": {"clip_id": "c1", "frame": 999}}])
    assert res.status_code == 422 and res.json()["error"]["code"] == "invalid"
    assert res.json()["error"]["problems"][0].startswith("op 2 (split): frame 999")
    res = _keep(client, p["id"], moved["head"]["id"],
                [{"op": "insert", "args": {"track_id": "V1",
                                           "clip": {"media": w["gb"], "src_in": 0, "src_out": 9}}}])
    assert res.status_code == 422
    assert _keep(client, p["id"], moved["head"]["id"], []).status_code == 422
    assert len(_open(client, p["id"])["versions"]) == 2


# --------------------------------------------------------------------------
# Clean up
# --------------------------------------------------------------------------

def test_cleanup_removes_the_silence_and_the_filler_and_the_sound_goes_with_the_picture(api):
    client, w = api
    p, got = _cut(client, w["g1"], w["g2"])
    _words(w["dsn"], w["g1"], w["a"], G1_WORDS)
    doc = got["head"]["doc"]
    out = _ok(client.post(f"/api/cut/projects/{p['id']}/cleanup", json={}))
    assert set(out) == {"proposal", "needs_index", "found", "notes"}
    assert out["found"] == {"silences": 1, "fillers": 1}
    assert out["needs_index"] == [w["g2"]]                # not indexed: said, not guessed
    prop = out["proposal"]
    assert prop["kind"] == "cleanup" and prop["base_id"] == got["head"]["id"]
    # 6 frames of "um," and 32 of the 40-frame silence (4 of air left each side)
    assert prop["duration_delta"] == -38 and prop["doc"]["duration"] == 270 - 38
    assert prop["summary"] == "Removed 1 silence and 1 filler word, −0:01"
    assert prop["region"] == {"from": 0, "to": 150}
    after = _replays(doc, prop, w["a"], w["dsn"])
    # picture and its sound were cut together: A1 mirrors V1 clip for clip
    pic = [(c["at"], c["src_in"], c["src_out"]) for c in d.track(after, "V1")["clips"]]
    snd = [(c["at"], c["src_in"], c["src_out"]) for c in d.track(after, "A1")["clips"]]
    assert pic == snd == [(0, 0, 18), (18, 24, 44), (38, 76, 150), (112, 0, 120)]
    # nothing saved
    assert len(_open(client, p["id"])["versions"]) == 1


def test_cleanup_options_and_a_filler_at_the_head_is_a_trim(api):
    client, w = api
    p, got = _cut(client, w["g1"])
    _words(w["dsn"], w["g1"], w["a"], G1_WORDS)
    base = got["head"]
    c1 = d.track(base["doc"], "V1")["clips"][0]["id"]
    trimmed = _op(client, p["id"], base["id"], "trim", clip_id=c1, head=18, ripple=True)
    out = _ok(client.post(f"/api/cut/projects/{p['id']}/cleanup",
                          json={"base_id": trimmed["head"]["id"]}))
    ops_used = [o["op"] for o in out["proposal"]["ops"]]
    assert ops_used[-1] == "trim" and out["proposal"]["ops"][-1]["args"]["head"] == 6
    assert out["proposal"]["duration_delta"] == -38
    _replays(trimmed["head"]["doc"], out["proposal"], w["a"], w["dsn"])

    only_silence = _ok(client.post(f"/api/cut/projects/{p['id']}/cleanup",
                                   json={"fillers": False}))
    assert only_silence["found"] == {"silences": 1, "fillers": 0}
    only_filler = _ok(client.post(f"/api/cut/projects/{p['id']}/cleanup",
                                  json={"min_silence": 2}))
    assert only_filler["found"] == {"silences": 0, "fillers": 1}
    res = client.post(f"/api/cut/projects/{p['id']}/cleanup", json={"base_id": base["id"]})
    assert res.status_code == 409 and res.json()["error"]["head_id"] == trimmed["head"]["id"]


def test_cleanup_skips_a_clip_whose_sound_is_not_on_the_timeline(api):
    client, w = api
    p = _ok(client.post("/api/cut/projects", json={}))["project"]
    head = _open(client, p["id"])["head"]
    _words(w["dsn"], w["g1"], w["a"], G1_WORDS)
    _op(client, p["id"], head["id"], "insert", track_id="V1",
        clip={"media": w["g1"], "src_in": 0, "src_out": 150})
    out = _ok(client.post(f"/api/cut/projects/{p['id']}/cleanup", json={}))
    assert out["proposal"] is None and out["found"] == {"silences": 0, "fillers": 0}
    assert any("sound is not on the timeline" in n for n in out["notes"])


# --------------------------------------------------------------------------
# Captions
# --------------------------------------------------------------------------

def test_captions_map_the_words_through_a_trimmed_and_moved_clip(api):
    client, w = api
    p, got = _cut(client, w["g1"], w["g2"])
    _words(w["dsn"], w["g1"], w["a"], G1_WORDS)
    _words(w["dsn"], w["g2"], w["a"], G2_WORDS, frames=120)
    c1 = d.track(got["head"]["doc"], "V1")["clips"][0]["id"]
    step = _op(client, p["id"], got["head"]["id"], "trim", clip_id=c1, head=27)
    step = _op(client, p["id"], step["head"]["id"], "move", clip_id=c1, at=10)
    out = _ok(client.post(f"/api/cut/projects/{p['id']}/captions", json={}))
    assert set(out) == {"proposal", "needs_index", "cues", "notes"}
    assert out["cues"] == 3 and out["needs_index"] == []
    prop = out["proposal"]
    assert prop["kind"] == "captions" and [o["op"] for o in prop["ops"]] == ["add_caption_track"]
    after = _replays(step["head"]["doc"], prop, w["a"], w["dsn"])
    # "Hello" and "um," fall in the trimmed-off head; the rest is shifted
    # by the move; a pause over 0.4s starts a new cue
    assert [(q["start"], q["end"], q["text"]) for q in d.track(after, "T1")["cues"]] == [
        (10, 23, "world"), (63, 93, "again done."), (150, 175, "next shot")]
    assert prop["duration_delta"] == 0 and prop["region"] == {"from": 10, "to": 175}

    one = _ok(client.post(f"/api/cut/projects/{p['id']}/captions", json={"max_words": 1}))
    assert one["cues"] == 5


def test_captions_onto_an_existing_track_leave_its_cues_alone(api):
    client, w = api
    p, got = _cut(client, w["g1"], w["g2"])
    _words(w["dsn"], w["g1"], w["a"], G1_WORDS)
    step = _op(client, p["id"], got["head"]["id"], "add_caption_track", cues=[], track_id="T1")
    step = _op(client, p["id"], step["head"]["id"], "set_cue", track_id="T1", start=70,
               end=100, text="mine")
    out = _ok(client.post(f"/api/cut/projects/{p['id']}/captions", json={"track_id": "T1"}))
    assert out["needs_index"] == [w["g2"]]
    prop = out["proposal"]
    # "Hello um, world" (0-40) is free; "again done." (80-110) would sit on "mine"
    assert [o["op"] for o in prop["ops"]] == ["set_cue"]
    assert out["cues"] == 1 and any("1 cue(s) left out" in n for n in out["notes"])
    after = _replays(step["head"]["doc"], prop, w["a"], w["dsn"])
    assert [(q["start"], q["end"], q["text"]) for q in d.track(after, "T1")["cues"]] == [
        (0, 40, "Hello um, world"), (70, 100, "mine")]

    res = client.post(f"/api/cut/projects/{p['id']}/captions", json={"track_id": "V1"})
    assert res.status_code == 422


def test_nothing_indexed_is_no_proposal_and_a_list_to_index(api):
    client, w = api
    p, _ = _cut(client, w["g1"], w["music"])
    out = _ok(client.post(f"/api/cut/projects/{p['id']}/captions", json={}))
    assert out["proposal"] is None and out["cues"] == 0 and out["needs_index"] == [w["g1"]]
    out = _ok(client.post(f"/api/cut/projects/{p['id']}/cleanup", json={}))
    assert out["proposal"] is None and out["needs_index"] == [w["g1"]]


# --------------------------------------------------------------------------
# indexing a cut's media
# --------------------------------------------------------------------------

def test_the_index_route_indexes_only_what_this_cut_has_not(api, monkeypatch):
    client, w = api
    from src.cut import index, sources
    p, _ = _cut(client, w["g1"], w["g2"])
    _words(w["dsn"], w["g1"], w["a"], G1_WORDS)

    monkeypatch.setattr(sources, "ffmpeg_bin", lambda: None)
    res = client.post(f"/api/cut/projects/{p['id']}/index")
    assert res.status_code == 503 and res.json()["error"]["code"] == "no_ffmpeg"

    monkeypatch.setattr(sources, "ffmpeg_bin", lambda: "/usr/bin/ffmpeg")
    seen = []

    def fake(h, **kw):
        seen.append((h, kw["account_id"]))
        _words(w["dsn"], h, w["a"], G2_WORDS, frames=120)
        return {"media": h, "status": "done", "shots": 1, "words": 2}

    monkeypatch.setattr(index, "index_media", fake)
    out = _ok(client.post(f"/api/cut/projects/{p['id']}/index"))
    assert out["handles"] == [w["g2"]]
    job = _wait(client, out["job_id"])
    assert job["status"] == "done" and seen == [(w["g2"], w["a"])]
    assert "1 indexed" in job["detail"] and job["ref_id"] == p["id"]
    res = client.post(f"/api/cut/projects/{p['id']}/index")
    assert res.status_code == 409 and res.json()["error"]["code"] == "nothing_to_index"
