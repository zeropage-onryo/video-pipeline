# Task: the Seedance page (#5 of docs/tasks/task-landing-pages-edit.md)

Started 2026-10-06. Route `/models/seedance-video-generator`, entry
`web/src/landing-pages/entries/seedance-video-generator.ts`, accent INDIGO
(`theme.ts`), signature `shot-timeline` (`components/shot-timeline.tsx`).
Preview: `preview_start web`, then http://localhost:3000/models/seedance-video-generator.
One commit per finished section, or one at the end: `feat(web): /models/seedance-video-generator -- <what changed>`.

What the page rests on (checked 2026-10-05 against `src/fal.py VIDEO_MODELS`
and the Queue): Seedance 2.0 Fast (480p/720p) and Seedance 2.0 (adds 1080p,
the premium band), 4-15 s a clip as a string on the wire, image-to-video off
the shot's keyframe, both on Creator and up. Seedance 2.5 is on fal
(text / image / reference-to-video, 4-30 s, 480p and 720p with audio) and
NOT in the catalog -- the page must not name it until the model is added and
`python -m src.pricing export` has run.

## 1. Hero

- [ ] `title` (the <title>): "Seedance AI Video Generator"
- [ ] `h1`: "Seedance Video Generator" (menu line the same)
- [ ] `subhead`: "Write a scene, anchor every shot on your reference photos, and render it on Seedance, 4 to 15 seconds a clip, up to 1080p."
- [ ] CTA label "Make a scene"; secondary "See the shots" -> `#shots`
- [ ] The spark the composer opens on: "A 15-second scene in three timed shots: a wide establishing shot, a close detail, the action. Render on Seedance."
- [ ] `description` (meta + OG): one line naming both tiers, 4-15 s, up to 1080p

## 2. Signature: the scroll-scrubbed scene (`shot-timeline.tsx`)

- [ ] The three shots' labels and lines (`SHOTS` in the component: "Wide establishing" / "Macro detail" / "The action", a workshop at dawn)
- [ ] The scene length (15 s, three 5-second windows) -- matches what Seedance renders
- [ ] The eyebrow and title: "One scene, three timed shots" / "Each shot is its own Seedance clip."
- [ ] Frames read the wall's first three tiles; a real still on a tile shows here too
- [ ] Pin length (2.6 screens) and feel on a phone

## 3. The wall (`SEEDANCE_TILES`)

- [ ] Title: "Shots Seedance Renders"; button "See the features" -> `#features`
- [ ] Eight tiles, all gradient plates today: Wide establishing, Macro detail, Slow push-in, Handheld follow, Top-down reveal, Rack focus, Golden hour, Night exterior (tags "Shot 1".."Shot 8")
- [ ] Media: eight Seedance stills from the studio as `src` (928x1152 JPEG under `web/public/models/seedance-video-generator/`); slot order follows the bento (0 short, 1 and 4 tall, 5 wide, 6-7 the pair)

## 4. Features ("Seedance in the Studio", nine cards)

- [ ] Two Seedance tiers (reads both names off the catalog)
- [ ] 4 to 15 seconds a shot
- [ ] Image to video, from your photos
- [ ] Keyframe first
- [ ] Price before spend
- [ ] Reusable elements
- [ ] Guided writing
- [ ] Export one MP4
- [ ] Everything on one wall

## 5. Models row ("6 Video Generator Models")

- [ ] Seedance 2.0, Seedance 2.0 Fast, Kling 3 Turbo Pro, then the fourth card for the rest (off the catalog, prices included)

## 6. How to ("How to render on Seedance")

- [ ] 1. Write the scene / 2. Check each keyframe / 3. Approve on Seedance

## 7. FAQ ("FAQs about Seedance", eight rows; the answers are the FAQPage JSON-LD)

- [ ] What is the Seedance video generator?
- [ ] Which Seedance models can I render on? (names both off the catalog, links /models)
- [ ] How long can a Seedance clip be?
- [ ] Can I use my own photos as references?
- [ ] Does it keep the same character or product across shots?
- [ ] Does the Queue render text-to-video or image-to-video?
- [ ] Which plan do I need? (links /pricing)
- [ ] Can I use the clips commercially? (links /terms)

## 8. Related and close

- [ ] `related` is still only `ai-product-ad-generator` (written before the other model pages existed): add the video pages -- kling, veo, wan, ltx
- [ ] Final CTA: "Your first scene" / "Render your first scene on Seedance." / "Write it, see every keyframe, see the price, approve."

## 9. Check

- [ ] 375 / 768 / 1440 in the preview, the signature pinning and un-pinning cleanly
- [ ] The Models dropdown and the footer's Models column still read "Seedance 2.0"
- [ ] `npx tsc --noEmit`, `npx eslint src`
- [ ] Lighthouse mobile if the media landed (last: perf 84, a11y / BP / SEO 100, CLS 0)
