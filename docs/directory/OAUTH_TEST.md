# OAuth and tenancy — the live script, and two findings

Phase 2 of `docs/tasks/task-directory-listing.md`. The code half (the
rate limit, the issuer check, the token and cross-tenant tests) is commit
`feat(mcp): per-account rate limit on the mount; cross-tenant and token
tests` on this branch. This file is the half only a person with a second
account can finish.

## What the tests now prove (no live call needed)

`tests/test_mcp_mount.py`, run as CI runs it:

- **Token validation** (`mcp_auth.verify`): a token for this resource
  verifies; an ordinary session token (`aud: authenticated`) verifies; a
  token minted for another resource is refused; an expired token is
  refused; a token with the right audience and an unknown issuer is refused
  (new: `_issued_here` — the issuer is now checked, which it was not); a
  forged signature is refused; the JWKS path accepts the project's ES256 key
  and nobody else's. `account_for_token` on a real schema answers
  `invalid_token` / `no_account` / the oldest membership.
- **Rate limit**: over the limit → 429 with `Retry-After`; another account
  is unaffected; the window turns over; the operator's key has its own,
  higher bucket; a bad setting falls back to the default and never to
  unlimited; an unauthenticated caller touches no bucket.
- **Isolation through the real streamable-HTTP app**, Alice and Bob each
  with their own account: `board`, `stats` and `search` return only the
  caller's rows; `capture` lands on the caller's board; `idea`, `pick`,
  `archive`, `shoot` on the other person's id answer "no concept N" (the
  same answer a nonexistent id gets) and change nothing; `job` on the other
  person's job answers "no job N"; the operator's static key still reads the
  bootstrap account.
- **The listed server** (2026-10-07): a signed-in caller's `tools/list` is
  exactly `LISTED_TOOLS`; `sparks` and `images` are unknown tools to them
  (the bank is shared by design, see Finding 2); the operator's key lists
  the full set; the engine flag changes nothing on the listed server.
- **No tool reports a credit balance.** `pick` quotes a draw; nothing
  answers "what can I spend". Noted for Phase 3.

## Finding 1 — first contact through the connector is a 403

`guarded` → `account_for_token` → `accounts.memberships(sub)` is empty →
`no_account` → **403 "this sign-in has no account yet -- ask to be invited"**.
The web sign-in provisions a workspace on first contact
(`app/auth.py:_provision` → `accounts.provision_personal`, open sign-up on by
default, plus the 100-credit trial); the mount never calls it. A stranger
who installs the connector from the directory, signs in through Supabase
and has never opened `zeropage.studio` gets a 403 on every tool.

Two options. **Not implemented** — it decides whether a stranger can create
an account through the connector:

- **A. Provision at the mount**, the way `app/auth.py` does at web sign-in:
  in `guarded`, on `no_account`, call `accounts.provision_personal(sub, email,
  name)` (the claims carry `email`; Supabase OAuth tokens may not carry a
  display name) and `grant_signup_credits`, then resolve again. One call
  site, ~15 lines, the same `open_signup()` switch. Consequence: anyone
  with a Supabase-verified email becomes a tenant with 100 trial credits by
  connecting from Claude, with no page of ours ever shown. The sign-up
  credits are what `imagine_reference` would spend (Phase 3).
- **B. Require one web sign-in first**, and say so: the connector
  description and the plugin README tell the person to sign in at
  `https://zeropage.studio` once ("your workspace is created on your first
  sign-in"), and the 403 body says the same with the link, instead of "ask
  to be invited" (which is wrong under open sign-up anyway). Zero schema or
  flow change; the reviewer's test account is pre-provisioned by Mike.

**Recommendation: B for the submission, A later if the funnel shows people
dropping at the 403.** Reasons: the consent page (Finding 3) already forces
a browser visit to our origin, so "sign in once on the web" is not an extra
step in practice; the trial-credit grant stays behind a surface we draw;
and the directory reviewer tests with the account Mike hands them, not a
fresh sign-up. The 403 text should change under either option — that edit
is in Phase 4's scope only if Mike picks B (it is a message, not a flow).

## Finding 2 — the sparks bank and the reference bin are shared (DECIDED: off the listed server)

**Mike, 2026-10-07: the bank stays off the listed server.** `build_server(listed=True)` registers `LISTED_TOOLS` only and the mount routes a signed-in caller to it; the xfail below became a passing test that `sparks` / `images` are unknown tools through that door. The paragraph that follows is the finding as it stood.

`sparks`, `tonight`, `add_spark`, `images`, `reference`, `imagine_reference`
and `research` read and write `scout_findings` / `scout_bin`, which are
shared across accounts on purpose ("a direction is not anyone's row",
`db.SHARED_TABLES`). For one operator with two brands that was the right
call. For a directory of strangers it means user A's typed directions and
banked images are listed to user B by `sparks` and `images`, and A's
`add_spark` is what B's `tonight` serves. Options, for Mike:

- fence the bank per account (an `account_id` column on both tables, the
  owned-table pattern, `tests/test_tenancy.py`'s schema guard, a backfill
  that claims the live rows for account 1) — then the xfail test flips green;
- or keep the bank shared and leave those seven tools off the connector a
  stranger reaches (Phase 3's option A does this for the spending ones; the
  read ones would go with them).

## Finding 3 — there is no consent page

Supabase's OAuth 2.1 server does not draw the consent screen. Its
`/auth/v1/oauth/authorize` validates the client, PKCE and redirect, then
**redirects the person to `<Site URL><Authorization Path>?authorization_id=<id>`**,
a page WE must serve (dashboard: Authentication → OAuth Server →
Authorization Path; Site URL is under URL Configuration — the email-templates
doc says it is the API origin). Nothing under `app/` or `web/src/` reads
`authorization_id`, and `docs/RUNBOOK.md` / `.env.example` have no note on
it. So today the flow from Claude ends on whatever the Site URL serves at
that path: a 404 on the API origin, or the landing page if the path is
unset. Sign-in cannot complete.

What is needed (not built here):

- **Route**: `GET /oauth/consent?authorization_id=…` on the API origin
  (`app/auth.py`'s router, beside `/signin`), and the same path set as the
  Authorization Path in the Supabase dashboard.
- **Session**: the person must be signed in TO SUPABASE for the approve call,
  and this app keeps no Supabase session — the cookie carries only the uid
  and the token is verified once and dropped. The page therefore has to
  mint a one-call user session the way `/studio/settings` already does for a
  password or email change (`auth.user_session_by_password` /
  `user_session_by_code`: "minted, used and dropped"), or run the sign-in
  step inline (email code, the existing `/signin` flow) carrying
  `authorization_id` through `next`.
- **Display**: `GET {SUPABASE_URL}/auth/v1/oauth/authorizations/{id}` (bearer:
  the person's token) returns the client name, the requested scopes and the
  **redirect URI — show its hostname** (`claude.ai`, or `localhost:<port>`
  for Claude Code; C21 asks for exactly this, with a warning on a loopback
  redirect). If the answer is a redirect rather than details, the person
  consented before — send them straight to `redirect_url`.
- **Decision**: `POST {SUPABASE_URL}/auth/v1/oauth/authorizations/{id}/consent`
  with `{"action": "approve"}` or `"deny"` (what `supabase.auth.oauth.
  approveAuthorization` / `denyAuthorization` call), bearer: the same token;
  the response carries `redirect_url` with the code and `state` — 303 there.
- **Tests**: the `gotrue` seam in `tests/test_auth.py` gains the two
  authorization endpoints; a page test for "shows the client name and the
  redirect host", "deny redirects with `error=access_denied`", and "a
  missing `authorization_id` is a 400, not a login loop".
- **Dashboard**: Authorization Path set; redirect URIs are registered by
  Claude itself through DCR (`registration_endpoint` is live), so nothing to
  allow-list by hand — unless Supabase's DCR refuses Claude Code's loopback
  redirect, which the live script below checks.

Until this exists the connector cannot be connected from claude.ai at all,
whatever the tools look like. It is the one build the submission is
blocked on that no decision can remove.

## The live script (Mike, with the second account)

Use `zp-billing-test` (account 5) as the SECOND person. Mike's own sign-in
is the first. Nothing below spends: `pick` quotes, `imagine_reference` is
not called.

Each step says what PASS looks like. Take the screenshot where it says
`📸`; the names are the ones `SUBMISSION.md` asks for.

0. **Which commit is live.** `fly releases --app zeropage-studio` (read-only).
   PASS: the newest release's commit is `main`'s tip or later than
   `209f7e9`. Note it in `SUBMISSION.md`'s live-check table. Then
   `fly ssh console -C "env" | grep ZEROPAGE_MCP` is the only way to read
   the engine flag — read-only, but it prints the token; do it with the
   output off the screen, or skip and infer from step 4.
1. **Discovery, no sign-in.** In a terminal:
   `curl -si -X POST https://zeropage-studio.fly.dev/mcp/ -d '{}'`.
   PASS: `401` and a `WWW-Authenticate: Bearer resource_metadata=".../.well-known/oauth-protected-resource/mcp"` header.
   `curl -s https://zeropage-studio.fly.dev/.well-known/oauth-protected-resource/mcp`
   PASS: `resource` is exactly `https://zeropage-studio.fly.dev/mcp`.
2. **Connect from claude.ai as the second person.** Signed in to claude.ai
   as any account, Customize → Connectors → Add custom connector → URL
   `https://zeropage-studio.fly.dev/mcp` → Connect. The browser lands on
   Supabase's authorize endpoint and then on OUR consent page.
   PASS: a page on `zeropage-studio.fly.dev` (or the Site URL) that names the
   client ("Claude"), the redirect host `claude.ai`, and Approve / Deny.
   **Expected today: FAIL** (Finding 3) — a 404 or the landing page. That
   result is itself the screenshot for the report. 📸 `consent-page.png`
   once it exists.
3. **Sign in as `zp-billing-test` on the consent page, approve.** PASS: the
   connector shows **Connected** under Your connectors, and its page lists
   the tools under Tool permissions, each with a title. 📸 `tool-list.png`
   (this is the plugin README's "what you get" image too).
4. **`board` as the second person.** In a chat with the connector on: "show
   my board". PASS: `count: 0, ideas: []` for `zp-billing-test` (its board
   is empty — if it is not, somebody wrote to account 5 since
   2026-10-01). If `research` or `generate` appear in the tool list, the
   engine flag is set on Fly (step 0's inference). 📸 `empty-board.png`.
5. **`idea` with one of Mike's concept ids.** "show idea 375" (Neon City
   Ascent, account 1). PASS: an error reading `no idea 375` — never the
   title, never the prompt. 📸 `cross-tenant-refused.png`.
6. **`capture`, then `board`.** "capture an idea called Smoke test". PASS:
   the card comes back with `status: open`; `board` now lists one idea;
   Mike's own board (first account, studio Pipeline page) does NOT show it.
7. **`pick` on that idea.** PASS: `status: picked`, no `keyframes` block (a
   captured idea has no scene, so there is nothing to draw) — and the
   account's credit balance on `/studio/settings` is unchanged.
8. **`sparks`.** PASS: the tool is not in the second person's list at all,
   and asking for it answers "Unknown tool". (Before 2026-10-07 this step
   showed Mike's banked sparks -- the Finding 2 evidence.)
9. **The rate limit.** From a terminal with the second person's access token
   (copy it from the browser's network tab on any `/mcp` call, or mint one
   from the console): a loop of 130 `tools/list` posts inside a minute.
   ```bash
   for i in $(seq 1 130); do curl -s -o /dev/null -w "%{http_code}\n" -X POST https://zeropage-studio.fly.dev/mcp/ -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' -H 'accept: application/json, text/event-stream' -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'; done | sort | uniq -c
   ```
   PASS: `120` lines of `200` then `429`s; a `429` body reads
   `{"error":"rate_limited","detail":"over 120 requests in 60s -- wait Ns before calling again"}`
   with a `Retry-After` header. Mike's own connector keeps working during
   the loop (another account is another bucket). 📸 `rate-limit-429.png`.
10. **Sign the second person out and reconnect.** PASS: the consent page is
    skipped the second time (Supabase remembers the consent) or shown
    again — either is fine; what must NOT happen is landing on Mike's board.
11. **Claude Code.** `claude mcp add --transport http zeropage https://zeropage-studio.fly.dev/mcp`
    then `/mcp` → authenticate. PASS: the loopback redirect
    (`http://localhost:<port>/callback`) is accepted by Supabase's DCR and the
    consent page shows `localhost` as the redirect host. If Supabase refuses
    the loopback redirect, C20 is a FAIL and `mcp-review@anthropic.com` is
    who to ask about Anthropic-held credentials.
