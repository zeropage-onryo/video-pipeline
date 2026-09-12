# The Director (React Flow) — the Gen Space

Run the FastAPI studio (`venv/bin/uvicorn app.main:app`), then `npm run dev`
here. `API_UPSTREAM` (default `http://localhost:8000`) is where the same-origin
proxy sends `/api`, `/ui`, `/brand`, `/auth` and the photo routes, so the
`zp_session` cookie rides along and sign-in stays FastAPI's.

Every signed-in page sits inside one shell (`src/components/studio/shell.tsx`):
the rail (Studio, Assets, Pipeline, Director, Elements, Queue — Analytics is
gone in favour of Elements, 2026-09-11), the bar, the account row, a Queue
badge (`GET /api/queue/pending` count). Every entry is a React page:
`/studio` (composer), `/studio/assets` (the media wall + detail rail),
`/studio/pipeline` (the board), `/studio/flows` (this canvas),
`/studio/elements`, `/studio/queue` (the spend gate + jobs).

## The canvas (`/studio/flows?concept=ID&shot=N`)

One shot's chain as cards: the prompt, its instructions, one **element card
per asset** the scene was written against (`zpf/reference_set` — a
character's frames, a room's plates, the composer's uploads), the Gemini
enhance, the Nano keyframe and the Runway clip. Wires are real links the
runner executes; `src/lib/director-graph.ts` is the adapter and the JSON on
the wire is still LiteGraph's serialize() shape. The billed cards carry a
`refs` port that takes SEVERAL wires (`workflow_runner.MULTI_LINK_PORTS`), and
`ref_urls` is rewritten from the wires on every save so the drawing and the
run never disagree.

- **The prompt bar** underneath edits the shot's prompt card. An `@`-mention
  (`/api/assets/search`) drops the element on the canvas already wired into
  every card with a refs port; the same works inside a prompt card.
- **Generate** saves the canvas to the shot's row and runs the backend's Run
  all (`POST /api/workflows/{id}/run`), painting each card from the job's
  `node_states`. A card's own Run (with the confirm) is the per-node route.
- **Send to Queue** only PICKS the concept (`POST /api/concepts/{id}/pick`);
  approving in Queue is still the one spend gate.
- **The inspector** (select a card): what it does, a rename, the camera
  presets (`/api/presets`, folded into the prompt — the runner has no camera
  parameter), the spend line and the gate state for the Runway card.
- Tools: select, pan, cut (click a wire), frame all; the + adds a card.

Edits autosave to `/api/concepts/{id}/shots/{n}/graph`; a changed scene seed
rebuilds the canvas (the server compares on read). `Save scene prompt`
writes the prompt card back onto the shot. A saved canvas wins over a
rebuild — `DELETE /api/concepts/{id}/graph` is the reset.

Without a concept the workspace is a browser-local draft with templates and
JSON import/export.

## Elements (`/studio/elements`)

The thing you @ in a prompt: one card per asset row with its plate, @handle,
frame count and how many concepts it has grounded (derived from the refs on
the board). New element posts to `/api/assets/{characters|locations|props}`,
which also teaches the RAG assets shelf.

## Tests

`node --test tests/` covers the adapter (seeding, grouping, the multi-wire
port, the round trip). `npx tsc --noEmit` and `npx eslint src` are the gates.
