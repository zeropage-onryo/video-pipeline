"""The mixer (2026-10-01): an audio track's fader and pan, a sound clip's
fades and volume keys -- the ops, the validator, the render graph, and one
real render whose levels are measured."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from src.cut import doc as d
from src.cut import ops, render
from src.cut import validate as v

MEDIA = {"gen:1": {"frames": 300, "video": True, "audio": True}}


def cut():
    doc = d.starter_doc(30, (720, 1280))
    return ops.apply(doc, "insert", {"track_id": "V1", "sound_track": "A1",
                                     "clip": {"media": "gen:1", "src_in": 0, "src_out": 90}}, media=MEDIA)


def graph(doc):
    argv = render.compile_args(doc, {"gen:1": Path("/a.mp4")}, Path("/o.mp4"))
    return argv[argv.index("-filter_complex") + 1]


def test_the_fader_and_pan_land_on_the_track_and_render():
    doc = ops.apply(cut(), "set_track_mix", {"track_id": "A1", "gain_db": -6, "pan": -0.5}, media=MEDIA)
    assert d.track(doc, "A1")["gain_db"] == -6 and d.track(doc, "A1")["pan"] == -0.5
    g = graph(doc)
    assert "volume=-6dB" in g and "pan=stereo|c0=1.0000*c0|c1=0.5000*c1" in g
    back = ops.apply(doc, "set_track_mix", {"track_id": "A1", "gain_db": 0, "pan": 0}, media=MEDIA)
    assert "gain_db" not in d.track(back, "A1") and "pan" not in d.track(back, "A1")


def test_fades_go_to_the_sound_even_from_its_picture():
    doc = ops.apply(cut(), "set_fade", {"clip_id": "c1", "fade_in": 15, "fade_out": 30}, media=MEDIA)
    sound = d.track(doc, "A1")["clips"][0]
    assert (sound["fade_in"], sound["fade_out"]) == (15, 30)
    assert "fade_in" not in d.track(doc, "V1")["clips"][0]
    g = graph(doc)
    assert "afade=t=in:st=0:d=0.5" in g and "afade=t=out:st=2:d=1" in g


def test_volume_is_keyed_on_the_sound_clip():
    sound = d.track(cut(), "A1")["clips"][0]["id"]
    doc = ops.apply(cut(), "set_key", {"clip_id": sound, "path": "volume", "frame": 0, "value": 0}, media=MEDIA)
    doc = ops.apply(doc, "set_key", {"clip_id": sound, "path": "volume", "frame": 60, "value": -20},
                    media=MEDIA)
    assert "volume=volume='pow(10,(" in graph(doc) and ":eval=frame" in graph(doc)
    with pytest.raises(ops.OpError, match="keyed on its sound"):
        ops.apply(cut(), "set_key", {"clip_id": "c1", "path": "volume", "frame": 0, "value": -3}, media=MEDIA)


@pytest.mark.parametrize("op,args", [
    ("set_track_mix", {"track_id": "A1", "gain_db": 20}),
    ("set_track_mix", {"track_id": "A1", "pan": 2}),
    ("set_track_mix", {"track_id": "V1", "gain_db": -3}),
    ("set_fade", {"clip_id": "c1", "fade_in": 500}),
    ("set_key", {"clip_id": "c1a1", "path": "volume", "frame": 0, "value": 40}),
])
def test_refusals(op, args):
    with pytest.raises(ops.OpError):
        ops.apply(cut(), op, args, media=MEDIA)


def test_the_validator_keeps_mix_fields_where_they_belong():
    doc = cut()
    d.track(doc, "V1")["pan"] = 0.5
    d.track(doc, "V1")["clips"][0]["fade_in"] = 10
    found = v.problems(doc, MEDIA)
    assert any("only an audio track has a fader" in p for p in found)
    assert any("fade_in belongs to sound clips" in p for p in found)


def test_summaries():
    assert ops.describe("set_track_mix", {"track_id": "A2", "gain_db": -4, "pan": -0.3}) \
        == "mix A2: -4 dB, pan 30% left"
    assert ops.describe("set_fade", {"clip_id": "c1", "fade_in": 15}, 30) == "c1 fade in 0.5s"


def _rms(path: Path, start: float, dur: float, channel: int) -> float:
    out = subprocess.run(["ffmpeg", "-hide_banner", "-ss", str(start), "-t", str(dur), "-i", str(path),
                          "-af", f"pan=mono|c0=c{channel},astats=metadata=1:reset=0,"
                          "ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-",
                          "-f", "null", "-"], capture_output=True, text=True)
    vals = [float(line.split("=")[1]) for line in out.stdout.splitlines()
            if "RMS_level=" in line and "inf" not in line]
    return vals[-1] if vals else -120.0


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg is not installed")
def test_a_panned_faded_mix_really_renders(tmp_path):
    src = tmp_path / "tone.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=gray:s=64x64:r=30",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", "3",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ac", "2", "-shortest", str(src)],
                   check=True)
    media = {"gen:1": {"frames": 90, "video": True, "audio": True}}
    doc = d.starter_doc(30, (64, 64))
    doc = ops.apply(doc, "insert", {"track_id": "V1", "sound_track": "A1",
                                    "clip": {"media": "gen:1", "src_in": 0, "src_out": 90}}, media=media)
    doc = ops.apply(doc, "set_track_mix", {"track_id": "A1", "pan": -1}, media=media)      # hard left
    doc = ops.apply(doc, "set_fade", {"clip_id": "c1", "fade_out": 30}, media=media)
    got = render.render(doc, account_id=None, name="mix", paths={"gen:1": src}, media=media,
                        out_dir=tmp_path)
    out = Path(got["path"])
    left, right = _rms(out, 0.5, 1.0, 0), _rms(out, 0.5, 1.0, 1)
    assert left > -30 and right < left - 40, (left, right)          # panned hard left
    assert _rms(out, 2.85, 0.1, 0) < left - 15                       # faded out by the end
    json.dumps(got)
