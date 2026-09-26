# Task: Instagram, after the tokens (2026-09-26)

Follows PR #67 (`9855a0c`, `feat/instagram-tokens`). Read `CLAUDE.md`,
`src/instagram.py`, `src/autopilot.py`, `app/api.py` `holds_post`, and
`src/scout.py` `gather_instagram` before writing code.

Branch off `origin/main` (one branch per task below, or one branch for 1+2
and one for 3+4). Commit, don't push; Mike pushes.

## Where things stand (checked 2026-09-26, read-only)

- **`IG_ACCESS_TOKEN` (publishing) is VALID**: @zeropage.ai, 59 days left.
  Both the `.env` copy and the refresh store (`data/ig_token.json`) work.
  The nightly sweep's refresh last ran on 09-26 at 02:00.
- **`IG_GRAPH_TOKEN` (research) is gone from the local `.env`.** It was a
  short-lived token pasted in by hand and expired on 09-01; that was the
  source of the 09-05 "Session has expired" errors. There is no replacement
  yet, because the research app doesn't exist.
- **Fly (`zeropage-studio`) still has secrets named `IG_ACCESS_TOKEN`,
  `IG_GRAPH_TOKEN` and `IG_USER_ID`.** Their values are unknown. The
  `IG_GRAPH_TOKEN` there is almost certainly the same dead one. Fly keeps
  its own refresh store on its `/app/data` volume.
- **Posting posture.** The zeropage channel is on `queue` and targets
  `instagram,youtube`; antihero is on `shadow`. A hold row posts only when
  someone clicks Post (`POST /api/holds/{id}/post`), and that also needs
  `ZEROPAGE_POST_OK=1`. `AUTO_POST_BRANDS = ()`.
- **hold_queue:** 418 rows are `held`, and **none of them carries postable
  media** (no clip URL, no `image_url`).
- `ops.ig_tokens check|refresh|publish|research` exists, and the nightly
  preflight logs `!!! INSTAGRAM TOKEN NEEDS YOU` for any token that needs a
  person.

## Hard rules (unchanged from the last task)

- Post nothing. Don't call a publish endpoint, don't run autopilot or
  `scheduling run --live`, and don't click Post.
- Don't change `hold_queue` rows in the live database. Reading them is
  fine, and so is changing test fixtures.
- Never print or log a token value.
- No `ig_hashtag_search` calls: that spends Meta's budget of 30 tags per
  7 days.
- No scraping or logged-in-session crawling of Instagram.
- Don't touch the ZeroPageFilms app's use case or login type.
- Tests run the way CI runs them. In a worktree that means
  `PYTHONPATH=$PWD ../../../venv/bin/python -m pytest tests/ -q`, because
  the venv's editable install otherwise imports the MAIN checkout. Keep
  ruff clean.

---

## 1. Fix the double post on a partial fan-out (bug, do this first)

`holds_post` builds one post action per channel target and hands all of
them to `autopilot.execute`. That function runs the actions in a loop with
no per-action handling, so the first exception aborts the loop.
`holds_post` then answers 502 and **does not resolve the hold**.

Here is what happens on the zeropage channel (`instagram,youtube`) with R2
configured:

1. Instagram publishes. Meta fetches the public R2 URL, so this succeeds.
2. YouTube raises `youtube post action has no local video file`, because
   `youtube.execute_post_action` uploads bytes and refuses an `http` URL.
   It would also raise without `YT_*` OAuth.
3. The hold stays `held` and the Post button stays live.
4. The next click publishes to Instagram **again**.

`scheduling.run_due` doesn't have this problem, because each of its rows
names one platform.

Fix it so a post is never repeated:

- Make `autopilot.execute` record a result per action instead of aborting
  at the first failure. Return `executed`, `failed: [{platform, error}]`
  and `posted: [{platform, media_id}]`. Redact errors the way `run_due`
  already does, using `instagram._safe_error` and `tiktok._safe_error`.
  Check every current caller of `execute` (`run_due`, `holds_post`,
  `app/main.py`'s `/post-image`) and keep what each one relies on. `run_due`
  currently depends on the executor raising, so give it an equivalent.
- `holds_post`: when at least one target posted, record which ones on the
  hold, and make the next click skip those targets. A payload field such as
  `posted: {"instagram": "<media_id>"}` works (`to_hold`/`get_hold` already
  carry the payload). Resolve the hold as `posted` only when every target
  has posted, or leave it `held` and say "posted to instagram; youtube
  failed: …".
- Add a regression test for exactly the scenario above: Instagram succeeds,
  YouTube raises, you click twice, and Instagram's executor is called
  exactly once.

## 2. A hold can reach a rendered clip (gap)

All 418 held rows are unpostable, because `holds_post` reads only
`payload.clips` / `payload.image_url` and the nightly graph never renders
(`ZEROPAGE_RENDER` is off). Renders land on the CONCEPT: the Queue's
approve and the manual lane write `shot["media_url"]`, and a timed scene
also has `timeline.parts[].media_url`. The hold never learns about them. So
a scene that was rendered after its run parked can still never be posted
from its hold.

- In `holds_post`, when the payload has no media, fall back to the hold's
  `concept_id`, reading it through the same accessor `autopilot.build_plan`
  uses. For a timed scene, the scene's `media_url` is shot 1's clip and is
  **not** a finished cut (the edit is Mike's, in Resolve). Decide whether a
  timed scene is postable at all. The safe answer is to refuse, with a
  reason, until an edited cut is attached.
- Before writing code, report how many held rows' concepts carry a
  `media_url` today, using a read-only query. The concept that went through
  the whole loop, #375, is one of them if it has a hold.
- Add tests: a hold with no clips and a rendered concept builds a post
  action with that URL; a timed scene is refused with a reason.

## 3. The hashtag half needs its own switch (before the lane goes on)

When `gather_instagram` runs, it calls `hashtag_top_media` for up to 3 tags
per brand (`INSTAGRAM_TAGS`). Each tag that has never been looked up spends
1 of Meta's 30 per 7 days. Hashtag search also needs the **Instagram Public
Content Access** feature, which requires App Review, and Mike hasn't
decided on that. So flipping the lane into the defaults, as the PR #67
description says to, would fire three calls a night that fail and may
still count against the budget.

- Put the hashtag half behind an explicit opt-in, `SCOUT_IG_HASHTAGS=1`,
  off by default and read per call. With it off, `gather_instagram` runs
  `business_discovery` only and says so once per pass, not once per tag.
- When a hashtag call fails with a permission or feature error, remember it
  in a `settings` row or beside `ig_hashtag_ids`, and stop trying for 7
  days. A lane that fails the same way every night is noise in `errors`.
- Update `.env.example` and CLAUDE.md's Instagram research-lane paragraph.
- The existing 15 tests in `tests/test_scout_instagram.py` must still pass.
  Add tests for: the switch off (no hashtag function called), and a
  permission error remembered and not retried.

## 4. Getting a token into Fly without printing it (small)

`ops.ig_tokens refresh|publish|research` writes `.env`, but Fly's copies
(see "Where things stand") get updated only by hand, and the obvious
command is `fly secrets set IG_ACCESS_TOKEN=<value>`, which puts the value
into shell history.

- Add `ops.ig_tokens fly-export NAME [NAME...]`. It writes `NAME=value`
  lines for the named IG variables to stdout, for piping into
  `fly secrets import -a zeropage-studio`. It **refuses when stdout is a
  TTY** (`sys.stdout.isatty()`), with a message showing the pipe, so the
  value can't land on screen. Allow only `IG_ACCESS_TOKEN`,
  `IG_GRAPH_TOKEN`, `IG_USER_ID` and `IG_BUSINESS_ID`. For
  `IG_ACCESS_TOKEN`, export what `instagram.access_token()` serves (it may
  be the stored replacement).
- Document the one-line pipe in `ops/ig_token.sh`'s header and in each
  `say(...)` that currently tells the person to run `fly secrets set`.
- Add tests: the TTY refusal, the allow-list, and that the stored
  replacement wins over `.env`.
- **Do not run it against Fly.** That's Mike's step.

## Not in scope. List these back to Mike, don't attempt them

- Creating the "ZeroPageFilms Research" app, getting the short-lived token,
  and running `bash ops/ig_token.sh research --app-id <id>`.
- Removing the dead `IG_GRAPH_TOKEN` from Fly
  (`fly secrets unset IG_GRAPH_TOKEN -a zeropage-studio`), and checking
  Fly's `IG_ACCESS_TOKEN` (`fly ssh console -C "python -m ops.ig_tokens check"`).
- The Meta App Review decision for hashtag search.
- Adding `"instagram"` to `scout()`'s default lanes. Do that after
  `ops.ig_tokens check --probe` shows `business_discovery` answering, and
  after task 3 lands. The one-line diff is in the PR #67 description.
- YouTube OAuth (`YT_*`). Until it exists, zeropage's `youtube` target
  always fails, which is exactly what makes task 1 urgent.
- What to do about 418 held rows that grow by about 20 a night. Aging them
  out is a posture decision; don't make it.

## Report

Report in this order:

1. Task 1: what an Instagram-succeeds / YouTube-fails click does now,
   shown with the test.
2. Task 2's read-only count.
3. What changed, per task.
4. Test counts and ruff.
5. The not-in-scope list.
