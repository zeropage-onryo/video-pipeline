# Sprint 4 — EIGHT EXITS — 2026-09-07

Mike's brief: 8 videos, 8 settings, 8 creatures, a setup + a hook + a scare in each, **each one
relates to the other**, his likeness unchanged, creatures from Midjourney, settings
ultrarealistic, Runway only, **zero Runway credits — Unlimited/Max only**.

Board: concepts **#267–274** (antihero), sparks **#136–143**.
Everything lives in `docs/reference-look/sprint4/`.

## The fix for "the episodics were unrelated"

THE OTHER LANE (#237–241) had a spine, but it lived in the captions. On screen it read as five
unrelated night scenes. This series puts the link **inside every frame**, four ways:

1. **The count** — a green reflective highway sign reading `EXIT 8` … `EXIT 1` is physically in
   frame in all eight. See EXIT 6 and you know it is the third one.
2. **The rider** — same face, same white-and-red cafe-racer jacket, same white sport motorcycle,
   same wet night, throughout.
3. **The tally** — each creature is wearing **one more piece of his kit than the last**, visible
   on it: glove → mirror → helmet → boot → chest patch → key → headlight → all of it.
4. **The rule**, stated once and obeyed eight times: *you do not stop between exits, because
   every stop costs you one thing.*

From ep6 on, his jacket carries a **bare circle where the red chest patch was torn off** — the
continuity marker a viewer can catch on a rewatch.

## The eight

| Ep | Exit | Setting | Creature | Takes | Concept |
|----|------|---------|----------|-------|---------|
| 1 | 8 | 24-hour gas station forecourt, rain | THE PUMP MAN — braided fuel hoses, nozzle head | left glove | #267 |
| 2 | 7 | self-serve car wash bay, foam | THE RAG — matted wash-cloth on the brush rail | bar-end mirror | #268 |
| 3 | 6 | rest-stop vending alcove, 3 a.m. | THE GLASS — pale, flattened, inside the machine | helmet | #269 |
| 4 | 5 | flooded underpass, hip-deep | THE SIGNALMAN — vest, head under water, lamp up | boot | #270 |
| 5 | 4 | motel corridor, ice machine | THE FROST — frost and matted carpet, elbows up | red chest patch | #271 |
| 6 | 3 | shuttered drive-thru lane | THE SPEAKER — long neck, grille for a mouth | ignition key | #272 |
| 7 | 2 | parking garage level four | THE FOLDED MAN — too many knee joints | headlight | #273 |
| 8 | 1 | his own street, storm drain | THE COLLECTOR — faceless, wearing all seven | his face | #274 |

## How it was actually made (and what was broken)

- **The Gemini prepay is at zero** (`429 RESOURCE_EXHAUSTED … prepayment credits are depleted`),
  so `orchestrator.run` fails on the first model call — job 28 died in ~2 minutes. The nightly
  run is dead too until it is topped up. The eight ideas were therefore **`capture`d onto the
  board** (ideas, `shots = []`, excluded from `pick_rate` by design) and their scene prompts
  written by hand. Re-run `python -m src.shootgen --scene <id>` once Gemini is funded and compare.
- **Midjourney's AceData balance is empty too**, so the creatures were made by driving Mike's
  logged-in **midjourney.com in Chrome** — the Runway pattern. His plan has **no Relax mode**
  (Speed toggle greyed), so all eight ran on fast GPU time; four images each, one picked by eye.
  The prompt recipe is his own Sep-4 one: `--chaos 5 --ar 9:16 --raw --stylize 50`, "grounded
  supernatural horror film still", plus **"real practical creature suit and animatronics on set,
  no CGI"** — that clause is what keeps the creatures photographic instead of game-engine.
- **Keyframes ran on Higgsfield's Nano Banana Pro**, not the repo's Nano path, because that path
  uses the dead Gemini key. Same likeness recipe: **his three real photos** (`IMG_0586/0593/0599`)
  as `image_references` + the LIKENESS line + "do not copy the reference photos' backgrounds or
  poses", with the chosen Midjourney plate as a **fourth reference carrying the set and the
  creature**. ~868 → ~840 credits. Note Higgsfield reports the model back as `nano_banana_2`.
- **Framing had to be redone for four of them.** The first pass put Michael at about a sixth of
  frame height in ep4/6/7/8 — under the 1/3-frame rule, and that is exactly where Runway's
  likeness drifts. Re-prompted with "SHOOT THIS CLOSE: a medium close-up. His head and shoulders
  fill the left/right half of the frame", creature behind at mid-distance, whole body lit. All
  four came back right. **The lesson: state the framing as an instruction to the camera, not as a
  proportion** — "at least a third of frame height" alone was ignored four times out of eight.
- **A wasted batch:** the first four keyframe jobs went out with no `medias` array at all — the
  prompt referred to "reference photos 1, 2 and 3" that were never attached. ~7 credits. Check
  the request, not the prompt.
- **Midjourney's CDN 403s Higgsfield's URL importer**, so `media_import_url` cannot shortcut the
  plates in; they have to be downloaded and PUT to the presigned S3 URL.

## Runway

Gen-4.5, image-to-video, 9:16, 10 s, **Unlimited mode, zero credits** (the ∞ Max popover showed
Unlimited selected before the first submit and was never switched). Motion prompts in
`runway_prompts.txt` — the keyframe carries the look, the prompt is motion only.

Queue behaviour, which differs from sprint 3: the app accepts roughly **two or three in flight**
and answers the next click with *"You're on a roll — wait or switch to Credits Mode"*; the
relaxed queue ran **15–30 minutes per clip** tonight, far slower than the 8–12 of sprint 3. The
gallery is stale until reload, and **a reload resets the duration chip to 5 s** — re-set it and
zoom-verify "10s" before every Generate. Video URLs are harvested off the `<video>` elements.

## Render log — 8/8, turn on screen in all eight

| Ep | Clip | Turn on screen? |
|----|------|-----------------|
| 1 | ep1_exit8_pumpman | yes — he turns, eyes widen, the hose figure steps forward with the glove |
| 2 | ep2_exit7_rag | yes — the rag walks the rail toward him and he flinches; last frame is soft (mid-motion face) |
| 3 | ep3_exit6_glass | yes — **best of the slate**: the pale thing rises behind the glass, hand to hand, he recoils |
| 4 | ep4_exit5_signalman / **_v2** | partial — v1's creature reads more monstrous; **v2 makes the boot-on-the-arm legible**, which is the series' connective device, so v2 is in the reel. Gen-4.5 **will not keep a head under water** — asked twice, surfaced twice |
| 5 | ep5_exit4_frost | yes — it stands up without unfolding its arms, red patch on its chest, he turns and sees it |
| 6 | ep6_exit3_speaker | yes — the grille leans to his face, key swinging; the headlight comes ON rather than dying (harmless drift) |
| 7 | ep7_exit2_foldedman | yes — it strides out on the wrong legs, headlight blazing in its chest, shadow sweeping the wall |
| 8 | ep8_exit1_collector / **_v2** | v1 partial (the wrong-hand button did not land); **v2 lands it** — a black waterlogged arm reaches across and closes on the glove. v2 is in the reel. The EXIT 1 sign warps to gibberish in v2's last second |

`EIGHT_EXITS_reel.mp4` is the 80 s cut in EXIT order using the two v2s. Both v1s are kept beside
them. All eight concepts are marked `shot` on the board.

## What to do next

1. **Fund the Gemini prepay** — the nightly run and every `--scene` are dead until then.
2. Re-run `python -m src.shootgen --scene 267..274` once it is funded and compare the graph's
   scene prompts against the hand-written ones in `runway_prompts.txt`.
3. If ep2's soft last frame bothers you, it is one re-run with "she flinches back a step" replaced
   by a smaller move — the fast recoil is what smeared the face.
