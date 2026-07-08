# AI Video Pipeline

## Overview

## Architecture

## How It Works

## Tech Stack

## Decisions Log
  ## Decisions Log

**2026-07-08 — Pipeline operates on proxies, not camera originals.**
All ingest and analysis runs on DaVinci Resolve proxy files rather than
6K Blackmagic RAW. Reasons: FFmpeg/Whisper can't read .braw natively,
processing time scales with file size, and transcription/tagging don't
need image quality. Camera originals are only touched by Resolve at
final export. Tradeoff: pipeline outputs reference proxy filenames, so
filenames must stay consistent between the proxy folder and Resolve's
media pool.

**2026-07-08 — Footage-first generation instead of script-first.**
Edit concepts are generated FROM the manifest of real footage, rather
than writing scripts and then searching for matching clips. Rejected
script-first because it produces edit lists calling for shots that were
never filmed. Cost: creative range is bounded by the current library —
mitigated by having the model flag footage gaps, which become the next
shoot's shot list.

**2026-07-08 — Manifest as the interface between stages.**
The pipeline's stages (ingest → story generation → timeline build)
communicate through manifest.json / concepts.json files rather than
direct coupling. Reasons: each stage can be run, tested, and debugged
independently, and intermediate outputs are human-readable. Tradeoff:
filenames act as IDs across stages, so renaming clips after ingest
breaks the chain — filenames are treated as immutable once ingested.

**2026-07-08 — Gemini API for story generation.**
Using Google's Gemini rather than other LLM APIs for concept
generation. Also relevant: Gemini's native video-input support leaves
a clean upgrade path from transcript-based tagging to true visual
analysis of clips without changing providers.

**2026-07-08 — Model output validated in code, not trusted from the prompt.**
storygen.py independently verifies that every clip filename in a
generated concept exists in the manifest and that in/out points fall
within real clip durations, rejecting concepts that fail. The prompt
also instructs this, but prompt instructions alone don't prevent
hallucinated filenames — validation is enforced at the code layer.
Lesson: prompts request, code enforces.

**2026-07-08 — Prompts and creative brief live in editable text files.**
The storygen prompt and brand brief are stored in prompts/ as plain
text with placeholder injection, not hardcoded in Python. Prompt and
brief tuning is the highest-frequency change in this system; editing
text files keeps iteration fast and keeps creative direction separate
from logic. Tradeoff: one more layer of files to keep in sync with the
code that loads them.

**2026-07-08 — Rough cuts target Resolve Studio's scripting API.**
Timelines are built directly inside the open Resolve project via
DaVinciResolveScript (available since Studio license is in hand),
rather than rendering standalone preview files. Reason: edits appear
in the real project with media already linked — no export/import
round-trip. Fallback documented: FFmpeg-rendered preview .mp4s if the
API path fails or for quick triage before committing timelines.
