# The Seedance 2.5 page's media: concepts, design, prompts

Drafted 2026-10-07 for Mike's review; revised the same day (v2) so every
video demonstrates ONE named Seedance 2.5 feature, the way OpenArt's model
page labels its demos (openart.ai/ai-model/seedance-2-5, read 2026-10-07).
NOTHING here has been rendered.
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

## 2b. Every video names its feature (v2)

OpenArt sells 2.5 as a list of named features, each with a demo. The page
should do the same, but only for features this studio actually delivers.

| Feature (OpenArt's / ByteDance's wording) | On our page? | Why |
|---|---|---|
| 30 seconds in one pass, no stitching | YES, the hero | The headline of 2.5, and v1 had no clip longer than 8 s |
| Opening, product moment, closing frame (OpenArt's "30-second ad in one pass") | YES, the hero's three beats | Exactly the studio's ad use case |
| Reference / appearance consistency | YES | The cup at second 12 is the cup at second 28 |
| Native audio sync | YES | The pour and the set-down land on the frame |
| Camera control (rack focus, follow, overhead) | YES, on the wall | Every wall loop is one named camera move |
| Motion physics (water, steam, spray, fabric) | YES, on the wall | ByteDance: "smoother, more consistent motion" |
| 480p / 720p / 1080p | YES, block 4 | The draft-then-approve workflow |
| Region-level editing | NO | Not wired: the studio has no video edit step |
| 50 multimodal references | NO | Not wired: only the keyframe reaches the model today |
| Multi-character scenes | NO | Needs per-character references, same gap |
| 3D blockout / previz | NO | The composer takes no mesh or viewport input |
| "20% better prompt accuracy", "near real-time" | NO | OpenArt's numbers, not on ByteDance's own page |
| Dialogue with lip sync | LATER | Real in 2.5, but the scene writer does not write dialogue yet |

Each label goes on the media's existing chip (`tag`) and on wall tiles as
the bold `title`, so no component change is needed for the labels.

## 3. The slots (v2)

ONE 30-second take carries the story slots, which is cheaper than v1's
three clips and demonstrates the one thing v1 missed. It is a single
continuous take with no cuts, because that is how the studio renders a
scene asked for as one take; a scene with cuts renders one clip per shot
(the signature shows that path).

| Slot | Feature chip | What goes there | Made by |
|---|---|---|---|
| Overview 1 | 30 seconds · one take | The hero clip, all 30 s | K1, Seedance 2.5 720p |
| Overview 2 | Reference consistency | The hero's 10-16 s, the cup turned at the window | a cut of the hero, free |
| Overview 3 | Native audio sync | The hero's 20-30 s, the pour and the set-down, with a sound toggle | a cut of the hero, free |
| Overview 4 | 480p draft, 720p final | The same 30 s at 480p and 720p under one divider | the 480p draft, rendered first anyway |
| Wall 1 to 3, signature frames | (see section 7) | Frames from the hero at 3 s, 14 s, 24 s | ffmpeg, free |
| Wall 4 to 8 | one camera move or physics effect each | 5 s loops | Seedream keyframe, Seedance 2.5 480p |

**The draft IS the workflow.** The 30 s clip renders at 480p first, Mike
reviews it, and only then is the 720p bought. That draft is block 4's
"before", so the page's claim ("draft cheap, then approve") is literally
how its own media was made.

Block 3 plays muted on autoplay, so the overview's video slot needs a
small sound toggle (a component change, no cost).

The signature says "each shot is its own Seedance clip" and shows the cut
path; its three frames are stills from the one-take hero. If that reads as
a mismatch, three 10 s clips at 480p for the signature cost $6.62 more.

### Cost (v2)

| Item | Cost |
|---|---|
| 6 Seedream 4.5 keyframes (K1 + five wall) at $0.04 | $0.24 |
| Hero draft, 30 s at 480p ($0.2205/s) | $6.62 |
| Hero final, 30 s at 720p ($0.473/s, sound included) | $14.19 |
| Wall loops 4 to 8, 25 s at 480p | $5.51 |
| Cuts, frame pulls | $0.00 |
| **Total** | **about $26.56** |

Stills on the wall instead of loops: about $21.05. The 480p draft is the
cheap stop point: if it is wrong, the 720p is never bought.

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

## 5. Keyframe K1 (Seedream 4.5, text-to-image through zeropage)

**K1, the hero's first frame (4:3).** Wide shot of the STUDIO. The POTTER
sits at the kick wheel in the left third of frame, the wheel already
spinning, her wet hands cupped around a cone of clay, a fine spray of slip
on the wheel head. On the shelf behind her, in soft focus, THE CUP. Dust
hangs in the shaft of window light. Camera at seated eye height. STYLE.
TEXTURE. EXCLUDE.

The cup is in K1 on purpose: the clip is image-to-video, so a cup already
in the first frame is the reference the model holds for 30 seconds.

---

## 6. The hero (Seedance 2.5, image-to-video from K1)

**30 s, one continuous take. 480p draft first, then 720p.**
Features: 30 seconds · one take; opening, product moment, closing frame;
reference consistency; native audio sync.

```
GOAL: one continuous 30-second take, NO CUTS: a 30-second film for a handmade
cup, in three beats: an opening, a product moment, a closing frame.
NO MUSIC, NO VOICE.
(0-10s) OPENING: the POTTER at the kick wheel by the window, the wheel already
spinning, her wet hands drawing the clay up into a cone. The camera starts wide
and dollies slowly toward the shelf behind her.
(10-20s) PRODUCT MOMENT: she reaches up and lifts THE CUP from the shelf, holds it
at chest height in the window light and turns it once through a full rotation;
the camera settles into a close-up, shallow focus, the window a soft cool blur.
(20-30s) CLOSING FRAME: she sets the cup on the worn oak bench; a matte black
gooseneck kettle enters from frame left and pours a thin stream of black coffee
into it; steam rises into the light; the kettle lifts away and the camera holds
still on the cup for the last two seconds.
CONTINUITY: the same POTTER, wardrobe and STUDIO light throughout. THE CUP's
shape, indigo glaze, rust speckles at the rim, bare clay foot and thumb-dip stay
exactly the same from the shelf to the last frame.
STYLE. TEXTURE.
CAMERA: one slow continuous move, no cuts, no handheld shake; wide at 0s,
close at 15s, locked off from 28s.
AUDIO, synced: the low hum and steady knock of the kick wheel and wet clay
under her hands (0-10s); the wheel slowing, her footsteps on concrete, the cup
lifted off the wooden shelf with a soft knock (10-20s); the cup set on oak, the
pour's pitch rising as it fills, the kettle set down off frame, one last drip
(20-30s). Quiet morning room tone under all of it, one distant bird.
RULES: start mid-motion. Her face never turns to camera. EXCLUDE.
```

The 480p draft uses the SAME prompt, so the divider in block 4 compares
like with like.

---

## 7. The wall, one feature per tile (v2)

The bold label is the FEATURE; the chip under it is the shot type.

**Tiles 1 to 3 (frames from the hero, free, cropped 4:5).**

| # | Label (feature) | Chip | Frame |
|---|---|---|---|
| 1 | One-take opening | Wide establishing | hero at 3 s |
| 2 | Product held steady | Close-up | hero at 14 s |
| 3 | Steam and pour | Macro | hero at 24 s |

**Tiles 4 to 8.** A Seedream keyframe, then a 5 s Seedance 2.5 loop at
480p. Each clip prompt is one continuous take, no music, STYLE, EXCLUDE,
and starts mid-motion.

| # | Label (feature) | Chip | Frame | Keyframe | Motion (the clip prompt) |
|---|---|---|---|---|---|
| 4 | Spray and momentum | Handheld follow | 4:5 | A skateboarder in a dark rain jacket mid-carve through a rain-slick concrete underpass at blue hour, low camera just behind, sodium lights doubled in the puddles, face turned away | The camera follows low and close as the board carves left then right, throwing a fine spray; wheels on wet concrete, the hiss of spray, the underpass echo |
| 5 | Multi-beat action | Top-down reveal | 9:16 | Directly overhead, a long oak table at dusk half set for dinner: indigo stoneware plates, linen, figs, bread, candle stubs, one hand placing a plate | In order: a plate set down, a glass, a napkin folded, a match struck and a candle lit; the camera rises slowly; each sound lands on its action |
| 6 | Rack focus | Camera control | 16:9 | A clear unlabelled glass perfume bottle on wet black slate, droplets sharp on the glass; behind it a figure in a cream coat, soft and out of focus, walking past a rain-streaked window | Focus pulls from the droplets to the figure as she passes, then back to the bottle; rain on glass, one distant car |
| 7 | Backlight and water | Golden hour | 4:5 | A surfer walking out of the sea at golden hour, board under one arm, backlit, water sheeting off the wetsuit, seen from behind at three-quarters | She walks up the wet sand out of frame right, the sun flaring through the spray, hair and wetsuit dripping; surf, wind, footsteps in wet sand |
| 8 | Rain, steam and sound | Night exterior | 4:5 | A street noodle stall at night in rain, steam rising under one bare bulb, a cook's arm lifting noodles high with long chopsticks, rain streaks through the light, no signage | The noodles lift and drop back into the pot, steam rolls up through the rain; the boil, rain drumming on a tarp, the clack of chopsticks, each on its frame |

---

## 8. The signature's copy (shot-timeline.tsx), to match

30 seconds in three 10-second windows, 2.5's headline length:

1. **Wide establishing, 0-10 s.** "Wide, static. A ceramics studio at dawn; dust hangs in one shaft of light over the wheel."
2. **Macro detail, 10-20 s.** "Macro, slow push-in. Wet thumbs open the clay on the spinning wheel; slip runs over the knuckles."
3. **The action, 20-30 s.** "Medium, handheld. She lifts the glazed cup to the window and turns it once; the indigo catches the light."

---

## 9. For Mike to decide

- [ ] Concept A, B or C for the story (v2 is written for A)
- [ ] The one-take 30 s hero (v2) instead of v1's three short clips
- [ ] Wall as real Seedance loops (about $26.56 in all) or stills (about $21.05)
- [ ] Mark up K1, the hero prompt and the wall table
- [ ] The signature at 30 s (three 10 s windows) or kept at 15 s
- [ ] Teach the scene writer dialogue, so lip sync can be a feature later

How it renders once approved: the keyframes go through zeropage's
`generate_image` (Seedream 4.5, filed on the Assets wall). Seedance 2.5 is
on this branch only, so the clips render from this machine through
`src/fal.py` on the local `FAL_KEY` until the branch is merged and deployed;
after that they can go through the Queue instead.
