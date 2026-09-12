# Midjourney prompts — matched to the two reference clips (2026-09-04)

## What the references actually are (read this before prompting)

**Ducati night run.** Two looks, hard-cut: (1) ultra-tight sodium-orange under an
overpass — fairing, ECU, helmet, warm tungsten, shallow focus; (2) cold teal-cyan
fog, wide side-on tracking, white superbike doing a slow roll / burnout on wet
asphalt, apartment block behind, ONE warm accent (a red neon sign), headlight halo
in the haze, mirror reflections in the wet. Commercial-grade, hazed, anamorphic feel,
high contrast, glossy. **Nothing about it is "raw handheld / matte / imperfect"** —
which is exactly what every prompt in the pipeline asks for. That is why the keyframes
read flat.

**Horror woman.** Blue-hour suburban street, drizzle, a house with warm windows and a
red emergency-light spill on one wall. A wet man drags a hunched wet woman by the arm;
insert of a woman crying behind rain-streaked amber glass; she looks up and her face is
wrong (grin, rotted teeth). Teal shadows / amber windows / red accent. Face-forward,
one turn, five seconds. **It needs a face.** Zero Page's faceless rule fights this look
head-on — flag, don't silently break.

Common DNA: teal-and-amber split, one red accent, wet surfaces, haze, blue-hour or
night, 35–50mm feel, subject small-to-mid in a wide frame with a tight insert cut
against it, polished not gritty.

Use the six frames in `sref/` as `--sref` (style) and, for Michael, your own photos
as `--cref`. Upload the frame, copy its URL, append `--sref <url> --sw 200`.

---

## A. Moto — the Ducati look (Antihero)

1. `cinematic night frame, white superbike mid-burnout on wet asphalt, rider in white and red leathers crouched low, dense teal-cyan fog, headlight halo in the haze, single red neon sign glowing in the background, apartment block silhouettes, mirror reflections on the wet ground, anamorphic lens flare, high contrast, commercial automotive film still, 9:16 vertical --ar 9:16 --style raw --s 150 --v 7`

2. `extreme close-up under a highway overpass at night, sodium-orange tungsten light, white superbike fairing and ECU in shallow focus, helmeted rider leaning in, visor reflecting the orange, condensation on the tank, rich blacks, 85mm, cinematic automotive commercial --ar 9:16 --style raw --s 120 --v 7`

3. `wide side-on tracking frame, white superbike leaning through a slow turn on a flooded car park at night, fog machine haze, cold teal ambient with one warm red practical, long light streak of a passing car, tyre smoke catching the headlight beam, anamorphic, glossy high-end motorcycle film --ar 9:16 --style raw --s 150 --v 7`

4. `low angle from the wet ground, white superbike rear tyre spinning up spray and smoke, rider's boot planted, teal fog above, red neon reflected in the puddle in the foreground, headlight flare bloom, cinematic grade, 9:16 --ar 9:16 --style raw --s 130 --v 7`

5. (keyframe for "The Passenger") `night intersection under a red traffic signal, white superbike idling, rider in white and red leathers seen from the side, a second black helmet strapped to the empty pillion seat, visor fogged from inside, teal haze, wet asphalt reflecting the red light, one warm streetlamp, anamorphic, commercial film still --ar 9:16 --style raw --s 140 --v 7`

## B. Horror — the blue-hour turn (Zero Page, face-forward variant)

6. `blue-hour suburban street in light rain, a two-storey house with warm yellow windows and a red emergency light spilling on its side wall, wet road reflecting both, a drenched man in a black t-shirt pulling a hunched wet-haired woman by the arm, her face hidden, teal shadows and amber highlights, 35mm, cinematic horror short film still --ar 9:16 --style raw --s 100 --v 7`

7. `tight insert, a young woman's face pressed close behind rain-streaked glass, warm amber light behind her, wet hair stuck to her cheeks, crying, one palm flat on the glass, water droplets in sharp focus, shallow depth, teal exterior reflection at the frame edge, cinematic horror --ar 9:16 --style raw --s 100 --v 7`

8. (the turn) `blue-hour street in drizzle, a drenched woman lifting her head toward camera, wet black hair parted over a face that is wrong — too-wide grin, darkened rotted teeth, pale skin — while a man's hand still grips her arm out of focus, house with lit windows and red light behind, teal and amber, practical realism, no gore, cinematic horror still --ar 9:16 --style raw --s 100 --v 7`

9. (faceless Zero Page version of the same beat) `blue-hour suburban driveway in rain, seen from behind a drenched man's shoulder as he grips a wet-haired woman's wrist, her head bowed so only hair shows, house with warm windows and a red light on the wall, wet asphalt, teal shadows amber highlights, 35mm, cinematic horror short --ar 9:16 --style raw --s 100 --v 7`

10. `blue-hour, a lit house at the end of a wet street, one upstairs window warm, a red police-style light strobing on the side wall, a lone figure standing in the road with their back to camera, drizzle visible against the light, teal and amber, cinematic dread, 9:16 --ar 9:16 --style raw --s 110 --v 7`

## C. Shared-look plates (either brand)

11. `empty wet car park at night in dense teal fog, one red neon sign in the distance, sodium streetlamp at the edge, headlight halo entering frame, mirror reflections, anamorphic, cinematic plate, no people --ar 9:16 --style raw --s 150 --v 7`

12. `rain-streaked window at night from inside, warm amber interior, cold teal street outside with one red light, condensation, shallow focus on the droplets, cinematic insert --ar 9:16 --style raw --s 100 --v 7`

---

### Why the pipeline's own prompts miss this
`prompts/enhance_system.txt` and the scene brief both push "raw handheld, natural
shake, imperfect framing, matte, muted, NOT glossy, no smooth camera moves." Both
reference clips are the opposite: hazed, glossy, high-contrast, commercial, smooth
tracking. That house style was chosen to fight the CG look; it now fights the
references. The fix is a **look block** per brand in `prompts/` that the enhance step
respects instead of overriding — not a prompt-by-prompt patch.
