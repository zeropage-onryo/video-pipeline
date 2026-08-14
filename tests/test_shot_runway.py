"""
render_runway's two modes, per task-runway-prompting-best-practices.md:
"generate" (Gen-4, from scratch -- unchanged existing t2v paragraph) and
"restyle" (Aleph, video-to-video) which wants a completely different,
much narrower [action verb] + [outcome] shape and must NOT re-describe
the subject/setting/camera the way generate mode does.
"""
import pytest

from src.shot import PLATFORMS, RUNWAY_MODES, Shot, render_runway, render_runway_restyle, runway_parameters


def _shot(**kw):
    base = dict(subject="a gloved hand", action="wipes an engine fin",
                camera="push_in", size="close", setting="a dim garage",
                lighting="one warm practical")
    base.update(kw)
    return Shot(**base)


def test_render_runway_generate_mode_is_unchanged():
    """Default mode still produces the existing t2v paragraph shape --
    don't regress current callers."""
    out = render_runway(_shot())
    assert "close shot of a gloved hand" in out
    assert "a dim garage" in out


def test_render_runway_restyle_mode_dispatches_to_the_aleph_shape():
    out = render_runway(_shot(runway_mode="restyle"))
    assert out == render_runway_restyle(_shot(runway_mode="restyle"))


def test_render_runway_restyle_does_not_redescribe_the_scene():
    """Aleph already has the source clip -- subject/setting/camera
    re-description is noise, not signal."""
    shot = _shot(
        action="relight with high-contrast noir shadows and heavy grain",
        runway_mode="restyle",
    )
    out = render_runway_restyle(shot)
    assert "a gloved hand" not in out
    assert "a dim garage" not in out
    assert "close shot" not in out.lower()


def test_render_runway_restyle_states_the_transformation():
    shot = _shot(action="relight with noir shadows and heavy grain", runway_mode="restyle")
    out = render_runway_restyle(shot)
    assert "relight with noir shadows and heavy grain" in out


def test_render_runway_restyle_preserves_notes_positively():
    shot = _shot(
        action="turn the grease into liquid gold droplets",
        notes="the hand count and motorcycle geometry unchanged",
        runway_mode="restyle",
    )
    out = render_runway_restyle(shot)
    assert "preserving the hand count and motorcycle geometry unchanged" in out


def test_invalid_runway_mode_raises():
    with pytest.raises(ValueError, match="runway_mode must be one of"):
        _shot(runway_mode="video-to-video")


def test_runway_mode_default_is_generate():
    assert _shot().runway_mode == "generate"


def test_runway_modes_tuple_has_generate_and_restyle():
    assert RUNWAY_MODES == ("generate", "restyle")


def test_runway_parameters_shape():
    assert runway_parameters(_shot()) == {"reference_images": []}


def test_platform_registry_still_points_at_render_runway():
    """render_all/render(shot, 'runway') don't need call-shape changes --
    the mode dispatch lives inside render_runway itself."""
    assert PLATFORMS["runway"].render is render_runway
