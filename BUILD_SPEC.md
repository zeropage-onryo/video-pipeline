# Build spec — Zero Page Films pipeline

Read this whole file before writing code. One session per section.

## What already exists

```
ingest.py    footage/ -> manifest.json
             ffprobe metadata, Whisper transcript,
             Gemini vision {beats:[{t,text}], arc} per clip
pitch.py     manifest.json -> pitches.json (10 stories)
editgen.py   selected pitch numbers -> concepts.json (cut lists)
gemini_utils.py retry + fallback models, strip_fences

Removed by REMOVAL_SPEC.md: beat_sync.py, build_timeline.py,
apply_grade.py, resolve_edit.py.
```

No tests, no CI, no linter. That is the biggest gap, not a missing feature.

## What this adds

The pipeline currently ends when a timeline is built. Nothing records what
got posted or how it did, so nothing informs the next run. This spec closes
that loop.

`src/db.py` is written and tested — 21 tests, all passing. Read it before
touching anything else. Do not redesign the schema.

## The main idea

`pitch.py` generates 10. A human picks 3. Those 3 get cut.

That choice is a label, and it is currently discarded at the command line.
Ten pitches from one manifest under one prompt, three marked good, seven
not, is a preference set. It is the only ground truth here that does not
require waiting weeks for view counts.

Recording it costs one column and unlocks:

- Feeding past picks into the prompt as examples of what gets chosen
- Measuring whether a prompt change raises the pick rate
- A real eval set that exists before any video is posted

Everything else in this spec is secondary to capturing that.

## Deletions

**Delete outright**

- `resolve_edit.py`'s `main()` and its `load_manifest` / `match_manifest_to_clips`
  helpers. That entrypoint is a dead TODO that duplicates `build_timeline.py`.
  Keep `get_resolve`, `base_name`, `build_clip_index` — both other modules
  import them.

**Fix, do not delete**

- `apply_grade.py`'s `DEFAULT_TIMELINE_NAMES` is hardcoded to one shoot's
  timelines. Make the argument required, or default to the titles in
  `concepts.json`.

**Removed separately** — see `REMOVAL_SPEC.md`: `beat_sync.py` and
`apply_grade.py`. `editgen.py` imports `beat_sync`, so it needs editing
rather than a straight delete; a cleaned copy is supplied.

**Decision made — the Resolve integration is removed.** `build_timeline.py`,
`apply_grade.py` and `resolve_edit.py` all go; see `REMOVAL_SPEC.md`
section 2. The pipeline now ends at a validated cut list you execute by
hand. An earlier draft of this spec recommended keeping it — that
recommendation is withdrawn.

## Sessions

### Session 1 — foundation

1. `pyproject.toml`, package installed editable, remove the `sys.path`
   hack from `tests/test_db.py`.
2. Add `pytest`, `fastapi`, `uvicorn`, `jinja2` to `requirements.txt`.
3. `.gitignore`: `.env`, `data/*.db`, `venv/`, `manifest.json`,
   `pitches.json`, `concepts.json`.
4. `python -m src.db` creates the tables.
5. If `pitches.json` exists, `db.import_pitches_file()` it so the current
   run is not lost.

Gate: 21 tests pass. `git log` shows discrete commits.

### Session 2 — capture the label

The whole point. Two small edits.

**`pitch.py`** — after writing `pitches.json`, call `db.save_pitch_run()`
with the pitches, `MODEL`, `len(manifest)`, and the raw text of
`brief.txt`, `settings.txt` and `pitch_prompt.txt`. Print the run id.

**`editgen.py`** — it already takes pitch numbers on the command line.
After a successful run, call `db.mark_selected_by_number(run_id, numbers)`.
Add `--run-id`, defaulting to the most recent run.

Neither script may fail because the database is unavailable. Wrap both
calls so a database error prints a warning and the pipeline continues.
Generating pitches must not depend on bookkeeping.

Gate: run `pitch.py` then `editgen.py 2 5 9`, and
`db.selection_rate()` reports 3 of 10.

### Session 3 — web app skeleton

FastAPI, Jinja2 templates, vanilla JS. No build step, no framework, no
component library. The whole frontend readable in one sitting.

This session: the dashboard route only, reading real data. Prove it
reaches the page. Styling next.

Gate: `uvicorn app.main:app --reload` shows real rows.

### Session 4 — the screens

Build one per prompt, not all at once.

**`/` dashboard.** Top performers — title, platform, views, sparkline.
Counts for runs, ideas, videos, snapshots. Pick rate.

Two separate controls, and label them so they do not get confused:

- **Measured at** — 7 / 30 / 90 days old. How old each video was when
  scored, so everything is compared at the same age.
- **Posted in the last** — 3 / 6 / 12 months / all time. Which videos are
  eligible. Default to 6 months.

Colour rows against `db.benchmark()` for the same window: above median
`--good`, below `--bad`. The benchmark must use the window on screen, not
all-time, or the colouring lies.

**`/metrics/new` add numbers.** The screen that gets used weekly, so it
has to be fast. One table, every video a row, editable cells for views /
likes / comments / saves. Tab across, enter down. Previous value greyed
behind each input. One save writes every changed row as a new snapshot.
Report what changed: "4 videos updated". Not a form per video.

**`/videos/new` add video.** Title, platform, posted date, url, timeline,
topic, hook type, optional idea link. `topic` and `hook_type` are free
text backed by a datalist of values already used, so vocabulary converges
without being locked down.

**`/videos/{id}`.** Metadata, full snapshot table, larger growth curve,
the originating pitch if there is one.

**`/pitches`.** Runs newest first, ten per run, picked ones marked. Pick
rate per prompt hash. This is the screen that tells you whether prompt
edits are working.

### Session 5 — YouTube numbers

YouTube Data API v3. An API key reads public statistics by video id;
channel analytics needs OAuth, so start with public stats.

- Parse video ids from stored urls: `youtube.com/watch?v=`, `youtu.be/`,
  `/shorts/`
- Write results through `record_metrics` like any other snapshot
- A refresh button on the metrics screen
- Missing key or failed call must not break the screen; manual entry
  keeps working

Gate: one real video's numbers arrive without typing.

Instagram and TikTok stay manual until their developer approvals land.
The screen does not change when they do.

## Design direction

This sits beside DaVinci Resolve on the same desktop. It should look like
it belongs there, not like a SaaS dashboard.

**Palette.** Neutral dark, the way a grading suite is neutral dark. No
blue-black, no warm grey. Colour judgement is the user's profession and a
tinted interface is a real irritation.

```
--bg     #1C1C1C   surround
--panel  #242424   cards, rows
--line   #333333   hairlines
--text   #E4E4E4   primary
--dim    #8A8A8A   labels, units
--good   #6FCF97   above median
--bad    #C97064   below median
```

Two accents, both meaning something. Nothing coloured for decoration.

**Type.** Inter for interface, 14px base, weights 400 and 500 only. A
monospace face with tabular figures for every number, date and duration,
so columns align down the page. Misaligned digits look broken to someone
who reads timecode all day.

**Signature element.** The growth curve, inline in each dashboard row,
drawn like a scope readout — 120x28 inline SVG from `get_video_history`,
thin stroke, no fill, no gridlines, no axis labels. The shape is the
information. Build that well and keep everything else quiet.

No gradients, no shadows, no border-radius above 4px, no icons where a
word fits.

**Empty states** say what to do next, with the action there. "No videos
yet. Add your first one." Not an illustration.

## Rules

- TDD on anything with logic: failing test first, confirm it fails, commit
  the test, then implement. Template-only routes are exempt. Parsers and
  queries are not.
- Conventional commits, one concern each.
- Never commit `.env`, API keys, or `data/*.db`.
- After each session, review the diff in a fresh context. Flag only what
  affects correctness or contradicts this file.
- Do not add anything not specified here. Raise it instead.

## Out of scope

Retrieval, trend features, LangGraph, user accounts, hosting, mobile
layout, light mode. Generative video prompts (Runway/Veo/Kling) — this
pipeline cuts real footage; that is a different product and mixing them
now would muddle both.

---

# Addendum — generative clips

One slot in an edit may be a clip that does not exist in the footage
library. This covers writing its prompt, tracking attempts, and learning
which prompts land.

## Why it belongs here

The decisions log already names the cost of footage-first generation:
creative range is bounded by the library, "mitigated by having the model
flag footage gaps, which become the next shoot's shot list." Some of those
gaps do not need a shoot. This is that mitigation, extended.

Constraint to hold: **one generated clip per edit, maximum.** A 15-second
noir cut built mostly from generated footage stops being your footage.
Enforce it in code, not in intention.

## New files

- `src/shot.py` — `Shot` dataclass, controlled camera and size vocabulary,
  one renderer per tool, house style baked in. No API calls, no database.
- `src/generative.py` — `shots` and `generations` tables, attempt
  tracking, scoreboards. Extends `db.py`; run `generative.init()` after
  `db.init_db()`.

47 tests pass across both plus the core spine. Read them before changing
anything — several encode decisions that are not obvious from the code.

## What gets measured

Not "is this prompt good". **Attempts before a usable clip.** Generative
video is a slot machine; a prompt landing in 2 tries beats one landing in
9 regardless of how it reads. `attempts_to_keeper()` and
`tool_scoreboard()` are the two functions that matter.

Also log `reject_reason` on failures. Grouped, it tells you which failure
your prompts keep inviting, which is more actionable than a hit rate.

## Sessions

### G1 — footage gaps become shots

`editgen.py` already produces `warnings` when the footage cannot support a
constraint. Extend `edit_prompt.txt` so the model may mark at most one
edit_list entry as `"source": "generate"` with a shot description, instead
of forcing a real filename.

Then `validate_edit` must exempt generative slots from the "unknown clip"
check — but still enforce in/out points and total runtime, since the
generated clip has to fit the cut like any other.

Write the failing tests first: an edit with one generative slot validates,
an edit with two is rejected, a generative slot with no description is
rejected.

Gate: a real `editgen.py` run produces a `concepts.json` containing one
generative slot, and `validate_edit` accepts it.

### G2 — the prompt writer

A command that takes a generative slot and produces prompts for all three
tools.

Build it in two layers. The renderer layer already exists and is pure and
tested — do not put an LLM in it. The LLM's job is turning the edit's
loose description into a well-formed `Shot`, nothing more. Structured
output into the dataclass, then `render_all()` compiles it.

That split matters: it means a bad prompt is either a bad `Shot` (the
model's fault, visible in the JSON) or a bad compile (your renderer's
fault, catchable in a test). Without it you cannot tell which broke.

Once `winning_prompts()` has entries, feed the top few into the writer as
examples. Same retrieval pattern as pitch selection: your own record, not
general advice.

Gate: one slot in, three prompts out, `Shot` validation rejecting free-text
camera moves.

### G3 — logging attempts

A small command: record a generation, mark kept or rejected with a reason.
Runs after you have actually generated in the tool's own UI.

Do not automate calling the generation APIs yet. Rendering the prompt is
where the reusable work is; submitting it is a thin wrapper you can add
once you know which tool you actually use.

Gate: `tool_scoreboard()` returns real numbers after a week of use.

### G4 — screens

Add to the web app:

- `/shots` — open shots queue, attempts so far, prompts per tool with a
  copy button
- `/shots/{id}` — every attempt, side by side, kept one marked
- On the dashboard — tool scoreboard and median attempts-to-keeper

## Verify the tool vocabulary first

`shot.py`'s per-tool phrasing is a starting point drawn from general
patterns, not from current documentation. Before relying on it, check each
tool's current prompt guide and correct the `RUNWAY_CAMERA`, `VEO_CAMERA`
and `KLING_CAMERA` maps.

This is exactly what the renderer layer is for: when a tool changes its
vocabulary, you fix one dictionary rather than every prompt you have
stored. Note the date you last verified each map in a comment.

## Out of scope

Calling generation APIs directly, image-to-video, multiple generated clips
per edit, upscaling, automatic clip insertion into Resolve. The generated
file goes into `footage/` by hand and gets ingested like anything else.
