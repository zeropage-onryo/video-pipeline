# Three Worlds sprint — 2026-09-05

Twelve concepts, three worlds, keyframes done, Runway Gen-4.5 running in **Unlimited mode only**
(zero credits — the toggle was checked before every submit; Unlimited runs one job at a time and
queues the rest, "may take longer" is Runway's own wording).

Everything lives in `docs/reference-look/sprint2/`: `keyframes/c<id>.png`, `graph_prompts_raw.txt`
(what the pipeline's judge-gated prompt writer produced), this sheet. Board: all twelve are
**parked in the Queue** with hold rows; three held first attempts (196, 197, 204) archived "seen it".

## Rules I worked to, and where they bent

- **Runway: Unlimited only.** Confirmed in the ∞ Max popover before each Generate. The app refuses
  a second concurrent job in Unlimited ("wait for your last generation, or switch to Credits Mode")
  — I waited. Never switched.
- **Research (~1 h):** Pinterest crawled through your Chrome (real `i.pinimg.com` image URLs, not
  pin pages), ~60 candidates viewed on contact sheets before picking, 34 banked across the twelve
  sparks with pin attribution. The scout's `research` ran on both brands: **0 images, Instagram
  token expired Sep 1** (`ops/ig_token.sh` is the fix). **Midjourney connector: still out of
  balance** (Ace Data) — contributed nothing. **Higgsfield last:** used only for keyframes, because
  the pipeline's Nano keyframe was blocked by the **global 20/day image cap, already spent before I
  started** (`NANO_GLOBAL_DAILY_CAP`). ~15 Higgsfield credits on 14 Nano Banana 2 renders; your
  "Mike Antihero v2" Element carried the likeness.
- **Michael / random people:** 5 concepts on your likeness (antihero), 7 on random people
  (zeropage). **The face-forward ones break Zero Page's faceless rule** — done on your instruction
  ("vary their faces"), flagged on every rationale, not silently.
- **Creature faces vary:** every crowd names distinct faces (moss beard, fungal shelf, mummified,
  bulbous asymmetric, pale melted, lichen neck, fused jaw, featureless "soap" face; synthetic seam;
  three-eyed fox / moon-mouth bear / antlered rabbit masks). Pinterest face refs were vetted by eye.
- **Pipeline used to refine:** all twelve ran the LangGraph (`generate` with a look+beat goal);
  three were held at 6/10 for multi-stage motion and rerun with a single action — all twelve then
  passed at 7–8/10. The judge's note is the same every time: story in the logline, ONE motion in
  the clip. The 2–3-shot concept is still the graph change to make.
- **Fly app** was unreachable during the sprint (connection closed) — the Mac MCP server did all
  the work. Worth a `fly status` when you're back.

## The three worlds (look bibles)

**Overgrowth** — the city ten years after; every street swallowed by vines, the infected grown
over with fungus and lichen, slow, and never the same face twice. Grade: overcast green-grey day
into sodium-orange practicals at night, fog, wet moss on everything; teal shadows / amber light /
one red. 35mm, glossy commercial finish (not gritty handheld).

**Undercity Rain** — a megacity where it has rained for thirty years; holographic ads the size of
buildings, noodle steam in every alley, synthetic people with fine porcelain seams. Grade: teal +
magenta neon, mirror-wet asphalt, volumetric haze, one red signal; extreme scale contrast.

**Lantern Harbor** — a toy-scale island village of round-headed felt-and-clay animal villagers,
pastel cottages, a dusk-blue sea, warm paper lanterns. Tilt-shift miniature, stylized 3D-animation
look. Original villager designs (cow in overalls, mouse with lantern, raccoon in knitted vest,
duckling in yellow raincoat, cat in a paper crown) — no franchise characters.

## The twelve — keyframe, story, Runway prompt

Runway: Gen-4.5, Image-to-Video, 9:16, 10 s, Unlimited. The keyframe carries the look; the prompt
is motion only. If a clip loses its turn, reject rather than polish.

### OVERGROWTH

**#192 The Toll** (antihero) — `keyframes/c192.png`
Bike dies under a vine-choked overpass; the infected gather at silence. One sentence: a rider's
bike dies in a city where the infected only move at silence, so he plays a recording of his engine.
Runway: *The rider sits still on the stalled motorcycle. In the shadows behind him, every infected
figure slowly turns its head toward him in eerie unison, then goes motionless. Slow steady push-in
from behind the bike toward the turning heads, no cuts. Fog drifts through the vines, sodium lamps
flicker faintly, moss glistens. Photoreal, anamorphic haze, high contrast, no text.*

**#193 Fresh Paint** (zeropage, face-forward) — `keyframes/c193.png`
She painted every turned neighbour's face on the barricade wall; tonight she paints her own.
Runway: *She sets the brush down on the paint can and turns away from the wall of painted faces,
walking slowly toward the silent crowd; the crowd parts to make a path for her. Slow tracking behind
her shoulder, no cuts. Soft rain, the work lamp flickers once, wet street reflections. Photoreal,
high contrast, no text.*

**#194 Supermarket Lights** (zeropage, face-forward) — `keyframes/c194.png`
The infected move only when a light dies; the old man taps the tube back on every night.
Runway: *The fluorescent tube above the old man stutters and dies, plunging the aisle into
near-dark; every motionless figure snaps its head toward him at once. He taps the fixture twice
with his cane and the tube buzzes back on; they freeze mid-turn, inches from him. Locked-off low
wide, no cuts. Photoreal, cold green fluorescent, no text.*

**#195 Garage Door** (antihero) — `keyframes/c195.png`
He hands the infected neighbour a wrench; they work on the engine together.
Runway: *The man holds the wrench out toward the dark doorway; the grey cracked hand reaches
slowly into the lamplight and takes it. Both figures then bend to the motorcycle engine and begin
working in the same rhythm. Slow push-in from inside the garage, no cuts. Sodium lamp hum, moths
in the light, vines stir outside. Photoreal, no text.*

### UNDERCITY RAIN

**#198 The Rain Stops for Her** (zeropage, face-forward) — `keyframes/c198.png`
Weather is a subscription; her playing stops the rain mid-air; the ad above switches to selling her.
Runway: *She plays the violin with intensity. The sphere of frozen raindrops around her slowly
expands outward across the street; drops hang glittering and rotate gently in the neon light as
the crowd lowers their umbrellas and looks up. Slow pull-back and rise, no cuts. The giant hologram
above flickers. Photoreal, pink and teal neon, no text.*

**#199 Reflection City** (antihero) — `keyframes/c199.png`
The reflected city runs its own traffic; his reflection gets the green and leaves without him.
Runway: *The rider and motorcycle stay completely still at the red light. Their reflection in the
flat black floodwater does not: the mirrored rider and bike slowly roll forward and ride away
downward into the reflected neon city, leaving spreading ripples, until the water under the real
bike is empty and shows only the city. Locked-off camera, no cuts. Mist drifts, neon flickers
softly, light rain. Photoreal, anamorphic haze, no text.*

**#200 Billboard** (antihero) — `keyframes/c200.png`
An ad borrows the face of whoever looks longest; it takes his.
Runway: *The tiny rider waits at the red light. Above him the forty-metre hologram rider slowly
turns its head and looks down at him, rain passing through its light, scan lines rippling. Low wide
from behind the bike, slow tilt up to the giant's face, no cuts. Neon reflections shimmer on the
flooded street. Photoreal, volumetric haze, no text.*

**#201 Noodles for Two** (zeropage, face-forward) — `keyframes/c201.png`
He serves synthetics who can't taste; one orders the dish he only made for his wife.
Runway: *Steam rises thickly from the bowl and drifts across her face; the seam on her cheek fogs
over like breath on glass. She looks up from the bowl and slowly smiles. The vendor behind the
counter goes still. Static medium close across the counter, shallow focus, no cuts. Rain streaks
past the pink neon, steam curls. Photoreal, no text.*

### LANTERN HARBOR

**#202 Scale** (antihero) — `keyframes/c202.png`
Full-size Michael in a toy village; every lantern is lit by a photo from his real life.
Runway: *Hundreds of paper lanterns rise slowly from the village past the seated man, each glowing
warm from inside, drifting upward and away over the sea. The tiny cow and mouse villagers look up.
The man lifts his head to follow the lanterns. Slow rise with the lanterns, gentle tilt-shift
miniature feel, no cuts. Dusk blue, amber light on his face. No text.*

**#203 The Last Lantern** (zeropage) — `keyframes/c203.png`
A lantern lights only if someone inside is waiting; the raccoon sits down and waits himself.
Runway: *The small raccoon sits still on the doorstep holding the dark lantern. After a beat the
lantern in his lap flickers and catches, glowing warm amber, lighting his face from below; his ears
lift. Static low angle, slow push, no cuts. Soft rain glistens on the cobbles, the row of lanterns
behind him sways gently. Stylized 3D-animation look, no text.*

**#205 Rain Day** (zeropage) — `keyframes/c205.png`
It rains only on the sad; she stays dry until she hands the letter over.
Runway: *The badger reads the letter in the doorway. Above the duckling's hood the small grey cloud
thickens and begins to rain on her alone, drops bouncing off the yellow raincoat, while the sunny
path behind stays dry. The badger lowers the letter and looks down at her. Static low angle,
slight push, no cuts. Stylized 3D-animation look, no text.*

**#206 Festival Masks** (zeropage) — `keyframes/c204.png`
Never lift someone else's mask; it's cute all the way down.
Runway: *The tall villager's antlered-rabbit mask slides slowly off, held by the small cat's reaching
paw, revealing the round rabbit face beneath, which blinks. The other masked villagers turn to
watch. Static low angle, slow push, no cuts. Lanterns sway overhead, warm amber against teal dusk.
Stylized 3D-animation look, no morphing, no text.*

## Render log (Runway Unlimited) — 12 / 12 complete

All Gen-4.5, Image-to-Video, 9:16, 10 s, 720×1280, Unlimited ("Explore Mode"), zero credits.
Files in `docs/reference-look/sprint2/clips/`. Unlimited ran two jobs concurrently in practice;
queue waits were 5–45 min, and the page state goes stale — reload/scroll to see completions.

| Concept | Clip | Did the turn land? |
|---|---|---|
| 199 Reflection City | c199_reflection_city.mp4 | **Yes** — reflection rides off, ripples, real bike stays. Best of the set. |
| 192 The Toll | c192_the_toll.mp4 | Yes — push-in past Michael into a crowd of distinct faces. |
| 198 The Rain Stops for Her | c198_rain_stops.mp4 | **Yes** — sphere of frozen rain, drone pull-back to overhead. |
| 202 Scale | c202_scale.mp4 | Yes — lanterns rise past photoreal Michael in the toy village. |
| 200 Billboard | c200_billboard.mp4 | Yes — the giant leans down. Keyframe carries a stray "@Mike Antihero v2" label on the jacket (Higgsfield element artifact) — rerender the still before posting. |
| 194 Supermarket Lights | c194_supermarket_lights.mp4 | Yes — tube dies, heads snap, tube relights, they crowd him. |
| 195 Garage Door | c195_garage_door.mp4 | **Yes** — hand-off, then both pairs of hands on the engine. |
| 201 Noodles for Two | c201_noodles_for_two.mp4 | Yes — steam, seam fogs, she looks up and smiles. |
| 203 The Last Lantern | c203_last_lantern.mp4 | Mostly — lantern catches, then he stands and walks toward camera (prompt said sit still). Charming anyway. |
| 206 Festival Masks | c206_festival_masks.mp4 | Yes — the rabbit lifts its own antlered mask; face beneath. |
| 193 Fresh Paint | c193_fresh_paint.mp4 | Yes — she walks into the crowd and they part. |
| 205 Rain Day | c205_rain_day.mp4 | Variation — the badger steps out and stands under her cloud with her (better button than the coat). |

Not done: pasting clip URLs back onto the Queue cards (`set_shot_media_url`) — both the local
server and Fly were down during the sprint. The files are in the folder; paste when the server
is up, then mark 📷 shot on the ones you post.
