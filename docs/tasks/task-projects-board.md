# Task: one Projects board (Pipeline + Director folded into Projects)

Written 2026-10-07 from Mike's decisions. Built the same day on
`claude/projects-board-consolidation-da4be9`. CLAUDE.md's "ONE PROJECTS BOARD" bullet is the
short version; this is the record of what was asked, what was built, and what is still open.

## Decisions (Mike's, not to be re-litigated)

1. The Projects board is the home. Pipeline leaves the rail.
2. A card opens the project's workspace: the Director canvas and the assistant pill. The pill IS
   the Guide; there is no second chat panel.
3. A project is not required. Single videos stay creatable.
4. The nightly run stays off. Nothing may re-enable it.
5. Old concepts are wiped (separate PR, report-first; keep #375 and anything rendered).
6. Per-project brief, look and memory stay as designed. The studio imposes no look.
7. Archiving never deletes, except the one-off wipe.
8. Projects are made only through the Guide: "make a project" or "save this as a project".
   No create form or button on the board.
9. A project keeps its chat history until it is deleted. Delete is a real action; archive hides.
10. A video made without a project finishes on the Assets wall. No board card, no hidden
    "Quick" project.

## As built

**Step 0.** Nothing to merge: `src/projects.py`, `app/creative_projects.py`,
`src/creative_projects.py` and `web/src/app/studio/projects/page.tsx` were already on main
(`34263c7`). `origin/claude/project-look-config-62c331` differs from main only in an older
`src/looks.py` and studio-api helpers main has since removed; it holds nothing to take.

**Step 1, the board** (`web/src/app/studio/projects/page.tsx`). Cards with a cover (newest
scene's still, else its first reference; `projects.list_projects` reads it in one query and
`GET /api/projects` mints it through `media.url_for` plus a 480px tile), title, the brief's first
line, scenes / picked / rendered and when it was touched. Active / Archived, search, Archive and
Delete per card. The empty board explains how a project starts through the assistant.

**Step 2, the workspace** (`/studio/projects/<id>?scene=&shot=`,
`components/studio/project-workspace.tsx`). Left: the project's scenes with Pick, Not this one and
the drawer (`components/studio/scene-drawer.tsx`, moved out of the old Pipeline page). Centre: the
same `FlowWorkspace`, with a `CanvasNav` prop for its links and `registerLeave` so switching
scenes saves first. Right: name, brief, look, memory, Write a scene here, Archive, Delete. On a
phone, one pane at a time. The canvas's narrow-screen rules now also key on its own width
(`@container` in `flows.css`), since it is narrow on a wide screen inside the workspace.

**Step 3, solo videos.** A Create with no project writes `project_id NULL`. Its canvas opens at
`/studio/scene/<id>` (`components/studio/scene-canvas.tsx`), which forwards into the workspace when
the scene IS filed under a project. The composer's "Pick on Pipeline" became **Send to Queue** (the
pick only). Once rendered it reaches the Assets wall through the existing `generated_assets`
writers; `/api/media` rows now carry `project_id` / `project_title` and the detail rail says "no
project". The spend gate is untouched.

**Step 4, old doors.** Pipeline and Director left the rail. `/studio/pipeline` and `/studio/flows`
redirect (`web/src/lib/legacy-routes.ts`, tested in `web/tests/legacy-routes.test.mjs`); a
`?concept=` lands on that scene, `?draft` on `/studio/scene/draft`. Every page builds scene links
through `sceneHref` / `workspaceHref`. `auth.STUDIO_VIEWS["pipeline"]` is the board. The vanilla
`/ui` still hands scenes to `/studio/flows` through `DIRECTOR_FRONTEND_URL`, i.e. the redirect.

**Step 5, the pill is the Guide.** `project_messages` (OWNED, in `db.OWNED_TABLES`) holds a
project's turns; `/creative-guide` writes them when a turn carries `project_id` and `remember=1`;
`GET /api/projects/{id}/messages` reads them, paged. On a workspace the shared thread
(`assistant-thread.tsx`) IS that history and the pill hides its clear button. `create_project` and
`save_as_project` are Guide write tools: proposed by the model, confirmed on a card in the pill or
the composer, run by `/creative-guide/act`. `save_as_project` copies the thread and files the
scenes its sends made, then clears the studio-wide thread and opens the new workspace. A turn
inside a project is told so and asked not to propose either. `DELETE /api/projects/{id}` deletes
the project, brief, look, memory and history in one transaction and detaches its scenes.

**Step 6, nightly off.** The Fly image's only cron line is still the Instagram token keeper
(Dockerfile), and supervisord runs only the web app and cron. Copy that promised a nightly run was
corrected: the MCP server's instructions and its `add_spark` / `tonight` tools, the Guide's
`add_spark` card label and tools prompt, the supervisord comment, and CLAUDE.md's "The night does
the rest" paragraph.

## Verified

- Python: 3,096 passed, 8 xfailed; ruff clean. New tests in `tests/test_projects.py` cover the
  history (order, paging, tenancy), delete (history gone, scenes detached, render kept), covers,
  the two Guide tools through the act route, a remembered Guide turn, and a solo render on the
  wall with no project.
- Web: `tsc` and `eslint` clean (two pre-existing warnings); every `node --test` file passes.
  CI does not run the web tests or the typecheck.
- Clicked through on a throwaway schema with every model call stubbed and no spend keys: board,
  workspace, scene switch keeping an unsaved edit, the pill's history across a reload, Pick and
  Send to Queue reaching the Queue, save-as-project from the pill, Delete with the scene list, a
  solo Create, the redirects, a second account seeing nothing, the empty board and phone widths.
  No approve was clicked and no render was run.

## Open for Mike

- **Delete's default**: chat, brief, look and memory are deleted; scenes are detached, never
  deleted. Confirm or change.
- **The wipe** (`ops/wipe_concepts.py`, its own PR) is report-first and has not been run.
- **Visiting a workspace sets the active project** (`rememberActiveProject`, as the old "Open in
  Studio" did), so the next Create on the composer is filed into that project until its chip's ×
  is pressed. That is the existing behaviour, kept; say if a solo Create should be the default.
- **The vanilla `/ui?legacy=1` Director** is untouched and still reachable. Delete it or keep it
  as the reference.
- A Guide proposal restored from a project's history is drawn as text only, not as a card: the
  history does not record whether it was confirmed, and a second card could bank it twice.
