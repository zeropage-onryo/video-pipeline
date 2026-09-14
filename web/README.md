# zpf-web-5t

**The signed-in studio lives under `/studio`** (2026-09-11): the shell, the
Studio composer, the Director canvas (`/studio/flows`, see FLOWS.md) and
Elements (`/studio/elements`). It talks to the FastAPI backend through the
same-origin proxy in `next.config.ts` (`API_UPSTREAM`), so run the Python app
first. The marketing page at `/` is the v0-generated landing.

This is a [Next.js](https://nextjs.org) project bootstrapped with [v0](https://v0.app).

## Built with v0

This repository is linked to a [v0](https://v0.app) project. You can continue developing by visiting the link below -- start new chats to make changes, and v0 will push commits directly to this repo. Every merge to `main` will automatically deploy.

[Continue working on v0 →](https://v0.app/chat/projects/prj_ul5LxD37s7KQ5P4iH1a4bbXtQdKm)

## Getting Started

First, run the development server:

```bash
npm run dev
# or
yarn dev
# or
pnpm dev
```

Open [http://localhost:3000](http://localhost:3000) with your browser to see the result.

You can start editing the page by modifying `app/page.tsx`. The page auto-updates as you edit the file.

## Learn More

To learn more, take a look at the following resources:

- [Next.js Documentation](https://nextjs.org/docs) - learn about Next.js features and API.
- [Learn Next.js](https://nextjs.org/learn) - an interactive Next.js tutorial.
- [v0 Documentation](https://v0.app/docs) - learn about v0 and how to use it.

## Deploying

The API (`zeropage-studio` on Fly, the FastAPI app one directory up) stays
where it is whichever of these serves this front end. The browser never
talks to the API directly: every `/api`, `/auth`, `/signin`, `/brand` and
photo request goes to THIS app's origin and is proxied by the rewrites in
`next.config.ts` -- a cross-site cookie is a third-party cookie Safari and
Chrome refuse to send. Sign-in navigates to the API's origin and the
session comes back through `/auth/handoff` (see `app/auth.py`).

Three settings, the same on either host, all fixed at BUILD time:

| setting | value | why |
|---|---|---|
| `API_UPSTREAM` | `https://zeropage-studio.fly.dev` | the proxy's target; the rewrites are computed by `next build` |
| `NEXT_PUBLIC_AUTH_ORIGIN` | `https://zeropage-studio.fly.dev` | where Sign in / Sign out navigate |
| `NEXT_PUBLIC_API_URL` | *unset* | leaving it unset keeps fetches same-origin |

### Vercel (git-connected; the recommended host)

1. vercel.com -> Add New -> Project -> import the `video-pipeline` repo.
2. **Root Directory: `web`** (Edit next to the detected root). Framework
   auto-detects as Next.js; leave build settings alone.
3. Environment Variables: the two from the table, for Production and
   Preview. Do not add `NEXT_PUBLIC_API_URL`.
4. Deploy. Every later push to `main` deploys itself; branches get
   preview URLs.
5. On the API, once the hostname is known (e.g. `zpf-web.vercel.app`):
   it must be in `FRONTEND_ORIGINS` (preview hosts match
   `FRONTEND_ORIGIN_REGEX`), and `STUDIO_URL` should point at it so `/ui`,
   the landing page and a sign-in with no return address land there:
   `fly secrets set -a zeropage-studio STUDIO_URL=https://<host>`.

### Fly (`zeropage-web`)

```bash
cd web && fly deploy --remote-only --yes --build-arg NEXT_PUBLIC_AUTH_ORIGIN=https://zeropage-studio.fly.dev
```

`web/Dockerfile` bakes `API_UPSTREAM` in with a default of the API's
public origin; `web/fly.toml` describes the app. The machine stops when
idle, which is the one reason to prefer Vercel.
