# Task — close the tenancy gap the dry run found, and settle the RAG question

**Hand this whole file to Claude Code.** One block, roughly a day. It has two
halves that are unrelated except in timing: the first is the gate on the pilot,
the second is the one thing the dry run could not test.

Read `docs/PILOT_DRY_RUN.md` first — it is the evidence for everything below,
and every claim in it was reproduced by a request or a query, not read off the
source. BACKLOG #12 is the summary.

## Ground rules

1. **Never touch `data/pipeline.db`.** Copy it and point the work at the copy.
   His studio dev server watches the source tree and runs the app lifespan —
   `db.init_db`, `preprod.init`, `entities.init` — against the live database
   within seconds of any save. **Prove every migration against a copy before
   the file lands in the tree.** A half-finished migration sitting in
   `src/preprod.py` for thirty seconds has already run on his real data; it
   cost a damaged `concept_locations` once.
2. `venv/bin/python -m pytest -q tests/` — not bare `pytest`, which collects
   `evals/` and makes real billed calls. Baseline is **1354 passed, 9 xfailed**.
3. Another session has untracked work in the tree (`src/imagesearch.py`,
   `src/framebank.py`, `ops/build-frame-bank.py`, `tests/test_imagesearch.py`,
   `ops/ig_token.sh`, `ig-token.command`). Never `git add -A`; always
   `git commit --only <paths>`.
4. Land part one and part two as separate commits. Part one can ship alone.

## SQLite will do these three things to you

All three are real bugs found by running, not theory:

- **Never rename a table another table's FK points at.** Since 3.25 a RENAME
  rewrites *other* tables' `REFERENCES` clauses to follow it, and neither
  `PRAGMA foreign_keys=OFF` nor `legacy_alter_table=ON` prevents it. Build the
  new table alongside, DROP the original, rename the new one *into* its name.
- **`UNIQUE(account_id, name)` does not do what you want** — NULLs are distinct
  inside a UNIQUE. Use `CREATE UNIQUE INDEX ... ON t (COALESCE(account_id, 0),
  name)` and give `ON CONFLICT` the same expression.
- **`PRAGMA foreign_key_check` is silent** about a `REFERENCES` clause naming a
  missing table. Assert on the schema text too.

Also: `cur.lastrowid` is untrustworthy after an upsert that took `DO UPDATE`.

---

# Part one — the three tables tenancy never listed

## 1. `hold_queue` and `workflows` get an owner

`add_account_column` + the backfill already exist and were used for the eight
tables in `db.OWNED_TABLES`; follow that path exactly. Backfill every existing
row to account 1 (the bootstrap account — confirm, do not assume, that it is
the one owning the 29 concepts). Then add both tables to `db.OWNED_TABLES`,
which is what puts them under the static SQL test.

Then thread the owner through every read, write, mutate and delete that reaches
them. The routes proven broken as an unauthorised caller:

```
GET    /api/holds                 -> listed Mike's 38 holds
POST   /api/holds/{id}/resolve    -> flipped hold 38 held -> rejected
GET    /api/workflows             -> listed Mike's canvases
PUT    /api/workflows/{id}        -> overwrote one
DELETE /api/workflows/{id}        -> destroyed "Midnight Evasion"
```

`autonomy.list_hold`, `autonomy.resolve_hold`, `autonomy.get_channel` and the
workflow store are the functions behind them. Match the shape the concept
routes already use: the owner is a **parameter the handler cannot use without
declaring** (`Depends(auth.current_account_id)`), and a row belonging to someone
else is a **404, not a 403** — same as `preprod.get_concept`. Do not invent a
second convention.

`workflows` also carries a `brand` column. Leave it a label. `account_id` is
ownership; brand is what the pill filters inside it. That distinction is
load-bearing — see `auth.current_account_id`'s docstring for why conflating
them empties his board.

## 2. `holds_post` — the one that can actually publish

`app/api.py:1998` is `def holds_post(hold_id: int)`. No account dependency of
any kind, an unscoped lookup, then
`autopilot.execute({...}, approve=True, dry_run=False)`. Today the only thing
between a stranger and a post on his Instagram is the `data/autopilot.off`
kill-switch file.

Give it the owner. Then look at the gate itself and say, in the code, what it
is: `ZEROPAGE_AUTOPILOT`, the credentials and the kill switch are three facts
about *the installation*, none about *the caller*. Publishing is the most
expensive irreversible action in the product and it is the one action with no
per-caller approval. Propose the smallest honest gate — the shape the other
tools use is a per-command `SPEND_OK`, and posting deserves at least its
equivalent. Do not build a permissions system; `role` is recorded and enforced
nowhere, and turning it on is a bigger decision than this task.

## 3. The job registry

`app/jobs.py` is a module-level dict, one process, one worker — that is
deliberate and stays. It is also unscoped: an unauthorised caller saw a job
labelled "Mike's private render" and got 200 from `POST /api/jobs/1/cancel`.
Put an owner on the job record at `create`, filter `/api/jobs` and
`/api/jobs/stream` by it, and 404 the per-job routes for anyone else. In-memory
is fine; unattributed is not.

## 4. The test that makes this unrepeatable

**This is the most valuable hour in the task.** `tests/test_tenancy.py`'s static
test passes on every bug above, because it parses SQL against
`db.OWNED_TABLES` — it audits the list, so a table missing from the list is
invisible to it. Two additions:

- **A route-signature test.** Walk the app's route table; every `/api` route
  whose signature does not declare `current_account_id` fails, unless it is on
  a small, explicitly commented exempt list (`/api/capabilities` and the
  presets endpoint are plausible members; justify each one in the comment).
  This is the test that would have caught all three tables at once.
- **A schema test.** Every table with rows a user creates either has
  `account_id` or is named in a `SHARED` tuple beside `OWNED_TABLES`, with the
  reason. That tuple is BACKLOG #11's first bullet and it belongs here: the
  learning tables are global *by decision*, and writing the decision down is
  what stops a future session "finishing the migration."

Note when you enumerate: `ideas`, `pitch_runs`, `channels`, `scheduled_posts`,
`corrections`, `settings`, `winning_prompts`, `scout_findings`, `prompt_scores`,
`inspiration_accounts`, `scout_bin`, `concept_locations`, `metrics`,
`eval_runs`, `eval_golden` all currently have no `account_id`. Most are the
shared brain and should land in `SHARED`. `channels` and `scheduled_posts` are
**not** obviously shared — a channel carries post targets, and that is the
publishing path again. Decide each one out loud in the report.

## 5. The two numbers

- Set the five `*_GLOBAL_DAILY_CAP` values deliberately in `.env.example` with
  a comment saying the arithmetic is roughly (per-account cap x people). The
  defaults equal one account's cap, and it is measured: six renders under a
  second account produce `daily ceiling: 6/6 ... across all accounts` for Mike.
- `src/veo.py` defines no `SPEND_ENV`. Runway, midjourney and higgsfield all
  do. Add `VEO_SPEND_OK` in exactly their shape and wire it the way
  `runway.generate_video` wires its own. `veo.estimate_cost(6)` is **$19.20**;
  it is the most expensive tool in the repo and the only ungated one.

---

# Part two — the RAG provenance gap

The dry run could not test this: the container had no Postgres. Claude Code on
his Mac can, with `RAG_DATABASE_URL` from `.env`.

## What is actually true in the code

`rag_documents` has a `project` column (`src/rag.py:49`) **and** an index on it
(`:56`). `query` filters on it (`:218`). `retrieve_references` takes it and
passes it down (`:238`). `crag` threads it through both its calls (`:93`,
`:108`).

And **no caller ever supplies it.** The five real retrieval sites —
`rework.py:147`, `director.py:180`, `shootgen.py:243` and `:252` — all call
without `project`. Exactly one site writes it: `app/api.py:1923`, the deny
handler, which sets it to the concept's **brand**.

So today the column is written by one route, read by nobody, and the plumbing
to use it is already finished. Verify all of that against the live store before
changing anything — `rag.sources()` (`:273`) groups by source/domain/project and
will tell you in one query what is actually labelled.

## The question to answer, then the smallest change

Mike's decision, recorded in BACKLOG #11, is that **the learning loop stays
global** — "the entire app learns as it goes and gets better, that is the loop."
This task does not relitigate that. A label is not a fence.

The failure mode it guards against: with N users and no label, every shelf gets
noisier per user instead of smarter — the network effect running backwards.
Mike's denials and a pilot's denials land in the same undifferentiated pile, and
his next concept is grounded on a stranger's taste with no way to tell.

So: **everyone still reaches every lesson; your own neighbourhood ranks first.**
Concretely —

1. Decide what `project` means, once, and write it in `rag.py`'s docstring. It
   is currently the brand at the only write site. Brand and account are
   different keys and the deny handler picked one by accident. Pick on purpose.
2. Write it at **every** ingest site, not just the deny handler. Find them all
   (`ingest_records` callers) — `promote_winners`, the library ingest at
   `/library/ingest`, the gold-standard seed, and whatever else the grep turns
   up. An unlabelled row is one that can never be ranked.
3. Rank rather than filter: pass the caller's label down from the five
   retrieval sites, and prefer the matching neighbourhood without excluding the
   rest. `query`'s current `project = %s` is a hard filter — that is a fence,
   and a fence is the thing Mike said he does not want. A second ordering term,
   or a wider fetch re-sorted, keeps the shelf global while making it yours
   first.
4. Backfill what exists, or say in the report why it cannot be backfilled
   honestly (rows whose origin is genuinely unknown are better left NULL than
   guessed — and a NULL must still be retrievable, or the shared brain
   silently shrinks).

Measure it before and after on the real store: same query, same k, what comes
back and in what order. A change to grounding that nobody measured is how the
concept generator quietly gets worse.

---

## What to produce

- Part one as its own commit, suite green, with the new tests failing against
  the old code (prove that — a regression test that passes before the fix is
  not a regression test).
- Part two as its own commit, with the before/after retrieval measurement in
  the message or a short doc.
- Update `docs/PILOT_DRY_RUN.md` with a "fixed" line per finding, mark BACKLOG
  #12 shipped, and remove the warning banner from `docs/PILOT.md` **only** if
  items 1–3 of that report's fix order are genuinely done.
- Write what you learned into project memory (update `pilot_dry_run.md`; add
  the RAG answer to `references.md` or its own file) and index it in
  `MEMORY.md`.

## Done means

An unauthorised caller — signed in with zero memberships, which is the state a
Google sign-up lands in — gets 404 or 403 on every route in the dry run's
"blocks the invite" list, proven by a test that runs; the caps and the veo gate
are set; the RAG shelf has a label that means something and a measurement
showing what it changed. And `pytest tests/` is still green.

**Verify by running it, not by reading it.** Every real bug this project has
had passed review and passed its own tests — including all three of the tables
above.
