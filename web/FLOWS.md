# React Director

Run the existing FastAPI server on port 8000, then `npm run dev` here on
port 3000. In the signed-in product, choose Pipeline → Open in Director.
Local FastAPI pages hand the scene to `/studio/flows?concept=ID&shot=N`.
The canvas returns to Pipeline, Queue, or Assets through `/ui?view=…`.
Queue opens the existing approval screen; navigating there does not render.

## Scene persistence

The canvas loads the owned concept and its existing per-shot graph. It reads
and writes the backend's LiteGraph format, with additional React metadata for
multiple reference wires and pending jobs. Existing prompts, node positions,
references, and cached outputs survive. Unsupported legacy nodes produce an
explicit fallback link instead of being dropped.

Edits autosave to `/api/concepts/{id}/shots/{n}/graph`. Save canvas retries
explicitly; navigation flushes pending edits. A changed scene seed rejects
stale graph saves. Save scene prompt explicitly writes the selected prompt or
enhancement back to the shot; ordinary canvas editing does not replace it.
The fallback is `/ui?view=director&concept=ID&legacy=1`.

Without a concept parameter the workspace is a browser-local draft, with
JSON import/export and templates. Templates cannot replace a connected scene.

## Generation and authentication

The Next.js server proxies API, auth, and reference/media routes to
`API_UPSTREAM` (default `http://localhost:8000`). Sign-in and account permissions
remain in FastAPI. `NEXT_PUBLIC_API_URL` optionally selects a direct API origin,
which needs matching CORS and cookie configuration.

Ground/enhance nodes use the existing execution endpoints. Image/video nodes
use Nano Banana and Runway through the existing authenticated endpoints and
explicit generation dialog. Concept and shot IDs accompany generation: the
server verifies ownership and references, enforces existing provider caps, and
attaches successful media to the shot even if the browser closes. Pending job
IDs and finished outputs persist with the canvas. Run upstream nodes before
downstream nodes; a whole-graph runner is not implemented in this workspace.

For a hosted setup, run the Next.js service alongside FastAPI and set the
backend's `DIRECTOR_FRONTEND_URL` to the full public `/studio/flows` URL. Nonlocal FastAPI defaults to the legacy
Director until this setting is configured. The combined Fly configuration below
sets it for the existing public domain.

## Verification

Graph round-trip tests cover prompts, references, layouts, outputs, pending
jobs, unsupported nodes, legacy image fallback, and legacy edits. Backend
checks cover graph persistence, stale saves, ownership, and mocked output
attachment. TypeScript, ESLint, Ruff, and production Next.js build pass.
No paid rendering was used. Browser automation timed out during integration
verification; an authenticated live browser walkthrough remains unverified.

The three small template thumbnails were cropped from the supplied recording
as reference assets for this local implementation.

## Combined Fly deployment

The root Dockerfile builds this app in standalone mode. Supervisor runs Next.js
on loopback port 3000, FastAPI on 8000, cron, and nginx on public port 8080.
Nginx sends `/studio/flows`, `/_next/`, and `/flows/` to Next.js; other routes
remain with FastAPI, preserving the landing page, auth, API, and media routes.
Forwarded host/protocol headers preserve the public OAuth callback origin.
The Fly machine has 1 GB RAM. Deploy from the repository root with
`fly deploy -a zeropage-studio --remote-only`.
