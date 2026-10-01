"""The editor's ops, the validator rules they lean on, the op summaries,
and the renderer's half of them (phase B of docs/CUT_EDITOR.md).

Pure: no database, no ffmpeg -- the ffmpeg-backed parts are in
test_cut_preview.py and test_cut_projects.py.
"""
import copy
from pathlib import Path

import pytest

from src.cut import doc as d
from src.cut import ops, render
from src.cut import validate as v

MEDIA = {
    "gen:1": {"frames": 150, "video": True, "audio": True},
    "gen:2": {"frames": 120, "video": True, "audio": True},
    "gen:3": {"frames": 90, "video": True, "audio": False},
    "asset:7": {"frames": 900, "video": False, "audio": True},
}


def cut():
    """V1: three shots, the second crossfading in from the first; A1 their
    sound, linked; T1 a caption track with two cues."""
    return {
        "fps": 30, "size": [720, 1280], "duration": 352, "markers": [],
        "tracks": [
            {"id": "V1", "kind": "video", "clips": [
                # a zoom lane at its default: renders exactly as none, and gives
                # delete_key / clear_lane a key to act on
                {"id": "c1", "media": "gen:1", "src_in": 0, "src_out": 150, "at": 0, "speed": 1,
                 "lanes": [{"path": "zoom", "keys": [{"frame": 0, "value": 1.0, "ease": "linear"}]}]},
                {"id": "c2", "media": "gen:2", "src_in": 0, "src_out": 120, "at": 142, "speed": 1,
                 "transition_in": {"kind": "xfade", "frames": 8}},
                {"id": "c3", "media": "gen:3", "src_in": 0, "src_out": 90, "at": 262, "speed": 1},
            ]},
            {"id": "A1", "kind": "audio", "role": "sfx", "clips": [
                {"id": "c1a", "media": "gen:1", "src_in": 0, "src_out": 150, "at": 0,
                 "speed": 1, "link": "c1", "gain_db": 0},
                {"id": "c2a", "media": "gen:2", "src_in": 0, "src_out": 120, "at": 142,
                 "speed": 1, "link": "c2", "gain_db": 0,
                 "transition_in": {"kind": "xfade", "frames": 8}},
            ]},
            {"id": "T1", "kind": "caption", "style": "preset:bold_center", "cues": [
                {"id": "q1", "start": 0, "end": 45, "text": "one"},
                {"id": "q2", "start": 60, "end": 90, "text": "two"}]},
        ],
    }


def test_the_fixture_is_valid():
    assert v.problems(cut(), MEDIA) == []


# --------------------------------------------------------------------------
# lift
# --------------------------------------------------------------------------

def test_lift_leaves_the_gap_and_moves_nothing():
    doc = ops.lift(cut(), "c3")
    assert [c["id"] for c in d.track(doc, "V1")["clips"]] == ["c1", "c2"]
    assert doc["duration"] == 262 and v.problems(doc, MEDIA) == []


def test_lift_takes_the_partners_and_drops_the_next_clips_transition():
    doc = ops.lift(cut(), "c1")
    assert d.find_clip(doc, "c1a") is None
    c2 = d.find_clip(doc, "c2")[1]
    assert c2["at"] == 142 and "transition_in" not in c2
    assert "transition_in" not in d.find_clip(doc, "c2a")[1]
    assert v.problems(doc, MEDIA) == []


def test_lifting_from_the_sound_lifts_the_picture_too():
    doc = ops.lift(cut(), "c2a")
    assert d.find_clip(doc, "c2") is None and d.find_clip(doc, "c3")[1]["at"] == 262


def test_lift_refuses_a_clip_that_is_not_there():
    with pytest.raises(ops.OpError):
        ops.lift(cut(), "nope")


# --------------------------------------------------------------------------
# set_canvas
# --------------------------------------------------------------------------

def test_set_canvas_changes_the_frame_and_nothing_else():
    doc = ops.set_canvas(cut(), 1280, 720)
    assert doc["size"] == [1280, 720]
    assert doc["tracks"] == cut()["tracks"]


def test_set_canvas_odd_or_silly_sizes_are_the_validators_to_refuse():
    with pytest.raises(ops.OpError) as e:
        ops.apply(cut(), "set_canvas", {"width": 721, "height": 1280})
    assert any("even" in p for p in e.value.problems)
    with pytest.raises(ops.OpError):
        ops.set_canvas(cut(), "720", 1280)


# --------------------------------------------------------------------------
# captions
# --------------------------------------------------------------------------

def test_set_cue_adds_one_with_a_fresh_id():
    doc = ops.set_cue(cut(), "T1", 100, 130, "  three ")
    cues = d.track(doc, "T1")["cues"]
    assert [q["id"] for q in cues] == ["q1", "q2", "q3"] and cues[-1]["text"] == "three"


def test_set_cue_with_an_id_edits_that_cue():
    doc = ops.set_cue(cut(), "T1", 10, 40, "ONE", cue_id="q1")
    assert d.track(doc, "T1")["cues"][0] == {"id": "q1", "start": 10, "end": 40, "text": "ONE"}


def test_set_cue_refuses_a_missing_cue_a_missing_track_and_a_clip_track():
    with pytest.raises(ops.OpError):
        ops.set_cue(cut(), "T1", 0, 10, "x", cue_id="q9")
    with pytest.raises(ops.OpError):
        ops.set_cue(cut(), "T9", 0, 10, "x")
    with pytest.raises(ops.OpError):
        ops.set_cue(cut(), "V1", 0, 10, "x")


def test_an_overlapping_or_empty_cue_is_the_validators_to_refuse():
    with pytest.raises(ops.OpError) as e:
        ops.apply(cut(), "set_cue", {"track_id": "T1", "start": 30, "end": 70, "text": "x"})
    assert any("overlap" in p for p in e.value.problems)
    with pytest.raises(ops.OpError) as e:
        ops.apply(cut(), "set_cue", {"track_id": "T1", "start": 100, "end": 120, "text": " "})
    assert any("empty" in p for p in e.value.problems)


def test_delete_cue():
    doc = ops.delete_cue(cut(), "T1", "q1")
    assert [q["id"] for q in d.track(doc, "T1")["cues"]] == ["q2"]
    with pytest.raises(ops.OpError):
        ops.delete_cue(cut(), "T1", "q1x")


def test_set_caption_style_only_takes_a_style_the_renderer_draws():
    for style in d.CAPTION_STYLES:
        assert d.track(ops.set_caption_style(cut(), "T1", style), "T1")["style"] == style
    with pytest.raises(ops.OpError):
        ops.set_caption_style(cut(), "T1", "preset:comic_sans")


def test_the_validator_refuses_an_unknown_style_from_any_writer():
    doc = cut()
    d.track(doc, "T1")["style"] = "preset:nope"
    assert any("style" in p for p in v.problems(doc, MEDIA))


def test_an_empty_caption_track_is_valid_and_cues_can_then_be_typed_onto_it():
    doc = ops.apply(cut(), "add_caption_track", {"cues": [], "style": "preset:lower_third"})
    t2 = d.track(doc, "T2")
    assert t2["cues"] == [] and t2["style"] == "preset:lower_third"
    doc = ops.apply(doc, "set_cue", {"track_id": "T2", "start": 0, "end": 30, "text": "hi"},
                    media=MEDIA)
    assert d.track(doc, "T2")["cues"][0]["id"] == "q3"


# --------------------------------------------------------------------------
# the validator: unmeasured media
# --------------------------------------------------------------------------

def test_a_handle_mapped_to_none_is_known_but_unmeasured():
    media = {**MEDIA, "gen:2": None}
    assert v.problems(cut(), media) == []
    del media["gen:2"]
    assert any("unknown media handle gen:2" in p for p in v.problems(cut(), media))


# --------------------------------------------------------------------------
# describe: every op has words
# --------------------------------------------------------------------------

ARGS = {
    "insert": {"track_id": "V1", "clip": {"media": "gen:3", "src_in": 0, "src_out": 30},
               "at": 262},
    "ripple_delete": {"clip_id": "c2"},
    "lift": {"clip_id": "c3"},
    "trim": {"clip_id": "c1", "head": 0, "tail": -10},
    "split": {"clip_id": "c3", "frame": 126 + 150},
    "move": {"clip_id": "c3", "at": 300},
    "set_gain": {"clip_id": "c1a", "db": -6},
    "duck": {"track_id": "A1", "under": "voice"},
    "add_caption_track": {"cues": []},
    "add_marker": {"frame": 150, "label": "Shot 2"},
    "add_transition": {"clip_id": "c3", "frames": 8},
    "set_canvas": {"width": 1280, "height": 720},
    "set_cue": {"track_id": "T1", "start": 100, "end": 130, "text": "three"},
    "delete_cue": {"track_id": "T1", "cue_id": "q2"},
    "set_caption_style": {"track_id": "T1", "style": "preset:minimal_top"},
    "add_track": {"kind": "audio", "role": "music"},
    "overwrite": {"track_id": "V1", "clip": {"media": "gen:3", "src_in": 0, "src_out": 30}, "at": 60},
    "set_key": {"clip_id": "c1", "path": "zoom", "frame": 30, "value": 1.5},
    "delete_key": {"clip_id": "c1", "path": "zoom", "frame": 0},
    "clear_lane": {"clip_id": "c1", "path": "zoom"},
    "set_crop": {"clip_id": "c1", "left": 0.1},
    "set_opacity": {"clip_id": "c1", "value": 0.5},
    "set_speed": {"clip_id": "c1", "speed": 2},
    "set_reverse": {"clip_id": "c1", "on": True},
}


def test_every_op_has_a_summary_and_it_is_not_just_its_name():
    assert set(ARGS) == set(ops.OPS)
    for name, args in ARGS.items():
        text = ops.describe(name, args, 30)
        assert text and text != name, name


def test_the_summary_speaks_seconds():
    assert ops.describe("split", {"clip_id": "c3", "frame": 126}, 30) == "split c3 at 4.2s"
    assert ops.describe("trim", {"clip_id": "c1", "head": 10}, 30) == "trim c1 head +10f"


def test_describe_never_raises_on_garbage():
    assert ops.describe("split", {"frame": "soon"}, 30)
    assert ops.describe("made_up", None, 30) == "made_up"


@pytest.mark.parametrize("name", sorted(ARGS))
def test_no_new_or_old_op_touches_the_doc_it_was_given(name):
    before = cut()
    frozen = copy.deepcopy(before)
    ops.OPS[name](before, **ARGS[name])
    assert before == frozen


# --------------------------------------------------------------------------
# the doc helpers
# --------------------------------------------------------------------------

def test_aspect_names_the_offered_canvases_and_reduces_the_rest():
    assert d.aspect_of([720, 1280]) == "9:16" and d.aspect_of([1080, 1920]) == "9:16"
    assert d.aspect_of([1280, 720]) == "16:9" and d.aspect_of([1080, 1080]) == "1:1"
    assert d.aspect_of([1080, 1350]) == "4:5"


def test_the_starter_doc_is_valid_and_has_somewhere_to_put_things():
    doc = d.starter_doc(30, d.ASPECT_SIZES["16:9"])
    assert v.problems(doc) == [] and doc["size"] == [1280, 720]
    assert [(t["id"], t.get("role")) for t in doc["tracks"]] == [
        ("V1", None), ("A1", "sfx"), ("A2", "music")]
    assert "duck_under" not in d.track(doc, "A2")


# --------------------------------------------------------------------------
# render: the caption looks and stills
# --------------------------------------------------------------------------

def test_every_caption_style_is_one_the_renderer_draws():
    assert set(render.CAPTION_PRESETS) == set(d.CAPTION_STYLES)


def test_the_three_looks_render_as_three_different_ass_styles():
    doc = cut()
    doc = ops.add_caption_track(doc, [{"start": 100, "end": 130, "text": "a name"}],
                                style="preset:lower_third")
    doc = ops.add_caption_track(doc, [{"start": 140, "end": 160, "text": "quiet"}],
                                style="preset:minimal_top")
    styles = [ln for ln in render.ass_document(doc).splitlines() if ln.startswith("Style:")]
    assert len(styles) == 3
    fields = [s.split(",") for s in styles]
    # Format: ... BorderStyle(16), Outline, Shadow, Alignment(19) ...
    assert [f[18] for f in fields] == ["2", "1", "8"]          # centre, lower-left, top
    assert fields[1][15] == "3" and fields[0][15] == "1"       # lower third is boxed
    assert fields[2][7] == "0"                                 # minimal_top is not bold


def test_a_still_is_looped_and_bounded():
    doc = {"fps": 30, "size": [720, 1280], "duration": 90, "markers": [],
           "tracks": [{"id": "V1", "kind": "video", "clips": [
               {"id": "c1", "media": "asset:4", "src_in": 0, "src_out": 60, "at": 0, "speed": 1},
               {"id": "c2", "media": "gen:1", "src_in": 0, "src_out": 30, "at": 60, "speed": 1}]}]}
    paths = {"asset:4": Path("/x/still.png"), "gen:1": Path("/x/clip.mp4")}
    argv = render.compile_args(doc, paths, Path("/x/out.mp4"),
                               stills=render.stills_in(None, paths))
    i = argv.index("/x/still.png")
    assert argv[i - 10:i] == ["-loop", "1", "-framerate", "30", "-t", "2",
                              "-threads", str(render.DECODE_THREADS), "-an", "-i"]
    j = argv.index("/x/clip.mp4")
    assert argv[j - 2:j] == ["-an", "-i"] and "-loop" not in argv[j - 5:j]
    assert render.stills_in({"gen:9": {"still": True}}, {}) == {"gen:9"}


# --------------------------------------------------------------------------
# add_track (the first live walk, 2026-09-29: an Assembled cut has no
# music track, so a bed had nowhere to go but behind the clips' sound)
# --------------------------------------------------------------------------

def test_add_track_takes_the_next_free_id_and_validates():
    doc = cut()
    out = ops.apply(doc, "add_track", {"kind": "audio", "role": "music"}, media=MEDIA)
    music = d.track(out, "A2")
    assert music == {"id": "A2", "kind": "audio", "role": "music", "clips": []}
    assert d.track(doc, "A2") is None, "the input is untouched"
    out = ops.apply(out, "add_track", {"kind": "video"}, media=MEDIA)
    assert d.track(out, "V2") == {"id": "V2", "kind": "video", "clips": []}
    out = ops.apply(out, "add_track", {"kind": "caption"}, media=MEDIA)
    assert d.track(out, "T2")["cues"] == [] and d.track(out, "T2")["style"] == d.DEFAULT_CAPTION_STYLE
    # a bed on its own track can be laid under the picture and ducked
    out = ops.apply(out, "insert", {"track_id": "A2", "at": 0, "ripple": False,
                                    "clip": {"media": "asset:7", "src_in": 0, "src_out": 352}},
                    media=MEDIA)
    out = ops.apply(out, "duck", {"track_id": "A2", "under": "sfx"}, media=MEDIA)
    assert out["duration"] == 352


@pytest.mark.parametrize("args, reason", [
    ({"kind": "audio"}, "needs a role"),
    ({"kind": "audio", "role": "drums"}, "needs a role"),
    ({"kind": "video", "role": "music"}, "only audio tracks"),
    ({"kind": "subtitle"}, "track kind"),
    ({"kind": "audio", "role": "music", "track_id": "A1"}, "already exists"),
])
def test_add_track_refuses(args, reason):
    with pytest.raises(ops.OpError) as e:
        ops.apply(cut(), "add_track", args, media=MEDIA)
    assert reason in str(e.value)


def test_add_track_is_described():
    assert ops.describe("add_track", {"kind": "audio", "role": "music"}) == "add music track"


# --------------------------------------------------------------------------
# overwrite (the Source viewer's F10, 2026-10-01): lay a clip over what is
# there; nothing after it moves
# --------------------------------------------------------------------------

def _spans(doc, tid):
    return [(c["id"], c["at"], c["src_in"], c["src_out"]) for c in d.track(doc, tid)["clips"]]


def test_overwrite_in_the_middle_of_a_clip_splits_it_around_the_new_one():
    doc = cut()
    out = ops.apply(doc, "overwrite", {"track_id": "V1", "at": 30, "sound_track": "A1",
                                       "clip": {"media": "gen:2", "src_in": 0, "src_out": 30}},
                    media=MEDIA)
    v1 = _spans(out, "V1")
    assert v1[0] == ("c1", 0, 0, 30)                     # c1 cut at 30
    assert (v1[1][1], v1[1][2], v1[1][3]) == (30, 0, 30)  # the new clip, 30-60
    assert v1[2][1:] == (60, 60, 150)                    # c1's tail from 60 on, same source
    assert out["duration"] == doc["duration"], "nothing after it moved"
    # its own sound landed on A1, linked, and c1's sound was cleared with c1
    a1 = _spans(out, "A1")
    assert (a1[1][1], a1[1][3]) == (30, 30)
    new = d.track(out, "V1")["clips"][1]["id"]
    assert d.track(out, "A1")["clips"][1]["link"] == new
    assert v.problems(out, MEDIA) == []


def test_overwrite_across_a_cut_replaces_both_sides_and_leaves_the_rest():
    doc = cut()
    # 120-200 covers c1's tail (to 150) and c2's head (c2 starts 142 with an 8f fade)
    out = ops.apply(doc, "overwrite", {"track_id": "V1", "at": 120,
                                       "clip": {"media": "gen:3", "src_in": 0, "src_out": 80}},
                    media=MEDIA)
    v1 = _spans(out, "V1")
    assert [x[1] for x in v1] == [0, 120, 200, 262]
    assert v1[0][3] == 120 and v1[2][2] == 58        # c1 ends at 120; c2 resumes 58f in
    assert v.problems(out, MEDIA) == []


def test_overwrite_past_the_end_just_places_it():
    doc = cut()
    out = ops.apply(doc, "overwrite", {"track_id": "V1", "at": 400,
                                       "clip": {"media": "gen:3", "src_in": 0, "src_out": 30}},
                    media=MEDIA)
    assert _spans(out, "V1")[-1][1] == 400 and out["duration"] == 430


@pytest.mark.parametrize("args, reason", [
    ({"track_id": "V9", "at": 0, "clip": {"media": "gen:3", "src_in": 0, "src_out": 30}}, "no track"),
    ({"track_id": "V1", "at": -5, "clip": {"media": "gen:3", "src_in": 0, "src_out": 30}}, "negative"),
    ({"track_id": "V1", "at": 0, "clip": {"media": "gen:3", "src_in": 30, "src_out": 30}}, "after src_in"),
    ({"track_id": "V1", "at": 0, "sound_track": "V1",
      "clip": {"media": "gen:1", "src_in": 0, "src_out": 30}}, "not audio"),
])
def test_overwrite_refuses(args, reason):
    with pytest.raises(ops.OpError) as e:
        ops.apply(cut(), "overwrite", args, media=MEDIA)
    assert reason in str(e.value)


def test_overwrite_is_described():
    assert ops.describe("overwrite", {"track_id": "V1", "at": 90, "clip": {"media": "gen:2"}}, 30) \
        == "overwrite gen:2 on V1 at 3.0s"
