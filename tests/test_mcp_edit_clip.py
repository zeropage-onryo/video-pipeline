"""
`edit_clip` -- a clip changed by instruction, one frame first (2026-10-10,
docs/tasks/task-mcp-studio-v2.md step 2c).

Two spends, each quoted and approved on its own: a frame edited as a still
(cents), then the whole clip (dollars) -- and the second is only taken with
the frame the first one made from THAT clip with THAT instruction. What is
guarded: the model table's limits and prices as read on 2026-10-10, the
wire body each model gets, the frame gate, and the whole conversation on
the real ledger with only fal's wire stood in for.
"""

import asyncio
import shutil
import subprocess

import pytest

from src import clip_edit, effects, fal, ledger, mcp_server, mcp_shapes, pricing

needs_ffmpeg = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
                                  reason="ffmpeg is not installed")
CLIP = {"seconds": 8.0, "width": 720, "height": 1280, "fps": 24.0}


# --------------------------------------------------------------------------
# the table
# --------------------------------------------------------------------------

def test_the_models_are_the_ones_the_research_chose():
    assert clip_edit.MODEL_NAMES == ("kling-o1", "kling-o1-pro", "flux-3")
    assert clip_edit.DEFAULT_MODEL == "kling-o1" and clip_edit.CHECKED == "2026-10-10"
    endpoints = {m["endpoint"] for m in clip_edit.MODELS.values()}
    assert endpoints == {"fal-ai/kling-video/o1/standard/video-to-video/edit",
                         "fal-ai/kling-video/o1/video-to-video/edit",
                         "blackforestlabs/flux-3/edit-video"}
    for m in clip_edit.MODELS.values():
        assert m["source"].startswith("https://fal.ai/models/")
    # never one call away: these are not effects apply_effect can run
    assert not set(clip_edit.MODELS) & set(effects.EFFECTS)
    assert not {r["endpoint"] for r in effects.EFFECTS.values()} & endpoints


@pytest.mark.parametrize("model, seconds, usd", [
    ("kling-o1", 8.0, 1.008), ("kling-o1-pro", 8.0, 1.344), ("flux-3", 8.0, 0.24),
    ("kling-o1", 5.04, 0.635),
])
def test_the_video_is_priced_per_second_of_the_clip(model, seconds, usd):
    assert clip_edit.video_usd(model, {**CLIP, "seconds": seconds}) == usd


def test_the_frame_costs_one_still_edit():
    assert clip_edit.frame_usd() == 0.039 == effects.quote_usd(clip_edit.FRAME_EFFECT, {})


@pytest.mark.parametrize("model, probe, kwargs, match", [
    ("kling-o1", {**CLIP, "seconds": 2.0}, {}, "at least 3s"),
    ("kling-o1", {**CLIP, "seconds": 12.0}, {}, "up to 10.05s"),
    ("kling-o1-pro", {**CLIP, "width": 480, "height": 854}, {}, "at least 720px"),
    ("kling-o1", {**CLIP, "width": 2160, "height": 3840}, {}, "at most 2160px"),
    ("kling-o1", {**CLIP, "fps": 12.0}, {}, "24-60fps"),
    ("kling-o1", CLIP, {"suffix": ".webm"}, "takes .mp4 / .mov"),
    ("kling-o1", CLIP, {"size_bytes": 300 * 1024 * 1024}, "up to 200MB"),
    ("flux-3", {**CLIP, "seconds": 16.0}, {}, "up to 15s"),
    ("flux-3", CLIP, {"suffix": ".mov"}, "takes .mp4 files"),
    ("flux-3", CLIP, {"size_bytes": 60 * 1024 * 1024}, "up to 50MB"),
])
def test_a_clip_outside_a_models_published_limits_is_refused(model, probe, kwargs, match):
    with pytest.raises(ValueError, match=match):
        clip_edit.check_clip(model, probe, **kwargs)


def test_a_clip_inside_the_limits_passes_and_a_10s_render_is_one():
    clip_edit.check_clip("kling-o1", {**CLIP, "seconds": 10.04}, suffix=".mp4")
    clip_edit.check_clip("flux-3", {**CLIP, "width": 480, "height": 854}, suffix=".mp4")


def test_every_model_is_priced_or_explained_for_this_clip():
    rows = {r["model"]: r for r in clip_edit.options_for({**CLIP, "seconds": 12.0},
                                                         suffix=".mp4")}
    assert "up to 10.05s" in rows["kling-o1"]["cannot"] and "usd" not in rows["kling-o1"]
    assert rows["flux-3"]["usd"] == 0.36 and rows["flux-3"]["frame_steers"] is False
    assert rows["kling-o1"]["frame_steers"] is True


def test_the_wire_bodies_follow_each_schema():
    endpoint, body = clip_edit.video_body("kling-o1", "https://v", "make the jacket red.",
                                          frame_url="https://f", keep_audio=False)
    assert endpoint.endswith("o1/standard/video-to-video/edit")
    assert body["video_url"] == "https://v" and body["image_urls"] == ["https://f"]
    assert body["prompt"].startswith("make the jacket red. Match @Image1")
    assert body["keep_audio"] is False
    endpoint, body = clip_edit.video_body("flux-3", "https://v", "make the jacket red",
                                          frame_url="https://f")
    assert endpoint == "blackforestlabs/flux-3/edit-video"
    assert body == {"video_url": "https://v", "prompt": "make the jacket red"}   # no frame, no audio


def test_an_instruction_is_required_and_bounded():
    assert clip_edit.normal("  make  it   dusk ") == "make it dusk"
    with pytest.raises(ValueError, match="say what to change"):
        clip_edit.normal("   ")
    with pytest.raises(ValueError, match="at most"):
        clip_edit.normal("x" * 2000)


@needs_ffmpeg
def test_a_frame_is_pulled_from_a_real_clip(tmp_path):
    clip = tmp_path / "c.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-t", "2", "-i",
                    "testsrc=size=160x284:rate=24", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    str(clip)], check=True, capture_output=True)
    out = clip_edit.extract_frame(str(clip), 1.0, tmp_path / "f" / "frame.jpg")
    from PIL import Image
    assert Image.open(out).size == (160, 284)
    with pytest.raises(ValueError, match="could not take a frame"):
        clip_edit.extract_frame(str(tmp_path / "missing.mp4"), 0, tmp_path / "x.jpg")


# --------------------------------------------------------------------------
# the tool, with the wall and fal stood in for
# --------------------------------------------------------------------------

@pytest.fixture
def signed(monkeypatch):
    monkeypatch.setenv(pricing.SIGNING_ENV, "test-quote-secret")


@pytest.fixture
def world(monkeypatch, tmp_path):
    """One 8s clip on the wall (gen:3), and room for frames stage 1 makes."""
    from src import render_assets
    wall = {3: {"id": 3, "media_kind": "video", "media_url": "https://r2/clip.mp4",
                "output_path": ""}}
    monkeypatch.setattr(render_assets, "get",
                        lambda i, dsn=None, account_id=None: wall.get(int(i)))
    monkeypatch.setattr(effects, "probe_video", lambda t: dict(CLIP))
    monkeypatch.setattr(effects, "fetchable_video",
                        lambda url, local="", account_id=None: url)
    monkeypatch.setattr(clip_edit, "extract_frame",
                        lambda target, at, out: (out.parent.mkdir(parents=True, exist_ok=True),
                                                 out.write_bytes(b"\xff\xd8 jpeg"), out)[2])
    monkeypatch.setattr(fal, "as_image_url", lambda v, **kw: "https://r2/frame.jpg")
    monkeypatch.setattr(mcp_server, "_fetchable", lambda raw, acct: raw)
    calls = []

    def run(effect, urls, prompt, opts, **kw):
        calls.append({"effect": effect, "urls": urls, "prompt": prompt, "opts": opts, **kw})
        asset = 40 + len(calls)
        kind = "video" if effect.startswith("edit-") else "image"
        wall[asset] = {"id": asset, "media_kind": kind,
                       "media_url": f"https://r2/out{asset}", "metadata": kw.get("extra") or {}}
        return {"ok": True, "media_url": f"https://r2/out{asset}", "asset_id": asset,
                "media_kind": kind, "error": None}

    monkeypatch.setattr(effects, "run", run)
    return {"wall": wall, "calls": calls}


ASK = dict(source="gen:3", instruction="make the jacket red")


def _yes(**kwargs):
    q = mcp_server.run_edit_clip(**kwargs)
    assert q["needs_approval"] is True, q
    return q, mcp_server.run_edit_clip(**kwargs, quote_token=q["quote"]["quote_token"])


def test_the_frame_is_quoted_first_and_says_what_the_clip_will_cost(world, signed):
    q = mcp_server.run_edit_clip(**ASK)
    assert q["needs_approval"] and world["calls"] == []
    quote = q["quote"]
    assert quote["stage"] == "frame" and quote["usd"] == 0.039 and quote["credits"] == 10
    then = {r["model"]: r for r in quote["then"]}
    assert then["kling-o1"]["usd"] == 1.008 and then["kling-o1"]["credits"] == 242
    assert then["flux-3"]["credits"] == ledger.charge_credits(0.24)


def test_an_approved_frame_is_edited_filed_and_names_the_next_call(world, signed):
    q, out = _yes(**ASK, at=2.5)
    (c,) = world["calls"]
    assert c["effect"] == clip_edit.FRAME_EFFECT and c["urls"] == ["https://r2/frame.jpg"]
    assert c["prompt"].startswith("make the jacket red. Keep everything else")
    assert c["extra"] == {"edit_clip": {"stage": "frame", "source": "gen:3",
                                        "instruction": "make the jacket red", "at": 2.5}}
    assert c["quote"].credits == q["quote"]["credits"] == 10
    assert out["ok"] and out["frame"] == "gen:41" and 'frame="gen:41"' in out["next"]


@pytest.mark.parametrize("kwargs, match", [
    ({"source": "gen:3", "instruction": "  "}, "say what to change"),
    ({"source": "https://x/c.mp4", "instruction": "x"}, "URLs are never taken"),
    ({"source": "gen:9", "instruction": "x"}, "no render 9"),
    ({**ASK, "stage": "preview"}, "stage must be one of"),
    ({**ASK, "at": 99}, "inside the clip"),
    ({**ASK, "stage": "video"}, "needs `frame`"),
    ({**ASK, "stage": "video", "frame": "gen:3"}, "no edited frame"),
    ({**ASK, "stage": "video", "frame": "gen:41", "model": "sora"}, "model must be one of"),
])
def test_refusals_come_before_any_quote(world, signed, kwargs, match):
    with pytest.raises(ValueError, match=match):
        mcp_server.run_edit_clip(**kwargs)
    assert world["calls"] == []


def test_the_video_takes_only_the_frame_made_from_this_clip_and_instruction(world, signed):
    _, frame = _yes(**ASK)
    made = frame["frame"]
    world["wall"][7] = {"id": 7, "media_kind": "image", "media_url": "https://r2/any.jpg",
                        "metadata": {}}
    world["wall"][8] = {"id": 8, "media_kind": "video", "media_url": "https://r2/other.mp4"}
    with pytest.raises(ValueError, match="not a frame this tool edited"):
        mcp_server.run_edit_clip(**ASK, stage="video", frame="gen:7")
    with pytest.raises(ValueError, match="different instruction"):
        mcp_server.run_edit_clip(source="gen:3", instruction="make the jacket blue",
                                 stage="video", frame=made)
    with pytest.raises(ValueError, match="was made from gen:3, not gen:8"):
        mcp_server.run_edit_clip(source="gen:8", instruction=ASK["instruction"],
                                 stage="video", frame=made)
    assert len(world["calls"]) == 1                       # only the frame was ever bought


def test_the_approved_frame_steers_kling_and_the_clip_is_priced_off_its_length(world, signed):
    _, frame = _yes(**ASK)
    q, out = _yes(**ASK, stage="video", frame=frame["frame"], keep_audio=False)
    assert q["quote"]["usd"] == 1.008 and q["quote"]["credits"] == 242
    assert q["quote"]["model"] == "kling-o1" and q["quote"]["frame_steers"] is True
    video = world["calls"][1]
    assert video["effect"] == "edit-kling-o1" and video["row"]["output"] == "video"
    endpoint, body = video["endpoint_body"]
    assert endpoint.endswith("o1/standard/video-to-video/edit")
    assert body["image_urls"] == ["https://r2/out41"] and body["keep_audio"] is False
    assert video["sources"] == ["gen:3", "gen:41"] and video["usd"] == 1.008
    assert video["quote"].credits == 242 and out["ok"] and out["media_kind"] == "video"
    with pytest.raises(ValueError, match="stale_content"):            # a dearer model after the yes
        mcp_server.run_edit_clip(**ASK, stage="video", frame=frame["frame"], keep_audio=False,
                                 model="kling-o1-pro", quote_token=q["quote"]["quote_token"])


def test_flux_follows_the_instruction_only_and_says_so(world, signed):
    _, frame = _yes(**ASK)
    q, _ = _yes(**ASK, stage="video", frame=frame["frame"], model="flux-3")
    assert q["quote"]["frame_steers"] is False and q["quote"]["usd"] == 0.24
    assert "keep_audio" not in q["quote"]
    _, body = world["calls"][1]["endpoint_body"]
    assert body == {"video_url": "https://r2/clip.mp4", "prompt": "make the jacket red"}


def test_a_clip_the_model_cannot_take_is_refused_at_the_video_quote(world, signed, monkeypatch):
    _, frame = _yes(**ASK)
    monkeypatch.setattr(effects, "probe_video", lambda t: {**CLIP, "seconds": 12.0})
    with pytest.raises(ValueError, match="up to 10.05s"):
        mcp_server.run_edit_clip(**ASK, stage="video", frame=frame["frame"])
    q = mcp_server.run_edit_clip(**ASK, stage="video", frame=frame["frame"], model="flux-3")
    assert q["quote"]["usd"] == 0.36


def test_a_frame_that_cannot_reach_the_renderer_fails_without_a_charge(world, signed, monkeypatch):
    monkeypatch.setattr(fal, "as_image_url", lambda v, **kw: None)     # no bucket
    _, out = _yes(**ASK)
    assert out["ok"] is False and "bucket" in out["error"] and world["calls"] == []


def test_edit_clip_is_a_studio_tool_and_answers_typed(pg, world, signed):
    from src import preprod, scout
    preprod.init(pg)
    scout.init(pg)
    server = mcp_server.build_server(dsn=pg, surface="studio")
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert "edit_clip" in names and len(names) == len(mcp_server.STUDIO_TOOLS) - 2   # no job tools here
    res = asyncio.run(server.call_tool("edit_clip", dict(ASK)))
    data = res.structured_content
    mcp_shapes.SpendResult.model_validate(data)
    assert data["state"] == "quote" and data["quote"]["stage"] == "frame"
    assert res.content[0].text.startswith("Quote: 10 credits")
    listed = {t.name for t in asyncio.run(mcp_server.build_server(dsn=pg, listed=True).list_tools())}
    assert "edit_clip" not in listed


# --------------------------------------------------------------------------
# the conversation, on the real ledger and the real wall: frame -> look ->
# video. Only fal's wire, the bucket and ffmpeg's frame pull are stood in for.
# --------------------------------------------------------------------------

@pytest.fixture
def studio(pg, monkeypatch, tmp_path):
    import types

    from src import accounts, db, generative, preprod, quote_redemptions, render_assets, scout
    monkeypatch.setenv("DATABASE_URL", pg)
    monkeypatch.setenv("FAL_KEY", "k")
    monkeypatch.setenv(pricing.SIGNING_ENV, "test-quote-secret")
    monkeypatch.setattr(fal, "POLL_SECONDS", 0)
    for mod in (preprod, scout, generative, render_assets, ledger, quote_redemptions):
        mod.init(pg)
    accounts.seed("mike@example.com", dsn=pg)
    with db.connect(pg) as conn:
        acct = int(conn.execute("SELECT MIN(id) AS id FROM accounts").fetchone()["id"])
    ledger.grant(acct, 1000, "purchase", dsn=pg)
    monkeypatch.setattr(render_assets, "_ingest",
                        lambda *a, **k: {"ok": True, "chunks": 1, "error": None})
    clip = render_assets.record(generation_id=9001, tool="ltx", model="ltx2.3",
                                media_kind="video", prompt="a man in a grey jacket",
                                media_url="https://r2/m/1/renders/fal/clip.mp4",
                                output_path="", account_id=acct, dsn=pg)
    monkeypatch.setattr(effects, "probe_video", lambda t: dict(CLIP))
    monkeypatch.setattr(clip_edit, "extract_frame",
                        lambda target, at, out: (out.parent.mkdir(parents=True, exist_ok=True),
                                                 out.write_bytes(b"\xff\xd8 jpeg"), out)[2])
    monkeypatch.setattr(fal, "as_image_url", lambda v, **kw: (
        v if isinstance(v, str) and v.startswith("https://") else "https://r2/frame.jpg"))
    monkeypatch.setattr(fal, "_download",
                        lambda url, out: (out.parent.mkdir(parents=True, exist_ok=True),
                                          out.write_bytes(b"\x00" * 2048))[1])
    monkeypatch.setattr(fal, "_publish",
                        lambda path, ctype, acct=None: f"https://r2/m/1/renders/fal/{path.name}")
    sent = []

    def wire(url, payload=None, account_id=None):
        if payload is not None and payload is not fal.CANCEL:
            sent.append((url, payload))
            return {"request_id": "r", "status_url": "https://q/s", "response_url": "https://q/r",
                    "cancel_url": "https://q/c"}
        if url == "https://q/s":
            return {"status": "COMPLETED"}
        image = "nano-banana" in sent[-1][0]
        return ({"images": [{"url": "https://cdn/frame-out.jpg"}]} if image
                else {"video": {"url": "https://cdn/edited.mp4"}})

    monkeypatch.setattr(fal, "_request", wire)
    results = []

    def start_job(kind, label, fn, cancellable=False, account_id=None):
        results.append(fn({})["result"])
        return {"id": len(results), "status": "done"}

    server = mcp_server.build_server(dsn=pg, surface="studio", start_job=start_job,
                                     job_status=lambda i, account_id=None: None,
                                     account_id=acct)
    return types.SimpleNamespace(dsn=pg, account_id=acct, server=server, sent=sent,
                                 results=results, clip=f"gen:{clip['id']}")


def _tool(studio, **args):
    return asyncio.run(studio.server.call_tool("edit_clip", args)).structured_content


def test_frame_then_video_charges_each_once_and_only_in_that_order(studio):
    from mcp.server.mcpserver.exceptions import ToolError
    ask = dict(source=studio.clip, instruction="make the jacket red")
    balance = lambda: ledger.available(studio.account_id, dsn=studio.dsn)   # noqa: E731

    # the video cannot be bought first
    with pytest.raises(ToolError, match="needs `frame`"):
        _tool(studio, **ask, stage="video")

    # 1. the frame: quoted, approved, edited, filed
    q1 = _tool(studio, **ask)
    assert q1["state"] == "quote" and q1["quote"]["credits"] == 10 and balance() == 1000
    _tool(studio, **ask, quote_token=q1["quote"]["quote_token"])
    frame = studio.results[0]
    assert frame["ok"] and frame["frame"].startswith("gen:") and balance() == 990
    assert studio.sent[0][0].endswith("fal-ai/nano-banana/edit")
    assert studio.sent[0][1]["image_urls"] == ["https://r2/frame.jpg"]

    # a frame of this clip does not approve a different instruction
    with pytest.raises(ToolError, match="different instruction"):
        _tool(studio, source=studio.clip, instruction="make the jacket blue", stage="video",
              frame=frame["frame"])

    # 2. the video: quoted off the clip's 8 seconds, approved, edited, filed
    q2 = _tool(studio, **ask, stage="video", frame=frame["frame"])
    assert q2["quote"]["credits"] == 242 and q2["quote"]["balance_after"] == 990 - 242
    _tool(studio, **ask, stage="video", frame=frame["frame"],
          quote_token=q2["quote"]["quote_token"])
    video = studio.results[1]
    assert video["ok"] and video["media_kind"] == "video" and balance() == 990 - 242
    url, body = studio.sent[1]
    assert url.endswith("fal-ai/kling-video/o1/standard/video-to-video/edit")
    assert body["video_url"] == "https://r2/m/1/renders/fal/clip.mp4"
    assert len(body["image_urls"]) == 1 and "@Image1" in body["prompt"]
    assert body["keep_audio"] is True

    # the same yes again starts nothing and charges nothing
    again = _tool(studio, **ask, stage="video", frame=frame["frame"],
                  quote_token=q2["quote"]["quote_token"])
    assert again["already_used"] is True and len(studio.sent) == 2 and balance() == 990 - 242
    kinds = [e["kind"] for e in ledger.entries(studio.account_id, studio.dsn)]
    assert kinds.count("settle") == 2 and "release" not in kinds
