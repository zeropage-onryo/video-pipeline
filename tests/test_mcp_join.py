"""
Joining clips from the studio MCP (2026-10-09, docs/tasks/
task-mcp-studio-v2.md step 2a): `assemble_clips`.

What is guarded: the refusals come before anything is written (a URL, an
image, a deleted render, an unreadable file, clips of two shapes unless
letterboxed, a crossfade too long for the shortest clip, music that is not
an audio upload); the cut is built by the same builder Assemble uses, with
the crossfades and the music bed in the right place; and -- with real
ffmpeg -- three clips come back as ONE MP4 on the Assets wall, as a
`gen:<id>` the next tool can name, with nothing held or charged.
"""

import asyncio
import shutil
import subprocess
from pathlib import Path

import pytest

from src import mcp_server, mcp_shapes, preprod, scout
from src.cut import doc as d
from src.cut import join

FPS = d.DEFAULT_FPS


# --------------------------------------------------------------------------
# plan: every refusal, with no files (the wall and the probe stood in for)
# --------------------------------------------------------------------------

def _world(monkeypatch, assets=None, media=None, uploads=None):
    from src import render_assets
    from src.cut import sources, store
    assets = assets if assets is not None else {
        i: {"id": i, "media_kind": "video", "media_url": f"/renders/fal/{i}.mp4"}
        for i in (1, 2, 3)}
    media = media if media is not None else {
        f"gen:{i}": {"frames": 5 * FPS, "seconds": 5.0, "video": True, "audio": True,
                     "still": False, "width": 720, "height": 1280} for i in (1, 2, 3)}
    monkeypatch.setattr(render_assets, "get",
                        lambda i, dsn=None, account_id=None: assets.get(int(i)))
    monkeypatch.setattr(sources, "measure",
                        lambda handles, **kw: {h: media.get(h) for h in handles if h in media})
    monkeypatch.setattr(store, "get_media",
                        lambda i, account_id=None, dsn=None: (uploads or {}).get(int(i)))
    return media


@pytest.mark.parametrize("handles, kwargs, match", [
    (["gen:1"], {}, "at least 2"),
    ([f"gen:{i}" for i in range(25)], {}, "at most 20"),
    (["gen:1", "https://x/a.mp4"], {}, "URLs are never taken"),
    (["gen:1", "asset:4"], {}, "a clip is gen:<id>"),
    (["gen:1", "gen:9"], {}, "no render 9"),
    (["gen:1", "gen:2"], {"transition": "wipe"}, "transition must be one of"),
    (["gen:1", "gen:2"], {"transition": "crossfade", "crossfade_s": 5}, "0.1-2.0 seconds"),
    (["gen:1", "gen:2"], {"music": "gen:3"}, "music is an asset:<id>"),
    (["gen:1", "gen:2"], {"music": "asset:7"}, "no audio upload 7"),
])
def test_refusals_come_before_anything_is_made(monkeypatch, handles, kwargs, match):
    _world(monkeypatch)
    with pytest.raises(join.JoinRefused, match=match):
        join.plan(handles, account_id=1, **kwargs)


def test_an_image_or_a_deleted_render_is_refused(monkeypatch):
    _world(monkeypatch, assets={
        1: {"id": 1, "media_kind": "video"}, 2: {"id": 2, "media_kind": "image"},
        3: {"id": 3, "media_kind": "video", "deleted_at": "2026-10-01"}})
    with pytest.raises(join.JoinRefused, match="gen:2 is an image"):
        join.plan(["gen:1", "gen:2"], account_id=1)
    with pytest.raises(join.JoinRefused, match="no render 3"):
        join.plan(["gen:1", "gen:3"], account_id=1)


def test_an_unreadable_file_is_refused(monkeypatch):
    media = _world(monkeypatch)
    media["gen:2"] = None
    with pytest.raises(join.JoinRefused, match="could not read gen:2"):
        join.plan(["gen:1", "gen:2"], account_id=1)


def test_two_shapes_are_refused_unless_letterboxed(monkeypatch):
    media = _world(monkeypatch)
    media["gen:2"] = {**media["gen:2"], "width": 1280, "height": 720}
    with pytest.raises(join.JoinRefused, match=r"gen:1 is 9:16, gen:2 is 16:9.*letterbox"):
        join.plan(["gen:1", "gen:2"], account_id=1)
    planned = join.plan(["gen:1", "gen:2"], account_id=1, letterbox=True)
    assert planned["letterboxed"] == ["gen:2"]
    assert planned["canvas"] == {"width": 720, "height": 1280, "aspect": "9:16"}


def test_one_shape_at_two_sizes_is_one_shape(monkeypatch):
    media = _world(monkeypatch)
    media["gen:2"] = {**media["gen:2"], "width": 1080, "height": 1920}
    assert join.plan(["gen:1", "gen:2"], account_id=1)["letterboxed"] == []


def test_a_crossfade_longer_than_half_the_shortest_clip_is_refused(monkeypatch):
    media = _world(monkeypatch)
    media["gen:2"] = {**media["gen:2"], "frames": FPS, "seconds": 1.0}
    with pytest.raises(join.JoinRefused, match="at least 2s long; gen:2 is 1.0s"):
        join.plan(["gen:1", "gen:2"], account_id=1, transition="crossfade", crossfade_s=1)


def test_a_still_is_not_a_clip(monkeypatch):
    media = _world(monkeypatch)
    media["gen:2"] = {**media["gen:2"], "still": True}
    with pytest.raises(join.JoinRefused, match="no moving picture"):
        join.plan(["gen:1", "gen:2"], account_id=1)


# --------------------------------------------------------------------------
# plan: the cut it builds
# --------------------------------------------------------------------------

def test_a_hard_cut_join_is_the_clips_in_order_with_their_sound(monkeypatch):
    _world(monkeypatch)
    planned = join.plan(["gen:2", "gen:1", "gen:2"], account_id=1)
    doc = planned["doc"]
    assert [c["media"] for c in d.track(doc, "V1")["clips"]] == ["gen:2", "gen:1", "gen:2"]
    assert len(d.track(doc, "A1")["clips"]) == 3          # each clip's own sound, linked
    assert doc["duration"] == 15 * FPS and planned["seconds"] == 15.0


def test_crossfades_overlap_every_cut_and_shorten_the_whole(monkeypatch):
    _world(monkeypatch)
    planned = join.plan(["gen:1", "gen:2", "gen:3"], account_id=1, transition="crossfade",
                        crossfade_s=0.5)
    doc, frames = planned["doc"], round(0.5 * FPS)
    clips = d.track(doc, "V1")["clips"]
    assert [bool(c.get("transition_in")) for c in clips] == [False, True, True]
    assert all(c["transition_in"]["frames"] == frames for c in clips[1:])
    assert doc["duration"] == 15 * FPS - 2 * frames
    markers = [m["frame"] for m in doc.get("markers") or []]
    assert markers == [c["at"] for c in clips]             # each label where its clip begins


def test_music_is_trimmed_to_the_picture_and_ducked(monkeypatch):
    media = _world(monkeypatch, uploads={4: {"id": 4, "kind": "audio"}})
    media["asset:4"] = {"frames": 60 * FPS, "seconds": 60.0, "video": False, "audio": True,
                        "still": False, "width": None, "height": None}
    planned = join.plan(["gen:1", "gen:2"], account_id=1, music="asset:4",
                        transition="crossfade", crossfade_s=0.5)
    doc = planned["doc"]
    (bed,) = d.track(doc, "A2")["clips"]
    assert bed["media"] == "asset:4" and d.clip_end(bed) == doc["duration"]
    assert d.track(doc, "A2")["duck_under"] == "sfx"      # under the clips' own sound


def test_music_must_be_sound(monkeypatch):
    media = _world(monkeypatch, uploads={4: {"id": 4, "kind": "audio"}})
    media["asset:4"] = {**media["gen:1"]}                  # a video file filed as audio
    with pytest.raises(join.JoinRefused, match="not an audio file"):
        join.plan(["gen:1", "gen:2"], account_id=1, music="asset:4")


# --------------------------------------------------------------------------
# the conversation, with real ffmpeg: three clips in, one MP4 on the wall
# --------------------------------------------------------------------------

needs_ffmpeg = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
                                  reason="ffmpeg is not installed")


def _clip(path: Path, seconds: float, size: str = "160x284", tone: int = 440) -> Path:
    subprocess.run(["ffmpeg", "-v", "error", "-y",
                    "-f", "lavfi", "-t", str(seconds), "-i", f"testsrc=size={size}:rate={FPS}",
                    "-f", "lavfi", "-t", str(seconds), "-i", f"sine=frequency={tone}:sample_rate=48000",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)],
                   check=True, capture_output=True)
    return path


@pytest.fixture
def wall(pg, tmp_path, monkeypatch):
    """Three clips on the wall and one audio upload, on a real database."""
    from src import accounts, db, entities, generative, ledger, projects, render_assets
    from src.cut import store
    preprod.init(pg)
    scout.init(pg)
    entities.init(pg)
    generative.init(pg)
    render_assets.init(pg)
    projects.init(pg)
    store.init(pg)
    ledger.init(pg)
    accounts.seed("mike@example.com", dsn=pg)
    with db.connect(pg) as conn:
        acct = int(conn.execute("SELECT MIN(id) AS id FROM accounts").fetchone()["id"])
    monkeypatch.setattr(render_assets, "_ingest",
                        lambda *a, **k: {"ok": True, "chunks": 1, "error": None})
    ids = []
    for i, tone in enumerate((330, 440, 550), start=1):
        path = _clip(tmp_path / f"clip{i}.mp4", 2.0, tone=tone)
        row = render_assets.record(generation_id=9000 + i, tool="ltx", model="ltx2.3",
                                   media_kind="video", prompt=f"clip {i}",
                                   media_url=f"/renders/fal/clip{i}.mp4",
                                   output_path=str(path), account_id=acct, dsn=pg)
        ids.append(f"gen:{row['id']}")
    song = tmp_path / "bed.m4a"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-t", "20", "-i",
                    "sine=frequency=220:sample_rate=48000", "-c:a", "aac", str(song)],
                   check=True, capture_output=True)
    up = store.add_media(account_id=acct, kind="audio", filename="bed.m4a",
                         media_url="/renders/cut/media/bed.m4a", output_path=str(song),
                         seconds=20.0, sha256=None, dsn=pg)
    started, results = [], []

    def start_job(kind, label, fn, cancellable=False, account_id=None):
        started.append(label)
        results.append(fn({})["result"])        # the job's body, inline
        return {"id": 77, "status": "done"}

    server = mcp_server.build_server(dsn=pg, surface="studio", start_job=start_job,
                                     job_status=lambda i, account_id=None: None,
                                     account_id=acct)
    return {"dsn": pg, "account_id": acct, "clips": ids, "music": f"asset:{up['id']}",
            "server": server, "started": started, "results": results}


def _call(server, tool, args):
    return asyncio.run(server.call_tool(tool, args))


@needs_ffmpeg
def test_three_clips_become_one_mp4_on_the_wall_for_free(wall):
    from src import db, ledger, render_assets
    from src.cut import sources
    res = _call(wall["server"], "assemble_clips", {
        "clips": wall["clips"], "transition": "crossfade", "crossfade_s": 0.5,
        "music": wall["music"]})
    out = res.structured_content
    mcp_shapes.SHAPES["assemble_clips"].model_validate(out)
    assert out["job_id"] == 77 and wall["started"] == ["join 3 clips"]
    assert out["plan"]["seconds"] == pytest.approx(5.0, abs=0.05)      # 3 x 2s - 2 x 0.5s
    assert "no credits" in res.content[0].text

    result = _call(wall["server"], "assemble_clips", {
        "clips": wall["clips"], "transition": "crossfade", "crossfade_s": 0.5,
        "music": wall["music"]})                                      # once more, inline below
    assert result.structured_content["job_id"] == 77

    # what the job made, read back off the wall
    with db.connect(wall["dsn"]) as conn:
        rows = conn.execute("SELECT id FROM generated_assets WHERE tool = 'cut' "
                            "AND account_id = %s", (wall["account_id"],)).fetchall()
    assert len(rows) == 2
    asset = render_assets.get(rows[0]["id"], wall["dsn"], account_id=wall["account_id"])
    assert asset["media_kind"] == "video" and asset["media_url"].startswith("/renders/cut/")
    made = sources.probe(Path(asset["output_path"]), FPS)
    assert made["video"] and made["audio"] and made["seconds"] == pytest.approx(5.0, abs=0.15)
    assert (made["width"], made["height"]) == (160, 284)
    # the cut is a scratch project the editor can open, its export recorded
    with db.connect(wall["dsn"]) as conn:
        cut = conn.execute("SELECT timeline_key FROM cut_projects WHERE account_id = %s "
                           "ORDER BY created_at LIMIT 1", (wall["account_id"],)).fetchone()
        exported = conn.execute("SELECT export_url FROM timelines WHERE project_id = %s "
                                "AND account_id = %s", (cut["timeline_key"],
                                                        wall["account_id"])).fetchone()
    assert cut["timeline_key"].startswith("cut:") and exported["export_url"]
    first = wall["results"][0]
    assert first["ok"] and first["credits"] == 0 and "no credits" in first["note"]
    assert first["ref"] == f"gen:{first['asset_id']}" and first["cut_project"]["version"] == 1
    # and nothing was held, charged or billed
    assert ledger.entries(wall["account_id"], wall["dsn"]) == []
    with db.connect(wall["dsn"]) as conn:
        costs = [r["cost_usd"] for r in conn.execute(
            "SELECT cost_usd FROM generations WHERE tool = 'cut' AND account_id = %s",
            (wall["account_id"],)).fetchall()]
    assert costs == [None, None]


@needs_ffmpeg
def test_the_joined_clip_is_a_gen_id_the_next_tool_can_name(wall):
    _call(wall["server"], "assemble_clips", {"clips": wall["clips"][:2]})
    ref = wall["results"][0]["ref"]
    assert ref and ref.startswith("gen:")
    again = _call(wall["server"], "assemble_clips", {"clips": [ref, wall["clips"][2]]})
    assert again.structured_content["plan"]["clips"] == [ref, wall["clips"][2]]


@needs_ffmpeg
def test_a_refusal_through_the_tool_is_a_tool_error_and_starts_nothing(wall):
    from mcp.server.mcpserver.exceptions import ToolError
    with pytest.raises(ToolError, match="at least 2"):
        _call(wall["server"], "assemble_clips", {"clips": wall["clips"][:1]})
    assert wall["started"] == []


def test_renders_lists_audio_uploads_as_asset_ids(pg):
    from src import accounts, db, render_assets
    from src.cut import store
    preprod.init(pg)
    render_assets.init(pg)
    store.init(pg)
    accounts.seed("mike@example.com", dsn=pg)
    with db.connect(pg) as conn:
        acct = int(conn.execute("SELECT MIN(id) AS id FROM accounts").fetchone()["id"])
    up = store.add_media(account_id=acct, kind="audio", filename="song.m4a",
                         media_url="/renders/cut/media/song.m4a", output_path=None,
                         seconds=31.5, sha256=None, dsn=pg)
    store.add_media(account_id=acct, kind="video", filename="b-roll.mp4",
                    media_url="/renders/cut/media/b.mp4", output_path=None,
                    seconds=4.0, sha256=None, dsn=pg)
    out = mcp_server.list_renders(kind="audio", dsn=pg, account_id=acct)
    assert [r["id"] for r in out["renders"]] == [f"asset:{up['id']}"]
    assert out["renders"][0]["prompt"] == "song.m4a" and out["renders"][0]["seconds"] == 31.5
    assert all(not r["id"].startswith("asset:")
               for r in mcp_server.list_renders(dsn=pg, account_id=acct)["renders"])
