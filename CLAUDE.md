# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

An AI pre-production tool for Zero Page Films (a one-person brand). It takes raw footage and
turns it into a validated cut list: an LLM proposes edit concepts from real footage, a human
picks favorites, and full edit specs get generated and checked in code against the manifest.
Experimental — cut lists are generated end-to-end but coherence is still being tuned.

## Commands

All Python commands run through the project's venv, not system Python:

```bash
venv/bin/pip install -r requirements.txt
venv/bin/pip install -e .

# PRE-PRODUCTION (before anything is shot)
# 0a. Describe the spaces in locations/<name>/*.jpg -> locations table
venv/bin/python -m src.locations [--locations-dir locations] [--force]

# 0b. Generate concepts grounded in those spaces -> shoot_concepts table.
#     Two stages: cheap ideas first, then a shot list for the ones you pick.
venv/bin/python -m src.shootgen [--brand antihero|zeropage] [--client ...] [--spark ...] [--count 8]
venv/bin/python -m src.shootgen --shotlist <concept_id>

# POST-PRODUCTION (footage exists)
# 1. Ingest raw footage -> manifest.json (ffprobe metadata, Whisper transcript, Gemini vision description per clip)
venv/bin/python -m src.ingest [--footage-dir footage] [--output manifest.json] [--model base] [--skip-transcription]

# 2. Generate 10 story pitches from manifest.json -> pitches.json
venv/bin/python -m src.pitch

# 3. Generate full edit specs for chosen pitch numbers -> concepts.json
venv/bin/python -m src.editgen <pitch_numbers...> [--print]

# GENERATIVE CLIPS (for a shot the footage can't cover)
venv/bin/python -m src.promptgen "<loose shot description>" [--idea-id N] [--slot-index N]
venv/bin/python -m src.genlog record|keep|reject ...

# WEB APP — everything above is also doable in the browser at 127.0.0.1:8000
venv/bin/uvicorn app.main:app --reload
```

`src/` is an installed editable package (`pyproject.toml`) — modules use relative imports and run
via `python -m src.<module>`, not `python src/<module>.py`.

Tests run with `venv/bin/python -m pytest tests/ -q`; lint with `venv/bin/ruff check .`. Both run
in CI on every push and PR (`.github/workflows/ci.yml`).

**`tests/conftest.py` blocks all network access during tests.** This exists because the same bug
landed four times: a test monkeypatches one generator function, the route is changed to call a
different one, the patch silently misses, and a real billed API call happens while the test still
passes — the only symptom being a slower suite. If a test fails with `NetworkUseInTest`, it is
patching something the code under test no longer calls.

Requires `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) in `.env` for pitch/editgen/shootgen/promptgen and
ingest's and locations' vision steps. `YOUTUBE_API_KEY` is optional — it enables auto-fetching
public view counts and importing a channel's videos; without it manual entry still works.

## Architecture

Two phases either side of the shoot. Pre-production reasons about **spaces you have**;
post-production reasons about **footage you shot**. Post-production stages communicate through
JSON files on disk; pre-production and the feedback loop use SQLite (`data/pipeline.db`).

```
PRE-PRODUCTION (nothing shot yet)
locations/<name>/*.jpg  --locations.py-->  locations table (vision description per space)
                                                  |
                            shootgen.py ideas <---+  (+ brand, spark, POV on/off)
                                                  |
                                    shoot_concepts rows, shots = []   <-- cheap ideas
                                                  |
                            shootgen.py --shotlist <id>   (human picks: THE LABEL)
                                                  |
                                    same row, now with <=6 shots, AI slot, edit, grade
                                                  |
                                         [ you go shoot it ]  -> shot_done (SECOND LABEL)
                                                  |
POST-PRODUCTION (footage exists)                  v
footage/*.mov  --ingest.py-->  manifest.json  --pitch.py-->  pitches.json
                                     |                            |
                                     +-------- editgen.py <-------+  (human picks pitch numbers)
                                                    |
                                              concepts.json
```

**Both phases are two-stage for the same reason.** Generate cheap options, a human picks, and
only the picks get expensive detail — `pitch.py`→`editgen.py` post-production,
`generate_concept_ideas`→`generate_shot_list` pre-production. The pick is recorded either way
(`ideas.selected`, `shoot_concepts.shots != []`), which is what makes a prompt change measurable
rather than arguable. `shootgen` can still produce one full concept in a single call
(`generate_concept`) — that's what the web app's main button does.

Post-production ends at `concepts.json` — a validated cut list you execute by hand in Resolve.
Nothing in the pipeline writes to Resolve or needs it running.

**Two names that sound alike and are not.** `concepts.json` (post-production, `editgen.py`) is a
cut list for footage you *have*. The `shoot_concepts` table (pre-production, `shootgen.py`) is a
shot list for footage you *need*. Don't merge them.

- **`src/locations.py`** — scans `locations/<name>/`, sends each space's photos to Gemini vision,
  stores `{space, light_sources, textures, angles, constraints}` per location. Incremental like
  `ingest.py`: a space already described is skipped unless `--force`.
- **`src/shootgen.py`** — three entry points over the same described locations plus a brand block
  from `prompts/brands.txt`: `generate_concept_ideas` (N cheap ideas in **one** call, so they're
  varied against each other rather than rolled independently), `generate_shot_list` (the shot plan
  for an idea you picked, leaving its title/hook/logline untouched), and `generate_concept` (both
  at once, what the web app's main button uses). `validate_concept` enforces (not just warns) at
  most 6 shots, `CHARACTER`/`BROLL`, `BMPCC`/`ACTION5`, `KLING`/`RUNWAY`, and — the one that
  matters — that every shot's `location` is a space that actually exists. A concept with warnings
  is still saved, warnings attached. `apply_pov(template, use_pov)` is why the POV toggle is real:
  off rewrites the prompt so `ACTION5` is never offered *or* named as legal, and `validate_concept`
  rejects it if the model reaches for it anyway.
- **`src/preprod.py`** — `locations`, `shoot_concepts`, `concept_locations` tables. Extends
  `db.py` in its own module (own `SCHEMA`, own `init()`), same pattern as `generative.py`.
  Two labels, not one: `shortlist_rate()` is which ideas were worth planning (derived from
  `shots != []`, never stored, so it can't drift), `shoot_rate()` is which ones actually got shot.
  Both break down per prompt hash.
- **`src/ingest.py`** — scans `footage/`, runs `ffprobe` for duration/resolution, Whisper for
  transcription (filtering low-confidence/repetitive segments via `is_repetitive`), and samples 3
  frames (10%/50%/90% of duration) sent to Gemini vision for a per-clip `{beats, arc}`
  description. Incremental: re-runs reuse a clip's existing `description` from the prior
  manifest (matched by filename) and only regenerate the new `{beats, arc}` shape, skipping
  old flat-string descriptions. Writes `manifest.json` after every clip, not just at the end.
- **`src/pitch.py`** — loads `manifest.json` plus `prompts/brief.txt` (brand identity) and
  `prompts/settings.txt` (locked runtime/tone/pacing constraints), fills `prompts/pitch_prompt.txt`,
  and asks Gemini for 10 cheap story pitches. `validate_pitches` only warns (never blocks) if a
  pitch's `story_note` doesn't reference a real clip filename.
- **`src/editgen.py`** — takes pitch numbers selected by a human, loads the corresponding entries
  from `pitches.json`, fills `prompts/edit_prompt.txt`, and asks Gemini for full edit specs
  (ordered clip in/out points, grade notes, sound notes). `validate_edit` enforces (not just
  warns) that every clip exists in the manifest, in/out points fall within real clip duration, and
  total runtime is within `MIN_RUNTIME`/`MAX_RUNTIME` (13-17s) — model output is never trusted
  without this code-level check. `--print` renders each edit's cut list as plain text (clip, in,
  out, duration, running total) via `format_edit_as_text`, to read beside Resolve without parsing
  `concepts.json` by eye.
- **`src/shot.py`** / **`src/promptgen.py`** / **`src/genlog.py`** / **`src/generative.py`** — the
  generative-clip side, for the one shot per edit the footage can't cover. `shot.py` is a `Shot`
  dataclass with a controlled camera/size vocabulary and one **pure** renderer per tool; no model
  call goes near it. `promptgen.py` is the only place an LLM turns a loose description into a
  `Shot`. That split is deliberate: a bad prompt is then either a bad `Shot` (visible in the JSON,
  the model's fault) or a bad compile (catchable in a render test, the renderer's fault). Collapse
  it and you can't tell which broke. `genlog.py` records attempts after you generate in the tool's
  own UI; `generative.py` holds `shots`/`generations` and the scoreboards. **Unverified:** the
  `RUNWAY_CAMERA`/`VEO_CAMERA`/`KLING_CAMERA` maps are general patterns, not current docs — check
  each tool's prompt guide before trusting the wording, and date the comment above each map.
- **`src/youtube.py`** — video-id parser for `watch?v=`/`youtu.be`/`shorts` URLs (the part that
  actually breaks), public stats via the Data API v3, and channel import. `refresh_metrics_for_video`
  and `import_channel_videos` never raise: a missing key or failed call returns `{"ok": False}` so
  manual entry keeps working, per BUILD_SPEC.
- **`app/main.py`** — the web app; every CLI step above is also doable in the browser. `/concepts`
  is the one-screen generator (photos, add-a-space, brand, POV toggle, spark, generate, results).
  `/locations` serves photos through `location_photo`, which resolves both path segments and
  refuses anything that escapes `locations/` — a space name becomes a directory name, so it's
  sanitised on the way in too. `?thumb=1` serves a cached 480px JPEG rather than the multi-megabyte
  original. Routes that call a model wrap it and redirect with a message rather than 500ing.
- **`src/gemini_utils.py`** — shared `generate_with_retry` (retries on `RESOURCE_EXHAUSTED`/
  `UNAVAILABLE`, falls through to `FALLBACK_MODELS` if the primary model stays down for the whole
  retry budget) and `strip_fences` (strips markdown code fences from model JSON output).

### Key conventions to preserve

- **Manifest is the interface, filenames are IDs.** Every stage after ingest keys off
  `manifest.json`'s `filename` field. Renaming a clip after ingest breaks the chain — treat
  ingested filenames as immutable. `pitch.py`'s regex assumes filenames follow the
  `A037_..._C001.mov` (camera card) or `DJI_..._D.mov` (drone) patterns.
- **Pipeline operates on proxies, not camera originals.** `footage/` holds Resolve proxy files,
  not 6K Blackmagic RAW — ffmpeg/Whisper can't read `.braw` natively and don't need full image
  quality. Camera originals are only touched by Resolve at final export.
- **Prompts and brand brief are plain text in `prompts/`, not hardcoded strings.** They're the
  highest-frequency edit surface in this system; treat `{brief}`, `{settings}`, `{manifest}`,
  `{selected_pitches}`, `{locations}`, `{brand}`, `{client}`, `{spark}`, `{count}`,
  `{title}`/`{hook}`/`{logline}`, and `{pov}`/`{cam_rule}`/`{cam_values}` as the templating
  placeholders when changing prompt files.
- **Prompts request, code enforces.** Model output is always independently validated against
  reality — real filenames and durations for edits, real location names for concepts — never
  trust the prompt alone to keep the model from hallucinating clip references, out-of-range cut
  points, or rooms that don't exist.
- **Grounded in what exists, never invented.** Post-production is footage-first: edits come from
  what's in the manifest, never a script matched to clips afterward. Pre-production is the same
  rule one step earlier: concepts are built from photographed, described spaces, so the model
  can't call for a rooftop you don't have.
- **The human choice is the label, and it gets recorded.** `pitch.py` generates 10 pitches and a
  human picks a few (`ideas.selected`); `shootgen.py` generates ideas, a human plans some
  (`shortlist_rate`), and shoots fewer still (`shoot_done`). All stored with the prompt's hash, so
  a prompt change can be measured against the rate it produced rather than argued about. That
  selection is also the only manual gate in each phase.
- **Anything that calls a model degrades instead of breaking.** A missing API key or a failed call
  returns a result the caller can report, not an exception that takes the page or the run with it
  — `pitch.py` still writes `pitches.json`, `/metrics/new` still accepts typed numbers, `/concepts`
  still renders. The exceptions are deliberate: `promptgen` and `locations` fail loudly, because
  there the model call *is* the deliverable rather than bookkeeping on top of one.
- **Verify by running it, not by reading it.** Every real bug this project has had — a `warnings`
  string shattered into 140 single-character warnings, CI dying on torch's CUDA build, two tests
  passing only because the dev machine had a populated database, a site with no navigation between
  its own pages, tests quietly making billed API calls — passed review and passed its own tests.
  Each was found by starting the server, clicking the thing, or noticing the suite got slower.

## Where the project stands

Everything below is current as of the last commit on `main`. Update it when it stops being true.

**Working and verified against real data:** both phases run end to end, including real Gemini
calls. One location described from real photos, 9 concepts (2 with shot lists), 1 pitch run with
10 ideas and 3 picked, 1 posted video with one metric snapshot. 313 tests, ruff clean, CI green
on every push.

**Not started:** the thing the tool exists for. The rates (`shortlist_rate`, `shoot_rate`,
`selection_rate`) are structurally correct and currently meaningless — they need weeks of real use
before a prompt change can be measured against them. The most valuable next step is not code: it
is shooting one of the generated concepts, marking it shot, and adding the video.

**Known gaps, in rough priority:**
- `shot.py`'s `RUNWAY_CAMERA`/`VEO_CAMERA`/`KLING_CAMERA` maps and the AI-slot prompt phrasing are
  general patterns, not current documentation. Check each tool's prompt guide before relying on a
  generated prompt, and date the comment above each map.
- `YOUTUBE_API_KEY` in `.env` is a placeholder, so channel import and metric refresh can't reach
  the API. Everything else works without it.
- `validate_edit` warns where BUILD_SPEC says enforce. Deliberate for now — warnings are visible
  and you decide — but it is a real spec divergence, not an oversight.
- `import_channel_videos` can report success when the bulk stats call failed; `mark_kept` doesn't
  clear other keepers on the same shot, which skews `attempts_to_keeper`; `ingest.py` reads only
  `GEMINI_API_KEY` where every other module also accepts `GOOGLE_API_KEY`.
- `/shots` and the tool scoreboard aren't built — they need real generation attempts logged
  through `genlog.py` first, and inventing that data would corrupt the only numbers that matter.

**The user's real data lives in `data/pipeline.db` (gitignored, ~128KB) and `locations/`
(gitignored, photos).** A fresh clone gets the tool, empty. Never overwrite either without asking.
