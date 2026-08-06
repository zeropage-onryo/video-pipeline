# Task — Bring the Veo renderer up to Veo 3.1 best practices

Update the AI-shot prompt layer (`src/shot.py` + `prompts/shot_prompt.txt`) to follow the current
Veo 3.1 guidance now installed at
`.claude/skills/video-prompting/references/models/veo3/prompting.md` (Google Cloud's
"Ultimate prompting guide for Veo 3.1"). This closes the exact gap `CLAUDE.md` flags:
*"the VEO/KLING/RUNWAY camera maps and AI-slot phrasing are general patterns, not current docs —
verify before trusting, and date the comment above each map."*

Scope is **Veo only** for now (it's the primary slot — it runs on the existing Gemini key). Kling
and Runway can get the same treatment later from their own guides.

## What the guide actually says (the deltas to implement)

1. **Five-part formula:** `[Cinematography] + [Subject] + [Action] + [Context] + [Style & ambiance]`.
   Cinematography leads.
2. **Keep aspect / duration / resolution / model name OUT of the prompt text** — pass them as
   external parameters. (Current `render_veo` wrongly emits an `Aspect: 9:16` line.)
3. **Direct the soundstage** — Veo 3.1 generates audio. Give explicit audio: dialogue in quotes,
   `SFX:` calls, ambient soundscape. If no dialogue is wanted, say so. (Current renderer has no audio
   at all; house style is no-talking noir, so default to ambient/SFX, no dialogue.)
4. **Phrase exclusions as a described scene**, not an abstract "no X" list ("a clean frame with no
   text" over "no text overlays").
5. **Explicit standard cinematography terms** (dolly / tracking / crane / pan / POV; shallow depth of
   field, macro, etc.).

## Contracts to preserve (don't break)

- Controlled vocabulary stays enforced — free-text `camera`/`size` still rejected in `__post_init__`.
- Renderers stay **pure** (no model calls) and covered by fast tests.
- House style is still applied automatically; the prompt template still says "do not restate it".

---

## 1. `src/shot.py`

### 1a. Add an optional `audio` field to `Shot`

In the dataclass, after `notes: str = ""`:

```python
    audio: str = ""      # ambient/SFX direction for models that generate sound (Veo). No dialogue by house style.
```

Add it to `as_dict()` (right after `"notes": self.notes,`):

```python
            "audio": self.audio,
```

No new validation — it's an optional free-text audio direction, not controlled vocab.

### 1b. Replace the Veo camera map + add a Veo negative, dated per CLAUDE.md

Replace the existing `VEO_CAMERA = {...}` block with:

```python
# Veo 3.1 cinematography vocabulary — the standard camera terms Google Cloud's
# "Ultimate prompting guide for Veo 3.1" recommends (dolly / tracking / crane /
# pan / POV). Verify against that guide before changing.
# Updated 2026-08-04 from .claude/skills/video-prompting/references/models/veo3/prompting.md
VEO_CAMERA = {
    "static": "locked-off static shot",
    "pan_left": "slow pan left",
    "pan_right": "slow pan right",
    "tilt_up": "tilt up",
    "tilt_down": "tilt down",
    "push_in": "slow dolly in, pushing toward the subject",
    "pull_out": "slow dolly out, pulling back from the subject",
    "tracking": "tracking shot moving alongside the subject",
    "handheld": "subtle handheld",
    "crane_up": "crane shot rising",
    "crane_down": "crane shot descending",
    "orbit": "arcing orbit around the subject",
}

# Veo's guide says to phrase exclusions as a described scene rather than an
# abstract "no X" list, so the house negatives are rewritten as a positive
# frame description for this model only.
VEO_NEGATIVE = (
    "a clean, unbranded frame with no on-screen text, logos, or lens flares; "
    "the subject faces away from or past the lens and never addresses the camera; "
    "colour stays muted and filmic, never saturated or upbeat"
)
```

### 1c. Rewrite `render_veo` to the five-part formula (and stop leaking aspect)

Replace the existing `render_veo`:

```python
def render_veo(shot: Shot) -> str:
    """
    Veo 3.1's five-part formula:
    [Cinematography] + [Subject] + [Action] + [Context] + [Style & ambiance].
    Aspect/duration are deliberately NOT in the prompt text — Veo's guide says
    keep those as external parameters (see veo_parameters()). Veo generates
    audio, so it's directed explicitly and defaults to no dialogue to match the
    house style.
    """
    cinematography = _phrase(VEO_CAMERA[shot.camera], f"{_readable_size(shot.size)} shot")
    context = _phrase(shot.setting, shot.lighting)
    lines = [
        f"Cinematography: {cinematography}",
        f"Subject: {shot.subject}",
        f"Action: {shot.action}",
    ]
    if context:
        lines.append(f"Context: {context}")
    lines.append(f"Style & ambiance: {shot.look}")
    lines.append(f"Audio: {shot.audio.strip() or 'ambient sound only, no dialogue'}")
    lines.append(f"Avoid: {VEO_NEGATIVE}")
    return "\n".join(lines)


def veo_parameters(shot: Shot) -> dict:
    """The generation params Veo's guide says to keep OUT of the prompt text —
    supply them alongside the prompt, not inside it."""
    return {"aspect_ratio": shot.aspect, "duration_s": shot.duration_s}
```

*(Leave `render_runway` and `render_kling` as-is for this pass. `negative_prompt()` still returns
`shot.negative` for Kling/Runway's separate negative field; Veo now folds `VEO_NEGATIVE` inline.)*

---

## 2. `prompts/shot_prompt.txt`

Two changes so the model can fill the new audio field and leans on explicit cinematography.

Add, just above the "Turn the loose description…" line:

```
AUDIO: this shot may be generated by a model that produces sound. If useful,
add an "audio" line describing ambient sound or specific SFX (e.g. "SFX: the
metallic clink of a wrench"). Never write dialogue — nobody speaks on camera in
this house style. Be explicit about camera and framing.
```

Update the output JSON shape to include the optional `audio` field:

```
{"subject": <string>, "action": <string>, "camera": <one camera value above>,
"size": <one size value above>, "setting": <string, optional>, "lighting":
<string, optional>, "audio": <string, optional -- ambient/SFX only, never
dialogue>, "duration_s": <number, typically 3-6>}
```

*(If `promptgen.py` constructs the `Shot` from parsed JSON with explicit keyword args rather than
`**data`, add `audio=data.get("audio", "")` there too. If it already spreads the dict, the new
optional field flows through — but drop any unknown-key filtering that would strip it.)*

---

## 3. Tests — `tests/test_shot_veo.py` (new)

Pure, fast, no model calls.

```python
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
```

**Also:** grep `tests/` for any existing `render_veo` assertion that expects the old
`Aspect: 9:16` line and update it — that format is intentionally gone now.

---

## 4. Verify

```bash
venv/bin/python -m pytest tests/ -q      # green, incl. the new file
venv/bin/ruff check .                    # clean

# eyeball a real render:
venv/bin/python -c "from src.shot import Shot, render_veo, veo_parameters; \
s=Shot(subject='a gloved hand', action='pushes between two engine fins', camera='push_in', size='extreme_close', setting='a dim garage', lighting='one amber practical', audio='SFX: low mechanical hum'); \
print(render_veo(s)); print(); print('PARAMS', veo_parameters(s))"
```

Done when: the Veo prompt reads as the five-part formula, carries an explicit `Audio:` line, never
contains aspect/duration/model-name, and `veo_parameters()` carries those externally — tests green,
ruff clean.

---

## Follow-ons (not this task)
- Same pass for Kling / Runway once you add their guides under
  `.claude/skills/video-prompting/references/models/`.
- Have `promptgen.py` actually *consult* the model guide (read the relevant
  `references/models/<tool>/prompting.md`) when drafting, so the guidance is used at generation time,
  not just encoded in the renderer.
