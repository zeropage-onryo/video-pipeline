# Task — take the studio's API and media traffic off the Vercel proxy (`api.zeropage.studio`)

**Status: PLAN ONLY. Blocked until Mike owns `zeropage.studio`. Nothing below is
built, nothing is merged, and no dashboard setting has been changed.** Written
2026-09-22 while cutting Vercel usage on `zpf-web`; the other half of that job
(the Ignored Build Step, `web/vercel.json`) shipped the same day and is not
part of this.

Read `web/README.md` (the Vercel recipe) and the CLAUDE.md paragraph "The React
studio gets its session through a handoff, never cross-site (2026-09-14)"
first — this plan exists because that paragraph is true, and it stays true.

## What is happening today, measured

Every request the React studio makes goes browser → Vercel edge → Fly → back
through Vercel → browser:

- `web/next.config.ts` `rewrites()` (lines 20–36) proxies `/api/:path*`,
  `/ui`, `/signin`, `/auth/:path*`, `/refs`, `/renders`, `/characters`,
  `/props`, `/locations`, `/static` and `/brand` to `API_UPSTREAM`
  (`https://zeropage-studio.fly.dev` on Vercel).
- `web/src/lib/api.ts` line 5: `API_URL = process.env.NEXT_PUBLIC_API_URL ?? ""`.
  The variable is unset on Vercel (the README says so, on purpose), so every
  fetch is relative and lands on the proxy. Line 14: `AUTH_ORIGIN` is the Fly
  origin, so only the sign-in/sign-out NAVIGATIONS leave Vercel.
- Verified from the live site 2026-09-22: `zpf-web.vercel.app/api/capabilities`,
  `/auth/logout` and `/ui` all answer with `via: 1.1 fly.io` and no
  `x-matched-path` — an edge rewrite, not a function, so the cost lands on
  **Edge Requests**, **Fast Origin Transfer** (Fly → Vercel bytes) and **Fast
  Data Transfer** (Vercel → browser bytes). A photo streamed off the Fly
  volume is billed on both transfer meters.
- The pollers: `web/src/app/studio/queue/page.tsx` line 163 polls the job
  list every 2.5 s while the Queue is open (1,440 edge requests per open
  hour, before a single card is drawn); `flow-workspace.tsx` line 1245 polls
  every 2 s during a run; `shell.tsx` line 167 refreshes the Queue badge
  every 60 s on every studio page.
- Through the proxy FastAPI sees **the upstream's Host**, not the browser's:
  `curl -I https://zpf-web.vercel.app/auth/google/login` redirects to Supabase
  with `redirect_to=https://zeropage-studio.fly.dev/auth/callback` — the same
  as hitting Fly directly. (Verified 2026-09-22. This is what makes the
  cookie-domain rule below safe: the API can tell a proxied request from a
  direct one by its own hostname, because the proxy's upstream is a
  deployment setting.)

## Why the proxy exists, and why it must not simply be removed

`zpf-web.vercel.app` and `zeropage-studio.fly.dev` are different SITES
(`fly.dev` and `vercel.app` are both on the public-suffix list), so the API's
`zp_session` cookie is a third-party cookie to the studio. Safari always
refuses those on fetch and Chrome now does by default; on 2026-09-14 that was
`/signin` saying "already signed in" beside every `/api` call answering 401.
The proxy makes the fetch same-origin, and `/auth/handoff` sets the cookie on
the studio's origin through it. Pointing `NEXT_PUBLIC_API_URL` at `fly.dev`
today would reproduce that bug exactly.

**The only clean way out is one registrable domain for both.** `zeropage.studio`
for the Vercel site and `api.zeropage.studio` for Fly are the SAME site, so a
cookie with `Domain=zeropage.studio` is first-party to both and a direct
credentialed fetch from the studio to the API carries it. Nothing else in this
plan is clever; everything else is the bookkeeping that follows from that.

## The shape after the move

```
browser ──── zeropage.studio (Vercel: the Next pages, static + the landing images)
   │
   └──────── api.zeropage.studio (Fly: /api, /auth, /signin, /ui, /brand, media)
             cookie zp_session; Domain=zeropage.studio; SameSite=None; Secure
```

Preview deployments (`zpf-web-*.vercel.app`) keep the proxy exactly as today:
their `API_UPSTREAM` stays `https://zeropage-studio.fly.dev`, which is outside
the cookie domain, so they get a host-only cookie through the handoff as now.
That is why the `fly.dev` hostname must keep serving, and why the cookie
domain is decided per request rather than switched on globally.

## Files touched, exactly

### 1. `app/auth.py` — the cookie domain is a deployment setting, applied by hostname

- New helper beside `studio_url()` (line ~83):

  ```python
  def cookie_domain(host: str | None) -> str | None:
      """SESSION_COOKIE_DOMAIN (e.g. zeropage.studio) when `host` is that domain
      or a subdomain of it; None (a host-only cookie, today's behaviour) for
      any other host, including a request that reached us through a proxy
      whose upstream is the fly.dev name."""
  ```
  Reads `SESSION_COOKIE_DOMAIN`, strips a leading dot, matches
  `host == d or host.endswith("." + d)`. Unset → always `None` → byte-for-byte
  today's cookies. This is the one rule; nothing else decides.
- `issue_session` (line 229): `domain=cookie_domain(request.url.hostname)`
  on `set_cookie`. Keep `samesite="none"` / `secure=True` on https — same-site
  now, but `None` still works and changing it is a separate decision.
- `clear_session` (line 245) takes the request and passes the same
  `domain=` to `delete_cookie`, or logout silently fails on the new domain
  (a delete only matches a cookie with the same domain and path). Both
  callers are in this file (`/auth/logout` GET, line 648, and the POST).
- `_finish` (line ~560): when `cookie_domain(request.url.hostname)` is set
  AND the trusted `destination` host is inside that same domain, redirect
  straight to `destination` — the cookie just issued already covers it and
  the handoff round-trip through the proxy is redundant. Every other case
  (a preview host, the fly.dev host, no domain configured) keeps the handoff
  exactly as it is. Optional; the handoff is harmless if left.
- Tests in `tests/test_auth.py`: host inside the domain → `Domain=` attribute
  on the cookie; the fly host → none; `SESSION_COOKIE_DOMAIN` unset → none;
  logout deletes with the same domain; a handoff for a `*.vercel.app` preview
  under a configured domain still lands a host-only cookie.

### 2. `app/main.py` — CORS (lines 252–269), no code change

The allow-list is `auth.frontend_origins()` (`FRONTEND_ORIGINS` +
`STUDIO_URL`) with `allow_credentials=True`, already correct. What changes is
the Fly secrets (step 4 below). `FRONTEND_ORIGIN_REGEX` stays for previews.

### 3. `web/next.config.ts` — the rewrites become conditional

```ts
const direct = !!process.env.NEXT_PUBLIC_API_URL;   // read at build time
const proxied = direct
  ? ["/auth/:path*"]      // the handoff still lands here; previews never set the var
  : [ ...the full list as today... ];
```
When the client is built to call the API directly, the proxy routes for
`/api`, media, `/ui`, `/signin`, `/brand` and `/static` are simply not
emitted; `/auth/:path*` is always emitted for `/auth/handoff`. Preview builds
never see `NEXT_PUBLIC_API_URL` (it is a Production-only variable), so they
keep the full list. `web/src/lib/api.ts` needs no code change — `API_URL` and
`AUTH_ORIGIN` already read the variables; update the comment block (lines
1–14) so it stops saying the var must be empty. Every media URL in the studio
is already `${API_URL}${path}` (elements, assets, queue, cards, mentions,
element-sheet, add-element, shell, flow-workspace) and so follows the switch.
`concept-card.tsx` line 237 guards with `startsWith("/")`; `assets/page.tsx`
lines 239–300 do not — fine while `/api/media` returns relative paths, worth
a guard if that ever returns an R2 URL.

### 4. Deployment settings (Mike, dashboards and CLI — none of this is code)

**DNS + Fly:**
```bash
fly certs add api.zeropage.studio -a zeropage-studio      # prints the CNAME to create
# registrar: api  CNAME  zeropage-studio.fly.dev  (plus the _acme-challenge it prints)
fly certs check api.zeropage.studio -a zeropage-studio
fly secrets set -a zeropage-studio \
  SESSION_COOKIE_DOMAIN=zeropage.studio \
  STUDIO_URL=https://zeropage.studio \
  FRONTEND_ORIGINS=https://zeropage.studio,https://www.zeropage.studio,https://zpf-web.vercel.app
```
`fly secrets list` first — `FRONTEND_ORIGINS` is a full replacement, and the
current value is not readable from here. Repo file `fly.toml` line 14:
`DIRECTOR_FRONTEND_URL` → `https://zeropage.studio/studio/flows` (it points
at the scaled-to-zero `zeropage-web.fly.dev` today, which is already stale).

**Supabase** (Authentication → URL Configuration → Redirect URLs): add
`https://api.zeropage.studio/auth/callback`. `redirect_to` is built from the
request host (`request.url_for("auth_callback")`, auth.py line 696), so the
new host must be on the allow-list or Google/Discord sign-in dies with
Supabase's "redirect URL not allowed". Keep the fly.dev entry for previews.
The Google/Discord OAuth clients point at Supabase's own callback, unchanged.

**Vercel → zpf-web** (Mike; not to be changed from a session):
- Domains: add `zeropage.studio` (primary) and `www.zeropage.studio`
  (redirect to apex); set `zpf-web.vercel.app` to redirect to the primary.
- Environment variables, **Production only**:
  `NEXT_PUBLIC_API_URL=https://api.zeropage.studio`,
  `NEXT_PUBLIC_AUTH_ORIGIN=https://api.zeropage.studio`,
  `API_UPSTREAM=https://api.zeropage.studio`,
  `NEXT_PUBLIC_SITE_URL=https://zeropage.studio` (read by `layout.tsx` line 50,
  `robots.ts` line 5, `sitemap.ts` line 3 — canonical tags and the sitemap).
- Preview: leave `API_UPSTREAM` and `NEXT_PUBLIC_AUTH_ORIGIN` on the fly.dev
  origin and do NOT add `NEXT_PUBLIC_API_URL`.
- Redeploy Production (the `NEXT_PUBLIC_*` values are inlined at build).

**Stripe:** the webhook endpoint (`/billing/webhook`) can stay on the fly.dev
host, which keeps serving; move it to the api host whenever convenient.
Checkout's return URL follows `STUDIO_URL` (`src/billing.py` line 318).

## Order of operations, with the check at each step

1. Buy the domain. Point `api` at Fly, add the cert, wait for `fly certs check`
   to say issued. Add the Supabase redirect URL. Nothing user-visible changes.
2. Merge the code (steps 1–3 above) with `SESSION_COOKIE_DOMAIN` unset on Fly.
   Deploy the API. Nothing changes — every cookie is still host-only.
3. Add the domain to the Vercel project; the studio now answers on
   `zeropage.studio` **through the proxy**, upstream still fly.dev. Sign in
   there once: works exactly as on vercel.app (host-only cookie via handoff).
4. Set the Fly secrets (`SESSION_COOKIE_DOMAIN`, `STUDIO_URL`,
   `FRONTEND_ORIGINS`). Sign-ins on `api.zeropage.studio` now issue the
   domain cookie; the proxied ones still see the fly host and stay host-only.
5. Set the Production Vercel variables and redeploy. The studio calls
   `api.zeropage.studio` directly. Check, in Safari and Chrome:
   `curl -sI https://zeropage.studio/api/capabilities` is a Vercel 404 (no
   rewrite), `curl -sI https://api.zeropage.studio/api/capabilities` is 401,
   sign in → Queue loads → a card's photos draw → sign out clears the session.
6. Watch Usage for a day: Edge Requests and Fast Origin Transfer should
   flatten to the landing page's share; Function Invocations were never the
   studio's meter (the proxy is a rewrite, not a function).

**Rollback** at any point: remove `NEXT_PUBLIC_API_URL` and redeploy (the
studio is back on the proxy; the domain cookie still works through it because
the proxied host is now `api.zeropage.studio`), then unset
`SESSION_COOKIE_DOMAIN` if wanted. Old `zp_session` cookies on the wrong
domain just mean one extra sign-in.

## Deliberately not in this plan

- Turning `SameSite=None` into `Lax`. Correct once everything is one site,
  but it is a second behaviour change and belongs in its own commit after
  the move is verified.
- Returning R2 URLs from `/api/media` so media skips Fly as well as Vercel.
  The wall concatenates `${API_URL}${url}` unconditionally; do it with the
  guard, as a separate change, if Fly's own egress ever matters.
- Anything about the Fly-hosted `zeropage-web` app: it stays scaled to zero.
