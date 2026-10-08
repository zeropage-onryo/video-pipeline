# The assistant's face: looks and states (2026-10-07)

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

## The looks

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
- `avatarText(avatar)` returns the emoji or `""` for anywhere a plain string is needed.

## Not built yet (worth doing, in order)

1. **Real progress.** `working` sweeps unless given `progress`. The Guide's job detail could
   carry `step/of` (find references: plan → search → check → sheet) so the arc fills for real.
2. **Unread badge.** When a turn lands while the card is closed, show a count on the face
   until it's opened.
3. **Open/close morph.** Grow the card out of the pill (motion `layoutId`) instead of
   swapping.
4. **Streaming text** in the card. Replies arrive whole today.
5. **The credit card everywhere.** It only shows on the Queue. Any proposal that spends should
   show "N cr · you have M" in the card (see `docs/tasks/task-metering-and-credits.md`).
6. **Rive**, if the glyphs ever need layered expressions. One state machine per glyph, under
   100KB. CSS is enough for now.
