"""
render_veo against Veo 3.1's actual prompting guide (Google Cloud's
"Ultimate prompting guide for Veo 3.1", vendored at
.claude/skills/video-prompting/references/models/veo3/prompting.md):
the five-part [Cinematography] + [Subject] + [Action] + [Context] +
[Style & ambiance] formula, an explicit Audio line, and no
aspect/duration/model-name leaking into the prompt text -- those are
external generation parameters per the guide, supplied by
veo_parameters() instead.
"""

from src.shot import Shot, render_veo, veo_parameters


def _shot(**kw):
    base = dict(subject="a gloved hand", action="wipes an engine fin",
                camera="push_in", size="close", setting="a dim garage",
                lighting="one warm practical")
    base.update(kw)
    return Shot(**base)


def test_render_veo_uses_five_part_labels():
    out = render_veo(_shot())
    for label in ("Cinematography:", "Subject:", "Action:", "Style & ambiance:", "Audio:"):
        assert label in out


def test_render_veo_never_leaks_aspect_or_settings():
    out = render_veo(_shot()).lower()
    for banned in ("aspect", "9:16", "duration", "veo"):
        assert banned not in out


def test_render_veo_defaults_to_no_dialogue_audio():
    assert "no dialogue" in render_veo(_shot()).lower()


def test_render_veo_uses_provided_audio():
    out = render_veo(_shot(audio="SFX: a wrench clinks on concrete"))
    assert "SFX: a wrench clinks on concrete" in out


def test_veo_parameters_carries_aspect_and_duration_externally():
    params = veo_parameters(_shot(duration_s=5.0))
    assert params == {"aspect_ratio": "9:16", "duration_s": 5.0}
