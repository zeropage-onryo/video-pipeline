"""Tests for editgen.py's plain-text cut-list formatter (the --print flag)."""

from src.editgen import format_edit_as_text


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
