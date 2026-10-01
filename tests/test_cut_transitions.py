"""Transition styles (2026-10-01): the xfade look of a transition, how it is
added, changed and removed, and that every style the editor offers is one
the installed ffmpeg can draw."""
import shutil
import subprocess
from pathlib import Path

import pytest

from src.cut import doc as d
from src.cut import ops, render
from src.cut import validate as v

MEDIA = {"gen:1": {"frames": 300, "video": True, "audio": True},
         "gen:2": {"frames": 300, "video": True, "audio": True}}


def cut():
    doc = d.starter_doc(30, (720, 1280))
    for h in ("gen:1", "gen:2"):
        doc = ops.apply(doc, "insert", {"track_id": "V1", "sound_track": "A1",
                                        "clip": {"media": h, "src_in": 0, "src_out": 90}}, media=MEDIA)
    return doc


def c2(doc, track="V1"):
    return d.track(doc, track)["clips"][1]


def test_add_with_a_style_and_the_sound_still_crossfades():
    doc = ops.apply(cut(), "add_transition", {"clip_id": "c2", "frames": 10, "style": "wipeleft"},
                    media=MEDIA)
    assert c2(doc)["transition_in"] == {"kind": "xfade", "frames": 10, "style": "wipeleft"}
    assert c2(doc)["at"] == 80 and c2(doc, "A1")["at"] == 80
    graph = render.compile_args(doc, {"gen:1": Path("/a"), "gen:2": Path("/b")}, Path("/o"))
    g = graph[graph.index("-filter_complex") + 1]
    assert "xfade=transition=wipeleft:duration=0.333333" in g
    assert "afade=t=in" in g


def test_the_default_style_is_not_written():
    doc = ops.apply(cut(), "add_transition", {"clip_id": "c2", "frames": 8}, media=MEDIA)
    assert "style" not in c2(doc)["transition_in"]
    graph = render.compile_args(doc, {"gen:1": Path("/a"), "gen:2": Path("/b")}, Path("/o"))
    assert "xfade=transition=fade:" in graph[graph.index("-filter_complex") + 1]


def test_remove_is_the_exact_inverse_of_add():
    base = cut()
    added = ops.apply(base, "add_transition", {"clip_id": "c2", "frames": 12, "style": "slideup"},
                      media=MEDIA)
    back = ops.apply(added, "remove_transition", {"clip_id": "c2"}, media=MEDIA)
    assert back == base


def test_set_transition_changes_the_look_and_the_length():
    doc = ops.apply(cut(), "add_transition", {"clip_id": "c2", "frames": 10}, media=MEDIA)
    doc = ops.apply(doc, "set_transition", {"clip_id": "c2", "style": "circleopen"}, media=MEDIA)
    assert c2(doc)["transition_in"]["style"] == "circleopen" and c2(doc)["at"] == 80
    doc = ops.apply(doc, "set_transition", {"clip_id": "c2", "frames": 20}, media=MEDIA)
    assert c2(doc)["transition_in"] == {"kind": "xfade", "frames": 20, "style": "circleopen"}
    assert c2(doc)["at"] == 70 and c2(doc, "A1")["at"] == 70


@pytest.mark.parametrize("op,args,reason", [
    ("add_transition", {"clip_id": "c2", "frames": 8, "style": "spin"}, "not one of"),
    ("remove_transition", {"clip_id": "c2"}, "no transition in"),
    ("set_transition", {"clip_id": "c2", "style": "fade"}, "add one first"),
])
def test_refusals(op, args, reason):
    with pytest.raises(ops.OpError) as e:
        ops.apply(cut(), op, args, media=MEDIA)
    assert reason in str(e.value)


def test_the_validator_refuses_a_style_it_cannot_draw():
    doc = ops.apply(cut(), "add_transition", {"clip_id": "c2", "frames": 8}, media=MEDIA)
    c2(doc)["transition_in"]["style"] = "spin"
    assert any("not one this editor renders" in p for p in v.problems(doc))


def test_every_style_has_a_group_and_label():
    for style, (group, label) in d.TRANSITION_STYLES.items():
        assert group in d.TRANSITION_GROUPS and label, style
    assert len(d.TRANSITION_STYLES) == 58


def test_summaries():
    assert ops.describe("add_transition", {"clip_id": "c2", "frames": 8, "style": "fadeblack"}) \
        == "dip to black into c2 (8f)"
    assert ops.describe("remove_transition", {"clip_id": "c2"}) == "hard cut into c2"
    assert ops.describe("set_transition", {"clip_id": "c2", "style": "zoomin", "frames": 6}) \
        == "transition into c2: zoom in, 6f"


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg is not installed")
def test_every_style_is_in_this_ffmpeg():
    out = subprocess.run(["ffmpeg", "-hide_banner", "-h", "filter=xfade"],
                         capture_output=True, text=True).stdout
    names = {line.split()[0] for line in out.splitlines() if line.strip() and line.split()[0].isalpha()}
    missing = set(d.TRANSITION_STYLES) - names
    assert not missing, missing


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg is not installed")
def test_a_wipe_really_renders(tmp_path):
    a, b = tmp_path / "a.mp4", tmp_path / "b.mp4"
    for path, colour in ((a, "red"), (b, "blue")):
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                        f"color=c={colour}:s=64x64:r=30", "-f", "lavfi", "-i", "sine", "-t", "2",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)],
                       check=True)
    media = {"gen:1": {"frames": 60, "video": True, "audio": True},
             "gen:2": {"frames": 60, "video": True, "audio": True}}
    doc = d.starter_doc(30, (64, 64))
    for h in ("gen:1", "gen:2"):
        doc = ops.apply(doc, "insert", {"track_id": "V1", "sound_track": "A1",
                                        "clip": {"media": h, "src_in": 0, "src_out": 60}}, media=media)
    doc = ops.apply(doc, "add_transition", {"clip_id": "c2", "frames": 30, "style": "wiperight"},
                    media=media)
    got = render.render(doc, account_id=None, name="wipe", paths={"gen:1": a, "gen:2": b},
                        media=media, out_dir=tmp_path)
    # half way through the wipe: the left of the frame is already blue,
    # the right still red

    def pixel(x):
        return subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", "1.5", "-i", got["path"],
                               "-vf", f"crop=2:2:{x}:32", "-frames:v", "1", "-f", "rawvideo",
                               "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout[:3]

    left, right = pixel(6), pixel(58)
    assert left[2] > 150 > left[0] and right[0] > 150 > right[2], (left, right)


def test_the_editor_offers_exactly_the_styles_the_server_renders():
    """web/src/lib/cut/transitions.ts is this list's twin: the Transitions
    tab must not offer a look the validator refuses, nor miss one."""
    import re
    ts = (Path(__file__).resolve().parents[1] / "web/src/lib/cut/transitions.ts").read_text()
    offered = re.findall(r'\["([a-z]+)", "([^"]+)"\]', ts)
    assert {s: label for s, label in offered} == {s: label for s, (_, label) in d.TRANSITION_STYLES.items()}
