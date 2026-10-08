# Task — get Zeropage Studio ready for the Claude directory (MCP connector + plugin bundle)

**Hand this whole file to Claude Code.** Written 2026-10-07 on branch
`claude/zeropage-directory-submission-a144d6`. It is six phases with one hard
stop in the middle (Phase 3 ends in a decision only Mike can make). Phases 0–2
are reading and auditing; nothing in them changes behaviour. Phase 4 is the
only code phase that lands without a decision. Phase 5 is a NEW PUBLIC repo.

**The goal.** Two directory submissions: (1) the remote MCP server at
`https://zeropage-studio.fly.dev/mcp` listed as an MCP connector, and (2) a
public plugin bundle whose skills teach Claude the studio workflow. Target
users are creators and filmmakers, self-serve. Agencies come later.

Read first, in this order: the CLAUDE.md paragraphs headed
"`src/mcp_server.py` + `app/mcp_mount.py`" and "TWO DOORS SINCE 2026-09-24"
(the mount, the two credentials, `CALLER_ACCOUNT`, the audience check);
`app/mcp_auth.py`'s module docstring (why this app is only the RESOURCE
server); `tests/test_mcp_mount.py` (the two-caller transport test is the
proof the tenancy design rests on); `docs/BACKLOG.md` (several gaps below are
already recorded there with reasoning).

## Ground rules

1. **Nothing renders and nothing spends.** No call to fal, Nano Banana,
   Gemini image/video, Runway, Higgsfield, or any paid provider. Tests use
   stubs only — `tests/conftest.py` blocks the network and a
   `NetworkUseInTest` is a bug in the test, never a reason to loosen the
   guard. If a live call seems necessary to answer a question, STOP and ask.
2. **Fly is read-only to you.** Do not change secrets or env vars, and do not
   set `ZEROPAGE_MCP_ENGINE=1` in production. Propose the change in the
   status report and wait. (Memory note: the classifier blocks reading Fly
   secrets; do not try to list them either. `fly.toml` is the readable part.)
3. **No push, no merge, no PR.** Commit on this branch, small commits, one
   per phase. Tell Mike what is on the branch; he pushes.
4. **The plugin repo is PUBLIC.** Nothing from this private repo goes into it
   unless written fresh for a stranger: no keys, no Mac paths, no personal
   skills (`.claude/skills/zp-*`, `idea-agent`), no Antihero or brand prompts,
   no internal notes, no account slugs, no concept ids off the live board.
   Read every file you put there once more as if you were a stranger reading
   it on GitHub.
5. **Keep the rules that already exist intact:**
   - the tenant comes in through `auth.current_account_id` (Depends) on
     routes, and through `mcp_server._account` on tools (`account_id` →
     `CALLER_ACCOUNT` → bootstrap), and is passed INTO helpers, never
     re-derived inside them (`tests/test_tenancy.py` is the guard);
   - a reference image is named by id only — `guide_tools.check_args` refuses
     a URL-shaped argument and the MCP surface must do the same;
   - the spend gate stays a human click or a quote-then-approve flow
     (`pricing.display()` / `pricing.sign()` / `queue_approve`), never an
     "approved" that lives in the environment;
   - the ledger hold happens BEFORE the provider submit (`src/charge.py`;
     `InsufficientCredit` means no HTTP call was made).
6. `venv/bin/python -m pytest tests/ -q` and `venv/bin/ruff check .` — the
   same two commands CI runs. Record the baseline count before you start.
7. **STOP AND ASK before:** changing Fly env, enabling the engine flag in
   prod, any live provider call, any change to billing or ledger behaviour,
   or anything that could expose another account's data.

## What is true today (checked 2026-10-07, read off this tree)

- `src/mcp_server.py` registers, under `build_server`: `board`, `idea`,
  `search`, `capture`, `pick`, `shoot`, `archive`, `add_spark`, `tonight`,
  `sparks`, `images`, `reference`, `imagine_reference`, `images_for`,
  `stats` always; `research`, `generate`, `job` only when
  `engine_enabled()` (`ZEROPAGE_MCP_ENGINE=1`). Every tool already carries
  an annotation object (`read_only` / `writes`) — check what those objects
  actually set (`readOnlyHint`, `destructiveHint`, `idempotentHint`,
  `openWorldHint`) rather than assuming they are complete.
- **The MCP server this Claude session is connected to exposes
  `generate_image` and `image_models` as well.** Those are not on this
  branch's `src/mcp_server.py`. They come from the main checkout's working
  tree (its newest commit is `ca4be3f feat(web): landing-page components +
  design MCP servers`, not on `main`). Find out which tool set is DEPLOYED
  on Fly (what `main` carries is what deploys) and audit that one. Say in
  the report which commit the live server is running and whether the image
  tools are reachable there.
- `imagine_reference` spends: it draws a still and charges the caller's
  credits (not charged on the operator's exempt account). It is NOT engine
  gated. Note it in the Phase 1 table as a spending tool on the always-on
  list.
- `generate` (`run_graph`) refuses outright while `ZEROPAGE_RENDER=1`; the
  graph it runs ends PARKED in the Queue. `research` crawls and banks; it
  spends model credit (Gemini), not render credit.
- `app/mcp_mount.py`: `ZEROPAGE_MCP=1` and a non-empty `ZEROPAGE_MCP_TOKEN`
  or the mount is refused. `guarded()` compares the static token with
  `hmac.compare_digest` (operator = bootstrap account), else verifies a
  Supabase access token through `mcp_auth.verify` (JWKS or
  `SUPABASE_JWT_SECRET`, `aud` = `ZEROPAGE_MCP_RESOURCE` or the session
  audience) and resolves ONE account by `min(membership id)`. No
  membership → 403, never a fall-through. The 401 carries
  `WWW-Authenticate` naming `/.well-known/oauth-protected-resource` (and the
  `/mcp`-suffixed path).
- **There is no rate limit on the mount.** `grep -n "rate\|limit"
  app/mcp_mount.py` finds nothing but prose.
- `accounts.provision_personal` exists and is called from `app/auth.py`
  line ~635 at WEB sign-in (open sign-up on by default). The MCP door does
  NOT call it: a person whose first contact with the studio is the connector
  (OAuth through Supabase, never signed into the web app) has no membership
  and gets 403. That is a Phase 2 finding to confirm and to design around,
  not something to silently change.
- The landing site has `/privacy` and `/terms` (`web/src/app/privacy`,
  `web/src/app/terms`), served from `zeropage.studio`. Confirm they are live
  with a fetch before the submission pack names them.
- `tests/test_mcp_mount.py` (15 tests) and `tests/test_mcp_server.py` (43)
  exist. Extend them; do not start a third file for the same surface.
- There is no `claude/` folder in this repo. The notes this project keeps
  are `docs/tasks/task-*.md` (this file's shape), dated entries in
  `docs/RUNBOOK.md`, and `docs/BACKLOG.md`. The summary Mike asked for goes
  to `claude/directory_listing_2026-10-07.md` as requested — create the
  folder — and is written in the RUNBOOK's dated-entry voice.

---

# Phase 0 — read the source of truth (no code)

Fetch and read, in order. Use WebFetch; if a page is unreachable say so in
the checklist rather than guessing its content.

- https://claude.com/docs/llms.txt (the index — use it to find anything the
  list below has moved)
- https://claude.com/docs/directory/publish
- https://claude.com/docs/connectors/building/review-criteria
- https://claude.com/docs/connectors/building/submission
- https://claude.com/docs/plugins/pre-submission-checklist
- https://claude.com/docs/plugins/submit
- https://claude.com/docs/plugins/quickstart

Write **`docs/directory/REQUIREMENTS.md`**: one checklist, every requirement
as a line, the source URL beside each item, grouped Connector / Plugin /
Both. Quote the requirement's own wording where the page gives one; a
paraphrase of a review criterion is how a submission gets bounced. This file
is the rubric every later phase is graded against — Phase 1's PASS/FAIL
table and Phase 6's status report both key on its item numbers.

Commit: `docs(directory): requirements checklist from the published pages`.

# Phase 1 — audit the live MCP surface (read-only)

Known facts to start from: `POST /mcp/` without auth returns 401 with a
`resource_metadata` pointer; `/.well-known/oauth-protected-resource` names
the Supabase Auth server; Supabase publishes authorization-server metadata
with PKCE and a dynamic client registration endpoint.

1. **The tool table**, from `app/mcp_mount.py` and `src/mcp_server.py`, one
   row per registered tool: name · title/description as published · args
   with types and defaults · read / write / SPEND · gated by (engine flag,
   operator-only, caller account) · what an OAuth caller sees today
   (registered? callable? refused with what message?). Include
   `imagine_reference` as SPEND and `generate_image` / `image_models` with a
   note on whether they are deployed (see "What is true today").
2. **Run `build_server` in a test harness** three ways and record which
   tools register in each: engine off; engine on; engine off with
   `CALLER_ACCOUNT` set to a non-bootstrap account. The existing tests show
   how to stand the server up without the `mcp` package's transport; copy
   their fixtures. Write the result into the table, not prose.
3. **Grade against the Phase 0 checklist**: every connector item PASS /
   FAIL / UNKNOWN with the file and line to change. Check specifically:
   - tool annotations (`readOnlyHint`, `destructiveHint`, `idempotentHint`,
     `openWorldHint`) — present on every tool and TRUE to what it does
     (`archive` is reversible: not destructive; `shoot` writes a label;
     `imagine_reference` spends);
   - titles and descriptions a stranger can act on (today's descriptions
     are written for Mike's agent — "the nightly", "the board", "brand" —
     and name internal concepts a directory user does not have);
   - JSON-schema quality: every arg typed, enums where the code has a
     vocabulary (`status`, `reason`, lanes), no bare `dict` returns without
     a described shape;
   - error shapes: a caller error is a `ToolError` with a message the agent
     can act on (CLAUDE.md: the SDK relays only a `ToolError`'s message);
     an id that does not exist, a wrong brand, an ungrounded concept must
     each say so, never "Error executing tool";
   - pagination and response size: `board`, `search`, `sparks`, `images_for`
     take `limit` — is there a cap, and what does a 400-concept board
     return? The directory reviewer will call `board` with no arguments;
   - the async job pattern (start → status → fetch): `research` and
     `generate` return a job id; `job` fetches it; is `job` registered
     when the engine is off, and what does a finished job's payload carry?
   - **no tool can spend without a quote and an explicit approval
     argument** — today `imagine_reference` spends on the call with no
     price shown first; `pick` returns the keyframe quote and spends
     nothing (2026-09-29). Grade `imagine_reference` FAIL on this item and
     carry it into Phase 3; do not fix it in Phase 4.

Write **`docs/directory/AUDIT.md`**: the tool table, the three registration
runs, the graded checklist. Commit: `docs(directory): audit of the live MCP
surface against the connector checklist`.

# Phase 2 — OAuth and tenancy end to end

1. **Token validation in the mount.** Read `mcp_auth.verify` and prove with
   tests, not reading: signature (JWKS and the HS256 secret path), issuer,
   audience / resource match, expiry. A token minted for another resource
   (`aud` = some other server) must be refused; an expired token must be
   refused; a token with the right `aud` but an unknown issuer must be
   refused. The existing `test_an_unverifiable_token_is_401_and_never_reaches_the_server`
   is the shape; add the three cases if they are missing.
2. **Provisioning and isolation.** Confirm what happens to a first-time
   OAuth caller (see "What is true today": 403, no `provision_personal`).
   Write it up as a finding with two options — call `provision_personal`
   from the mount the way `app/auth.py` does at web sign-in, or require one
   web sign-in first and say so in the connector's description — and
   recommend one; do NOT implement either without Mike's word, since it
   decides whether a stranger can create an account through the connector.
   Then write the isolation tests: user A and user B, both with their own
   account, through the real streamable-HTTP app the way
   `test_two_callers_through_the_real_transport_read_two_boards` does, and
   prove A cannot see B's `board`, `idea` (by B's concept id — must be "no
   concept N", never B's row), `sparks`, `images` / `reference` (B's
   finding id), `stats`, and credits (whatever tool reports a balance, or
   note that none does). Every tool that takes an id gets a cross-tenant
   case.
3. **The consent / authorization page.** Supabase's OAuth 2.1 server
   redirects to an authorization page this app or the studio must serve.
   Find the route (the studio under `web/`, or the API), check the Supabase
   config notes in `docs/RUNBOOK.md` and `.env.example`, and state whether
   it exists and what it shows. If it is missing, describe exactly what is
   needed (route, what it must display, what it posts back) — do not build
   it here.
4. **Rate limit per account on the mount.** There is none. Add one in
   `app/mcp_mount.guarded` (or a wrapper beside it): keyed on the resolved
   account id, a token bucket or fixed window, limits read from env with a
   sane default, 429 with `Retry-After`, in-process (the API is one
   machine; say so in a comment and in the report — a second machine means
   a shared store). The operator key is subject to it too, with a higher
   default. Tests: a caller over the limit gets 429; a different account
   is unaffected; the window resets.

Deliver **`docs/directory/OAUTH_TEST.md`**: a step-by-step manual script
Mike can follow with a SECOND account (he has `zp-billing-test`, account 5,
kept for exactly this kind of check — memory note) since you cannot sign in
as one: connect the server from claude.ai, what the consent page should
show, what `board` should answer for an empty account, what `idea` with one
of Mike's concept ids must answer, what the 429 looks like, and what to
screenshot for the submission. Each step says what PASS looks like.

Commit twice: the tests + rate limit as code (`feat(mcp): per-account rate
limit on the mount; cross-tenant and token tests`), the docs separately.

# Phase 3 — decide how an external user renders (PROPOSE, do not build)

Today `generate` is engine-gated and the graph ends parked in the Queue;
`imagine_reference` spends on the call; whatever the image tools turn out to
be (Phase 1) are gated the same way or not deployed. So an external
connector user cannot render a clip through chat at all, and can draw a still
without seeing a price.

Write **`docs/directory/RENDER_DESIGN.md`** with these options, each with
spend-exposure risk, work needed (files and tests, estimated), directory
review risk, and your recommendation:

- **A. Read-and-board only in v1.** Renders happen in the Studio Queue via a
  link the tool returns (`pick` already returns the keyframe quote and a
  "approve the draw in the studio" note — this is the shape). Hide or
  refuse `imagine_reference` for OAuth callers until it shows a price.
- **B. Quote-then-approve in chat** against the caller's own credit ledger:
  a `quote` tool returning `pricing.display()` + a signed token
  (`pricing.sign`, 1-hour TTL, `QUOTE_SIGNING_SECRET`), and an `approve`
  tool that takes the token, re-verifies it (the six refusals in
  `pricing.verify`), holds credit through `src/charge.py` BEFORE the submit,
  refuses above the quoted price, and runs the same `queue_approve` path the
  React Queue posts. Reuse, never a second price computation.
- **C. Both**, B behind a per-account flag in the `accounts` table (the
  `manual_lane_operator` / `credit_exempt` shape: a column, fails closed,
  `python -m src.accounts <flag> <slug> --on`).

Include the known exposure: **Create (Gemini, `/api/scenes/run`) and Nano
keyframes are not credit-gated for an account with a plan or balance** —
`charge.create_refusal` refuses only an account with neither (CLAUDE.md
"Beyond renders"), and `docs/tasks/task-meter-create-and-keyframes.md` is
the metering task. State what must be metered or capped before any tool
that triggers a Create or a keyframe is exposed to strangers, and which
tools those are (`generate`, `capture`? `imagine_reference`, the image
tools).

**STOP HERE. Commit the doc and wait for Mike's pick.** Phase 4 does not
depend on it; Phase 5's render-and-status skill does.

# Phase 4 — fix the connector gaps that need no decision

Only items Phase 1 graded FAIL that are unambiguous:

- tool annotations completed and truthful;
- titles and descriptions rewritten for a stranger (keep the operator's
  `ARCHIVE_DESCRIPTION` pattern: a constant beside the tool, tested);
- error shapes: every caller error a `ToolError` with a specific message;
- pagination caps on the listing tools, with the cap named in the
  description and a `next`/offset or "narrow your query" note when it is
  hit;
- the rate limit from Phase 2 if not already landed.

NOT in this phase: anything that changes which tools register, who can call
`imagine_reference`, provisioning on first contact, or any spend path.

Tests: extend `tests/test_mcp_mount.py` with a **registration test that
proves what an external (OAuth, non-operator) caller sees** — the exact tool
names, that engine tools are absent with the engine off, and that every
registered tool carries complete annotations. Extend `tests/test_mcp_server.py`
for the error shapes and caps. Ruff clean, suite green as CI runs it.

Commit: `fix(mcp): directory-ready annotations, descriptions, error shapes
and listing caps`.

# Phase 5 — the plugin bundle (new public folder `../zeropage-studio-plugin`)

Create it as a sibling of the main checkout (NOT inside this repo and NOT
inside the worktree folder), `git init` it, and follow the quickstart's
layout from Phase 0 exactly. Include:

- the plugin manifest; an MCP config pointing at the same connector URL
  (`https://zeropage-studio.fly.dev/mcp`); `LICENSE` (ask which — default
  to MIT and say so); `README.md` with install steps and a 60-second demo
  flow; a support contact (a `support@` address or the GitHub issues URL —
  confirm with Mike which); links to `https://zeropage.studio/privacy` and
  `https://zeropage.studio/terms` after fetching both and confirming 200.
- four skills, each under 300 lines, written fresh for a stranger, each
  description carrying an explicit **"NOT for:"** line:
  1. **concept-board** — turn a brief into a few story ideas the user
     approves BEFORE anything renders; at most 3 chip-style questions; uses
     `board` / `capture` / `pick` / `archive`.
  2. **look-matching** — set the visual look from a reference image or
     video; references by id only (`images`, `reference`, `images_for`);
     never pull a stranger's face off the web; say plainly that the studio
     grounds on photographs the user attached, never on a name.
  3. **render-and-status** — start a job, poll, fetch (`generate` / `job`
     or the Phase 3 shape); ALWAYS show the price and wait for the user's
     approval. Its shape depends on Mike's Phase 3 pick: write it against
     option A (link to the Queue) and leave a clearly marked block for B.
  4. **credits-and-limits** — show the balance, warn before anything
     expensive, explain what is free (board reads, captures, picks) and
     what is not (stills, renders), and the rate limit's shape.
- Run the plugin validator the checklist names (`claude plugin validate`
  or whatever Phase 0 found) and fix everything it flags. Paste its clean
  output into the README's "Validated" line with the date.

Before the first commit there, run the stranger check from ground rule 4
over every file: `grep -rn "iphone\|/Users/\|antihero\|ANTIHERO\|zp-\|Mike\|michael"` must find nothing.

Commit in that repo; do not push. Tell Mike the path.

# Phase 6 — the submission pack

Write **`docs/directory/SUBMISSION.md`** with every field the portal asks
for (from Phase 0's submission pages): names, short and long descriptions,
categories, the tool list with one line each, test-account instructions
for reviewers (which account, how it is provisioned, what it must NOT be
able to do — and the open question from Phase 2.2), privacy / terms /
support URLs, the screenshots needed (name each, say what it must show),
and what each tool does with user data (read, store, send to a model, send
to a provider). List separately **everything Mike must do by hand** at
`claude.ai/directory/manage`, in order.

## Deliverables

- This branch with one commit per phase (not pushed); the plugin folder
  beside the main checkout; `docs/directory/{REQUIREMENTS,AUDIT,OAUTH_TEST,
  RENDER_DESIGN,SUBMISSION}.md`.
- **A status report** (the final message, and the top of `SUBMISSION.md`):
  a table of every Phase 0 checklist item with PASS / FAIL / UNKNOWN, what
  changed in Phase 4, what needs Mike's decision (Phase 3; Phase 2.2
  provisioning; the license and support contact), and what needs a live
  check he must do (second-account sign-in per `OAUTH_TEST.md`, which
  commit Fly is running, whether the engine flag is set there).
- `claude/directory_listing_2026-10-07.md`: a short dated summary in the
  RUNBOOK entry voice — what was found, what landed, what is waiting on
  whom.
