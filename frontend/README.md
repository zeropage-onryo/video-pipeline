# ZPF Studio — frontend

The React app for `/ui`. Built and run **on its own**, wired to the FastAPI
backend afterwards.

It is wired (2026-09-10): `src/lib/api.ts` talks to the real routes by
default. `VITE_USE_FIXTURES=true` switches it back to
`src/lib/fixtures.ts` so a screen can be built with no Python server
running — the unusual case now, not the normal one.

```bash
npm install
npm run dev      # http://localhost:5173, fixtures on
npm run build    # tsc -b && vite build
npm run lint     # oxlint
```

## Wiring it to the backend

Two things, in this order.

1. **Run the studio on :8000.** `venv/bin/uvicorn app.main:app --reload`.
   `vite.config.ts` proxies `/api`, `/refs`, `/renders` and the asset photo
   routes there. It is a proxy rather than CORS because Google sign-in for
   this app only works on localhost (see `START_SERVER.md`) — the browser
   stays on one origin and the `zp_session` cookie keeps working.

## The routes it uses

Every one is live. `src/lib/api.ts` documents each against what
`app/api.py` returns today.

| Route | What it feeds |
| --- | --- |
| `GET /api/capabilities` | which controls may be drawn at all |
| `GET /api/me` | the account block: person, active brand, memberships |
| `GET /api/brains` | the model pill (`gemini_utils.BRAINS`) |
| `GET /api/scene-lengths` | the duration pill (`timeline.SCENE_SECONDS_CHOICES`) |
| `GET /api/render-choices` | the frame pill (`render_specs.RUNWAY_RATIOS`) |
| `POST /api/scenes/run` | Create — returns a job |
| `POST /api/creative-guide` | Guide — one turn, returns a job |
| `GET /api/jobs/{id}` | both, polled until terminal |
| `POST /brand/{slug}`, `POST /logout` | the account menu |

Two behaviours worth knowing, because they are the server's rules and
not the client's:

- **Guide mode is gated on the `creative_guide` capability.** If the
  route is not there, Create becomes the default mode rather than the
  primary button 404ing.
- **The frame is refused, not clamped.** `POST /api/scenes/run` rejects a
  size outside `render_specs.RUNWAY_RATIOS` — a silently corrected frame
  is a clip that comes back the wrong shape. There is deliberately no
  separate "resolution": a ratio here IS a frame size.

## Shape

```
src/
  lib/api.ts          the ONLY module that calls fetch — the wiring seam
  lib/fixtures.ts     honest transcriptions of real responses
  lib/utils.ts        cn()
  components/ui/      Pill, OptionPopover, SendButton — the design system
  components/         Rail, Composer — the screen
  index.css           ZPF's tokens as a Tailwind v4 @theme
```

Tailwind v4 (no config file — tokens live in `@theme` in `index.css`),
Radix for the popovers and the account menu (focus trapping, Escape,
collision flipping, submenus), lucide-react for icons, motion for
entrance transitions.

## Type and colour

**Manrope**, self-hosted through `@fontsource-variable/manrope`. LTX's
brand face is Aeonik (checked against their own stylesheet, 2026-09-10);
it is licensed, so Manrope stands in — the closest free geometric
grotesque. Self-hosted rather than Google-hosted because the app is
behind sign-in and a third-party font request on first paint buys a
round trip and a flash of fallback text for nothing.

**Black and white, no hue anywhere.** The accent is white, which means
whatever carries it has to earn it: today that is the send button and
the current rail item, and nothing else. The token is named
`--color-accent` rather than `--color-white` so a future theme can move
it without a find-and-replace.

Note this DIVERGES from `app/static/zpf/zpf.css`, which is still the red
`--signal` and Oswald. The two will look like different products until
one of them moves.
