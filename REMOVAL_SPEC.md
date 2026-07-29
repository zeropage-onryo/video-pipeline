# Removal spec — beat sync and automatic color grade

Two features come out. Work through this top to bottom, committing each
numbered section separately.

## Warning before you start

The word **beats** means two different things in this repo. Read this
before deleting anything that mentions it.

1. **Visual beats** — `ingest.py`'s Gemini vision step produces
   `{"beats": [{"t": 3.2, "text": "..."}], "arc": "..."}` per clip. These
   are timestamped moments *inside a shot*. `edit_prompt.txt` refers to
   them: "Each clip in the library includes timestamped beats". They are
   central to how edits get cut and must stay.

2. **Musical beats** — `beat_sync.py`. These are what we are removing.

Do not touch anything in group 1. If a change would alter `manifest.json`'s
shape or `edit_prompt.txt`'s instructions about clip beats, it is wrong.

---

## 1. Delete `src/beat_sync.py`

`editgen.py` is the only importer. A cleaned `editgen.py` is supplied
alongside this file — drop it in, then delete `beat_sync.py`.

What was removed from `editgen.py`:

- the `from beat_sync import ...` line
- `--music`, `--bpm`, `--bpm-offset` arguments
- the mutual-exclusion guard for `--music` / `--bpm`
- the beat-detection block that built `beat_times`
- the `snap_edit_to_beats(...)` call in the per-edit loop
- the `" (beat-synced)"` suffix in the summary print

`validate_edit` is untouched. It was already the thing enforcing runtime
and in/out bounds, and it does that independently of snapping.

Verify: `grep -rn "beat_sync\|snap_edit\|synthetic_beats\|detect_beats" src/`
returns nothing.

## 2. Delete the whole Resolve integration

Three files, in this order:

```
src/apply_grade.py      standalone, nothing imports it
src/build_timeline.py   standalone, nothing imports it
src/resolve_edit.py     imported ONLY by the two above
```

`resolve_edit.py` has no other importers. Once the first two go it is dead
code, so it goes with them. Verify before deleting:

```bash
grep -rn "resolve_edit\|build_timeline\|apply_grade\|DaVinciResolveScript" src/
```

Should return nothing afterwards. Surviving modules are `ingest.py`,
`pitch.py`, `editgen.py`, `gemini_utils.py`, plus the new spine.

Keep `grades/zero_page_batman.drx`. It is a Resolve asset you still apply
by hand — only the automation goes.

No `requirements.txt` change: `DaVinciResolveScript` was loaded from the
Resolve app bundle at runtime, never installed.

### What the pipeline becomes

```
footage/ -> ingest.py -> manifest.json -> pitch.py -> pitches.json
                                              |
                                        editgen.py (human picks numbers)
                                              |
                                        concepts.json
```

It ends at `concepts.json` — a validated cut list plus generative slots,
which you execute yourself in Resolve. Nothing writes to Resolve any more,
and Resolve no longer needs to be running for any command.

`validate_edit` still matters and stays. It is what stops the model
proposing cuts outside a clip's real duration, and that check is more
important now, not less, because nothing downstream will catch a bad
in-point for you.

### One thing to add back

`concepts.json` was machine-readable because a machine consumed it. Now you
read it. Add a `--print` flag to `editgen.py` that renders the cut list as
plain text — clip name, in, out, duration, running total — so you can work
from it beside Resolve without parsing JSON by eye. Small, and it is the
difference between the tool being usable and being technically correct.

## 3. Drop `librosa` from `requirements.txt`

It existed solely for `detect_beats`. Removing it also drops numba,
scipy, soundfile and audioread from the install — a noticeably faster
and smaller environment.

Then try removing the `numpy<2` pin and reinstall. That pin may have been
there for librosa's numba dependency, but Whisper also pulls in numba, so
it may still be required. Run `ingest.py` on one clip afterwards. If
transcription breaks, put the pin back and note why in the file:

```
numpy<2   # whisper's numba dependency; unpinning breaks transcription
```

A one-line comment explaining a pin is worth more than the pin alone.

## 4. Update `CLAUDE.md`

- Commands block: delete the `build_timeline.py` and `apply_grade.py`
  commands. Change the `editgen.py` line to drop `[--music ...] [--bpm ...]`.
- Overview: it currently claims the tool "automatically produces rough-cut
  timelines inside DaVinci Resolve". That is no longer what it does.
  Rewrite it — this is now a pre-production tool that produces validated
  cut lists and generative prompts from real footage.
- Architecture: replace the stage diagram with the four-stage version in
  section 2. Delete the `build_timeline.py`, `resolve_edit.py` and
  `apply_grade.py` bullets.
- Requirements paragraph: delete the entire DaVinci Resolve Studio
  requirement. No command needs Resolve running any more. `GEMINI_API_KEY`
  is still required.
- Key conventions: the "Manifest is the interface, filenames are IDs"
  convention loses its Resolve-matching clause but otherwise holds. The
  other four are untouched.

## 5. Update `README.md`

This is a reframe, not a bullet deletion. The project is no longer "an AI
video editing pipeline". It is an AI pre-production tool: it decides what
to cut and writes the prompts for the clips you do not have.

That narrowing is a gain, not a loss. "AI video editing pipeline" is a
crowded and vague claim. "Analytics-grounded ideation, validated cut lists,
and generative prompts for a working brand" is specific and defensible.

- Overview: rewrite. Delete "automatically produces a rough cut",
  "assembles a timeline", "syncs cuts to the music's beat", "applies color
  grade presets".
- Architecture: three stages now — ingest, concept generation, edit spec.
- How It Works: ends at the cut list, which you execute in Resolve.
- Tech Stack: delete the DaVinci Resolve scripting API line, the `.drx`
  grade preset line, and the FFmpeg fallback-rendering line. FFmpeg stays,
  but for frame extraction in ingest, so describe it that way.
- Roadmap: "improve rough-cut coherence" is no longer the goal. Replace
  with what you are actually building — performance feedback, generative
  slots, evaluation.

## 6. Add three entries to the Decisions Log

Removals with a stated reason read as judgment. Removals with no trace read
as abandonment. Your log is dated and append-only, which is the right
pattern — do not edit the old Resolve entry, supersede it.

Drafts below. Edit them: the reasons should be yours, and a plain "it never
earned its place" beats my guess at your reasoning.

> **Removed beat-synced cutting.** Cut transitions were being snapped to
> detected or synthetic musical beats. Removed because the timing of a cut
> is a creative decision and snapping overrode it mechanically — a cut
> landing on a beat is not the same as a cut landing where the shot wants
> to end. Also removed `librosa` and its dependency chain. Cut points now
> come only from the clip's own described beats, which is what the edit
> prompt was already reasoning about.

> **Removed automatic color grading.** `apply_grade.py` applied a saved
> `.drx` to every clip on named timelines. Removed because grading is
> shot-by-shot work and a blanket application produced something that
> always needed redoing by hand. The grade preset stays in `grades/` and is
> applied manually in Resolve.

> **Superseded 2026-07-08 "Rough cuts target Resolve Studio's scripting
> API". Removed the Resolve integration entirely.** `build_timeline.py`,
> `apply_grade.py` and `resolve_edit.py` are gone. The pipeline now ends at
> a validated cut list in `concepts.json`, which is executed by hand.
> Reason: assembling the timeline was the least valuable step and the most
> brittle — it required Resolve running with a project open, matched clips
> by filename across two systems, and produced an assembly that was always
> re-cut anyway. The judgment worth automating is which shots and which
> moments, not the mechanical assembly. Cost: no more one-command rough
> cut. Accepted, because the rough cut was never the output that got used.

## 7. Prompt files — leave alone

`prompts/settings.txt` keeps its GRADE line. It tells the model what the
finished look will be, which shapes the per-shot `grade_notes` it writes.
Those notes are guidance for you in Resolve, not automation.

`prompts/edit_prompt.txt` keeps `sound_note` and its references to clip
beats. Neither depends on what was removed.

## Verification

```bash
grep -rn "beat_sync\|apply_grade\|build_timeline\|resolve_edit\|librosa\|DaVinciResolveScript" \
     src/ *.md requirements.txt
```

Should return nothing. Then:

```bash
venv/bin/python src/pitch.py
venv/bin/python src/editgen.py 2 5 9
```

Both should run clean, and `concepts.json` should contain edits with
`grade_notes` and `sound_note` intact.
