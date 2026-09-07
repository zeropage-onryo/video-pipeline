# Sprint 3 — Twenty — 2026-09-06

Twenty concepts, six worlds, keyframes done, Runway Gen-4.5 running **Unlimited mode only**
(zero Runway credits — the ∞ Max popover showed "Unlimited" before the first submit and the app
queues two at a time in that mode ("Please wait for your last generation to complete, or
switch to Credits Mode." on the third). I waited. Never switched.)

Everything lives in `docs/reference-look/sprint3/`: `keyframes/c<id>.png`, `clips/`, this sheet.
Board: all twenty are **parked in the Queue** (graph-gated 7–8/10); four held first attempts
(242, 247, 248, 258) archived "seen it".

## Rules I worked to, and where they bent

- **Research:** the scout's `research` ran on both brands (33 + 31 signals, 10 new sparks
  #103–112, **0 images — Instagram token expired Sep 1 again**, `ops/ig_token.sh`). `images_for`
  returned nothing on either brand (only Openverse is switched on). Deep story research: motif
  index (Thompson C331 / M211 / E723 / F377 / Q40 / K1911), two-sentence-horror structure
  (keyframe = sentence one, motion = sentence two), 2026 share mechanics (first frame already
  wrong; loop that closes; locked-frame escalation). Scout sparks were the usual body-horror;
  two were rebuilt as stories (#104 → BLINK, #108's rule → THE BOAT IS COMING) and one taken as
  written (#107 → FACE SUBSCRIPTION). Everything else is hand-written.
- **Pipeline:** all twenty ran the LangGraph (`generate` with a look + ONE-action goal). The
  Nano keyframe cap was 20/20 before I started (nightly job spends it), so every run parked
  "no keyframe" — prompts still scored: 7–8/10 pass on all twenty after three narrower reruns
  (Shadow Rabbit 5→7, Last Bread 5→8, Blink 6→5→7 once I banked my own spark instead of the
  scout's — the graph reads the SPARK text, not the goal, so a spark with reflection logic in
  it will fail however the goal is phrased). Running 20 graph jobs in parallel produced one
  Postgres deadlock (`UPDATE shots SET account_id`) on #246 — harmless, but sequence them next
  time. Job 8 died on a JSON trailing-comma parse error from the model; rerun passed.
- **Michael / likeness (his 2026-09-06 rule):** every Michael still is `soul_cinematic` + Soul
  "Mike Antihero v2" + the LIKENESS line + medium-or-closer. Soul Cinema costs 0.12 credits a
  still; I rendered 20 variants (~2.5 credits) and picked by eye against IMG_0586. **Brand words
  trip things:** "Ducati Panigale" in a Soul prompt got one `ip_detected` refusal and prints
  DUCATI on the jacket; "white sport motorcycle" + "no logos" fixed both. Ep1 is the one
  compromise: the story needs the reflection in frame, so its face is ~1/5 of frame height
  (mustache and hair read; the 1/3-frame variants had no reflection).
- **World keyframes:** Higgsfield `nano_banana_2` 2k (2 credits each) with sprint2 keyframes
  imported as `image_references` (media_upload → curl PUT → media_confirm; the widget path is
  not needed) so Overgrowth / Undercity Rain / Lantern Harbor stay the same worlds. Bolt needed
  a second pass (the door kept rendering open). ~30 Higgsfield credits total; 939 → ~905.
- **Runway:** file_upload only accepts paths under `/mnt/user-data/uploads/…` — commit the PNGs
  to the connected folder, `device_stage_files` them, then upload. Uploading a 9:16 image flips
  the ratio chip automatically; the duration popover's right end is 10 s.

## The six worlds (look bibles)

**Undercity Rain** (est. sprint2) — thirty years of rain, holographic ads, noodle steam,
porcelain-seamed synthetics; teal + magenta neon, mirror-wet asphalt, one red signal.
**Overgrowth** (est. sprint2) — the vine-swallowed city, infected grown over with lichen and
never the same face twice; sodium amber in fog, teal shadows, wet moss.
**Lantern Harbor** (est. sprint2) — felt-and-clay animal village, tilt-shift, paper lanterns.
**Blackout Wards** (new) — one lantern per room; a shadow outlives what casts it by ten seconds.
**Fog Harbor / Drowned Coast** (new) — a harbor town where time passes only for those who stop
waiting, and a coast where the drowned town's lights still work.
**Sunken Cathedral** (new) — the water rises only when someone lies.
**Corridor Blocks / Corporate Hub / Forgetful Suburb** — liminal one-rule districts for the
free slate.

## The twenty — keyframe, story, Runway prompt

Runway: Gen-4.5, Image-to-Video, 9:16, 10 s, Unlimited. The keyframe carries the look; the
prompt is motion only (`runway_prompts.txt`). If a clip loses its turn, reject rather than polish.

### THE OTHER LANE — five episodes, one world, Michael (antihero)

A man loses his reflection, goes down to get it back, and becomes the reflection that leaves
without you. Ep5's last frame is Ep1's first frame, reversed.

- **#237 Ep1 — Red Light.** The reflected light goes green first; his reflection rides off
  without him. Retell: *his reflection got the green light and left without him.*
- **#238 Ep2 — Empty Bike.** No reflection now; a handprint answers his from inside the glass.
- **#239 Ep3 — The Stairwell.** He reaches for it across the still water; it grabs him first.
- **#240 Ep4 — The Trade.** He rides into the mirror; the other one rides out.
- **#241 Ep5 — Green Light.** From below: the rider above gets green and leaves; his stays red;
  a hundred riders at a hundred red lights. Retell: *he went down to get his reflection back and
  became the one that leaves.*

### TEN STORIES

- **#257 The Dry Garage** (Michael, antihero, banked spark #99) — wet = invisible; the one dry
  garage makes him the only thing the drones can see.
- **#243 The Watering Hour** (Overgrowth) — she watered the vine every night; tonight it waters
  her.
- **#256 Shadow Rabbit** (Blackout Wards) — hands drop, the rabbit keeps hopping, and something
  else's shadow arrives before it does.
- **#245 The Stop** (Fog Harbor) — the street ages a century around her; the driver is her, old.
- **#246 The Keeper's Night** (Drowned Coast) — the lighthouse goes dark and the sea turns its
  lights on.
- **#244 Boards** (Overgrowth) — she takes the boards down; what is inside her room leaves first.
- **#259 Last Bread** (Overgrowth) — a kid shares her last bread; the stray's shadow is the size
  of the building.
- **#260 Blink** (Forgetful Suburb) — she blinks; it is behind her, wearing her jacket.
- **#249 WARM** (Undercity Rain, product) — a synthetic gives away the last can of warmth, the one
  thing he cannot survive.
- **#251 The Boat Is Coming** (Sunken Cathedral) — the water rises when you lie; he keeps telling
  his sister the boat is coming. The bar-test line of the slate.

### FIVE FREE

- **#250 Big Glove** (Lantern Harbor) — the villagers turn a rider's glove into a boat; it waves.
- **#252 Bolt** (Corridor Blocks) — every night she locks the door and the world switches off.
- **#253 The Umbrella That Chooses** (Undercity Rain) — his umbrella leaves him for a kitten.
- **#254 Eight Arms** (Undercity Rain) — eight bowls at once; a ninth arm serves the kid.
- **#255 Face Subscription** (Corporate Hub, scout #107) — the filter was rendering the building.

## Render log (Runway Unlimited)



All twenty rendered: Gen-4.5, 720×1280, 10.04 s, Unlimited ("Explore Mode"), zero Runway credits.
Queue behaviour: the app accepts up to 4 in flight early on, then settles to 2 (generating + queued);
a "You're on a roll — wait or switch to Credits Mode" toast marks the rejected click. Rounds of two took
8–12 minutes. The gallery is stale until reload; harvest video URLs by setting `.scroller-CHzmxL`
scrollTop and dispatching a `scroll` event (synthetic wheel events do nothing).

| # | clip | turn on screen? |
|---|------|-----------------|
| 237 | c237_red_light | yes — reflection rides off, he lifts his head |
| 238 | c238_empty_bike | yes — second handprint, eyes widen |
| 239 | c239_stairwell | yes — the hand comes through and grips |
| 240 | c240_trade | yes — camera dives with him into the mirror city, rider rises |
| 241 | c241_green_light | yes — looks up at the inverted city, lowers gaze |
| 257 | c257_dry_garage | yes — red searchlight locks onto his face |
| 243 | c243_watering_hour | yes — the vine takes the can |
| 256 | c256_shadow_rabbit | yes — the best of the slate: rabbit stays, tall shadow arrives |
| 245 | c245_the_stop | yes — vines grow, lamp ages, headlights arrive (no driver reveal) |
| 246 | c246_keepers_night | yes — lens dies, drowned town lights, keeper turns |
| 244 | c244_boards | partial — the dark pours out and they leave, but the window became a doorway |
| 259 | c259_last_bread | partial — dog stands; the shadow is huge from frame one rather than growing |
| 260 | c260_blink | yes — she blinks, the figure in her jacket is behind her |
| 249 | c249_warm | yes — tiny sun rises, vendor's face cracks |
| 251 | c251_boat_is_coming_v3 | **no** — three tries (v1 prompt, v2 water-first prompt, v3 new keyframe with him shoulder-deep): Gen-4.5 will not raise water over a subject from one keyframe. v3 ships (he is shoulder-deep and smiling, she is dry) — the turn is in the caption, not the frame. Fix is a two-keyframe interpolation or a different model. |
| 250 | c250_big_glove | yes — the glove waves, the mouse waves back |
| 252 | c252_bolt | yes — the hallway goes black |
| 253 | c253_umbrella | yes — the umbrella leaves him for the kitten |
| 254 | c254_eight_arms | partial — bowls slide, the ninth-arm beat is soft |
| 255 | c255_face_subscription | yes — faces strobe, the lobby breaks into grey blocks |

## Michael likeness — redone (Mike: "This isn't what I look like")

The Soul Cinema stills were a different actor (thick mustache, pompadour). What actually
reproduces Mike is **Nano Banana Pro with three real photos as `image_references`** (front,
3/4, profile — IMG_0586/0593/0599, media_upload → curl PUT → media_confirm) and a prompt that
opens "This is the same man as in the reference photos: reproduce his face exactly … and his
exact jacket …", then the new scene. Soul Cinema, Soul V2 and the Element path all fail this
test. All six keyframes were regenerated that way (`keyframes/c2xx_v2.png`, `runway/c2xxm.jpg`)
and the six clips re-rendered on Runway Unlimited (still zero credits), same motion prompts,
verified 10 s each:

| # | v2 clip | likeness | turn |
|---|---------|----------|------|
| 237 | c237_red_light_v2 | Mike | reflection leaves, he lifts his head |
| 238 | c238_empty_bike_v2 | Mike | second handprint, wide-eyed |
| 239 | c239_stairwell_v2 | Mike | hand breaks the surface, shock |
| 240 | c240_trade_v2 | Mike | rides through the water, rider settles and looks up (no literal sink) |
| 241 | c241_green_light_v2 | Mike | looks up at the inverted city, camera drops to a close-up as he lowers his gaze — the best likeness of the six |
| 257 | c257_dry_garage_v2 | Mike, drifts at the end | steam, red drone light locks on, he turns into it; the last ~2 s push so close that Gen-4.5 sharpens the jaw — recognisable, but crop the tail if it bothers you |

The v1 clips stay in `clips/` for comparison; the v2s are the ones to use. Note for the
motion prompts: **Runway's likeness drifts on extreme push-ins** (257) — keep Michael at
medium/medium-close and let the camera hold rather than dive into his face.

Rerun candidates if he wants a second pass: 244, 259, 254 (and 251 on a different tool). A 20-clip review reel at 540p is in `sprint3_review_reel.mp4`. Clip URLs are NOT
pasted onto the Queue cards (no render path from the MCP by design) — the mp4s live in `clips/`.
