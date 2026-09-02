# Task — the shared brain: making global learning deliberate

**Status: not started.** Written 2026-09-01, out of Mike's answer when the
unscoped learning tables were put to him as a tenancy gap:

> "the learning loop continues for all users, the entire app learns as it goes
> and gets better, that is the loop. I see all the data in dev studio."

That is a product decision, not an oversight, and this document is built on it:
**the learning tables stay global on purpose.** Every user's grades, taught
prompts and proven winners improve the system for everybody. It is also the
defensible position BACKLOG #10 was reaching for — Runway and Higgsfield sell
inference and never see the grade, so the loop is the part they structurally
cannot copy.

The work below is not undoing that. It is the three things the decision needs in
order to survive its hundredth user, and one of them is a live bug.

---

## 1. What is true today (verified 2026-09-01 against `main` @ `a7c97a3`)

Tenancy scoped 8 tables (`db.OWNED_TABLES`, `src/db.py:162`). Twenty others have
no `account_id`, and nine of those carry the loop or the controls:

| shared table | rows | what it holds |
|---|---|---|
| `prompt_scores` | 63 | the gate's record; `autonomy.prompt_gate_agreement` averages it |
| `hold_queue` | 38 | the grade queue and the dead-man log |
| `winning_prompts` | 14 | taught prompts and the avoid shelf |
| `metrics` | 11 | post performance |
| `scout_findings` | 7 | the spark bank — **already partitioned by `brand`** |
| `workflows` | 5 | Director canvases |
| `inspiration_accounts` | 4 | the lanes |
| `channels` | 2 | autonomy level per brand |
| `settings` | 0 | thresholds **and the kill switch** |
| `corrections` | 0 | standing human notes — see §2 |

Plus `rag_documents` in Postgres, which is domain-scoped and has never been
account-scoped.

**The hybrid Mike described is already half-built — it just isn't declared.**
`taste_judge.gather_signals` (`src/taste_judge.py:56`) is the clearest example:

- `liked` / `disliked` take `account_id` and are **scoped** — your own grades;
- `winners.list_all(path=path)` (`src/winners.py:82`) is **global** — everyone's
  taught prompts;
- `post_seo.derive_signals(db_path=db_path)` is called **without** `account_id`
  even though the function accepts one (`src/post_seo.py:52`) — so global, but by
  omission rather than intent.

So the judge already scores a fresh concept against *your* taste and *everyone's*
lessons. That is exactly the right shape. Nothing says so anywhere, and the third
line is an accident that currently agrees with the design and will stop agreeing
the first time somebody "fixes" it.

**This is the cheapest and most valuable thing in this task: write the decision
down.** A future session — or a future contributor — reads twenty unscoped tables
next to a 42-test tenancy suite and concludes the migration was left half
finished. The correct response to that reading is a comment at `db.OWNED_TABLES`
naming the tables that are global *on purpose* and why, not a pull request that
quietly ends the network effect.

---

## 2. The one genuine leak: `corrections`

A correction is not a lesson. It is an **instruction**, and instructions are
addressed to somebody.

`corrections` (`src/autonomy.py:60`) has no `brand` and no `account_id`. It is
written from two places:

```
app/api.py:1905    every concept denial -- any signed-in user, on their own board
app/main.py:1303   the Dev Studio note box
```

and consumed in the orchestrator (`src/orchestrator.py:406`):

```python
notes = autonomy.pending_corrections(path=db.DB_PATH)   # every unconsumed note
...
autonomy.consume_correction(n["id"], path=db.DB_PATH)   # and marks it used
```

`pending_corrections` (`src/autonomy.py:337`) selects `WHERE consumed = 0` with
no owner and no brand. `main.py:1303`'s own docstring says each note "steers
exactly once."

So with two people on the system: **a pilot user denying a concept on their own
board writes a standing instruction that steers Mike's next nightly run, once,
and is consumed before the user's own night ever sees it.** Both halves are
wrong, and neither is what "the app learns from everyone" means — the lesson
(what got denied and why) *should* be shared, and it already is, via the
`denials` RAG shelf written two lines later at `app/api.py:1923`. It is the
imperative that has to be addressed.

This one is a bug under any reading of the decision, and it is the first fix.

---

## 3. The shelves have a provenance hook that nobody writes and nobody reads

Global learning is only as good as its ability to *weight*. Without a label
saying where a lesson came from, a cooking channel's taught prompt and Mike's
horror shelf are one undifferentiated pile, and the shelf gets noisier with every
user instead of smarter — the network effect running backwards.

The hook already exists. `rag_documents` has a `project` column **and an index on
it** (`src/rag.py:49,56`), and `rag.retrieve` already accepts `project=` and
filters on it (`src/rag.py:197,218`).

- **Exactly one site writes it:** `app/api.py:1923`, the denials shelf, as
  `"project": concept.get("brand")`. The pattern is already correct, in one place.
- **Zero callers read it.** No call to `retrieve(...)` anywhere passes `project=`.
- `winners.ingest_to_rag` (`src/winners.py:116`) and
  `promote_winners._ingest_candidates` (`src/promote_winners.py:202`) write with
  `domain` only.
- `winning_prompts` itself (`src/winners.py:26`) has `tool / prompt / note /
  verdict / pair_id / rag_source / ingested` — no brand, no account.

**Provenance is a label, not a fence.** Every user still reaches every lesson.
The label is what lets retrieval put your own neighbourhood first and the rest
behind it, and what lets the Dev Studio answer "whose lessons fired in this run" —
which is the number that tells Mike whether the shared brain is actually helping
or just adding noise.

---

## 4. The build (~5 hours)

### Step 1 — declare the design (~30 min)

A `SHARED` tuple beside `db.OWNED_TABLES` naming the deliberately-global tables
with one line each on why, and a paragraph in `docs/ARCHITECTURE.md`. The
`tests/test_tenancy.py` static scan should assert that every table is in exactly
one of the two lists, so a table added later cannot be silently neither.

### Step 2 — address the corrections (~1 h)

Add `brand` and `account_id` to `corrections`; `add_correction` takes them from
the caller (both sites already have them); `pending_corrections(brand=...)`
returns the ones addressed to the run being generated. **Do not add it to
`OWNED_TABLES`** — an operator note written on the Dev Studio with no brand
should still steer everything, and the static scan would forbid that read.
Document that exception where the table is defined.

### Step 3 — label the shelves (~2 h)

`project` set on every ingest, matching the shape `app/api.py:1923` already uses:
`winners.ingest_to_rag`, `promote_winners._ingest_candidates`,
`asset_shelf` (`src/asset_shelf.py:116`, currently an explicit `None`). Add
`brand` to `winning_prompts`, backfilled `NULL` = house, and carry it into the
ingest. Existing `rag_documents` rows: only the denials shelf can be backfilled
from data; everything else becomes `NULL` and reads as house, which is true.

### Step 4 — weight the retrieval (~1.5 h)

Own-neighbourhood-first, everything-else-behind — not a filter that excludes.
`taste_judge` passes `account_id` into `derive_signals` so the omission becomes a
decision. Then the Dev Studio panel: per run, which shelves and whose lessons
were retrieved, so the effect of the shared brain is visible rather than assumed.

---

## 5. Traps

- **`rag_documents` is `UNIQUE (source, chunk_index)`** (`src/rag.py:51`).
  Backfilling `project` is an `UPDATE`; re-ingesting to attach it writes duplicate
  rows or raises, depending on the path taken.
- **Sparks are already brand-partitioned** — `scout_findings.brand` with an index
  on `(brand, used_at)` (`src/scout.py:159,174`), and `next_spark(brand, ...)`.
  That is not the problem it looks like. The real one is narrower: `next_spark`
  deliberately does not claim, and `mark_used` stamps later and swallows its own
  errors (`src/scout.py:959,969`) — correct with one nightly job, a race with two.
  Fix it as a claim, or leave it and write down that it is single-writer.
- **`settings` holds the kill switch** (`autonomy.KILL_KEY`, `src/autonomy.py:167`).
  Global is right for it — one operator, one brake — but only while the Settings
  tab stays DEV_TOOLS-only and unmounted in public deployment, as `docs/PILOT.md`
  already requires. If that ever changes, this is the first table to revisit.
- **Never iterate on schema code inside the mounted folder.** The dev server
  reloads on save and runs the migration against `data/pipeline.db`. Prove it in a
  scratch copy against a copy of the database, then copy the finished file in.

---

## 6. Verification

`pytest tests/` (not bare `pytest` — that collects `evals/`). New tests:

- a correction written on brand A never appears in `pending_corrections` for a run
  on brand B, and is still there for A's own run afterwards;
- a lesson taught on brand A **is** retrievable by brand B — the network effect,
  asserted, so a later change cannot quietly fence it off;
- and ranks below B's own lessons when both match;
- every table is in exactly one of `OWNED_TABLES` / `SHARED`.

Then the honest check: run both brands' nights, and confirm from the Dev Studio
panel that A's denial steered A and that B's grounding still reached A's winners.

---

## 7. What this deliberately does not do

- **It does not scope the learning tables.** That was the proposal Mike rejected,
  and rightly — it would trade the compounding loop for a cleanliness that nobody
  asked for.
- **It does not touch the RAG library's global reach.** Every user keeps grounding
  on every lesson. Only the ordering changes.
- **It is not a consent or privacy feature.** But the pilot invite should say in
  one sentence that grades and prompts train the shared system and that the
  operator can see them in the Dev Studio. That is a fair trade stated plainly,
  and it reads badly if discovered later. One line in `docs/PILOT.md`, not a
  project.
