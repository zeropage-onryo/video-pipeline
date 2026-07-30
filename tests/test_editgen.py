"""Tests for editgen.py's plain-text cut-list formatter (the --print flag)
and validate_edit's handling of generative clip slots."""

from src.editgen import format_edit_as_text, merge_warnings, validate_edit

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
