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
| `NEXT_PUBLIC_AUTH_ORIGIN` | `https://api.zeropage.studio` (Production); `https://zeropage-studio.fly.dev` (Preview) | where Sign in / Sign out navigate |
| `NEXT_PUBLIC_API_URL` | *unset* | leaving it unset keeps fetches same-origin |

**Why sign-in goes to `api.zeropage.studio` (2026-10-07).** Chrome showed a
"Did you mean zeropage.studio?" lookalike warning when Sign in on
`zeropage.studio` navigated to `zeropage-studio.fly.dev`. The API now also
answers on `api.zeropage.studio` (a Fly certificate on `zeropage-studio`,
and an `api` CNAME to `d6rkm5r.zeropage-studio.fly.dev` in the Vercel DNS
zone), and only the Production sign-in/sign-out NAVIGATION moved there.
`API_UPSTREAM`, the proxy, the handoff and the cookie are unchanged, and the
`fly.dev` hostname keeps serving: Preview builds still sign in there, and it
is still the proxy's target. The API builds Supabase's `redirect_to` from the
request host, so `https://api.zeropage.studio/auth/callback` has to be on
Supabase's Redirect URLs list beside the `fly.dev` one. The rest of the move
(direct fetches, a shared cookie domain) is `docs/tasks/task-api-domain-move.md`.

### Vercel (git-connected; the recommended host)

1. vercel.com -> Add New -> Project -> import the `video-pipeline` repo.
2. **Root Directory: `web`** (Edit next to the detected root). Framework
   auto-detects as Next.js; leave build settings alone.
3. Environment Variables: the two from the table, for Production and
   Preview. Do not add `NEXT_PUBLIC_API_URL`.
4. Deploy. Every later push to `main` deploys itself; branches get
   preview URLs. **A push that changes nothing under `web/` is skipped**
   (`web/vercel.json`'s `ignoreCommand`, 2026-09-22; since 2026-10-08 it
   runs `web/scripts/vercel-ignore.sh`): before it, every docs/tests/adapter
   commit in the monorepo was a full `next build` and a new deployment --
   51 of the 105 commits in the five days before the file landed. Exit 0
   is the skip; anything else builds. Two rules:
   - **`main` (production)** diffs `VERCEL_GIT_PREVIOUS_SHA` (the last
     deployment that actually built, so a push of several commits is
     judged as a whole) against `HEAD`, falling back to `HEAD^`.
   - **Any other branch** diffs its merge base with `main` against `HEAD`:
     a branch whose changes touch `web/` builds on every push, and one that
     only merges `web/` changes in from `main` never does. The production
     rule under-built here, which is why previews no longer use it: on a
     branch's first push `VERCEL_GIT_PREVIOUS_SHA` is unset, and when that
     tip is a merge FROM `main`, `HEAD^` already holds the branch's own
     `web/` change, so the diff saw only `main`'s commits. PR #182
     (2026-10-08) changed 20 files under `web/` and got "1 Skipped
     Deployment" that way. Vercel clones with `--depth=10`, so the script
     fetches `main` (from `origin`, else the public GitHub URL that
     `VERCEL_GIT_REPO_OWNER`/`VERCEL_GIT_REPO_SLUG` name) and deepens both
     histories to 64, 256, then 1024 commits until the merge base shows.

   Whenever the script cannot tell -- no remote, a failed fetch, a SHA
   outside the clone, no merge base within 1024 commits -- it builds: an
   extra build costs minutes, a skipped preview costs the review.
   `tests/test_vercel_ignore.py` replays these shapes on `--depth=10`
   clones, PR #182's merge tip first. The file is only read because Root
   Directory is `web`; move the root and the setting moves to the dashboard
   (Settings -> Git -> Ignored Build Step) as
   `sh web/scripts/vercel-ignore.sh` (the script finds the repository root
   itself).
   **So a `NEXT_PUBLIC_*` change cannot be rebuilt by redeploying
   production.** A redeploy builds the same commit, the diff is empty, and
   the build is canceled. Deploy from the CLI instead, which skips the step. Run it from
   the REPOSITORY ROOT (Root Directory is `web`, so a deploy from inside
   `web/` fails with "Root Directory does not exist"), on a clean checkout of
   the commit production runs, with `.claude` listed in a temporary
   `.vercelignore` (the CLI does not read `.gitignore`):
   `npx vercel@latest link --yes --project zpf-web --scope zero-page-ai`, then
   `npx vercel@latest deploy --prod --scope zero-page-ai`. `vercel link`
   also writes `.env.local` and appends to `.gitignore`; remove both after.
5. On the API, once the hostname is known (e.g. `zpf-web.vercel.app`):
   it must be in `FRONTEND_ORIGINS` (preview hosts match
   `FRONTEND_ORIGIN_REGEX`), and `STUDIO_URL` should point at it so `/ui`,
   the landing page and a sign-in with no return address land there:
   `fly secrets set -a zeropage-studio STUDIO_URL=https://<host>`.

### Fly (`zeropage-web`)

```bash
cd web && fly deploy --remote-only --yes --build-arg NEXT_PUBLIC_AUTH_ORIGIN=https://api.zeropage.studio
```

`web/Dockerfile` bakes `API_UPSTREAM` in with a default of the API's
public origin; `web/fly.toml` describes the app. The machine stops when
idle, which is the one reason to prefer Vercel.
