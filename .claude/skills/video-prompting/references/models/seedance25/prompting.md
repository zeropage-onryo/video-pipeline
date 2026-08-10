---
title: Seedance 2.5 — Prompting & Reference Reference
type: prompt-reference
model: seedance-2.5
source_video: https://www.youtube.com/watch?v=UxwV16jDglA
source_channel: (AI filmmaking tutorial)
captured: 2026-08-08
status: draft — verify field names against your agent schema
tags: [video-gen, seedance, character-lock, references, ugc, prompting]
summary: >
  Working notes distilled from a Seedance 2.5 walkthrough. Two prompt
  formats (simple / advanced), how references changed (30 img / 10 vid /
  10 audio), the shift away from character sheets toward multi-angle
  distinct-subject packs, editing/extension workflow, and credit discipline.
---

# Seedance 2.5 — Prompting & Reference Reference

> Notes are paraphrased/distilled from the source tutorial, not a verbatim
> transcript. ASR-garbled names corrected: **Seedance** (not "Cance/Cense/Seance"),
> **Higgsfield** (platform, not "Hicksfield"), **Claude** (not "cloth"),
> **Nano Banana Pro** / **GPT Image** (reference generators), **Dreamina 2.5**.

## TL;DR / what changed in 2.5

- **30-second generations** now possible — but each gen costs proportionally
  more, so prompt with intent, not slot-machine spam.
- **Resolution: 720p only** at time of recording (1080p/4K expected later; plan
  to upscale for now).
- **Reference ceiling per request:** 30 images, 10 videos (30s combined), 10
  audio clips (30s combined). You *can* max these; you generally *shouldn't*.
- **Realism is the standout** — in the creator's side-by-side vs Seedance 2 and
  Kling, 2.5 held finer skin/face detail (freckles, texture) even at 720p while
  the others read plasticky.
- **Best-in-class in-video editor** (see Editing section) — first-gen no longer
  has to be perfect.

---

## Prompt Format A — Simple ("let Seedance fill the details")

Use when you have a clear idea and one or two references and want fast output.
You describe like a director; you do NOT timestamp every second.

```text
References:
  image 1: <who/what — e.g. "woman, mid-20s, [look]"> (loop/character ref)
  image 2: <other subject, if any>
  audio 1: <voice reference — match to dialogue>

Scene context: <where we are, who's there, time of day, is it one continuous take>

Technical: <lens, depth of field, grain, camera behavior>

Dialogue: <language + accent + approx age, e.g. "male, Dutch accent, ~25">

Scene description (director's beats, not timestamps):
  cut 1: <what happens>
  cut 2: <what happens>
  cut 3: <what happens>
  (one continuous take = no cuts; describe the single shot + all dialogue)

Keep consistent: <the things that must not drift — face, wardrobe, etc.>
```

Reference example distilled from the video: a single loop reference of a subject
doing a handheld vlog "on a date in Japan, early morning into night," with the
prompt written from the POV of the person holding the camera. One image, simple
prompt, strong result.

---

## Prompt Format B — Advanced (staged, director-grade)

Use for multi-shot sequences, tight continuity, or anything expensive enough
that you want to think it through. This is the format the creator used for most
serious work.

```text
GOAL: <what a successful clip looks like> (duration optional — set it in the UI)

REFERENCES: <describe what each ref is; GROUP refs of the same subject/angles>

CONTINUITY:
  Character A: <appearance + wardrobe held the entire way through>
  Character B: <same>

SCENE: <location / world>

STAGES (one per shot):
  Stage 1 @ ~00:03 — "<segment name>": <what happens + how it's framed>
  Stage 2 @ ~00:XX — "<segment name>": <...>
  ... (add stages per shot)

LOOK: <sharpness, format/clarity e.g. handheld-phone, color, grain, lighting,
       shadow, mood>

CAMERA & PERFORMANCE: <cut pace (fast/punchy vs slow), how characters carry
                       themselves>

AUDIO: <music? style? SFX? ambience? subtitles? — keep tracks SEPARATE>

RULES:
  - Keep consistent: same Character A, same Character B (customize per shot)
  - Do NOT include: brand logos, extra people, on-screen text, <other exclusions>
```

Example goal from the video: *"cinematic chase sequence, large-format IMAX
clarity,"* staged out (stage 1 = first four seconds, stage 2 = "approaching the
edge," camera stays close, etc.).

---

## References — the big mindset shift

**Stop leaning on single character sheets. Build multi-angle distinct-subject packs.**

- A "distinct subject" = one person/object described across *many* angles, all
  grouped as one subject. Example: 4 face angles + 4 body angles = **one**
  distinct subject. This gives the model far more context than a 3-view sheet.
- Seedance's own guidance (per the video): **1–8 distinct subjects** across your
  image refs — not 30 random images. Group, don't dump.
- Character sheets still work and appear in the video, but are no longer the
  recommended default now that you can supply rich multi-angle context.

**Per-request limits (again):**
| Type   | Limit                                    |
|--------|------------------------------------------|
| Images | 30                                       |
| Videos | 10 clips, **30s combined** (e.g. 1×21s + 9×1s) |
| Audio  | 10 clips, **30s combined**               |

- Video refs: aim for **1–5 distinct subjects**, ~5–10s per subject.
- Audio: keep tracks purpose-separated — dialogue / voice characteristics /
  ambience / music on their own tracks. **Don't** mix voice + music in one clip.

### Reference-image build template

Generate refs with **Nano Banana Pro** or **GPT Image** (creator leans GPT Image
for realistic *characters*; either for objects).

```text
Image type: <e.g. product still, character angle>
Subject: <the thing — e.g. "extremely long oversized trench coat">
Design: <colors, material, details>
Pose: <how it's positioned>
Environment: <e.g. pure white seamless studio background>
Camera: <framing>
Exclude: <what must not appear>
Aspect: 4:5 (not 16:9 — captures the full subject)
```

For a main character sheet: make the base character image, then ask Claude/GPT to
render it as a 2- or 3-sided view.

---

## Self-as-subject / UGC workflow (directly relevant to your pipeline)

The creator's UGC ad pattern, generalized:

1. Generate the **product** in multiple angles from one clean reference (he got 6
   angles of a shoe from one ref).
2. Generate **yourself** as the UGC talent: feed one selfie → produce ~4 angles
   (2 front, 1 side, 1 back).
3. Add a **short voice reference** (~16s of your own prior recording is enough to
   get a decent voice match).
4. Hand the idea + all refs to **Claude with an MD file** → it writes the prompt
   and tags the references for you.
5. Paste into Higgsfield / Dreamina 2.5, upload refs, generate.

> Note the loop: an MD reference file (like this one) is explicitly used as the
> tool that helps write the look-and-feel prompt. This doc is meant to be that
> input for your agents.

---

## Editing (2.5's strongest single feature)

Treat first-gen as a draft — edit rather than reroll:

- **Add elements:** e.g. populate an empty cinema with a crowd — 2.5 matches
  lighting/scale far better than 2.0.
- **Swap objects:** chips → popcorn, change a door's color — everything else
  holds.
- **Audio:** add or remove a background music track by prompt.
- **Reframe-and-regenerate (tip credited to X):** cut the exact frame/scene you
  like, feed it back as the new starting reference, then prompt "do it better."
  Locks in a good look before refining.

---

## Length & continuity — credit discipline

- **Avoid the "long video" (up to 180s) mode.** It's really six 30s clips
  stitched from **one ~5,000-char prompt** — not enough detail per minute.
- For continuous/matching scenes, **chain**: use the previous clip as a reference
  and describe what happens next. Lets you introduce new refs mid-sequence and
  stitch seamlessly.
- You can also pass video 1 + video 2 and prompt for a seamless combine.

---

## Actionable — how this plugs into your stack

- [ ] Adopt **Format B** as the default template your generation agent fills;
      keep **Format A** as the fast-path for single-subject shots.
- [ ] For yourself-as-character-lock: replace single character sheets with a
      **multi-angle distinct-subject pack** (4 face + 4 body). Mirrors what
      you're already doing with Gen-4 References — build the pack once, reuse.
- [ ] Standardize a **voice-ref clip** (~15–20s, clean) as a pipeline asset.
- [ ] Test Seedance 2.5 against your current Runway/Kling/Veo bench on the
      *realism + freckle/skin-detail* axis at 720p, since that's its claimed edge.
- [ ] Build the **reframe-and-regenerate** step into the agent loop: cut best
      frame → reseed → refine, instead of full rerolls (saves credits).
- [ ] Keep audio tracks separated by role in whatever manifest your agents emit.

---

## Open questions to verify before trusting this in an agent

- Current res cap (720p at capture time — check for 1080p/4K now).
- Exact per-gen credit cost at 30s on your platform (Higgsfield vs Dreamina vs direct).
- Whether the 1–8 distinct-subject guidance holds at your typical ref counts.
