"""Speed and reverse on a clip (2026-10-01): set_speed / set_reverse, what
split and trim do to a retimed clip, the validator, the render graph --
plus a real ffmpeg render that checks the reversed frames ARE reversed."""
import shutil
import subprocess
from pathlib import Path

import pytest

from src.cut import cleanup, ops, render
from src.cut import doc as d
from src.cut import validate as v

MEDIA = {"gen:1": {"frames": 300, "video": True, "audio": True},
         "gen:2": {"frames": 300, "video": True, "audio": True}}


def cut():
    doc = d.starter_doc(30, (720, 1280))
    doc = ops.apply(doc, "insert", {"track_id": "V1", "sound_track": "A1",
                                    "clip": {"media": "gen:1", "src_in": 0, "src_out": 120}}, media=MEDIA)
    doc = ops.apply(doc, "insert", {"track_id": "V1", "sound_track": "A1",
                                    "clip": {"media": "gen:2", "src_in": 0, "src_out": 60}}, media=MEDIA)
    return doc


def rows(doc, track="V1"):
    return [(c["id"], c["at"], c["src_in"], c["src_out"], c.get("dur"), bool(c.get("reverse")))
            for c in d.track(doc, track)["clips"]]


def test_set_speed_changes_the_length_and_ripples_what_follows():
    doc = ops.apply(cut(), "set_speed", {"clip_id": "c1", "speed": 2}, media=MEDIA)
    assert rows(doc) == [("c1", 0, 0, 120, 60, False), ("c2", 60, 0, 60, None, False)]
    # the linked sound is retimed with it
    assert [r[4] for r in rows(doc, "A1")] == [60, None]
    assert doc["duration"] == 120
    assert d.speed_of(d.track(doc, "V1")["clips"][0]) == 2
    back = ops.apply(doc, "set_speed", {"clip_id": "c1", "speed": 1}, media=MEDIA)
    assert "dur" not in d.track(back, "V1")["clips"][0]
    assert rows(back) == rows(cut())


def test_slow_motion_without_ripple_is_refused_when_it_runs_into_the_next_clip():
    with pytest.raises(ops.OpError) as e:
        ops.apply(cut(), "set_speed", {"clip_id": "c1", "speed": 0.5, "ripple": False}, media=MEDIA)
    assert any("overlap" in p or "starts" in p for p in e.value.problems), e.value.problems
    ok = ops.apply(cut(), "set_speed", {"clip_id": "c1", "speed": 0.5}, media=MEDIA)
    assert rows(ok)[1][1] == 240


@pytest.mark.parametrize("speed", [0.1, 5, "2", True])
def test_speed_out_of_range_is_refused(speed):
    with pytest.raises(ops.OpError):
        ops.apply(cut(), "set_speed", {"clip_id": "c1", "speed": speed}, media=MEDIA)


def test_keys_keep_their_place_in_the_clip():
    doc = ops.apply(cut(), "set_key", {"clip_id": "c1", "path": "zoom", "frame": 60, "value": 1.5},
                    media=MEDIA)
    doc = ops.apply(doc, "set_key", {"clip_id": "c1", "path": "zoom", "frame": 0, "value": 1.0},
                    media=MEDIA)
    doc = ops.apply(doc, "set_speed", {"clip_id": "c1", "speed": 2}, media=MEDIA)
    lane = d.track(doc, "V1")["clips"][0]["lanes"][0]
    assert [k["frame"] for k in lane["keys"]] == [0, 30]


def test_split_a_fast_clip_splits_the_timeline_exactly():
    doc = ops.apply(cut(), "set_speed", {"clip_id": "c1", "speed": 2}, media=MEDIA)
    doc = ops.apply(doc, "split", {"clip_id": "c1", "frame": 25}, media=MEDIA)
    assert rows(doc)[:2] == [("c1", 0, 0, 50, 25, False), ("c1_1", 25, 50, 120, 35, False)]


def test_split_a_reversed_clip_gives_the_first_half_the_END_of_the_source():
    doc = ops.apply(cut(), "set_speed", {"clip_id": "c1", "speed": 2}, media=MEDIA)
    doc = ops.apply(doc, "set_reverse", {"clip_id": "c1"}, media=MEDIA)
    doc = ops.apply(doc, "split", {"clip_id": "c1", "frame": 20}, media=MEDIA)
    assert rows(doc)[:2] == [("c1", 0, 80, 120, 20, True), ("c1_1", 20, 0, 80, 40, True)]


def test_trim_a_fast_clip_moves_the_source_by_the_speed():
    doc = ops.apply(cut(), "set_speed", {"clip_id": "c1", "speed": 2}, media=MEDIA)
    doc = ops.apply(doc, "trim", {"clip_id": "c1", "head": 10, "tail": 5, "ripple": True}, media=MEDIA)
    assert rows(doc) == [("c1", 0, 20, 110, 45, False), ("c2", 45, 0, 60, None, False)]
    rev = ops.apply(cut(), "set_speed", {"clip_id": "c1", "speed": 2}, media=MEDIA)
    rev = ops.apply(rev, "set_reverse", {"clip_id": "c1"}, media=MEDIA)
    rev = ops.apply(rev, "trim", {"clip_id": "c1", "head": 10, "tail": 0}, media=MEDIA)
    # trimming the head of a reversed clip takes from the END of its source
    assert rows(rev)[0] == ("c1", 10, 0, 100, 50, True)


def test_reverse_keeps_place_and_length_and_comes_back_off():
    doc = ops.apply(cut(), "set_reverse", {"clip_id": "c1", "on": True}, media=MEDIA)
    assert rows(doc)[0] == ("c1", 0, 0, 120, None, True)
    assert d.track(doc, "A1")["clips"][0]["reverse"] is True
    off = ops.apply(doc, "set_reverse", {"clip_id": "c1", "on": False}, media=MEDIA)
    assert "reverse" not in d.track(off, "V1")["clips"][0]


def test_source_and_timeline_frames_map_both_ways():
    c = {"at": 100, "src_in": 30, "src_out": 90, "dur": 30}
    assert d.source_frame(c, 10) == 50 and d.timeline_frame(c, 50) == 110
    c["reverse"] = True
    assert d.source_frame(c, 10) == 70 and d.timeline_frame(c, 70) == 110


def test_the_validator_checks_dur_and_reverse():
    doc = cut()
    d.track(doc, "V1")["clips"][0]["dur"] = 20         # 6x
    assert any("outside 0.25x-4x" in p for p in v.problems(doc))
    doc = cut()
    d.track(doc, "V1")["clips"][0]["dur"] = 0
    assert any("dur must be" in p for p in v.problems(doc))
    doc = cut()
    d.track(doc, "V1")["clips"][0]["reverse"] = "yes"
    assert any("reverse must be" in p for p in v.problems(doc))


def test_describe():
    assert ops.describe("set_speed", {"clip_id": "c1", "speed": 2}) == "speed 2x on c1"
    assert ops.describe("set_reverse", {"clip_id": "c1", "on": False}) == "play forwards c1"


def test_captions_follow_the_speed_and_skip_a_reversed_clip():
    doc = ops.apply(cut(), "set_speed", {"clip_id": "c1", "speed": 2}, media=MEDIA)
    timing = {"fps": 30, "words": [{"start_f": 60, "end_f": 70, "text": "hello"}]}
    assert cleanup.timeline_words(doc, {"gen:1": timing}) == [(30, 35, "hello")]
    rev = ops.apply(doc, "set_reverse", {"clip_id": "c1"}, media=MEDIA)
    assert cleanup.timeline_words(rev, {"gen:1": timing}) == []


def test_clean_up_skips_retimed_sound_with_a_note():
    doc = ops.apply(cut(), "set_speed", {"clip_id": "c1", "speed": 2}, media=MEDIA)
    units, notes = cleanup.sound_units(doc, MEDIA)
    assert [c["id"] for _, c in units] == ["c2a1"]
    assert any("sped up, slowed or reversed" in n for n in notes)


def test_the_graph_retimes_picture_and_sound():
    doc = ops.apply(cut(), "set_speed", {"clip_id": "c1", "speed": 2}, media=MEDIA)
    doc = ops.apply(doc, "set_reverse", {"clip_id": "c2"}, media=MEDIA)
    paths = {"gen:1": Path("/x/a.mp4"), "gen:2": Path("/x/b.mp4")}
    argv = render.compile_args(doc, paths, Path("/x/o.mp4"))
    graph = argv[argv.index("-filter_complex") + 1]
    assert "setpts=PTS*0.500000" in graph and "atempo=2.000000" in graph
    assert "trim=end=2" in graph            # the sped clip held to its exact length
    assert ",reverse," in graph and "areverse" in graph
    # with a pre-reversed file the graph reads it and never holds the span
    pre = render.compile_args(doc, {**paths, "rev:c2": Path("/x/rev.mp4")}, Path("/x/o.mp4"))
    pgraph = pre[pre.index("-filter_complex") + 1]
    assert ",reverse," not in pgraph and "/x/rev.mp4" in pre
    assert render._atempo(4) == ["atempo=2.0", "atempo=2.000000"]
    assert render._atempo(0.25) == ["atempo=0.5", "atempo=0.500000"]


def _luma(path: Path, seconds: float) -> int:
    out = subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", f"{seconds}", "-i", str(path),
                          "-vf", "scale=1:1", "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                         capture_output=True, check=True).stdout
    return out[0]


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg is not installed")
def test_a_reversed_and_a_fast_clip_really_render(tmp_path, monkeypatch):
    # a picture that brightens over its 3 s, so direction is measurable
    src = tmp_path / "ramp.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "nullsrc=s=64x64:r=30,geq=lum='16+T*60':cb=128:cr=128",
                    "-f", "lavfi", "-i", "sine=frequency=440", "-t", "3",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(src)],
                   check=True)
    media = {"gen:1": {"frames": 90, "video": True, "audio": True}}
    doc = d.starter_doc(30, (128, 128))
    for _ in range(2):
        doc = ops.apply(doc, "insert", {"track_id": "V1", "sound_track": "A1",
                                        "clip": {"media": "gen:1", "src_in": 0, "src_out": 90}}, media=media)
    doc = ops.apply(doc, "set_reverse", {"clip_id": "c1"}, media=media)
    doc = ops.apply(doc, "set_speed", {"clip_id": "c2", "speed": 2}, media=media)
    assert doc["duration"] == 135
    monkeypatch.setattr(render, "REVERSE_CHUNK_SECONDS", 0.5)    # several chunks, joined
    got = render.render(doc, account_id=None, name="speed", paths={"gen:1": src}, media=media,
                        out_dir=tmp_path)
    assert got["notes"] == [], got["notes"]
    assert abs(got["seconds"] - 4.5) < 0.1
    out = Path(got["path"])
    # reversed: bright first, dark last; then the fast clip dark -> bright
    assert _luma(out, 0.1) > 150 and _luma(out, 2.85) < 60
    assert _luma(out, 3.05) < 60 and _luma(out, 4.4) > 150
    # monotone across the reversed clip's chunk joins
    lumas = [_luma(out, t / 10) for t in range(1, 29, 3)]
    assert lumas == sorted(lumas, reverse=True), lumas


@pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg is not installed")
def test_a_reversed_source_keeps_its_length_across_chunk_joins(tmp_path, monkeypatch):
    # ffmpeg 7.1's concat demuxer read each piece a frame short, so a joined
    # file lost one frame of time per join unless the listing states it
    src = tmp_path / "ramp.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "nullsrc=s=64x64:r=30,geq=lum='16+T*60':cb=128:cr=128", "-t", "3",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(src)], check=True)
    monkeypatch.setattr(render, "REVERSE_CHUNK_SECONDS", 0.5)    # six pieces, five joins
    rev = render.reverse_source("ffmpeg", src, 0, 90, 30, tmp_path, "rev")
    got = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
                          "-show_entries", "stream=nb_read_frames,duration", "-of", "csv=p=0", str(rev)],
                         capture_output=True, text=True, check=True).stdout.strip().split(",")
    seconds, frames = float(got[0]), int(got[1])
    assert frames == 90
    assert abs(seconds - 3.0) < 0.5 / 30, seconds
