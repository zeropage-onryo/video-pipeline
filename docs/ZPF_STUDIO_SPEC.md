# ZPF Studio — build spec

Web UI for the Zero Page Films pipeline. FastAPI backend, server-rendered shell, vanilla ES modules on the client.

`prototype/studio.html` is the **visual source of truth** — a working single-file mockup with the real shader, layout, tokens, and interaction model. Port from it. Do not redesign it. Its data is fixtures; your job is to replace every fixture with a live connection.

The Assets view also owns successful first-party renders. Nano Banana images and Runway videos land
there automatically with the exact prompt and model details; generated images may be selected as
future references, while generated videos are gallery-only for any image-input control.

---

## 0. Prime directive — no orphan controls

**Every interactive element in the UI must be backed by a working endpoint. If the endpoint does not exist yet, the control does not render.**

This is not a style preference. A button that does nothing is worse than a missing button: it produces false confidence, it can't be tested, and it rots. Enforce it mechanically:

### Capability gating

`GET /api/capabilities` returns what is actually wired:

```json
{
  "studio.compose": true,
  "studio.upload": true,
  "assets.search": true,
  "assets.categories": true,
  "pipeline.pitch": true,
  "pipeline.editgen": false,
  "pipeline.concepts": true,
  "pipeline.feedback": true,
  "evals.run": true,
  "evals.probe": true,
  "evals.golden_write": true,
  "analytics.instagram": true,
  "analytics.youtube": true,
  "analytics.tiktok": false,
  "queue.cancel": true,
  "credits.ledger": false
}
```

The client fetches this once at boot into `state.caps`. Every control checks it:

```js
if (!caps['pipeline.editgen']) hide('[data-cap="pipeline.editgen"]');
```

Mark controls in the template with `data-cap="..."`. A rail icon whose entire view is uncapable is removed from the rail, not greyed out.

### Rules that follow from the directive

1. **No hardcoded numbers anywhere in the client.** Every metric, count, score, and label comes from a response. If you cannot source a number, delete the element that would show it.
2. **No optimistic UI without reconciliation.** You may render a pending state immediately, but it must be replaced by server truth or reverted on failure. Never leave a locally-invented value on screen.
3. **Empty states are real states.** Zero assets renders an empty-state message, not a placeholder grid.
4. **Errors surface.** A failed fetch shows an inline error on the affected panel with a retry. Never fail silently, never fall back to fixture data.
5. **No feature flags that lie.** `capabilities` reflects whether the endpoint works, derived at startup from config presence (API keys, DB tables) — not a static dict someone forgets to update.

### Definition of done for any component

- [ ] Reads from a named endpoint
- [ ] Has loading, empty, error, and populated states
- [ ] Writes go through an endpoint and re-read or reconcile
- [ ] Gated by a capability key
- [ ] No number in the markup that isn't from a response

---

## 1. Stack

| Layer | Choice | Why |
|---|---|---|
| API | FastAPI + Pydantic v2 | Already the house language |
| DB | Postgres + pgvector | Existing RAG store |
| Migrations | Alembic | Schema is going to move |
| Jobs | `asyncio` tasks + a `jobs` table | Single-user tool; don't add Celery |
| Streaming | SSE (`text/event-stream`) | One-way job progress, trivial to implement |
| Templates | Jinja2 | Server-rendered shell |
| Client | Vanilla ES modules | Prototype ports 1:1; no build step |
| CSS | One `tokens.css` + per-view files | Tokens already defined in the prototype |
| Embeddings | Gemini (existing `rag/` package) | Reuse, don't rewrite |

Do **not** introduce React, a bundler, Celery, Redis, or Docker unless a specific requirement forces it. This is a single-operator tool on localhost.

---

## 2. Repo layout

```
zpf-studio/
├── CLAUDE.md
├── prototype/studio.html          # visual source of truth, read-only
├── app/
│   ├── main.py                    # FastAPI app, mounts routers + static
│   ├── config.py                  # env, derives capabilities
│   ├── db.py                      # async engine, session dep
│   ├── models.py                  # SQLAlchemy
│   ├── schemas.py                 # Pydantic request/response
│   ├── routers/
│   │   ├── assets.py
│   │   ├── retrieve.py
│   │   ├── pipeline.py
│   │   ├── evals.py
│   │   ├── analytics.py
│   │   ├── jobs.py
│   │   └── meta.py                # /api/capabilities, /api/credits
│   ├── services/
│   │   ├── rag.py                 # wraps existing rag/ package
│   │   ├── pitch.py               # wraps pitch.py
│   │   ├── editgen.py             # wraps editgen.py
│   │   ├── proxies.py             # ffmpeg poster + sprite generation
│   │   └── social/
│   │       ├── instagram.py
│   │       ├── youtube.py
│   │       └── tiktok.py
│   ├── templates/
│   │   ├── base.html              # rail, top bar, job rail, palette
│   │   └── views/{studio,assets,pipeline,evals,analytics,queue}.html
│   └── static/
│       ├── css/tokens.css         # lifted verbatim from prototype :root
│       ├── js/{app,field,studio,assets,pipeline,evals,analytics,queue}.js
│       └── media/                 # proxies, sprites (gitignored)
├── alembic/
└── tests/
```

---

## 3. Data model

```sql
-- ── assets ────────────────────────────────────────────
CREATE TYPE asset_category AS ENUM ('location','character','prop','look');

CREATE TABLE assets (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name          text NOT NULL,
  category      asset_category NOT NULL,
  source_file   text NOT NULL,              -- A047_C012_0820MK.braw
  timecode      text,
  camera        text DEFAULT 'Blackmagic 6K',
  lut           text DEFAULT 'Batman v3',
  poster_path   text,                       -- /static/media/<id>/poster.jpg
  sprite_path   text,                       -- 8-frame strip, nullable
  duration_s    numeric,
  tags          text[] DEFAULT '{}',
  transcript    text,
  created_at    timestamptz DEFAULT now()
);
CREATE INDEX ON assets USING gin (to_tsvector('english',
  coalesce(name,'') || ' ' || coalesce(transcript,'')));
CREATE INDEX ON assets (category);

-- ── rag chunks (extend existing) ──────────────────────
CREATE TABLE chunks (
  id          bigserial PRIMARY KEY,
  asset_id    uuid REFERENCES assets(id) ON DELETE CASCADE,
  content     text NOT NULL,
  sha256      text UNIQUE NOT NULL,
  embedding   vector(768),
  kind        text DEFAULT 'transcript',    -- transcript | caption | feedback
  created_at  timestamptz DEFAULT now()
);
CREATE INDEX ON chunks USING hnsw (embedding vector_cosine_ops);

-- ── pipeline ──────────────────────────────────────────
CREATE TYPE concept_status AS ENUM ('open','approved','denied');

CREATE TABLE runs (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  prompt      text NOT NULL,
  stage       text NOT NULL,                -- pitch | editgen
  status      text NOT NULL,                -- queued|running|done|failed
  started_at  timestamptz DEFAULT now(),
  ended_at    timestamptz
);

CREATE TABLE concepts (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id      uuid REFERENCES runs(id) ON DELETE CASCADE,
  ordinal     int NOT NULL,
  title       text NOT NULL,
  logline     text NOT NULL,
  shot_count  int NOT NULL,
  prompt      text NOT NULL,                -- the prompt that produced it
  status      concept_status DEFAULT 'open',
  created_at  timestamptz DEFAULT now()
);

CREATE TABLE concept_assets (               -- what grounded it
  concept_id  uuid REFERENCES concepts(id) ON DELETE CASCADE,
  asset_id    uuid REFERENCES assets(id),
  score       numeric NOT NULL,
  rank        int NOT NULL,
  PRIMARY KEY (concept_id, asset_id)
);

CREATE TABLE concept_feedback (             -- deny screen output
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  concept_id   uuid REFERENCES concepts(id) ON DELETE CASCADE,
  reasons      text[] NOT NULL,             -- structured, NOT free text
  note         text,
  prompt_before text NOT NULL,
  prompt_after  text NOT NULL,
  chunk_id     bigint REFERENCES chunks(id),  -- written back to RAG
  created_at   timestamptz DEFAULT now()
);

-- ── evals ─────────────────────────────────────────────
CREATE TABLE golden_queries (
  id          bigserial PRIMARY KEY,
  query       text NOT NULL,
  expected    uuid[] NOT NULL,
  set_version int NOT NULL DEFAULT 1,
  source      text DEFAULT 'manual',        -- manual | probe | denial
  created_at  timestamptz DEFAULT now()
);

CREATE TABLE eval_runs (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  label        text NOT NULL,               -- "gemini embed v2"
  set_version  int NOT NULL,                -- which golden set
  query_count  int NOT NULL,
  hit1 numeric, hit3 numeric, hit5 numeric, mrr numeric, p50_ms int,
  config       jsonb NOT NULL,              -- chunk size, model, weights
  created_at   timestamptz DEFAULT now()
);

CREATE TABLE eval_results (                 -- per query, per run
  run_id     uuid REFERENCES eval_runs(id) ON DELETE CASCADE,
  query_id   bigint REFERENCES golden_queries(id),
  rank       int,                           -- NULL = miss
  retrieved  jsonb NOT NULL,                -- [{asset_id, score}] top-k
  PRIMARY KEY (run_id, query_id)
);

-- ── social ────────────────────────────────────────────
CREATE TYPE audience AS ENUM ('zpf','ai');

CREATE TABLE social_accounts (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  platform     text NOT NULL,               -- instagram|youtube|tiktok
  handle       text NOT NULL,
  audience     audience NOT NULL,
  api_label    text NOT NULL,
  token_ok     boolean DEFAULT true,
  last_sync_at timestamptz,
  UNIQUE (platform, handle)
);

CREATE TABLE social_posts (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id   uuid REFERENCES social_accounts(id) ON DELETE CASCADE,
  external_id  text NOT NULL,
  asset_id     uuid REFERENCES assets(id),  -- which plate it was cut from
  title        text,
  posted_at    timestamptz NOT NULL,
  permalink    text,
  UNIQUE (account_id, external_id)
);

CREATE TABLE social_metrics (               -- one row per post per sync day
  post_id   uuid REFERENCES social_posts(id) ON DELETE CASCADE,
  day       date NOT NULL,
  reach     int, sends int, saves int, follows int,
  views     int, avg_watch_pct numeric,
  PRIMARY KEY (post_id, day)
);

-- ── jobs & credits ────────────────────────────────────
CREATE TABLE jobs (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  kind       text NOT NULL,                 -- pitch|editgen|eval|embed|sync|render
  label      text NOT NULL,
  status     text NOT NULL,                 -- queued|running|done|failed|cancelled
  progress   numeric DEFAULT 0,
  ref_id     uuid,
  error      text,
  started_at timestamptz DEFAULT now(),
  ended_at   timestamptz
);

CREATE TABLE credit_ledger (
  id         bigserial PRIMARY KEY,
  delta      int NOT NULL,                  -- negative = spend
  reason     text NOT NULL,
  job_id     uuid REFERENCES jobs(id),
  created_at timestamptz DEFAULT now()
);
```

---

## 4. API contract

All under `/api`. All responses Pydantic-typed. Errors: `{"error": {"code": str, "message": str}}` with a real HTTP status.

### Meta
```
GET  /api/capabilities            -> {key: bool}
GET  /api/credits                 -> {balance:int, spent_7d:int, per_approval:int}
```

### Assets
```
GET    /api/assets?q=&category=&limit=&cursor=
       -> {items:[Asset], total:int, counts:{all,location,character,prop}, next:str|null}
GET    /api/assets/{id}           -> AssetDetail  (+transcript, +neighbours)
POST   /api/assets                multipart, 1..n files
       -> {items:[Asset]}         # generates poster + sprite, embeds, returns real rows
PATCH  /api/assets/{id}           {name?, category?, tags?}
GET    /api/assets/{id}/neighbours?k=3  -> [{asset, score}]
```

`counts` must come from the DB, not from `len(items)` — the category tabs show set totals, not page totals.

### Retrieval
```
POST /api/retrieve  {query:str, k:int=5, category?:str}
     -> {hits:[{asset_id, name, source_file, timecode, score, poster_path}],
         latency_ms:int, model:str}
```
One endpoint serves the Studio grounding rail, the Evals probe, and the harness. Do not write three scorers.

### Pipeline
```
GET  /api/pipeline/stages         -> [{key,name,status,progress,detail}]
POST /api/pipeline/run            {prompt:str}  -> {run_id, job_id}
GET  /api/pipeline/concepts?status=open
     -> [{id, ordinal, title, logline, shot_count, prompt, status,
          grounded:[{asset_id,name,poster_path,score}]}]
POST /api/concepts/{id}/approve   -> {concept, job_id}      # queues editgen
POST /api/concepts/{id}/deny
     {reasons:[str], note:str|null, prompt:str}
     -> {feedback_id, chunk_id, job_id}                     # writes to chunks
GET  /api/pipeline/feedback?limit=20 -> [ConceptFeedback]
GET  /api/pipeline/log?run_id=      -> [{t, stage, message}]
```

**Deny writes to RAG.** Compose a chunk of kind `feedback` — the corrected prompt plus the reason tags — embed it, insert into `chunks`, and store the id on `concept_feedback.chunk_id`. Return the id so the UI can display it. If the embed fails, the whole request fails; do not record feedback that never reached the store.

### Evals
```
GET  /api/evals/runs              -> [EvalRun]        # for the history chart
GET  /api/evals/runs/{id}         -> {run, results:[{query, rank, rr, retrieved}]}
POST /api/evals/run   {label?:str} -> {job_id}        # SSE reports progress
GET  /api/evals/golden            -> [{id, query, expected:[Asset], source}]
POST /api/evals/golden {query:str, expected:[uuid], source:'probe'} -> GoldenQuery
DELETE /api/evals/golden/{id}

# DEV_TOOLS only; production CRAG behavior observed from the shared /ui path
GET /studio/api/evals/requeries
     -> {total, retried, requery_rate, requery_success_rate,
         requery_adoption_rate, avg_score_improvement}
```

The harness runs the same golden set against both one-shot retrieval and the complete CRAG rewrite
path. It computes base/CRAG Hit@k and MRR plus re-query, score-improvement, adoption, and
expected-source rates server-side. The client never calculates a metric. The `/studio` telemetry
surface is dev-only; `/ui` uses the instrumented shared retrieval path but does not render internal
metrics or controls.

Every `eval_runs` row records query-set and reference-library fingerprints plus the retrieval
configuration and threshold. A score is meaningless without knowing which query set, library, and
retrieval configuration produced it; the UI only shows deltas for comparable runs.

### Analytics
```
GET /api/analytics/accounts?audience=zpf
    -> [{id, platform, handle, api_label, token_ok, last_sync_at}]
GET /api/analytics/summary?audience=&platform=&days=14
    -> {sends_per_reach:float, reach:int, sends:int, saves:int, follows:int,
        prev:{...}, benchmark:float}
GET /api/analytics/daily?audience=&platform=&days=14
    -> [{day, by_platform:{instagram:int,...}, reach:int, sends:int}]
GET /api/analytics/posts?audience=&platform=&days=14
    -> [{id, title, platform, posted_at, asset_id, poster_path,
         reach, sends, saves, follows, sends_per_reach}]
POST /api/analytics/sync          -> {job_id}   # manual re-sync
```

`benchmark` comes from config per audience — the two funnels do not share a threshold.

### Jobs
```
GET    /api/jobs?active=true      -> [Job]
GET    /api/jobs/stream           -> SSE, event: job, data: Job
POST   /api/jobs/{id}/cancel      -> Job
DELETE /api/jobs/{id}             -> 204            # clear a finished job
```

SSE is the only push channel. The job rail, the queue view, and the pipeline stage bars all subscribe to it — do not poll.

---

## 5. Wiring table

Every control in the prototype, and what it must connect to. **If a row has no endpoint, the control is not built.**

### Global shell
| Element | Connection |
|---|---|
| Credits pill (top right) | `GET /api/credits` on boot + after any job completes |
| Job rail (bottom pill) | `GET /api/jobs/stream` SSE |
| ⌘K palette — actions | `POST` the corresponding endpoint |
| ⌘K palette — asset jump | `GET /api/assets?q=` typeahead |
| Rail icons | Client route + `capabilities` gate |

### Studio
| Element | Connection |
|---|---|
| Prompt textarea | Local until submit |
| Grounding rail (live) | `POST /api/retrieve` debounced 250 ms |
| Latency readout | `latency_ms` from that response |
| `+` upload | `POST /api/assets` multipart |
| Create button | `POST /api/pipeline/run` → routes to Pipeline |
| Plates carousel | `GET /api/assets?limit=12` |
| Carousel filter chips | `GET /api/assets?category=` |
| Hover scrub | `sprite_path`; if null, no scrub — poster only |

### Assets
| Element | Connection |
|---|---|
| Search | `GET /api/assets?q=` debounced 200 ms |
| Category tabs + counts | `counts` from the same response |
| Grid | `GET /api/assets` paginated |
| Detail rail | `GET /api/assets/{id}` |
| Neighbours | `GET /api/assets/{id}/neighbours` |
| Use as plate | Adds to composer selection (client state, sent with `/pipeline/run`) |
| Add to queue | `POST /api/jobs` kind=render |

### Pipeline
| Element | Connection |
|---|---|
| Stage cards (pitch, editgen) | `GET /api/pipeline/stages` + SSE |
| Run all | `POST /api/pipeline/run` |
| Concept cards | `GET /api/pipeline/concepts` |
| Grounded thumbnails | `grounded[]` on each concept |
| Approve | `POST /api/concepts/{id}/approve` |
| Deny → screen | Opens with `concept.prompt` from the API |
| Reason chips | Sent as `reasons[]` — enum, validated server-side |
| Record & regenerate | `POST /api/concepts/{id}/deny` |
| Recorded-to-RAG panel | `GET /api/pipeline/feedback` |
| Run log | `GET /api/pipeline/log` |

### Evals
| Element | Connection |
|---|---|
| Metric cards | `GET /api/evals/runs/{selected}` |
| Deltas | Previous run in the same list |
| Run history bars | `GET /api/evals/runs` |
| Bar click | Loads that run's metrics + results |
| Run eval | `POST /api/evals/run` → SSE |
| Probe input | `POST /api/retrieve` |
| ✓ marks | Client selection |
| Add to golden set | `POST /api/evals/golden` |
| Golden rows | `GET /api/evals/golden` |
| Row expand | `retrieved` from `eval_results` for the selected run |

### Analytics
| Element | Connection |
|---|---|
| Audience toggle | Query param on every call in the view |
| Platform tabs + counts | `GET /api/analytics/posts` grouped |
| KPI cards | `GET /api/analytics/summary` |
| Sends-per-reach chart | `GET /api/analytics/daily` |
| Benchmark line | `benchmark` from summary |
| Reach-by-platform chart | `daily[].by_platform` |
| Posts table | `GET /api/analytics/posts` |
| Post row click | Opens asset detail via `asset_id` |
| Connected accounts | `GET /api/analytics/accounts` |
| Sync stamp / reauth dot | `last_sync_at`, `token_ok` |

### Queue
| Element | Connection |
|---|---|
| Rows | `GET /api/jobs` + SSE |
| Cancel | `POST /api/jobs/{id}/cancel` |
| Clear | `DELETE /api/jobs/{id}` |

---

## 6. Build order

Each phase ends with something usable. Do not start a phase before the previous one passes its check.

**Phase 1 — shell + assets**
Port `base.html` (rail, top bar, shader, palette), `tokens.css`, and the field module. Assets CRUD, ffmpeg poster + sprite generation on upload, Gemini embedding on ingest, search and category endpoints.
*Check:* upload three real Blackmagic stills, see them in the grid with working search, categories, and detail rail.

**Phase 2 — retrieval + studio**
`POST /api/retrieve` against pgvector. Wire the grounding rail and the carousel.
*Check:* typing in the composer returns real plates with real scores and real latency.

**Phase 3 — jobs + pipeline**
Jobs table, SSE stream, job rail, queue view. Wrap `pitch.py`. Concepts, approve, deny, feedback-to-RAG.
*Check:* Create → concepts appear → approve queues editgen → deny writes a chunk you can query.

**Phase 4 — evals**
Golden set CRUD, harness computing Hit@k/MRR server-side, run history, probe.
*Check:* run the harness, add a query from the probe, re-run, watch the score move.

**Phase 5 — analytics**
Social clients, nightly sync job, summary/daily/posts endpoints.
*Check:* real numbers from at least one live account, correct on both audience tabs.

**Phase 6 — credits**
Ledger, per-job cost accounting, the pill and per-approval metric.

---

## 7. Porting notes from the prototype

- **`tokens.css`** — copy the `:root` block verbatim. Do not re-pick colours.
- **The shader** — `static/js/field.js`, unchanged. It is self-contained, has a CSS fallback, and respects `prefers-reduced-motion`.
- **`makeStrip()` / `drawFrame()` — delete.** Canvas frame synthesis exists only so the mockup isn't full of grey boxes. Replace with real posters and sprites:
  ```bash
  # poster at 15% in
  ffmpeg -ss "$(echo "$DUR*0.15" | bc)" -i in.mov -frames:v 1 -q:v 3 poster.jpg
  # 8-frame sprite strip, 340px wide each
  ffmpeg -i in.mov -vf "select='not(mod(n,floor(${FRAMES}/8)))',scale=340:-1,tile=8x1" \
         -frames:v 1 -q:v 3 sprite.jpg
  ```
  Keep the CSS contract: `background-size: 800% 100%`, `background-position: <pct> 50%`. The scrub interaction then works unchanged.
- **Selection, keyboard nav (`J`/`K`/`X`/`Enter`), detail rail, deny screen** — port the interaction code as-is, swap the data source.
- **Every fixture array** (`PLATES`, `CONCEPTS`, `RUNS`, `GOLDEN`, `POSTS`, `SYNC`, `JOBS`) — delete. They exist to be replaced.

---

## 8. Known gotchas

- **Instagram "sends"** is `shares` on the Graph API and is not available for every media type. Confirm what the sync actually pulls before trusting the benchmark line. If a platform can't report sends, mark it unavailable in `capabilities` rather than showing a zero.
- **TikTok Display API** gives limited metrics without Research API access. Gate accordingly.
- **YouTube** reports at the video level with a reporting lag of up to 48h. Show `last_sync_at`, don't imply real-time.
- **pgvector HNSW** needs `ef_search` tuned per query volume; default is fine at this scale but record it in `eval_runs.config`.
- **Concept prompts are versioned by denial.** When a deny edits the prompt, keep `prompt_before` — the diff is the training signal.
- **`counts` vs page length.** Category tabs must show totals from the DB.
- **SSE through a proxy** needs buffering off. If you tunnel this, set `X-Accel-Buffering: no`.

---

## 9. Decisions already made — don't relitigate

- Two audiences never average together in analytics.
- Sends-per-reach is the headline social metric.
- One retrieval endpoint serves composer, probe, and harness.
- Deny reasons are an enum, not free text.
- Red (`#E4002B`) means active or selected. Nothing else is red.
- The shader appears on Studio only; working views get a neutral background so footage colour reads true.
- No React, no bundler, no Celery.

## 10. Open questions for Mike

1. Where does the media library live on disk, and should assets reference originals or copies?
2. Is `editgen.py` callable as a function, or does it need subprocess isolation?
3. Do you want a fourth asset category for **Looks** (LUTs, grade refs)?
4. Credits — Runway/Kling API spend, or your own internal unit?
5. Should a denied concept regenerate in place, or vacate its slot for a fresh one?
