[![CI](https://github.com/zeropage-onryo/video-pipeline/actions/workflows/ci.yml/badge.svg)](https://github.com/zeropage-onryo/video-pipeline/actions/workflows/ci.yml)

# Zero Page Films — production pipeline

> **An automated video production machine for a solo filmmaker — real footage and AI, mixed.**
> It generates concepts and shot lists from your real rooms, writes platform-native AI video
> prompts for the shots a camera can't get, plans the cut from your real footage, and learns from
> what performs. Real material grounds everything; AI extends it.

A production pipeline for a one-person film operation, aimed at running more of itself over
time: it helps decide what to make (concepts, shot lists), decides shot by shot what gets
captured versus generated, writes the AI prompts across platforms, and feeds posted-video
analytics back into the next slate. Editing stays by hand — the judgment worth automating is
which shots and which moments, not the mechanical assembly.

Built for solo shoots — one operator who is also the on-screen subject, two cameras, a house,
and six AI video platforms.

## What it does

**Before the shoot — idea to shot list.** Photograph a space and the tool describes it: geometry,
light sources, textures, workable camera positions, and what the room *won't* allow. Concepts are
then generated against those real rooms — 8 cheap ideas to choose between, or one complete shoot
plan: a shot-by-shot list with camera, framing, movement, and lighting drawn from what's genuinely
in the space, plus edit rhythm and grade notes.

**Real and AI shots, mixed.** Every plan decides shot by shot what you capture and what a model
generates — both grounded in the same photographed rooms, so the mix cuts as one piece. Each AI
shot carries a paste-ready, platform-native prompt (Veo, Kling, Runway, Seedance, LTX, Wan; one
controlled shot vocabulary, one renderer per platform). Attempts are logged per tool, so you
learn which prompts land in two tries and which take nine.

**After the shoot — footage to cut list.** Ingest catalogs and organizes raw clips: duration and
resolution via ffprobe, a Whisper transcript, and a vision pass that timestamps what happens
inside each shot. From that manifest it proposes story pitches, and for the ones you pick it
writes full edit specs — ordered in/out points, sound notes, and per-shot grade notes on top of
your existing LUT.

**It learns from your choices.** Which ideas you plan, which concepts you shoot, which pitches you
cut — each decision is recorded against the hash of the prompt that produced it. So changing a
prompt becomes something you can measure against the rate it produced, rather than argue about.
Posted videos and their view counts feed back in, compared at equal age so a year-old video can't
beat last week's on accumulated totals alone.

## The rule the whole thing is built on

**Grounded in what exists — grounding shapes, it doesn't gate.** Every idea, shot list, AI
prompt and cut plan is generated from real material: photographed rooms, ingested footage, your
own posted results. Checks still run — in/out points against real clip durations, locations
against described spaces — but as visible advisories the filmmaker weighs, never rejections. A
generated plan that breaks a rule is saved with its warnings, because it is worth looking at and
deciding on, not silently discarded.

The second rule, learned the hard way: **verify by running it.** Every real defect this project has
had passed code review and passed its own tests. They were caught by starting the server, clicking
the thing, or noticing the test suite had quietly gotten slower.

## Pipeline

```
PRE-PRODUCTION                        POST-PRODUCTION
photos of a room                      raw footage
   |                                     |
   | vision: light, texture,             | ffprobe + Whisper + vision:
   | angles, constraints                 | duration, transcript, timestamped beats
   v                                     v
described spaces                      manifest
   |                                     |
   | + brand, spark, POV on/off          | story pitches (you pick a few)
   v                                     v
concepts  ->  shot list + AI slot     edit specs: in/out points, sound, grade notes
   |             + edit & grade notes     |
   | [ you shoot it ]  ------------------>|
   |                                      v
   |                                 execute by hand in Resolve
   v
what you actually shot  ---------->  posted videos + view counts  ---> informs the next prompt
```

## Running it

```bash
venv/bin/pip install -r requirements.txt && venv/bin/pip install -e .
venv/bin/uvicorn app.main:app --reload      # everything, in the browser
```

Every step also has a CLI (`python -m src.locations`, `src.shootgen`, `src.ingest`, `src.pitch`,
`src.editgen`, `src.promptgen`, `src.genlog`). See `CLAUDE.md` for the full command list and
architecture notes.

Needs `GEMINI_API_KEY` in `.env`. `YOUTUBE_API_KEY` is optional — it enables pulling public view
counts and importing a channel automatically; without it manual entry works exactly the same.

## Reference library (RAG)

Pitches can be grounded in a retrieval library: text you want the writing to learn from —
brand notes, past scripts, films-you-admire notes — chunked, embedded with
`gemini-embedding-001`, and stored in **PostgreSQL + pgvector**. At pitch time the manifest's
clip descriptions become the query, and the closest chunks are injected into the prompt as
tone/structure references (with a hard rule: never pitch what a reference shows but the
footage doesn't). No Postgres? The pitch run continues ungrounded and says so — the library
is an enhancement, not a dependency.

```bash
# one-time setup: EITHER a local Postgres (Postgres.app / brew) + `createdb zeropage`,
# OR no local install at all:
docker compose up -d     # Postgres + pgvector; set DATABASE_URL per docker-compose.yml

# build the library, ask it questions, wire it into pitches automatically
venv/bin/python -m src.rag ingest prompts/brief.txt --domain personal_brand
venv/bin/python -m src.rag query "stillness broken once" --k 5 [--domain cinematography]
venv/bin/python -m src.pitch                # picks up references on its own

# measure retrieval quality against labeled cases (hit@k, MRR)
venv/bin/python -m src.rag_eval eval_cases.json --k 5
```

An eval case file is plain JSON — `[{"query": "...", "relevant": ["brief.txt"]}]` — judged at
the document level, because that's what a human can actually label.

## Tech Stack
- **Python**, **FastAPI** + **Jinja2** — pipeline and a no-build-step web app
- **SQLite** — spaces, concepts, pitches, videos, metric snapshots, generation attempts
- **PostgreSQL + pgvector** — the retrieval library grounding pitch generation (optional; everything else runs without it)
- **Google Gemini** — vision descriptions of rooms and clips, concept and edit-spec generation
- **OpenAI Whisper** — clip transcription
- **FFmpeg / ffprobe** — metadata and frame extraction
- **Veo / Kling / Runway / Seedance / LTX / Wan** — AI shots (prompts written here, generated in each tool's UI)
- **pytest** + **ruff**, run in CI on every push

## Roadmap
- `/shots` queue and the tool scoreboard — waiting on real generation attempts to measure
- Verify the per-tool camera vocabulary against each platform's current prompt guide
- Instagram and TikTok stats stay manual until their developer approvals land; the screen
  doesn't change when they do
- Case-study writeup with a demo video

## Decisions Log

**2026-07-08 — Two-stage generation (pitch, then edit).**
`src/pitch.py` generates a cheap slate of 10 story descriptions from the
manifest; a human selects a few; only those get full edit specs (clip in/out
points, grade notes, sound notes) generated by `src/editgen.py`. Selection is
the one decision kept manual — everything before and after it is automated.

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
DaVinciResolveScript, rather than rendering standalone preview files. 
Edits appear in the real project with media already linked — no 
export/import round-trip. Fallback: FFmpeg-rendered preview .mp4s if 
the API path fails or for quick triage.

**2026-07-29 — Removed beat-synced cutting.**
Cut transitions were being snapped to detected or synthetic musical beats.
Removed because the timing of a cut is a creative decision and snapping
overrode it mechanically — a cut landing on a beat is not the same as a cut
landing where the shot wants to end. Also removed `librosa` and its
dependency chain (`numba`, `scipy`, `soundfile`, `audioread`). Cut points now
come only from the clip's own described beats, which is what the edit prompt
was already reasoning about.

**2026-07-29 — Removed automatic color grading.**
`apply_grade.py` applied a saved `.drx` to every clip on named timelines.
Removed because grading is shot-by-shot work and a blanket application
produced something that always needed redoing by hand. The grade preset
stays in `grades/` and is applied manually in Resolve.

**2026-07-29 — Superseded 2026-07-08 "Rough cuts target Resolve Studio's
scripting API". Removed the Resolve integration entirely.**
`build_timeline.py`, `apply_grade.py` and `resolve_edit.py` are gone. The
pipeline now ends at a validated cut list in `concepts.json`, which is
executed by hand. Reason: assembling the timeline was the least valuable
step and the most brittle — it required Resolve running with a project open,
matched clips by filename across two systems, and produced an assembly that
was always re-cut anyway. The judgment worth automating is which shots and
which moments, not the mechanical assembly. Cost: no more one-command rough
cut. Accepted, because the rough cut was never the output that got used.

<!-- DRAFT — per RUNBOOK, Decisions Log entries are yours to write. Edit the
     reasoning (especially the "why now" in the first entry — that's your call,
     not mine), delete this comment, then commit. -->

**2026-07-30 — Added a pre-production phase: locations, then concepts.**
The pipeline was footage-first end to end — it could only reason about clips
that already existed. That meant the hardest part of a one-person operation,
deciding what to shoot at all, happened entirely outside the tool. Now
`locations.py` photographs and describes the spaces available (geometry,
light sources, textures, workable angles, and what each space won't allow),
and `shootgen.py` generates concepts and ≤6-shot lists grounded in those real
rooms. Ported from two React generators that ran as Claude artifacts; moving
them in swapped the Anthropic API for this project's existing Gemini client
and browser storage for SQLite, which is what makes concepts queryable and
comparable rather than trapped in one browser session. Cost: a second meaning
for the word "concept" in this repo — `concepts.json` is a cut list for
footage you have, `shoot_concepts` is a shot list for footage you need.
Accepted, with the names kept deliberately distinct.

**2026-07-30 — Concepts are grounded in photographed spaces, not imagined ones.**
`validate_concept` rejects any shot whose `location` isn't a space that has
actually been photographed and described. This is the pre-production version
of the footage-first rule: the same reason edit specs are validated against
the manifest applies one step earlier, because a concept set in a room you
don't have is worse than no concept — it reads as usable and wastes a shoot
day. Tradeoff: you can't generate anything until at least one space is
described, and the UI hides the generate button until then rather than
offering something that would fail.

**2026-07-30 — Recording which concepts actually get shot.**
`shoot_concepts.shot_done`, alongside the prompt's hash. Same reasoning as
recording which pitches get picked: the decision is already being made, it's
free to store, and without it a prompt rewrite can only be argued about
rather than measured. Generating ten concepts and shooting one is a different
outcome from generating three and shooting two, and `shoot_rate()` makes that
difference visible per prompt version.

**2026-08-04 — The pivot: from grounded validator to autonomous content machine.**
Retired the "grounded inverse of Google Flow" identity — a tool whose selling point was
rejecting model output that didn't match reality. The mission now is an automated production
pipeline mixing real footage and AI that runs more of itself over time: L1 assisted → L2
grounded generation + measurement → L3 self-improving ideation from performance data → L4
supervised autonomous generate-and-post (gated, dry-run, default off). What changed in code:
the 6-shot cap, the one-AI-shot-per-concept slot, and the one-generative-clip-per-edit cap are
gone — real and AI shots are co-inputs, each shot carrying `source: CAMERA | AI`; the AI
platform set became data (`shot.PLATFORMS`, now also Seedance 2.0, LTX-2, Wan 2.2); and a
missing described location degrades to an ungrounded run with a note instead of raising. What
deliberately did not change: grounding itself (rooms, footage, and the reference library still
shape every generation), every human pick recorded against its prompt hash, degrade-don't-break,
and the 2026-07-29 removal of the Resolve integration — **editing stays manual (an explicit L1
hold)**. Validators survive as advisories: visible warnings, never gates. Supersedes the
rejection clause of "Concepts are grounded in photographed spaces" (2026-07-30) and
BUILD_SPEC's "one generated clip per edit, maximum."
