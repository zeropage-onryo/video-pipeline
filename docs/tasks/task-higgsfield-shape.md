# Task: the Higgsfield shape — no idea board, an output-based eval layer, prompts that learn

Written 2026-10-11 from Mike's decisions in chat. **Nothing here is built yet.** This doc is
the plan for him to approve or edit first; the open questions at the bottom need his answer
before the step that depends on them starts.

## Why

The board was built for a pipeline that wrote ideas faster than a person could choose between
them: the night wrote, the morning picked, the pick was the label. The night is deleted
(2026-10-07), the Pipeline tab folded into Projects the same day, and Claude Desktop already
launches the studio MCP surface, which has no board tools. What is left of the board is
leftovers, and they still decide two important things: **a scene cannot be rendered until it
has been picked**, and **the eval layer is built on picks**.

The eval layer is not earning its place. Live numbers, read 2026-10-11:

| Signal | Rows |
|---|---|
| `prompt_scores` (the LLM rubric judge) | 470 |
| `generations` marked kept | 1 of 141 |
| `generated_assets` starred | 0 of 99 |
| concepts passed with a human reason | 1 |
| posted videos linked to a concept | 1 |

The rubric agreed with Mike's verdicts ~38% of the time (`credit_gate.md`, "THE GATES ARE
INVERTED"). It measures whether a prompt is complete; what actually fails is whether the shot
is feasible for the model and whether it looks good, and both only show in the output.

Higgsfield and Runway don't grade prompts. Their good prompts come from tested recipes (presets,
modes), per-model rewriters, reference images carrying the look so the prompt only directs
motion, and outcome data at scale (which outputs people keep). This plan copies that shape.

## Decisions (Mike's, 2026-10-11)

1. **No idea board.** The studio is Higgsfield-shaped: you make something and it lands in its
   project or on the Assets wall. The only decision is spend or don't, made at the moment of
   making, with the price shown.
2. **The eval layer moves from the idea to the output.** The unit is a generation; the signal is
   what the person does with it, collected without asking them to grade anything.
3. **The prompt-rubric judge goes.** Code checks that are facts (empty prompt, a leftover
   `{token}`, too short to render) stay.
4. **Prompts improve by per-model writing and by learning from the person's own keepers**, not by
   a judge.
5. **Nothing is lost.** Old picks, archive reasons, gate scores and hold grades are snapshotted
   before anything that reads them is removed. Scenes and renders are never deleted by this work.

Standing rules this work must keep: the spend is always quoted first and runs only on a yes (the
signed quote token, the ledger hold); nothing renders on its own; the reference gate stays.

## What goes, what stays

**Goes (this doc):** pick as the spend predicate; Pick / Not this one / the verdict keys on
scene lists; the Queue page as a separate stop; the board MCP surface and its tools on the hosted
connector; the Guide's board tools; the `zeropage-board` desktop entry; `pick_rate`,
`shoot_rate`, `reason_counts`, `evaluator_agreement`, `prompt_gate_agreement`; the Dev Studio's
Grade and Teach tabs; the rubric layer of `score_prompts`.

**Goes later (step 9, only on Mike's yes):** the scout and spark bank, `src/research_agent.py`,
the idea-agent skill, `prompts/sparks.txt`, `src/rework.py`.

**Stays:** projects, the workspace, the Director canvas, the composer and its brain, the Assets
wall, the cut editor, the ledger and signed quotes, the reference gate, edit-teach pairs
(`src/edit_teach.py`), the retrieval eval (hit@k / MRR), the cost tracker, `posted_outcomes`, the
uncanny judge (kept by Mike's earlier call), and `archived_at` on scenes as plain "hide".

## Steps

Each step is one PR unless noted. Every PR: `pytest tests/ -q` and ruff clean, `tsc` + eslint +
`node --test` for `web/`, and a click-through on a throwaway schema with every model call
stubbed. **No approve is clicked and no render runs during verification** (Mike's rule).

### Step 0 — snapshot (report first)

`ops/snapshot_board_evals.py`: for every account, writes to `data/backups/board-evals-<date>/`
(untracked; the repo is public) the picked / archived / reason columns of `shoot_concepts`,
`prompt_scores`, graded `hold_queue` rows, pending and ingested `winning_prompts` /
`avoid_prompts`, and the current output of the five rate functions. Report-only by default,
`--write` to save. Nothing is dropped in this whole doc; columns and tables are left in place
and simply stop being written or read.

### Step 1 — spend from the scene, not from the Queue

- `app.api.approve_render` and `approve_keyframes` stop requiring `picked or parked`
  (`not_queued` goes). Every other refusal stays and stays in order: no prompt, no reference
  (`preprod.reference_gate`), `missing_quote` / the six quote refusals, the ledger hold, the cap.
- The approve stamps `picked_at` (the column stays; it now means "was rendered on purpose").
- **A Render button on the scene**, in the workspace's scene list
  (`components/studio/project-workspace.tsx`) and on the solo canvas
  (`components/studio/scene-canvas.tsx`): renderer / length / frame pickers and the price, fed by
  the existing quote route. That's the Queue card's body moved onto the scene, not a second
  implementation. `GET /api/queue/{id}/quote` and `POST /api/queue/{id}/approve` get
  `/api/scenes/{id}/…` names; the old paths stay as aliases for one release.
- The composer's **Send to Queue** becomes **Render…**, opening the same priced card (the
  still step card's pattern, always "ask": a clip is never auto-rendered).
- Draw keyframes moves onto the scene the same way.
- The composer's plan runner (`src/make_plan.py`, `web/src/lib/make-plan.ts`) has a `queue`
  step that picks a scene. It becomes a `render` step: priced on the plan card once the scene
  exists, and it always stops for its own Approve, even under "Approve all" and Auto, because a
  plan never renders a clip unasked.
- **The Queue page becomes "Renders"**: what is running and what finished, off the job feed
  (`lib/jobs.ts`) and the activity tray. No approve lives there any more. The rail badge goes.
  Open question Q1.

### Step 2 — take the board out of the studio UI

- Remove Pick, Not this one, the archive-reason picker and the verdict keys
  (`lib/verdict-keys.ts`, `lib/use-verdict-keys.ts`) from scene lists. "Remove scene" stays, as
  archive with no reason.
- `POST /api/concepts/{id}/pick` is deleted. `POST /api/concepts/{id}/archive` stays (hide /
  unhide); its `reason` is ignored.
- The scene drawer keeps the prompt editor and the references; it loses the verdict row.
- `GET /api/pipeline/concepts` stays as the workspace's scene listing; the `status` filter
  reduces to live / removed.
- `web/src/lib/legacy-routes.ts` redirects stay.

### Step 3 — the board leaves both MCP doors and the Guide

- `mcp_server.LISTED_TOOLS` (the hosted connector) drops `board`, `idea`, `search`, `capture`,
  `pick`, `shoot`, `archive`, `stats`. It keeps `projects`, `project`, `project_chat`,
  `create_project`, `save_chat`, `elements`, `write_scene`, `quote`, `approve`, `job`.
  `write_scene` takes a `project_id` (or none) and creates the scene, rather than writing onto
  an existing idea. `approve` follows step 1's rules.
- **The board surface is deleted.** `SURFACES = ("studio",)`; the operator's static key on the
  HTTP mount gets the studio surface's tools instead of the board's.
  `src/research_agent.py` asked for `--surface board`; it stops working here and is removed in
  step 9 (open question Q3).
- `ops/claude-desktop-mcp.json` loses the `zeropage-board` entry; `ops/connect-claude.md` and
  `ops/register-claude-desktop.command` say so. That also settles the open init-time worry in
  CLAUDE.md: with one entry, Desktop never queues four inits.
- Guide: `guide_tools.READ_TOOLS` drops `board`, `sparks`, `stats`, `tonight`;
  `WRITE_TOOLS` drops `add_spark`. The Guide prompts lose every line that offers them.
- `TITLES` / `DESCRIPTIONS` / `HINTS`, the mount's ordering test, the directory docs
  (`docs/directory/`) and the public plugin repo's skills get the same cut.

### Step 4 — the eval layer, part A: outcome events

One OWNED table, `output_events`: `id, account_id, generation_id, asset_id, event, source, meta,
at`. One writer, `src/outcomes.py record(...)`, which never raises (the `spend.record_call`
shape). The vocabulary is closed:

| Kept | Discarded | Edited |
|---|---|---|
| `cut_add` — a `gen:` handle enters a timeline (`src/cut/projects.py`, `assemble_clips`) | `delete` — the wall's soft delete | `prompt_edit` — `edit_teach`'s pair, linked to the generation it led to |
| `export` — a cut containing it is exported | `regen` — the same scene part, or the same prompt hash, rendered again within 10 minutes with nothing kept in between | |
| `element_from` — a render becomes an element (`photo_urls` on the create routes) | | |
| `ref_reuse` — a `gen:` id is used as a reference or a clip source (the composer's "Use as reference" and effect cards, `/api/effects/run`, the MCP, `edit_clip`, `apply_effect`) | | |
| `continued` — any of the result's continue actions that makes something from it (Variation, Animate, Turn into a shot; `web/src/lib/continue.ts`) | | |
| `download` — `GET /api/assets/generated/{id}/download` | | |
| `star` — the wall's star | | |
| `post` — a `videos` row is linked to it | | |

`generations.kept` becomes derived (any kept event sets it), so `tool_scoreboard` and
`attempts_to_keeper`, which already exist and read `kept`, start meaning something.
A backfill pass (`ops/backfill_output_events.py`, report first) reads what already happened:
timelines' handles, element photos that point at renders, deleted assets.

### Step 5 — the eval layer, part B: new numbers, old tabs out

- **Dev Studio Stats** shows: keep rate by model, by brain tier and by writer template hash;
  attempts before a keeper; **credits per kept output** (ledger settles joined to kept
  generations); discard mix (deleted vs regenerated). Windowed by week, per account, never
  averaged across accounts.
- The five old tiles go. Grade and Teach go: `/grade/*`, `/concepts/{id}/grade`, `/pass`,
  `/concepts/grade-all`, `_dev_grade.html`, `_dev_graded.html`.
- **Teach ingested pending pairs by hand; now it happens automatically.** An edit-teach pair is
  ingested onto the winning / avoid shelves when the generation made from the edited prompt
  gets a kept event. A pair whose output is discarded is withdrawn.
- `posted_outcomes` and the retrieval eval stay as they are.

### Step 6 — the rubric judge goes

- `orchestrator.score_prompts` keeps layer 1 (`_structural_check`) and loses the LLM rubric;
  `PROMPT_GATE_MIN`, the `prompt_gate_min` setting and `ZEROPAGE_GATES` go with it.
  `prompt_scores` stops being written.
- The rubric's checklist (subject, camera, motion, lighting, coherence) moves into the writer
  templates as instructions, where it costs nothing.
- `src.trigger` still runs the graph by hand; it just has no judge in the middle.

### Step 7 — prompts that learn (per-model writing, tested recipes, your own keepers)

This is the "per-model prompt dialects" item `task-studio-agent.md` lists as not built; it
goes beside the skill shelf (`src/skills.py`), not in place of it.

1. **Audit first, then build.** Confirm what a model actually receives: `fal.generate_for_shot`
   sends `target["prompt"]` as written, and `shot.py`'s per-platform renderers
   (`render_kling`, `render_ltx`, …) look unused at the render boundary. Write down the finding
   before changing it.
2. **Per-model prompt at the render boundary.** One function, `prompts_for.render(model, part,
   anchored)`: when a keyframe or reference anchors the clip, a short motion-and-camera prompt
   in that model's dialect; when nothing anchors it, the full scene. Each model's rules live in a
   dated table beside `fal.VIDEO_MODELS` (the `task-runway-prompting-best-practices.md` /
   `task-veo-prompting-best-practices.md` pattern), checked against the vendor's own guide.
3. **Presets become tested recipes.** `prompts/presets.json` rows gain `kept` / `tried` counts
   from step 4; the composer's `/` menu sorts by keep rate and marks untested ones.
4. **Few-shot from the person's own keepers.** The writer's retrieval draws from winning prompts
   **whose output was kept**, same model family first, the caller's account first
   (`prefer_project`, as today).

### Step 8 — offline brain eval, then an output judge

- **A frozen brief set.** ~30 briefs with their references, chosen with Mike from the surviving
  scenes, in `evals/briefs/`. `python -m src.brain_eval --a <template|tier> --b <…>` writes both
  sides and has Claude compare each pair blind, then prints the wins and the pairs worth a human
  look. Model text only: nothing renders.
- **An output judge, advisory.** After ~100 kept/discarded events: a vision check on stills
  against their references (identity, reference adherence, stray text, artifacts). It records
  only. Its agreement with the keep signal is on the Stats tab; it only becomes a gate if that
  number is high and Mike says so. The clip-level hook already exists
  (`orchestrator.JUDGE` / `select_clip`).

### Step 9 — the second pass (only on Mike's yes)

Scout and spark bank (`src/scout.py`, `scout_findings`, `scout_bin` stay readable), the research
agent, the idea-agent skill, `sparks.txt`, `rework`, `promote_winners`' proposal flow. CLAUDE.md's
"Where the project stands" and every section naming the board are rewritten in the same PR.

## Order

PR 1 = steps 0–3 (the board is gone, spending is from the scene). PR 2 = steps 4–6. PR 3 =
step 7. PR 4 = step 8. PR 5 = step 9. PR 1 is the one that changes how the studio feels; the
rest change what it learns.

## Open questions for Mike

- **Q1. The Queue page:** turn it into "Renders" (running and finished jobs), or remove it and
  rely on the activity tray?
- **Q2. Video spend in the composer:** always ask (proposed), or follow the Ask first / Auto
  pill like stills do?
- **Q3. The research agent and scout:** delete in step 9, or keep as a CLI you run by hand?
- **Q4. The hosted connector's `stats` tool:** drop it (proposed), or bring it back once step 5's
  keep numbers exist?
- **Q5. The brief set in step 8:** pick the ~30 together, or let Claude propose and you strike?
</content>
</invoke>
