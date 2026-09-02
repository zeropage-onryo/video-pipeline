# Task — the pilot dry run

**Hand this whole file to Claude Code.** It is one overnight block, ~4–6 hours,
and it builds nothing. It answers one question: *what actually breaks the first
time somebody who is not Mike signs in?* `docs/PILOT.md` is a checklist written
from reading the code. This walks it.

Chosen 2026-09-02 over BACKLOG #2 (cost tracker) and #11 (shared brain) because
both of those build against a guess about what a second user hits, and this is
the cheapest way to stop guessing. Its output is the input to both.

## Ground rules

1. **Never touch `data/pipeline.db`.** Copy it (`cp data/pipeline.db
   data/_pilot.db`) and point every command at the copy via `ZEROPAGE_DB` /
   `db.DB_PATH` — check how the entry points resolve it and use whichever knob
   is real. The studio dev server may be running and holding the live file.
2. **Do not start the migration you are about to want.** Findings go in a
   report, not in a refactor. The one exception is a fix that is three lines
   and provably safe — commit it separately with its own message.
3. **Another session is writing `src/imagesearch.py`, `src/framebank.py`,
   `ops/build-frame-bank.py`, `tests/test_imagesearch.py`, `ops/ig_token.sh`
   and `ig-token.command` right now.** They are untracked on purpose. Leave
   them alone: never `git add -A`, always `git commit --only <paths>`.
4. Branch `claude/pilot-dry-run` already exists and is where this lands. The
   previous session's work is committed as `8f4f9b6`; the tree was green at
   **1354 passed, 9 xfailed** when it landed. Re-run `venv/bin/python -m pytest
   -q tests/` (not bare `pytest` — `evals/` makes real billed calls) before you
   trust any "this is broken" conclusion.
5. Real API keys: don't spend. No Runway, no Veo, no Midjourney, no Higgsfield.
   The Gemini path is cents but still unnecessary — stub or skip generation and
   test the *scoping*, which is what this is about.

## Setup

```bash
cp data/pipeline.db data/_pilot.db
venv/bin/python -m src.accounts invite pilot@example.com --brand pilot   # against the COPY
venv/bin/python -m src.accounts members
```

The live copy today holds exactly: accounts 1 `zeropage` / 2 `antihero`, one
user (`mikemassaad@gmail.com`, id 2) with owner rows on **both** — so
`current_account_id` ("oldest membership") resolves to account 2, ANTIHERO, not
the one whose name is on the door. Confirm that is still true and write down
which account actually owns the eleven-plus concepts, because half the
interesting failures are "the board is empty and nothing is wrong."

Sign-in as the pilot without OAuth: mint the `zp_session` cookie directly —
`auth._serializer().dumps({"user_id": <id>})` with `SESSION_SECRET` pinned to
the value the server is running under. FastAPI's `TestClient` is the fastest
way to walk breadth; use a real uvicorn + the container's Chromium only for the
few screens where layout is the finding.

## The walk

Do every one of these **twice** — once as Mike, once as the pilot — and record
both answers. A route that behaves identically for both is as much a finding as
one that 500s.

- `/signin`, then a fresh signup with **no** membership: PILOT.md claims "no
  account access yet". Verify the copy, and that nothing leaks behind it.
- `/ui` and every rail view: Studio, Assets, Pipeline, Director, Analytics,
  Queue. Empty is expected; *broken* empty is the finding (a spinner that never
  resolves, a 500, a capability control that renders and then 404s).
- Every `/api/*` the views call. Then the ownership probe that matters: as the
  pilot, `GET`/`POST` a **concept id you know belongs to Mike** — pick, archive,
  restore, the shot-prompt write, the Director graph read and write, the queue
  approve. Each must refuse. `app/api.py`'s `/concepts/{id}/archive` took
  `account_id` as a bare default until `8f4f9b6` and FastAPI read it as a query
  parameter — assume there are siblings and check every route's signature for
  the same shape.
- Asset creation (`POST /api/assets/locations|characters|props`) and its RAG
  side-effect. Whose shelf does a pilot's asset land on?
- `/studio` with `DEV_TOOLS=1` and again with it unset. Unset must 404. Set,
  note honestly what the pilot can see through `auth.dev_account_id`'s
  bootstrap fallback.
- The photo routes (`/locations/{space}/photo/...` and the character/prop
  twins) — they register on `app`, not `dev`, so they are reachable on a public
  deploy. Try to escape their root and try to read another account's asset.
- `/mcp` — leave `ZEROPAGE_MCP` unset as PILOT.md says, then verify that with
  it set and a token, the tools are account-scoped the way the HTTP API is.

## The suspects — check these even if the walk looks clean

Each is written down somewhere as a known risk and none has been run.

1. **The five `*_GLOBAL_DAILY_CAP` defaults equal one account's cap** (runway
   6/6, veo 6/6, higgsfield 6/6, midjourney 10/10, nano 20/20). Prove it: as
   the pilot, exhaust the global ceiling with fake `generations` rows and show
   Mike's next render refused. Then propose actual numbers.
2. **Veo has no `SPEND_OK` gate** — the $3.20/clip tool is the only one that
   needs nothing but a cap. Confirm and say what the gate should look like.
3. **`corrections` is cross-tenant.** `pending_corrections` takes every
   unconsumed note and consumes it. Write a note as the pilot, run a nightly
   generation as Mike (stub the model call), and show whose run it steered and
   that it is gone before the pilot's own night. This is the sharpest one.
4. **`rag_documents.project`** is written at exactly one site and read by no
   caller. Show what a second user's lessons do to the shelf.
5. **`taste_judge`** scores against *your* grades and *everyone's* winners, and
   its third input (`post_seo.derive_signals`) is unscoped by accident. Say
   which of those three is right and which is a bug.
6. **`app/jobs.py` is an in-process dict.** Two users, one worker: show what a
   second concurrent job does, and what a restart does to the Queue (the Queue
   is derived from rows, so it should survive — verify, don't assume).
7. `SESSION_SECRET` rotation signs everyone out; unset it is ephemeral. Confirm
   the failure mode is a clean redirect to `/signin` and not a 500.

## What to produce

`docs/PILOT_DRY_RUN.md`, ranked by **what blocks an invite** — not by severity
in the abstract. For each finding: the reproduction (the exact call), the file
and line behind it, what the user sees, and the smallest honest fix. Separate
"blocks the invite" from "breaks on the second user" from "breaks at ten."

Then update `docs/PILOT.md` where it is now wrong, add a line to
`docs/BACKLOG.md` #2 and #11 saying what the dry run settled, and commit
(`git commit --only`).

Close the loop for the next session: write what you learned into project
memory as `pilot_dry_run.md` and index it in `MEMORY.md`.

## Done means

Every route in the walk has two recorded answers, every suspect above has a
verdict backed by something you *ran*, `pytest tests/` is still green, and the
report names the one thing to fix first.

The standing rule in CLAUDE.md applies harder here than anywhere: **verify by
running it, not by reading it.** Every real bug this project has had passed
review and passed its own tests.
