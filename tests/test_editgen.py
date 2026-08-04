"""Tests for editgen.py's plain-text cut-list formatter (the --print flag),
validate_edit's handling of generative clip slots, and the revise_until_valid
self-correction loop."""

import json

from src.editgen import (
    format_edit_as_text,
    merge_warnings,
    revise_until_valid,
    validate_edit,
)

SAMPLE_EDIT = {
    "title": "Cold Open",
    "edit_list": [
        {"clip": "A037_0812_C001.mov", "in": 2.0, "out": 6.5},
        {"clip": "A037_0812_C002.mov", "in": 0.0, "out": 4.0},
    ],
}


def test_format_title_is_header():
    assert format_edit_as_text(SAMPLE_EDIT).splitlines()[0] == "Cold Open"


def test_format_includes_clip_names():
    out = format_edit_as_text(SAMPLE_EDIT)
    assert "A037_0812_C001.mov" in out
    assert "A037_0812_C002.mov" in out


def test_format_includes_in_and_out_points():
    out = format_edit_as_text(SAMPLE_EDIT)
    assert "2.00" in out
    assert "6.50" in out


def test_format_running_total_accumulates():
    lines = format_edit_as_text(SAMPLE_EDIT).splitlines()
    assert "4.50" in lines[1]  # first cut's own duration
    assert "8.50" in lines[2]  # running total after the second cut


# ---------- validate_edit: generative slots ----------

MANIFEST_BY_NAME = {
    "A037_0812_C001.mov": {"filename": "A037_0812_C001.mov", "duration_seconds": 20.0},
}


def test_one_generative_slot_with_description_validates():
    edit = {
        "title": "Test",
        "edit_list": [
            {"clip": "A037_0812_C001.mov", "in": 0.0, "out": 10.0},
            {"source": "generate", "description": "a gloved hand closes a steel drawer",
             "in": 0.0, "out": 4.0},
        ],
    }
    assert validate_edit(edit, MANIFEST_BY_NAME) == []


def test_two_generative_slots_rejected():
    edit = {
        "title": "Test",
        "edit_list": [
            {"source": "generate", "description": "a hand on a wrench", "in": 0.0, "out": 7.0},
            {"source": "generate", "description": "a door swings shut", "in": 0.0, "out": 7.0},
        ],
    }
    warnings = validate_edit(edit, MANIFEST_BY_NAME)
    assert any("one generative slot" in w for w in warnings)


def test_generative_slot_without_description_rejected():
    edit = {
        "title": "Test",
        "edit_list": [
            {"clip": "A037_0812_C001.mov", "in": 0.0, "out": 10.0},
            {"source": "generate", "in": 0.0, "out": 4.0},
        ],
    }
    warnings = validate_edit(edit, MANIFEST_BY_NAME)
    assert any("description" in w for w in warnings)


# ---------- merge_warnings ----------
# The model sometimes writes edit["warnings"] as a single string rather
# than a list. list("a string") shatters it into one warning per
# character -- that's the bug this guards against.

def test_merge_warnings_wraps_a_string_instead_of_splitting_it():
    edit = {"warnings": "subject looks at lens in the punch"}
    assert merge_warnings(edit, ["real problem"]) == [
        "subject looks at lens in the punch", "real problem",
    ]


def test_merge_warnings_handles_a_list_normally():
    edit = {"warnings": ["already a list"]}
    assert merge_warnings(edit, ["another"]) == ["already a list", "another"]


def test_merge_warnings_handles_missing_field():
    assert merge_warnings({}, ["x"]) == ["x"]


def test_records_the_selection_on_a_brand_new_database(tmp_path):
    """
    Same fresh-clone hazard as pitch.py: no pre-existing schema. The
    module has to create it rather than warn and drop the label.
    """
    from src import db, editgen

    fresh = tmp_path / "brand-new.db"
    editgen.record_selection(None, [2], db_path=fresh)   # no init beforehand
    assert db.summary(fresh) == {
        "pitch_runs": 0, "ideas": 0, "videos": 0, "metrics": 0
    }


def test_validate_edit_reports_non_numeric_cut_points_instead_of_crashing():
    """
    The model sometimes returns timecode strings. Raising here discards
    the whole paid generation, since concepts.json is written after the
    loop -- so this has to be a warning like any other bad value.
    """
    edit = {"edit_list": [{"clip": "A037_0812_C001.mov", "in": "0:02", "out": "0:06"}]}
    warnings = validate_edit(edit, MANIFEST_BY_NAME)
    assert any("not a number" in w for w in warnings)


def test_validate_edit_survives_a_null_duration_in_the_manifest():
    edit = {"edit_list": [{"clip": "B.mov", "in": 0.0, "out": 5.0}]}
    warnings = validate_edit(edit, {"B.mov": {"duration_seconds": None}})
    assert any("B.mov" in w for w in warnings)


# ---------- revise_until_valid: the level-3 decide -> act -> check loop ----------

BROKEN_EDIT = {
    "title": "Cold Open",
    "edit_list": [{"clip": "unknown_clip.mov", "in": 0.0, "out": 15.0}],
}

FIXED_EDIT = {
    "title": "Cold Open",
    "edit_list": [{"clip": "A037_0812_C001.mov", "in": 0.0, "out": 15.0}],
}

PITCH = {"number": 1, "title": "Cold Open", "logline": "x", "story_note": "A037_0812_C001"}
MANIFEST = [{"filename": "A037_0812_C001.mov", "duration_seconds": 20.0}]


def test_revise_until_valid_accepts_a_fix_on_the_first_attempt(monkeypatch):
    """The core loop: broken edit in, one round-trip, clean edit out."""
    import src.editgen as editgen

    monkeypatch.setattr(editgen, "generate_with_retry", lambda client, model, prompt: json.dumps(FIXED_EDIT))

    edit, warnings = revise_until_valid(
        client=None, model="test-model", pitch=PITCH, manifest=MANIFEST,
        manifest_by_name=MANIFEST_BY_NAME, edit=BROKEN_EDIT,
    )

    assert warnings == []
    assert edit["edit_list"][0]["clip"] == "A037_0812_C001.mov"
    assert edit["revision_attempts"] == 1


def test_revise_until_valid_stops_at_the_attempt_budget(monkeypatch):
    """A model that never actually fixes it shouldn't loop forever or
    silently keep paying for more attempts than the budget allows."""
    import src.editgen as editgen

    calls = []

    def fake_generate(client, model, prompt):
        calls.append(prompt)
        return json.dumps(BROKEN_EDIT)  # returns the same broken edit every time

    monkeypatch.setattr(editgen, "generate_with_retry", fake_generate)

    edit, warnings = revise_until_valid(
        client=None, model="test-model", pitch=PITCH, manifest=MANIFEST,
        manifest_by_name=MANIFEST_BY_NAME, edit=BROKEN_EDIT, max_attempts=2,
    )

    assert len(calls) == 2
    assert edit["revision_attempts"] == 2
    assert warnings  # still broken -- the loop gave up, it didn't fabricate success


def test_revise_until_valid_rejects_a_revision_that_makes_things_worse(monkeypatch):
    """If the "fix" trades one problem for two, the loop must not accept
    it just because it's the newest attempt."""
    import src.editgen as editgen

    worse_edit = {
        "title": "Cold Open",
        "edit_list": [
            {"clip": "unknown_clip.mov", "in": 0.0, "out": 15.0},
            {"clip": "also_unknown.mov", "in": 0.0, "out": 2.0},
        ],
    }
    monkeypatch.setattr(editgen, "generate_with_retry", lambda client, model, prompt: json.dumps(worse_edit))

    edit, warnings = revise_until_valid(
        client=None, model="test-model", pitch=PITCH, manifest=MANIFEST,
        manifest_by_name=MANIFEST_BY_NAME, edit=BROKEN_EDIT, max_attempts=1,
    )

    # kept the original edit, not the "fix" that adds a second broken clip
    assert edit["edit_list"] == BROKEN_EDIT["edit_list"]
    assert len(warnings) == 2


def test_revise_until_valid_survives_a_malformed_json_response(monkeypatch):
    """A response that doesn't even parse is a failed attempt, not a
    crash -- the loop keeps the best edit it had going in."""
    import src.editgen as editgen

    monkeypatch.setattr(editgen, "generate_with_retry", lambda client, model, prompt: "not valid json {{")

    edit, warnings = revise_until_valid(
        client=None, model="test-model", pitch=PITCH, manifest=MANIFEST,
        manifest_by_name=MANIFEST_BY_NAME, edit=BROKEN_EDIT, max_attempts=1,
    )

    assert edit["edit_list"] == BROKEN_EDIT["edit_list"]
    assert warnings  # unchanged from the original validation
    assert edit["revision_attempts"] == 1


def test_revise_until_valid_skips_the_call_entirely_when_already_clean():
    """A clean edit shouldn't trigger a paid call at all -- zero warnings
    in means the while loop body never runs."""
    edit, warnings = revise_until_valid(
        client=None, model="test-model", pitch=PITCH, manifest=MANIFEST,
        manifest_by_name=MANIFEST_BY_NAME, edit=FIXED_EDIT,
    )
    assert warnings == []
    assert edit.get("revision_attempts", 0) == 0
