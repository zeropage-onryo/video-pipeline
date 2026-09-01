# Task — make every Dev Studio button do what its label says

Second pass, 2026-08-31 15:2x, against `studio-composer-merge` @ `18af95d` and the live
`data/pipeline.db`. Supersedes the 08-29 draft; the environment half of that plan is already done.

**Baseline before you start:** `ruff check .` clean. Suite is 1059 tests — **1049 pass, 9 xfail,
1 fails**, and that one failure is item 5 below, not something you broke.

**Out of scope by Mike's call:** pressing Run eval. Do everything else; he'll exercise that last.

## Already done — do not redo

| Item | Evidence |
|---|---|
| Store unreachable | `.env` now carries `RAG_DATABASE_URL`. |
| 14 parked lessons | `SELECT SUM(ingested) FROM winning_prompts` = 14 of 14. Backfilled. |
| Nightly job on a dead path | Plist now points at `…/PRODUCTION PIPLINE .GIT/run_morning_prompts.sh`. |
| Untracked strays | `.gitignore` now matches `data/ref_contact_sheet.jpg` and `data/zpf-src.tar.gz`. |
| Weekly eval gate | Shipped in `52422f6`; `workflow_dispatch` present in HEAD's `ci.yml`. |

## Two corrections to the first draft — read before touching the kill switch

**1. There are two kill switches and they are not the same thing.**

- `autonomy.killed()` (`src/autonomy.py:170`) — a `settings` row keyed `kill_switch`, plus the
  `ZEROPAGE_KILL` env var. This is what the Dev Studio `/kill` button toggles and what
  `src/orchestrator.py:779` checks. Its effect is to force every run to **hold** — it *feeds* the
  grading queue, it does not starve it. **The `settings` table is empty, so this switch is OFF.**
- `autopilot.killed()` (`src/autopilot.py:94`) — the file `data/autopilot.off`, read only inside
  `src/autopilot.py`, which is the posting/dispatch path. Present since 13 Aug.

`src/trigger.py` checks **neither**. So the earlier claim that `data/autopilot.off` was starving the
hold queue was wrong — nothing in the content graph is blocked. The queue is dry for exactly one
reason: item 6. Leave `data/autopilot.off` alone; it gates posting, which is a separate decision.

**2. `.git/index.lock` is not evidence of a crash.** The Cowork device bridge cannot delete files,
so every git command run through it leaves its lock behind (`warning: unable to unlink … index.lock:
Operation not permitted`). If you find one, `rm -f .git/index.lock` and move on.

## Still open

Verified unchanged at these exact lines on 08-31.

### 1. "Draw ungraded concept (3)" can never reach zero

`app/main.py:460`. The counter and the buttons under it mean different things by "graded":

```python
"ungraded_count": sum(1 for c in preprod.list_concepts(path=db.DB_PATH)
                      if c.get("judge_overall") is None)
```

`judge_overall` is set by exactly one control — **"Grade taste + perf · billed"**. Approve, Teach and
Deny route to `teach_verdict`, which writes the winners shelf and never touches it.

**Do not fix this by having the verdict buttons write `judge_overall`** — that column is the
taste-judge's billed score, and faking it corrupts `judge_taste` / `judge_perf`. Prefer relabelling
to **"Draw unjudged concept (N)"** and showing the teach count as its own number. If you'd rather
change the semantics, count a concept done when it has `judge_overall` *or* a `winning_prompts` row
whose `video_ref` matches `concept-{id}-shot-%` — but that's the bigger change, so say so in the
commit message.

### 2. Archived concepts inflate that count

`src/preprod.py:395` — `SELECT * FROM shoot_concepts ORDER BY id DESC LIMIT ?`, no `archived_at`
filter. Of the 3 concepts, 1 is archived (123, 28 Aug), so the honest count is 2.

Check callers first (`grep -rn "list_concepts" src/ app/`); if any want archived rows, add
`include_archived: bool = False` rather than changing the default for everyone.

### 3. The credit gate's denominator counts things that aren't runs

`src/autonomy.py:237`:

```sql
SELECT status, COUNT(*) FROM hold_queue WHERE status IN ('approved','rejected')
```

Four of the 16 aren't gate judgments. #1 and #2 predate the gate; #4 is a crash artifact
(`trigger crashed: no such column: verdict`, empty payload); #16 is a queued Midjourney image
(`app/main.py:1200`). None carries a `run_id`, so grading each recorded **zero** prompt verdicts via
`set_prompt_verdicts`' `if not run_id: return 0` guard (`src/autonomy.py:275`) — silently, while
still moving the graded count. Real sample is 12, not 16, against `TARGET = 25` in `grade.py:20`.

Restrict the count to holds whose payload carries a `run_id`, and give image holds their own status
or channel so they never enter the denominator. Add a test in `tests/test_autonomy.py`: a hold with
no `run_id` must not move `evaluator_agreement`.

Also make `grade.py`'s `(0 prompt score(s) recorded)` say plainly that the hold carried no run and
nothing reached the gate.

### 4. Two unreachable prompt scores

Run `aa0e3f5e8be9485bbd22f093f168eed9` (19 Aug 18:43) has two `prompt_scores` and never produced a
hold, six minutes before hold #14 did. Both grading paths find holds first, so nothing can ever set
their verdict. Backfill them from the concept they belong to, or delete them — leaving them makes
`prompt_gate_agreement`'s total permanently two larger than the gradeable population.

### 5. Two tests hardcode `/tmp/ok.mp4` — the one suite failure

`tests/test_runway.py:362` and `:426`, both added in `18af95d`. They pass on a machine where that
path is writable and fail with `PermissionError` anywhere it already exists under another owner —
a shared CI runner, a second user, a sandbox. Non-hermetic and machine-dependent.

Fix, verified working:

```python
# line 362 — add tmp_path to the signature
def test_a_prompt_at_the_cap_is_let_through(approved, tmp_db, fake_download,
                                            monkeypatch, tmp_path):
    runway.generate_video("y" * 1000, str(tmp_path / "ok.mp4"), db_path=tmp_db)

# line 403 — same
def test_the_swap_happens_before_the_length_check(asset_db, approved,
                                                  monkeypatch, tmp_path):
    runway.generate_video(prompt, str(tmp_path / "ok.mp4"), db_path=asset_db)
```

With both applied, `pytest tests/test_runway.py -q` is 23 passed.

### 6. The shadowrun job has never run

`ops/com.zeropage.shadowrun.plist` (added `52422f6`) runs `venv/bin/python -m src.trigger` daily at
**03:30**, logging to `data/trigger.log`. `src/trigger.py` and the venv both exist.
**`data/trigger.log` does not exist**, across firings on 30 and 31 Aug.

Almost certainly the plist is committed in `ops/` but was never copied to `~/Library/LaunchAgents/`
and loaded. Confirm with `launchctl list | grep zeropage`, then `cp` and
`launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.zeropage.shadowrun.plist`. Run
`venv/bin/python -m src.trigger` by hand once first — it should exit 0 and print a hold row.

This is the only thing keeping the grading queue empty. Nothing else is blocked.

## What not to change

- `runway.generate` / `runway.spend` being false is correct. `RUNWAYML_API_SECRET` is absent, and
  `spend_approved()` is deliberately per-run — "an approval that's always on isn't an approval."
  Do not move it into `.env`.
- `data/autopilot.off` — see correction 1. It gates posting, not creation.
- The `_structural_check` length ceiling was removed on purpose (`src/orchestrator.py`, 2026-08-14).
- All 24 Dev Studio form actions and links resolve to registered routes; all 18 `@dev` routes were
  re-verified present on 08-31. Nothing is unwired — don't go looking for missing routes.

## Verifying

The venvs in the repo are macOS builds. From a Linux sandbox, build a throwaway venv outside the
mounted folder, `rsync` the repo out, and run the suite in halves with `-n 16` (~40s and ~25s).
`ruff check .` runs anywhere.
