# Runbook — building this in Claude Code

Work through in order. Each session is a fresh Claude Code window. Do not
continue a session past its gate.

Roughly four working days. Day 1 is the one that matters most.

---

## Setup — 10 minutes, no Claude Code

```bash
cd video-pipeline
git checkout -b build/spine
mkdir -p tests data
```

Copy in the supplied files:

```
BUILD_SPEC.md          -> repo root
REMOVAL_SPEC.md        -> repo root
src/db.py              -> src/
src/shot.py            -> src/
src/generative.py      -> src/
src/editgen.py         -> src/   (replaces yours)
tests/test_db.py       -> tests/
tests/test_generative.py -> tests/
```

Add to `.gitignore`:

```
.env
data/*.db
venv/
manifest.json
pitches.json
concepts.json
__pycache__/
*.pyc
```

Commit this as `chore: add spine modules and specs`. Nothing runs yet —
that is expected.

---

## The habit that makes this work

After **every** session below, open a fresh Claude Code window and run:

```
Review the diff on this branch against BUILD_SPEC.md. Flag only things that
affect correctness or contradict the spec. Do not invent work.
```

Fix what it finds before moving on. A reviewer in a fresh context is not
biased toward code it just wrote. The "do not invent work" clause matters —
a reviewer told to find problems will always find some.

---

# Day 1 — the spine

## Session 0 — removals

```
Read REMOVAL_SPEC.md. Work through all seven sections in order, committing
each numbered section separately.

Before you start: read section "Warning before you start" carefully. The
word "beats" means two different things in this repo and only one is being
removed.

src/editgen.py has already been replaced with a cleaned version. Verify it,
then delete src/beat_sync.py.

Section 2 removes build_timeline.py, apply_grade.py AND resolve_edit.py.
resolve_edit is imported only by the other two, so it is dead once they go.
Confirm that with grep before deleting rather than taking my word for it.

Section 2 also asks for a --print flag on editgen.py. Do that one TDD:
failing test for the formatter first.
```

**Gate**

```bash
grep -rn "beat_sync\|apply_grade\|build_timeline\|resolve_edit\|librosa" \
     src/ *.md requirements.txt
```

Returns nothing. `git log --oneline` shows about seven commits.

Also confirm nothing needs Resolve any more:

```bash
grep -rn "DaVinciResolveScript" src/
```

Write the three Decisions Log entries yourself. Edit my drafts — the reasons
should be yours, and "it never sounded right" is more convincing than my
guess at your reasoning.

## Session 1 — foundation and the import fix

This one has a trap. State it up front:

```
Read BUILD_SPEC.md session 1.

Important: src/ is currently not a package. Existing modules use flat
imports (from gemini_utils import ...) that only work because scripts are
run as `python src/pitch.py`. The new src/generative.py uses relative
imports (from .db import ...) and cannot be imported that way.

Fix this properly:
- add pyproject.toml, make src a real package, install editable
- convert ALL existing src/ modules to relative imports
- update the run commands in CLAUDE.md and README.md to `python -m src.pitch`
- remove the sys.path hack from both test files

Do NOT solve this with sys.path.insert anywhere. If you find yourself
adding one, stop and tell me.

Also: add pytest to requirements.txt, drop librosa if session 0 missed it,
and try removing the numpy<2 pin per REMOVAL_SPEC section 3.

Plan mode first.
```

**Gate**

```bash
python -m pytest tests/ -q          # 47 passed
python -m src.db                    # creates data/pipeline.db
python -m src.pitch --help          # still runs
grep -rn "sys.path" src/ tests/     # nothing
```

If `pitches.json` exists, import it so the current run is not lost:

```
Run db.import_pitches_file on the existing pitches.json and confirm the
count with db.summary().
```

## Session 2 — capture the label

The highest-value session in this document. Two function calls.

```
Read BUILD_SPEC.md session 2. Implement it.

pitch.py: after writing pitches.json, call db.save_pitch_run with the
pitches, MODEL, len(manifest), and the raw text of brief.txt, settings.txt
and pitch_prompt.txt. Print the run id.

editgen.py: after a successful run, call db.mark_selected_by_number with
the pitch numbers already on the command line. Add --run-id defaulting to
the most recent run.

Critical: neither script may fail because the database is unavailable.
Wrap both calls so a database error prints a warning and the pipeline
continues. Generating pitches must never depend on bookkeeping.

Write a test for the failure path: a broken database path must not stop
pitch.py from writing pitches.json.
```

**Gate**

```bash
python -m src.pitch
python -m src.editgen 2 5 9
python -c "from src import db; print(db.selection_rate())"
```

Shows 3 chosen of 10.

**From this point every normal run of your pipeline accumulates labelled
data.** That is the thing that compounds. Everything below is worth less
than getting this working.

---

# Day 2 — generative clips

## Session 3 — footage gaps become shots

```
Read the "Addendum — generative clips" section of BUILD_SPEC.md, then
session G1. Implement G1 only.

TDD, in this order:
1. Write failing tests in tests/test_editgen.py: an edit_list with one
   entry marked "source": "generate" plus a shot description validates;
   two generative entries is rejected; a generative entry with no
   description is rejected. Confirm they fail. Do not write implementation.
2. Then update validate_edit to exempt generative slots from the unknown-
   clip check while still enforcing in/out points and total runtime.
3. Then update prompts/edit_prompt.txt so the model may mark at most one
   entry this way when the footage cannot support a shot.

Do not touch anything about clip "beats" in edit_prompt.txt — those are the
vision-description timestamps, not musical beats, and they are load-bearing.
```

**Gate** — a real `editgen.py` run produces a `concepts.json` with one
generative slot, and validation accepts it.

## Session 4 — the prompt writer

```
Read BUILD_SPEC.md session G2. Implement it as src/promptgen.py.

Architecture, non-negotiable:
- The LLM's ONLY job is turning a loose edit description into a valid Shot
  dataclass via structured output. Nothing else.
- src/shot.py's renderers are pure functions. Do not put a model call
  anywhere near them. Do not modify shot.py.
- Then call render_all() to compile.

This split means a bad prompt is either a bad Shot (visible in the JSON) or
a bad compile (catchable in a test). Do not collapse it.

Read tests/test_generative.py first — several tests encode decisions that
are not obvious from the code.

Plan mode first.
```

**Gate** — one generative slot in, three tool prompts out, and a free-text
camera value like "swooshes dramatically" raises rather than passing through.

## Session 5 — logging attempts

```
Read BUILD_SPEC.md session G3. Build a small CLI: src/genlog.py.

Commands: record a generation against a shot, mark one kept, mark one
rejected with a reason. It runs after you have generated in the tool's own
UI — do not call any generation APIs.

Keep reject reasons a short controlled list plus "other": morphing,
wrong lighting, camera ignored, subject wrong, artefacts, other.
Grouped reasons are only useful if the vocabulary is tight.
```

**Gate** — after logging a few real attempts, `gen.tool_scoreboard()` and
`gen.attempts_to_keeper()` return sensible numbers.

**Before you trust the prompts:** open each tool's current prompt guide and
correct `RUNWAY_CAMERA`, `VEO_CAMERA`, `KLING_CAMERA` in `shot.py`. Put the
date you checked in a comment above each map. Mine are starting points from
general patterns, not from current documentation.

---

# Day 3 — the app

## Session 6 — skeleton

```
Read BUILD_SPEC.md session 3. FastAPI, Jinja2, vanilla JS. No build step,
no framework, no component library.

This session: the dashboard route only, reading real data through src/db.py.
No styling beyond the palette variables. Prove the data reaches the page.
```

**Gate** — `uvicorn app.main:app --reload` shows your real rows.

## Sessions 7–10 — screens, one per session

Do not ask for four screens in one prompt. You will get four mediocre ones.

**Session 7**

```
Read BUILD_SPEC.md session 4 and the design direction. Build /metrics/new
only — the add-numbers screen.

Follow the keyboard behaviour exactly: tab across, enter down, previous
value greyed behind each input, one save writes every changed row as a new
snapshot. Report what changed.
```

**Session 8** — `/videos/new`, with datalist-backed free text for topic and
hook type.

**Session 9** — `/videos/{id}` and the sparkline:

```
Add the growth-curve sparkline. Inline SVG from db.get_video_history.
120x28, thin stroke, no fill, no axes, no gridlines. Show it to me before
styling anything around it.
```

**Session 10** — `/pitches` and `/shots`, plus the tool scoreboard on the
dashboard.

Check every screen at 1280px and 1920px.

---

# Day 4 — automation and finish

## Session 11 — YouTube

Get the key first, five minutes: Google Cloud Console, new project, enable
YouTube Data API v3, create an API key.

```
Read BUILD_SPEC.md session 5.

TDD: write failing tests for the video-id parser first. Handle
youtube.com/watch?v=, youtu.be/, and /shorts/ urls, plus urls with extra
query params. Confirm they fail. Do not write the fetcher yet.
```

The parser is the part that actually breaks. Test it properly.

## Session 12 — CI

```
Add .github/workflows/ci.yml running ruff and pytest on every push and PR.
Add a badge to README.md that links to the actual workflow runs.
```

Click the badge afterwards. A badge that does not link to real runs is worse
than none.

## Session 13 — README as case study

Do this one yourself with Claude Code assisting, not the other way round.
It is the thing people read first.

Problem, architecture diagram, key decisions with rationale, what you
measured, demo. Your Decisions Log is already most of the raw material —
it is genuinely stronger than most portfolio repos have.

Lead with the loop: ideas grounded in your own performance data, one
generated clip where the footage runs out, measured selection rates.

---

## Rules for every session

- One session per section. Long sessions degrade — context fills with dead
  ends and it starts contradicting earlier decisions.
- Plan mode for anything spanning more than one file. Skip it when you could
  describe the diff in one sentence.
- Read every diff before committing. Every one.
- Conventional commits, one concern each.
- If Claude proposes something not in the spec, say no and ask it to raise
  it instead.

## If a session goes sideways

```bash
git reset --hard HEAD    # discard uncommitted work
git checkout .           # or just the working tree
```

You are on a branch. Throwing away a bad session costs nothing. Untangling
one costs an afternoon.
