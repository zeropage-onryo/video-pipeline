# ZPF Studio — an idea spark to a finished video

Give it an idea. It generates several scenes to choose between, you shape the one you picked with
director notes until it's right, and it renders a finished video or image. One studio across six
generation platforms instead of six tabs and a notes app.

```
idea spark
    │
    ▼
several scenes generated off that one idea  ──── you pick one  (pick_rate)
    │
    ▼
director mode — one note at a time: "shot slower", "hold the reveal a beat longer"
    │
    ▼
prompt enhanced (Gemini 3 Flash)
    │
    ├──▶ Nano Banana Pro ──▶ keyframe you approve ──┐
    │                                               │
    └───────────────────────────────────────────────┴──▶ Runway ──▶ finished clip
                                                                        │
                                                                        ▼
                                                          posted ──▶ view counts
                                                                        │
                                                     feeds the next spark ┘
```

The keyframe is not a side branch: the enhanced prompt feeds both render nodes, and the approved
still feeds Runway's image port, so the clip starts from an image you already said yes to rather
than from text alone. A scene is one prompt and one shot — the render *is* the deliverable.

Every platform speaks a slightly different dialect — Veo wants one thing, Kling another, Seedance
another. Moving an idea between them by hand is where the time goes, and none of it is creative
work. This aggregates that: one controlled shot vocabulary in, platform-native prompts out, renders
dispatched through per-platform connectors, and every attempt logged so you learn which prompts land
in two tries and which take nine.

Ideas come from wherever they work best. **Zero Page** rides format skeletons — the structure that
travels — ranked by what's actually performing. **Antihero** grounds in real photographed rooms with
a recurring star. Either can draw on inspiration accounts, a retrieval library of your own writing,
or evidence from your own posted results. Grounding in your own material is a toggle, not a gate.

**Status: pre-launch.** Sign-in, accounts and capability gating work; it isn't open to other people
yet. See *Where this actually is*.

## What it does

https://github.com/user-attachments/assets/967a5d87-b345-404c-8d84-d72477798b9b


**Spark → scenes you choose between.** From an idea and a brand, several scenes are generated in a
single call — so the options are varied *against each other* rather than rolled independently — each
one a complete, paste-ready scene prompt with camera, framing, movement, lighting and diegetic
sound. Which one you pick is recorded (`pick_rate`), against the hash of the prompt that wrote it.

**Director mode — where a scene becomes video.** Two halves. The conversational half takes one note
in plain language — "shot 2 slower", "hold the reveal a beat longer", "move it to the bedroom" — and
revises the stored scene in place via Gemini 3 Flash, never regenerating it and never touching the
picked title, hook or logline. The canvas half renders it: the shot's prompt is enhanced, that
enhanced prompt feeds **Nano Banana Pro** for a keyframe, and the keyframe feeds **Runway** so the
clip starts from a still you already approved rather than from text alone. The reference image and
RAG retrieval ride on the backend rather than as extra nodes.

Two protections keep a note from destroying work: attached material survives a revision (a shot
keeps its `reference_image` and `media_url` unless the model explicitly returns new ones, so a
wording change can't detach a clip you already rendered), and broken output never lands — an
unparseable response, an empty shot list, or a plan that lost more than half its shots is an error,
and the stored scene stays exactly as it was.

**One vocabulary, six platforms.** Each shot carries a paste-ready, platform-native prompt — Veo,
Kling, Runway, Seedance, LTX, Wan — written from one controlled shot vocabulary, one renderer per
platform. Reference grounding and Extend Video sequence-chaining where the platform supports them.

**Renders, dispatched.** `runway.py`, `veo.py`, `midjourney.py` and `nano_banana.py` are gated
connectors sharing one shape: a daily cap, a cost estimate before the call, every attempt logged,
and a connector that isn't configured degrading with a stated reason rather than failing the run.
One click from the scene board.

**Every shot is generated.** There is no camera path any more. A shot's `source` records whether
real reference material anchors the generation — an acting take, a room plate, feeding the shot's
`reference_image` — not whether the shot escapes the pipeline. A reference is an enhancement, never
a gate, the same way RAG grounding is.

**It learns from your choices.** Which concepts you plan and which you actually make, each recorded
against the hash of the prompt that produced it — so a prompt change becomes something you measure
rather than argue about. Posted videos and their view counts feed back in, compared **at equal age**
so a year-old video can't win on accumulated totals. `rework.py` then ideates the next slate from
that evidence rather than from scratch.

**Brand-scoped.** Inspiration lanes are scoped per brand so grounding never leaks across them.

## The Studio

`/ui` is the product in a browser — FastAPI + Jinja2, no build step.

- **Composer** — upload references, pick rooms, characters and props from the front page, generate.
- **Scene board** — generate a scene, copy per-shot prompts, fire a render, attach clips back.
- **Assets gallery** — date-grouped media panel.
- **Holds** — every parked run with a human-readable reason, graded approved / rejected.
- **Jobs** — long-running work streamed over SSE rather than polled.
- **Sign-in** — Supabase Auth (Google, Discord, email/password), verified server-side with PyJWT. The
  modal renders only the providers actually configured, so a missing client secret hides a button
  instead of breaking the page.

The JSON API behind it is capability-gated and derived live from real key presence, never a static
dict — a control only appears if the endpoint behind it can actually run.

## The rules the whole thing is built on

**Nothing spends a credit unscored.** Every generated prompt runs a two-layer judge: a zero-cost
structural check, then a strict LLM rubric that **fails closed**, so an unreadable verdict scores 0
rather than passing by default. All prompts in a run must pass or the run holds — no partial renders.

**Degrade, don't break.** A missing Postgres, an unconfigured connector, an absent described
location, a feature that hasn't landed — each degrades to a run that continues and says so. The
exceptions are deliberate: `promptgen` and `locations` fail loudly, because there the model call *is*
the deliverable rather than bookkeeping on top of one.

**Prompts request, code enforces.** Model output is checked against reality — described locations,
the shot vocabulary, the tool registry — and every mismatch surfaces as a visible warning on a saved
result. Nothing is rejected. Models hallucinate rooms and vocabularies, and the human deciding needs
to see that.

**Verify by running it.** Every real defect this project has had passed code review and passed its
own tests. They were caught by starting the server, clicking the thing, or noticing the suite had
quietly gotten slower.

## Judging quality

Four scorers, deliberately separate:

| Module | Judges |
|---|---|
| prompt gate (`orchestrator`) | Is this prompt well-formed enough to spend a credit on? Subject / camera / motion / lighting / coherence, 0–2 each, against `PROMPT_GATE_MIN`. Fails closed. |
| `uncanny_judge.py` | The on-brand gate. A **fixed** rubric, so it works from day one — before there's any history to learn from. This is what would make a channel safe on autopilot. |
| `taste_judge.py` | Scores against **this creator's own record** — what they approved and rejected on `/holds`, what they marked worked, the traits of their winning versus losing posts. Predicts "they'll like this." |
| `quality.py` | Faithfulness and answer relevancy over retrieved context, via DeepEval's LLM-judge metrics on the same Gemini models the pipeline already uses. |

Kept separate because a prompt can be structurally excellent and tonally wrong, or perfectly
on-brand and generically bad. One collapsed score makes failures non-diagnostic. `evalstore.py`
persists them, so quality is a trend rather than a vibe.

## Running it

```bash
venv/bin/pip install -r requirements.txt && venv/bin/pip install -e .
venv/bin/uvicorn app.main:app --reload   # the Studio, in the browser
```

Needs `GEMINI_API_KEY` in `.env`. Optional: `YOUTUBE_API_KEY` (public view counts, channel import),
OAuth client credentials for sign-in, and per-platform render keys. Each absent key disables its
feature with a stated reason rather than breaking startup.

Every step also has a CLI — `python -m src.locations`, `src.shootgen`, `src.promptgen`,
`src.director`, `src.genlog`, `src.orchestrator`, `src.trigger`, `src.rework`, `src.autopilot`,
`src.scheduling`, `src.accounts`. See `CLAUDE.md` for the full list.

## Reference library (RAG)

Text you want the writing to learn from — brand notes, past scripts, films-you-admire notes,
platform prompting references — chunked, embedded with `gemini-embedding-001` (documents and queries
embedded with different task types, because the model is asymmetric), and stored in PostgreSQL +
pgvector. At generation time the spark, brand and mood become the query, and the closest chunks are
injected as tone and structure references. Retrieval is CRAG-graded (`crag.py`): a weak first pass
earns one query rewrite rather than being silently used. No Postgres? The run continues ungrounded
and says so.

Every production CRAG decision is logged without storing reference text: initial and retry scores,
whether a retry ran, whether it improved the score, whether it was adopted, and the threshold plus
reference-library fingerprint used at the time. The private `/studio` Stats view shows that product
telemetry; `/ui` uses the same retrieval path but never exposes the internal diagnostics.

Every successful Nano Banana image and Runway video is also published to `/ui`'s Asset Bank with
its exact prompt, provider/model, media type, and available scene metadata. Nano images remain
selectable as later image references; Runway clips appear in the gallery but stay out of image-only
pickers. The prompt and model description are indexed on the RAG `assets` shelf, while a temporary
vector-store failure never discards the completed render or its local Asset Bank record.

```bash
docker compose up -d                       # Postgres + pgvector

venv/bin/python -m src.rag ingest prompts/brief.txt --domain personal_brand
venv/bin/python -m src.rag query "stillness broken once" --k 5
venv/bin/python -m src.shootgen --spark "gearing up ritual"   # picks up references on its own

venv/bin/python -m src.rag_eval eval_cases.json --k 5         # hit@k, MRR against labeled cases
```

The Dev Studio eval run uses the same golden questions twice: once with one-shot retrieval and once
through the complete CRAG rewrite path. It reports base versus CRAG Hit@k/MRR, re-query rate, how
often retry scores improve, how often retries are adopted, and whether retries actually return a
human-labelled expected source. A lower re-query rate is not treated as success by itself: it must
hold or improve retrieval accuracy. Runs record the query-set fingerprint, embedding/rewrite model,
threshold, and reference-library count/fingerprint so unlike configurations are not presented as
equivalent comparisons.

Every chunk carries a required `domain` shelf label, so queries can scope semantically and by hard
SQL filter in one pass. Re-ingesting a source replaces its chunks, keyed by path relative to the
project root — not basename, or `editing/notes.txt` and `lighting/notes.txt` would delete each other.

## Tested in CI

Every push runs `pytest` and `ruff`, then an eval gate that stands up an ephemeral Postgres +
pgvector, re-ingests the library, and runs two gates kept separate so each failure is diagnostic:

- **Retrieval regression** — hit@5 and MRR against floors.
- **Generation quality** — a 14-case golden set scored on faithfulness, answer relevancy, contextual
  precision and recall, each against an absolute floor *and* a regression band versus recorded
  baselines.

`tests/conftest.py` blocks all network access during tests, because the same bug landed four times:
a test patches one generator, the route changes to call a different one, the patch silently misses,
and a real billed API call happens while the test still passes.

The run history is public in the Actions tab, failures included — a judge-model timeout that clipped
three golden cases, a `deepeval` pin after 4.1.10 dropped Python 3.9, a CI-only failure from an
unstubbed client.

## Tech stack

Python · FastAPI + Jinja2 · SQLite (spaces, concepts, scenes, videos, metric snapshots, generation
attempts) · PostgreSQL + pgvector (retrieval library) · Google Gemini — vision, structured
generation, embeddings, **Gemini 3 Flash** for enhancement and director notes, **Nano Banana Pro**
(`gemini-3-pro-image-preview`) for keyframes · LangGraph + LangSmith (orchestration and tracing) ·
DeepEval (judge metrics) · Runway / Veo / Midjourney connectors · Instagram + YouTube metrics ·
Cloudflare R2 · ffprobe · Supabase Auth · pytest + ruff in CI · Docker Compose

## Where this actually is

Being straight about the state, because the code will tell you anyway:

- **Not launched.** Sign-in and capability gating work, but a fresh signup gets zero membership rows
  and sees "no account access yet" — membership is granted by hand for v1. Nobody outside has an
  account.
- **No tenancy yet.** Owned tables have no `account_id`, and the render caps are global rather than
  per-account. That's the actual blocker to a pilot, scoped in `docs/tasks/task-account-tenancy.md`.
- **The posting line is deliberately stubbed.** `generate_render` only calls a real renderer when
  explicitly enabled; no posting API is wired, so even a channel set to `auto` parks with an explicit
  reason rather than pretending to post. Instagram and TikTok stats stay manual until developer
  approvals land.
- **A scene is the unit, not a cut.** One scene is one prompt and one shot, so its render is a
  finished deliverable. Stringing several scenes into a longer edit is still done by hand in Resolve
  — the timeline assembly was removed deliberately, see the Decisions Log.
- **The measurement loop is structurally complete and statistically empty.** The rates and signals
  are correct and currently meaningless; they need weeks of real posting before a prompt change can
  be measured rather than argued about.

## Roadmap

- Account tenancy, then a closed pilot — `docs/tasks/task-account-tenancy.md`
- Open sign-ups
- The tool scoreboard — which platform lands which shot type, once enough attempts are logged
- Verify per-tool camera vocabulary against each platform's current prompt guide
- Case-study writeup with a demo video

## Architecture

Two paths, deliberately different. The **request path** is what runs when you press Create — a
straight line, because a person is standing there waiting for it. The **autonomous path** is the
unattended nightly run, with gates the request path doesn't need.

Both are documented in **[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)**, along with the two known
divergences between them.

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

**2026-08-11 — Documented the LangGraph orchestrator as a first-class architecture section.**
The graph in `src/orchestrator.py` was previously explained only in `CLAUDE.md`, written for
an assisting coding agent rather than a reader of this repo. Added an "Architecture — the
LangGraph orchestrator" section to this README plus a rendered node/edge diagram at
`docs/architecture.html`, describing the grounding-and-retry loop, the two-layer prompt
credit gate, the deliberately stubbed posting line, and the shared hold sink. Reason: the
graph's shape *is* the autonomy story — how much currently runs unattended versus what's
still gated — and that was previously implicit in code rather than legible on its own.
Nothing in the graph itself changed.

**2026-08-11 — Synced this README to the post-production removal.**
`CLAUDE.md` already documented that post-production (ingest → pitches → cut lists) was cut
from the product in August 2026, but this README's intro, "What it does," Pipeline diagram,
Running-it command list, and Reference-library section still described it as live —
`src.ingest`/`src.pitch`/`src.editgen` commands that no longer exist, a two-column
pre/post-production diagram, and RAG examples grounding "pitches" instead of concepts.
Rewrote all of it to the current single-phase pipeline: photograph a space, generate a
grounded concept and shot list, shoot it, post it, feed the metrics back. The edit still
happens by hand in Resolve — that was already true, just no longer framed as one stage of
two. No code changed; this brings the docs in line with what Aug 2026 already did.

**2026-08-11 — Fixed a CI-only failure in `test_judge_parses_fenced_json_and_clamps_dims`.**
The test mocked `generate_with_retry` but not `_client`, so `_judge_prompt` built a real
`genai.Client()` before ever reaching the mock. That construction is harmless locally
(`.env` has a real `GEMINI_API_KEY`) but raised in CI's `test` job, which deliberately has
no key — only `eval-gate` gets one, gated behind a real secret. `_judge_prompt`'s fail-closed
`except` swallowed the exception and returned `dims={}`, which the test's
`verdict["dims"]["camera"]` lookup then hit as a `KeyError`. Every other orchestrator test
avoids this by stubbing `_client` through the shared `tmp_db` fixture; this one test skipped
that fixture entirely and needed its own stub. Passed locally, failed in CI — a genuine
"trust the log, not the assumption" case, same spirit as the Verify-by-running-it rule
above. No production code changed, only the test.

**2026-08-20 — Every shot is generated; the camera path is gone.** The pipeline was built on real
and AI shots as co-inputs, each shot carrying `source: CAMERA | AI` to say which one it was. That
mix is retired. Every shot is now AI-generated, and `source` was repurposed rather than removed: it
records whether real reference material anchors the generation — an acting take, a room plate,
feeding the shot's `reference_image` — not whether the shot escapes the pipeline. A reference is an
enhancement, never a gate, exactly as RAG grounding is. Reason: the mix was the last thing forcing
the product to be about one operator with two cameras and a house. Cutting it is what let the
identity become an aggregator for generating concepts and video, which is the shape someone other
than me could use. Cost: the "real material grounds everything, AI extends it" story, which was
distinctive and is now simply untrue. Accepted. Direct consequence: Director mode grew a rendering
half — enhance the shot prompt with Gemini 3 Flash, generate a Nano Banana Pro keyframe, feed that
keyframe to Runway so the clip starts from an approved still instead of from text.

**2026-08-27 — From "a solo filmmaker's grounded pipeline" to a multi-platform generation studio.**
This README described a one-operator, CLI-first pre-production tool whose central rule was that
everything is grounded in photographed rooms. Twenty commits since 2026-08-11 made that wrong in
both halves. What shipped meanwhile: the **ZPF Studio** UI (`/ui`, capability-gated JSON API, jobs
over SSE, an eval store), **real sign-in** (Supabase Auth: Google, Discord and email/password) and
an accounts model, **gated render connectors** for Runway, Veo, Midjourney and Nano Banana, the
**scene board** and **director mode**, **brand-scoped inspiration lanes**, and **opt-in asset
grounding** — which demoted grounding from the thesis of the product to a toggle on it. The clearest
evidence the old framing had expired is `format_feed.py`, which states outright that Zero Page rides
format skeletons, *not* rooms. The identity that replaced it: an aggregator for generating content
concepts and videos across platforms, where grounding in your own material is one available input
rather than the precondition. Also newly documented: the four separate scorers (prompt gate,
`uncanny_judge`'s fixed on-brand rubric, `taste_judge`'s learned-from-history rubric, `quality.py`'s
DeepEval metrics), which were doing significant work while going unmentioned entirely. Cost: the
grounding story was the sharpest thing about the old README, and the new framing is broader and
therefore less pointed. Accepted, because a sharp description of the wrong product is worse than an
accurate description of the right one. No code changed.

**2026-08-27 — Recorded the tenancy gap rather than quietly shipping around it.** Adding sign-in
made it read as though the product were multi-user. It isn't: `list_concepts` and `get_concept` carry
no owner predicate, `shoot_concepts` has no `account_id`, and the render caps count globally rather
than per account — so a second user would see the first's work and exhaust their daily budget.
Written up as `docs/tasks/task-account-tenancy.md` and stated plainly in the README's "Where this
actually is" instead of being left for a reader to discover. Reason: the repo is public and linked
in job applications; an OAuth flow and an SEO module imply a live product, and being first to say it
isn't costs nothing while buying credibility for everything else on the page. Same instinct as
logging removals — the honest state of a thing is more useful than the flattering one.
