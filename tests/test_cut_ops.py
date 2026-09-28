"""The timeline doc, its ops and its validator (src/cut/, CUT_EDITOR.md 5.1-5.2).

This module is the safety rail the edit agent will stand on, so it is
tested hardest: every op, every rejection, and the one property the whole
version history rests on -- an op never touches the doc it was handed.
"""
import copy

import pytest

from src.cut import doc as d
from src.cut import ops
from src.cut import validate as v

MEDIA = {
    "gen:1": {"frames": 150, "video": True, "audio": True},
    "gen:2": {"frames": 120, "video": True, "audio": True},
    "gen:3": {"frames": 90, "video": True, "audio": False},
    "asset:7": {"frames": 900, "video": False, "audio": True},
}


def cut():
    """V1: three shots butted together (0-150, 150-270, 270-360); A1: the
    first two shots' own sound, linked; A2: a music bed ducked under it."""
    return {
        "fps": 30, "size": [720, 1280], "duration": 360, "markers": [],
        "tracks": [
            {"id": "V1", "kind": "video", "clips": [
                {"id": "c1", "media": "gen:1", "src_in": 0, "src_out": 150, "at": 0, "speed": 1},
                {"id": "c2", "media": "gen:2", "src_in": 0, "src_out": 120, "at": 150, "speed": 1},
                {"id": "c3", "media": "gen:3", "src_in": 0, "src_out": 90, "at": 270, "speed": 1},
            ]},
            {"id": "A1", "kind": "audio", "role": "sfx", "clips": [
                {"id": "c1a", "media": "gen:1", "src_in": 0, "src_out": 150, "at": 0,
                 "speed": 1, "link": "c1", "gain_db": 0},
                {"id": "c2a", "media": "gen:2", "src_in": 0, "src_out": 120, "at": 150,
                 "speed": 1, "link": "c2", "gain_db": 0},
            ]},
            {"id": "A2", "kind": "audio", "role": "music", "duck_under": "sfx", "clips": [
                {"id": "m1", "media": "asset:7", "src_in": 0, "src_out": 360, "at": 0,
                 "speed": 1, "gain_db": -12},
            ]},
        ],
    }


def clip(doc, cid):
    return d.find_clip(doc, cid)[1]


def ats(doc, track_id):
    return [(c["id"], c["at"]) for c in d.track(doc, track_id)["clips"]]


# --------------------------------------------------------------------------
# the fixture itself is valid -- otherwise every rejection test below proves nothing
# --------------------------------------------------------------------------

def test_the_fixture_is_valid_against_its_media():
    assert v.problems(cut(), MEDIA) == []


def test_handles_parse_and_urls_do_not():
    assert d.parse_handle("gen:812") == ("gen", 812)
    assert d.parse_handle("asset:3") == ("asset", 3)
    for bad in ("https://x.r2.dev/renders/a.mp4", "/renders/a.mp4", "gen:0", "gen:-1",
                "gen:abc", "clip:3", "", None, 5):
        assert d.parse_handle(bad) is None, bad


def test_to_frames_never_claims_more_than_the_file_has():
    assert d.to_frames(10.042, 30) == 301
    assert d.to_frames(4.999, 30) == 149
    assert d.to_frames(5.0, 30) == 150


# --------------------------------------------------------------------------
# validate: each rejection
# --------------------------------------------------------------------------

def _has(doc, needle, media=MEDIA):
    found = v.problems(doc, media)
    assert any(needle in p for p in found), found
    return found


def test_overlap_on_a_track_is_rejected():
    doc = cut()
    clip(doc, "c2")["at"] = 140
    clip(doc, "c2a")["at"] = 140
    _has(doc, "overlap on V1")


def test_src_out_past_the_media_is_rejected():
    doc = cut()
    clip(doc, "c3")["src_out"] = 91
    doc["duration"] = 361
    _has(doc, "past the end of gen:3")


def test_unknown_handle_is_rejected():
    doc = cut()
    clip(doc, "c3")["media"] = "gen:99"
    _has(doc, "unknown media handle gen:99")


def test_a_url_in_place_of_a_handle_is_rejected_even_without_media():
    doc = cut()
    clip(doc, "c3")["media"] = "https://pub.r2.dev/renders/runway/x.mp4"
    _has(doc, "must be a gen:<id> or asset:<id> handle", media=None)


def test_duration_mismatch_is_rejected():
    doc = cut()
    doc["duration"] = 300
    _has(doc, "duration says 300 frames but the tracks end at 360")


def test_float_frames_are_rejected():
    doc = cut()
    clip(doc, "c1")["src_out"] = 150.0
    _has(doc, "whole frame number")


def test_negative_and_empty_clips_are_rejected():
    doc = cut()
    clip(doc, "c1")["src_in"] = 150
    _has(doc, "must be after src_in")
    doc = cut()
    clip(doc, "c1")["at"] = -1
    _has(doc, "cannot be negative")


def test_sound_from_a_silent_file_is_rejected():
    doc = cut()
    d.track(doc, "A1")["clips"].append(
        {"id": "c3a", "media": "gen:3", "src_in": 0, "src_out": 90, "at": 270,
         "speed": 1, "link": "c3"})
    _has(doc, "gen:3 has no sound")


def test_picture_from_an_audio_file_is_rejected():
    doc = cut()
    clip(doc, "c3")["media"] = "asset:7"
    _has(doc, "asset:7 has no picture")


def test_speed_and_lanes_are_refused_until_they_render():
    doc = cut()
    clip(doc, "c1")["speed"] = 2
    _has(doc, "speed 2 is not supported")
    doc = cut()
    clip(doc, "c1")["lanes"] = [{"path": "transform.scale", "keys": []}]
    _has(doc, "lanes are not supported")


def test_gain_out_of_range_is_rejected():
    doc = cut()
    clip(doc, "m1")["gain_db"] = 40
    _has(doc, "gain_db must be")


def test_bad_header_is_rejected():
    doc = cut()
    doc["fps"] = 29.97
    _has(doc, "fps must be a whole number")
    doc = cut()
    doc["size"] = [721, 1280]
    _has(doc, "size must be")


def test_duplicate_ids_and_tracks_are_rejected():
    doc = cut()
    clip(doc, "c2")["id"] = "c1"
    _has(doc, "id c1 is used twice")
    doc = cut()
    d.track(doc, "A2")["id"] = "A1"
    _has(doc, "track id A1 is used twice")


def test_bad_kind_role_and_duck_are_rejected():
    doc = cut()
    d.track(doc, "A2")["role"] = "dialogue"
    _has(doc, "role must be one of")
    doc = cut()
    d.track(doc, "A2")["duck_under"] = "music"
    _has(doc, "cannot duck under its own role")
    doc = cut()
    d.track(doc, "A2")["duck_under"] = "crowd"
    _has(doc, "duck_under must be a role")
    doc = cut()
    doc["tracks"].append({"id": "X1", "kind": "overlay", "clips": []})
    _has(doc, "kind must be one of")


def test_a_dangling_link_is_rejected():
    doc = cut()
    clip(doc, "c2a")["link"] = "c9"
    _has(doc, "links to c9")


def test_a_transition_must_overlap_by_exactly_its_length():
    doc = ops.add_transition(cut(), "c2", 10)
    assert v.problems(doc, MEDIA) == []
    clip(doc, "c2")["at"] += 1
    _has(doc, "transition must start 10 frames before c1 ends")


def test_a_transition_on_the_first_clip_is_rejected():
    doc = cut()
    clip(doc, "c1")["transition_in"] = {"kind": "xfade", "frames": 5}
    _has(doc, "needs a clip before it")


def test_a_transition_as_long_as_the_clip_is_rejected():
    doc = cut()
    clip(doc, "c3")["transition_in"] = {"kind": "wipe", "frames": 5}
    _has(doc, "kind must be one of")
    doc = cut()
    clip(doc, "c3")["transition_in"] = {"kind": "xfade", "frames": 90}
    _has(doc, "as long as the clip")


def test_captions_overlapping_or_empty_are_rejected():
    doc = ops.add_caption_track(cut(), [{"start": 0, "end": 60, "text": "one"},
                                        {"start": 60, "end": 120, "text": "two"}])
    assert v.problems(doc, MEDIA) == []
    d.track(doc, "T1")["cues"][1]["start"] = 50
    _has(doc, "overlap on T1")
    doc = cut()
    doc["tracks"].append({"id": "T1", "kind": "caption",
                          "cues": [{"id": "q1", "start": 0, "end": 30, "text": "  "}]})
    _has(doc, "text is empty")


def test_a_marker_past_the_end_is_rejected():
    doc = cut()
    doc["markers"] = [{"frame": 400, "label": "late"}]
    _has(doc, "past the end")


def test_validate_reports_every_problem_at_once():
    doc = cut()
    clip(doc, "c3")["media"] = "gen:99"
    doc["duration"] = 1
    with pytest.raises(v.InvalidDoc) as err:
        v.validate(doc, MEDIA)
    assert len(err.value.problems) == 2


# --------------------------------------------------------------------------
# ops: purity
# --------------------------------------------------------------------------

@pytest.mark.parametrize("name,args", [
    ("insert", {"track_id": "V1", "clip": {"media": "gen:3", "src_in": 0, "src_out": 30},
                "at": 150}),
    ("ripple_delete", {"clip_id": "c2"}),
    ("trim", {"clip_id": "c1", "tail": 10, "ripple": True}),
    ("split", {"clip_id": "c1", "frame": 60}),
    ("move", {"clip_id": "c3", "at": 300}),
    ("set_gain", {"clip_id": "m1", "db": -18}),
    ("duck", {"track_id": "A2", "under": None}),
    ("add_caption_track", {"cues": [{"start": 0, "end": 30, "text": "hi"}]}),
    ("add_marker", {"frame": 150, "label": "Shot 2"}),
    ("add_transition", {"clip_id": "c2", "frames": 8}),
])
def test_no_op_touches_the_doc_it_was_given(name, args):
    before = cut()
    frozen = copy.deepcopy(before)
    after = ops.OPS[name](before, **args)
    assert before == frozen
    assert after is not before
    assert v.problems(after, MEDIA) == [], name


# --------------------------------------------------------------------------
# ops: each one
# --------------------------------------------------------------------------

def test_insert_ripples_the_track_and_its_sound():
    doc = ops.insert(cut(), "V1", {"media": "gen:1", "src_in": 0, "src_out": 30},
                     at=150, sound_track="A1")
    assert ats(doc, "V1")[1][1] == 150 and clip(doc, "c2")["at"] == 180
    assert clip(doc, "c2a")["at"] == 180 and clip(doc, "c3")["at"] == 300
    new = ats(doc, "V1")[1][0]
    sound = [c for c in d.track(doc, "A1")["clips"] if c.get("link") == new]
    assert sound and sound[0]["at"] == 150
    assert doc["duration"] == 390


def test_insert_at_the_end_by_default_and_without_ripple():
    doc = ops.insert(cut(), "V1", {"media": "gen:3", "src_in": 0, "src_out": 30})
    assert ats(doc, "V1")[-1][1] == 360 and doc["duration"] == 390
    doc = ops.insert(cut(), "V1", {"media": "gen:3", "src_in": 0, "src_out": 30},
                     at=400, ripple=False)
    assert doc["duration"] == 430 and clip(doc, "c3")["at"] == 270


def test_insert_into_the_middle_of_a_clip_is_refused():
    with pytest.raises(ops.OpError, match="split it first"):
        ops.insert(cut(), "V1", {"media": "gen:3", "src_in": 0, "src_out": 30}, at=100)


def test_insert_never_carries_a_link_or_a_transition_in():
    doc = ops.insert(cut(), "V1", {"id": "c1", "media": "gen:3", "src_in": 0, "src_out": 30,
                                   "link": "c2", "transition_in": {"kind": "xfade", "frames": 3}})
    new = d.track(doc, "V1")["clips"][-1]
    assert new["id"] != "c1" and "link" not in new and "transition_in" not in new


def test_ripple_delete_closes_the_hole_on_every_track():
    doc = ops.ripple_delete(cut(), "c2")
    assert ats(doc, "V1") == [("c1", 0), ("c3", 150)]
    assert ats(doc, "A1") == [("c1a", 0)]
    assert doc["duration"] == 360          # the music bed still runs to 360


def test_ripple_delete_through_the_sound_deletes_the_picture():
    doc = ops.ripple_delete(cut(), "c1a")
    assert ats(doc, "V1") == [("c2", 0), ("c3", 120)]


def test_ripple_delete_keeps_a_gap_that_was_already_there():
    doc = ops.move(cut(), "c3", 300)          # a 30-frame gap before c3
    doc = ops.ripple_delete(doc, "c2")
    assert ats(doc, "V1") == [("c1", 0), ("c3", 180)]


def test_ripple_delete_drops_a_transition_that_faded_from_it():
    doc = ops.add_transition(cut(), "c3", 10)
    doc = ops.ripple_delete(doc, "c2")
    assert "transition_in" not in clip(doc, "c3")
    assert clip(doc, "c3")["at"] == 150
    assert v.problems(doc, MEDIA) == []


def test_ripple_delete_of_a_faded_in_clip_joins_its_neighbours_on_a_cut():
    doc = ops.add_transition(cut(), "c2", 10)     # c2 at 140
    doc = ops.ripple_delete(doc, "c2")
    assert ats(doc, "V1") == [("c1", 0), ("c3", 150)]
    assert v.problems(doc, MEDIA) == []


def test_trim_in_place_and_with_ripple():
    doc = ops.trim(cut(), "c2", head=20)
    assert clip(doc, "c2")["at"] == 170 and clip(doc, "c2")["src_in"] == 20
    assert clip(doc, "c2a")["src_in"] == 20 and clip(doc, "c3")["at"] == 270
    doc = ops.trim(cut(), "c2", head=20, tail=10, ripple=True)
    assert clip(doc, "c2")["at"] == 150 and d.clip_length(clip(doc, "c2")) == 90
    assert clip(doc, "c3")["at"] == 240


def test_trim_that_leaves_nothing_is_refused():
    with pytest.raises(ops.OpError, match="leaves nothing"):
        ops.trim(cut(), "c3", tail=90)


def test_extending_past_the_media_is_caught_by_apply():
    with pytest.raises(ops.OpError) as err:
        ops.apply(cut(), "trim", {"clip_id": "c3", "tail": -10, "ripple": True}, media=MEDIA)
    assert any("past the end of gen:3" in p for p in err.value.problems)


def test_split_makes_two_linked_halves():
    doc = ops.split(cut(), "c1", 60)
    v1 = d.track(doc, "V1")["clips"]
    assert [(c["at"], c["src_in"], c["src_out"]) for c in v1[:2]] == [(0, 0, 60), (60, 60, 150)]
    second = v1[1]
    halves = [c for c in d.track(doc, "A1")["clips"] if c["at"] == 60]
    assert halves and halves[0]["link"] == second["id"] and halves[0]["src_in"] == 60
    assert v.problems(doc, MEDIA) == []
    # the two halves have independent ids, so each can be deleted on its own
    doc = ops.ripple_delete(doc, second["id"])
    assert ats(doc, "V1") == [("c1", 0), ("c2", 60), ("c3", 180)]


def test_split_outside_the_clip_is_refused():
    for frame in (0, 150, 200):
        with pytest.raises(ops.OpError, match="not inside clip c1"):
            ops.split(cut(), "c1", frame)


def test_move_carries_the_sound_and_can_change_track():
    doc = ops.move(cut(), "c2", 400)
    assert clip(doc, "c2a")["at"] == 400
    doc = copy.deepcopy(cut())
    doc["tracks"].insert(1, {"id": "V2", "kind": "video", "clips": []})
    doc = ops.move(doc, "c3", 270, track_id="V2")
    assert ats(doc, "V2") == [("c3", 270)]
    with pytest.raises(ops.OpError, match="cannot move a video clip"):
        ops.move(cut(), "c3", 0, track_id="A1")


def test_a_move_into_another_clip_is_caught_by_apply():
    with pytest.raises(ops.OpError) as err:
        ops.apply(cut(), "move", {"clip_id": "c3", "at": 200}, media=MEDIA)
    assert any("overlap on V1" in p for p in err.value.problems)


def test_set_gain_is_for_sound_only():
    doc = ops.set_gain(cut(), "m1", -18)
    assert clip(doc, "m1")["gain_db"] == -18.0
    with pytest.raises(ops.OpError, match="not an audio track"):
        ops.set_gain(cut(), "c1", -3)


def test_duck_sets_and_clears():
    doc = ops.duck(cut(), "A2", "voice")
    assert d.track(doc, "A2")["duck_under"] == "voice"
    doc = ops.duck(doc, "A2", None)
    assert "duck_under" not in d.track(doc, "A2")
    with pytest.raises(ops.OpError):
        ops.duck(cut(), "V1", "voice")
    with pytest.raises(ops.OpError):
        ops.duck(cut(), "A2", "crowd")


def test_add_caption_track_numbers_itself_and_ids_its_cues():
    doc = ops.add_caption_track(cut(), [{"start": 0, "end": 30, "text": " one "},
                                        {"start": 30, "end": 60, "text": "two"}])
    t = d.track(doc, "T1")
    assert [q["id"] for q in t["cues"]] == ["q1", "q2"] and t["cues"][0]["text"] == "one"
    doc = ops.add_caption_track(doc, [{"start": 0, "end": 30, "text": "fr"}])
    assert d.track(doc, "T2") is not None
    # an explicitly EMPTY track is allowed (the editor types cues onto it);
    # a missing or non-list `cues` is still refused
    empty = ops.add_caption_track(cut(), [])
    assert d.track(empty, "T1")["cues"] == [] and v.problems(empty, MEDIA) == []
    with pytest.raises(ops.OpError):
        ops.add_caption_track(cut(), None)
    with pytest.raises(ops.OpError):
        ops.apply(cut(), "add_caption_track", {})


def test_captions_past_the_picture_extend_the_duration_and_validate():
    doc = ops.add_caption_track(cut(), [{"start": 300, "end": 400, "text": "late"}])
    assert doc["duration"] == 400 and v.problems(doc, MEDIA) == []


def test_add_marker_keeps_them_in_order():
    doc = ops.add_marker(ops.add_marker(cut(), 270, "Shot 3"), 150, "Shot 2")
    assert [m["frame"] for m in doc["markers"]] == [150, 270]


def test_add_transition_overlaps_and_shifts_everything_after():
    doc = ops.add_transition(cut(), "c2", 10)
    assert clip(doc, "c2")["at"] == 140 and clip(doc, "c2")["transition_in"]["frames"] == 10
    assert clip(doc, "c2a")["at"] == 140 and clip(doc, "c2a")["transition_in"]["frames"] == 10
    assert clip(doc, "c3")["at"] == 260 and doc["duration"] == 360   # music still to 360
    assert v.problems(doc, MEDIA) == []


def test_add_transition_needs_a_hard_cut():
    with pytest.raises(ops.OpError, match="hard cut"):
        ops.add_transition(cut(), "c1", 5)
    gapped = ops.move(cut(), "c3", 300)
    with pytest.raises(ops.OpError, match="hard cut"):
        ops.add_transition(gapped, "c3", 5)
    twice = ops.add_transition(cut(), "c2", 5)
    with pytest.raises(ops.OpError, match="hard cut"):
        ops.add_transition(twice, "c2", 5)


def test_a_transition_into_a_silent_clip_shifts_the_sound_track_consistently():
    doc = ops.add_transition(cut(), "c3", 10)       # c3 has no sound on A1
    assert clip(doc, "c3")["at"] == 260 and v.problems(doc, MEDIA) == []


def test_apply_names_unknown_ops_and_bad_arguments():
    with pytest.raises(ops.OpError, match="unknown op"):
        ops.apply(cut(), "explode")
    with pytest.raises(ops.OpError, match="trim"):
        ops.apply(cut(), "trim", {"clip": "c1"})
    with pytest.raises(ops.OpError, match="no clip c9"):
        ops.apply(cut(), "ripple_delete", {"clip_id": "c9"})


def test_apply_returns_the_edited_doc_when_it_validates():
    out = ops.apply(cut(), "ripple_delete", {"clip_id": "c3"}, media=MEDIA)
    assert [c["id"] for c in d.track(out, "V1")["clips"]] == ["c1", "c2"]
