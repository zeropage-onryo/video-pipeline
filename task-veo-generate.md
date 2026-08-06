# Task — Veo 3 connector (prompt → video → pipeline)

Wire the `generate` executor `autopilot.py` left unwired: send a shot prompt to **Veo 3** via the
Gemini API, poll the long-running job, download the mp4, and hand it back to the pipeline as a real
generated clip. This is the round trip — prompt out, video back — and its output is what the
Instagram scheduler then posts, closing **generate → host → post**.

Read `src/gemini_utils.py`, `src/autopilot.py`, `src/promptgen.py`, `src/shot.py`,
`src/generative.py` / `src/genlog.py`, and `CLAUDE.md` before writing code.
**Start in plan mode; show the plan before editing.**

## How you actually use it — you pick the keeper, and you watch your prompting

The point isn't headless generation. It's **you in the loop**: a prompt produces **several
candidate clips**, you **see the options and choose the final result**, and every pick (and every
reject) is logged so you can **see how your prompting is doing** over time. This is the same
footage-first rule the whole project runs on — *the human choice is the label, and it gets
recorded* — applied to Veo. `genlog`/`generative.py` already model exactly this
(`attempts_to_keeper`, `tool_scoreboard`, grouped `reject_reason`); this task fills them with real
Veo data.

So there are **two paths over one connector**:

- **Interactive (primary — build this first):** studio → generate N candidates for a shot → review
  them side by side → keep one / reject all and regenerate. Each batch is an explicit, cost-shown
  action you approve; no autopilot gate needed, because *you* are the gate.
- **Headless autopilot (later, L4):** the same `veo.generate_*` functions behind
  `autopilot.EXECUTORS["generate"]` and its full gate, for when you want it to run without you.
  Build the connector so both paths call the same core — the interactive one just adds the review
  UI on top.

## Why this drops in cleanly

- **Same SDK, same key.** Veo runs on `google-genai` (`from google import genai`) with the project's
  existing `GEMINI_API_KEY` — the same client `gemini_utils` already builds. No new dependency, no
  new secret.
- `autopilot.EXECUTORS["generate"]` is `_unwired("generate")` today. This task registers the real
  adapter there. The gate (`ZEROPAGE_AUTOPILOT` + per-run `--approve` + kill switch, dry-run
  otherwise) is untouched — and it matters more here than anywhere, because **every call costs real
  money**.
- `shot.py` + `promptgen.py` already turn a loose description into a well-formed prompt string;
  Veo's adapter consumes that string. `genlog.py`/`generative.py` already track attempts per tool —
  a Veo generation is logged there like any other.

## The Veo call pattern (verified against Google's docs, Aug 2026)

Async: submit → poll operation until done → download. Files live on Google's server **2 days
only**, so download immediately. Latency ranges ~11s to ~6 min, so polling is mandatory.

```python
from google import genai
from google.genai import types
import time

client = genai.Client()  # uses GEMINI_API_KEY

operation = client.models.generate_videos(
    model="veo-3.1-generate-preview",          # or "veo-3", "veo-3-fast"
    prompt=shot_prompt,
    config=types.GenerateVideosConfig(
        aspect_ratio="9:16",                   # portrait for reels; "16:9" default
        resolution="720p",                     # "1080p"/"4k" require 8s duration
        # duration "4" | "6" | "8"
    ),
    # image=first_frame,                        # optional image-to-video
)

while not operation.done:
    time.sleep(10)
    operation = client.operations.get(operation)

video = operation.response.generated_videos[0]
client.files.download(file=video.video)
video.video.save(out_path)                     # download NOW — server keeps it 2 days
```

Model IDs: `veo-3.1-generate-preview` (current), `veo-3` / `veo-3-fast` (stable). Config surface:
`aspect_ratio` 16:9 / 9:16; `resolution` 720p/1080p/4k; `duration` 4/6/8s (1080p/4k force 8s).
Image-to-video via `image=`. Confirm the model id + params against the Veo docs before a live run —
Google versions these.

## Contracts to preserve

1. **Never raises at the edge.** The public orchestrator returns `{"ok": bool, ...}` like
   `youtube.refresh_metrics_for_video` — a missing key, a failed job, or a timeout is a result, not
   an exception that takes the run down. Redact the key from any error text (`_safe_error` pattern).
   The thin SDK wrapper may raise; its caller catches.
2. **The gate is sacred, and this is the expensive side of it.** The real `generate_videos` call
   runs **only** through `autopilot.execute` in `live` mode. Dry-run must describe the prompt it
   *would* send and call nothing. No second path that spends money outside the gate.
3. **Reuse `gemini_utils`.** Build the client the same way; reuse retry/backoff on transient errors
   (`RESOURCE_EXHAUSTED`/`UNAVAILABLE`) with a bounded budget. Don't hand-roll a second retry.
4. **Hermetic tests.** Patch the `genai` client / the SDK wrapper; `tests/conftest.py` blocks the
   network. No test may reach Veo (it would bill). Patch what the code under test calls.

## 1. `src/veo.py` — the connector

- `MODELS` / default constant + a dated comment (versions move).
- `generate_video(prompt, out_path, *, model=DEFAULT, aspect_ratio="9:16", resolution="720p",
  duration="8", image=None, client=None, poll_delay=10, timeout_s=600)` — thin wrapper: submit,
  poll until `operation.done` or `timeout_s`, download to `out_path`. Raises on failure/timeout.
- `generate_candidates(shot_or_prompt, out_dir, n=3, db_path=None, **cfg)` — the never-raises edge
  you actually use: generate **N candidate clips** for one prompt (via the SDK's candidate count if
  supported, else N calls), download each, log every attempt through `genlog` (tool = the Veo
  model), and return `{"ok", "candidates": [{path, attempt_id, model}], "error"}`. Files land under
  `footage/generated/<concept>/<shot>/` with deterministic names. This is what lets you *see the
  options*.
- Env: `GEMINI_API_KEY` (already required). Optional `VEO_MODEL` / `VEO_RESOLUTION` / `VEO_CANDIDATES`
  overrides.

## 1b. Review & pick the keeper (the primary UI)

A studio review surface — extend the `/shots` screen BUILD_SPEC already scoped, now with real data:

- After a generate batch, the N candidates show **side by side** as playable tiles, with the exact
  prompt that produced them printed above.
- **Keep one** → `genlog` records it kept (feeds `attempts_to_keeper`); the kept file becomes the
  shot's generated clip. **Reject all → regenerate** → each reject logs a **reason** (a short
  datalist-backed field), because grouped reject reasons tell you *which failure your prompts keep
  inviting* — more actionable than a hit rate.
- Nothing is auto-selected. Ever. You choose, or you regenerate. The pick is the label.
- Generating a batch is an explicit button that **shows the estimated cost first** ("3 candidates ≈
  $X") and confirms before spending.

## 1c. "How my prompting is doing" — the performance surface

The reason to run this before trusting it. Surface, on `/shots` and the dashboard, from
`generative.py`'s existing scoreboards now that they have real Veo rows:

- **Attempts to a keeper**, per prompt and overall — the single number that says whether your
  prompting is landing. Trending down = your prompts are getting better.
- **Tool scoreboard** — Veo vs. (later) Kling/Runway hit rates, same board.
- **Grouped reject reasons** — the recurring failure modes your prompts invite, ranked.
- **Which prompt phrasings landed in 1–2 tries** — `winning_prompts()`, so good prompts become
  examples fed back into `promptgen` (your own record, not generic advice).

This is the trust meter: you don't flip on any headless generation until these numbers say the
prompts are good enough.

## 2. Register the generate adapter in `autopilot.py` (later, stays off)

Wire `EXECUTORS["generate"]` to the same core (`veo.generate_candidates`, auto-keeping only when you
later choose to trust it) so the headless L4 path exists — but it remains behind the full gate and
**off** until the performance surface in §1c says the prompts are good enough. Until then, autopilot
`generate` in dry-run just previews the prompt. The interactive path in §1b is how content actually
gets made for now. Keep dry-run touching nothing; preserve every existing autopilot test.

## 3. Close the loop to posting

Once a shot has a generated file, it needs to reach a **public URL** for Instagram (`video_url` must
be fetchable by Meta) — the generated mp4 gets uploaded to the configured public bucket, and that
URL is what `scheduling.py` schedules. Note this handoff; the actual bucket upload can be a small
`storage.py` helper or a follow-up task — flag it, don't silently skip it. (Veo's 2-day server
retention is exactly why the file is downloaded and re-hosted, not linked from Google.)

## 4. Tests (hermetic, network blocked)

- `generate_video`: polls until `operation.done`, returns/saves the file (SDK fully mocked); raises
  on timeout; passes config through correctly.
- `generate_candidates`: returns N candidate paths; logs one `genlog` attempt per candidate;
  returns `ok:false` on wrapper failure without crashing the batch.
- review actions: keeping a candidate records it kept in `genlog` and sets it as the shot's clip;
  rejecting all records each reason; nothing is auto-selected.
- performance surface: `attempts_to_keeper` / `tool_scoreboard` / grouped reject reasons render from
  seeded rows (pure DB, no network).
- `autopilot`: with the adapter registered, `disabled`/`unapproved`/`dry-run` execute 0 and never
  touch `veo`; `live` calls it. A dry-run `run` **spends nothing** (assert the SDK is never called).

## 5. Verify by running it

```bash
venv/bin/python -m pytest tests/ -q      # green incl. new files
venv/bin/ruff check .                    # clean
venv/bin/python -m src.autopilot plan    # generate actions show the Veo prompt, nothing runs
venv/bin/python -m src.autopilot run     # dry-run: previews prompts, spends nothing
```

A **live** generation is a separate, deliberate, paid step the user takes by hand:
`ZEROPAGE_AUTOPILOT=1 ... run --approve --live`. Start with `veo-3-fast` and short durations to keep
the first real spend small. Do not enable any live path in this task.

## Cost note (build the guardrail)

Veo is billed per generation (roughly per-second of output, audio included on the standard model) —
the free/AI tiers cap you at a handful of clips/day, paid scales up fast. Add a **per-day generation
cap** (config, default low) in the adapter as a runaway guard, and surface estimated cost in the
dry-run preview so a plan with 40 shots reads as "40 generations ≈ $X" before anyone approves it.

## Out of scope

Multiple providers in one call (Kling/Runway are their own adapters behind the same `generate`
seam — the renderer split in `shot.py` already anticipates this), upscaling, the public-bucket
uploader beyond a flagged helper, and any live spend. Confirm the current Veo model id + pricing
against Google's docs at build time.

## Sources
- [Generate videos with Veo (Gemini API) — Google](https://ai.google.dev/gemini-api/docs/veo)
- [Veo — Google Gen AI Python SDK](https://googleapis-python-genai-70.mintlify.app/guides/veo)
- [Veo 3 API pricing 2026](https://www.veo3ai.io/blog/veo-3-api-pricing-2026)
