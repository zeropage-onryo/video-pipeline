"""Keyframe lanes, crop and opacity on picture clips (src/cut/lanes.py,
2026-10-01): the math, the ops, what split and trim do to keys, the
validator, and the render graph -- plus one real ffmpeg render when this
box has ffmpeg."""
import shutil
import subprocess
from pathlib import Path

import pytest

from src.cut import doc as d
from src.cut import lanes, ops, render
from src.cut import validate as v

MEDIA = {"gen:1": {"frames": 300, "video": True, "audio": True},
         "gen:2": {"frames": 300, "video": True, "audio": True}}


def cut():
    doc = d.new_doc(30, (720, 1280))
    doc["tracks"] = [{"id": "V1", "kind": "video", "clips": []},
                     {"id": "A1", "kind": "audio", "role": "sfx", "clips": []}]
    doc = ops.apply(doc, "insert", {"track_id": "V1", "sound_track": "A1",
                                    "clip": {"media": "gen:1", "src_in": 0, "src_out": 150}}, media=MEDIA)
    return doc


def c1(doc):
    return d.track(doc, "V1")["clips"][0]


def keys(clip, path):
    return [(k["frame"], k["value"], k["ease"]) for k in lanes.lane(clip, path)["keys"]]


# --------------------------------------------------------------------------
# the math
# --------------------------------------------------------------------------

K = [{"frame": 0, "value": 1.0, "ease": "linear"}, {"frame": 30, "value": 2.0, "ease": "ease"},
     {"frame": 60, "value": 2.0, "ease": "hold"}, {"frame": 90, "value": 1.0, "ease": "linear"}]


def test_value_at_holds_outside_and_interpolates_inside():
    assert lanes.value_at(K, -5, 9) == 1.0
    assert lanes.value_at(K, 15, 9) == pytest.approx(1.5)            # linear
    assert lanes.value_at(K, 45, 9) == pytest.approx(2.0)            # ease between equal values
    assert lanes.value_at(K, 75, 9) == pytest.approx(2.0)            # hold until the next key
    assert lanes.value_at(K, 90, 9) == 1.0 and lanes.value_at(K, 200, 9) == 1.0
    assert lanes.value_at([], 10, 9) == 9


def test_ease_is_smoothstep():
    k = [{"frame": 0, "value": 0.0, "ease": "ease"}, {"frame": 100, "value": 1.0, "ease": "linear"}]
    assert lanes.value_at(k, 25, 0) == pytest.approx(0.15625)
    assert lanes.value_at(k, 50, 0) == pytest.approx(0.5)


@pytest.mark.parametrize("frame", [0, 7, 15, 29, 30, 44, 59, 60, 74, 89, 90, 120])
def test_the_ffmpeg_expression_is_the_same_curve(frame):
    """render.py evaluates expr() in ffmpeg; it must be value_at exactly."""
    e = lanes.expr(K, 30, 9)
    t = frame / 30

    def lt(a, b):
        return 1 if a < b else 0

    got = eval(e.replace("if(", "_if("), {"_if": lambda c, a, b: a if c else b, "lt": lt, "t": t})
    assert got == pytest.approx(lanes.value_at(K, frame, 9))


def test_window_rebases_and_keeps_the_values_at_the_edges():
    first, = lanes.window([{"path": "zoom", "keys": K}], 0, 45)
    second, = lanes.window([{"path": "zoom", "keys": K}], 45, 120)
    assert first["keys"][-1]["frame"] == 45
    assert second["keys"][0] == {"frame": 0, "value": pytest.approx(2.0), "ease": "ease"}
    assert [k["frame"] for k in second["keys"]] == [0, 15, 45]
    for f in (0, 10, 30, 44):
        assert lanes.value_at(first["keys"], f, 1) == pytest.approx(lanes.value_at(K, f, 1))
    for f in (15, 40, 45, 70):           # linear / hold stretches are exact
        assert lanes.value_at(second["keys"], f, 1) == pytest.approx(lanes.value_at(K, f + 45, 1))


def test_a_flat_window_becomes_a_constant():
    out, = lanes.window([{"path": "x", "keys": K}], 30, 60)
    assert out["keys"] == [{"frame": 0, "value": 2.0, "ease": "linear"}]


# --------------------------------------------------------------------------
# the ops
# --------------------------------------------------------------------------

def test_set_key_upserts_in_frame_order_and_one_key_is_a_constant():
    doc = ops.apply(cut(), "set_key", {"clip_id": c1(cut())["id"], "path": "zoom", "frame": 0, "value": 1.2},
                    media=MEDIA)
    assert keys(c1(doc), "zoom") == [(0, 1.2, "linear")]
    assert lanes.animated(c1(doc), "zoom") and lanes.has_look(c1(doc))
    cid = c1(doc)["id"]
    doc = ops.apply(doc, "set_key", {"clip_id": cid, "path": "zoom", "frame": 60, "value": 1.5, "ease": "ease"},
                    media=MEDIA)
    doc = ops.apply(doc, "set_key", {"clip_id": cid, "path": "zoom", "frame": 30, "value": 1.3}, media=MEDIA)
    doc = ops.apply(doc, "set_key", {"clip_id": cid, "path": "zoom", "frame": 30, "value": 1.4}, media=MEDIA)
    assert keys(c1(doc), "zoom") == [(0, 1.2, "linear"), (30, 1.4, "linear"), (60, 1.5, "ease")]
    assert v.problems(doc, MEDIA) == []


def test_delete_key_and_clear_lane_return_to_the_default():
    doc = cut()
    cid = c1(doc)["id"]
    for f, val in ((0, 0.0), (60, 0.5)):
        doc = ops.apply(doc, "set_key", {"clip_id": cid, "path": "x", "frame": f, "value": val}, media=MEDIA)
    doc = ops.apply(doc, "delete_key", {"clip_id": cid, "path": "x", "frame": 60}, media=MEDIA)
    assert keys(c1(doc), "x") == [(0, 0.0, "linear")]
    doc = ops.apply(doc, "delete_key", {"clip_id": cid, "path": "x", "frame": 0}, media=MEDIA)
    assert "lanes" not in c1(doc)
    doc = ops.apply(doc, "set_key", {"clip_id": cid, "path": "rotation", "frame": 0, "value": 5}, media=MEDIA)
    doc = ops.apply(doc, "clear_lane", {"clip_id": cid, "path": "rotation"}, media=MEDIA)
    assert "lanes" not in c1(doc) and not lanes.has_look(c1(doc))


def test_crop_and_opacity_are_static_and_reset_to_nothing():
    doc = cut()
    cid = c1(doc)["id"]
    doc = ops.apply(doc, "set_crop", {"clip_id": cid, "left": 0.1, "bottom": 0.2}, media=MEDIA)
    assert c1(doc)["crop"] == {"left": 0.1, "right": 0.0, "top": 0.0, "bottom": 0.2}
    doc = ops.apply(doc, "set_opacity", {"clip_id": cid, "value": 0.5}, media=MEDIA)
    assert c1(doc)["opacity"] == 0.5 and lanes.has_look(c1(doc))
    doc = ops.apply(doc, "set_crop", {"clip_id": cid}, media=MEDIA)
    doc = ops.apply(doc, "set_opacity", {"clip_id": cid, "value": 1}, media=MEDIA)
    assert "crop" not in c1(doc) and "opacity" not in c1(doc)


@pytest.mark.parametrize("op, args, reason", [
    ("set_key", {"path": "zoom", "frame": 0, "value": 9}, "0.1 to 4"),
    ("set_key", {"path": "spin", "frame": 0, "value": 1}, "path must be one of"),
    ("set_key", {"path": "zoom", "frame": 151, "value": 1}, "outside clip"),
    ("set_key", {"path": "zoom", "frame": 0, "value": 1, "ease": "bounce"}, "ease must be one of"),
    ("delete_key", {"path": "zoom", "frame": 0}, "no zoom key"),
    ("clear_lane", {"path": "zoom"}, "no zoom to reset"),
    ("set_crop", {"left": 0.5}, "crop left must be"),
    ("set_crop", {"left": 0.45, "right": 0.45}, "leaves nothing"),
    ("set_opacity", {"value": -0.1}, "opacity must be 0 to 1"),
])
def test_refusals(op, args, reason):
    doc = cut()
    with pytest.raises(ops.OpError) as e:
        ops.apply(doc, op, {"clip_id": c1(doc)["id"], **args}, media=MEDIA)
    assert reason in str(e.value) or any(reason in p for p in e.value.problems)


def test_sound_clips_take_no_keyframes():
    doc = cut()
    sound = d.track(doc, "A1")["clips"][0]["id"]
    with pytest.raises(ops.OpError, match="belong to picture clips"):
        ops.apply(doc, "set_key", {"clip_id": sound, "path": "zoom", "frame": 0, "value": 1.2}, media=MEDIA)
    bad = cut()
    d.track(bad, "A1")["clips"][0]["opacity"] = 0.5
    assert any("belong to picture clips" in p for p in v.problems(bad, MEDIA))


def test_split_and_trim_carry_the_motion():
    doc = cut()
    cid = c1(doc)["id"]
    for f, val in ((0, 1.0), (90, 1.6)):
        doc = ops.apply(doc, "set_key", {"clip_id": cid, "path": "zoom", "frame": f, "value": val}, media=MEDIA)
    split = ops.apply(doc, "split", {"clip_id": cid, "frame": 45}, media=MEDIA)
    a, b = d.track(split, "V1")["clips"]
    assert keys(a, "zoom") == [(0, 1.0, "linear"), (45, 1.3, "linear")]
    assert keys(b, "zoom") == [(0, 1.3, "linear"), (45, 1.6, "linear")]
    assert "lanes" not in d.track(split, "A1")["clips"][1], "the sound has no picture keys"
    trimmed = ops.apply(doc, "trim", {"clip_id": cid, "head": 30, "tail": 30}, media=MEDIA)
    assert keys(c1(trimmed), "zoom") == [(0, 1.2, "linear"), (60, 1.6, "linear")]
    assert v.problems(split, MEDIA) == [] and v.problems(trimmed, MEDIA) == []


def test_every_new_op_has_a_summary():
    for op, args in (("set_key", {"clip_id": "c1", "path": "zoom", "frame": 30, "value": 1.5}),
                     ("delete_key", {"clip_id": "c1", "path": "x", "frame": 0}),
                     ("clear_lane", {"clip_id": "c1", "path": "rotation"}),
                     ("set_crop", {"clip_id": "c1", "left": 0.1}),
                     ("set_opacity", {"clip_id": "c1", "value": 0.4})):
        text = ops.describe(op, args, 30)
        assert text and text != op
    assert ops.describe("set_key", {"clip_id": "c1", "path": "zoom", "frame": 30, "value": 1.5}, 30) \
        == "zoom 1.5 on c1 at +1.0s"


# --------------------------------------------------------------------------
# the render
# --------------------------------------------------------------------------

def looked():
    doc = cut()
    cid = c1(doc)["id"]
    for op, a in (("set_key", {"path": "zoom", "frame": 0, "value": 1.0}),
                  ("set_key", {"path": "zoom", "frame": 60, "value": 1.5, "ease": "ease"}),
                  ("set_key", {"path": "rotation", "frame": 60, "value": 10}),
                  ("set_key", {"path": "y", "frame": 0, "value": -0.1}),
                  ("set_crop", {"left": 0.1}), ("set_opacity", {"value": 0.8})):
        doc = ops.apply(doc, op, {"clip_id": cid, **a}, media=MEDIA)
    return doc


def test_a_looked_clip_takes_the_transform_path_and_a_plain_one_does_not():
    argv = render.compile_args(looked(), {"gen:1": Path("/x/a.mp4")}, Path("/x/o.mp4"))
    graph = argv[argv.index("-filter_complex") + 1]
    for stage in ("crop=iw*0.9000", "colorchannelmixer=aa=0.8000", "eval=frame", "rotate=a=",
                  "overlay=x='(W-w)/2+(0)*W':y='(H-h)/2+(-0.1)*H'", "color=c=black:s=720x1280"):
        assert stage in graph, stage
    assert "pad=720:1280" not in graph
    plain = render.compile_args(cut(), {"gen:1": Path("/x/a.mp4")}, Path("/x/o.mp4"))
    pgraph = plain[plain.index("-filter_complex") + 1]
    assert "pad=720:1280" in pgraph and "overlay" not in pgraph and "rotate" not in pgraph


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg is not installed")
def test_a_looked_clip_really_renders(tmp_path):
    src = tmp_path / "src.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc2=size=360x640:rate=30", "-f", "lavfi", "-i", "sine=frequency=440",
                    "-t", "10", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                    "-shortest", str(src)], check=True)
    out = tmp_path / "o.mp4"
    argv = render.compile_args(looked(), {"gen:1": src}, out)
    proc = subprocess.run(argv, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr[-400:]
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=width,height",
                            "-of", "compact", str(out)], capture_output=True, text=True).stdout
    assert "width=720" in probe and "height=1280" in probe
    assert "duration=5.0" in probe
