# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

An automated video production pipeline for Zero Page Films (a one-person brand), mixing real
footage and AI and aimed at running more of itself over time. It generates concepts and shot
lists from described real rooms, decides shot by shot what gets captured versus AI-generated,
writes platform-native AI video prompts, plans cuts from ingested footage, and feeds
posted-video analytics back into the next slate. The autonomy ladder: L1 assisted -> L2
grounded generation + measurement -> L3 self-improving ideation -> L4 supervised
generate-and-post (gated, default off). Editing stays manual — an explicit L1 hold.
Experimental — the loop is structurally in place but needs weeks of real use to mean anything.

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

# THE LOOP (L2 -> L3) — analytics into the next slate
venv/bin/python -m src.promote_winners propose|approve|reject|run     # winners -> proven_results shelf
venv/bin/python -m src.rework [--count 6] [--brand ...]               # evidence-grounded next slate

# AUTOPILOT (L4) — OFF by default; dry-run unless env+approve+no kill switch align
venv/bin/python -m src.autopilot plan|run|kill

# SCHEDULED PUBLISHING — the queue cron invokes; publishes only through the autopilot gate
venv/bin/python -m src.scheduling list
venv/bin/python -m src.scheduling run [--approve] [--live]

# REFERENCE LIBRARY (RAG) — optional grounding for pitch.py
venv/bin/python -m src.rag ingest <files...>        # (re-)build the pgvector library
venv/bin/python -m src.rag query "<text>" [--k 5]
venv/bin/python -m src.rag_eval <cases.json> [--k 5]   # hit@k + MRR over labeled cases

# WEB APP — one page at 127.0.0.1:8000/studio does everything above.
# 127.0.0.1:8000 is the public landing (the only indexed URL).
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
  at once, what the web app's main button uses). `validate_concept` advises (never blocks): shot
  `type` in `CHARACTER`/`BROLL`, per-shot `source` in `CAMERA`/`AI`, camera shots' `cam` in
  `BMPCC`/`ACTION5`, AI shots' `tool` in the `shot.PLATFORMS` registry with a non-empty prompt,
  and — the one that matters — that every shot's `location` is a described space. Everything is
  a visible warning on a saved concept; nothing is rejected, and no shot-count cap exists. No
  described locations degrades to an ungrounded run with a stderr note, same as a missing
  reference library. `apply_pov(template, use_pov)` is why the POV toggle is real: off rewrites
  the prompt so `ACTION5` is never offered *or* named as legal, and `validate_concept` flags it
  if the model reaches for it anyway. Ideation is also reference-grounded, the same
  way `pitch.py` is: `reference_block` (the *edge* helper — called from `main()` and the web
  routes, never from inside the generators) queries the RAG library with the spark, client, and
  the mood of the described rooms, and the generators take the resulting `references` string as a
  plain argument defaulting to `""`. That split is what keeps the generators hermetic in tests.
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
  (ordered clip in/out points, grade notes, sound notes). `validate_edit` advises: unknown clips,
  in/out points outside real clip duration, and total runtime outside `MIN_RUNTIME`/`MAX_RUNTIME`
  (13-17s) all surface as visible warnings on a saved edit. Any number of edit_list entries may be
  generative slots (`"source": "generate"` + description) — real and AI clips are co-inputs. `--print` renders each edit's cut list as plain text (clip, in,
  out, duration, running total) via `format_edit_as_text`, to read beside Resolve without parsing
  `concepts.json` by eye.
- **`src/shot.py`** / **`src/promptgen.py`** / **`src/genlog.py`** / **`src/generative.py`** — the
  generative-clip side, for the one shot per edit the footage can't cover. `shot.py` is a `Shot`
  dataclass with a controlled camera/size vocabulary and one **pure** renderer per tool; no model
  call goes near it. `promptgen.py` is the only place an LLM turns a loose description into a
  `Shot`. That split is deliberate: a bad prompt is then either a bad `Shot` (visible in the JSON,
  the model's fault) or a bad compile (catchable in a render test, the renderer's fault). Collapse
  it and you can't tell which broke. `genlog.py` records attempts after you generate in the tool's
  own UI; `generative.py` holds `shots`/`generations` and the scoreboards. **Verification is per-map:** each camera map carries a dated comment naming the guide it was
  checked against (Veo/Seedance/LTX/Wan dated 2026-08-04 from the local video-prompting skill
  references); `RUNWAY_CAMERA` and `KLING_CAMERA` remain undated general patterns — check those
  tools' guides before trusting their wording.
- **`src/youtube.py`** — video-id parser for `watch?v=`/`youtu.be`/`shorts` URLs (the part that
  actually breaks), public stats via the Data API v3, and channel import. `refresh_metrics_for_video`
  and `import_channel_videos` never raise: a missing key or failed call returns `{"ok": False}` so
  manual entry keeps working, per BUILD_SPEC.
- **`app/main.py`** — the web app; every CLI step above is also doable in the browser. **The app
  is one page.** `/studio` is the workspace: a left rail of what you have (media pool, rooms +
  add-a-room, library shelves, escape-hatch tool links), a canvas of what you've made (concept
  cards, cut lists, the performance strip), and an assistant on the right. The per-stage screens
  (`/concepts`, `/locations`, `/library`, `/analytics`, `/pitches`) still exist as the engine and
  each links back to `/studio`; `/dashboard` is gone (308 → `/studio`, since it was the front door
  for months). Inline actions pass `next` so a decision made on the canvas lands back on the
  canvas — `safe_next` refuses anything that isn't a site-relative path, or every button becomes
  an open redirect. `/locations` serves photos through `location_photo`, which resolves both path
  segments and refuses anything that escapes `locations/` — a space name becomes a directory name,
  so it's sanitised on the way in too. `?thumb=1` serves a cached 480px JPEG rather than the
  multi-megabyte original. Routes that call a model wrap it and redirect with a message rather
  than 500ing.
- **The assistant is keyword routing, not a model call.** `route_intent` matches typed text (or an
  explicit chip) against `INTENT_PHRASES` → one pipeline stage, falling back to `ideas`. Free and
  inspectable on purpose: the stages it dispatches each cost a billed generation, so an unclear
  ask must not spend one on the wrong stage. Stages the browser can't run (a cut list needs
  ingested footage and a pitch run) say what to run instead of pretending.
- **`app/seo.py`** — the machine-readable growth surface, all pure functions so the exact bytes a
  crawler sees are testable without a server: `robots.txt` (the AI crawlers named explicitly and
  allowed; the app disallowed), `llms.txt` (what "grounded" means plus the hard specs — the part
  worth citing), `sitemap.xml`, and the homepage JSON-LD `@graph`
  (Organization + WebSite + SoftwareApplication, **no** `Offer` — nothing is for sale yet).
  `PUBLIC_PAGES` is the single list all three read, so they can't drift apart. Everything is built
  from `SITE_URL` (default `http://127.0.0.1:8000`) — set it before the site goes public or every
  canonical tag points at localhost. `/` is the only indexed URL; every app template carries
  `noindex`.
- **`src/rag.py`** / **`src/rag_eval.py`** — the reference library. Text files are chunked at
  word boundaries, embedded with `gemini-embedding-001` (768 dims — documents as
  `RETRIEVAL_DOCUMENT`, queries as `RETRIEVAL_QUERY`; the model is asymmetric and mixing them
  quietly worsens ranking), stored in PostgreSQL + pgvector (`RAG_DATABASE_URL` or `DATABASE_URL`, default
  `postgresql://localhost/zeropage`). Every row carries a required `domain` shelf label plus
  optional `project`/`source_ref`, and queries can scope on them (`--domain`, `--project`) —
  semantic similarity and hard SQL filters in one query. Deliberately not in `data/pipeline.db`: SQLite has no
  vector type, and the library is rebuildable from its sources. Re-ingesting a source replaces
  its chunks, keyed by `source_key(path)` — the path relative to the project root, **not** the
  basename. That matters for a folder tree of references: keyed by basename,
  `references/editing/notes.txt` and `references/lighting/notes.txt` are one source that deletes
  itself on every ingest. Two consumers inject into a prompt's `{references}` section: `pitch.py` queries with
  the manifest's beats/arcs, `shootgen.py` with the spark plus the mood of the described rooms.
  `retrieve_references` never raises, so no Postgres means an ungrounded run with a stderr note,
  not a dead one. The `rag` CLI fails loudly — there
  the store is the deliverable. `rag_eval.py` scores retrieval (hit@k, MRR) against a labeled
  JSON case file, judged at document level, sources deduplicated before ranking. **Note:**
  psycopg/libpq connects below Python's socket module, so `tests/conftest.py`'s network guard
  cannot catch a stray Postgres connection in tests — anything touching the store must patch
  `rag.connect` (or above) explicitly.
- **`src/post_seo.py`** / **`src/promote_winners.py`** / **`src/rework.py`** — the L2→L3 loop.
  `post_seo` derives winning/losing traits (topics, hooks, title words) at the comparison-window
  median, equal-age, and `score_post` grades a draft with reasons that cite the evidence — pure
  against SQLite, so a hundred drafts cost nothing. (Two "seo"s on purpose: `app/seo.py` is the
  site's crawler surface; this scores *posts*.) `promote_winners` proposes/approves winners onto
  the RAG `proven_results` shelf, docs now carrying the window's patterns; `rework` proposes the
  next slate from those signals + shelf (CRAG-graded retrieval), each idea carrying an "evidence"
  sentence, saved as ordinary concept ideas so the pick stays the measured label.
- **`src/autopilot.py`** — the L4 scaffold, where the contract is the gate: nothing executes
  unless `ZEROPAGE_AUTOPILOT=1` AND a per-run `--approve` AND no `data/autopilot.off` kill switch
  all align; anything less is a dry run that describes every action. The `generate` executor is
  a deliberately unwired registration point; `post` is wired to `instagram.execute_post_action`
  but only ever runs in live mode and refuses without `IG_USER_ID`/`IG_ACCESS_TOKEN` — the gate
  above it is unchanged. `build_plan` emits a `post` action only when a concept's shot carries a
  rendered `media_url` (the plan never invents deliverables).
- **`src/instagram.py`** — the Meta Graph publish + insights module, youtube.py's shape exactly:
  thin raising wrappers (container create/status/publish, `publishing_limit`, insights) under
  never-raising edges (`post_reel` walks create → poll-until-FINISHED → publish, never publishing
  an unprocessed container; `refresh_metrics_for_video` guards platform/token, maps insights →
  `db.record_metrics`, `saved`→`saves`). `_safe_error` redacts the token from every error that
  could reach a page or a db row. `VERSION` and `REEL_METRICS` are single dated constants —
  insight metric names shift between Graph versions, so verify on bump. A `/reel/<shortcode>`
  permalink does **not** contain the numeric media id; store `ig://<media_id>` (or the raw id) in
  a video's url for refresh to work, or pass a `media_id` key. Token refresh (long-lived tokens
  expire ~60 days) is a noted follow-up, not built.
- **`src/scheduling.py`** — the publish queue, because Meta has no native future-scheduling: a
  `scheduled_posts` table (own `SCHEMA`/`init()`, the preprod.py pattern), pure `due_posts`
  windowing, and `run_due`, the worker step cron invokes. Queue management is ungated — rows are
  intentions; the publish itself always goes through `autopilot.execute`, so gate/dry-run/kill
  switch apply unchanged and there is no second posting path. Idempotency: a row is marked
  `publishing` *before* dispatch and `publishing` rows are excluded from `due_posts`, so a crash
  can't double-post — a stuck row is visible in `list` and resolved by hand. `DAILY_CAP` (20)
  sits well under Meta's 100/24h quota, which is also checked live and treated pessimistically
  (unverifiable = don't post). `build_caption` grounds captions in `post_seo.derive_signals` and
  picks the best of several candidates by `score_post` (pure, free), degrading to the fallback
  caption on any failure.
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
- **Prompts request, code advises.** Model output is always independently checked against
  reality — real filenames and durations for edits, described location names for concepts — and
  every mismatch surfaces as a visible warning on a saved result. Nothing is rejected: the
  checks exist because models hallucinate clip references, cut points and rooms, and the human
  deciding needs to see that, not because output "doesn't count" until it validates.
- **Grounded in what exists — grounding shapes, it doesn't gate.** Every stage generates *from*
  real material: concepts from photographed spaces, edits from the manifest, AI prompts from the
  named real room they extend, ideation from the reference library and proven winners. That is
  what keeps output shootable and on-brand. A mismatch is a warning, and a missing grounding
  source degrades to an ungrounded run with a note.
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
calls. One location described from real photos, 23 concepts (5 with shot lists), 1 pitch run with
10 ideas and 3 picked, 1 posted video with one metric snapshot. Reference-grounded ideation is
verified live both ways: `src.shootgen --spark "gearing up ritual"` printed "Grounding in 5
retrieved reference(s)" against the real library, and the same command with the store pointed at
a dead URL printed the ungrounded note and still produced ideas (exit 0). 411 tests, ruff clean,
CI green on every push.

The one-page workspace was verified in the browser against the real database, not just by its
tests: the rail's four panels (36 clips, the described room with thumbnails, the two live library
chunks, the tool links), an idea card, a planned card with its 5 shots and AI slot, a cut list
with real filenames and its three validation checks, the performance strip (2 pitch runs, 20
ideas, 30% pick rate, 22% shortlist, 10 videos), and an assistant round trip. Three real defects
only showed up there: the rail's radios were `opacity:0; pointer-events:none`, which took the
tab controls out of the accessibility tree and off the keyboard entirely; `.wk-tool`'s title and
description were inline spans, so every tool read as "ROOMSPhotograph and describe a space"; and
the card and stat grids were sized for a wider canvas than the three-zone layout leaves.

**Structurally complete, statistically empty:** the L2→L3 loop is built and verified live —
`promote_winners propose` honestly reports nothing clears the bar (no videos measured at equal
age yet), and `src.rework` generates an evidence-free slate with the note. The rates
(`shortlist_rate`, `shoot_rate`, `selection_rate`) and `post_seo`'s signals are structurally
correct and currently meaningless — they need weeks of real posting before a prompt change can be
measured or a slate genuinely reworked from evidence. The most valuable next step is not code: it
is shooting one of the generated concepts, marking it shot, posting it, and recording metrics.
The de-cap is verified live: SHOOT-25 generated with 2 AI shots (WAN, RUNWAY) + 2 camera shots,
zero warnings, rendered on the studio canvas. L4 exists as `src.autopilot` — gated, dry-run,
default off, executors unwired.

**Known gaps, in rough priority:**
- `shot.py`'s `RUNWAY_CAMERA`/`VEO_CAMERA`/`KLING_CAMERA` maps and the AI-slot prompt phrasing are
  general patterns, not current documentation. Check each tool's prompt guide before relying on a
  generated prompt, and date the comment above each map.
- `YOUTUBE_API_KEY` in `.env` is a placeholder, so channel import and metric refresh can't reach
  the API. Everything else works without it.
- `import_channel_videos` can report success when the bulk stats call failed; `mark_kept` doesn't
  clear other keepers on the same shot, which skews `attempts_to_keeper`; `ingest.py` reads only
  `GEMINI_API_KEY` where every other module also accepts `GOOGLE_API_KEY`.
- The RAG store runs live on this machine via **Homebrew `postgresql@17`** (auto-starts at
  login through `~/Library/LaunchAgents/homebrew.mxcl.postgresql@17.plist`; database `zeropage`,
  data directory `/usr/local/var/postgresql@17`). No `DATABASE_URL` is set in `.env` — connections
  fall through to `rag.DEFAULT_DB_URL`, which is already `postgresql://localhost/zeropage`, so
  nothing needs setting on this machine; set `RAG_DATABASE_URL` to point elsewhere. There are no
  standalone vector files to back up: the embeddings are Postgres pages (TOASTed out of
  `rag_documents`, since 768 floats exceed the inline threshold). Use `pg_dump zeropage`, or just
  re-run `python -m src.rag ingest` — the library is rebuildable from its sources by design.
  Ingest, scoped query, and the eval harness are all verified against it with real embeddings.
  **The library is nearly empty and its eval scores are not yet evidence of anything.** It holds
  two chunks — `prompts/brief.txt` and `prompts/settings.txt` — so `eval_cases.json`'s hit@3 1.00 /
  MRR 1.00 over 2 queries is arithmetic, not retrieval quality: with 2 documents and k=3 every
  query retrieves the whole store. `prompts/edit_prompt.txt` was ingested early and has been
  removed: it is a prompt *template*, and retrieving `THE BRAND: {brief}` scaffolding as a
  "reference" to inject into another prompt is worse than no grounding. Don't re-add prompt
  templates; the library wants real reference material. Machines
  without a local Postgres can use the repo's `docker-compose.yml` instead. Note: Postgres.app
  is also installed but is an uninitialised PostgreSQL 18 that owns none of this data — do not
  "Initialize" it, it would contend for port 5432 with the server that actually has the library. The grounded
  `src.pitch` end-to-end run is still pending — next real pitch run exercises it.
- `/shots` and the tool scoreboard aren't built — they need real generation attempts logged
  through `genlog.py` first, and inventing that data would corrupt the only numbers that matter.

**The user's real data lives in `data/pipeline.db` (gitignored, ~128KB) and `locations/`
(gitignored, photos).** A fresh clone gets the tool, empty. Never overwrite either without asking.
