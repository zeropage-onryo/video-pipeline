# Task — Bring the Runway prompt layer up to Runway's current guides, and stop mismatching mode

Same shape as `task-veo-prompting-best-practices.md`, for Runway. Closes the same gap
`CLAUDE.md` flags for Runway specifically: `render_runway` in `src/shot.py` has
`verified=None` and its camera map has never been dated/checked against Runway's own docs.

## The actual bug, not just staleness

`concept_prompt.txt` describes RUNWAY to the LLM as "video-to-video restyle or extension" — but
`render_runway()` in `src/shot.py` renders a from-scratch text-to-video paragraph (subject +
action + setting + camera + look), which is the wrong prompt shape for Runway's actual
video-to-video edit model (Aleph). Aleph wants `[action verb] + [description of the outcome]`
against an existing clip, not a full scene re-description. The two code paths that touch Runway
prompts both need fixing:

1. **`shootgen`/`concept_prompt.txt`** (the LLM writes the paste-ready prompt directly) — the
   one-line tool description ("video-to-video restyle or extension") is too thin for the model to
   reliably produce an Aleph-shaped prompt. It needs the real structure inline.
2. **`shot.py` / `promptgen.py` / `shot_prompt.txt`** (structured `Shot` → `render_runway()`) —
   the renderer itself needs a restyle-mode path, not just the current generate-from-scratch one.

Full guide now at `.claude/skills/video-prompting/references/models/runway/prompting.md`
(fetched from Runway's Help Center, 2026-08-06) — covers Gen-4/Gen-4.5 (t2v/i2v), Gen-4
References (up to 3 images: character/environment/style), Act-Two (performance capture), and
Aleph (video-to-video restyle). Read it before writing code.

## What the guide actually says (the deltas to implement)

1. Runway is four sub-modes with different prompt shapes, not one. A shot needs a `mode` before
   it can be rendered correctly.
2. Aleph (restyle/extend an existing clip): `[action verb] + [outcome]`, one transformation at a
   time, positively state what to preserve if it's load-bearing. Not a scene re-description.
3. Gen-4 t2v/i2v: layer subject motion → camera → scene reaction → style, one layer at a time;
   positive phrasing only; generic subject references ("the subject", "the woman").
4. Gen-4 References: up to 3 images (character/environment/style) are the identity channel; the
   text prompt only carries what changes. Don't re-describe what a reference image already shows.
5. Keep duration/resolution/aspect/model name out of prompt text, same rule as every other
   platform in this repo.

## Contracts to preserve (don't break)

- Controlled vocabulary stays enforced for `Shot.camera`/`Shot.size`.
- Renderers stay pure (no model calls) and covered by fast tests.
- House style still applies automatically.

## 1. `src/shot.py`

### 1a. Add a `mode` field so a Shot can say which Runway sub-mode it wants

Runway needs to know which of its four products a shot is targeting. Add to `Shot`:

```python
    runway_mode: str = "generate"   # "generate" | "restyle" — see RUNWAY_MODES
```

```python
RUNWAY_MODES = ("generate", "restyle")
```

Validate in `__post_init__` alongside the existing camera/size checks.

### 1b. Split `render_runway` into a mode-aware dispatcher

- `render_runway(shot)` — keep as the existing t2v paragraph (Gen-4 generate mode); this is
  correct for shots with no existing footage to restyle.
- `render_runway_restyle(shot)` — new, Aleph-shaped: one line, `[action verb] + [outcome]`,
  built from `shot.action` and `shot.look`/`shot.notes` (whatever field carries "what changes").
  Do not include the full subject/setting/camera re-description Aleph doesn't need.
- Dispatch on `shot.runway_mode` inside `render_runway` (or have `PLATFORMS["runway"].render`
  pick the function) so existing call sites (`render_all`, `render(shot, "runway")`) don't need
  to change their call shape.
- Date the camera map: `RUNWAY_CAMERA` verified against the Gen-4 Video Prompting Guide,
  2026-08-06 — update `PLATFORMS["runway"]`'s `verified=` field to that date.

### 1c. Reference images are an external input, like Veo's aspect/duration

Add `runway_parameters(shot) -> dict` returning e.g. `{"reference_images": [...]}` placeholders
— actual image paths aren't a `Shot` concern yet (no image pipeline exists), but the shape
should exist so the studio UI has somewhere to attach reference images per shot once that lands.
Flag this as a follow-on if it's a real lift; don't block this task on it.

## 2. `prompts/concept_prompt.txt`

Replace the one-line Runway tool description in the tool list with mode-aware guidance, e.g.:

```
RUNWAY — two shapes depending on the shot:
  - restyle an existing/planned real shot (look, environment, lighting, wardrobe change) using
    "[action verb: change/remove/replace/re-light/re-style] + [outcome]", one transformation per
    shot, not a full scene re-description;
  - generate a brand-new AI shot from scratch (no source clip) as a short motion-first
    description: subject motion, then camera, then scene reaction, then style — positive
    phrasing only, no "no X" negatives.
  State which shape you're using isn't needed in the output — just write the prompt in the
  matching shape.
```

## 3. `prompts/shot_prompt.txt`

Same treatment as the Veo audio addition: if `promptgen.py`/`shootgen.py` know a shot is a
restyle of real footage (vs. a from-scratch AI shot), pass that through so the LLM writing the
loose-description-to-Shot conversion can set `runway_mode` correctly. If there's no existing
signal for "this AI shot restyles a real one" in the current concept schema, flag it — don't
invent new schema in this pass beyond what's specified above.

## 4. `.claude/skills/video-prompting/SKILL.md`

Add Runway to the Model Index (it's currently missing entirely, even though `shot.py` has had a
Runway renderer since before this task):

```
- Runway (Gen-4 / Gen-4.5 / Act-Two / Aleph): `references/models/runway/prompting.md`
```

## 5. Tests — `tests/test_shot_runway.py` (new)

Mirror `test_shot_veo.py`'s shape:

- `render_runway` (generate mode, default) still produces the existing t2v paragraph shape —
  don't regress current callers.
- `render_runway` with `runway_mode="restyle"` produces the `[action] + [outcome]` shape and
  does NOT include the full subject/setting/camera paragraph.
- Invalid `runway_mode` raises in `__post_init__`, same pattern as camera/size.
- `PLATFORMS["runway"].verified` is dated (not `None`).

## 6. Verify

```bash
venv/bin/python -m pytest tests/ -q      # green, incl. the new file
venv/bin/ruff check .                    # clean
```

Done when: Runway shots pick a prompt shape that matches what they're actually asking Runway to
do, the camera map is dated like Veo/Seedance/LTX/Wan, and `concept_prompt.txt` gives the LLM
enough to write an Aleph-shaped restyle prompt instead of a scene re-description mislabeled as
one. Tests green, ruff clean.

## Follow-ons (not this task)

- Gen-4 References (up to 3 images) and Act-Two (driving video + character ref) aren't
  represented in `Shot` at all yet — both need an actual image/video attachment path before
  they're usable, which is a bigger lift than this prompt-layer fix. Track separately.
- Same "verify against current docs, date the comment" pass for Kling, which is still
  `verified=None`.
