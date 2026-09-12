# Zero Page studio — review and roadmap (2026-09-07)

Scope: the `PRODUCTION PIPLINE .GIT` repo as it sits on the Mac this morning, the last SQLite snapshot before the Supabase cutover (2026-09-04), the nightly logs, and the project notes from the last two weeks. Everything below is checked against the repo; where a number comes from a file, the file is named.

## The one-paragraph verdict

The studio is a very good idea machine attached to nothing. It has never produced a video by itself. Every clip that exists was made by a person (or a Claude session) driving the Runway web app by hand from a paste sheet; the API render path in `src/runway.py`, `src/veo.py` and `src/higgsfield.py` has never run for real. The `providers.py` docstring calls itself "the aggregator's registry", and that is an accurate description of the architecture: every pixel comes from someone else's model, behind their caps, their credits, their ToS. Meanwhile the codebase has grown multi-tenant auth, BYOK, a Fly deploy, a cost tracker, an MCP server and 78 test files — SaaS scaffolding for a product whose top-line output metric (posts of AI content per week) is zero. Both of your goals require inverting that: less pre-render intelligence and tenancy, more render, assemble, post, measure.

## What the evidence says

The library table `videos` holds 10 rows. All 10 are pre-existing YouTube uploads dated 2020–2026 (two short films, cocktail recipes, a haircut, a dinner fit, a motovlog, an engine clean). None were produced by the pipeline. `scheduled_posts` has 0 rows. The `generations` table has 38 rows and every one is `tool = 'nano'` — stills, not video. The `hold_queue` is 40 held, 14 rejected, 2 approved; nothing has ever been published through it. The kill switch `data/autopilot.off` has been set since 2026-08-13.

`data/renders/higgsfield/` contains 20 `.mp4` files. Every one is 2048 bytes of zeros — they are test fixtures (`tests/test_higgsfield.py:55`, `tests/test_runway.py:37` write `b"\x00" * 2048`) leaking into the real render directory because the tests write to the live `RENDER_DIR`. The 152 PNGs beside them are real keyframes. So the honest count of API-rendered video in the studio's own storage is zero.

The real clips (7 on Sep 4, 20 + 6 redos on Sep 6) live in `docs/reference-look/sprint3/` and came from the Runway web app on the Unlimited plan, driven through Chrome with scroll-harvesting JS and a "duration resets to 5s on every reload" checklist. That is a person doing the render node's job. There is no `RUNWAY_API_KEY` in `.env`; the Higgsfield Cloud API balance is 0; the Gemini prepay hit zero and the nightly log ends in `429 RESOURCE_EXHAUSTED … run crashed` repeatedly; the Instagram token has expired twice. Every night in `data/trigger.log` for the past week ends in `held='no keyframe: daily ceiling: 20/20 images'` or a DNS failure reaching the Supabase pooler.

## Deficiencies, in order of how much they block the two goals

**1. There is no render node.** The code has three adapters that share a contract, but none is funded, none is enabled (`spend_approved()` is off by default), all three default to a cap of 6 clips a day, and the orchestrator parks in `hold_queue` with render and publish as stubs "until the credit gate clears" — a gate whose agreement with your own verdict is measured at 38%, near chance (see `credit_gate.md`). The machine is designed to not spend, and it has succeeded.

**2. It is an aggregator by decision, not by accident.** Backlog #14 rejects Modal/Replicate as solving "GPU problems this repo does not have; it calls other people's APIs rather than running models." Kling, Seedance, LTX and Wan exist in `shot.PLATFORMS` as prompt vocabularies only — no adapter. There is no mention of LoRA, fine-tuning, ComfyUI, or self-hosting anywhere in `src/`. The 149 GB of ProRes in `footage/` and the seven-photo Soul training set are the raw material for an owned model and are being used for nothing but still-frame captions and reference uploads.

**3. Likeness is a prompt hack, not an asset.** The trained Higgsfield Soul "wasn't you" (Sep 6). The fix that worked is Nano Banana Pro with three real photos pasted as references on every single still, and the face still drifts in the last two seconds of a push-in. That is per-image labour with no accumulation. An identity you own has to be weights, not a reference-image ritual.

**4. Six gates before a render, none after.** Prompt gate (7/10), uncanny judge (fails closed), taste judge, story judge (built, not activated), trendable gate, likeness rule, variety enforcement, per-tool caps, the global Nano cap of 20/day, spend approval, the kill switch, and a one-tap hold. All of them predict from the prompt whether a clip will be good. The rubric analysis already showed no dimension separates what you would post. Prediction is the wrong lever when a render is cheap; selection after the render is the right one. Today the studio spends its intelligence budget avoiding a $0.25 clip.

**5. No post-production at all.** Nothing in `src/` or `ops/` touches ffmpeg, moviepy, captions, music, voice, loudness, stitching or thumbnails. The unit the studio produces is one 5–10 s clip; the unit a platform rewards is a 15–45 s post with a hook, text, audio and a cut. Editing is an "explicit L1 hold" in Resolve — i.e., the bottleneck is you, by design. A content engine cannot have a human in the assembly step.

**6. The nightly is structurally unreliable.** launchd/TCC killed it silently for eleven nights; since then the runs die on DNS to Supabase, Gemini 429s, LangSmith unreachable, and the Nano cap being spent before the job starts. A scheduler that crashes most nights on a laptop cannot accumulate output. The Fly box exists (`zeropage-studio.fly.dev`) and is not running the nightly.

**7. The learning loop learns from the wrong corpus.** `proven_results` and the taste judge are fed by ten old YouTube videos about cocktails and haircuts. Until the pipeline has posted its own AI content and measured it, "grounding in 5 performance references — what actually travelled" is grounding in noise.

**8. Distribution is thin.** Instagram reels and YouTube upload exist behind the autopilot gate; TikTok is a two-line grep hit and a "developer-app approval" note. The Higgsfield MCP already exposes `tiktok_publish`; unused.

**9. Infra-to-output ratio is inverted.** 23,700 lines in `src/`, account tenancy with an AST-walking SQL guard, Supabase Auth with Google/Discord, BYOK design, a pilot dry-run, cost tracker, MCP surface, Fly deploy — all for one user and zero shipped posts. Each of these was reasonable in isolation. Together they consumed the weeks the render and assembly nodes needed.

**10. Hygiene.** Five `.env.bak*` files with secrets sit in the repo root; tests write into `data/`; nine `pipeline.db` backups; `CLAUDE.md` is 90 KB; the 149 GB footage tree is inside the repo. None of this blocks the goals, but it slows every session that has to read around it.

## Goal 1 — make its own videos from a foundational model

Be precise about what "own foundational model" can mean for a one-person studio. Training a video foundation model from scratch is not on the table at any budget you have (it is hundreds of GPU-years). What is on the table, and what actually delivers the outcome you want — unlimited, uncapped, no-ToS, on-brand video that looks like you and your worlds — is **own weights on an open base**: an Apache-licensed base model, served on GPUs you rent or own, with LoRAs you trained on your own footage and face. That is "your model" in every way that matters: nobody can cap it, price it, refuse a Ducati logo, or change it under you.

Base model choice. Wan 2.2 (Apache 2.0, the deepest LoRA tooling — diffusion-pipe, musubi-tuner, ComfyUI — and the best I2V character-consistency results) is the default. LTX-2.5 (22B, native audio+video in one pass, multi-shot continuity, runs in 32 GB FP8) is the one to evaluate for the assembly step because it removes the separate audio problem. HunyuanVideo 1.5 has a restrictive license and limited fine-tuning; skip. Sources at the bottom.

Serving. A rented H100 or 4090-class GPU on RunPod serverless or Modal, cold-starting a ComfyUI/diffusers worker, comes in around a few cents per 5 s 720p clip at volume and has no daily cap. A local RTX 5090 pays for itself within a couple of months at the volumes goal 2 needs; do rented first, buy when the graph is producing daily.

Training. The published 2026 numbers for a Wan 2.2 video LoRA: 20–40 short clips, 3,000–5,000 steps, roughly 24–48 h, about $40–50 on an on-demand H100 (or $30 on spot). Three LoRAs to start: Michael identity (from the Soul photo set plus face-forward cuts from `footage/`), the Antihero garage/moto look (the framebank already cuts stills from the ProRes — extend it to cut 3–5 s clips), and one Zero Page world (Undercity Rain has the most keyframes). Evaluate with the uncanny judge and the likeness rule you already wrote; they finally have something to judge.

Phases:

- **P0, this week — prove the loop once with real money.** Fund one API (Higgsfield Cloud or Runway) with $20, set the spend flag, let `orchestrator.run` produce one real mp4 into `hold_queue`, approve it, post it. This is the first video the studio ever makes on its own, and it exposes whatever is broken in `_download`, R2 publish, `holds_post` and the IG container flow before you build on top of them. Also: point tests at a tmp render dir and delete the 20 zero-byte stubs.
- **P1, weeks 1–3 — `src/wan.py`, a provider that is yours.** Implement the `providers.REQUIRED` contract against a RunPod/Modal endpoint running Wan 2.2 I2V from the Nano keyframes you already generate. Register it first in `DEFAULT_ORDER`. Caps become a budget in dollars per day, not a count of six.
- **P2, weeks 3–6 — the three LoRAs.** Build the dataset cutter on top of `framebank.py`, train identity first, ship it as a flag on every Michael shot (replacing the three-photo prompt ritual), then look and world.
- **P3 — image side too.** The Nano 20/day global cap is what kills every nightly. Move keyframes to Flux/Qwen-Image on the same GPU worker with the same LoRAs so keyframe and clip share an identity.

## Goal 2 — a content engine that drives tons of content

Volume comes from three things the studio does not have: a cheap render (goal 1), an automated assembly step, and selection after the render instead of prediction before it.

Define the unit. A post is not a clip. Pick three formats and build them as graph nodes: a 15–30 s reel (2–3 stitched shots, hook text burned on the first frame, music bed, loudness-normalized, 9:16), a still carousel from keyframes (you have 152 already made and zero posted — this is free volume today), and an episodic series slot (The Other Lane) that posts on a fixed cadence.

Build post-production as code. One `src/assemble.py` on ffmpeg: concat, crop/pad to 9:16, subtitle/hook burn-in, audio bed (LTX-2.5 or a licensed library), thumbnail extraction. This is a two-day build and it is the single biggest multiplier in the repo, because it removes you from the loop between "clip" and "post".

Invert the gates. Keep the uncanny judge and the likeness rule; make everything else advisory. Render N cheap candidates per concept, run a video-level judge (frames, motion, likeness) on the outputs, keep the top one, and put the finished post — not the prompt — in front of you for one tap. When the render is yours, over-rendering costs cents and beats prediction every time.

Make the nightly survive. Move `trigger`/the graph onto the Fly box that already exists, with the Wan endpoint as its renderer and a dollar budget as the only stop. Retire launchd. Keep the Mac for the lanes that need local files (footage, photos) and pre-ingest those to R2.

Fix the feedback corpus. Brand-tag or purge the ten legacy YouTube rows so `proven_results` and the taste judge learn only from posted AI content. Until posts/week is nonzero the loop has nothing to learn; after that it is the thing that makes volume compound.

Widen distribution. TikTok through the Higgsfield MCP's `tiktok_publish` now; YouTube Shorts through the existing `upload_video`; Instagram already wired. Schedule, don't just post: `scheduled_posts` is built and empty.

Change the top-line stat. `/stats` should lead with posts per week per brand and cost per post. Concepts generated is a vanity number; you have 260 of them.

Freeze what does not move that number. Tenancy split, BYOK, pilot invites, shared brain, review-queue UI: parked until posts/week is above zero for a month. They are all good work for a second user who does not exist yet.

## A sane 90-day target

Week 1: one real API-rendered post published. Weeks 2–3: Wan endpoint live, assembly node live, still carousels posting daily from the existing keyframe bank. Weeks 4–6: identity LoRA shipped, one reel a day per brand from the nightly on Fly. Weeks 7–12: look and world LoRAs, series cadence, TikTok added, analytics loop retrained on the new corpus. Success is measured in posts per week and cost per post, and by whether a shot with your face in it needs no reference photos.

## Sources

- [Open Source Video Generation Models (2026 Landscape Guide) — LTX](https://ltx.io/blog/open-source-video-generation-models-guide)
- [Best Open-Source AI Video Generation Models (2026) — Thunder Compute](https://www.thundercompute.com/blog/best-open-source-ai-video-generation-models)
- [LTX-2 vs Wan 2.2 — LinkModel](https://www.linkmodel.ai/blog/ltx-2-vs-wan-2-2)
- [Fine-Tune Flux.2 and Wan LoRA cost on GPU cloud (2026) — Spheron](https://www.spheron.network/blog/fine-tune-flux2-wan-lora-cost-gpu-cloud-2026/)
- [Wan 2.2 LoRA Training Guide: I2V character consistency — wan27.org](https://wan27.org/blog/wan-2-2-lora-training-guide)
- [Train Wan 2.2 LoRAs best practices — Apatero](https://www.apatero.com/blog/train-wan-22-loras-best-practices-2025)
- [Local AI Video Generation: Wan 2.2 vs LTX-2 vs HunyuanVideo](https://localaimaster.com/blog/local-ai-video-generation)
