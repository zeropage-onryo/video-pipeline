# Task — get a week of work onto main

**Hand this whole file to Claude Code, on the Mac.** It cannot be done from the
cloud bridge: `git merge` needs two index-lock cycles and the FUSE mount
refuses the unlink, so every merge attempt dies on a stale lock. On the Mac
git works normally.

One session, an hour or two. It writes almost no code.

## Why this is the next task and not the cost tracker

`main` is at `9444f23`, 2026-08-29. **Thirty-three commits are ahead of it** —
account tenancy, the research node, both pilot dry runs, all three fixes — and
main carries three commits no branch has (`9444f23` assets archive, `93c49ff`
CRAG eval, `6f43338` README). A trial merge already conflicts in **12 places**,
and that number only grows.

Two consequences, both live:

- **It is not backed up.** Only `main` and `build/spine` have ever been pushed.
  A week of work exists on one disk.
- **New sessions have no trunk to start from.** There are ~20 `claude/*`
  branches, several of which have merged each other; sessions have been
  branching off whatever they happened to land on. That is why two independent
  pilot dry runs happened on the same day and neither knew about the other.

## What to merge

`claude/pilot-merged` (`03b5fef`) is the tip of the real line. It contains
`9e28d67` (Midjourney into scene_chain, the `.env.*` gitignore fix),
`51a39a8` (the three tables, the route + schema tests, the caps, VEO_SPEND_OK),
`12a1573` (rag_documents.project as the tenant) and `03b5fef` (the render path
and the job-closure owner, plus both dry-run reports merged into one).

Merge it into `main`. Not the other way round.

## Ground rules

1. **The working tree has another session's uncommitted work in it** —
   `src/imagesearch.py`, `src/framebank.py`, `ops/build-frame-bank.py`,
   `tests/test_imagesearch.py`, `ops/pinterest-bank.py`, `ops/ig_token.sh`,
   plus modified `src/uncanny_judge.py`, `src/winners.py`, `src/shootgen.py`,
   `app/main.py` and four test files. **Commit it or stash it first, on its own
   branch, as its own commit — do not merge on top of it and do not sweep it
   into the merge commit.** `tests/test_imagesearch.py` is the source of the
   only failures in the current suite; that is in-flight work, not a
   regression, and it is not this task's to fix.
2. `git commit --only <paths>`. Never `git add -A` — `.env.bak.<timestamp>`
   files have been one such command away from history before.
3. `venv/bin/python -m pytest -q tests/` (not bare `pytest`, which collects
   `evals/` and makes real billed calls). Expected on the merge:
   **1407 passed, 9 xfailed**, plus whatever `test_imagesearch` is doing.
4. Never touch `data/pipeline.db`. The dev server reloads on save and runs the
   app lifespan against it.

## The merge

The 12 conflicts are concentrated where the last week rewrote things the three
main-only commits also touched. Resolve on meaning, not on markers:

- **Scoping always wins.** If a conflict is between a call that passes
  `account_id` and one that does not, the one that passes it is correct. The
  whole week is that change. Same for `prefer_project=` on retrieval calls.
- **`db.OWNED_TABLES` and `db.SHARED_TABLES` must end up complete.** Every
  table belongs to exactly one of them; `test_every_table_is_owned_or_declared_
  shared` fails otherwise, which is the point of it.
- The three main-only commits are additive features (an assets archive, a CRAG
  eval, a README line). If one of them reaches an owned table without an owner
  predicate, the static SQL test will say so — fix it there rather than
  merging it as-is.

After resolving, **run the suite before committing the merge**, and read
`test_tenancy.py`'s failures first if there are any: that file is the safety
net for everything this week bought.

## Then verify the merge, don't assume it

The merge is exactly the moment a scoping fix gets silently reverted by a
conflict resolution. So re-run the dry run's own probes against the merge
result — the method is in project memory (`pilot_dry_run.md`) and takes about
ten minutes:

- as a second account: `/api/holds`, `/api/workflows`, `/api/jobs` all empty;
  resolve, post-now, canvas PUT and DELETE all 404
- as a signed-in user with **zero memberships**: 403 everywhere
- as the owner: the board still loads, and
  `runway.generate_for_shot(<an owned concept>, 1, ...)` does **not** answer
  `no concept N`

That last one is the regression that already happened once. It fails closed,
so nothing looks broken until someone clicks render.

## Then push

`git push origin main`. Confirm first, in the browser, whether
`github.com/zeropage-onryo/video-pipeline` is **public or private** — the badge
is next to the repo name — and say which in the report. If it is public, that
push makes a week of work public; nothing in it is a secret (`.env` has never
been committed on any branch, verified across all refs), but it should be a
decision rather than a side effect.

## Then delete the dead branches

~20 `claude/*` branches and a dozen prunable worktrees under
`.claude/worktrees/`. Anything now merged into `main` is dead weight; anything
NOT merged is either lost work or a deliberate parking spot, and the difference
matters. `git branch --merged main` lists the safe ones. For each branch not
merged, say in one line what is on it and whether it should be kept — do not
delete an unmerged branch without saying what dies with it.

The goal is that the next session that runs `git branch` sees a trunk and a
handful of live branches, not a graveyard it has to guess its way through.

## What to produce

- `main` carrying everything, suite green, pushed.
- The probe results above, pasted, not summarized.
- A one-line inventory of every branch kept or deleted, in the commit message
  or a short `docs/` note.
- Project memory updated: the trunk is real again, and what the branch policy
  is from here.

## Done means

`git log --oneline main -1` is `03b5fef`'s merge, `git status` is clean apart
from the other session's in-flight files, the probes pass, origin has it, and
`git branch` fits on one screen.
