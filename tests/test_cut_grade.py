"""The Color page's basic correction (2026-10-01): set_grade, the
validator, the render graph, and a real render that measures it."""
import shutil
import subprocess
from pathlib import Path

import pytest

from src.cut import doc as d
from src.cut import ops, render
from src.cut import validate as v

MEDIA = {"gen:1": {"frames": 90, "video": True, "audio": True}}


def cut(size=(720, 1280)):
    return ops.apply(d.starter_doc(30, size), "insert",
                     {"track_id": "V1", "sound_track": "A1",
                      "clip": {"media": "gen:1", "src_in": 0, "src_out": 90}}, media=MEDIA)


def test_set_grade_merges_and_drops_neutral_fields():
    doc = ops.apply(cut(), "set_grade", {"clip_id": "c1", "exposure": 0.5, "saturation": 1.3}, media=MEDIA)
    doc = ops.apply(doc, "set_grade", {"clip_id": "c1", "temperature": 0.4}, media=MEDIA)
    assert d.track(doc, "V1")["clips"][0]["grade"] == {"exposure": 0.5, "saturation": 1.3, "temperature": 0.4}
    doc = ops.apply(doc, "set_grade", {"clip_id": "c1", "saturation": 1}, media=MEDIA)
    assert "saturation" not in d.track(doc, "V1")["clips"][0]["grade"]
    doc = ops.apply(doc, "set_grade", {"clip_id": "c1", "reset": True}, media=MEDIA)
    assert "grade" not in d.track(doc, "V1")["clips"][0]


def test_the_graph_grades_before_the_fit():
    doc = ops.apply(cut(), "set_grade", {"clip_id": "c1", "exposure": 1, "contrast": 1.2,
                                         "temperature": 0.5}, media=MEDIA)
    argv = render.compile_args(doc, {"gen:1": Path("/a.mp4")}, Path("/o.mp4"))
    g = argv[argv.index("-filter_complex") + 1]
    assert "exposure=exposure=1.0000,eq=contrast=1.2000:saturation=1.0000," \
           "colortemperature=temperature=5000,format=yuv420p,fps=" in g


@pytest.mark.parametrize("args", [{"exposure": 3}, {"saturation": -1}, {"contrast": "x"}])
def test_refusals(args):
    with pytest.raises(ops.OpError):
        ops.apply(cut(), "set_grade", {"clip_id": "c1", **args}, media=MEDIA)


def test_a_grade_belongs_to_picture():
    doc = cut()
    d.track(doc, "A1")["clips"][0]["grade"] = {"exposure": 1}
    assert any("a grade belongs to picture clips" in p for p in v.problems(doc, MEDIA))
    with pytest.raises(ops.OpError):
        ops.apply(cut(), "set_grade", {"clip_id": "c1a1", "exposure": 1}, media=MEDIA)


def test_summary():
    assert ops.describe("set_grade", {"clip_id": "c1", "exposure": 0.5, "saturation": 1.2}) \
        == "grade c1: exposure +0.5, saturation 1.2"
    assert ops.describe("set_grade", {"clip_id": "c1", "reset": True}) == "reset the grade on c1"


def _mean_rgb(path, t):
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", str(t), "-i", str(path), "-vf", "scale=1:1",
                          "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True).stdout
    return raw[0], raw[1], raw[2]


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg is not installed")
def test_a_grade_really_renders(tmp_path):
    src = tmp_path / "grey.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=0x606060:s=64x64:r=30",
                    "-f", "lavfi", "-i", "sine", "-t", "3", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", str(src)], check=True)
    plain = render.render(cut((64, 64)), account_id=None, name="plain", paths={"gen:1": src},
                          media=MEDIA, out_dir=tmp_path)
    doc = ops.apply(cut((64, 64)), "set_grade", {"clip_id": "c1", "exposure": 1, "temperature": 0.8},
                    media=MEDIA)
    graded = render.render(doc, account_id=None, name="graded", paths={"gen:1": src}, media=MEDIA,
                           out_dir=tmp_path)
    r0, g0, b0 = _mean_rgb(plain["path"], 1)
    r1, g1, b1 = _mean_rgb(graded["path"], 1)
    assert g1 > g0 + 20, (g0, g1)                    # a stop brighter
    assert (r1 - b1) > (r0 - b0) + 10, ((r0, b0), (r1, b1))   # and warmer
