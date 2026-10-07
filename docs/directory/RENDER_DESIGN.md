# How an external connector user renders — a proposal, not a build

Phase 3 of `docs/tasks/task-directory-listing.md`. **Nothing here is
implemented.** Mike picks; Phase 5's render-and-status skill is written
against option A with a marked block for the alternative.

## The fact that reframes the question

The connector checklist (`REQUIREMENTS.md` C12, quoted from
https://claude.com/docs/connectors/building/review-criteria) lists, under
"Unsupported use cases":

> Connectors that do the following aren't accepted: ... Generate images,
> video, or audio through AI models

and the submission form's Compliance step carries a matching "AI media
generation" acknowledgment, one of seven that are all required.

Everything this studio makes is an AI-generated still or clip. So the
question the task asks — "how does an external user render through chat" —
has a policy answer before it has a design answer: **a tool that renders
cannot be on the listed connector.** A `quote` + `approve` pair that holds
credit and submits to fal is exactly "generate video through AI models",
whoever presses it. The same applies to `imagine_reference` (a still via
Midjourney/Nano Banana), `generate` with keyframes on, and the unmerged
`generate_image`.

What the directory DOES accept is a connector that reads and decides, and
hands the person a link into the product where the spend happens. That is
the shape `pick` already has since 2026-09-29 ("not drawn -- approve 'Draw
keyframes' on the Queue card in the studio"), and it is the shape the
whole spend design wants anyway: the quote, the signed token, the ledger
hold and the approve are already in the React Queue and `queue_approve`.

## What today's surface exposes (the spend map)

| tool | what it spends | whose money | gate in front of it today |
|---|---|---|---|
| `imagine_reference` | one still (Midjourney, else Nano Banana) | the caller's credits (`charge.Charge` hold → settle); an exempt operator pays nothing | `REFGEN_LANE` (on by default), `REFGEN_DAILY_CAP` (8/day, global, not per account). **No price shown first; spends on the call.** Always registered. |
| `research` | Gemini (grounded search + one digest), image fetches | the operator's `GEMINI_API_KEY`; the caller is refused only if they have no plan AND no balance (`charge.create_refusal`), otherwise **free to the caller** — the metering task decided a Create is "in the plan" | `ZEROPAGE_MCP_ENGINE=1` |
| `generate` | a Create (Gemini: ground, write, judge, timeline), keyframes only when `ZEROPAGE_KEYFRAME=1` (off in the production posture) | the operator's key; same `create_refusal` rule | engine flag; refuses while `ZEROPAGE_RENDER=1` |
| `pick` | nothing (quotes the keyframe strip) | — | — |
| `images_for` | web image search on the operator's keys (Openverse free; Google CSE/Unsplash/Pexels metered by the vendor) | the operator | none; `limit` ≤ 12 |
| `reference` | one server-side fetch of an image | nothing billed | none |
| everything else | nothing | — | — |

**The known exposure the task names, stated plainly:** `charge.create_refusal`
refuses a Create only to an account with no plan and no balance
(`docs/tasks/task-meter-create-and-keyframes.md` §0, decision 2: "0 credits
per Create — included in the subscription"). So for any account holding a
plan or even the 100-credit trial, `generate` and `research` run on Mike's
Gemini key at no charge to the caller, bounded only by the daily Gemini
budget the Stripe task's phase 4 was to add per account — which the
metering task lists as the wall for the Guide/Direct/Polish and which I did
not find implemented for the MCP engine tools (`_create_gate` asks
`create_refusal` and nothing else). Keyframes are off (`ZEROPAGE_KEYFRAME=0`
posture) so `generate` draws nothing; `imagine_reference` is the one tool
that charges the caller per call, and it does so with no quote.

**What must be metered or capped before any of these reaches a stranger:**

- `generate` / `research`: a per-account daily cap on Creates (count of
  `llm_calls` rows by `account_id` and stage per day — the meter already
  writes both), refusing with a named reason, before the engine flag is ever
  set on a listed server. Today a trial account could run the graph in a
  loop on Mike's key until the new rate limit (120 req/min) is the only
  wall — and a graph run is one request.
- `imagine_reference`: a quote first (the still's credits, `refgen.hold_usd()`
  through `pricing`'s markup) and an explicit approve argument carrying a
  signed token — or, under the policy above, simply not on the listed server.
- `images_for`: a per-account daily count, since the paid lanes bill the
  operator per query.
- `capture`: free (a row), no change.

## Options

### A. Read-and-board only in v1 (recommended)

The listed connector registers the read/decide set — `board`, `idea`,
`search`, `capture`, `pick`, `shoot`, `archive`, `stats`, `job` — and the
sparks/images tools only if the bank is fenced per account (OAUTH_TEST.md
Finding 2); otherwise they stay off too. A pick returns the keyframe quote
and a deep link to the Queue card
(`{STUDIO_URL}/studio/queue?concept={id}`), where "Draw keyframes · N cr"
and the render approve already show a price and hold credit. Every spend
stays behind a surface we draw, with a price on it.

- **Spend exposure**: none through the connector. The only money path is
  the Queue, unchanged.
- **Directory review risk**: lowest. No AI-generation tool to explain; every
  tool is a read or a reversible write; the "AI media generation"
  acknowledgment is answered honestly because the connector does none.
- **Work**: `build_server` gains a `listed: bool` (or `public=True`) mode
  that registers the read/decide set only — one conditional around the
  spending registrations, the way the engine flag already works; the mount
  passes it for OAuth callers (registration is per server, not per request,
  so this is one server built with the public set, selected in `guarded`
  by which door the caller came through, or simpler: the mount always
  builds the public set and the operator's agents keep using stdio, which
  already has everything). `pick` returns the Queue link. Tests: the Phase 4
  registration test asserts the exact public set. ~60 lines + tests, half a
  day. The sparks fence (if wanted) is a separate day: two `account_id`
  columns, the owned-table guard, a backfill.
- **Cost**: a person who wants a render leaves the chat for one click. That
  is the product's existing posture ("approving in Queue is what calls the
  renderer") and the skill says so up front.

### B. Quote-then-approve in chat

A `quote` tool returning `pricing.display()` for the shot plus the signed
token (`pricing.sign`, 1-hour TTL, `QUOTE_SIGNING_SECRET`), and an `approve`
tool taking the token, re-verifying it (the six refusals in
`pricing.verify`: bad_signature / retired_pricing / expired / wrong_account /
wrong_render / stale_content), holding credit through `src/charge.py` BEFORE
the submit, refusing above the quoted price, and running the same
`queue_approve` path the React Queue posts — one price computation,
reused, never a second.

- **Spend exposure**: the caller's own ledger, bounded by the quote and the
  hold. Technically the same guarantees as the Queue. But the approval is a
  tool argument the model fills in: the human's "yes" is a sentence in chat
  that Claude turns into `approve(token=...)`. Claude's own permission
  prompt on a destructive tool (`destructiveHint: true`) is the real click.
- **Directory review risk**: **high to certain.** This is "generate video
  through AI models" by the checklist's wording. Submitting it means either
  answering the Compliance acknowledgment untruthfully or being refused.
- **Work**: `src/mcp_server.py` two tools (~120 lines) + `app/api.py`'s
  approve body shared as a function the tool can call without a Request
  (today `queue_approve` is a route with `Depends`; the render body would
  need lifting into `src/` or a thin app-layer callable injected like
  `start_job`), the job registry for the render, tests for the six
  refusals through the tool, the content-hash check against the live
  shot. Two to three days.
- **Where it IS right**: as an operator-only tool on the stdio server, or
  behind the static token — Mike's own agents rendering from a phone. That
  is not a directory question.

### C. Both, B behind a per-account column

`accounts.chat_render` (the `manual_lane_operator` / `credit_exempt` shape:
a column, fails closed, `python -m src.accounts chat-render <slug> --on`),
with `quote`/`approve` registered for everyone but refusing for accounts
without the flag.

- **Spend exposure**: as B for flagged accounts, none for the rest.
- **Directory review risk**: the tools are still REGISTERED and visible in
  the portal's Tools step; a reviewer sees `approve` described as rendering
  a clip. Refusing by flag does not change what the listing claims to do.
  Same risk as B.
- **Work**: B plus a column, a CLI verb and a gate test. Three days.

## Recommendation

**A for the listing, and the operator keeps B's shape where it already
exists: the Queue.** Concretely:

1. Build the public registration set (A). Decide the sparks fence
   separately; until it lands, the sparks/images tools stay off the listed
   server.
2. `imagine_reference` leaves the listed server regardless (policy, and it
   spends without a quote). On the operator's stdio server it stays as it
   is — Mike's own credits, Mike's own agent.
3. Before `ZEROPAGE_MCP_ENGINE=1` is ever set on Fly: the per-account daily
   Create cap above. Not for the listing — the engine tools are not on it —
   but because the flag is global and the mount serves strangers.
4. If chat rendering is wanted for Mike's own use, build B as an
   operator-only tool on stdio, where the directory's rules do not reach,
   and keep it off the mount.

What A gives up is small (one click in the studio instead of a sentence in
chat) and what it keeps is the one rule the whole project has guarded since
August: the only place money is spent is a priced approve a person presses
on a surface we draw.

**STOP. Phase 4 does not depend on this. Phase 5's render-and-status skill
is written against A with a marked block for B.**
