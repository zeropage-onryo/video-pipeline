# The assistant's face: looks and states (2026-10-07)

## The floating creature and the dock (2026-10-09): they replaced the pill

Mike asked for the creatures to be "bigger and floating", to "have thoughts instead of a chat
box", and for a chat that opens from them; every step was designed and picked on the "Creature
Companions" canvas (https://claude.ai/artifact/QkzWQd3ZYXsWzwFjMt8DsR) before any code. What he
picked:

- **320px, floating.** The creature IS the assistant now: no pill. It floats in the bottom-right
  corner with a glow under it in its own colour (`tintOf`). Drawn from a new **640px** set
  (`site/mascot/v1/640/`, exported from the same frames as 128 and 320, so the sizes swap in
  place; `mascot.smallerSrc` falls back to 320 if a 640 file is missing). Smaller where the
  corner is taken: 200px above the minimap on a canvas page, 120px on a phone.
- **All eight reactions:** hover (it turns to listen and leans in), press (it squishes), drag
  (park it on either side at any height, kept per browser), idle (a slow drift on top of the
  float), working (a red ring fills on the floor), needs you (still, amber light and glow),
  didn't go through (one shake), asleep (z z z after 10 minutes).
- **Thoughts, "amber leads":** the one thing waiting on a click (a still to approve, a write to
  confirm, frames picked and not kept) is the thought nearest its head, edged amber, with the
  buttons that do it -- Approve there is the same click, at the same price, as on the card.
  While it works, the thought says what it is doing; after a failed turn, Retry; else a line it
  wants to say. Above, up to three of the latest answer's quick replies as small thoughts, and
  "Ask me anything".
- **Click opens the dock** (layout F): a drawer along the bottom, over the page (the page gets
  that much room at its end, `--zpa-clear`, so anything behind it can be scrolled into view).
  Conversation on the left, **On the table** in the middle (directions, the contact sheet, the
  newest still, a write to confirm, the Queue's price), the creature seated at its end with its
  head over the top edge -- the left end when it is parked on the left. Drag the handle (or the
  arrow keys) to resize; kept per browser. On a phone it is a sheet over the bottom bar, the
  table first.
- **Double-click makes it small** (80px, no thoughts, the amber light and unread count stay);
  a click brings it back. A click waits 240ms to tell the two apart (`lib/creature.ts`,
  `clickIntent`, node-tested); Enter or Space acts at once. The dock's header has a "make
  small" button too, for a keyboard.

`assistant-pill.tsx` keeps everything the assistant does (asking, keeping, approving,
confirming) and only draws differently; the creature and its thoughts are
`assistant-creature.tsx` + `assistant-creature.css`.

## The mascot (2026-10-08): it replaced the glyphs

Mike rejected the flat SVG round (the glyphs below) for a soft, plush 3D creature, with Meta
Muse's "Jolly" as the reference. What shipped:

- **Five creatures, names fixed:** Nimbus (the default, a lavender felt cloud), Mote, Sprout,
  Glim and Pip. Each has **three looks**, with the material and accessory baked into the
  render, for 15 looks in all.
- **Colours:** each look's own colour, plus light red, lavender, mint and sky. A look whose own
  colour is one of those four is not offered it twice. Six looks have 4 colours and nine have 5.
- **Seven moods:** awake, listen, think, talk, made, oops and sleep. 15 looks × colours × 7 moods
  = **483 images**, each exported as a transparent WebP at 128px and 320px.
- **Nothing is generated per person.** Every image was rendered once (Runway, Nano Banana 2 at 1K),
  cut out with fal's Bria remover, and framed so all of a look's colours and moods share one
  square. They are served from R2 at `site/mascot/v1/<size>/<look>-<colour>-<mood>.webp`. Bump
  the version when an image is redone, so no browser keeps a stale copy.
- **The persona:** `avatar` stores a code like `m:nf.own` (look `nf` = nimbus-felt, colour `own`),
  which fits `assistant_store.clean_avatar`'s 16 characters. The server did not change. The name is
  the creature's and never changes. The tone is the persona's existing three. An old emoji or glyph
  persona reads as Nimbus in lavender felt and keeps its tone. `lib/mascot.ts` holds the data and
  `web/tests/mascot.test.mjs` checks it.
- **States to moods** (`moodFor`): idle → awake, listening → listen, thinking and working → think
  (working keeps a neutral progress ring), talking → talk and awake in turn every 160ms (the
  lip-flap; a reply is streaming, `partial` on the job), needs → awake, still, with the amber light,
  success → made, error → oops, sleeping → sleep with the drifting z. Each state also gets its
  own body move from the canvas's Pill board: float, lean, bounce, hop, shake or breathe. All seven
  moods are stacked and cross-faded, so a change never waits on a download.
- **The customiser** is "Meet your assistant": Who (five creatures) → Look (that creature's
  three, drawn in the chosen colour) → Colour (swatches) → How it talks. The preview walks
  through every state.

The asset pipeline (renders, cut-outs, framing, export) lives outside the repo, in
`data/_scratch_mascot/` on Mike's machine; `HANDOFF.md` there has the steps. The rest of this
document is the glyph round it replaced, kept as history.

Mike asked for "front end designs for the pill" and "different interactive emojis or icons for it".
This is what was researched, what was built (`web/src/components/studio/assistant-avatar.tsx`
+ `assistant-avatar.css`), and what is left.

## What the field does

Nobody ships the thing we have. Checked October 2026:

- **LTX Studio** has no agent at all; its automation is the Flows node canvas.
- **invideo Agent Two** is a docked chat panel next to the timeline. You name it by role
  ("who should I be?"), but it shows no visible working or approval states.
- **Higgsfield Supercomputer** is a full-page chat that shows the plan up front and a running
  credit cost while it works. There's an "Ask before generating" toggle.
- **Runway Agent** keeps the work centre-stage and puts options on the canvas, not in chat.

The useful references for a *floating* helper come from outside video:

- **Siri on iOS 27** is a pill that grows out of a fixed anchor.
- **Notion AI** has a small line-drawn face whose expression changes while it works. That's
  about the upper limit of personality for a pro tool.
- **Duolingo** characters are built in Rive state machines (idle, listening, thinking,
  talking), with layered parts so the idle loop never repeats visibly.
- **Dia** keeps motion and colour for the AI only, so the rest of the UI stays quiet.
- **Raycast** lets you queue or steer while the AI is answering, and notifies you when a
  background chat finishes.

## Rules the face follows

1. **States read without colour.** Each state is a shape as well as a hue: an arc that fills,
   a steady light, a check drawn once, a notch.
2. **"Needs you" is the loudest state, and it does not move.** A steady amber ring plus a tally
   light reads louder than another loop on a page full of motion. The pill's border goes amber
   too. Approvals are the only persistent signal.
3. **Success and error play once.** No endless shimmer, no blinking.
4. **Motion belongs to the assistant only.** All of it stops under `prefers-reduced-motion`.
5. **The look is restrained.** It's a glyph on a lens, not a mascot. An emoji is an optional
   skin.

## The states

| State | When the pill shows it | What it looks like |
|---|---|---|
| idle | nothing happening | slow 4.6s breathing |
| listening | card open, text in the box | leans in, ring brightens, the glyph's own "attention" move |
| thinking | a turn is out, detail is "Thinking…" | the glyph ponders (iris closes, slate chatters, reel drifts, beam sweeps) |
| working | a turn is out and the job reports a step | the ring becomes a film strip with sprocket holes, and a red arc fills (`progress` 0–1) or sweeps |
| needs | the newest answer waits on a click: an unanswered confirm card, or a contact sheet with frames picked and not kept | steady amber ring, amber tally dot, amber pill border, "NEEDS YOU" in the mono line |
| success | 1.4s after a turn lands without failing | green ring, a check drawn once |
| error | a turn failed and is waiting to be resent | one shake, a red notch at the top |
| sleeping | 10 minutes with no activity and the card closed | desaturated, slower, a drifting z |

The pill's mono line also says the state in words (`Nova · Step 7 of 7 · NEEDS YOU`), so the
state is readable without seeing the ring.

## The looks (superseded by the mascot)

Eight glyphs plus nine emoji. A glyph is stored as `glyph:<id>` in the existing
`assistants.avatar` column. `assistant_store.clean_avatar` allows 16 characters with no
brackets or quotes, and every id fits, so nothing on the server changed. The default for a new
persona is `glyph:aperture`. Existing personas keep their emoji.

| id | name | its move |
|---|---|---|
| aperture | Iris | blades turn and close to think, open wide on success, red pupil |
| clapper | Slate | the stick chatters while thinking, claps on success, stripes march while working |
| reel | Reel | drifts while thinking, spins fast while working |
| lens | Lens | a flare drifts across the glass |
| tally | Tally | a camera tally light: green ready, red working, amber needs you |
| megaphone | Director | sound waves call out while listening or thinking |
| spot | Spot | the beam sweeps while it looks |
| finder | Finder | viewfinder corners frame in, the rec dot pulses while working |

Emoji skins: 🎬 🎥 📽️ 🎞️ 📣 🦊 🤖 👾 🐺, plus "Any…" for a free emoji.

**"Meet your assistant"** now opens on a large preview that cycles through every state every
1.7s, so the person sees the look moving before picking it. The selected glyph tile animates in
step with the preview.

## Where it is used

- `assistant-pill.tsx`: the perch avatar (56px), the card's badge (60px), and the setup preview
  and tiles. `face` is derived in one place from `busy`, `detail`, failed turns, a 1.4s
  landed flash, the waiting answer, the input text and a 10-minute rest timer.
- `app/studio/page.tsx`: the composer's "Filled by" note draws the face at 18px instead of
  printing the avatar string, so a glyph id never shows as text.

## Built on 2026-10-08 (items 1–4 of the old "not built yet" list)

1. **Real progress.** The reference hunt (`assistant_brain.find_references`) reports
   `on_step(done, of, detail)`. `of` is 0 while the scene is still being read, then 2 per need
   (search, look) plus reading and laying out the sheet. A need that finds nothing still counts
   its two, so the arc never stalls. The route writes it onto the job as
   `steps: {done, of}`, `progress` and `detail`. Any other note (a retry, "looked at
   find_references", "checking the directions") sets `steps` back to null, so the arc returns to
   its sweep while the model writes. The pill passes `steps.done / steps.of` as `progress`, the
   card's working line shows `2/8` beside the detail, and the face's title says the percentage.
   The arc fills smoothly toward each step (`stroke-dasharray` transitions).
2. **Unread badge.** `badge` on `AssistantAvatar`: a red count on the bottom corner (the tally
   keeps the top), `9+` past nine, popping in once per new count. The pill counts every answer,
   keep or confirm that lands while the card is shut (`openRef`, since a turn's closure holds the
   `open` it started with). Opening the card clears the count. The bubble says the answer's
   next move, or else its first sentence (`lib/assistant-text.ts headline`), and the pill's
   label reads "Open Nova — 1 new answer".
3. **Open/close morph.** One motion `layoutId` for the shell (`zpa-shell`: the pill button and
   the card section) and one for the face (`zpa-face`: the perch and the card's badge). Each has
   `layoutDependency={open}`, so a card that grows with its conversation never re-runs the
   morph. The corners are given inline, since motion only scale-corrects the radius it is
   handed: the card is 26px all round, or 26/26/0/0 on a phone, where it is a sheet, and the
   pill is 30px. Contents fade in once the shell has mostly settled (CSS, 150ms delay), so
   nothing reads while stretched. `.zpa-pill` no longer transitions `transform`. Under reduced
   motion there is no `layoutId` at all and the two swap as before.
4. **Streaming text.** `gemini_utils.generate_with_retry(on_text=)` streams through
   `generate_content_stream` and still returns one whole response: every part of every chunk,
   in order, the last usage for the meter. So the tool loop and the meter cannot tell the
   difference. A retry or a fallback tells the listener "" first. A client with no stream
   method (every fake in the suite) is called the old way. `creative_guide.respond(on_text=)`
   decodes the answer's `message` out of the JSON as it is written (`partial_message`, which
   handles escapes and surrogate pairs cut by a chunk) and clears it at each tool round. The
   route stores it on the job as `partial`, the pill polls every 500ms instead of 1.5s once
   words are arriving, and `Typed` catches up a 24th of the gap each frame
   (`lib/assistant-text.ts typeAhead`), with a red caret. Screen readers hear the landed turn
   once, not the typing. The Studio composer streams the same way (same day, a follow-up): its
   Guide turn reads `partial` off the same job and types it on the left of the stream, where
   the answer will land. `components/studio/typed-text.tsx` is the one typing component; the
   pill and the composer pass their own caret class.

Also fixed on the way: the setup card ("Meet your assistant") was 850px tall inside a card
capped at `100vh - 110px`. On a laptop screen its "Say hi" button fell off the bottom. It
scrolls inside the card now.

**The credit card (same day, a third follow-up).** The pill proposes nothing that spends (a
spark, a reference, a keep, a project; #166 checked). The one thing the Guide can spend credits
on is a still from the composer, which used to run on the send. It is now a step card shaped
on Runway Agent's "Ask before generating media" (Mike: "similar to Runway's in their chat"). It
shows the prompt and the frame, then "Approve" with the model and its price under it ("Nano
Banana · 10 credits"). The composer's Ask first / Auto pill switches between waiting and
drawing at once. A scene still writes at once, since it costs nothing. The pill shows the same
card (`still-step.tsx`, one component for both). Its turns can propose a still, though never a
scene, and Approve draws it into the shared turn. A still waiting on Approve counts as "needs
you", so the face goes amber. See CLAUDE.md, "THE BRAIN IS THE COMPOSER".

## Still not built

1. **Rive**, if the glyphs ever need layered expressions. One state machine per glyph, under
   100KB. CSS is enough for now.
