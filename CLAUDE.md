# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

An AI pre-production studio for Zero Page Films (a one-person brand), aimed at running more of
itself over time. It generates concepts and shot lists from described real rooms, decides shot
by shot what gets captured versus AI-generated, writes platform-native AI video prompts, and
feeds posted-video analytics back into the next slate. The autonomy ladder: L1 assisted -> L2
grounded generation + measurement -> L3 self-improving ideation -> L4 supervised
generate-and-post (gated, default off). Editing stays manual — an explicit L1 hold.
Post-production (footage ingest -> pitches -> cut lists) was cut in Aug 2026: the product is
the pre-production loop, and the edit happens by hand in Resolve.
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

# 0c. Or one run through the autonomous content graph (LangGraph). No CLI --
#     call it: grounds in cast+library (CRAG), generates, evaluates (JUDGE=1
#     adds the LLM-judge), retries with issues folded into the spark, then
#     PARKS in autonomy.hold_queue -- render/publish are stubs until the
#     credit gate clears. LANGSMITH_TRACING=true traces; `langgraph dev`
#     (venv-studio/) serves it to Studio as "zeropage".
venv/bin/python -c "from src import orchestrator; print(orchestrator.run('gearing up ritual'))"
venv/bin/python -c "from src import autonomy; print(autonomy.list_hold())"      # the dead-man log

# THE NIGHTLY TRIGGER — one shadow run, spark rotated from prompts/sparks.txt.
# ops/com.zeropage.shadowrun.plist schedules it at 03:30 (see its header to
# install); grading happens on /holds each morning.
venv/bin/python -m src.trigger [--spark ...] [--channel zeropage]

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

# REFERENCE LIBRARY (RAG) — optional grounding for ideation
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

Requires `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) in `.env` for shootgen/promptgen and
locations' vision step. `YOUTUBE_API_KEY` is optional — it enables auto-fetching
public view counts and importing a channel's videos; without it manual entry still works.

## Architecture

One phase, before the shoot: everything reasons about **spaces you have**. State lives in
SQLite (`data/pipeline.db`).

```
locations/<name>/*.jpg  --locations.py-->  locations table (vision description per space)
                                                  |
                            shootgen.py ideas <---+  (+ brand, spark, POV on/off)
                                                  |
                                    shoot_concepts rows, shots = []   <-- cheap ideas
                                                  |
                            shootgen.py --shotlist <id>   (human picks: THE LABEL)
                                                  |
                                    same row, now with <=6 shots, AI shots, edit, grade
                                                  |
                                         [ you go shoot it ]  -> shot_done (SECOND LABEL)
```

**Two-stage on purpose.** Generate cheap options, a human picks, and only the picks get
expensive detail — `generate_concept_ideas`→`generate_shot_list`. The pick is recorded
(`shoot_concepts.shots != []`), which is what makes a prompt change measurable rather than
arguable. `shootgen` can still produce one full concept in a single call (`generate_concept`)
— that's what the web app's main button does — and `src/graph.py` wraps that single-call path
in a LangGraph evaluate-and-retry loop.

Post-production (ingest -> pitch -> editgen, the manifest.json/pitches.json/concepts.json
chain) was removed in Aug 2026. The pipeline's output is a shot plan you go shoot; the edit
is yours, in Resolve, by hand.

- **`src/locations.py`** — scans `locations/<name>/`, sends each space's photos to Gemini vision,
  stores `{space, light_sources, textures, angles, constraints}` per location. Incremental: a
  space already described is skipped unless `--force`.
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
  if the model reaches for it anyway. Ideation is reference-grounded:
  `reference_block` (the *edge* helper — called from `main()`, the web
  routes, and the orchestrator, never from inside the generators) queries the RAG library
  (scoped to `IDEATION_DOMAINS`, never `ai_prompting`) with the spark, client, and
  the mood of the described rooms, and the generators take the resulting `references` string as a
  plain argument defaulting to `""`. That split is what keeps the generators hermetic in tests.
- **`src/preprod.py`** — `locations`, `shoot_concepts`, `concept_locations` tables. Extends
  `db.py` in its own module (own `SCHEMA`, own `init()`), same pattern as `generative.py`.
  Two labels, not one: `shortlist_rate()` is which ideas were worth planning (derived from
  `shots != []`, never stored, so it can't drift), `shoot_rate()` is which ones actually got shot.
  Both break down per prompt hash.
- **`src/orchestrator.py`** — the autonomous content graph (LangGraph, registered as `zeropage`
  in `langgraph.json`): `planner -> ensure_locations -> ground_entities -> ground_rag ->
  gen_concept -> evaluate -> structure_prompt -> score_prompts -> generate_render ->
  qc_clip -> caption -> publish`, with the corrective `evaluate -> gen_concept` retry edge and
  a `hold` sink. `score_prompts` is the credit gate proper: a deterministic floor (thin /
  leftover template tokens, zero model calls — **no upper length bound**, removed 2026-08-14:
  a 130-word ceiling never fired across the first 17 scored prompts while six of eight judge
  failures were too *little* detail, and length is a quality judgment the judge's `coherence`
  dimension owns, not a broken-output signal this layer should reject on) under a strict LLM judge
  (subject/camera/motion/lighting/coherence, 0–2 each, bar `PROMPT_GATE_MIN`, default 7/10)
  that **fails closed** — an unreadable verdict scores 0, so a credit is never spent on a
  judgment nobody could read. One failing prompt holds the whole run, reason = the judge's own
  one-liner. Every score is a `prompt_scores` row logged before any spend; grading a hold on
  `/holds` writes the human verdict next to the gate's, and `autonomy.prompt_gate_agreement`
  splits disagreement by cost (passed-but-rejected burns a credit; held-but-posted only costs
  an approval — drive the first near zero before lowering the bar, on 20–30 graded rows, not a
  handful). The
  left third is the original evaluate-and-retry loop unchanged: the evaluator combines
  shootgen's code-enforced `warnings` with an optional LLM-judge (`JUDGE=1`, floor `JUDGE_MIN`,
  never blocks); failed critiques fold into the spark and regenerate up to `MAX_ATTEMPTS`, and
  every attempt is a saved concept row. `ground_entities` formats the picked (or all)
  characters/props into `{cast}`; `ground_rag` is CRAG-graded retrieval (weak first pass gets
  one query rewrite) that degrades to ungrounded. **The right two-thirds is deliberately
  stubbed:** `generate_render` returns no clips until the credit gate is cleared (first-try
  prompt acceptance), `publish` posts nowhere — every run ends as a row in
  `autonomy.hold_queue` with its reason. Tests drive the compiled `GRAPH` hermetically and the
  publish gates directly.
- **`src/autonomy.py`** — channels / hold_queue / corrections / settings on the shared SQLite
  DB (the preprod.py pattern). Autonomy is **per-channel** (`shadow` | `queue` | `auto`), both
  channels seed as `shadow`, and promotion is a one-row `set_autonomy` change. The kill switch
  is global (a `settings` row or `ZEROPAGE_KILL=1`) and forces every run to hold. `hold_queue`
  doubles as the dead-man log — every graph run writes a row — and morning approve/reject via
  `resolve_hold` feeds `evaluator_agreement`, the credit-gate number (~0.9 is the bar for
  promoting a channel). `_post_gate` in the orchestrator is the last code-enforced check:
  clips QC'd, caption non-empty, no warnings, under the channel's `rate_cap`. `/holds` is the
  control room: grade runs, promote/demote channels, toggle the kill switch, and drop a note —
  pending `corrections` fold into the next generation's spark and are consumed (each note
  steers exactly once).
- **`src/veo.py`** — the Veo connector (same SDK + key as everything else). `generate_video`
  is the thin raising wrapper (submit → poll → download immediately; Google keeps files ~2
  days); `generate_candidates` is the never-raises edge: N candidates, every attempt a
  `generations` row (the data `attempts_to_keeper`/`tool_scoreboard` read), **nothing ever
  auto-kept** — the pick is the label. Guardrails live in the module: a DB-enforced
  `VEO_DAILY_CAP` (default 6/day) and `estimate_cost` so every dry-run preview prices the plan.
  Reached two ways, both gated: the graph's `generate_render` only when `ZEROPAGE_RENDER=1`
  (unadapted tools — KLING/RUNWAY/... — honestly stay dry), and `autopilot.EXECUTORS["generate"]`
  only in live mode through the full L4 gate. Config verified against the *installed*
  google-genai (2026-08): `duration_seconds`, not the docs snippet's `duration`.
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
  is one page.** `/studio` is the workspace: the Workflow library of what you have (characters,
  rooms, props — real DB rows), the canvas, and the assistant. The per-stage screens
  (`/concepts`, `/locations`, `/library`, `/analytics`, `/characters`, `/props`) still exist as
  the engine; `/pitches` went with post-production, and `/dashboard` is gone (308 → `/studio`,
  since it was the front door for months). Inline actions pass `next` so a decision made on the canvas lands back on the
  canvas — `safe_next` refuses anything that isn't a site-relative path, or every button becomes
  an open redirect. `/locations` serves photos through `location_photo`, which resolves both path
  segments and refuses anything that escapes `locations/` — a space name becomes a directory name,
  so it's sanitised on the way in too. `?thumb=1` serves a cached 480px JPEG rather than the
  multi-megabyte original. Routes that call a model wrap it and redirect with a message rather
  than 500ing.
- **The assistant is keyword routing, not a model call.** `route_intent` matches typed text (or an
  explicit chip) against `INTENT_PHRASES` → one pipeline stage, falling back to `ideas`. Free and
  inspectable on purpose: the stages it dispatches each cost a billed generation, so an unclear
  ask must not spend one on the wrong stage.
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
  itself on every ingest. `shootgen.py` injects into a prompt's `{references}` section, querying
  with the spark plus the mood of the described rooms.
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

- **Prompts and brand brief are plain text in `prompts/`, not hardcoded strings.** They're the
  highest-frequency edit surface in this system; treat `{brief}`, `{settings}`,
  `{locations}`, `{cast}`, `{brand}`, `{client}`, `{spark}`, `{count}`, `{references}`,
  `{title}`/`{hook}`/`{logline}`, and `{pov}`/`{cam_rule}`/`{cam_values}` as the templating
  placeholders when changing prompt files.
- **Prompts request, code advises.** Model output is always independently checked against
  reality — described location names, the shot-source vocabulary, the tool registry — and
  every mismatch surfaces as a visible warning on a saved result. Nothing is rejected: the
  checks exist because models hallucinate rooms and vocabularies, and the human
  deciding needs to see that, not because output "doesn't count" until it validates.
  (The orchestrator adds one twist: it *uses* the warnings to retry, but the saved result
  still carries them.)
- **Grounded in what exists — grounding shapes, it doesn't gate.** Every stage generates *from*
  real material: concepts from photographed spaces, AI prompts from the
  named real room they extend, ideation from the reference library and proven winners. That is
  what keeps output shootable and on-brand. A mismatch is a warning, and a missing grounding
  source degrades to an ungrounded run with a note.
- **The human choice is the label, and it gets recorded.** `shootgen.py` generates ideas, a human
  plans some (`shortlist_rate`), and shoots fewer still (`shoot_done`). Stored with the prompt's
  hash, so a prompt change can be measured against the rate it produced rather than argued about.
  That selection is also the only manual gate.
- **Anything that calls a model degrades instead of breaking.** A missing API key or a failed call
  returns a result the caller can report, not an exception that takes the page or the run with it
  — `/metrics/new` still accepts typed numbers, `/concepts`
  still renders. The exceptions are deliberate: `promptgen` and `locations` fail loudly, because
  there the model call *is* the deliverable rather than bookkeeping on top of one.
- **Verify by running it, not by reading it.** Every real bug this project has had — a `warnings`
  string shattered into 140 single-character warnings, CI dying on torch's CUDA build, two tests
  passing only because the dev machine had a populated database, a site with no navigation between
  its own pages, tests quietly making billed API calls — passed review and passed its own tests.
  Each was found by starting the server, clicking the thing, or noticing the suite got slower.

## Where the project stands

Everything below is current as of the last commit on `main`. Update it when it stops being true.

**Working and verified against real data:** the pre-production loop runs end to end, including
real Gemini calls. One location described from real photos, 50+ concepts (5+ with shot lists),
1 posted video with one metric snapshot. Reference-grounded ideation is
verified live both ways: `src.shootgen --spark "gearing up ritual"` printed "Grounding in 5
retrieved reference(s)" against the real library, and the same command with the store pointed at
a dead URL printed the ungrounded note and still produced ideas (exit 0). The evaluate-and-retry
graph is verified live too: a `src.graph`-era run produced Concept 55, grounded in 5 references,
clean on attempt 1. ~490 tests, ruff clean, CI green on every push.

Post-production (ingest/pitch/editgen, `/pitches`, the assistant's `cut` intent) was removed in
Aug 2026 — the DB keeps historical pitch-run rows, but nothing generates new ones.

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
  clear other keepers on the same shot, which skews `attempts_to_keeper`.
- The RAG store runs live on this machine via **Homebrew `postgresql@17`** (auto-starts at
  login through `~/Library/LaunchAgents/homebrew.mxcl.postgresql@17.plist`; database `zeropage`,
  data directory `/usr/local/var/postgresql@17`). No `DATABASE_URL` is set in `.env` — connections
  fall through to `rag.DEFAULT_DB_URL`, which is already `postgresql://localhost/zeropage`, so
  nothing needs setting on this machine; set `RAG_DATABASE_URL` to point elsewhere. There are no
  standalone vector files to back up: the embeddings are Postgres pages (TOASTed out of
  `rag_documents`, since 768 floats exceed the inline threshold). Use `pg_dump zeropage`, or just
  re-run `python -m src.rag ingest` — the library is rebuildable from its sources by design.
  Ingest, scoped query, and the eval harness are all verified against it with real embeddings.
  The library currently holds 14 sources / 106 chunks across `ai_prompting` (79), `marketing`
  (25), `personal_brand`, and `cinematography`. `prompts/edit_prompt.txt` was ingested early and
  has been removed: it is a prompt *template*, and retrieving `THE BRAND: {brief}` scaffolding as
  a "reference" to inject into another prompt is worse than no grounding. Don't re-add prompt
  templates; the library wants real reference material. Machines
  without a local Postgres can use the repo's `docker-compose.yml` instead. Note: Postgres.app
  is also installed but is an uninitialised PostgreSQL 18 that owns none of this data — do not
  "Initialize" it, it would contend for port 5432 with the server that actually has the library.
- `/shots` (the candidate review-and-keep screen) and the tool scoreboard surface aren't built —
  the data path is ready (`veo.generate_candidates` logs every attempt; keeping stays a human
  act through `genlog`), but the screens want real generation attempts to show, and the first
  real Veo spend is a deliberate step (`ZEROPAGE_RENDER=1`, or the autopilot live gate) nobody
  has taken yet. Same for posting: `publish` parks even on `auto` until an upload API + public
  clip hosting exist — the IG path needs the rendered mp4 re-hosted at a public URL
  (`storage.py` is the flagged follow-up), and YouTube needs OAuth.

**The user's real data lives in `data/pipeline.db` (gitignored, ~128KB) and `locations/`
(gitignored, photos).** A fresh clone gets the tool, empty. Never overwrite either without asking.
