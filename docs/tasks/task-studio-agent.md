# Task: the chat box becomes a studio agent

Mike, 2026-10-10: "Evaluate the current ai production studio, specifically the chat box
portion. I want it to have the same capabilities as an expert llm and match that of higgsfield
or runway" -- crawl and create reference photos, element sheets, effects, winning prompts for
one scene and several, and a better chat and main page. Rules he set: no changes without his
approval, build on what exists, research the competitors first.

After the research (Runway Agent, Higgsfield Supercomputer, invideo Agent Two, and the rest of
the field) he chose the order: **"take some out of the runway and higgsfield playbook first"**,
then **"go"** on the batch below.

## Ground rules for the session doing this

- One PR per numbered item; **stop after each item and report** before starting the next.
- Read `CLAUDE.md` first. Build on existing code; nothing here is a rewrite.
- Mike's design-first rule (the creature work): a change to how the studio LOOKS goes on a
  design canvas for his pick before code. Item 1 added one chip and one menu group in existing
  styles. Item 2 he told to go ahead on 2026-10-10 ("merge it and go ahead with item 2"): build
  it out of the step card he already picked (`still-step.tsx`), and show him the result at the
  stop. A look that is NEW -- the effects gallery in item 3 -- goes on the canvas first.
- No live spend while building: stub the model in the server process (the recipe is in the
  memory note `worktree-browser-verification`). A live check is Mike's call.
- `venv/bin/python -m pytest tests/ -q`, `venv/bin/ruff check .`, and in `web/`:
  `npx tsc --noEmit`, `npx eslint src`, `node --test tests/<file>.test.mjs`.

## What the research found (short)

- The chat is a careful one-step assistant: up to six read calls, then the turn ENDS on the
  first write (`creative_guide._respond_with_tools`). Runway and Higgsfield plan several steps,
  price each, and run them on approval.
- Most of the missing abilities already exist in the repo, wired to the Claude Desktop connector
  and not to the in-app chat: `src/effects.py`, `prompt_craft`, prop and place sheets, and the
  studio MCP v2 tools (cancel, edit a clip, reframe, join clips).
- The competitors' "expertise" is a shelf of named recipes the agent reads on demand, not a
  bigger model.
- Zero Page is ahead on: Ask-first as the default, screened and attributed web references,
  per-project memory, free thinking.

## Progress

| item | state | PR / notes |
|---|---|---|
| 1. Skills | built 2026-10-10 | see "As built" below |
| 2. Plan with step cards | built 2026-10-10 | see "As built" below |
| 3. Effects in chat | built 2026-10-10 | see "As built" below |
| 4. "Continue" actions on results | not started | depends on 3 for upscale and edit |
| 5. Draft, then finish | not started | fal's draft price has to be checked first |

## The batch

1. **Skills.** Named recipes the brain loads when needed, also listed under `/`. Runway's slash
   skills, Higgsfield's skill files.
2. **Plan with step cards.** One message gets a numbered plan; each step shows model, prompt and
   credits and can be approved, edited or skipped; editing a step re-runs only that step, and
   stopping charges only finished steps. Runway's "Ask before generating", Higgsfield's plan and
   Approve. On the way it fixes two things seen on the live page on 2026-10-10: a failed draw
   that read "Done · Approved", and a raw provider error ("User is locked. Reason: Exhausted
   balance...") shown on a tile.
3. **Effects in chat.** `/effects` opens a gallery that never runs anything by browsing; a pick
   puts a priced card in the thread. Built on `src/effects.py`.
4. **"Continue" actions on every result.** Upscale, Edit, Variations, Make element, Turn into a
   shot, Download, and the price on the send button.
5. **Draft, then finish.** A cheap low-resolution clip first; full price only for the keeper.

## Decisions

Made:
- Runway and Higgsfield patterns first; invideo's after (Mike, 2026-10-10).
- No session list: a conversation is working memory and projects hold the history (Mike's
  2026-10-02 call; proposed by mistake in the first plan and withdrawn).
- Thinking stays free (Mike's 2026-10-08 call); invideo bills it and is disliked for it.

Open, for Mike:
- **Rendering a clip from the chat.** Should a plan's last step buy the clip, through the same
  approve body and signed quote the Queue and the claude.ai connector use? Until he says, a plan
  ends at "Send to Queue".
- **Auto mode.** invideo's three states (always allow / ask before video / always ask) with a
  credit cap per project, Ask-first staying the default -- recommended, not decided.
- **Invented characters.** `prompts/stages/cast.md` says a face is always an Element from real
  photos, never a generated stranger. Casting an invented person (invideo, Higgsfield) reverses
  that; not built.
- **Sheet layouts and styles.** The character sheet is the landing page's five-panel prompt
  "exactly as is" (Mike, 2026-10-09). Other layouts (expressions, outfits) would be options
  beside it, never a change to it; not built.

Later (invideo's list, and the small fixes): a role on every attached reference, research by
name saved to the project's look, product facts from a pasted link, a casting skill, a model
proposed per step, an explore / execute switch per project, a short number on every result
tile, a top-up link when a balance runs out mid-job, markdown in answers, Stop while thinking,
directions and questions drawn in the composer, stills made inside a project filed under it.

## Item 1 -- Skills: as built (2026-10-10)

`src/skills.py`, `prompts/skills/*.md`, `prompts/creative_guide_skills.txt`; the `CLAUDE.md`
entry "THE BRAIN HAS A SKILL SHELF" is the description of record.

- **Five skills,** in the studio's own words: `character-sheet`, `single-shot`, `multi-shot`,
  `product-still`, `mood-board`. Each uses only tools the brain already has; nothing new spends.
- **The brain loads one** with `load_skill`, a read tool published beside `find_references`;
  the shelf's index is in the instructions only when that tool is offered.
- **The person picks one** from `/` in the composer: a chip on the box, the Image | Video switch
  follows the skill, and that one send carries `skill=<name>` with the recipe already loaded.
- **The thread says which skill an answer used** ("used the Mood board skill"), whichever way it
  was loaded, and the person's own bubble carries the pick.
- What every composer and dock turn now carries: the shelf's index in the instructions (about
  1,400 characters) and one more tool. A turn that is offered no tools is what it was, and so is
  every turn when the shelf is empty.

Checked: `tests/test_skills.py` (shelf, tool, turn, routes) and `web/tests/skills.test.mjs`;
then in a browser against the real routes with the model stubbed in the server process -- the
menu, the chip, a picked send, a load the brain made on its own, the saved thread after a
reload, and 375px. No real model call was made, so **how well the live brain follows each
recipe has not been measured**; that is the first thing to watch on real turns.

Deliberately left out of item 1:
- Per-model prompt dialects (Kling / Veo / Seedance / LTX each read a prompt differently). The
  scene writer is not told which model will render, and the composer has no video model picker;
  this belongs with item 2, where each step names its model.
- A write tool for a project's LOOK. The mood-board skill writes the look into the brief and
  points at the LOOK box in the project's workspace.
- The dock's conversation does not offer the `/` menu; the brain can still load a skill there.

## Item 2 -- Plan with step cards: as built (2026-10-10)

`src/make_plan.py`, `prompts/creative_guide_plan.txt`, `web/src/lib/make-plan.ts`,
`web/src/components/studio/make-plan-card.tsx`, the `runPlan` block in
`web/src/app/studio/page.tsx`; the `CLAUDE.md` entry "THE BRAIN PROPOSES A PLAN" is the
description of record.

- **One answer, several makes.** `make_plan` takes two to eight steps: a still, a scene, a
  character sheet, keeping hunted references, a scene's keyframes, sending a scene to the
  Queue. Several scene steps in one plan is how a multi-scene piece is written from one message.
- **A checklist in the thread.** Each step says what it is, what it will do, why, and what it
  costs. Start runs it; a step that costs credits stops for its own Approve beside its price;
  "Approve all" covers the steps whose price is on the card. Keyframes are priced once their
  scene exists, so they always ask (with Ask first on).
- **Edit, skip, bring back.** Before a step runs, or after: editing a step that ran re-runs that
  step only. Skipping a scene takes its keyframes and Queue steps with it.
- **Stop and failure.** Stop ends the wait on the running make; a failed step stops the plan
  where it is, says why in plain words, and offers Try again.
- **Results are ordinary turns** under the card: the still's own step card and tile, the scene's
  shot tiles with every action they always had. A still a later step is "held to" rides along
  as a reference.
- **It never renders a clip.** A plan's last word on a scene is the Queue.
- **Fixed on the way** (both seen live on 2026-10-10): a still that failed at the provider no
  longer reads Done, and the provider's raw error no longer reaches the page (`src/failures.py`,
  `web/src/lib/made-state.ts`).

Checked: `tests/test_make_plan.py`, `tests/test_failures.py`, a new case in
`tests/test_pipeline_tabs.py`, `web/tests/make-plan.test.mjs`, `web/tests/made-state.test.mjs`;
then in a browser against the real routes, jobs, concept rows and keyframe approve with every
model stubbed in the server process: Ask first (Start, per-step Approve, Approve all), a draw
that failed with the live 403 text and its Try again, Edit and Skip, a reload mid-plan, 375px,
and Auto with Stop and Resume. **No real model call was made**: whether the live brain proposes
plans when it should, and writes steps that stand on their own, is the first thing to watch.

Known limits:
- The loop runs in the page. A plan left mid-step is picked up on return (each step follows the
  turn its result went into) but does not carry on by itself; the card offers Resume.
- With Auto on, a plan spends through every step without a click, as a single make does. The
  open decision on a per-project credit cap (above) matters more now.
- `uses` holds a step to an earlier STILL only. A sheet step's character reaches a later scene by
  being named in it, the way any Element does.
- Plain failure wording is applied to the still route. Keyframes, sheets and Queue renders still
  show their adapters' own text.
- The dock shows a plan's summary line and nothing else; a plan is run from the composer.

## Item 3 -- Effects in chat: as built (2026-10-10)

`app/api.py` (`/api/effects`, `/effects/quote`, `/effects/run`), `guide_tools.EFFECT_SPECS`,
`prompts/creative_guide_effects.txt`, `web/src/lib/effects.ts`,
`web/src/components/studio/effect-gallery.tsx` and `effect-step.tsx`; the `CLAUDE.md` entry
"EFFECTS IN THE CHAT" is the description of record.

- **Thirteen effects, four tabs,** all from `src/effects.py`, the table the Claude Desktop
  connector already used: edit an image by instruction (three models) or cut out its
  background; animate a still with a Kling or PixVerse template (98 and 154 looks) or a named
  camera move (20); and finish a clip -- upscale or smooth it, add sound, give it a new shape,
  remove its background.
- **`/effects` opens a gallery above the box.** Browsing runs nothing. Each row says what it
  takes, what it gives and what it costs from; a row with nothing to act on yet is greyed
  with the reason.
- **A pick puts a card in the thread.** It shows what it will act on (what is attached to the
  box, else the newest result that fits), its choices, its words, and Approve beside the
  price. The price is asked from the server whenever a choice changes, and Approve sends that
  number back: the effect runs at the price shown or is refused.
- **The brain can propose one** from a plain sentence ("remove the background", "give it a
  slow camera move"). It looks the exact template and camera names up first, and its options
  and words land on the same card, still editable. It never picks what the effect acts on.
- **Results chain.** A still, and what an effect made, each carry their render id, so the
  next effect can act on them: still -> template clip -> sound on that clip was walked.
- **Effects always ask.** The Auto pill does not cover them.
- **Failure** reads as one plain sentence with "Nothing was charged", and the card offers
  Approve again.
- Found and fixed on the way: a clip an effect made read "Not made" (the rule that a still
  with no image is a failure did not know about clips); the effect job's result wrote over
  the job's own `kind`; a finished card said "Pricing..." after a reload.

Checked: `tests/test_effects_studio.py`, a new case in `tests/test_pipeline_tabs.py`,
`web/tests/effects.test.mjs` and new cases in `made-state`, `job-feed` and `skills`; then in a
browser against the real routes, checks, quote, job registry and Assets rows with the
provider and the model stubbed in the server process: the gallery and its tabs, a Kling
template on a still, sound on the clip that made (priced from the clip's measured length), a
failed run and its Approve again, the brain's two paths, a reload, and 375px. **No real model
or provider call was made.** Unmeasured: whether the live brain reaches for an effect only
when asked, and every effect's real output.

The look: the design-first rule says a new look goes on a canvas before code. The gallery was
built out of parts Mike already picked -- the slash menu's panel and the still step card --
and is shown to him at this stop. If he wants a different look, it changes before merge.

Known limits:
- No preview per template: 252 template names are words in a list with a search box.
  Higgsfield and Runway show a thumbnail or a loop for each; that needs media made per template.
- An effect is not a plan step, and the dock does not offer effects.
- **What an effect can act on is what this conversation holds:** images attached to the box,
  and results in the thread. A clip rendered from the Queue is on the Assets wall but the
  composer cannot pick it yet, so "Finish a clip" works today only on a clip an effect made
  here. Item 4's actions on the Assets wall are where that closes.
- Each row is called by the effects table's own label, which names the model
  ("Add sound (MMAudio)").
- Lip sync, relight and frame interpolation by RIFE / FILM are still out of the table, for the
  reason `src/effects.py` gives: a price or an input could not be verified.
