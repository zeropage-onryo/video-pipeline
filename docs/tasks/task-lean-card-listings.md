# Task: lean card listings (Supabase egress per user)

## Measurements (step 0, 2026-09-25, live Supabase, account 1)

**Method.** Each route function called in-process against the live database
(read-only; worktree code, `PYTHONPATH` pinned). The venv's editable install
points at the main checkout, so without the pin you measure the wrong tree.
**db bytes** is every value fetched from Postgres, summed as text. That is a
proxy for Supabase egress, excluding protocol overhead. **response** is the
JSON body as FastAPI serialises it, which is what Vercel's edge carries to the
browser. Both brands have more than 100 rows, so every listing is a full window
(zeropage 121 rows with 116 archived; antihero 134 with 112 archived).

| Route (account 1) | response | db bytes | rows read | queries |
|---|---:|---:|---:|---:|
| `/api/pipeline/concepts?brand=zeropage` | 44,828 | 937,345 | 711 | 28 |
| `/api/pipeline/concepts?brand=zeropage&archived=true` | 382,296 | 937,345 | 711 | 28 |
| `/api/queue/pending?brand=zeropage` | 27,806 | 933,659 | 452 | 38 |
| `/api/queue/manual?brand=zeropage` | 5,640 | 933,478 | 434 | 20 |
| `/api/pipeline/concepts?brand=antihero` | 52,749 | 852,401 | 668 | 28 |
| `/api/pipeline/concepts?brand=antihero&archived=true` | 442,126 | 852,401 | 668 | 28 |
| `/api/queue/pending?brand=antihero` | 8,126 | 848,715 | 409 | 38 |
| `/api/queue/manual?brand=antihero` | 606 | 848,534 | 391 | 20 |

The three side readers (Elements, Director arrival, scene switcher) each call
the default `/api/pipeline/concepts`, so each costs the same ~0.85–0.94 MB from
the database for a count, one id, or a menu.

**Where the board's ~0.94 MB comes from (zeropage, per query):**

| Query | db bytes |
|---|---:|
| `SELECT * FROM shoot_concepts … LIMIT 100` | 482,913 |
| `gates_for_concepts`: `hold_queue` rows **with `payload`** | 420,692 |
| `gates_for_concepts`: `prompt_scores` | 25,238 |
| `scout.sources_for_refs` | 4,631 |
| `shoot_rate` + `pick_rate` + `subscription_rendered` | 3,871 |

**The doc missed one.** Almost half the egress is `hold_queue.payload` (text,
1.08 MB across 424 rows), which `gates_for_concepts` reads only for
`payload.run_id`. That fix goes in step 3 (read `run_id` in SQL).

**`shoot_concepts` (255 rows):** avg row 4,911 B, `shots_json` avg 3,581 B /
max 9,570 B, `ai_json` empty everywhere. Column totals: `shots_json` 913 KB,
`spark` 163 KB, `logline` 70 KB, `uncanny_reason` 24 KB, `hook` 22 KB,
`card_line` 11 KB. `notes`, `edit_note`, `grade_note`, `judge_reason` and
`ai_json` are all empty, so dropping them saves nothing today.

**Inside `shots_json[0]`:** `prompt` 371 KB, **`written_prompt` 321 KB
(35%)**, `desc` 67 KB, `refs` 41 KB, `timeline` 32 KB (12 rows; parts'
`refs` 8.7 KB, `text` 8.2 KB, `prompt` 6.2 KB), `frames` 16 KB,
`park_reason` 15 KB. `model_prompt` is on no row yet (edit-teach is new).

## Before / after

Each step re-runs the same eight calls. Figures are db bytes / response bytes.

| Route | before | step 1 |
|---|---|---|
| `pipeline/concepts` zeropage | 937,345 / 44,828 | unchanged |
| `pipeline/concepts` zeropage archived | 937,345 / 382,296 | unchanged |
| `queue/pending` zeropage | 933,659 / 27,806 | **52,052** / 27,806 |
| `queue/manual` zeropage | 933,478 / 5,640 | **51,871** / 5,640 |
| `pipeline/concepts` antihero | 852,401 / 52,749 | unchanged |
| `pipeline/concepts` antihero archived | 852,401 / 442,126 | unchanged |
| `queue/pending` antihero | 848,715 / 8,126 | **11,023** / 8,126 |
| `queue/manual` antihero | 848,534 / 606 | **10,842** / 606 |

Step 1 (`perf/queue-listing-lean`): the Queue and the manual lane pick their
rows off `queue_candidates` + `_is_waiting`, then load only those
(`preprod.get_concepts`). Response bodies are byte-identical in size, and the
test pins the ids to the old path.

**Step 2 (`perf/board-side-readers`): the side readers stop pulling the board.**

| Reader | before: what it fetched | db / response | after: what it fetches | db / response |
|---|---|---:|---|---:|
| Director arrival, zeropage | `/pipeline/concepts?brand=zeropage` | 937,345 / 44,828 | `/pipeline/arrival?brand=zeropage` | **204 / 10** |
| Director arrival, antihero | `/pipeline/concepts?brand=antihero` | 852,401 / 52,749 | `/pipeline/arrival?brand=antihero` | **1,012 / 10** |
| Scene switcher, zeropage | `/pipeline/concepts?brand=zeropage` | 937,345 / 44,828 | `/pipeline/concepts?brand=zeropage&view=menu` | **204 / 499** |
| Scene switcher, antihero | `/pipeline/concepts?brand=antihero` | 852,401 / 52,749 | `/pipeline/concepts?brand=antihero&view=menu` | **1,012 / 254** |
| Elements usage | `/pipeline/concepts` (unbranded) | 896,205 / 59,334 | `used_in` on `/assets?scope=elements` | **2,161** extra / a few bytes per element |

Checked on the live rows: the server's arrival and menu give exactly the ids
and states the old client-side `pickArrival`/`openable` gave, for both brands
and unbranded. The arrival rule (`api._arrival` / `api._openable`) moved to the
server, and `web/src/lib/director-arrival.ts` and its node test were deleted;
the four cases were ported to `tests/test_api.py`. `used_in` goes through
`asset_shelf.parse_ref`, so it also fixes a quiet bug: the page's old regex only
knew the local `/characters/<slug>/` shape, and every canonical R2 ref counted
as 0. Account 1 has no elements on the live database today, so there was
nothing live to compare against there; the test covers local, R2 and repeated
refs.

Written 2026-09-25. Follows PR #48 (`perf/queue-count-egress`), which fixed the
Queue badge. Read that commit (5fe9245) first: this task applies the same fix
to the pages a person actually opens.

## Why

After #48 went live, daily egress fell from 1.38 GB (22 Sep) to 14 MB (23 Sep).
With only Mike using the studio, that's fine. With users, egress scales with
**page loads**, and the page loads still read the same fat rows the badge used
to read:

- `preprod.list_concepts` is `SELECT *` over the newest 100 concepts, including
  all of `shots_json` (prompts, `written_prompt`, `model_prompt`, timeline parts,
  refs), `ai_json`, notes and judge reasons. Every call also adds
  `gates_for_concepts` (2 queries) and `scout.sources_for_refs` (1 query).
- Our rough guess is ~1 MB per listing, the same figure #48 measured for the
  badge. Step 0 replaces that guess with a measurement.

Budget: the free plan's 5 GB/month is about 165 MB/day. Mike's baseline (the
nightly runs plus his own use) is about 15–30 MB/day. At ~1 MB per listing,
someone opening the board 20 times a day costs ~20 MB/day, so the free plan
runs out at about 5–10 active users. The goal of this task is to make a page
load cost kilobytes.

## Who reads the full board today

| Caller | Route | What it needs | What it gets |
|---|---|---|---|
| Pipeline page (`web/src/app/studio/pipeline/page.tsx`) | `/api/pipeline/concepts?archived=true` | cards | 100 full cards, **including archived** (~80% of rows) |
| Queue page | `/api/queue/pending` → `_waiting` | a handful of waiting cards | `list_concepts` over 100 rows plus a card built for each, then most are thrown away |
| Manual lane | `/api/queue/manual` → `_waiting` | picked cards | same as above |
| Elements page (`elements/page.tsx`) | `/api/pipeline/concepts` | a usage count per element (refs by slug) | the whole board |
| Director arrival (`director-arrival.tsx`) | `/api/pipeline/concepts` | ONE concept id | the whole board |
| Scene switcher (`flow-workspace.tsx`) | `/api/pipeline/concepts` | id, title, state for a menu | the whole board |

None of these are on a timer (#48 checked). The cost is per visit, multiplied
by the number of users.

## Steps, cheapest and safest first

### 0. Measure before touching anything
- In SQL: `SELECT avg(octet_length(shots_json)), max(octet_length(shots_json)),
  avg(octet_length(coalesce(ai_json,''))) FROM shoot_concepts;` Also measure
  which keys inside `shots_json` carry the bytes (`written_prompt`,
  `model_prompt`, `timeline.parts[].prompt`).
- Record the response size of each route above for Mike's account (browser
  devtools or `curl -s ... | wc -c` with a session). Put the numbers at the
  top of this doc. Every later step reports its before/after against them.

### 1. The Queue listing counts off `queue_candidates` (same shape as #48)
- `_waiting`: get the window from `preprod.queue_candidates`, run
  `_is_waiting`, and only then load full rows **for those ids** (a new
  `preprod.get_concepts(ids, account_id=...)`, scoped like every read).
  Batch gates and sources over those ids only.
- Keep: the spendable-first sort, `include_blocked`, `reference_gate` asked
  again at approve, and the manual lane's picked-only rule.
- Test: the listing never calls `list_concepts`, and its ids match the old
  path across both brands, blocked rows included (extend
  `test_the_lean_queue_count_matches_the_listing_ungrounded_included`).

### 2. The three side readers stop pulling the board
- **Director arrival** → `GET /api/pipeline/arrival?brand=` returns
  `{id}` or `{id: null}`, using the same `pickArrival` rule, moved to the
  server so the rule lives in one place.
- **Scene switcher** → `GET /api/pipeline/concepts?view=menu` returns
  `id, title, brand, picked, parked, has_media` from a column-only query, with
  no card, gates or sources.
- **Elements usage** → a `used_in` count on each element in
  `/api/assets?scope=elements`, computed server-side from a lean refs-only
  query. Use `asset_shelf.parse_ref`, **the** parser, never another
  `split("/")`.

### 3. The board query stops shipping what no card draws
- `list_concepts(lean=True)`: name the columns instead of `*` (drop
  `ai_json`, `notes`, `edit_note`, `grade_note`, `judge_reason`,
  `uncanny_reason` unless a card reads them; grep `_concept_card` and
  `concept-card.tsx`).
- If step 0 shows `written_prompt` / `model_prompt` are the weight, strip them
  in SQL: `(shots_json::jsonb #- '{0,written_prompt}' #- '{0,model_prompt}')::text`.
  They are only read when a scene is opened (Director, edit-teach), and those
  paths read the single concept, not the board.
- **Don't change `refs` or its order.** `refs[0]` is the frame Runway anchors on.

### 4. Archived rows on demand (DECIDED 2026-09-25, Mike: yes)
The Pipeline page asks for archived rows so its count line can say where
every card went (the 2026-09-02 lesson). The count line stays. Only where
its numbers come from changes:
- `GET /api/pipeline/concepts` returns a `counts` object
  (`{open, picked, archived}`, plus per-reason archived counts if the
  line shows them) from a `COUNT(*) ... GROUP BY` over the same window,
  scoped by account and brand in SQL. Default response = open cards only.
- `?archived=true` still works and still returns the archived cards, but
  the page asks for them only when the Archived filter is opened, then
  caches them for the visit.
- `web/src/app/studio/pipeline/page.tsx` stops calling
  `boardConcepts(brand, true)` on load, reads the count line from
  `counts`, and fetches the archived cards lazily. Archive and restore
  must update `counts` locally (or refetch the counts) so the line
  doesn't go stale.
- Keep archiving a soft delete. Archived rows stay counted in `pick_rate`,
  which reads the rows, not this endpoint.
- Test: `counts` matches the old client-side tally across both brands, and
  the default response carries no archived card.

## Rules this must not break
- Tenant via `Depends(auth.current_account_id)`, passed into every helper;
  LIMIT after the brand filter (`account_scoping`).
- One waiting predicate (`_is_waiting`), one ref parser (`parse_ref`), one
  arrival rule. A second copy is how two surfaces start disagreeing.
- The React card and `app/static/zpf/cards.js` are twins. If a field
  leaves the lean card, check both.

## Done when
- Each route in the table has a before/after byte figure in this doc.
- Suite green the way CI runs it, ruff clean, `next build` clean.
- Deployed: `fly deploy` for the API and Vercel for `web/`. Then read the
  Supabase usage chart the next day, with a figure per day, not the cycle
  total.
