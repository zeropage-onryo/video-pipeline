"""The post-render length check measures the PICTURE of an mp4 export
(2026-10-08). An MP4's format duration is its longest stream's, and the
export pads its sound to the cut's length -- so a video stream that rendered
short (2026-10-07: 132 frames of picture under a 135-frame cut, reversed
clips losing a frame per chunk join) read as full length and noted nothing."""
import shutil
import subprocess
from pathlib import Path

import pytest

from src.cut import doc as d
from src.cut import ops, render, sources

pytestmark = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
                                reason="ffmpeg is not installed")


@pytest.fixture
def short_picture(tmp_path) -> Path:
    """4.4 s of picture (132 frames at 30 fps) over 4.5 s of sound -- no
    -shortest, so the container is as long as the audio."""
    out = tmp_path / "short.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y",
         "-f", "lavfi", "-t", "4.4", "-i", "testsrc=size=160x284:rate=30",
         "-f", "lavfi", "-t", "4.5", "-i", "sine=frequency=440:sample_rate=48000",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(out)],
        check=True, capture_output=True)
    return out


def cut(frames=135):
    media = {"gen:1": {"frames": frames, "video": True, "audio": True}}
    doc = ops.apply(d.starter_doc(30, (160, 284)), "insert",
                    {"track_id": "V1", "sound_track": "A1",
                     "clip": {"media": "gen:1", "src_in": 0, "src_out": frames}}, media=media)
    return doc, media


def test_probe_still_reports_the_container_length(short_picture):
    # the timeline's measure of SOURCE media is untouched: the longest stream
    assert sources.probe(short_picture, 30)["frames"] == 135
    assert sources.video_frames(short_picture, 30) == 132


def test_video_frames_is_none_without_a_picture(tmp_path):
    out = tmp_path / "sound.m4a"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-t", "1",
                    "-i", "sine=frequency=440", "-c:a", "aac", str(out)],
                   check=True, capture_output=True)
    assert sources.video_frames(out, 30) is None


def test_length_note_reads_the_picture_of_an_mp4(short_picture):
    doc, _ = cut()
    got = sources.probe(short_picture, 30)
    assert render.length_note(short_picture, got, doc, "mp4") == \
        "rendered 132 frames against a 135-frame cut"
    # the sound-only export keeps the file's own length
    assert render.length_note(short_picture, got, doc, "audio") is None


def test_render_notes_a_short_picture_under_full_length_sound(short_picture, tmp_path, monkeypatch):
    """Through render() itself: ffmpeg's graph is swapped for a copy of the
    short file, so the check is the only thing under test."""
    doc, media = cut()

    def copy_args(doc, paths, out, **kw):
        return [kw.get("ffmpeg") or "ffmpeg", "-v", "error", "-y", "-i", str(short_picture),
                "-c", "copy", str(out)]

    monkeypatch.setattr(render, "compile_args", copy_args)
    result = render.render(doc, account_id=None, name="short", paths={"gen:1": short_picture},
                           media=media, out_dir=tmp_path / "out")
    assert "rendered 132 frames against a 135-frame cut" in result["notes"]
