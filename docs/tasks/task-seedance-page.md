# Task: the Seedance page (#5 of docs/tasks/task-landing-pages-edit.md)

Started 2026-10-06. Route `/models/seedance-video-generator`, entry
`web/src/landing-pages/entries/seedance-video-generator.ts`, accent INDIGO
(`theme.ts`), signature `shot-timeline` (`components/shot-timeline.tsx`).
Preview: `preview_start web`, then http://localhost:3000/models/seedance-video-generator.
One commit per finished section, or one at the end: `feat(web): /models/seedance-video-generator -- <what changed>`.

What the page rests on (re-checked 2026-10-06 against `src/fal.py
VIDEO_MODELS` and fal's pages): **the page is the Seedance 2.5 page**
(Mike's call, 2026-10-06). Seedance 2.5 was added to the catalog that day
(`seedance2.5`: `bytedance/seedance-2.5/{text,image}-to-video`, 4-30 s a
clip as a string on the wire, 480p $0.2205/s, 720p $0.4730/s, 1080p
$1.164/s, audio generated with the picture and included in the rate, no
fast tier; Creator band, 1080p premium; `python -m src.pricing export`
run). Seedance 2.0 Fast (480p/720p) and Seedance 2.0 (adds 1080p) stay on
the page as the family, 4-15 s a clip. Image-to-video off the shot's
keyframe on all three.

## 1. Hero

- [x] `title` (the <title>): "Seedance 2.5 AI Video Generator"
- [x] `h1`: "Seedance 2.5" (menu line the same; the title tag keeps "AI Video Generator" for search)
- [x] `subhead`: "Write a scene, anchor every shot on your reference photos, and render it on Seedance 2.5, 4 to 30 seconds a clip with sound, up to 1080p."
- [x] CTA label "Make a scene"; secondary "See the shots" -> `#shots`
- [x] The spark the composer opens on: "A 30-second scene in three timed shots: a wide establishing shot, a close detail, the action. Render on Seedance 2.5."
- [x] `description` (meta + OG): one line, 2.5, 4-30 s with sound, 480p to 1080p, priced before approve

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
