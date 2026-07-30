"""
Tests for promptgen.py.

The split that matters: the LLM's only job is producing a well-formed
Shot from a loose description (parse_shot_response). Rendering the
three tool prompts is shot.py's pure, already-tested render_all -- no
model call goes anywhere near it.
"""

import json

import pytest

from src import db, promptgen
from src import generative as gen

VALID_RESPONSE = json.dumps({
    "subject": "a gloved hand",
    "action": "closes a steel drawer",
    "camera": "push_in",
    "size": "close",
    "setting": "empty workshop at night",
    "lighting": "single overhead practical",
    "duration_s": 4.0,
})


# ---------- parse_shot_response ----------

def test_parse_shot_response_builds_a_valid_shot():
    shot = promptgen.parse_shot_response(VALID_RESPONSE)
    assert shot.subject == "a gloved hand"
    assert shot.camera == "push_in"
    assert shot.size == "close"


def test_parse_shot_response_rejects_free_text_camera():
    bad = json.dumps({
        "subject": "a gloved hand", "action": "closes a drawer",
        "camera": "swooshes dramatically", "size": "close",
    })
    with pytest.raises(ValueError, match="camera must be one of"):
        promptgen.parse_shot_response(bad)


def test_parse_shot_response_strips_markdown_fences():
    fenced = f"```json\n{VALID_RESPONSE}\n```"
    shot = promptgen.parse_shot_response(fenced)
    assert shot.subject == "a gloved hand"


def test_parse_shot_response_ignores_unknown_keys():
    extra = json.dumps({
        "subject": "a gloved hand", "action": "closes a drawer",
        "camera": "static", "size": "medium",
        "tool_preference": "runway",  # not a Shot field
        "confidence": 0.9,            # not a Shot field
    })
    shot = promptgen.parse_shot_response(extra)
    assert shot.subject == "a gloved hand"


# ---------- format_examples ----------

def test_format_examples_empty_list_is_blank():
    assert promptgen.format_examples([]) == ""


def test_format_examples_mentions_tool_and_prompt():
    entries = [{"tool": "kling", "attempts": 2, "prompt": "a hand on a wrench",
                "subject": "a hand", "camera": "static", "size": "medium"}]
    out = promptgen.format_examples(entries)
    assert "kling" in out
    assert "a hand on a wrench" in out


# ---------- generate_prompts_for_slot (network mocked) ----------

@pytest.fixture
def tmp_db(tmp_path):
    path = tmp_path / "test.db"
    db.init_db(path)
    gen.init(path)
    return path


def test_generate_prompts_for_slot_returns_three_prompts_and_persists(tmp_db, monkeypatch):
    monkeypatch.setattr(promptgen, "generate_with_retry",
                        lambda *a, **kw: VALID_RESPONSE)

    result = promptgen.generate_prompts_for_slot(
        "a gloved hand closes a steel drawer",
        client=None, db_path=tmp_db,
    )

    assert set(result["prompts"]) == {"runway", "veo", "kling"}
    assert all(result["prompts"][tool].strip() for tool in result["prompts"])

    stored = gen.get_shot(result["shot_id"], tmp_db)
    assert stored is not None
    assert stored["subject"] == "a gloved hand"


def test_generate_prompts_for_slot_links_idea_and_slot(tmp_db, monkeypatch):
    monkeypatch.setattr(promptgen, "generate_with_retry",
                        lambda *a, **kw: VALID_RESPONSE)
    run_id = db.save_pitch_run(
        [{"number": 1, "title": "T", "logline": "L", "story_note": "N"}],
        path=tmp_db,
    )
    with db.connect(tmp_db) as conn:
        idea_id = conn.execute(
            "SELECT id FROM ideas WHERE run_id = ?", (run_id,)
        ).fetchone()[0]

    result = promptgen.generate_prompts_for_slot(
        "a gloved hand closes a steel drawer",
        idea_id=idea_id, slot_index=2, client=None, db_path=tmp_db,
    )

    stored = gen.get_shot(result["shot_id"], tmp_db)
    assert stored["idea_id"] == idea_id
    assert stored["slot_index"] == 2
