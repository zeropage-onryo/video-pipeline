# The Seedance 2.5 page's media: concepts, design, prompts

Drafted 2026-10-07 for Mike's review. NOTHING here has been rendered.
Every prompt below is a draft to mark up; nothing spends until it is
approved line by line.

Prompt shape follows `.claude/skills/video-prompting/references/models/seedance25/`:
constraints and timing at the top, a style block, a texture block, every
shot starting mid-motion, explicit blocking, audio as its own section.

---

## 1. Concepts: one world for the story slots

The overview's four blocks and the signature's three shots should be ONE
short film, so the page shows what 2.5 is sold on: the same thing held
across shots, timed beats, sound with the picture. Three candidates:

**A. The Cup (recommended).** A ceramicist's studio at dawn. Clay rises on
the wheel, the glazed cup comes off the shelf, coffee is poured into it by
the window. The cup is the "product" held steady across clips, which is
the claim ad customers care about. Sound is rich and tactile (wheel hum,
wet clay, the wire, the pour, the set-down). Cool dawn light against warm
tungsten matches the page's indigo. It is also what the signature already
describes (a workshop at dawn, a piece set down, lifted to the window).

**B. Last Train.** A night platform in the rain; a courier with a parcel
waits, the train arrives, the doors close on the parcel. Indigo night,
huge sound (rain, the train), the parcel is the held object. Harder:
crowds and trains are where video models break.

**C. Night Swim.** An outdoor pool at blue hour; a swimmer dives, the
camera follows under the surface, she comes up as the pool lights switch
on. The most beautiful and the most on-palette, but nothing is "held"
across shots, so it demonstrates the reference claim worst.

Everything below is written for A.

## 2. Design rules (all media on the page)

- **Look:** photoreal, large-format film, real grain, soft halation. Cool
  blue-hour shadows, warm practical highlights. The indigo lives in the
  shadows and in one object (the cup's glaze), never as a colour filter.
- **No** text, logos, signage, screens or watermarks in frame. No
  recognisable people: faces turned away, at distance or out of focus.
  Hands are welcome.
- **Sound:** diegetic only, never music, the studio's house rule.
- **Start mid-motion:** no clip begins or ends on a still subject.
- **Compose to the slot:** the subject sits in the centre third, because
  every tile is cropped `object-cover` and the bento crops hard.
- **Honesty:** the wall is titled "Shots Seedance Renders", so every tile
  is a real Seedance 2.5 render: a short clip, or a frame pulled from one.
  Seedream draws only the first frames the clips start on.

## 3. The slots

| Slot | What goes there | Made by | Frame |
|---|---|---|---|
| Overview 1, timed beats | Clip 1: three timed shots in one 8 s generation | Seedream keyframe K1, Seedance 2.5 720p | 4:3 |
| Overview 2, reference hold | Clip 2: the cup turned through a full rotation, 6 s | K2, Seedance 2.5 720p | 4:3 |
| Overview 3, sound | Clip 3: coffee poured into the cup, synced audio, 6 s | K3, Seedance 2.5 720p | 4:3 |
| Overview 4, production | Clips 1 to 3 cut together into one MP4 | the studio's Export / ffmpeg, free | 4:3 |
| Wall 1 to 3 = signature frames | Frames pulled from clips 1 and 2 | ffmpeg, free | 4:5 crop |
| Wall 4 to 8 | Five 5 s loops, one per shot type | Seedream keyframe, Seedance 2.5 480p | per slot |

Block 3's clip plays muted on autoplay, which hides the one thing it
demonstrates. It needs a small sound toggle on the overview's video slot
(a component change, no cost).

### Cost

| Item | Cost |
|---|---|
| 8 Seedream 4.5 keyframes at $0.04 | $0.32 |
| Clips 1 to 3, 20 s at 720p ($0.473/s, sound included) | $9.46 |
| Wall clips 4 to 8, 25 s at 480p ($0.2205/s) | $5.51 |
| Export, frame pulls | $0.00 |
| **Total** | **about $15.30** |

Without the five wall clips (stills on the wall instead, retitled): about
$9.80.

---

## 4. Shared blocks (pasted into every prompt that names them)

**STYLE** Photorealistic, shot on large-format film, real organic film
grain, soft halation on highlights, high dynamic range. Cool blue-hour
shadows, warm practical highlights. Not a 3D render, not CGI, not a game
engine, not a cutscene.

**TEXTURE** Matte, lived-in surfaces: raw clay, worn oak, unglazed
stoneware, linen, concrete dusted with dry clay.

**STUDIO** A small ceramics studio at dawn: a kick wheel beside a tall
steel-framed window, wooden shelves of pale bisque ware, a concrete floor
dusted with clay, one shaft of cool morning light through the window and
a single warm tungsten bulb over the workbench.

**POTTER** A woman in her thirties, dark hair tied back, a charcoal linen
apron over an undyed cotton shirt with the sleeves rolled, dried clay on
her forearms. Always seen from the side or behind; her face turned away
or out of focus.

**THE CUP** A hand-thrown stoneware cup about 9 cm tall, no handle,
slightly uneven walls, a deep indigo glaze that breaks to rust-brown
speckles at the rim, the bottom third left as bare buff clay, one small
thumb-dip pressed into its side.

**EXCLUDE** No text, no logos, no signage, no screens, no watermark, no
extra people, no recognisable faces.

---

## 5. Keyframes (Seedream 4.5, text-to-image through zeropage)

Each is the FIRST frame of its clip, so it is drawn already mid-motion.

**K1, clip 1's first frame (4:3).** Wide shot of the STUDIO. The POTTER
sits at the kick wheel in the left third of frame, the wheel already
spinning, her wet hands cupped around a cone of clay, a fine spray of slip
on the wheel head. Dust hangs in the shaft of window light. Static camera
at seated eye height. STYLE. TEXTURE. EXCLUDE.

**K2, clip 2's first frame (4:3).** Close-up at chest height: two
clay-dusted hands hold THE CUP in front of the tall window, already
turning it, the rim catching the cool light. The window is a soft blur of
blue morning behind, the warm bulb a bokeh point at frame right. Shallow
depth of field, the cup tack-sharp. STYLE. TEXTURE. EXCLUDE.

**K3, clip 3's first frame (4:3).** Close side angle at bench height:
a matte black gooseneck kettle, held by a hand entering from frame left,
already pouring a thin stream of black coffee into THE CUP on a worn oak
workbench. Steam curls up into the shaft of window light. STYLE. TEXTURE.
EXCLUDE.

Note: the zeropage tool draws from text only, so the cup in K2 and K3 is
held to the CUP block by wording, not by a reference. If they drift,
the fix is to draw K2 first and pass it to K3 through fal's Seedream
edit endpoint (same price, a local call instead of the tool).

---

## 6. Clips (Seedance 2.5, image-to-video from the keyframe above)

**Clip 1, timed beats. 8 s, 720p, from K1.**

```
GOAL: one 8-second clip in three timed shots, cutting between them. Photoreal.
(0-3s) SHOT 1, wide, static: the POTTER at the kick wheel by the window, the
wheel already spinning, her wet hands drawing the clay up into a cone; dust
drifts through the shaft of light.
(3-5s) SHOT 2, macro close-up, shallow focus: her thumbs press down into the
spinning clay and open it, slip running over her knuckles.
(5-8s) SHOT 3, medium, side angle, slow push-in: she draws a cutting wire
under the finished cylinder and lifts it off the wheel onto a wooden board.
NO MUSIC.
CONTINUITY: the same POTTER, wardrobe and STUDIO light in all three shots.
STYLE. TEXTURE.
AUDIO: the low hum and steady knock of the kick wheel; wet clay squelching
under the thumbs at 3s; the thin zip of the wire at 6s; the board set down on
the bench at 7s. Quiet room tone, one distant bird outside.
RULES: every shot starts mid-motion. Her face never turns to camera. EXCLUDE.
```

**Clip 2, the reference hold. 6 s, 720p, from K2.**

```
GOAL: one continuous 6-second take, no cuts.
Two clay-dusted hands hold THE CUP at chest height in front of the window and
keep turning it slowly through one full rotation, then tilt it toward camera
to show the bare clay foot. The cup's shape, the indigo glaze, the rust
speckles at the rim and the thumb-dip stay exactly the same the whole time.
NO MUSIC.
CAMERA: locked-off close-up, shallow depth of field; the window a soft cool
blur behind, the warm bulb a bokeh point at frame right.
STYLE. TEXTURE.
AUDIO: the faint grit of dry clay against the glaze as the hands turn it; at
about 4s a fingertip taps the rim once, a clear high ring; quiet room tone.
RULES: the cup never changes. EXCLUDE.
```

**Clip 3, sound with the picture. 6 s, 720p, from K3.**

```
GOAL: one continuous 6-second take, no cuts. The sound must land on the action.
A hand pours a thin stream of black coffee from a matte black gooseneck kettle
into THE CUP on a worn oak bench; steam curls up into the window light. At
about 4s the pour stops, the kettle lifts out of frame left, and the hand
lifts the cup an inch and sets it back down.
NO MUSIC, NO VOICE.
CAMERA: static, close side angle at bench height, shallow depth of field.
STYLE. TEXTURE.
AUDIO, synced: the pour's pitch rising as the cup fills; the kettle set down
on wood off frame at 4s; the cup's soft stoneware clunk on the bench at 5s; one
last drip. Quiet room tone under all of it.
RULES: THE CUP stays identical. EXCLUDE.
```

**Overview 4, production.** No render: clips 1 to 3 assembled in order
into one MP4 by the studio's Export, which is the claim the block makes.

---

## 7. The wall

**Tiles 1 to 3 (signature frames, free).** Frames pulled from the clips,
cropped 4:5: tile 1 "Wide establishing" from clip 1 at 1.5 s, tile 2
"Macro detail" from clip 1 at 4 s, tile 3 "Slow push-in" from clip 2 at
1 s (the cup at the window).

**Tiles 4 to 8.** A Seedream keyframe, then a 5 s Seedance 2.5 loop at
480p. Each clip prompt is one continuous take, no music, STYLE, EXCLUDE.

| # | Label | Frame | Keyframe | Motion (the clip prompt) |
|---|---|---|---|---|
| 4 | Handheld follow | 4:5 | A skateboarder in a dark rain jacket mid-carve through a rain-slick concrete underpass at blue hour, low camera just behind, sodium lights doubled in the puddles, face turned away | The camera follows low and close as the board carves left then right, throwing a fine spray; wheels on wet concrete, the hiss of spray, the underpass echo |
| 5 | Top-down reveal | 9:16 | Directly overhead, a long oak table at dusk half set for dinner: indigo stoneware plates, linen, figs, bread, candle stubs, one hand placing a plate | The camera rises slowly as hands keep setting the table until it is full; plates on wood, cutlery, a match struck at the end |
| 6 | Rack focus | 16:9 | A clear unlabelled glass perfume bottle on wet black slate, droplets sharp on the glass; behind it a figure in a cream coat, soft and out of focus, walking past a rain-streaked window | Focus pulls from the droplets to the figure as she passes, then back; rain on glass, one distant car |
| 7 | Golden hour | 4:5 | A surfer walking out of the sea at golden hour, board under one arm, backlit, water sheeting off the wetsuit, seen from behind at three-quarters | She walks up the wet sand out of frame right, the sun flaring through the spray; surf, wind, footsteps in wet sand |
| 8 | Night exterior | 4:5 | A street noodle stall at night in rain, steam rising under one bare bulb, a cook's arm lifting noodles high with long chopsticks, rain streaks through the light, no signage | The noodles lift and drop back into the pot, steam rolls up through the rain; the boil, rain on a tarp, the clack of chopsticks |

---

## 8. The signature's copy (shot-timeline.tsx), to match

30 seconds in three 10-second windows, 2.5's headline length:

1. **Wide establishing, 0-10 s.** "Wide, static. A ceramics studio at dawn; dust hangs in one shaft of light over the wheel."
2. **Macro detail, 10-20 s.** "Macro, slow push-in. Wet thumbs open the clay on the spinning wheel; slip runs over the knuckles."
3. **The action, 20-30 s.** "Medium, handheld. She lifts the glazed cup to the window and turns it once; the indigo catches the light."

---

## 9. For Mike to decide

- [ ] Concept A, B or C for the story slots
- [ ] Wall as real Seedance loops (about $15.30 in all) or stills (about $9.80)
- [ ] Mark up the prompts in sections 5 to 7
- [ ] The signature at 30 s (three 10 s windows) or kept at 15 s

How it renders once approved: the keyframes go through zeropage's
`generate_image` (Seedream 4.5, filed on the Assets wall). Seedance 2.5 is
on this branch only, so the clips render from this machine through
`src/fal.py` on the local `FAL_KEY` until the branch is merged and deployed;
after that they can go through the Queue instead.
