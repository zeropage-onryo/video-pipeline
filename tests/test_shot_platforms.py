"""
The platform registry: tools are data, not hardcoded tuples. Adding a
generation platform means one PLATFORMS entry — a camera map and a
renderer — and everything downstream (render_all, shootgen's tool
validation, promptgen) picks it up. These tests pin that contract and
the per-platform prompt dialects for the three added alongside
Veo/Kling/Runway: Seedance 2.0, LTX-2, Wan 2.2.

Each renderer is a pure Shot -> str function; nothing here spends money.
"""
import pytest

from src import shot as shot_mod
from src.shot import (
    PLATFORMS,
    Shot,
    render,
    render_all,
)

SHOT = Shot(
    subject="a gloved hand",
    action="closes a steel drawer",
    camera="push_in",
    size="close",
    setting="a cramped garage at night",
    lighting="one warm practical",
    audio="the metallic clunk of the drawer seating",
)


# ---------- the registry is the single source ----------

def test_registry_carries_all_eight_platforms():
    assert set(PLATFORMS) == {"runway", "veo", "kling", "seedance", "ltx", "wan",
                              "openart", "higgsfield"}


def test_tools_tuple_derives_from_the_registry():
    """shootgen validates AI-shot tools against this — a platform added
    to the registry must be legal everywhere without a second edit."""
    assert set(shot_mod.TOOLS) == set(PLATFORMS)


def test_every_platform_entry_has_a_renderer_and_camera_map():
    for name, platform in PLATFORMS.items():
        assert callable(platform.render), name
        for cam in shot_mod.CAMERA:
            assert cam in platform.camera, f"{name} missing camera {cam!r}"


def test_render_all_covers_every_platform():
    prompts = render_all(SHOT)
    assert set(prompts) == set(PLATFORMS)
    assert all(isinstance(p, str) and p for p in prompts.values())


def test_render_rejects_an_unknown_tool():
    with pytest.raises(ValueError, match="tool must be one of"):
        render(SHOT, "sora")


# ---------- seedance: labeled sections, audio included ----------

def test_seedance_uses_labeled_sections():
    prompt = render(SHOT, "seedance")
    for label in ("Setting:", "Action:", "Camera:", "Style:", "Audio:"):
        assert label in prompt, f"missing {label}"


def test_seedance_carries_the_audio_direction():
    assert "metallic clunk" in render(SHOT, "seedance")


# ---------- ltx: flowing paragraph, style first, params out ----------

def test_ltx_starts_with_the_style_cue():
    """LTX-2's guide: always put style first as `Style: <style>, ...`."""
    assert render(SHOT, "ltx").startswith("Style:")


def test_ltx_is_one_flowing_paragraph():
    assert "\n" not in render(SHOT, "ltx")


def test_ltx_keeps_generation_params_out_of_the_text():
    """Duration/aspect are generation controls, not prompt text."""
    prompt = render(SHOT, "ltx")
    assert "9:16" not in prompt
    assert "4.0" not in prompt and "seconds" not in prompt.lower()


def test_ltx_avoids_scene_opens_phrasing():
    assert "The scene opens" not in render(SHOT, "ltx")
    assert "The video starts" not in render(SHOT, "ltx")


# ---------- wan: subject + scene + motion, explicit camera verbs ----------

def test_wan_leads_with_the_subject():
    assert render(SHOT, "wan").startswith("a gloved hand")


def test_wan_uses_explicit_camera_verbs():
    """Wan's guide wants pan/tilt/dolly/orbit/crane named plainly."""
    assert "dolly" in PLATFORMS["wan"].camera["push_in"]
    assert "orbit" in PLATFORMS["wan"].camera["orbit"]


def test_wan_keeps_model_and_params_out_of_the_text():
    prompt = render(SHOT, "wan")
    assert "Wan" not in prompt
    assert "9:16" not in prompt


# ---------- openart: Director reads language, not shorthand ----------

def test_openart_is_flowing_sentences_not_shorthand():
    """Director is conversational (Story → Scenes → Shots, directed in
    plain language) -- the render must read as prose a director would
    hear, not a comma list of camera codes."""
    prompt = render(SHOT, "openart")
    assert "the camera slowly pushes in" in prompt
    assert "push_in" not in prompt
    assert prompt.count(".") >= 3          # actual sentences, not one clause


def test_openart_camera_map_is_full_prose_clauses():
    for phrase in shot_mod.CAMERA_PROSE.values():
        assert phrase.startswith("the camera"), phrase


def test_openart_keeps_generation_params_out_of_the_text():
    prompt = render(SHOT, "openart")
    assert "9:16" not in prompt
    assert "4.0" not in prompt


def test_openart_carries_story_notes_when_present():
    noted = Shot(subject="a gloved hand", action="closes a steel drawer",
                 notes="this beat is the reveal — the drawer is already empty")
    assert "already empty" in render(noted, "openart")


# ---------- reference_image: the real capture behind an AI shot ----------

def test_reference_image_defaults_to_none_attached():
    assert SHOT.reference_image == ""
    assert SHOT.as_dict()["reference_image"] == ""


def test_openart_parameters_attach_the_capture_not_the_prompt():
    """The reference travels beside the description, never inside it --
    same contract as veo_parameters()."""
    anchored = Shot(subject="a gloved hand", action="closes a steel drawer",
                    reference_image="https://cdn.example/ref.jpg")
    assert shot_mod.openart_parameters(anchored) == {
        "reference_images": ["https://cdn.example/ref.jpg"]}
    assert shot_mod.openart_parameters(SHOT) == {"reference_images": []}
    assert "cdn.example" not in render(anchored, "openart")


def test_runway_parameters_now_carry_the_capture_too():
    """runway_parameters() was a placeholder shape waiting for exactly
    this field -- with a reference attached it stops being empty."""
    anchored = Shot(subject="a gloved hand", action="closes a steel drawer",
                    reference_image="https://cdn.example/ref.jpg")
    assert shot_mod.runway_parameters(anchored) == {
        "reference_images": ["https://cdn.example/ref.jpg"]}


# ---------- existing platforms keep their dialects ----------

def test_veo_still_renders_the_five_part_formula():
    prompt = render(SHOT, "veo")
    assert prompt.startswith("Cinematography:")
    assert "Audio:" in prompt


def test_kling_and_runway_still_render():
    assert "close shot" in render(SHOT, "kling")
    assert "close shot" in render(SHOT, "runway")
