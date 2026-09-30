"""The index (src/cut/index.py + moments.py, CUT_EDITOR.md phase 2).

The three things that would talk to a network -- the Gemini client, fal's
HTTP and the embedder -- are the three seams index_media takes, and every
test here hands in a fake for each. The fixture clips are made with
ffmpeg on the spot.
"""
import hashlib
import json
import math
import shutil
import subprocess
from types import SimpleNamespace

import pytest
from conftest import seed_two  # noqa: E402

from src import db, preprod, render_assets
from src.cut import index, moments

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg/ffprobe not installed")


# --------------------------------------------------------------------------
# fakes
# --------------------------------------------------------------------------

def embed(texts):
    """Bag-of-words hashed into 768 dims: texts sharing words are near."""
    out = []
    for t in texts:
        v = [0.0] * 768
        for w in t.lower().replace(".", " ").replace(",", " ").split():
            v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 768] += 1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        out.append([x / n for x in v])
    return out


class FakeGemini:
    def __init__(self, answer):
        self.answer = answer
        self.calls = 0
        self.models = self

    def generate_content(self, model, contents):
        self.calls += 1
        return SimpleNamespace(text=json.dumps(self.answer) if not isinstance(self.answer, str)
                               else self.answer)


def log_answer(speech, shots=1, **overrides):
    shot = {"summary": "a man laughs at a kitchen table", "people": ["man in a grey coat"],
            "action": "laughs", "objects": ["mug"], "setting": "kitchen interior",
            "emotion": "joy", "shot_size": "medium", "angle": "eye level",
            "camera": "static", "quality": []}
    shot.update(overrides)
    return {"speech": speech, "shots": [dict(shot, n=i + 1) for i in range(shots)]}


class FakeFal:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def __call__(self, url, payload=None):
        self.calls.append((url, payload))
        if payload is not None:
            return {"status_url": "https://queue.fal.run/s", "response_url": "https://queue.fal.run/r"}
        if url.endswith("/s"):
            return {"status": "COMPLETED"}
        return self.result


WHISPER = {"text": "Hello there. I am fine.", "inferred_languages": ["en"],
           "chunks": [{"timestamp": [0.1, 0.4], "text": "Hello"},
                      {"timestamp": [0.45, 0.9], "text": "there."},
                      {"timestamp": [1.2, 1.4], "text": "I"},
                      {"timestamp": [1.45, 1.6], "text": "am"},
                      {"timestamp": [1.65, 2.1], "text": "fine."}],
           "diarization_segments": [{"timestamp": [0.0, 1.0], "speaker": "SPEAKER_00"},
                                    {"timestamp": [1.1, 2.5], "speaker": "SPEAKER_01"}]}


# --------------------------------------------------------------------------
# pure pieces
# --------------------------------------------------------------------------

def test_shots_from_cuts_drops_flash_frames():
    assert index.shots_from_cuts([], 300) == [(0, 300)]
    assert index.shots_from_cuts([120, 125, 295], 300) == [(0, 120), (120, 300)]
    assert index.shots_from_cuts([5], 300) == [(0, 300)]


def test_the_prompt_lists_every_shot_in_seconds():
    p = index.build_prompt([(0, 60), (60, 150)], 30)
    assert "2 shot(s)" in p and "1. 0.00s - 2.00s" in p and "2. 2.00s - 5.00s" in p
    assert '{"speech": false' in p        # the literal braces survived .format


def test_the_log_is_checked_not_trusted():
    raw = "```json\n" + json.dumps(log_answer(True, shots=2, shot_size="cowboy",
                                              quality=["blur", "vibes"])) + "\n```"
    log, notes = index.check_log(raw, [(0, 60), (60, 90)])
    assert log["speech"] is True and len(log["shots"]) == 2
    assert log["shots"][0]["shot_size"] is None                    # off the list: dropped
    assert log["shots"][0]["quality"] == ["blur"]                  # "vibes" is not a flag
    assert any("cowboy" in n for n in notes)


def test_a_log_that_miscounts_or_is_garbage_says_so():
    log, notes = index.check_log(json.dumps(log_answer(False, shots=1)), [(0, 30), (30, 60)])
    assert len(log["shots"]) == 1 and any("1 shot(s) of 2" in n for n in notes)
    log, notes = index.check_log("I cannot see the video", [(0, 30)])
    assert log == {"speech": None, "shots": []} and notes
    log, _ = index.check_log(json.dumps({"speech": "maybe", "shots": []}), [(0, 30)])
    assert log["speech"] is None                                   # only a real bool counts


def test_the_transcript_becomes_words_and_sentences_with_speakers():
    t = index.parse_transcript(WHISPER, 30, 300)
    assert [w["text"] for w in t["words"]] == ["Hello", "there.", "I", "am", "fine."]
    assert t["words"][0] == {"kind": "word", "start_f": 3, "end_f": 12, "text": "Hello",
                             "speaker": "SPEAKER_00"}
    assert [(s["text"], s["speaker"]) for s in t["segments"]] == [
        ("Hello there.", "SPEAKER_00"), ("I am fine.", "SPEAKER_01")]


def test_a_transcript_is_clamped_to_the_clip_and_splits_on_a_pause():
    result = {"chunks": [{"timestamp": [0.0, 0.3], "text": "wait"},
                         {"timestamp": [2.0, 2.3], "text": "now"},
                         {"timestamp": [9.9, 12.0], "text": "late"},
                         {"timestamp": [None, None], "text": "lost"}]}
    t = index.parse_transcript(result, 30, 300)
    assert [s["text"] for s in t["segments"]] == ["wait", "now", "late"]
    assert t["words"][-1]["end_f"] == 300


def test_audio_goes_to_fal_as_a_data_uri_when_there_is_no_bucket(tmp_path):
    p = tmp_path / "a.mp3"
    p.write_bytes(b"ID3fake")
    assert index.audio_url(p, "ab" * 32, None).startswith("data:audio/mpeg;base64,")


# --------------------------------------------------------------------------
# against ffmpeg and the database
# --------------------------------------------------------------------------

def _ff(*args):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


@pytest.fixture(scope="module")
def clips(tmp_path_factory):
    if not HAS_FFMPEG:
        pytest.skip("ffmpeg/ffprobe not installed")
    root = tmp_path_factory.mktemp("index-fixtures")
    enc = ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast"]
    _ff("-f", "lavfi", "-i", "testsrc2=s=720x1280:r=30:d=3", "-f", "lavfi",
        "-i", "sine=f=440:d=3", "-shortest", *enc, "-c:a", "aac", str(root / "talk.mp4"))
    _ff("-f", "lavfi", "-i", "testsrc=s=720x1280:r=30:d=2", *enc, str(root / "silent.mp4"))
    # a hard cut at 2s: two unrelated pictures back to back
    _ff("-f", "lavfi", "-i", "testsrc2=s=720x1280:r=30:d=2", "-f", "lavfi",
        "-i", "color=c=red:s=720x1280:r=30:d=2", "-filter_complex",
        "[0:v][1:v]concat=n=2:v=1:a=0[v]", "-map", "[v]", *enc, str(root / "cut.mp4"))
    _ff("-f", "lavfi", "-i", "sine=f=220:d=4", "-c:a", "aac", str(root / "vo.m4a"))
    return root


@pytest.fixture
def banked(pg, clips, monkeypatch):
    # the meter (spend.record_call) writes wherever DATABASE_URL points
    monkeypatch.setenv("DATABASE_URL", pg)
    preprod.init(pg)
    render_assets.init(pg)
    moments.init(pg)
    from src.cut import store
    store.init(pg)
    seed_two("mike@example.com", dsn=pg)
    with db.connect(pg) as conn:
        a = conn.execute("SELECT id FROM accounts WHERE slug='zeropage'").fetchone()["id"]
        b = conn.execute("SELECT id FROM accounts WHERE slug='antihero'").fetchone()["id"]
        cid = conn.execute(
            "INSERT INTO shoot_concepts (created_at, brand, title, shots_json, account_id) "
            "VALUES ('t', 'zeropage', 'Kitchen Laugh', %s, %s) RETURNING id",
            (json.dumps([{"n": 1, "media_url": "/renders/runway/talk.mp4"}]), a)).fetchone()["id"]
        ids = {}
        for n, name in enumerate(("talk", "silent", "cut"), 1):
            ids[name] = conn.execute(
                "INSERT INTO generated_assets (created_at, generation_id, tool, model, media_kind, "
                "prompt, media_url, output_path, concept_id, account_id) VALUES ('t', %s, 'runway', "
                "'gen4_turbo', 'video', 'p', %s, %s, %s, %s) RETURNING id",
                (n, f"/renders/runway/{name}.mp4", str(clips / f"{name}.mp4"),
                 cid if name == "talk" else None, a)).fetchone()["id"]
    vo = store.add_media(account_id=a, kind="audio", filename="vo.m4a",
                         media_url="/renders/cut/media/vo.m4a", output_path=str(clips / "vo.m4a"),
                         seconds=4, sha256=None, dsn=pg)
    return {"dsn": pg, "a": a, "b": b, "concept": cid, "vo": f"asset:{vo['id']}",
            **{k: f"gen:{v}" for k, v in ids.items()}}


@needs_ffmpeg
def test_a_hard_cut_is_found(clips):
    cuts = index.shot_cuts(clips / "cut.mp4")
    assert len(cuts) == 1 and abs(cuts[0] - 60) <= 2
    assert index.shot_cuts(clips / "silent.mp4") == []


@needs_ffmpeg
def test_a_talking_clip_is_logged_transcribed_and_embedded(banked):
    gem, fal = FakeGemini(log_answer(True)), FakeFal(WHISPER)
    row = index.index_media(banked["talk"], account_id=banked["a"], dsn=banked["dsn"],
                            gemini=gem, http=fal, embed=embed)
    assert row["status"] == "done" and row["speech"] is True
    assert (row["shots"], row["words"], row["frames"]) == (1, 5, 90)
    assert gem.calls == 1
    body = fal.calls[0][1]
    assert body["chunk_level"] == "word" and body["diarize"] is True
    assert body["audio_url"].startswith("data:audio/mpeg;base64,")
    got = moments.moments_for(banked["talk"], account_id=banked["a"], dsn=banked["dsn"])
    assert sorted({m["kind"] for m in got}) == ["segment", "shot", "word"]
    shot = next(m for m in got if m["kind"] == "shot")
    assert shot["tags"]["shot_size"] == "medium" and "laughs" in shot["text"]
    with db.connect(banked["dsn"]) as conn:
        n = conn.execute("SELECT count(*) AS n FROM media_moments WHERE embedding IS NOT NULL "
                         "AND account_id = %s", (banked["a"],)).fetchone()["n"]
        spent = conn.execute("SELECT stage, cost_usd FROM llm_calls WHERE stage IN "
                             "('shot_log', 'transcribe') AND account_id = %s ORDER BY stage",
                             (banked["a"],)).fetchall()
    assert n == 3                                   # the shot and two sentences, not the words
    assert [(r["stage"], r["cost_usd"]) for r in spent][1] == ("transcribe", None)   # unpriced


@needs_ffmpeg
def test_no_speech_and_no_sound_never_reach_whisper(banked):
    fal = FakeFal(WHISPER)
    row = index.index_media(banked["talk"], account_id=banked["a"], dsn=banked["dsn"],
                            gemini=FakeGemini(log_answer(False)), http=fal, embed=embed)
    assert row["status"] == "done" and row["words"] == 0 and fal.calls == []
    row = index.index_media(banked["silent"], account_id=banked["a"], dsn=banked["dsn"],
                            gemini=FakeGemini(log_answer(True)), http=fal, embed=embed)
    assert row["has_audio"] is False and row["words"] == 0 and fal.calls == []


@needs_ffmpeg
def test_an_unreadable_log_holds_the_transcript_back_and_says_why(banked):
    fal = FakeFal(WHISPER)
    row = index.index_media(banked["talk"], account_id=banked["a"], dsn=banked["dsn"],
                            gemini=FakeGemini("no idea"), http=fal, embed=embed)
    assert fal.calls == [] and "could not say whether anyone speaks" in row["notes"]
    assert row["shots"] == 1                        # the shot is still indexed, unlogged


@needs_ffmpeg
def test_a_voiceover_upload_goes_straight_to_the_transcript(banked):
    gem, fal = FakeGemini(log_answer(True)), FakeFal(WHISPER)
    row = index.index_media(banked["vo"], account_id=banked["a"], dsn=banked["dsn"],
                            gemini=gem, http=fal, embed=embed)
    assert row["status"] == "done" and row["words"] == 5 and gem.calls == 0


@needs_ffmpeg
def test_an_indexed_file_is_skipped_until_it_changes_or_is_forced(banked):
    kw = dict(account_id=banked["a"], dsn=banked["dsn"], http=FakeFal(WHISPER), embed=embed)
    index.index_media(banked["talk"], gemini=FakeGemini(log_answer(True)), **kw)
    gem = FakeGemini(log_answer(True))
    assert index.index_media(banked["talk"], gemini=gem, **kw)["skipped"] == "already indexed"
    assert gem.calls == 0
    again = index.index_media(banked["talk"], gemini=gem, force=True, **kw)
    assert again.get("skipped") is None and gem.calls == 1
    assert len(moments.moments_for(banked["talk"], account_id=banked["a"], kind="shot",
                                   dsn=banked["dsn"])) == 1        # replaced, not doubled


@needs_ffmpeg
def test_a_failed_step_is_recorded_not_raised(banked):
    class Broken(FakeGemini):
        def generate_content(self, model, contents):
            raise ValueError("model exploded")
    row = index.index_media(banked["talk"], account_id=banked["a"], dsn=banked["dsn"],
                            gemini=Broken(None), http=FakeFal(WHISPER), embed=embed)
    assert row["status"] == "failed" and "model exploded" in row["notes"]
    assert not moments.is_current(banked["talk"], "x", account_id=banked["a"], dsn=banked["dsn"])


@needs_ffmpeg
def test_embedding_trouble_still_indexes_for_word_search(banked):
    def broken(texts):
        raise RuntimeError("quota")
    row = index.index_media(banked["talk"], account_id=banked["a"], dsn=banked["dsn"],
                            gemini=FakeGemini(log_answer(True)), http=FakeFal(WHISPER),
                            embed=broken)
    assert row["status"] == "done" and "without embeddings" in row["notes"]


def test_another_accounts_clip_does_not_index(banked):
    row = index.index_media(banked["talk"], account_id=banked["b"], dsn=banked["dsn"],
                            gemini=FakeGemini(log_answer(True)), http=FakeFal(WHISPER), embed=embed)
    assert row["status"] == "failed" and "unknown media handle" in row["notes"]


# --------------------------------------------------------------------------
# search
# --------------------------------------------------------------------------

@pytest.fixture
def searchable(banked):
    for h, answer in ((banked["talk"], log_answer(True)),
                      (banked["cut"], log_answer(False, shots=2, summary="a red wall, then a test pattern",
                                                 people=[], action="nothing moves",
                                                 setting="studio", emotion="calm",
                                                 shot_size="wide"))):
        index.index_media(h, account_id=banked["a"], dsn=banked["dsn"], gemini=FakeGemini(answer),
                          http=FakeFal(WHISPER), embed=embed)
    return banked


def q(text):
    return embed([text])[0]


@needs_ffmpeg
def test_search_finds_the_shot_by_meaning_and_the_line_by_its_words(searchable):
    s = searchable
    found = index.find("the man laughing in the kitchen", account_id=s["a"], dsn=s["dsn"], embed_query=q)
    top = found["results"][0]
    assert top["media"] == s["talk"] and top["kind"] == "shot"
    assert top["concept_title"] == "Kitchen Laugh" and top["concept_id"] == s["concept"]
    assert top["start_s"] == 0.0 and top["end_s"] == 3.0
    line = index.find("fine", account_id=s["a"], dsn=s["dsn"], embed_query=q)["results"][0]
    assert line["text"] in ("fine.", "I am fine.") and "words" in line["matched"]


@needs_ffmpeg
def test_search_without_an_embedder_still_answers_by_words(searchable):
    def dead(text):
        raise RuntimeError("no key")
    found = index.find("red wall", account_id=searchable["a"], dsn=searchable["dsn"],
                       embed_query=dead)
    assert found["results"] and found["results"][0]["media"] == searchable["cut"]
    assert any("words only" in n for n in found["notes"])


@needs_ffmpeg
def test_search_never_shows_another_account_anything(searchable):
    found = index.find("laughs", account_id=searchable["b"], dsn=searchable["dsn"], embed_query=q)
    assert found["results"] == []


def test_an_empty_search_and_an_empty_index(pg):
    moments.init(pg)
    assert moments.search("", account_id=None, dsn=pg)["results"] == []
    assert moments.search("anything", account_id=None, dsn=pg)["results"] == []


# --------------------------------------------------------------------------
# the pill and the routes
# --------------------------------------------------------------------------

def test_the_pill_tool_is_a_read_that_refuses_urls():
    from src import guide_tools
    assert "search_footage" in guide_tools.LOCAL_READ and not guide_tools.is_write("search_footage")
    with pytest.raises(guide_tools.Refused):
        guide_tools.check_args("search_footage", {"query": "https://x.com/a.mp4"})
    with pytest.raises(guide_tools.Refused):
        guide_tools.check_args("search_footage", {"query": "  "})
    assert guide_tools.check_args("search_footage", {"query": "laugh", "k": True})["k"] == 8


def test_the_model_reads_handles_and_times_never_urls():
    from src import assistant_brain
    text = assistant_brain.footage_for_model({"results": [
        {"media": "gen:85", "concept_id": 375, "concept_title": "Neon City Ascent",
         "start_s": 1.0, "end_s": 4.5, "kind": "shot", "speaker": None,
         "text": "a man walks in the rain", "media_url": "https://pub.r2.dev/x.mp4"}],
        "notes": []})
    assert "gen:85" in text and "Neon City Ascent (concept #375)" in text and "1.0-4.5s" in text
    assert "http" not in text
    assert "not be indexed" in assistant_brain.footage_for_model({"results": [], "notes": []})


@pytest.fixture
def api(banked, monkeypatch):
    from fastapi.testclient import TestClient

    import app.main as app_main
    from app import auth
    monkeypatch.setenv("DATABASE_URL", banked["dsn"])
    monkeypatch.setattr(auth, "current_user", lambda request: {"id": "u1", "email": "x@example.com"})
    app_main.app.dependency_overrides[auth.current_account_id] = lambda: banked["a"]
    yield TestClient(app_main.app), banked
    app_main.app.dependency_overrides[auth.current_account_id] = lambda: None


@needs_ffmpeg
def test_the_index_route_runs_a_job_over_a_concepts_clips(api, monkeypatch):
    import time
    client, b = api
    seen = []
    monkeypatch.setattr(index, "index_media", lambda h, **kw: seen.append(h) or
                        {"media": h, "status": "done", "shots": 1, "words": 0})
    res = client.post("/api/cut/index", json={"concept_id": b["concept"]})
    assert res.status_code == 200 and res.json()["handles"] == [b["talk"]]
    for _ in range(100):
        job = client.get(f"/api/jobs/{res.json()['job_id']}").json()
        if job["status"] not in ("queued", "running"):
            break
        time.sleep(0.05)
    assert job["status"] == "done" and seen == [b["talk"]] and "1 indexed" in job["detail"]
    assert client.post("/api/cut/index", json={"concept_id": 99999}).status_code == 404


def test_the_search_route_refuses_an_empty_query_and_answers_a_real_one(api, monkeypatch):
    client, b = api
    assert client.get("/api/cut/search?q=").status_code == 400
    monkeypatch.setattr(index, "find", lambda q, **kw: {"results": [
        {"media": "gen:1", "media_url": "/renders/runway/talk.mp4"}], "notes": []})
    out = client.get("/api/cut/search?q=laugh").json()
    assert out["results"][0]["media_url"] == "/renders/runway/talk.mp4"
