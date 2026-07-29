# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

An AI-powered video editing pipeline for Zero Page Films (a one-person brand). It takes raw
footage and automatically produces rough-cut timelines inside DaVinci Resolve: an LLM proposes
edit concepts from real footage, a human picks favorites, full edit specs get generated, cuts are
snapped to a music track's beat, and a saved color grade is applied. Experimental — cuts are
generated end-to-end but coherence is still being tuned.

## Commands

All Python commands run through the project's venv, not system Python:

```bash
venv/bin/pip install -r requirements.txt

# 1. Ingest raw footage -> manifest.json (ffprobe metadata, Whisper transcript, Gemini vision description per clip)
venv/bin/python src/ingest.py [--footage-dir footage] [--output manifest.json] [--model base] [--skip-transcription]

# 2. Generate 10 story pitches from manifest.json -> pitches.json
venv/bin/python src/pitch.py

# 3. Generate full edit specs for chosen pitch numbers -> concepts.json
venv/bin/python src/editgen.py <pitch_numbers...> [--music path/to/track.mp3] [--bpm 120 --bpm-offset 0.3]

# 4. Build timelines in the currently-open DaVinci Resolve project from concepts.json
venv/bin/python src/build_timeline.py

# 5. Apply the saved grade to specific timelines (defaults to a hardcoded list of timeline names)
venv/bin/python src/apply_grade.py ["Timeline Name" ...] [--grade grades/zero_page_batman.drx]
```

There is no test suite, linter, or CI configured yet (see Roadmap in README.md).

Requires `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) in `.env` for pitch/editgen/ingest's vision step,
and DaVinci Resolve Studio running with a project open for build_timeline.py / apply_grade.py
(Preferences > General > External scripting using = "Local").

## Architecture

The pipeline is a one-way chain of stages, each its own module, that communicate only through
JSON files on disk — never by direct import of each other's data structures:

```
footage/*.mov  --ingest.py-->  manifest.json  --pitch.py-->  pitches.json
                                     |                            |
                                     +-------- editgen.py <-------+  (human picks pitch numbers)
                                                    |
                                              concepts.json
                                                    |
                                        build_timeline.py (Resolve API)
                                                    |
                                          apply_grade.py (Resolve API)
```

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
  without this code-level check. Optionally snaps cut boundaries to a real audio track's beats
  (`--music`, via `librosa` in `src/beat_sync.py`) or a synthetic BPM grid (`--bpm`, for
  platform-native sounds you can't download) — see `snap_edit_to_beats`, which keeps the first
  cut's start and last cut's end fixed and only moves internal transitions.
- **`src/build_timeline.py`** / **`src/resolve_edit.py`** — connect to a running DaVinci Resolve
  Studio instance via `DaVinciResolveScript`, match `concepts.json` clip filenames (by base name,
  extension-agnostic) against the media pool, and append matched sub-clips to new timelines using
  each clip's real FPS to convert seconds to frames.
- **`src/apply_grade.py`** — applies a saved `.drx` grade file to all video-track-1 items on named
  timelines (defaults to a hardcoded list of timeline names from the current shoot).
- **`src/gemini_utils.py`** — shared `generate_with_retry` (retries on `RESOURCE_EXHAUSTED`/
  `UNAVAILABLE`, falls through to `FALLBACK_MODELS` if the primary model stays down for the whole
  retry budget) and `strip_fences` (strips markdown code fences from model JSON output).

### Key conventions to preserve

- **Manifest is the interface, filenames are IDs.** Every stage after ingest keys off
  `manifest.json`'s `filename` field (or its base name without extension, for Resolve matching).
  Renaming a clip after ingest breaks the chain — treat ingested filenames as immutable.
  `resolve_edit.base_name()` / `pitch.py`'s regex both assume filenames follow the
  `A037_..._C001.mov` (camera card) or `DJI_..._D.mov` (drone) patterns.
- **Pipeline operates on proxies, not camera originals.** `footage/` holds Resolve proxy files,
  not 6K Blackmagic RAW — ffmpeg/Whisper can't read `.braw` natively and don't need full image
  quality. Camera originals are only touched by Resolve at final export.
- **Prompts and brand brief are plain text in `prompts/`, not hardcoded strings.** They're the
  highest-frequency edit surface in this system; treat `{brief}`, `{settings}`, `{manifest}`,
  `{selected_pitches}` as the templating placeholders when changing prompt files.
- **Prompts request, code enforces.** Model output is always independently validated against the
  manifest (real filenames, real durations, runtime windows) — never trust the prompt alone to
  keep the model from hallucinating clip references or out-of-range cut points.
- **Footage-first, not script-first.** Edit concepts are generated from what's actually in the
  manifest, never a written script matched to clips afterward — this keeps the model from
  proposing shots that were never filmed.
- **Two-stage generation, one manual gate.** `pitch.py` generates 10 cheap pitches; a human
  selects a few by number; only those get full edit specs from `editgen.py`. That selection is
  the only manual step in the pipeline.
