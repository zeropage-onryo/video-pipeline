# The Seedance 2.5 page's media: snippets, one feature each

v3, 2026-10-07, after Mike: "every video different, no 30-second video,
these are all just snippets." Supersedes v1 (one story, three clips) and
v2 (one 30 s hero cut into excerpts). RENDERED 2026-10-07 on Seedance 2.5 through Mike's Runway account
(session "Seedance 2.5 landing page", text-to-video, 720p, sound on;
1,930 credits for 12 clips plus a 480p motorcycle draft drawn from the
720p clip's first frame, since Runway has no seed). The clips live under
`web/public/models/seedance-video-generator/` as web MP4s with posters.
The Seedream first-frame step was skipped; the wall chips read T2V.

Prompt shape follows `.claude/skills/video-prompting/references/models/seedance25/`:
constraints and timing first, a style block, every clip starting
mid-motion, explicit blocking, audio as its own section. The feature
labels follow OpenArt's model page (openart.ai/ai-model/seedance-2-5): each
demo names the one thing it shows.

---

## 1. The rules every snippet follows

- **Twelve different subjects.** No two videos share a person, a place or
  a product. Each one demonstrates ONE named feature.
- **Short.** 5 s each (6 s for the timed-beats one). Seedance's floor is
  4 s.
- **Look:** photoreal, large-format film, real grain, soft halation, cool
  shadows and warm practical highlights. The page's indigo may appear in
  one object or in the shadows, never as a colour filter.
- **Never:** text, logos, signage, screens, watermarks, recognisable faces.
  Faces turned away, at distance or out of focus; hands are welcome.
- **Sound:** diegetic only, never music.
- **Start mid-motion:** no clip begins or ends on a still subject. Every
  snippet loops on the page, so the last frame should sit close to the first.
- **Compose to the slot:** the subject in the centre third, because tiles
  are cropped to fit.
- **Only features the studio delivers.** Not on the page: region editing,
  50 references, multi-character scenes, 3D blockout (none are wired), and
  OpenArt's "20% better accuracy" and "near real-time" (not on ByteDance's
  own page).

## 2. How each one is made

A Seedream 4.5 still (through zeropage's `generate_image`, text only) is the
first frame; Seedance 2.5 animates it, image-to-video, so the clip keeps the
still's framing. The overview's four render at 720p (they are shown large),
the wall's eight at 480p (they are small tiles).

## 3. Cost

| Item | Cost |
|---|---|
| 15 Seedream 4.5 stills at $0.04 (12 first frames + 3 signature frames) | $0.60 |
| Overview: 6 s + 5 s + 5 s + 5 s at 720p ($0.473/s) | $9.94 |
| Overview 4's 480p draft, 5 s ($0.2205/s) | $1.10 |
| Wall: 8 × 5 s at 480p | $8.82 |
| **Total** | **about $20.46** |

All twelve at 480p, keeping only overview 4's 720p final: about $15.

---

## 4. Shared blocks

**STYLE** Photorealistic, shot on large-format film, real organic film
grain, soft halation on highlights, high dynamic range. Cool shadows, warm
practical highlights. Not a 3D render, not CGI, not a game engine.

**TEXTURE** Matte, lived-in, real-world surfaces.

**EXCLUDE** No text, no logos, no signage, no screens, no watermark, no
extra people, no recognisable faces. No music.

Every first-frame prompt ends with STYLE, TEXTURE, EXCLUDE; every motion
prompt with STYLE, EXCLUDE and "starts mid-motion; one continuous take"
unless it says otherwise.

---

## 5. The overview (four blocks, 4:3, 720p)

### O1. Timed beats (block 1, "Up to 30 seconds a shot, written as timed beats")
Chip: **Timed beats**. 6 s.

- **First frame:** Macro, a chef's knife mid-slice through a bunch of
  scallions on a dark wooden board, green rings rolling off the blade, a
  hand in a white sleeve at frame left. Warm kitchen light.
- **Motion:**
  ```
  GOAL: one 6-second clip in three timed shots, cutting between them.
  (0-2s) SHOT 1, macro: the knife finishes three quick slices through the scallions.
  (2-4s) SHOT 2, medium: a carbon-steel wok tossed over a high flame, the
  scallions and rice leaping, a burst of fire licking the rim.
  (4-6s) SHOT 3, wide, low: the finished plate slid across a steel pass under
  heat lamps, a hand pulling it away out of frame right.
  AUDIO: the knife's quick taps on wood; the roar of the burner and the sizzle
  as the wok lands; the plate's scrape on steel. Kitchen room tone.
  ```

### O2. Reference consistency (block 2, "Held to your photos")
Chip: **Product held steady**. 5 s.

- **First frame:** Close-up at chest height, two hands holding a white
  leather sneaker with no logos against a soft grey studio wall, already
  turning it; a cool window light from the left, a warm rim from the right.
  Shallow depth of field, the shoe tack-sharp.
- **Motion:**
  ```
  GOAL: one continuous 5-second take, no cuts.
  The hands keep turning the sneaker through one full rotation and tilt it to
  show the sole. Its shape, stitching, laces and sole pattern stay exactly the
  same the whole time.
  CAMERA: locked-off close-up, shallow focus.
  AUDIO: the soft creak of leather, a lace tapping the upper, quiet studio tone.
  ```

### O3. Native audio sync (block 3, "Sound is generated with the frame")
Chip: **Native audio sync**. 5 s. Needs the sound toggle on the overview's
video slot (a small component change), or it plays muted.

- **First frame:** Close side angle at table height, a tall clear glass on
  a dark stone counter, three ice cubes mid-fall into it, a bottle of
  amber soda tilted above it at frame right, condensation on the glass.
- **Motion:**
  ```
  GOAL: one continuous 5-second take, no cuts. Every sound lands on its frame.
  The ice cubes hit the glass one after another; the soda pours in, foams up
  near the rim and settles; a slice of lime drops in at about 4s.
  CAMERA: static, close, shallow focus.
  AUDIO, synced: three distinct ice clinks; the pour's glug and rising fizz; the
  hiss of the foam settling; the small splash of the lime. Nothing else.
  ```

### O4. 480p draft, 720p final (block 4, "Priced before you spend")
Chip: **480p draft · 720p final**. 5 s, rendered twice from the same first
frame and prompt: 480p first, 720p only once the draft is approved. The
block shows the two under one divider, so the page's claim is how its own
media was made.

- **First frame:** Dusk on a coastal road, a vintage motorcycle with no
  badges parked at the edge, its chrome catching the last orange light; a
  gloved hand already reaching for the key; the sea a blue blur below.
- **Motion:**
  ```
  GOAL: one continuous 5-second take, no cuts.
  The gloved hand turns the key; the headlight flicks on and throws a beam
  across the road; the engine catches and idles, the bike trembling slightly.
  CAMERA: slow push-in from a three-quarter front angle.
  AUDIO: the key's click; the starter; the engine catching into a low idle;
  wind and distant surf.
  ```

---

## 6. The wall (eight tiles, 480p, 5 s each)

Built as the SHOWCASE wall (2026-10-07, after ByteDance's "Creativity
Unleashed" grid): three masonry columns, an "I2V" chip on each tile, the
feature along the bottom, and the prompt opening right under the tile on
click, with "Use this prompt" into the composer. Frames are Seedance's own
(it takes no 4:5); the entry's order deals them into even columns. The
prompts live on the tiles in `entries/seedance-video-generator.ts`.

| # | Label (feature) | Chip | Frame | First frame | Motion + sound |
|---|---|---|---|---|---|
| 1 | Scale and atmosphere | Wide establishing | 16:9 | A lone figure in a long dark coat crossing a white salt flat at blue hour, tiny in the lower third, a low ridge of mountains behind | She keeps walking left to right as wind lifts the coat and drives a thin haze of salt across the ground; wind, crunching footsteps |
| 2 | Micro detail | Macro detail | 9:16 | Extreme macro: a ribbon of honey already falling from a wooden dipper onto a honeycomb, light glowing through it | The honey folds over itself and pools into the cells, a drip stretching and snapping; the faint tick of the drip |
| 3 | Push-in | Slow push-in | 4:3 | An empty theatre, a dancer in a pale slip dress mid-turn on a bare stage under one spotlight, seen from the stalls, face in shadow | The camera pushes slowly in as she completes the turn and sweeps into an arabesque, dress trailing; her feet on boards, the hush of the hall |
| 4 | Spray and momentum | Handheld follow | 3:4 | A skateboarder in a dark rain jacket mid-carve through a rain-slick concrete underpass at blue hour, low camera just behind, sodium lights doubled in the puddles, face turned away | The camera follows low and close as the board carves left then right, throwing a fine spray; wheels on wet concrete, the hiss of spray, the underpass echo |
| 5 | Multi-beat action | Top-down reveal | 9:16 | Directly overhead, a long oak table at dusk half set for dinner: stoneware plates, linen, figs, bread, candle stubs, one hand placing a plate | In order: a plate set down, a glass, a napkin folded, a match struck and a candle lit; the camera rises slowly; each sound on its action |
| 6 | Rack focus | Camera control | 16:9 | A clear unlabelled glass perfume bottle on wet black slate, droplets sharp on the glass; behind it a figure in a cream coat, soft and out of focus, passing a rain-streaked window | Focus pulls from the droplets to the figure as she passes, then back to the bottle; rain on glass, one distant car |
| 7 | Backlight and water | Golden hour | 3:4 | A surfer walking out of the sea at golden hour, board under one arm, backlit, water sheeting off the wetsuit, seen from behind at three-quarters | She walks up the wet sand toward frame right, the sun flaring through the spray, hair dripping; surf, wind, footsteps in wet sand |
| 8 | Rain and steam | Night exterior | 3:4 | A street noodle stall at night in rain, steam rising under one bare bulb, a cook's arm lifting noodles high with long chopsticks, rain streaking through the light, no signage | The noodles lift and drop back into the pot, steam rolls up through the rain; the boil, rain drumming on a tarp, the clack of chopsticks |

---

## 7. The signature (three stills of ONE scene, no video)

The signature is "one scene, three timed shots", so its three frames must
be the same scene, which no longer matches the wall's first three tiles.
It gets its own three frames (a small change: the entry carries them and
`shot-timeline.tsx` reads them instead of `wall.tiles[0..2]`). Stills only,
15 s as today:

1. **Wide establishing, 0-5 s.** A small ceramics studio at dawn, a potter
   at a kick wheel by a tall window, dust hanging in one shaft of light.
2. **Macro detail, 5-10 s.** Wet thumbs opening clay on the spinning wheel,
   slip running over the knuckles.
3. **The action, 10-15 s.** Clay-dusted hands lifting a glazed indigo cup
   toward the window light.

Copy unchanged except "workshop" becomes "ceramics studio".

---

## 8. For Mike to decide

- [ ] The twelve subjects: keep, swap or rewrite any of them
- [ ] Overview at 720p (about $20.46 in all) or everything at 480p (about $15)
- [ ] Mark up any first frame or motion line
- [ ] The signature's own three stills (section 7)

How it renders once approved: the 15 stills go through zeropage's
`generate_image` on Seedream 4.5 and land on the Assets wall. Seedance 2.5
is on this branch only, so the twelve clips render from this machine
through `src/fal.py` on the local `FAL_KEY` until the branch is merged and
deployed; after that they can go through the Queue instead.
