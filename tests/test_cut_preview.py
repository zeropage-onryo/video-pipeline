"""The browser previews (src/cut/preview.py, Mike's D3): a 540p proxy with
a keyframe every second, a filmstrip sprite and waveform peaks, built by
ffmpeg from tiny generated clips. Skipped on a machine with no ffmpeg (CI
installs it, so they run there)."""
import json
import shutil
import subprocess

import pytest

from src.cut import preview

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
pytestmark = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg/ffprobe not installed")


def _ff(*args):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def _probe(path, *entries):
    out = subprocess.run(["ffprobe", "-v", "error", *entries, "-of", "json", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


@pytest.fixture(scope="module")
def media(tmp_path_factory):
    root = tmp_path_factory.mktemp("preview-src")
    enc = ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast"]
    _ff("-f", "lavfi", "-i", "testsrc2=s=720x1280:r=30:d=4.5", "-f", "lavfi",
        "-i", "sine=f=440:d=4.5", "-shortest", *enc, "-c:a", "aac", str(root / "tall.mp4"))
    _ff("-f", "lavfi", "-i", "testsrc=s=640x360:r=24:d=3", *enc, str(root / "wide.mp4"))
    _ff("-f", "lavfi", "-i", "testsrc=s=800x600:d=1", "-frames:v", "1", str(root / "still.png"))
    # a second of silence, then a second of full-scale tone
    _ff("-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono:d=1", "-f", "lavfi",
        "-i", "sine=f=440:d=1:sample_rate=44100",
        "-filter_complex", "[1]volume=8[t];[0][t]concat=n=2:v=0:a=1", str(root / "tone.wav"))
    return root


def _info(path):
    from src.cut import sources
    return sources.probe(path, 30)


def test_the_filmstrip_plan_is_one_per_second_until_it_would_pass_120():
    assert preview.filmstrip_plan(4.5) == (1, 4)
    assert preview.filmstrip_plan(0.4) == (1, 1)
    assert preview.filmstrip_plan(120) == (1, 120)
    interval, count = preview.filmstrip_plan(600)
    assert interval == 5 and count == 120
    interval, count = preview.filmstrip_plan(301)
    assert interval == 3 and count == 100


def test_a_tall_clip_gets_a_540p_proxy_keyed_every_second_a_strip_and_peaks(media, tmp_path):
    info = _info(media / "tall.mp4")
    built = preview.build(media / "tall.mp4", tmp_path, info)
    assert built["proxy"] == "proxy.mp4" and built["poster"] == "poster.jpg"

    streams = _probe(tmp_path / "proxy.mp4", "-show_entries",
                     "stream=codec_type,codec_name,width,height")["streams"]
    vid = next(s for s in streams if s["codec_type"] == "video")
    assert (vid["codec_name"], vid["width"], vid["height"]) == ("h264", 540, 960)
    assert any(s["codec_type"] == "audio" and s["codec_name"] == "aac" for s in streams)
    keys = _probe(tmp_path / "proxy.mp4", "-select_streams", "v", "-skip_frame", "nokey",
                  "-show_entries", "frame=pts_time")["frames"]
    assert [round(float(f["pts_time"])) for f in keys] == [0, 1, 2, 3, 4]

    strip = built["filmstrip"]
    assert (strip["count"], strip["interval"], strip["frame_height"]) == (4, 1, 90)
    assert strip["frame_width"] == 50           # 90 * 720/1280, evened
    size = _probe(tmp_path / "filmstrip.jpg", "-show_entries", "stream=width,height")["streams"][0]
    assert (size["width"], size["height"]) == (200, 90)

    wave = json.loads((tmp_path / "waveform.json").read_text())
    assert wave["per_second"] == preview.PEAKS_PER_SECOND
    assert abs(len(wave["peaks"]) - 4.5 * 50) <= 2
    assert all(0 <= p <= 1 and round(p, 3) == p for p in wave["peaks"])


def test_a_wide_clip_is_540_tall_and_a_silent_one_has_no_waveform(media, tmp_path):
    built = preview.build(media / "wide.mp4", tmp_path, _info(media / "wide.mp4"))
    vid = _probe(tmp_path / "proxy.mp4", "-show_entries",
                 "stream=codec_type,width,height")["streams"]
    assert [(s["width"], s["height"]) for s in vid if s["codec_type"] == "video"] == [(640, 360)]
    assert not any(s["codec_type"] == "audio" for s in vid)   # 360 < 540: never upscaled
    assert built["waveform"] is None


def test_an_image_gets_a_one_frame_strip_and_no_proxy_or_waveform(media, tmp_path):
    info = _info(media / "still.png")
    assert info["still"] and info["video"] and not info["audio"] and info["seconds"] == 600
    built = preview.build(media / "still.png", tmp_path, info)
    assert built["proxy"] is None and built["waveform"] is None
    assert built["filmstrip"]["count"] == 1 and built["filmstrip"]["frame_height"] == 90
    assert built["filmstrip"]["frame_width"] == 120
    assert not (tmp_path / "proxy.mp4").exists()


def test_audio_gets_a_waveform_only_and_the_peaks_are_absolute(media, tmp_path):
    built = preview.build(media / "tone.wav", tmp_path, _info(media / "tone.wav"))
    assert built["proxy"] is None and built["filmstrip"] is None and built["poster"] is None
    peaks = json.loads((tmp_path / "waveform.json").read_text())["peaks"]
    assert abs(len(peaks) - 100) <= 2
    assert max(peaks[:45]) == 0                 # the silent second draws as silence
    assert min(peaks[55:95]) > 0.5              # the tone draws as loud, not normalised to 1
    assert max(peaks) <= 1


def test_a_file_ffmpeg_cannot_read_is_a_preview_error(tmp_path):
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"not a video")
    with pytest.raises(preview.PreviewError):
        preview.make_proxy(bad, tmp_path / "p.mp4", {"width": 10, "height": 10})
