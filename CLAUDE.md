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

# 0b. Generate a shoot concept grounded in those spaces -> shoot_concepts table
venv/bin/python -m src.shootgen [--brand antihero|zeropage] [--client ...] [--spark ...] [--count N]

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

# WEB APP
venv/bin/uvicorn app.main:app --reload
```

`src/` is an installed editable package (`pyproject.toml`) — modules use relative imports and run
via `python -m src.<module>`, not `python src/<module>.py`.

Tests run with `venv/bin/python -m pytest tests/ -q`; lint with `venv/bin/ruff check .`. Both run
in CI on every push and PR (`.github/workflows/ci.yml`).

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
                                    shootgen.py <-+  (+ brand, spark)
                                                  |
                                          shoot_concepts table
                                          (title, hook, <=6 shots, AI slot, edit, grade)
                                                  |
                                         [ you go shoot it ]
                                                  |
POST-PRODUCTION (footage exists)                  v
footage/*.mov  --ingest.py-->  manifest.json  --pitch.py-->  pitches.json
                                     |                            |
                                     +-------- editgen.py <-------+  (human picks pitch numbers)
                                                    |
                                              concepts.json
```

Post-production ends at `concepts.json` — a validated cut list you execute by hand in Resolve.
Nothing in the pipeline writes to Resolve or needs it running.

**Two names that sound alike and are not.** `concepts.json` (post-production, `editgen.py`) is a
cut list for footage you *have*. The `shoot_concepts` table (pre-production, `shootgen.py`) is a
shot list for footage you *need*. Don't merge them.

- **`src/locations.py`** — scans `locations/<name>/`, sends each space's photos to Gemini vision,
  stores `{space, light_sources, textures, angles, constraints}` per location. Incremental like
  `ingest.py`: a space already described is skipped unless `--force`.
- **`src/shootgen.py`** — loads the described locations, fills `prompts/concept_prompt.txt` with
  them plus a brand block from `prompts/brands.txt`, and asks Gemini for one concept.
  `validate_concept` enforces (not just warns) at most 6 shots, `CHARACTER`/`BROLL`,
  `BMPCC`/`ACTION5`, `KLING`/`RUNWAY`, and — the one that matters — that every shot's `location`
  is a space that actually exists. A concept with warnings is still saved, warnings attached.
- **`src/preprod.py`** — `locations`, `shoot_concepts`, `concept_locations` tables. Extends
  `db.py` in its own module (own `SCHEMA`, own `init()`), same pattern as `generative.py`.
  `shot_done` records which generated concepts you actually shot — the pre-production equivalent
  of `ideas.selected`, and `shoot_rate()` breaks it down per prompt hash.
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
  `{selected_pitches}`, `{locations}`, `{brand}`, `{client}`, `{spark}` as the templating
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
  human picks a few (`ideas.selected`); `shootgen.py` generates concepts and a human actually
  shoots some (`shoot_concepts.shot_done`). Both are stored with the prompt's hash, so a prompt
  change can be measured against the rate it produced rather than argued about. That selection
  is also the only manual gate in each phase.
