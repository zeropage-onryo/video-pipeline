# Prompt Techniques: Seedance 2.5 Realism Cheat Codes

Source: "the cheat codes to prompting for true realism with Seedance 2.5 (free claude skills)" — https://www.youtube.com/watch?v=5dWgZDka3Ww

Reusable techniques, ready to apply to any shot prompt.

---

## 1. Costume/identity disambiguation

If a character could be misread as a literal creature/animal vs. a designed character (a costume, a practical effect, a specific creature design), state explicitly what it *is* rather than relying only on negative constraints. This tells the model which physics/anatomy/behavior rules to apply.

> Example from source: "This is a human wearing a gorilla costume, treat it as such" — so the model doesn't render it as a real gorilla.

Applies in either direction: state "this is a real creature, not a person in a suit" just as validly if that's the risk you're fighting.

---

## 2. Prompt ordering — critical constraints go at the very top

Models weight information near the top of a prompt more heavily. Recommended order, top to bottom:

1. Shot count, total duration, per-shot breakdown (what happens, how many seconds each)
2. Hard constraints / negatives (e.g., "no music whatsoever" if audio bleed is an issue)
3. Style block
4. Texture block
5. Motion, camera, blocking detail

---

## 3. Style block template (photoreal, non-CG)

> 8K photorealism, real organic film grain, halation, high dynamic range, shot on large format film. Not a 3D render, not a game engine, not a game cutscene aesthetic.

---

## 4. Texture block template

> Matte, non-reflective surfaces. Lived-in, worn materials.

---

## 5. Start mid-motion — avoid static bookending

Don't let a shot start or end with a character beginning/finishing an action from complete stillness. Prompt so the first frame is already mid-motion or mid-action. Reads as more organic, less like an obvious AI generation start/stop.

---

## 6. Extend Video for continuity (Seedance 2.5, up to 30s)

Instead of (or alongside) last-frame chaining, feed an existing clip into Extend Video and prompt it as a "sequel" (continues after) or "prequel" (happens before) the source clip. It analyzes the whole video automatically for placement and appearance.

Workflow:
1. Drop the source clip into Claude, ask it to analyze frame-by-frame — positions, appearance, exact hand/body placement.
2. Have Claude write the continuation prompt preserving that physical continuity explicitly (e.g., "hand stays on X" rather than re-describing the pose generically).
3. Feed that prompt into Extend Video along with the source clip.

---

## 7. Director mindset — specify blocking explicitly

Under-specified blocking causes failed generations. Always state:
- Which side of frame the character enters from
- What the camera is doing (track, push in, hold focus on)
- The character's expression/emotional beat during the action

---

## 8. Ground it in references — don't write a shot from adjectives alone

Text alone underspecifies appearance, wardrobe, location, and grade. Before a shot counts as finished, check whether a reference exists (and could be attached) for each of: character/identity, wardrobe, location/environment, lighting/color-grade, camera-technique, and continuity (the source clip's own frames, on a follow-up shot). If a shot clearly needs one of these and none exists yet, say so and name what to gather — a photo to take, a frame to pull from existing footage — rather than writing from adjectives alone and hoping the model guesses right.

The rule that makes this safe: only attach a reference for what the shot should *reproduce*. Feeding a reference image (or seed frame) into a generation anchors the model hard on that image's scene — reliable when the new shot should resemble it (a wardrobe close-up, the same location, matching grade), but if the new shot needs a *different* scene, environment, or framing, the model tends to reproduce the reference's scene almost verbatim regardless of how the text prompt is worded. Attach the reference when the shot should resemble it; describe the new scene in text only — keeping just a character/identity anchor if one exists — when the shot needs to diverge from it. This has been observed directly in this pipeline's own image work (Higgsfield `soul_2` + a `medias` reference): every attempt pairing a reference photo with a prompt for a different scene reproduced the reference's scene near-verbatim, independent of prompt wording.
