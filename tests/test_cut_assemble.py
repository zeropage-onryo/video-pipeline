"""Assemble v0 end to end: the store, the assembler, the render and the
/api/cut routes (docs/tasks/CUT_ASSEMBLE_V0.md).

Nothing here renders anything paid. The clips are made on the spot with
ffmpeg's `testsrc` / `sine` sources; the tests that need ffmpeg skip on a
machine without it (CI installs it, so they run there).
"""
import json
import re
import shutil
import subprocess
import time

import pytest

from src import accounts, db, preprod, render_assets
from src.cut import assemble, render, sources, store
from src.cut import doc as d
from src.cut import validate as v

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg/ffprobe not installed")


def _ff(*args):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


@pytest.fixture(scope="module")
def clips(tmp_path_factory):
    """Three shots (the first one letterboxed at another fps, the last one
    silent), a music bed and a voiceover."""
    if not HAS_FFMPEG:
        pytest.skip("ffmpeg/ffprobe not installed")
    root = tmp_path_factory.mktemp("fixtures")
    enc = ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast"]
    _ff("-f", "lavfi", "-i", "testsrc2=s=720x1280:r=30:d=4", "-f", "lavfi",
        "-i", "sine=f=660:d=4", "-shortest", *enc, "-c:a", "aac", str(root / "a.mp4"))
    _ff("-f", "lavfi", "-i", "testsrc=s=640x360:r=24:d=5", "-f", "lavfi",
        "-i", "sine=f=440:d=5", "-shortest", *enc, "-c:a", "aac", str(root / "b.mp4"))
    _ff("-f", "lavfi", "-i", "testsrc=s=720x1280:r=30:d=3", *enc, str(root / "c.mp4"))
    _ff("-f", "lavfi", "-i", "sine=f=220:d=30", "-c:a", "aac", str(root / "music.m4a"))
    _ff("-f", "lavfi", "-i", "sine=f=880:d=6", "-c:a", "aac", str(root / "voice.m4a"))
    return root


# --------------------------------------------------------------------------
# a database with a rendered, timed concept on it
# --------------------------------------------------------------------------

def _tiny_doc(frames=30):
    doc = d.new_doc()
    doc["tracks"] = [{"id": "V1", "kind": "video", "clips": [
        {"id": "c1", "media": "gen:1", "src_in": 0, "src_out": frames, "at": 0, "speed": 1}]}]
    doc["duration"] = frames
    return doc


@pytest.fixture
def owners(pg):
    preprod.init(pg)
    render_assets.init(pg)
    store.init(pg)
    accounts.seed("mike@example.com", dsn=pg)
    with db.connect(pg) as conn:
        a = conn.execute("SELECT id FROM accounts WHERE slug='zeropage'").fetchone()["id"]
        b = conn.execute("SELECT id FROM accounts WHERE slug='antihero'").fetchone()["id"]
    return pg, a, b


def _bank(conn, n, path, account_id, concept_id=None):
    url = f"/renders/runway/{path.name}"
    row = conn.execute(
        "INSERT INTO generated_assets (created_at, generation_id, tool, model, media_kind, "
        "prompt, media_url, output_path, concept_id, account_id) "
        "VALUES ('t', %s, 'runway', 'gen4_turbo', 'video', 'p', %s, %s, %s, %s) RETURNING id",
        (n, url, str(path), concept_id, account_id)).fetchone()
    return row["id"], url


def _concept(conn, shots, account_id, title="Neon City Ascent"):
    return conn.execute(
        "INSERT INTO shoot_concepts (created_at, brand, title, shots_json, account_id) "
        "VALUES ('t', 'zeropage', %s, %s, %s) RETURNING id",
        (title, json.dumps(shots), account_id)).fetchone()["id"]


def _timed_shot(urls):
    return {"n": 1, "prompt": "(0-4s) a. (4-9s) b. (9-12s) c.", "refs": ["/refs/x.jpg"],
            "timeline": {"seconds": 12, "source": "stale-on-purpose", "parts": [
                {"n": i + 1, "media_url": u} for i, u in enumerate(urls)]}}


@pytest.fixture
def rendered(owners, clips):
    """Concept whose three timeline parts are rendered and banked --
    deliberately stored OUT of order, so the test proves part order wins."""
    pg, a, b = owners
    with db.connect(pg) as conn:
        ga, ua = _bank(conn, 1, clips / "a.mp4", a)
        gb, ub = _bank(conn, 2, clips / "b.mp4", a)
        gc, uc = _bank(conn, 3, clips / "c.mp4", a)
        shot = _timed_shot([ua, ub, uc])
        shot["timeline"]["parts"].reverse()
        cid = _concept(conn, [shot], a)
    music = store.add_media(account_id=a, kind="audio", filename="music.m4a",
                            media_url="/renders/cut/media/music.m4a",
                            output_path=str(clips / "music.m4a"), seconds=30, sha256=None, dsn=pg)
    voice = store.add_media(account_id=a, kind="audio", filename="voice.m4a",
                            media_url="/renders/cut/media/voice.m4a",
                            output_path=str(clips / "voice.m4a"), seconds=6, sha256=None, dsn=pg)
    return {"dsn": pg, "a": a, "b": b, "concept": cid, "gen": [ga, gb, gc],
            "music": f"asset:{music['id']}", "voice": f"asset:{voice['id']}"}


# --------------------------------------------------------------------------
# store
# --------------------------------------------------------------------------

def test_versions_append_and_the_head_follows(owners):
    pg, a, _ = owners
    v1 = store.save_version("concept:9", _tiny_doc(), account_id=a, author="assemble",
                            op_summary="first", dsn=pg)
    v2 = store.save_version("concept:9", _tiny_doc(20), account_id=a, author="user",
                            op_summary="trim", dsn=pg)
    assert (v1["version"], v2["version"]) == (1, 2)
    assert v2["parent_id"] == v1["id"] and v1["parent_id"] is None
    assert store.head("concept:9", account_id=a, dsn=pg)["id"] == v2["id"]
    assert store.head("concept:9", account_id=a, dsn=pg)["doc"]["duration"] == 20


def test_rollback_moves_the_pointer_and_deletes_nothing(owners):
    pg, a, _ = owners
    v1 = store.save_version("concept:9", _tiny_doc(), account_id=a, author="assemble",
                            op_summary="first", dsn=pg)
    store.save_version("concept:9", _tiny_doc(20), account_id=a, author="user",
                       op_summary="trim", dsn=pg)
    assert store.rollback("concept:9", v1["id"], account_id=a, dsn=pg)["version"] == 1
    assert store.head("concept:9", account_id=a, dsn=pg)["id"] == v1["id"]
    assert len(store.history("concept:9", account_id=a, dsn=pg)) == 2
    # an edit after a rollback branches from where the head is
    v3 = store.save_version("concept:9", _tiny_doc(25), account_id=a, author="agent",
                            op_summary="retry", dsn=pg)
    assert v3["version"] == 3 and v3["parent_id"] == v1["id"]


def test_the_store_refuses_a_bad_doc_a_bad_author_and_a_foreign_parent(owners):
    pg, a, _ = owners
    bad = _tiny_doc()
    bad["duration"] = 99
    with pytest.raises(v.InvalidDoc):
        store.save_version("concept:9", bad, account_id=a, author="user", op_summary="x", dsn=pg)
    with pytest.raises(ValueError, match="author"):
        store.save_version("concept:9", _tiny_doc(), account_id=a, author="robot",
                           op_summary="x", dsn=pg)
    other = store.save_version("concept:8", _tiny_doc(), account_id=a, author="user",
                               op_summary="x", dsn=pg)
    with pytest.raises(ValueError, match="no version"):
        store.save_version("concept:9", _tiny_doc(), account_id=a, author="user",
                           op_summary="x", parent_id=other["id"], dsn=pg)
    assert store.rollback("concept:9", other["id"], account_id=a, dsn=pg) is None


def test_another_accounts_cut_is_indistinguishable_from_none(owners):
    pg, a, b = owners
    row = store.save_version("concept:9", _tiny_doc(), account_id=a, author="user",
                             op_summary="x", dsn=pg)
    media = store.add_media(account_id=a, kind="audio", filename="m.m4a", media_url="/x",
                            output_path=None, seconds=1, sha256=None, dsn=pg)
    assert store.head("concept:9", account_id=b, dsn=pg) is None
    assert store.get(row["id"], account_id=b, dsn=pg) is None
    assert store.history("concept:9", account_id=b, dsn=pg) == []
    assert store.rollback("concept:9", row["id"], account_id=b, dsn=pg) is None
    assert store.get_media(media["id"], account_id=b, dsn=pg) is None
    assert store.latest_exports(["concept:9"], account_id=b, dsn=pg) == {}
    # and b's own version 1 is its own chain, not a v2 of a's
    mine = store.save_version("concept:9", _tiny_doc(), account_id=b, author="user",
                              op_summary="x", dsn=pg)
    assert mine["version"] == 1


def test_a_handle_does_not_resolve_across_accounts(rendered, tmp_path):
    with pytest.raises(sources.SourceError, match="unknown media handle"):
        sources.resolve(f"gen:{rendered['gen'][0]}", account_id=rendered["b"],
                        workdir=tmp_path, dsn=rendered["dsn"])
    with pytest.raises(sources.SourceError, match="unknown media handle"):
        sources.resolve(rendered["music"], account_id=rendered["b"], workdir=tmp_path,
                        dsn=rendered["dsn"])


def test_a_local_path_never_climbs_out_of_renders(tmp_path, monkeypatch):
    monkeypatch.setattr(sources, "RENDERS_DIR", tmp_path / "renders")
    (tmp_path / "renders" / "runway").mkdir(parents=True)
    (tmp_path / "renders" / "runway" / "ok.mp4").write_bytes(b"x")
    (tmp_path / "secret.txt").write_text("no")
    assert sources.local_path_for("/renders/runway/ok.mp4") is not None
    assert sources.local_path_for("/renders/../secret.txt") is None


def test_a_private_address_is_never_fetched(tmp_path):
    with pytest.raises(sources.SourceError, match="private address"):
        sources._download("http://127.0.0.1/clip.mp4", tmp_path)
    with pytest.raises(sources.SourceError, match="not a fetchable URL"):
        sources._download("file:///etc/passwd", tmp_path)


# --------------------------------------------------------------------------
# assemble: the pure half
# --------------------------------------------------------------------------

FAKE = {"gen:1": {"frames": 120, "video": True, "audio": True, "width": 720, "height": 1280},
        "gen:2": {"frames": 150, "video": True, "audio": True, "width": 641, "height": 361},
        "gen:3": {"frames": 90, "video": True, "audio": False, "width": 720, "height": 1280},
        "asset:5": {"frames": 900, "video": False, "audio": True},
        "asset:6": {"frames": 180, "video": False, "audio": True}}
CLIPS = [{"handle": "gen:1", "label": "shot 1 part 1"},
         {"handle": "gen:2", "label": "shot 1 part 2"},
         {"handle": "gen:3", "label": "shot 1 part 3"}]


def test_slots_follow_part_order_and_legacy_shots():
    shot = _timed_shot(["u1", "u2", None])
    shot["timeline"]["parts"].reverse()
    slots = assemble.clip_slots({"shots": [shot]})
    assert [(s["part"], s["media_url"]) for s in slots] == [(1, "u1"), (2, "u2"), (3, None)]
    legacy = assemble.clip_slots({"shots": [{"n": 1, "media_url": "x"}, {"n": 2}]})
    assert [(s["label"], s["media_url"]) for s in legacy] == [("shot 1", "x"), ("shot 2", None)]


def test_the_first_cut_is_hard_cuts_with_linked_sound_and_markers():
    doc, notes = assemble.build_doc(CLIPS, FAKE)
    assert doc["size"] == [720, 1280] and doc["duration"] == 360
    assert [(c["media"], c["at"]) for c in d.track(doc, "V1")["clips"]] == [
        ("gen:1", 0), ("gen:2", 120), ("gen:3", 270)]
    assert not any(c.get("transition_in") for c in d.track(doc, "V1")["clips"])
    a1 = d.track(doc, "A1")["clips"]
    assert [c["media"] for c in a1] == ["gen:1", "gen:2"]        # gen:3 is silent
    assert all(c["link"] for c in a1)
    assert [m["frame"] for m in doc["markers"]] == [0, 120, 270]
    assert notes == [] and v.problems(doc, FAKE) == []


def test_an_odd_first_frame_size_is_evened():
    doc, _ = assemble.build_doc([CLIPS[1]], FAKE)
    assert doc["size"] == [640, 360]


def test_music_ducks_under_the_clips_own_sound_when_there_is_no_voice():
    doc, _ = assemble.build_doc(CLIPS, FAKE, music="asset:5")
    a2 = d.track(doc, "A2")
    assert a2["role"] == "music" and a2["duck_under"] == "sfx"
    assert a2["clips"][0]["src_out"] == 360 and a2["clips"][0]["gain_db"] == assemble.MUSIC_GAIN_DB


def test_music_ducks_under_voice_and_captions_ride_the_voice():
    doc, notes = assemble.build_doc(CLIPS, FAKE, music="asset:5", voice="asset:6",
                                    captions="First line. Then a second, longer line!")
    assert d.track(doc, "A2")["duck_under"] == "voice"
    cues = d.track(doc, "T1")["cues"]
    assert len(cues) == 2 and cues[0]["start"] == 0 and cues[-1]["end"] == 180
    assert cues[0]["end"] == cues[1]["start"]
    assert any("estimated" in n for n in notes)
    assert v.problems(doc, FAKE) == []


def test_captions_without_voice_are_left_out_and_said_so():
    doc, notes = assemble.build_doc(CLIPS, FAKE, captions="Hello there.")
    assert not d.tracks_of(doc, "caption")
    assert any("without a voiceover" in n for n in notes)


def test_timed_captions_convert_seconds_to_frames_and_clamp():
    cues = assemble.caption_cues([{"start": 0.5, "end": 2, "text": "hi"},
                                  {"start": 5, "end": 99, "text": "late"},
                                  {"start": 7, "end": 8, "text": "gone"}], 30, 180)
    assert cues == [{"start": 15, "end": 60, "text": "hi"}, {"start": 150, "end": 180, "text": "late"}]


def test_a_voice_longer_than_the_picture_is_trimmed_and_said_so():
    media = {**FAKE, "asset:6": {"frames": 999, "video": False, "audio": True}}
    doc, notes = assemble.build_doc(CLIPS, media, voice="asset:6")
    assert d.track(doc, "A3")["clips"][0]["src_out"] == 360
    assert any("trimmed" in n for n in notes)


# --------------------------------------------------------------------------
# assemble: against the database
# --------------------------------------------------------------------------

def test_plan_refuses_a_part_with_no_clip_and_a_clip_not_in_the_bank(owners):
    pg, a, _ = owners
    with db.connect(pg) as conn:
        cid = _concept(conn, [_timed_shot(["/renders/runway/unbanked.mp4", None])], a)
    planned = assemble.plan(cid, account_id=a, dsn=pg)
    assert planned["missing"] == ["shot 1 part 1's clip is not in the Asset Bank",
                                  "shot 1 part 2 has no clip yet"]


def test_plan_says_a_stale_timeline_was_assembled_from_what_rendered(rendered):
    planned = assemble.plan(rendered["concept"], account_id=rendered["a"], dsn=rendered["dsn"])
    assert planned["missing"] == []
    assert [c["handle"] for c in planned["clips"]] == [f"gen:{g}" for g in rendered["gen"]]
    assert any("stale" in n for n in planned["notes"])


def test_plan_does_not_see_another_accounts_concept(rendered):
    with pytest.raises(LookupError):
        assemble.plan(rendered["concept"], account_id=rendered["b"], dsn=rendered["dsn"])


def test_a_banked_clip_matches_by_its_storage_tail_too(owners, clips):
    """The row may hold the R2 URL while the shot holds the local route
    (or the reverse); both name the same object."""
    pg, a, _ = owners
    with db.connect(pg) as conn:
        gid, url = _bank(conn, 7, clips / "a.mp4", a)
        cid = _concept(conn, [{"n": 1, "media_url": "https://pub.r2.dev" + url}], a)
    planned = assemble.plan(cid, account_id=a, dsn=pg)
    assert [c["handle"] for c in planned["clips"]] == [f"gen:{gid}"]


# --------------------------------------------------------------------------
# render: the pure graph
# --------------------------------------------------------------------------

def test_the_graph_has_every_stage_the_spec_names():
    doc, _ = assemble.build_doc(CLIPS, FAKE, music="asset:5", voice="asset:6",
                                captions=[{"start": 0, "end": 2, "text": "hi"}])
    from src.cut import ops
    doc = ops.add_transition(doc, d.track(doc, "V1")["clips"][1]["id"], 8)
    paths = {h: f"/x/{h.replace(':', '_')}" for h in d.handles(doc)}
    argv = render.compile_args(doc, paths, "/x/out.mp4", burn="captions.ass")
    graph = argv[argv.index("-filter_complex") + 1]
    for stage in ("trim=start=", "setpts=PTS-STARTPTS", "scale=720:1280", "pad=720:1280",
                  "xfade=transition=fade", "concat=n=2", "atrim=", "volume=-12dB",
                  "sidechaincompress=", "amix=", "loudnorm=I=-14", "ass=captions.ass",
                  "afade=t=in", "afade=t=out"):
        assert stage in graph, stage
    # the crossfade pulls the picture in by 8 frames, but the music bed still
    # runs to 360, so the cut stays 12s and the picture is padded black
    assert argv[argv.index("-t") + 1] == "12"
    assert "tpad=stop_mode=add:stop_duration=0.266667" in graph
    # a file is opened once for its picture (-an) and once for its sound
    # (-vn), never once for both: reading a clip's sound early must not
    # queue its decoded picture (T25's v9 OOM on Fly, 2026-09-30)
    inputs = [i for i, a in enumerate(argv) if a == "-i"]
    assert all(argv[i - 1] in ("-an", "-vn") for i in inputs)
    on_video = {c["media"] for c in d.track(doc, "V1")["clips"]}
    on_audio = {c["media"] for t in d.tracks_of(doc, "audio") for c in t["clips"]}
    assert len(inputs) == len(on_video) + len(on_audio)
    assert "-filter_complex_threads" in argv and argv[argv.index("-c:v"):].count("-threads") == 1


def test_a_gap_renders_as_black_and_an_empty_track_is_silence():
    doc = d.new_doc()
    doc["tracks"] = [{"id": "V1", "kind": "video", "clips": [
        {"id": "c1", "media": "gen:3", "src_in": 0, "src_out": 30, "at": 30, "speed": 1}]}]
    doc["duration"] = 60
    argv = render.compile_args(doc, {"gen:3": "/x/c.mp4"}, "/x/o.mp4")
    graph = argv[argv.index("-filter_complex") + 1]
    assert "color=c=black" in graph and "anullsrc" in graph and "loudnorm" not in graph


def test_two_video_tracks_are_refused_not_flattened():
    doc = _tiny_doc()
    doc["tracks"].append({"id": "V2", "kind": "video", "clips": [
        {"id": "c2", "media": "gen:1", "src_in": 0, "src_out": 30, "at": 0, "speed": 1}]})
    with pytest.raises(render.RenderError, match="one video track"):
        render.compile_args(doc, {"gen:1": "/x"}, "/x/o.mp4")


def test_ass_captions_are_timed_and_escaped():
    doc = {**_tiny_doc(90), "tracks": _tiny_doc(90)["tracks"] + [
        {"id": "T1", "kind": "caption", "style": "preset:bold_center",
         "cues": [{"id": "q1", "start": 15, "end": 75, "text": "a {brace}\nnext"}]}]}
    ass = render.ass_document(doc)
    assert "Dialogue: 0,0:00:00.50,0:00:02.50,S1,,0,0,0,,a (brace)\\Nnext" in ass
    assert "PlayResY: 1280" in ass
    assert render.ass_document(_tiny_doc()) is None


# --------------------------------------------------------------------------
# render: for real
# --------------------------------------------------------------------------

def _loudness(path):
    out = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af",
                          "ebur128", "-f", "null", "-"], capture_output=True, text=True).stderr
    return float(re.findall(r"I:\s+(-?[\d.]+) LUFS", out)[-1])


@needs_ffmpeg
def test_assemble_and_render_a_finished_mp4(rendered, tmp_path):
    out = assemble.assemble(rendered["concept"], account_id=rendered["a"], workdir=tmp_path,
                            music=rendered["music"], dsn=rendered["dsn"])
    tl = out["timeline"]
    assert tl["version"] == 1 and tl["author"] == "assemble"
    assert "music bed" in tl["op_summary"]
    result = render.render(tl["doc"], account_id=rendered["a"], name="t1",
                           paths=out["paths"], media=out["media"])
    got = sources.probe(result["path"], 30)
    assert got["frames"] == tl["doc"]["duration"] == 360       # 4s + 5s + 3s
    assert (got["width"], got["height"]) == (720, 1280)        # the letterboxed shot fitted
    assert got["audio"] and got["video"]
    assert abs(_loudness(result["path"]) - render.LOUDNESS_LUFS) < 1.0
    assert result["stored"] == "/renders/cut/t1.mp4"
    assert result["url"] == "/renders/cut/t1.mp4"               # R2 off in tests


@needs_ffmpeg
def test_render_resolves_the_handles_itself_and_notes_unburned_captions(rendered, monkeypatch):
    out_doc, _ = assemble.build_doc(
        [{"handle": f"gen:{rendered['gen'][2]}", "label": "c"}],
        {f"gen:{rendered['gen'][2]}": {"frames": 90, "video": True, "audio": False,
                                       "width": 720, "height": 1280},
         rendered["voice"]: {"frames": 180, "video": False, "audio": True}},
        voice=rendered["voice"], captions="One line.")
    monkeypatch.setattr(render, "can_burn_captions", lambda exe=None: False)
    result = render.render(out_doc, account_id=rendered["a"], name="t2", dsn=rendered["dsn"])
    assert any("NOT burned" in n for n in result["notes"])
    assert (render.CUT_DIR / "t2.ass").is_file()
    assert sources.probe(result["path"], 30)["frames"] == 90


@needs_ffmpeg
def test_render_refuses_a_doc_that_lies_about_its_media(rendered):
    doc = _tiny_doc(400)
    doc["tracks"][0]["clips"][0]["media"] = f"gen:{rendered['gen'][2]}"   # a 90-frame file
    with pytest.raises(v.InvalidDoc, match="past the end"):
        render.render(doc, account_id=rendered["a"], name="t3", dsn=rendered["dsn"])


# --------------------------------------------------------------------------
# the routes
# --------------------------------------------------------------------------

@pytest.fixture
def api(rendered, monkeypatch):
    from fastapi.testclient import TestClient

    import app.main as app_main
    from app import auth

    monkeypatch.setenv("DATABASE_URL", rendered["dsn"])
    monkeypatch.setattr(auth, "current_user",
                        lambda request: {"id": "u1", "email": "x@example.com"})
    app_main.app.dependency_overrides[auth.current_account_id] = lambda: rendered["a"]
    yield TestClient(app_main.app), rendered
    app_main.app.dependency_overrides[auth.current_account_id] = lambda: None


def _wait(client, job_id, timeout=60):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] not in ("queued", "running"):
            return job
        time.sleep(0.2)
    raise AssertionError(f"job {job_id} still running")


@needs_ffmpeg
def test_export_from_the_queue_card_end_to_end(api):
    client, r = api
    ready = client.get("/api/cut/ready").json()
    card = next(c for c in ready["ready"] if c["concept_id"] == r["concept"])
    assert card["clips"] == 3 and card["export"] is None and ready["ffmpeg"] is True

    res = client.post("/api/cut/assemble", json={"concept_id": r["concept"],
                                                 "music": r["music"]})
    assert res.status_code == 200, res.text
    job = _wait(client, res.json()["job_id"])
    assert job["status"] == "done", job
    assert job["mp4_url"].startswith("/renders/cut/concept-") and job["version"] == 1
    assert job["seconds"] == pytest.approx(12, abs=0.05)

    card = next(c for c in client.get("/api/cut/ready").json()["ready"]
                if c["concept_id"] == r["concept"])
    assert card["export"]["url"] == job["mp4_url"] and card["export"]["version"] == 1

    # a second export is version 2; rolling back points the card at v1's MP4 again
    second = _wait(client, client.post("/api/cut/assemble",
                                       json={"concept_id": r["concept"]}).json()["job_id"])
    tl = client.get(f"/api/cut/{r['concept']}/timeline").json()
    assert tl["head"]["version"] == 2 and [x["version"] for x in tl["versions"]] == [2, 1]
    assert tl["head"]["export_url"] == second["mp4_url"]
    back = client.post(f"/api/cut/{r['concept']}/rollback",
                       json={"timeline_id": tl["versions"][1]["id"]}).json()
    assert back["head"]["version"] == 1 and back["head"]["export_url"] == job["mp4_url"]


def test_assemble_answers_refusals_before_starting_a_job(api):
    client, r = api
    assert client.post("/api/cut/assemble", json={"concept_id": 999999}).status_code == 404
    with db.connect(r["dsn"]) as conn:
        half = _concept(conn, [_timed_shot(["/renders/runway/a.mp4", None])], r["a"], "half")
    res = client.post("/api/cut/assemble", json={"concept_id": half})
    assert res.status_code == 409
    assert "shot 1 part 2 has no clip yet" in res.json()["error"]["missing"]
    res = client.post("/api/cut/assemble", json={"concept_id": r["concept"], "music": "gen:1"})
    assert res.status_code == 400 and "asset" in res.json()["error"]["message"]
    res = client.post("/api/cut/assemble", json={"concept_id": r["concept"], "music": "asset:999"})
    assert res.status_code == 400


def test_the_ready_list_leaves_out_half_rendered_and_archived_scenes(api):
    client, r = api
    with db.connect(r["dsn"]) as conn:
        half = _concept(conn, [_timed_shot(["/renders/runway/a.mp4", None])], r["a"], "half")
        gone = _concept(conn, [{"n": 1, "media_url": "/renders/runway/a.mp4"}], r["a"], "gone")
        conn.execute("UPDATE shoot_concepts SET archived_at = 't' WHERE id = %s AND "
                     "account_id = %s", (gone, r["a"]))
    ids = [c["concept_id"] for c in client.get("/api/cut/ready").json()["ready"]]
    assert r["concept"] in ids and half not in ids and gone not in ids


def test_another_account_sees_no_cut_and_cannot_export(api):
    import app.main as app_main
    from app import auth
    client, r = api
    app_main.app.dependency_overrides[auth.current_account_id] = lambda: r["b"]
    assert client.get("/api/cut/ready").json()["ready"] == []
    assert client.post("/api/cut/assemble", json={"concept_id": r["concept"]}).status_code == 404
    assert client.get(f"/api/cut/{r['concept']}/timeline").status_code == 404


@needs_ffmpeg
def test_uploading_a_music_bed_gives_an_asset_handle(api, clips, monkeypatch, tmp_path):
    from src.cut import preview
    monkeypatch.setattr(preview, "PREVIEW_DIR", tmp_path / "preview")
    client, r = api
    with open(clips / "music.m4a", "rb") as fh:
        res = client.post("/api/cut/media", files={"file": ("bed.m4a", fh, "audio/mp4")})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["handle"].startswith("asset:") and body["seconds"] == pytest.approx(30, abs=0.1)
    # the upload started its waveform build; let it land in this test's database
    end = time.monotonic() + 60
    while client.get(f"/api/cut/media/{body['handle']}/preview").json()["status"] == "pending":
        assert time.monotonic() < end, "waveform still pending"
        time.sleep(0.2)
    row = store.get_media(int(body["handle"].split(":")[1]), account_id=r["a"], dsn=r["dsn"])
    assert row["filename"] == "bed.m4a" and row["media_url"].startswith("/renders/cut/media/")
    # footage is an upload too since the editor (phase B); a type that is
    # neither audio, video nor an image is still refused
    assert client.post("/api/cut/media",
                       files={"file": ("x.txt", b"words", "text/plain")}).status_code == 400
    assert client.post("/api/cut/media",
                       files={"file": ("x.wav", b"not audio", "audio/wav")}).status_code == 400
