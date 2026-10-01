"""Export targets (2026-10-01): the sound alone (.m4a), one frame (.png),
and an editable project (.otio + .srt) -- the graphs, real renders, and the
OTIO document read back by OpenTimelineIO itself when it is installed."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from src.cut import doc as d
from src.cut import ops, otio, render

MEDIA = {"gen:1": {"frames": 90, "video": True, "audio": True},
         "gen:2": {"frames": 90, "video": True, "audio": True}}
REFS = {"gen:1": {"url": "https://media.example/a.mp4", "name": "Kling #1"},
        "gen:2": {"url": "https://media.example/b.mp4", "name": "Kling #2"}}


def cut(size=(720, 1280)):
    doc = d.starter_doc(30, size)
    for h in ("gen:1", "gen:2"):
        doc = ops.apply(doc, "insert", {"track_id": "V1", "sound_track": "A1",
                                        "clip": {"media": h, "src_in": 0, "src_out": 90}}, media=MEDIA)
    return doc


def graph(argv):
    return argv[argv.index("-filter_complex") + 1]


def test_audio_only_opens_no_picture_and_maps_only_the_mix():
    argv = render.compile_args(cut(), {"gen:1": Path("/a.mp4"), "gen:2": Path("/b.mp4")},
                               Path("/o.m4a"), fmt="audio")
    assert argv.count("-vn") == 2 and "-an" not in argv
    assert "[aout]" in argv and "[vout]" not in argv and "libx264" not in argv
    assert "loudnorm=I=-14" in graph(argv)


def test_a_still_opens_no_sound_and_takes_one_frame():
    argv = render.compile_args(cut(), {"gen:1": Path("/a.mp4"), "gen:2": Path("/b.mp4")},
                               Path("/o.png"), fmt="still", frame=100)
    assert argv.count("-an") == 2 and "-vn" not in argv
    assert "trim=start_frame=100:end_frame=101" in graph(argv) and "-frames:v" in argv
    with pytest.raises(render.RenderError, match="outside the cut"):
        render.compile_args(cut(), {"gen:1": Path("/a"), "gen:2": Path("/b")}, Path("/o.png"),
                            fmt="still", frame=500)


def test_the_otio_keeps_frames_gaps_and_names():
    doc = cut()
    doc = ops.apply(doc, "move", {"clip_id": "c2", "at": 120}, media=MEDIA)          # a 30-frame gap
    tl = otio.timeline(doc, REFS, name="Test v3")
    v1 = tl["tracks"]["children"][0]
    assert v1["kind"] == "Video" and [c["OTIO_SCHEMA"] for c in v1["children"]] == ["Clip.1", "Gap.1", "Clip.1"]
    assert v1["children"][1]["source_range"]["duration"]["value"] == 30
    clip = v1["children"][2]
    assert clip["name"] == "Kling #2"
    assert clip["media_reference"]["target_url"] == "https://media.example/b.mp4"
    assert clip["source_range"]["start_time"]["rate"] == 30


def test_a_transition_becomes_an_abutting_cut_with_the_outgoing_media_borrowed():
    doc = ops.apply(cut(), "add_transition", {"clip_id": "c2", "frames": 10, "style": "wipeleft"},
                    media=MEDIA)
    v1 = otio.timeline(doc, REFS, name="t")["tracks"]["children"][0]["children"]
    assert [c["OTIO_SCHEMA"] for c in v1] == ["Clip.1", "Transition.1", "Clip.1"]
    first, tr, second = v1
    assert first["source_range"]["duration"]["value"] == 80          # ends where c2 starts
    assert tr["in_offset"]["value"] == 10 and tr["out_offset"]["value"] == 0
    assert tr["metadata"]["zpf"]["style"] == "wipeleft"
    # the timeline length is unchanged: 80 + 90 == the doc's 170
    assert first["source_range"]["duration"]["value"] + second["source_range"]["duration"]["value"] \
        == doc["duration"]


def test_speed_and_reverse_ride_as_a_time_warp():
    doc = ops.apply(cut(), "set_speed", {"clip_id": "c1", "speed": 2}, media=MEDIA)
    doc = ops.apply(doc, "set_reverse", {"clip_id": "c1"}, media=MEDIA)
    tl = otio.timeline(doc, REFS, name="t")
    c = tl["tracks"]["children"][0]["children"][0]
    assert c["effects"][0]["OTIO_SCHEMA"] == "LinearTimeWarp.1"
    assert c["effects"][0]["time_scalar"] == -2
    assert c["metadata"]["zpf"]["reverse"] is True
    # the item is its TIMELINE length, read backwards from the span's end
    assert (c["source_range"]["start_time"]["value"], c["source_range"]["duration"]["value"]) == (90, 45)


def test_a_handle_with_no_url_is_a_missing_reference():
    c = otio.timeline(cut(), {"gen:1": {"url": None, "name": "x"}}, name="t")["tracks"]["children"][0]
    assert c["children"][0]["media_reference"]["OTIO_SCHEMA"] == "MissingReference.1"


def test_captions_are_an_srt():
    doc = ops.apply(cut(), "add_caption_track", {"cues": [{"start": 0, "end": 45, "text": "hello"},
                                                          {"start": 60, "end": 90, "text": "again"}]},
                    media=MEDIA)
    assert otio.srt(doc) == ("1\n00:00:00,000 --> 00:00:01,500\nhello\n\n"
                             "2\n00:00:02,000 --> 00:00:03,000\nagain\n")
    assert otio.srt(cut()) is None


def test_opentimelineio_reads_it_back():
    otio_lib = pytest.importorskip("opentimelineio")
    doc = ops.apply(cut(), "add_transition", {"clip_id": "c2", "frames": 10}, media=MEDIA)
    doc = ops.apply(doc, "add_marker", {"frame": 30, "label": "beat"}, media=MEDIA)
    doc = ops.apply(doc, "set_speed", {"clip_id": "c1", "speed": 2}, media=MEDIA)
    tl = otio_lib.adapters.read_from_string(json.dumps(otio.timeline(doc, REFS, name="t")), "otio_json")
    assert len(tl.video_tracks()) == 1 and len(tl.audio_tracks()) == 2
    assert tl.duration().to_frames() == doc["duration"]
    assert tl.video_tracks()[0][0].media_reference.target_url == "https://media.example/a.mp4"


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg is not installed")
def test_audio_and_still_really_render(tmp_path):
    src = tmp_path / "s.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=64x64:r=30",
                    "-f", "lavfi", "-i", "sine", "-t", "3", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", str(src)], check=True)
    doc = cut((64, 64))
    paths = {"gen:1": src, "gen:2": src}
    a = render.render(doc, account_id=None, name="snd", paths=paths, media=MEDIA, out_dir=tmp_path,
                      fmt="audio")
    assert a["path"].endswith(".m4a") and abs(a["seconds"] - 6.0) < 0.1
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0",
                            a["path"]], capture_output=True, text=True).stdout.split()
    assert probe == ["audio"]
    s = render.render(doc, account_id=None, name="frame", paths=paths, media=MEDIA, out_dir=tmp_path,
                      fmt="still", frame=45)
    assert Path(s["path"]).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
