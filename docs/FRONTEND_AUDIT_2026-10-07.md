# Studio front end vs LTX Studio and invideo: what we're missing (2026-10-07)

Mike asked me to "scour the studio and take a look at how we can improve the front end compared
to ltx or invideo. What are we missing specifically and where could we improve."

**How I checked:**
- **Our side:** read off `main` at `0072b0d` (every page under `web/src/app/studio`, the shell,
  the pill, the cut editor).
- **Their side:** their public pages, launch posts, help centres and reviews, as of October 2026.
- **Not done:** no live sign-in to either competitor.

## Where we already stand

We're not behind everywhere. We have things neither competitor has:

- **A floating, nameable assistant.** It has visible states, judged directions, reference
  contact sheets and a credit card on the Queue. LTX has no agent. invideo's agent is a docked
  panel with no visible working or approval states. Higgsfield's agent is a separate full-page
  chat.
- **Price before spend.** Every render and still is priced and held before it's submitted, and
  every approve needs a signed quote. Only Higgsfield comes close (it shows the cost before
  running).
- **A real editor.** `/studio/cut` has a source viewer, keyframes, speed/reverse, 58
  transitions, a mixer, Color/Audio pages, OTIO export and an agent that proposes edits for
  Keep/Undo. That's at invideo Editor's level on the core, which most generation tools
  (LTX, Higgsfield) don't attempt.
- **Elements with reference sheets.** This is LTX-level consistency (`@`-mentions, a sheet
  drawn from real photos).

The gaps are mostly the **connective tissue**: getting around, knowing what's happening, seeing
a project as a whole, and sharing it.

## What we're missing, specifically

### A. Getting around

1. **⌘K does nothing.** The rail shows a `⌘K` hint (`shell.tsx:348-350`), but there is no
   handler anywhere. Build a command palette that covers:
   - jump to any project, scene, element or asset;
   - run "New project", "Find references", "Draw keyframes" and "Open Queue";
   - search prompts.

   invideo ships Premiere/DaVinci shortcut sets. We have those only inside the cut editor.
2. **No global search.** Search exists only per page (projects, assets, composer elements, the
   cut Search tab). The Queue and Elements pages have none. The palette should be the global
   search.
3. **No keyboard verdicts.** BACKLOG #15 is still parked. Add `A` approve, `X` reject and `→`
   next on the Queue, and the same on a project's scene list.

### B. Knowing what's happening

4. **Jobs are polled, never streamed.** The `/api/jobs/stream` SSE feed exists, and no page
   uses it (grep finds no `EventSource`). Polling runs at the Queue's 2.5s, the sheet's 2s, the
   badge's 60s, plus `waitForJob`.
5. **No activity tray or notification centre.** A render finishing on another page shows only
   as a badge count. Add a tray (bell in the header) listing running and finished jobs with
   credits spent and a link to each result. Higgsfield shows a running credit cost during agent
   work. invideo's agent answers "what's the update?" with one combined status.
6. **One toast slot.** The toast overwrites itself (`shell.tsx:269, 472`). Stack them, and give
   the destructive ones **Undo**: archive, reject, remove from the wall and delete element are
   all soft server-side, but the UI offers no way back.
7. **No browser notification when a long job lands.** Raycast and invideo both notify. Do it
   behind the tray, with explicit permission.

### C. Seeing a project as a whole (LTX's strongest area)

8. **No storyboard view.** LTX splits a script into scenes and shots and lays them out as a
   board you can edit at project, scene or frame level, then exports it as PDF or MP4. We have
   the data (`shot.timeline.parts`, per-part stills, seconds, refs) but only show it per scene
   on a Queue card or in the composer. Add a **Storyboard** tab in the project workspace:
   - every scene's shots in order as a grid (still, seconds, camera, refs);
   - re-roll one shot;
   - reorder scenes;
   - export the board as PDF.
9. **No camera picker.** LTX has motion presets plus keyframed crane, orbit and tracking.
   Higgsfield has a camera → lens → focal length → aperture rig. Ours are slash commands that
   fold "Camera: …" into the idea text (`composer_redesign` doc). Add a visual move picker on a
   shot: thumbnails of each preset, looping. Keep it as prompt text underneath, since the
   renderer has no camera parameter.
10. **No per-shot retake surface.** The Queue renders part by part and resumes, but there's no
    "redo shot 3 only" button outside the canvas. LTX's Retake regenerates a 2–16s segment and
    keeps the rest.
11. **No version history for scenes.** LTX lets you roll back any scene. We keep versions only
    in the cut editor. A scene's prompt edits (Direct, Polish, hand edit) overwrite in place.
    Add a small history drawer on the scene: prompt-before/prompt-after pairs, which the
    edit-teaches feature already records.
12. **No pitch deck export.** LTX generates a deck from the storyboard. Ours could be the
    storyboard plus brief plus look, exported as Slides or PDF. This matters for the
    agency buyer in `positioning.md`.

### D. Sharing and review (invideo's strongest area)

13. **No review links.** invideo Editor has share links with frame-accurate comments that the
    agent can act on. We have nothing to send a client.
    - A read-only `/r/<token>` page per cut export or storyboard would cover it.
    - Comments would be pinned to a frame, and the cut agent would read them as proposals.
14. **No collaboration presence.** This is lower priority until there are teams.

### E. Guidance

15. **No playbooks.** invideo has 9 workflows plus custom ones, each with a ≤3-question intake.
    Our pill has the seven steps but no named formats ("UGC ad", "product hero", "15s teaser").
    Add a playbook picker on an empty composer that seeds the pill's first three chip
    questions.
16. **No first-run tour.** Onboarding is the pill's "Meet your assistant" and the Elements
    how-to. A new open sign-up lands on an empty Projects board. Add one guided pass: name your
    assistant → make an element → write a scene → see the price.

## Where to improve what we have

17. **Three design systems in one app.**
    - The `.zps` CSS variables (shell, assets, elements, queue) live alongside the Tailwind
      noir/bone tokens with Bebas and Plex (projects, workspace, cards) and plain Tailwind
      constants (settings).
    - There are two reds (`--signal #e4002b`, `noir-red #e23b2e`) plus `#d10024` in the pill,
      and about 140 hard-coded hex values across studio.css, assistant.css and composer.css.
    - Fix: one token file (studio.css), map the Tailwind theme onto it, and replace the hex
      values.

    This is the single biggest "feels less polished than LTX" cause.
18. **Stale copy from before the Projects merge.** These all still point people at pages that
    no longer exist:
    - "Scene written · it is on Pipeline to pick" (`studio/page.tsx:549`, 550 on this branch)
    - "pick a concept on Pipeline" (`queue/page.tsx:585`)
    - "picked on Pipeline or sent from the Director" (`queue/page.tsx:1018`)
    - "on the Director canvas" (`elements/page.tsx:168-169`)
    - "pick a scene to draw its keyframe" (`assets/page.tsx:218`). Since 2026-09-29, Draw
      keyframes is on the Queue.

    This is a 30-minute fix.
19. **Confirm dialogs disagree.**
    - `window.confirm` in `cut/page.tsx:63`
    - an inline two-step on elements
    - a proper dialog for project delete

    Use one dialog component.
20. **Missing empty states.** The Cut projects page has none, and its error is a toast only.
21. **Settings has no Billing.** The credit pill is the only balance UI, and "Buy credits" goes
    to the public `/pricing`. Add a Billing section with plan, lots, expiry, top-up and portal.
    The data is already in `GET /api/billing/balance`.
22. **Dollars still show in places.** These are the Director Generate node, the Queue fallbacks
    and the vanilla Queue. See `docs/tasks/task-metering-and-credits.md` part 2.
23. **The pill.**
    - Built tonight (`docs/ASSISTANT_AVATARS.md`): the animated face with 8 states and 8
      glyphs.
    - Still missing: streaming replies, an unread badge, the open/close morph, persisting
      open/closed across reloads, and the credit card on any spending proposal (not only the
      Queue).
24. **Motion is uneven.** The composer, assets and elements use `motion`. The shell, queue,
    projects and workspace snap. Add one shared enter/exit for cards and drawers.
25. **The cut editor on a phone.** It has no layout below tablet. invideo's editor runs in
    mobile browsers. At minimum, show a read-only player with Export on a phone.

## Suggested order

**This week (small, high-visibility):**
- 18 stale copy
- 17 token unification (start with the reds and the pill)
- 6 stacked toasts with Undo
- 22 credits everywhere
- 20 empty states

**Next:**
- 1 + 2 command palette and global search
- 4 + 5 SSE plus activity tray
- 21 Billing in Settings
- 3 keyboard verdicts

**Then (the LTX/invideo parity pieces that sell):**
- 8 Storyboard tab (with 10 per-shot retake inside it)
- 13 review links
- 12 deck export
- 15 playbooks
- 9 camera picker
- 11 scene history

**Later:**
- 16 tour
- 25 cut on mobile
- 14 presence

## Sources

Our side is file:line throughout. Their side, from public pages:

- ltx.io/blog/top-ltx-studio-features
- invideo.io/agent-two
- invideo.io/news/introducing-invideo-editor
- help.invideo.io/en/articles/16819946
- invideo.io/news/introducing-slate-invideo-agent-two
- higgsfield.ai/blog/how-we-built-supercomputer
- higgsfield.ai/blog/how-we-built-cinema-studio
- runway.com/news/engineering/inside-building-runway-agent
