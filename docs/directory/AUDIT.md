# Audit of the live MCP surface against the connector checklist

Phase 1 of `docs/tasks/task-directory-listing.md`, read off this tree
(`claude/directory-listing-tasks-5fa35e` at `209f7e9`, which is `main`'s tip
on 2026-10-07) and off the deployed server by unauthenticated HTTP only.
Item numbers are `REQUIREMENTS.md`'s.

## Which server is deployed

- `main` is `209f7e9`; a push to `main` is what deploys Fly, and this branch
  is byte-for-byte `main` in `src/mcp_server.py` and `app/mcp_mount.py`.
- The main checkout's working tree carries an UNCOMMITTED `src/mcp_server.py`
  with two more tools, `generate_image` and `image_models` (its newest commit
  `ca4be3f feat(web): landing-page components + design MCP servers` is on
  branch `feat/landing-components`, not on `main`). **Those two tools are not
  on `main` and so not deployed.** They are reachable from THIS Claude session
  only because the session's `zeropage` MCP server is the stdio one launched
  from the main checkout.
- `fly releases --app zeropage-studio` could not be run from this session
  (not logged in; Fly is read-only to the task anyway). The live server's
  `server:` header is Fly's proxy version, not the app's. **Mike confirms the
  release commit** — `SUBMISSION.md` lists it under live checks.
- Live, unauthenticated (2026-10-07 13:41 UTC):
  - `POST https://zeropage-studio.fly.dev/mcp/` → `401` with
    `WWW-Authenticate: Bearer resource_metadata="https://zeropage-studio.fly.dev/.well-known/oauth-protected-resource/mcp"`
    (C14 PASS).
  - `GET /.well-known/oauth-protected-resource/mcp` → `200`,
    `resource = https://zeropage-studio.fly.dev/mcp`,
    `authorization_servers = ["https://ewkbrenbjsiggufegrnd.supabase.co/auth/v1"]`,
    `resource_documentation = https://zeropage-studio.fly.dev/llms.txt` (C15 PASS).
  - Supabase's `/auth/v1/.well-known/oauth-authorization-server` → `200` with
    `registration_endpoint` (DCR on), `code_challenge_methods_supported =
    ["S256","plain"]`, `token_endpoint_auth_methods_supported` includes
    `none`, grant types `authorization_code` + `refresh_token`, no
    `client_id_metadata_document_supported` (so Claude will use DCR) (C16,
    C17, C18 PASS).
  - `https://zeropage.studio/privacy` and `/terms` → `200`.
- Whether `ZEROPAGE_MCP=1`, `ZEROPAGE_MCP_TOKEN` and `ZEROPAGE_MCP_ENGINE` are
  set on Fly cannot be read from here. The 401 proves the mount is on (it is
  refused entirely without a token). The engine flag is **UNKNOWN** — the
  only way to tell is a tools/list with a valid token, which is Mike's live
  check.

## 1. The tool table

From `src/mcp_server.py build_server` and `app/mcp_mount.py`, as the SDK
publishes them (`tools/list` from a `build_server(engine=True,
job_status=...)` harness; column "wire" is the exact argument schema).

Legend — **R** read, **W** write, **SPEND** spends credits or model money.
"OAuth caller" = a Supabase-token caller resolved to their own account
(`CALLER_ACCOUNT`). Every tool is registered for every caller; nothing is
hidden per caller.

| name | title | description (as published, trimmed) | wire args | kind | gated by | OAuth caller sees |
|---|---|---|---|---|---|---|
| `board` | none | "List concepts on the pre-production board. status is one of open, picked, archived, parked, shot, all. brand is antihero or zeropage." | `brand:str\|null=null, status:str="open", limit:int=25` | R | — | own account's rows (`_account`) |
| `idea` | none | "One concept in full, scene prompt included. `origin` says which door wrote it; `gate` is the graph's verdict ... `judge_*` is the Dev Studio's manual taste judge" | `idea_id:int` | R | — | own rows; another account's id → ToolError "no idea N" |
| `search` | none | "Find concepts whose title, hook, logline, spark or scene prompt contains this text." | `query:str, brand:str\|null=null, limit:int=25` | R | — | own rows |
| `capture` | none | "Put a new idea on the board. Saves an idea with no scene prompt; writing the scene is a separate step." | `brand:str, title:str, hook:str="", logline:str="", spark:str=""` | W | — | writes under own account (via `CALLER_ACCOUNT`); the Guide's explicit `account_id` is NOT passed (see F-9) |
| `pick` | none | "Mark a concept worth rendering. Spends nothing. ... `keyframes` in the result says how many stills that would be and what they cost." | `idea_id:int, picked:bool=true` | W | — | own rows; quote only, no spend |
| `shoot` | none | "Record that a concept actually got MADE -- by any means: the render lane, Higgsfield, the studio, a camera." | `idea_id:int, shot:bool=true` | W | — | own rows |
| `archive` | none | `ARCHIVE_DESCRIPTION` constant: "Take a concept off the board. Hides it; never deletes. `reason` is WHY ... One of: weak concept · no turn · no stake · off-brand · unshootable · seen it." | `idea_id:int, archived:bool=true, reason:str=""` | W (reversible) | — | own rows |
| `add_spark` | none | "Bank a one-line direction for the nightly run to generate from." | `brand:str, spark:str, rationale:str="", evidence:str=""` | W | — | **writes to the SHARED bank** (`scout_findings` is in `db.SHARED_TABLES`): every account reads it |
| `tonight` | none | "What direction tonight's scheduled run would take." | `brand:str` | R | — | **shared bank** — sees every account's sparks |
| `sparks` | none | "List banked sparks, highest-scoring first." | `brand:str\|null=null, unused_only:bool=true, limit:int=20` | R | — | **shared bank** |
| `images` | none | "The reference images the scout banked alongside a spark, each with the source URL it came from." | `finding_id:int` | R | — | **shared bin** (`scout_bin`); unknown id answers `count: 0`, not an error |
| `reference` | none | "Bank one reference image behind a spark ... Pass a `candidate_id` from `find_images` ... (`image_url` + `source_url` exist for a person dragging a photo onto the composer...)" | `finding_id:int, candidate_id:str="", image_url:str="", source_url:str="", title:str=""` | W, server-side fetch | — | **shared bin**; accepts a model-supplied URL (ground rule 5 FAIL, F-6) |
| `imagine_reference` | none | "Render ONE reference still for a spark from its hook frame -- and bank it behind the spark. ... Midjourney first, then Gemini's image model; the result says ... the `credits` it cost the caller" | `finding_id:int, hook_frame:str` | **W + SPEND** (a still, charged to the caller; exempt operator not charged) | `REFGEN_LANE`, `REFGEN_DAILY_CAP`; **not engine-gated** | charged on the call, **no price shown first**; also AI image generation (C12) |
| `images_for` | none | "Search for reference images and get back ids to bank. Describe the LIGHT and the SURFACES ..." | `query:str, brand:str="", limit:int=6` | R (outbound web search on the operator's keys) | — | shared candidates |
| `stats` | none | "Pick rate, shoot rate, and what is sitting on the board." | — | R | — | own rows; `sparks_unused` counts the shared bank |
| `research` | none | "Run a research pass: crawl the lanes, bank scored sparks, and download the reference images behind them. Spends a grounded search and one digest call." | `brand:str, count:int=4, lanes:list\|null=null` | **W + SPEND** (Gemini, on the operator's key; refused by `charge.create_refusal` for an account with no plan and no balance) | `ZEROPAGE_MCP_ENGINE=1` | registered only with the engine on; returns a job id; writes the **shared bank** |
| `generate` | none | "Run the LangGraph content graph on a spark: ground, generate, evaluate, score, keyframe, and park the scene in the Queue. Ends AT the spend gate, never through it." | `spark:str="", brand:str="", goal:str="", finding_id:int\|null=null` | **W + SPEND** (Gemini Create; keyframes only if `ZEROPAGE_KEYFRAME=1`, off in production posture) | engine flag; refuses outright while `ZEROPAGE_RENDER=1`; `create_refusal` | job id; the concept lands on the caller's own board |
| `job` | none | "Check a background job: one this server started, or one /ui started on the machine..." | `job_id:int` | R | registered whenever a job registry is injected (always on the mount, engine on or off) | own jobs only (`jobs.owned_by`); someone else's id → ToolError "no job N" |
| `elements` (added 2026-10-07) | List your elements (reference photos) | the account's characters/props/places with photo refs | — | R | listed | own rows |
| `write_scene` (added) | Save a scene prompt onto an idea | saves a chat-written prompt; refs only from `elements`; reference gate; model-free timeline split | `idea_id:int, prompt:str, seconds:int=10, refs:list[str]\|null` | W | listed | own rows |
| `quote` (added) | Price the keyframes and the clip | pricing.display + keyframe_quote + balance | `idea_id:int, provider?, model?, duration?, frame?` | R | listed | own rows |
| `approve` (added) | Approve a priced render (spends credits) | runs app/api's approve bodies | `idea_id:int, what:"keyframes"\|"clip"="clip", tokens:list[str]\|null, provider?, model?, duration?, frame?` | **W + SPEND**, destructiveHint | listed; registered only when the mount injects the bodies | own rows; holds credit before the submit |
| `generate_image` | — | — | — | SPEND | — | **not on `main`, not deployed** (see above) |
| `image_models` | — | — | — | R | — | **not on `main`, not deployed** |

Every published tool name is ≤ 17 characters (C4 PASS). No tool carries a
`title` (C3 FAIL). Annotations today are exactly two objects:
`{readOnlyHint: true}` and `{readOnlyHint: false, destructiveHint: false}`;
`idempotentHint` and `openWorldHint` are never set.

## 2. The three registration runs

`build_server(dsn=":memory:", ...)` → `list_tools()`, same harness as
`tests/test_mcp_server.py::_tools`:

| run | tools registered | count |
|---|---|---|
| engine off (`engine=False`, no job registry) | board, idea, search, capture, pick, shoot, archive, add_spark, tonight, sparks, images, reference, imagine_reference, images_for, stats | 15 |
| engine on (`engine=True`) | the 15 above + research, generate | 17 |
| engine off, `CALLER_ACCOUNT=7` (an OAuth caller) | **identical to engine off** — registration does not look at the caller | 15 |
| engine off + job registry (what the mount always injects) | the 15 + `job` | 16 |

So on the deployed mount an OAuth caller sees 16 tools with the engine off
and 18 with it on. `imagine_reference` (a spend) is in every set.

## 3. Graded checklist (connector items)

| # | item | grade | evidence / where to change |
|---|---|---|---|
| C1 | read and write split | PASS | one function per action; no `method` parameter anywhere |
| C2 | custom query tools name the API | PASS (n/a) | no freeform endpoint/query tool; `images_for` names its sources in the result's `sources` |
| C3 | `title` + applicable hint on every tool | **FAIL** | no tool has a `title` (`server.tool(title=...)` is never passed, `src/mcp_server.py:1012` onward). `destructiveHint` is set `false` on every write — true for archive (reversible), pick, shoot, capture, add_spark; **untrue for `imagine_reference`** (spends; cannot be undone) and `research`/`generate` (spend model money). `idempotentHint`/`openWorldHint` absent: `images_for`, `reference` (fetches a URL), `research` are open-world. Phase 4. |
| C4 | names ≤ 64 chars | PASS | longest is `imagine_reference` (17) |
| C5 | narrow, accurate descriptions a stranger can act on | **FAIL** | written for the operator's agent: "the nightly run", "the scheduled run", "the Dev Studio's manual taste judge", "antihero or zeropage", "Higgsfield", "the render lane", "`venv/bin/python -m src.shootgen --scene N`" (in `capture`'s result), "/ui started on the machine". A directory user has none of these. `shoot`'s description names Higgsfield, a lane removed 2026-09-29. Phase 4: a constant per tool beside `ARCHIVE_DESCRIPTION`, tested. |
| C6 | no prompt-injection patterns | PASS, with two edits | `imagine_reference` says "Do this BEFORE `images_for`, and then add one or two real photographs" and `images_for` says "Two or three searches beat one" — workflow steering inside a tool description, which a reviewer may read as telling Claude how to behave. Move that guidance to the plugin skill; keep descriptions to what the tool does. Phase 4. |
| C7 | valid input → success; no generic errors | PASS / UNKNOWN live | every tool returns a dict on valid input in tests; `_t` translates `ValueError`/`Refused` to `ToolError`. UNKNOWN: a Postgres outage inside `preprod.*` raises a bare exception → "Error executing tool", which the SDK does not explain. Acceptable (that is a server fault, not a caller error) but note for the reviewer. |
| C8 | validate inputs, actionable errors | PARTIAL | `status`, `brand`, lanes, empty `query`/`title`/`spark` are validated with the allowed list in the message. Gaps: `images(finding_id)` on an unknown id answers `{count: 0}` rather than "no finding N"; `imagine_reference` answers `{ok: false, note}` for an unknown finding (a note, by design, so an agent does not retry); `limit` is silently clamped to 1..100 rather than named. Phase 4: `images` says "no finding N"; the clamp is stated in the description. |
| C9 | response size | PASS | measured on a 400-concept board in a throwaway schema: `board` with no arguments → 25 cards, **7.6 KB**; `limit=100` (the cap) → 30 KB; `search` capped the same; `sparks` ≤ 100 rows; `images_for` ≤ 12; `idea` returns one concept's `shots` whole (a timed scene with parts, ~5–15 KB). Caps exist in code (`LIST_LIMIT=25`, max 100, `SEARCH_SCAN=500`) but **no description names them** and nothing says "narrow the query" when the cap is hit. Phase 4. |
| C10 | no conversation-data collection | PASS | tools take ids and short strings; nothing reads memory, history or files |
| C11 | first-party API | PASS | the server IS the product's API (`zeropage-studio.fly.dev`); `images_for` proxies Openverse/Google CSE/Reddit/Unsplash/Pexels with the operator's keys — declare it under Data handling as "APIs we proxy" |
| C12 | no AI image/video/audio generation | **FAIL (deployed) — the biggest finding** | `imagine_reference` renders a still through Midjourney/Nano Banana on the always-on list; `generate` draws keyframes when `ZEROPAGE_KEYFRAME=1`; the uncommitted `generate_image` would be the same. The checklist says such connectors "aren't accepted", and the Compliance step requires an "AI media generation" acknowledgment. Phase 3 (RENDER_DESIGN.md) is written around this: **option B as the task describes it (render in chat) cannot be listed**. |
| C13 | OAuth 2.0 | PASS | Supabase OAuth 2.1 server is the AS; DCR on |
| C14 | 401 with `resource_metadata` | PASS | live, see above |
| C15 | `resource` matches the URL exactly; first issuer | PASS | `https://zeropage-studio.fly.dev/mcp`, one issuer |
| C16 | AS metadata reachable | PASS (from here) | reachability from `160.79.104.0/21` is Mike's live check (no WAF is in front of Supabase) |
| C17 | DCR or CIMD | PASS (DCR) | note the doc's warning: DCR registers a new client on every fresh connection |
| C18 | PKCE S256 | PASS | advertised |
| C19 | scopes | PASS | the metadata deliberately publishes no `scopes_supported`; Claude then omits `scope` (`mcp_auth.protected_resource_metadata` docstring) |
| C20 | callback URLs | UNKNOWN | DCR means Claude registers `https://claude.ai/api/mcp/auth_callback` (and Claude Code its loopback) itself; whether Supabase's DCR accepts loopback redirects on any port is unverified. Live check. |
| C21 | consent screen shows the redirect host | **FAIL — no consent page exists** | see `OAUTH_TEST.md` §3 and Phase 2 finding F-3 |
| C22–C23 | token endpoint, latency | PASS (Supabase's) | nothing of ours is in that path |
| C24 | no tokens in URLs | PASS | `guarded` reads the `Authorization` header only |
| C25 | remote HTTPS | PASS | |
| C26 | tested in Claude + Inspector | UNKNOWN | Mike's live check with the second account (`OAUTH_TEST.md`) |
| C27 | listing materials | PARTIAL | privacy + terms live; documentation URL = `/llms.txt` exists but describes the whole product, not the connector; icon: none prepared; support contact: `mikemassaad@gmail.com` is what the legal pages name — decision needed |
| C28 | test account | PARTIAL | `zp-billing-test` (account 5) exists; it needs populating and the open question F-2 answered before a reviewer can connect |
| C29 | public documentation by publish date | UNKNOWN | the plugin README (Phase 5) can serve; a page under `zeropage.studio` would be better |
| C30–C35 | portal steps | — | drafted in `SUBMISSION.md` |
| C36–C38 | links, carousel, local privacy | n/a | |
| C39 | no `clientInfo` gating | PASS | nothing reads it |
| — | rate limit per account | **FAIL** | none: `grep -n "rate\|limit" app/mcp_mount.py` finds prose only. Phase 2.4 adds one. |
| — | async job pattern | PASS | `research`/`generate` return `{job_id, status, label, note}`; `job` is registered whenever the mount injects the registry (engine on or off), returns the registry snapshot (`status`, `label`, `detail`, `result`, `error`, timestamps), and refuses another account's job as "no job N". The registry is in-process: a deploy mid-job loses it, and the description says so. |
| — | no spend without a quote and explicit approval | **FAIL for `imagine_reference`** | spends on the call; `pick` is the right shape (quote, "approve in the studio"). Carried to Phase 3, not fixed in Phase 4. |

## Findings carried forward (numbered for Phase 2/3 and the report)

- **F-1 AI media generation is not listable (C12).** Any tool that draws
  (`imagine_reference`, `generate` with keyframes on, the unmerged
  `generate_image`) has to be off the connector a stranger reaches, or the
  listing is refused on policy. The pre-2026-09-29 docstring at the top of
  `src/mcp_server.py` ("Nothing here spends money. No render, no keyframe ...
  no model call of any kind") is the posture the directory wants and the
  module has since drifted from it.
- **F-2 First contact through the connector is a 403.** `guarded` →
  `account_for_token` → `accounts.memberships` empty → `no_account` → 403
  "ask to be invited". The web sign-in calls `accounts.provision_personal`
  (`app/auth.py:635`); the mount never does. Phase 2 writes the options.
- **F-3 No consent page.** Supabase redirects to `<Site URL><Authorization
  Path>?authorization_id=…`; nothing in `app/` or `web/` handles it.
- **F-4 The sparks bank and the reference bin are SHARED across accounts by
  design** (`db.SHARED_TABLES`: "a direction is not anyone's row", "keyed by
  pass, not by person"). `sparks`, `tonight`, `add_spark`, `images`,
  `reference`, `imagine_reference` and `research` therefore read and write
  one pool for every tenant. Correct for one operator, a cross-tenant
  exposure for strangers: user A's typed directions and banked images are
  listed to user B. **Resolved 2026-10-07 (Mike's call): the bank stays off
  the listed server.** `mcp_server.LISTED_TOOLS` is what a signed-in caller
  is offered through the mount (two servers, routed by door in
  `app/mcp_mount.guarded`); the operator's static key and stdio keep the
  full set. The transport test proves `sparks` is an unknown tool to a
  signed-in caller.
- **F-5 No rate limit** (Phase 2.4 builds one).
- **F-6 `reference` accepts a model-supplied URL** (`image_url`,
  `source_url`); ground rule 5 says the MCP surface must refuse URL-shaped
  arguments the way `guide_tools.check_args` does. `_reachable()` also HEADs
  an arbitrary `source_url` with no `public_host` guard. A change to what the
  operator's own agent may pass, so it is a decision, not a Phase 4 edit.
- **F-7 Descriptions and titles** (C3, C5, C6, C9) — Phase 4.
- **F-8 `images(unknown id)` is silent** (C8) — Phase 4.
- **F-9 `capture`/`pick`/`shoot`/`archive` ignore `build_server(account_id=)`.**
  They call `_t(fn, ..., dsn=dsn)` without `account_id=account_id`, so the
  Guide's in-process server (`guide_tools.py:180`, which passes an explicit
  account) would write those four under `CALLER_ACCOUNT`/bootstrap instead.
  OAuth callers are unaffected (`CALLER_ACCOUNT` is what they use). Phase 4
  passes the explicit account through, which only narrows what a call can
  reach.
- **F-10 Which commit Fly runs and whether the engine flag is set there** are
  live checks for Mike.
