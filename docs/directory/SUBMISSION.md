# The submission pack

Phase 6 of `docs/tasks/task-directory-listing.md`, 2026-10-07. Item numbers
are `REQUIREMENTS.md`'s; grades are `AUDIT.md`'s, updated for what Phase 4
landed on this branch (not yet deployed — a push to `main` deploys Fly).

## Status report

### Connector items

| # | item | status | note |
|---|---|---|---|
| C1 | read/write split | PASS | |
| C2 | custom query tools name the API | PASS (n/a) | |
| C3 | title + hints on every tool | **PASS after Phase 4** (was FAIL) | `TITLES` / `HINTS` constants, pinned by test |
| C4 | names ≤ 64 | PASS | |
| C5 | narrow, accurate descriptions | **PASS after Phase 4** (was FAIL) | `DESCRIPTIONS`, operator vocabulary screened |
| C6 | no prompt-injection patterns | PASS after Phase 4 | workflow steering moved into the plugin's skills |
| C7 | valid input → success, no generic errors | PASS | a database outage still surfaces as the SDK's generic text; that is a server fault |
| C8 | validate inputs, actionable errors | PASS after Phase 4 | `images` on an unknown id now errors; caps named |
| C9 | response size | PASS after Phase 4 | 7.6 KB default board; `truncated` + note at the cap |
| C10 | no conversation-data collection | PASS | |
| C11 | first-party API | PASS | declare the image-search lanes as proxied APIs |
| C12 | no AI image/video/audio generation | **FAIL — open review risk** | Built as Mike chose: `approve` renders stills and clips after a quote and a yes in chat. The checklist says such connectors "aren't accepted"; the Compliance step asks for the acknowledgment. Answer it truthfully; if refused, drop `approve` from LISTED_TOOLS (one line) and the Queue is the approve |
| C13–C19 | OAuth, 401, metadata, AS metadata, DCR, PKCE, scopes | PASS | verified live from here 2026-10-07 |
| C20 | callback URLs (incl. Claude Code loopback) | **PASS live 2026-10-08** | a Claude Code-shaped client registered `http://localhost:<port>/callback` through DCR (201) and completed the code flow (OAUTH_TEST.md, live results) |
| C21 | consent screen | **PASS live 2026-10-08**, one open warning | shown and approved live; Chrome's lookalike interstitial on `zeropage-studio.fly.dev` until the Site URL moves to `https://api.zeropage.studio` (OAUTH_TEST.md Finding 4) |
| C22–C24 | token endpoint, latency, no tokens in URLs | PASS | |
| C25 | remote HTTPS | PASS | |
| C26 | tested in Claude + Inspector | PARTIAL | claude.ai on Mike's account and a second account through a local OAuth client, 2026-10-08; Inspector not run |
| C27 | listing materials | PARTIAL | privacy/terms live; docs URL and icon: see "By hand" |
| C28 | test account | **OPEN** | `zp-billing-test` (account 5) has NO members, so nobody can sign in as it; the reviewer needs an account with a sign-in (OAUTH_TEST.md, live results) |
| C29 | public documentation | PARTIAL | the plugin README once the repo is public; a `zeropage.studio/connector` page would be better |
| C39 | no clientInfo gating | PASS | |
| — | rate limit | **PASS live 2026-10-08** | 120/min per account, 1200/min operator key; 429 + Retry-After; a deploy mid-window resets the in-process count |
| — | token: audience, expiry, issuer | PASS after Phase 2 | issuer check added |
| — | cross-tenant isolation (board, idea, search, capture, pick, archive, shoot, job, stats, projects, project, project_chat, create_project, save_chat) | **PASS live 2026-10-08** for the first nine with a second account; all of them through the real transport in tests | the project tools arrived after the walk; `stats` no longer reports the shared bank's size to a signed-in caller (Finding 6) |
| — | cross-tenant: sparks / images bank | **PASS** -- not on the listed server | Mike's call 2026-10-07; the operator's door keeps them |
| — | spend without a quote + approval | **PASS on the listed server** | `quote` then `approve` (tokens, hold before submit); `imagine_reference` is not on the listed server |

### Plugin items

| # | item | status |
|---|---|---|
| P1–P2 | layout and manifest | PASS — `.claude-plugin/plugin.json`, `.mcp.json`, `README.md`, `LICENSE`, four `skills/*/SKILL.md` |
| P3–P5 | name, writing system, version | PASS — `zeropage-studio`, 0.1.0 |
| P6 | README ≥ 40 words | PASS (661 words outside code) |
| P7 | license | PASS — MIT (Mike's pick), file and field |
| P8–P12 | system files, names, size, text only, no symlinks | PASS — `.gitignore` carries the four; 8 files, all text |
| P13–P16 | `.mcp.json`, same URL, no secrets, no launchers | PASS |
| P17–P21 | skills | PASS — each under 100 lines, frontmatter `name` + `description` with a "NOT for" line |
| P22 | `claude plugin validate` | PASS — `✔ Validation passed`, 2026-10-07, Claude Code 2.1.285 |
| P23 | loaded on each surface | UNKNOWN — Mike: `claude --plugin-dir ./zeropage-studio-plugin`, then the zip upload on claude.ai |
| P24 | GitHub repo, public before going live | PASS — https://github.com/zeropage-onryo/zeropage-studio-plugin, public |
| P25–P28 | portal steps | drafted below |

### What changed in Phase 4 (on this branch, not deployed)

- Every tool has a title, `readOnlyHint`, `destructiveHint`, `idempotentHint`,
  `openWorldHint`, true to what it does.
- Descriptions rewritten for a stranger, as constants, with a vocabulary
  screen in the tests. The server's `instructions` too.
- `status`, `brand`, `lanes` published as enums; `brand` defaults so a
  stranger never has to type it.
- `board` / `search` name their cap and answer `truncated` with a note.
- `images` on an unknown direction errors instead of answering an empty list.
- `capture`'s hint no longer prints a shell command.
- `capture` / `pick` / `shoot` / `archive` honour the explicit account the
  Guide builds its server for (F-9).

### What needs Mike's decision (answered 2026-10-07 unless marked open)

- Render path: **B, built** — `elements` / `write_scene` / `quote` / `approve`
  on the listed server; Claude writes the scene in chat (no model credit),
  the studio renders after a quote and a yes. The listed set is
  `mcp_server.LISTED_TOOLS`; the spark bank and the engine tools stay on the
  operator's door (Mike's call).
- First contact: **require one web sign-in**; the 403 body and the connector
  description should say so (one string in `app/mcp_mount.py`, not yet changed).
- License: **MIT**. Support: **GitHub issues on the plugin repo**.
- Sparks bank: **off the listed server** (decided). `reference`'s URL
  argument (AUDIT.md F-6) and the Create cap now concern the operator's door
  only; neither is reachable by a stranger.

### Live checks only Mike can do

- `fly releases --app zeropage-studio`: which commit is live; whether
  `ZEROPAGE_MCP_ENGINE` is set there (inferred from the tool list).
- ~~The second-account script, `OAUTH_TEST.md`, steps 0–11.~~ **Walked
  2026-10-08** (step 10 skipped); results and Findings 4–7 in `OAUTH_TEST.md`.
- Reachability of `ewkbrenbjsiggufegrnd.supabase.co` from Anthropic's egress
  range (no WAF is in front of it, so expected PASS).

## The portal fields (MCP connector)

**Connection** — `https://zeropage-studio.fly.dev/mcp`, Universal URL.

**Tools** — sync from the server; a signed-in reviewer sees the listed set,
every tool with a title and hints. Read-only: board, idea, search, stats,
projects, project, project_chat, elements, quote, job. Write: capture, pick,
shoot, archive, create_project, save_chat, write_scene, approve
(destructive: it spends).

**Listing**

- Name (≤100): `Zero Page Studio`
- One-liner (≤200): `Your AI pre-production board: turn a brief into story ideas you approve, set the look from reference images you attach, and render with the price shown first.`
- Description (≤2,000), draft:

  > Zero Page Studio is an AI pre-production studio for creators and
  > filmmakers. From a conversation, read the ideas on your board, capture new
  > ones from a brief, pick the ones worth making and archive the rest with a
  > reason the studio learns from. Set a scene's look from reference images —
  > the studio grounds on photographs you attach, never on a name — and see
  > which references sit behind a direction, each with the page it came from.
  > Writing a scene, drawing its keyframes and rendering the clip cost
  > credits from your own balance, and the price is shown and approved before
  > anything is spent. Reads and decisions are free. Sign in once at
  > zeropage.studio to create your workspace, then connect.

- Categories (1–5): Creative & Design; Productivity; Marketing (pick what the
  portal offers closest to video / creative).
- Documentation URL: the plugin README on GitHub once public
  (`https://github.com/zeropage-onryo/zeropage-studio-plugin#readme`), or a
  page at `https://zeropage.studio/connector` if written.
- Privacy policy URL: `https://zeropage.studio/privacy` (200 on 2026-10-07).
- Terms: `https://zeropage.studio/terms` (200).
- Support contact: `https://github.com/zeropage-onryo/zeropage-studio-plugin/issues`.
- Icon: none prepared — a square PNG of the red dot mark from the studio header.
- Slug: `zeropage-studio` (permanent).

**Use cases** — "Decide between story ideas for a short or an ad from a
brief"; "Set the visual look of a scene from reference images"; "Price and
approve a render without leaving the chat". Users need: a Zero Page Studio
account (free sign-in; trial credits; a plan or credits for renders). Reads
and writes data: both.

**Company** — Zero Page Studio, `https://zeropage.studio`, primary contact:
Mike's email for review updates (not shown publicly).

**Authentication** — OAuth with dynamic client registration (Supabase OAuth
2.1 server, PKCE S256). No lazy auth: every tool needs the account.

**Data handling** — the API is our own; `images_for` proxies open image
sources (Openverse, and Google Programmable Search / Unsplash / Pexels when
keyed) with our own keys. No personal health data. No sponsored content.

**Test & launch** — reviewer instructions:

1. Account: `zp-billing-test` (account 5) — a real workspace, kept for billing
   checks. **It has no members (2026-10-08), so as written nobody can sign
   in to it**: invite the reviewer's address to it (`src.accounts invite`),
   or hand over a fresh sign-up's workspace instead. Mike populates it before submitting: three to five captured ideas,
   one picked, one with a written scene and two reference images, a small
   credit balance so `pick` returns a keyframe quote and `imagine_reference`
   can be refused or charged as the reviewer chooses. Credentials (the
   Supabase email + password for that user) go in the portal field only.
2. Steps: sign in once at https://zeropage.studio with those credentials
   (workspace exists already); add the connector; approve the consent page;
   call `board`, `idea`, `search`, `capture`, `pick`, `archive`, `stats`,
   `create_project`, `projects`, `project`, `save_chat`, `project_chat`,
   `elements`, `write_scene`, `quote`, `approve` (keyframes, then clip, with
   a balance that covers one small render), `job`.
3. What it must NOT be able to do: read any other account's ideas (every
   id outside its board answers "no idea N"); buy credits or change a plan
   (not possible through the connector); post anywhere; delete anything.
4. The open question the reviewer may hit: a brand-new sign-up through the
   connector gets "no account" until they sign in once on the web (Mike's
   decision; the description says so).
5. Confirm "tested every tool in Claude and Inspector" only after
   `OAUTH_TEST.md` is walked.

**Compliance** — seven acknowledgments. The "AI media generation" one is the
open risk (C12); answer truthfully.

### Screenshots (for the review note and the README; none required for a
non-App connector)

- `consent-page.png` — the consent page naming Claude and the redirect host
  (once built).
- `tool-list.png` — the connector's Tool permissions list with titles.
- `empty-board.png` — `board` for the test account before population.
- `cross-tenant-refused.png` — `idea 375` as the test account → "no idea 375".
- `rate-limit-429.png` — the 429 body with Retry-After.
- `shared-sparks.png` — the Finding 2 evidence (decision support, not for
  the listing).

### What each tool does with user data

| tool | reads | stores | sends to a model | sends to a provider |
|---|---|---|---|---|
| board, idea, search, stats, elements, quote, job | the caller's rows | — | — | — |
| projects, project, project_chat | the caller's projects: brief, look, scenes, the reference images they used, renders, chat history | — | — | — |
| capture, pick, shoot, archive, write_scene | — | a row under the caller's account (the scene prompt and the photo refs chosen) | — | — |
| create_project, save_chat | — | a project, or chat turns Claude passes (the conversation's text), under the caller's account; kept until the person deletes the project in the studio | — | — |
| approve (keyframes) | — | the stills under the caller's renders; a ledger charge | the scene prompt and the attached photos, to the studio's image model | Google's image model (Nano Banana) |
| approve (clip) | — | the clip under the caller's renders; a ledger charge | the shot prompt, its still and the attached photos, to the renderer | fal.ai (the model quoted) |

Not on the listed server (operator's door only): sparks, tonight, add_spark, images, reference, images_for, imagine_reference, research, generate.

## The portal fields (plugin bundle)

- Repository: `zeropage-onryo/zeropage-studio-plugin` (to be created and
  pushed; public before publishing). Plugin path: root. Branch: `main`.
- Validate → listing details come from `plugin.json` and the README.
- Data handling: reads personal data — only the account's own board text;
  sends data to services other than the declared connector — no; retention —
  the studio's (privacy policy); for people under 18 — no.
- Compliance: contact email; four acknowledgments.
- Review and submit: GitHub push webhook (needs repo admin).

## Everything Mike must do by hand, in order

1. **Merge the PR** once CI is green (built 2026-10-07: the consent page is
   in it). A push to `main` deploys Fly.
2. **Push this branch and open the PR** (nothing is pushed). Merging to
   `main` deploys Fly with Phase 4 and the rate limit.
3. **Supabase dashboard** (Authentication → OAuth Server): set the
   Authorization Path to `/oauth/consent` (done 2026-10-07). The Site URL is
   the API origin, and should be `https://api.zeropage.studio` -- the same
   Fly app -- rather than `zeropage-studio.fly.dev`, which Chrome flags as a
   lookalike on the consent page (`OAUTH_TEST.md` Finding 4 has the command).
4. **Fly**: `fly releases` to confirm the live commit. `QUOTE_SIGNING_SECRET`
   is already set there, so `quote` will carry tokens. Optionally set
   `ZEROPAGE_MCP_RATE` / `ZEROPAGE_MCP_RATE_OPERATOR` (defaults 120 / 1200
   per minute) and `ZEROPAGE_SIGNUP_URL` (default https://zeropage.studio).
5. ~~**Walk `OAUTH_TEST.md`**~~ walked 2026-10-08 with a fresh sign-up
   (account 5 cannot sign in); the claude.ai screenshots are still to take.
6. **Populate the test account** as the reviewer instructions describe; put
   its credentials in the portal only.
7. ~~Create the GitHub repo~~ **Done 2026-10-07:**
   https://github.com/zeropage-onryo/zeropage-studio-plugin, public, `main`,
   Issues on (the support contact), MIT detected by GitHub. Commits are
   authored as Zero Page Studio <noreply@zeropage.studio>.
8. **Icon**: a square PNG.
9. **Portal, connector**: claude.ai/directory/manage → Submit new → MCP
   connector → fill the fields above → Test & launch → Compliance → submit.
10. **Portal, plugin**: Submit new → Plugin bundle → repository → Validate →
    Data handling → Compliance → submit; set up the push webhook.
11. **Pair** the two listings once both exist.
12. After publishing: watch the connector dashboard; `directory@anthropic.com`
    / `mcp-review@anthropic.com` for a stuck submission.
