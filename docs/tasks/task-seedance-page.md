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

## 2. Signature: the scroll-scrubbed scene (`shot-timeline.tsx`), done 2026-10-07

- [x] Three shots matched to the signature's own stills (`signatureFrames`, a ceramics studio at dawn), each line now carrying its sound: "the wheel's low hum, a bird outside" / "wet clay under the thumbs" / "a fingertip taps the rim"
- [x] Length kept at 15 s in three 5 s windows (the page's clips are snippets)
- [x] Eyebrow "One scene, three timed shots"; title "Each shot is its own Seedance 2.5 clip."
- [x] Frames: three Nano Banana Pro stills drawn on Runway (60 credits)
- [x] Phone: the pinned block was 698 px in a 607 px pin on 375x667; tightened below md only (padding, gaps, card height, caption size) to 572 px

## 3. The wall (`SEEDANCE_TILES`)

- [ ] Title: "Shots Seedance Renders"; button "See the features" -> `#features`
- [ ] Eight tiles, all gradient plates today: Wide establishing, Macro detail, Slow push-in, Handheld follow, Top-down reveal, Rack focus, Golden hour, Night exterior (tags "Shot 1".."Shot 8")
- [ ] Media: eight Seedance stills from the studio as `src` (928x1152 JPEG under `web/public/models/seedance-video-generator/`); slot order follows the bento (0 short, 1 and 4 tall, 5 wide, 6-7 the pair)

## 1b. Overview (new section, 2026-10-07)

- [x] The template gained an optional `overview` slot between the hero and the signature (`components/overview-section.tsx`): statement blocks in the shape of ByteDance's own 2.5 page, text and a media slot alternating sides
- [x] Four blocks for Seedance, each of ByteDance's headings restated as what the studio does: longer narratives (30 s, timed beats, one take or a cut, six frames), smarter reference (keyframes off your photos, continuity), audio with the picture (diegetic sound, in the price), production (480p draft, price on the card, one MP4)
- [ ] Media: one Seedance 2.5 clip per block (`media: { video, src }`); plates until then

## 4. Features ("Seedance 2.5 in the Studio", nine cards, rewritten 2026-10-07)

- [x] Sound with the picture
- [x] Up to 30 seconds a shot
- [x] Timed beats, in order
- [x] One take, or a cut
- [x] Image to video, from your photos
- [x] Keyframe first
- [x] Draft cheap, then approve
- [x] Reusable elements
- [x] Export one MP4
- [ ] Not on the page, not wired: reference-to-video (`image_urls`, up to 30), the end frame (`end_image_url`), dialogue in quotes with lip sync, extend; white-model / green-screen / video editing need inputs the composer does not take

## 5. Models row ("7 Video Generator Models"), done 2026-10-07

- [x] Seedance 2.5, Seedance 2.0, Seedance 2.0 Fast, then the fourth card for the rest
- [x] Each named card opens the composer on ITS model ("Render on Seedance 2.0"), not the page's 2.5 spark (`modelCards(featured, spark)`)
- [x] The fourth card links to /models ("See every model") instead of sign-up, on every model page
- [x] Prices name the frame they are for ("568 credits for a 5-second 720p clip"), on every model page

## 6. How to ("How to render on Seedance 2.5"), done 2026-10-07

- [x] Rewritten to main's flow (the branch is behind main; the page must match what ships): 1. Write the scene (Create, references, timed shots with sound) / 2. Send it to the Queue (Send to Queue is the pick; keyframes drawn in the Queue, priced on the button) / 3. Approve on Seedance 2.5 (model, length, frame per shot; then the editor exports one MP4)
- [x] "The board" and "the Director" are gone from the copy: the studio's menu is Projects, Create, Assets, Edit, Elements, Queue. The Keyframe first feature card was corrected the same way.

## 7. FAQ ("FAQs about Seedance 2.5", nine rows), done 2026-10-08

- [x] Every answer checked against main: plans Starter / Creator / Studio, reference gate still refuses a scene with no photos, scenes clamp to 4-30 s, /terms exists
- [x] FIXED a false claim: the Queue renders text-to-video when a shot has no keyframe (the card says so), so "a Seedance clip always starts from a frame you have seen" became "Both. Draw a keyframe and it renders image-to-video; approve without one and it renders text-to-video"
- [x] Q1 names 2.5 (30 s a shot, sound in the same pass); references answer says Create, not "the composer"
- [x] Added "Does Seedance 2.5 make sound?" (diegetic sound, same pass, in the price)

## 8. Related and close

- [ ] `related` is still only `ai-product-ad-generator` (written before the other model pages existed): add the video pages -- kling, veo, wan, ltx
- [ ] Final CTA: "Your first scene" / "Render your first scene on Seedance." / "Write it, see every keyframe, see the price, approve."

## 9. Check

- [ ] 375 / 768 / 1440 in the preview, the signature pinning and un-pinning cleanly
- [ ] The Models dropdown and the footer's Models column still read "Seedance 2.0"
- [ ] `npx tsc --noEmit`, `npx eslint src`
- [ ] Lighthouse mobile if the media landed (last: perf 84, a11y / BP / SEO 100, CLS 0)
