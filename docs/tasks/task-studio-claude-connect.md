# Task — "Connect to Claude" in the studio, then finish the directory listing

**Hand this whole file to a new Claude Code session.** Written 2026-10-08,
after `docs/tasks/task-directory-listing.md` was built and merged (PR #151,
consent page live; sign-in pictures PR #160). Three parts. Part A is code;
Parts B and C are mostly Mike's, with checks you can run.

Read first: CLAUDE.md's paragraph "THE LISTED SERVER (2026-10-07 ...)" (the
two MCP servers, routed by door, the 13 listed tools, the consent page);
`docs/directory/SUBMISSION.md` (what is left, in order);
`docs/directory/OAUTH_TEST.md` (the live script).

## What is true today (checked 2026-10-08)

- The connector URL is `https://zeropage-studio.fly.dev/mcp`. A signed-in
  person reaches the LISTED server: `board`, `idea`, `search`, `capture`,
  `pick`, `shoot`, `archive`, `stats`, `elements`, `write_scene`, `quote`,
  `approve`, `job` (`src/mcp_server.LISTED_TOOLS`).
- Connecting works end to end, live: claude.ai → Supabase OAuth → our
  `/oauth/consent` → `/signin` → Allow → "Connected" in claude.ai with the 13
  tools listed under their titles (walked 2026-10-08 on Mike's own account).
- **Nothing connects automatically, and nothing on our side can.** Signing in
  or signing up to the studio creates the workspace and nothing else. A
  connector is added FROM claude.ai (Customize → Connectors → Add custom
  connector, or the directory's Connect button once listed); claude.ai starts
  the OAuth flow, and our consent page is where the person says yes. The
  studio has no API into a person's claude.ai account and must not pretend
  to. What the studio CAN do is make that one step obvious and show whether
  it has happened.
- The studio shell (`web/src/components/studio/shell.tsx`): the rail's
  account row at the bottom (`.racct`) opens a menu with Settings and Sign
  out; the header's avatar opens a twin menu (`hmenu`). `/studio/settings`
  (`web/src/app/studio/settings/page.tsx`) has Profile, Password, Email and
  Workspaces sections.
- Not yet proven live: **cross-account isolation**. The 2026-10-08 walk was
  signed in as Mike, so `board` returned his board and a "Smoke test" card
  (#396) was captured onto it (archived the same day). The second-account
  walk is still owed (Part B).

## Ground rules

1. Nothing renders and nothing spends. Tests use stubs; `tests/conftest.py`
   blocks the network. No call to fal, Gemini image/video or any provider.
2. Never enter a password or an emailed code into a live site; Mike signs in.
3. Branch from `main`, one commit per part, open a PR, merge only on Mike's
   word (`gh pr merge --merge`; auto-merge is off on this repo). A merge to
   `main` deploys Fly immediately.
4. `venv/bin/python -m pytest tests/ -q` and `venv/bin/ruff check .`; for
   `web/`: `npx tsc --noEmit` and `npx eslint src`.
5. STOP AND ASK before: a new table or column on the live database, anything
   that changes who can reach which MCP tools, any change to billing.

---

# Part A — "Connect to Claude" near the profile (code)

**The ask (Mike, 2026-10-08):** "I want to be able to access the MCP from the
studio page at the bottom near profile."

### A1. The entry point

- In the rail's account menu (bottom, next to the profile row) add **Connect
  to Claude**, above Settings. Same item in the header avatar's menu, so the
  two menus stay twins.
- It opens a small panel (a sheet or a popover, the studio's existing modal
  style) — not a new page in the rail. Content, in this order:
  1. One line: what it is ("Use your studio from Claude: read the board, write
     scenes, price and approve renders, with your yes before anything spends").
  2. The connector URL `https://zeropage-studio.fly.dev/mcp` with a Copy
     button. Read it from one place: add it to `GET /api/me` or
     `GET /api/capabilities` as `mcp_url`, derived from
     `mcp_auth.resource_url()` — never hard-code a second copy in `web/`.
  3. Three numbered steps: open claude.ai → Customize → Connectors → Add
     custom connector, paste the URL, press Connect and sign in with the same
     account as this studio. A button that opens
     `https://claude.ai/customize/connectors` in a new tab.
  4. Once the directory listing is live (Part C), the steps collapse to one
     button pointing at the listing page. Keep that URL in config
     (`ZEROPAGE_CLAUDE_DIRECTORY_URL`, unset = show the manual steps), so
     the switch is a Fly env change, not a deploy.
- **Check before building, don't assume:** whether claude.ai accepts a deep
  link that pre-fills a custom connector URL. If one exists and is documented
  (search https://claude.com/docs/llms.txt), use it for the button; if not,
  the copy-and-paste steps above are the design. Say which in the PR.

### A2. Show whether it is connected

The panel should say "Connected to Claude" (and when) once it is. The studio
cannot ask claude.ai, but it can see both ends of OUR side of the flow:

- **When the person presses Allow** on `/oauth/consent`
  (`app/oauth_consent.consent_decision`, action `approve`, Supabase answered
  with a `redirect_url`): record it. And **every request through the
  listed door** in `app/mcp_mount.guarded` (after the account is resolved)
  can stamp a last-used time for that account.
- Where to keep it is a schema decision → **stop and ask Mike** with a
  proposal: either an OWNED table `mcp_connections (account_id, user_id,
  client_name, redirect_host, approved_at, last_used_at)` registered in
  `db.OWNED_TABLES` (the tenancy schema test enforces it), or two additive
  columns on `accounts`. Recommendation: the table (a person can connect
  more than one client; Claude Code and claude.ai are two).
- The last-used stamp must not add a database write to every MCP call:
  update at most once per account per N minutes (an in-process memo, the
  rate limiter's shape), and never let a failed write fail the request.
- `GET /api/me` (or a new `GET /api/mcp/connection`, guarded by
  `auth.current_account_id` — the route tenancy test requires it) returns
  `{connected, approved_at, last_used_at, client_name}` for the caller's
  account only.
- **Disconnect is claude.ai's**, and Supabase's grant list needs the person's
  own token, which this app does not keep. So the panel says "To disconnect,
  remove ZeroPage in claude.ai → Customize → Connectors" with the same link.
  Do not build a revoke button unless you find a way that does not store a
  user token; if you find one, stop and ask.

### A3. Tests and checks

- Route tests: the panel's data route answers only the caller's account; a
  second account sees `connected: false`.
- Consent test: an approve writes the connection; a deny writes nothing.
- Mount test: N calls through the listed door write the last-used stamp once
  inside the window; the operator's static key writes nothing.
- `web/`: the menu item is in both menus; the panel renders with and without
  `mcp_url`; Copy works; 390px width has no horizontal scroll. Walk it in
  the Browser pane against a stubbed API (the recipe in the memory note
  "Worktree browser verification").

---

# Part B — the cross-account walk (Mike signs in, you check)

`docs/directory/OAUTH_TEST.md` steps 2–10, as `zp-billing-test` (account 5).

1. Mike: in claude.ai, Customize → Connectors → ZeroPage → **Disconnect**,
   then **Connect**, and on the Zero Page sign-in use the `zp-billing-test`
   email (code or password) — NOT "Continue with Google", which signs him in
   as himself. Allow on the consent page.
2. You: in a new claude.ai chat with only ZeroPage on, run `board` with
   status `all` **first, alone**. PASS = an empty board (or only account 5's
   cards). If it shows #395/#384/#375, the sign-in is Mike's again — stop,
   write nothing, ask him to redo step 1.
3. Only after step 2 passes: `idea` 375 → must be an error naming "no idea
   375"; `capture` "Smoke test" → card on account 5; `board` again → only that
   card; `pick` it → picked, no spend. Then archive it.
4. Cross-check with the operator's local MCP (`mcp__zeropage__board`, which
   reads account 1): the smoke-test card must NOT appear there.
5. Record the result in `docs/directory/OAUTH_TEST.md` (a dated "walked"
   line per step) and in `SUBMISSION.md`'s status table (C26 → PASS).

# Part C — the submission (Mike's, at claude.ai/directory/manage)

Everything is drafted in `docs/directory/SUBMISSION.md` → "Everything Mike
must do by hand". What is already done: the PR merged, the consent page live,
the Authorization Path set to `/oauth/consent`, the public plugin repo at
https://github.com/zeropage-onryo/zeropage-studio-plugin (MIT, Issues on),
the icon at `docs/directory/icon/zeropage-studio-icon-512.png` (square,
opaque; the 1024 beside it). What is left:

1. Part B passes.
2. Populate `zp-billing-test` for reviewers (3–5 ideas, one with a written
   scene and photos, a small credit balance) and put its credentials in the
   portal only.
3. Portal → Submit new → MCP connector → the fields in SUBMISSION.md.
4. Portal → Submit new → Plugin bundle → `zeropage-onryo/zeropage-studio-plugin`
   → Validate → submit; set up the push webhook.
5. Pair the two listings. Then set `ZEROPAGE_CLAUDE_DIRECTORY_URL` on Fly so
   Part A's panel points at the listing.

The open review risk, stated once: the connector checklist refuses
connectors that "generate images, video, or audio through AI models", and
`approve` renders on purpose (Mike's call). If the listing is refused on it,
remove `approve` from `LISTED_TOOLS` and the Queue stays the place to
approve.
