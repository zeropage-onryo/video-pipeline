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

    # one prompt per registered platform — the registry is the source,
    # so a platform added there shows up here with no promptgen edit
    from src.shot import PLATFORMS
    assert set(result["prompts"]) == set(PLATFORMS)
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

# ---------- refine_prompt (network mocked) ----------

GOOD_SHOT_PROMPT = ("Extreme macro close-up of a brass door handle slowly "
                    "turning in a dark hallway at night, one warm practical "
                    "light spilling under the door, heavy film grain, "
                    "crushed shadows, noir mood, static camera")


def test_refine_prompt_passes_through_with_no_references():
    # no references retrieved -> nothing to refine against, never bill a call
    out = promptgen.refine_prompt(GOOD_SHOT_PROMPT, "KLING", gemini_client=None, references="")
    assert out == GOOD_SHOT_PROMPT


def test_refine_prompt_returns_the_model_rewrite(monkeypatch):
    monkeypatch.setattr(promptgen, "generate_with_retry",
                        lambda *a, **kw: "  Refined: " + GOOD_SHOT_PROMPT + ", start mid-motion  ")
    out = promptgen.refine_prompt(
        GOOD_SHOT_PROMPT, "KLING", gemini_client=object(),
        references="1. [cheat-codes.md] start mid-motion, avoid static bookending",
    )
    assert out == "Refined: " + GOOD_SHOT_PROMPT + ", start mid-motion"


def test_refine_prompt_falls_back_when_the_call_raises(monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("network is down")
    monkeypatch.setattr(promptgen, "generate_with_retry", boom)
    out = promptgen.refine_prompt(
        GOOD_SHOT_PROMPT, "KLING", gemini_client=object(), references="some technique notes",
    )
    assert out == GOOD_SHOT_PROMPT


def test_refine_prompt_falls_back_on_empty_rewrite(monkeypatch):
    monkeypatch.setattr(promptgen, "generate_with_retry", lambda *a, **kw: "   ")
    out = promptgen.refine_prompt(
        GOOD_SHOT_PROMPT, "KLING", gemini_client=object(), references="some technique notes",
    )
    assert out == GOOD_SHOT_PROMPT


def test_refine_prompt_falls_back_on_a_much_shorter_rewrite(monkeypatch):
    monkeypatch.setattr(promptgen, "generate_with_retry", lambda *a, **kw: "a door")
    out = promptgen.refine_prompt(
        GOOD_SHOT_PROMPT, "KLING", gemini_client=object(), references="some technique notes",
    )
    assert out == GOOD_SHOT_PROMPT


def test_refine_prompt_falls_back_on_a_leftover_placeholder(monkeypatch):
    monkeypatch.setattr(
        promptgen, "generate_with_retry",
        lambda *a, **kw: GOOD_SHOT_PROMPT + " {still missing detail here}",
    )
    out = promptgen.refine_prompt(
        GOOD_SHOT_PROMPT, "KLING", gemini_client=object(), references="some technique notes",
    )
    assert out == GOOD_SHOT_PROMPT


def test_build_refine_prompt_injects_tool_prompt_and_references():
    out = promptgen.build_refine_prompt(
        GOOD_SHOT_PROMPT, "KLING", "1. [cheat-codes.md] start mid-motion",
    )
    assert "KLING" in out
    assert GOOD_SHOT_PROMPT in out
    assert "start mid-motion" in out
    assert "{tool}" not in out and "{raw_prompt}" not in out and "{references}" not in out
