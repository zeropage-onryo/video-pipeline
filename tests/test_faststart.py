"""src/faststart.py and ops/faststart_clips.py: a clip's index goes in front
of its media, or the file is left exactly as it was."""
import shutil
import struct
import subprocess

import pytest

from ops import faststart_clips
from src import faststart, storage


def box(kind: str, payload: bytes = b"") -> bytes:
    return struct.pack(">I", 8 + len(payload)) + kind.encode("latin1") + payload


def write(path, *boxes: bytes):
    path.write_bytes(b"".join(boxes))
    return path


def test_the_layout_is_read_from_box_headers(tmp_path):
    slow = write(tmp_path / "slow.mp4", box("ftyp", b"isom"), box("free"), box("mdat", b"x" * 500), box("moov", b"m"))
    fast = write(tmp_path / "fast.mp4", box("ftyp", b"isom"), box("moov", b"m"), box("mdat", b"x" * 500))
    assert faststart.top_level_boxes(slow) == ["ftyp", "free", "mdat", "moov"]
    assert faststart.needs_faststart(slow) is True
    assert faststart.needs_faststart(fast) is False
    # not an MP4 at all, or no index: nothing to fix
    assert faststart.needs_faststart(write(tmp_path / "junk.mp4", b"not a video")) is False
    assert faststart.needs_faststart(write(tmp_path / "bare.mp4", box("ftyp"), box("mdat", b"x"))) is False


def test_a_64_bit_box_size_is_followed(tmp_path):
    big_mdat = struct.pack(">I", 1) + b"mdat" + struct.pack(">Q", 16 + 4) + b"abcd"
    path = write(tmp_path / "wide.mp4", box("ftyp"), big_mdat, box("moov"))
    assert faststart.top_level_boxes(path) == ["ftyp", "mdat", "moov"]


def test_nothing_runs_when_nothing_needs_fixing(tmp_path):
    calls = []
    fast = write(tmp_path / "fast.mp4", box("ftyp"), box("moov"), box("mdat", b"x"))
    image = write(tmp_path / "still.jpg", b"\xff\xd8")
    assert faststart.faststart(fast, run=lambda *a, **k: calls.append(a)) is False
    assert faststart.faststart(image, run=lambda *a, **k: calls.append(a)) is False
    assert calls == []


def test_a_failed_remux_leaves_the_original_untouched(tmp_path, monkeypatch):
    monkeypatch.setattr(faststart, "ffmpeg_bin", lambda: "/bin/ffmpeg")
    slow = write(tmp_path / "slow.mp4", box("ftyp"), box("mdat", b"x" * 64), box("moov"))
    before = slow.read_bytes()

    class Failed:
        returncode = 1
        stderr = b"boom"

    assert faststart.faststart(slow, run=lambda *a, **k: Failed()) is False
    assert slow.read_bytes() == before
    assert not [p for p in tmp_path.iterdir() if "faststart" in p.name]   # no temp file left behind

    def raises(*a, **k):
        raise OSError("no such binary")

    assert faststart.faststart(slow, run=raises) is False
    assert slow.read_bytes() == before


def test_no_ffmpeg_is_a_no_op(tmp_path, monkeypatch):
    monkeypatch.setattr(faststart, "ffmpeg_bin", lambda: None)
    slow = write(tmp_path / "slow.mp4", box("ftyp"), box("mdat", b"x"), box("moov"))
    before = slow.read_bytes()
    assert faststart.faststart(slow) is False
    assert slow.read_bytes() == before


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
def test_a_real_index_last_clip_comes_back_index_first(tmp_path):
    clip = tmp_path / "clip.mp4"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
                    "-i", "color=c=red:s=64x64:d=1", "-c:v", "mpeg4", str(clip)],
                   check=True, capture_output=True)
    assert faststart.needs_faststart(clip) is True     # ffmpeg's own default is index-last
    size = clip.stat().st_size
    assert faststart.faststart(clip) is True
    assert faststart.needs_faststart(clip) is False
    assert abs(clip.stat().st_size - size) < size * 0.05


def test_every_upload_runs_the_clip_through_faststart(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(faststart, "faststart", lambda p: seen.append(str(p)) or False)

    class Client:
        def upload_file(self, *a, **k):
            pass

    monkeypatch.setattr(storage, "_client", lambda: Client())
    monkeypatch.setattr(storage, "bucket", lambda: "b")
    monkeypatch.setattr(storage, "public_base_url", lambda: "https://cdn.test")
    clip = write(tmp_path / "c.mp4", box("ftyp"))
    assert storage.upload_file(clip, key="renders/c.mp4") == "https://cdn.test/renders/c.mp4"
    assert seen == [str(clip)]


def test_the_backfill_reads_the_layout_from_the_first_bytes():
    slow = box("ftyp", b"isom") + box("uuid", b"u" * 40) + box("free") + struct.pack(">I", 10_000_000) + b"mdat"
    fast = box("ftyp") + box("moov", b"m" * 20) + struct.pack(">I", 10_000_000) + b"mdat"
    assert faststart_clips.layout_from_head(slow, 10_000_100) == "index-last"
    assert faststart_clips.layout_from_head(fast, 10_000_100) == "index-first"
    assert faststart_clips.layout_from_head(box("ftyp") + b"\x00\x00", 100) == "unknown"
