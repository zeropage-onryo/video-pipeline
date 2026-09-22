# Overnight 2026-09-21 — handoff to Claude Code

Mike approved all six items below on 2026-09-21. A Cowork session started them,
then Mike asked to move the work to Claude Code (Cowork can't push to GitHub
from its sandbox). Nothing below has been committed yet.

**Rules for this run:** one branch + one PR per item, off `origin/main`. Don't
merge. No renders, no generation, no paid calls. Run
`venv/bin/python -m pytest tests/ -q` and `venv/bin/ruff check .` before every
push. Leave `0001-fix-web-composer-refs-on-guide.patch` and
`0002-guide-brain-tier.patch` at the repo root alone (from 2026-09-18, not
part of this run; ask Mike about them).

## 1. FIRST — commit the Supabase egress fix (urgent: costing money)
It's sitting uncommitted on `main` in exactly these four files:
`app/api.py`, `src/preprod.py`, `tests/test_api.py`,
`web/src/components/studio/shell.tsx`.
- `preprod.queue_candidates`: a lean query of just the columns the rule needs,
  pre-filtered in SQL, over the same window as `list_concepts`.
- `api._is_waiting`: the one shared waiting predicate. `queue_count` now counts
  off `queue_candidates` and no longer builds every card (~1 MB per poll before).
- `shell.tsx`: the badge only polls while the tab is visible.
- New test: `test_the_lean_queue_count_matches_the_listing_ungrounded_included`.
Branch `perf/queue-count-egress`, run the tests, push, open a PR. Mike merges;
Vercel deploys web from main and the API needs a `fly deploy`. Also check
whether any other poller pulls `list_concepts` on a timer.

## 2. BACKLOG #18 — a failed provider submit leaves no `generations` row
#361 on Higgsfield `kling2.1` failed with HTTP 423 and left no row. Read
`src/higgsfield.py`'s never-raises edge for where the row is written relative
to the submit, then check `runway.py`, `fal.py` and `veo.py`. Write a test per
adapter where a submit raises and the row still has to exist (failed, with the
error redacted by `_safe_error`). If `src/charge.py` holds before the submit,
also assert that the hold is released on this path.

## 3. BACKLOG #19 — the React Queue hides the other brand, and the switch is dead
`web/src/app/studio/queue/page.tsx` shows only the active brand's cards (15 of 18
were invisible). ANTIHERO in the account menu sends no `/brand` request.
Fix: the menu POSTs `/brand/{name}` through the Next proxy (so the cookie is
first-party), then refreshes `/api/me` and the Queue.

## 4. Instagram long-lived token refresh
It expires after about 60 days and nothing refreshes it (BACKLOG #4). Add a
refresh step to `src/refresh_metrics.py`'s sweep before the IG pass
(`graph.instagram.com/refresh_access_token`, `ig_refresh_token`). The token
lives in `.env`, so store the refreshed one where the code already reads it, or
if that's only `.env`, have the step print a loud warning with days left and
the exact update to make. Never print the token. Tests go through the module's
one HTTP seam.

## 5. BACKLOG #0 leftover — cards draw full-size photos
The server already sends `photo_thumbs`, and `_concept_card` may need a
parallel `ref_thumbs`. Point `app/static/zpf/queue.js`, `scenes.js` and
`web/src/components/studio/concept-card.tsx` at the thumbnails, falling back
to `?thumb=1`. **Never change `refs` or its order**: `refs[0]` is the frame
Runway anchors the clip on.

## 6. Fix the contradictions in CLAUDE.md
- "0 concepts carry a `media_url`" sits beside "THE LOOP CLOSED on 2026-09-18
  (1 concept)". Delete the stale paragraph.
- The billing section says "every adapter holds credit before its submit
  (`src/charge.py`)", but the pricing section says step 6 is "Not built". Check
  the code to see which is true and fix the other.

## Known noise
On a clean `main` (fa71ae6), `tests/test_creative_guide.py::test_guide_job_is_owned_and_does_not_create_scenes`
failed in a Linux container because it connected to `127.0.0.1:5432` and ignored
`TEST_DATABASE_URL`. Look into it if it fails for you too. It may be a real test
isolation bug.

## Outcome (Claude Code, night of 2026-09-21 → 22)

One branch + PR per item off `origin/main` (c530778), none merged; full suite +
ruff green on each; no renders, no paid calls.

1. Egress fix — PR #48 `perf/queue-count-egress`. Rebased by hand onto #45's
   rewrite of the badge effect. No other poller pulls the listing on a timer.
   API needs a `fly deploy` after merge.
2. BACKLOG #18 — already PR #46 `fix/failed-submit-leaves-a-row` (open, per-adapter
   tests, hold released, error redacted). Not redone.
3. BACKLOG #19 — already merged as PR #45 before this run. Not redone.
4. Instagram token refresh — PR #51 `feat/ig-token-refresh`. `.env` is never
   written; a NEW token goes to `data/ig_token.json` and `access_token()` serves
   it while `.env` still holds the one it replaced. Never printed.
5. BACKLOG #0 leftover — PR #49 `perf/card-ref-thumbs`. `ref_thumbs` parallel
   to `refs` (card + timeline parts); `refs` untouched, pinned by test.
6. CLAUDE.md — PR #50 `docs/claude-md-contradictions`. Step 6 IS built
   (`src/charge.py`); the "Not built" paragraph was the stale one.

Known noise: the creative_guide failure did not reproduce (four full runs).
The one real catch: a new module-level Path under `data/` must be registered
in conftest's `OUTPUT_ROOTS` (`tests/test_output_roots.py`).
