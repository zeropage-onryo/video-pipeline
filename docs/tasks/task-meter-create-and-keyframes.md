# Task: charge Create (Gemini) and Nano keyframes through the credit ledger

**Status: DECIDED (Mike, 2026-09-29 — section 0). Not built yet.**
Written 2026-09-28. Follows `task-fal-only.md` ("Still Mike's call": metering
Create and Nano keyframes) and phase 4 of `task-stripe-billing.md`.

**Why now:** every video render holds credit (`src/charge.py`), but the two
things a new account does FIRST — Create a scene, pick it (which draws its
keyframes) — run on the operator's `GEMINI_API_KEY` with nothing in front of
them except `NANO_DAILY_CAP`. Open sign-up must not go live until a stranger's
Create costs the stranger, not Mike.

---

## 0. Decisions (Mike, 2026-09-29) — these override the proposals below

| # | question | decision |
|---|---|---|
| 1 | flat or metered | **Flat per action.** |
| 2 | what a Create costs | **0 credits per Create — included in the subscription, and its cost is priced INTO the plan, not absorbed.** See "Create is in the plan" below. |
| 3 | creative guide, Direct, Polish | **Free** (per-account daily Gemini budget is their wall — phase 4 of the Stripe task). |
| 4 | scout / research / nightly | MCP `research` / `generate` from a non-exempt account **hold like a Create**; the nightly walk stays operator-only and uncharged. |
| 5 | balance runs out | **Refuse**, with "top up credits" and the link to buy. Never a partial keyframe strip. |
| 6 | `NANO_DAILY_CAP` | **Removed for everyone** (exempt accounts included). The credit balance is the limit for paying and trial accounts. |
| 7 | element reference sheets | **Do what InVideo does:** a character/element sheet is an ordinary image generation, charged image credits like any other image — no free sheet, no separate fee. Priced at the Pro still (the sheet is drawn on Nano Banana Pro), shown on the "draw a reference sheet" toggle before the element is saved. |
| 8 | keyframes | **Charged, behind an APPROVE step.** A pick no longer draws its stills automatically: the card shows `Draw keyframes · N stills · X cr` and nothing is spent until that is pressed — the same shape as the Queue's render approve. Same for the Director's Nano node and `/api/generate/run`'s image branch. |
| 9 | new sign-ups | **One-time trial grant of 100 credits** (InVideo's shape: no card, try it, then subscribe or buy credits). After it is spent: refuse with "subscribe or top up". |
| 10 | Higgsfield | **Remove it entirely**, the Soul still path too. `refgen` and `scene_chain`'s visual targets move to Nano (charged like any keyframe). |

**Create is in the plan (decision 2).** No per-Create debit; the cost sits inside the
subscription price. Checked against today's plans (`pricing.PLANS`, credits sold at
2.4x provider cost): a Starter plan ($15, 1,500 credits) spent entirely on renders costs
$6.25 at the provider, leaving $8.75 — which covers ~580 Creates a month at ~$0.015 each
before the plan loses money. Creator and Studio scale the same way. So no price change
is needed now; the number to watch is Creates per account per month against that
headroom (`llm_calls`, stage `concepts` + `timeline`, grouped by account).
**Who may Create:** an account with an active plan, or with any credit balance (the trial
grant counts). An account with neither is refused with "subscribe or top up" — Create
is free per click, not free forever to an account that has never paid or trialled.

**What this changes from the proposal below:** no Create hold (section 3's Create
price is dropped); the pick's automatic keyframe draw becomes an approve step (changes
`scene_chain.draw_on_pick` and MCP `pick`, which today spend on pick); the Nano cap
goes rather than being raised; Higgsfield goes.

---

## 1. What these actually cost (live `llm_calls`, last 30 days, read 2026-09-28)

| what | calls | provider cost | x2.4 | credits (`ledger.charge_credits`, floor 10) |
|---|---|---|---|---|
| Studio Create: `concepts` (one scene) | 1 | avg $0.0085, max $0.013 | $0.020 | **10** (floor) |
| + `timeline` plan (timed scene) | 1 | avg $0.0062, max $0.009 | $0.015 | |
| Create, both together | 2 | ~$0.015 | ~$0.036 | **10** (floor) |
| a nightly graph run (concept + gate + prompt + judge, no still) | ~7 | avg $0.03–0.05, max $0.066 | ~$0.10 | 10–16 |
| one Nano keyframe, Flash (`gemini-2.5-flash-image`) | 1 image | $0.039 | $0.094 | **10** |
| one Nano keyframe, Pro (`gemini-3-pro-image`) | 1 image | $0.134–0.139 | $0.33 | **33–34** |
| a timed scene's pick (one still per shot, 3–5 shots), Flash | 3–5 | $0.12–0.20 | | **30–50** |
| same, Pro | 3–5 | $0.40–0.70 | | **100–170** |
| an element's reference sheet (Nano Pro, auto on create) | 1 | ~$0.134 | | **33** |

For scale: the cheapest render is LTX 6s 1080p = 87 credits.

**Two facts that shape the design:**

1. **A Create is under the 10-credit floor.** At MARKUP 2.4 a Create costs ~4
   credits of charge, so it rounds up to 10 whatever it actually cost.
   "Hold an estimate, settle to the metered actual" would settle at 10 almost
   every time — the settle step buys precision nobody sees.
2. **Nano is priced per image, not per token.** The price of a keyframe is
   known before the call (model x images). Hold and settle are the same
   number; it is already "flat".

**One gap the meter has today:** `reference_map` (36 calls) and
`reference_check` (99 calls) are written with `cost_usd` NULL — unpriced. A
settle-to-actual design would silently charge nothing for them. Either price
them in `spend.DEFAULT_PRICES` first, or don't settle to actual.

---

## 2. What would be charged — the doors

User-driven, in the studio (the ones that matter for open sign-up):

| door | route / function | Gemini stages | Nano images |
|---|---|---|---|
| **Studio Create** | `POST /api/scenes/run` → `scene_chain.run` (a job) | concepts, timeline, reference_map, crag | 0 (Create stops on the board) |
| **Pick** (board, MCP `pick`) | `POST /api/concepts/{id}/pick` → `scene_chain.draw_on_pick` (a job) | — | 1 per shot |
| **Director keyframe node** | `POST /api/workflows/exec/nano`, `workflow_runner` Run all | enhance | 1 |
| `/api/generate/run` image branch | `nano_banana.generate_from_prompt` | enhance | 1 |
| **New element** | create routes → `element_sheet` (auto, `sheet` on by default) | location (vision) | 1 Pro |
| Creative guide | `POST /api/creative-guide` | creative_guide, per turn | 0 |
| Direct / Polish | `director.direct_scene`, `refine_shot_prompt` | director, shot_prompt | 0 |
| Scout / research from the studio or MCP | `scout_spark`, MCP `research` / `generate` | scout, research, the whole graph | 0–1 |

Operator / unowned (today every row is attributed to account 1 or 2, both
`credit_exempt`, so these cost no one either way): the nightly walk, the
`03:30`-style manual shadow run (`src.trigger`), the CLI, `src.scout run`.

---

## 3. Proposed shape (for Mike to accept or change)

**Recommendation: flat, held-then-settled per USER ACTION, not per model call.**

- **One hold per action**, taken before the first model call, through the same
  seam as renders: `ledger.hold_for_render(account_id, ref=..., provider=
  "gemini"|"nano", estimate_usd=..., credits=<the flat price>)`. That already
  returns `None` for a `credit_exempt` account and for the unowned pool, so
  Mike's accounts stay uncharged with no new predicate.
- **Create = a flat price** (the floor, 10 credits, unless Mike picks another
  number). Held at the start of the job, settled when a concept row is saved,
  released if the job fails before it saves anything. Because the real cost is
  under the floor, flat and settle-to-actual give the same number; flat has no
  dependency on the unpriced stages.
- **Keyframe = per image**, `charge_credits(price_per_image(model))`: 10
  credits on Flash, 33 on Pro. A pick on a timed scene holds **the whole
  strip up front** (N shots x per-image) and settles per still actually drawn
  — so a strip cut short by a failure or the daily cap releases the rest.
  This is the renders' pattern exactly (hold the quote, settle at most that).
- **Reuse `src/charge.py`'s `Charge`** (take / submitted / settle / release)
  rather than a second wrapper; `submitted()` marks the instant before the
  first Gemini call, so the reaper can tell "never ran" from "ran and nothing
  recorded it".
- **Tie the meter to the hold**: `spend.bind(..., charge_ref=ref)` so each
  `llm_calls` row of the action carries the hold's ref. Not needed to price a
  flat Create, but it makes margin measurable (`sum(cost_usd)` per ref vs the
  credits settled) and it is what a later switch to settle-to-actual reads.

**Implementation risks to check before building**

- `ledger.reap` was written for renders: it looks for a `generations` row
  carrying `ledger_ref`. A Create hold has no generations row. The reaper
  must learn the new provider(s) or it will flag every settled-without-row
  Create hold.
- The job registry dies on a deploy (the orphan PR #73 fixes for fal). A
  Create or pick killed mid-job leaves a `submitted` hold. Cheap enough that
  "release it on the next boot" is the right answer — decide that it is.
- `NANO_DAILY_CAP` is counted from `generations`; a charged image must still
  write its generations row (it does today) so the cap keeps counting.

---

## 4. Where the studio shows the charge

Same rule as the Queue since PR #71: an exempt account sees **"not charged"**,
everyone else sees the credits before they click, and a refusal says the
balance and what it needed (`charging.refusal`).

| surface | what it shows |
|---|---|
| Studio composer, **Create** button | `Create · 10 cr` |
| Board card, **Pick** | `Pick · draws 4 stills · 40 cr` (N from the scene's timeline; 1 for a one-window scene). A scene that already has its stills: `Pick` (free — `pick_skip_reason` already says why) |
| Director, **Nano keyframe node** | `10 cr` / `33 cr` beside Run, from the node's model |
| Director, **Run all** | the sum of the billable nodes it will run (renders already refuse without a quote) |
| Elements, **Add element** with sheet on | `Draw a reference sheet · 33 cr` on the toggle |
| Studio shell header | the balance (`GET /api/billing/balance` exists; the shell does not show it yet — BILLING.md "Still open") |

One new endpoint serves all of them: `GET /api/prices/actions` →
`{create, keyframe: {flash, pro}, sheet, exempt}`, projected off the same
constants the hold uses (no JS price twin — the rule since pricing step 4).

---

## 5. What is NOT in this task

- Video renders — done.
- Soul stills (`higgsfield.generate_image*`, refgen, scene_chain's visual
  targets) — operator's Higgsfield key, unowned or exempt today. Listed as a
  question below rather than assumed.
- Embeddings (`rag.py`) — not metered at all, fractions of a cent.
- Stripe, plans, the markup — unchanged.

---

## 6. Questions for Mike (ANSWERED 2026-09-29 — see section 0)

1. **Flat or settle-to-actual?** Recommendation: flat per action (Create = one
   price, keyframe = per image). A Create really costs ~4 credits, so both
   land on the 10-credit floor; settle-to-actual would only differ for a
   graph run or a long creative-guide session. Yes to flat?
2. **What does one Create cost, and what does it include?** Recommendation:
   **10 credits** covers the scene, its timeline plan, the reference map and
   the CRAG rewrite. The judge (`prompt_gate`) and the uncanny judge don't run
   on Create today (they are the nightly graph's). OK — or a different number?
3. **The other Gemini doors:** charge the creative guide (per turn, ~$0.016,
   so 10 credits a turn at the floor), Direct and Polish (~$0.006 each)? Or
   leave them free and let the per-account daily Gemini budget (phase 4 of
   the Stripe task) be their wall? Recommendation: free + budget; charging
   10 credits for a chat turn reads badly.
4. **Scout, research and the nightly walk:** they run on accounts 1/2
   (exempt) or unowned. If a paying account ever gets its own nightly walk or
   uses MCP `research` / `generate`, does it pay? Recommendation: MCP
   `research`/`generate` from a non-exempt account holds like a Create (per
   run); the nightly walk stays operator-only and uncharged.
5. **Balance hits zero mid-action:** with one hold taken before the first
   call, a Create cannot run out halfway — it is refused before it starts,
   with the balance and the price. A keyframe strip holds all N stills up
   front, so the same. The remaining question: **refuse, or draw what the
   balance covers** (e.g. 2 of 4 stills)? Recommendation: refuse — a partial
   strip leaves a scene half-anchored.
6. **`NANO_DAILY_CAP` once keyframes are charged:** keep it? Recommendation:
   keep it as an abuse backstop and the only wall on exempt accounts
   (the code default is 20/day per account; CLAUDE.md says 60, and neither
   fly.toml nor the preflight sets it, so check Fly's secrets), but raise
   it — a paying account with 5-shot scenes hits 20 at four picks.
7. **Element reference sheets:** drawn automatically on Nano Pro when an
   element is added (~33 credits). Charge it, make it opt-in for non-exempt
   accounts, or keep it free as an onboarding cost?
8. **Nano Flash or Pro for a paying account's keyframes?** 10 vs 33 credits a
   still. Which model do non-exempt accounts get — or is it their pick at the
   node?
9. **A new sign-up with 0 credits:** refused on their first Create, or a
   trial grant (e.g. 100 credits = ten Creates or one LTX render)? This is
   the phase-4 "usable trial rather than a refusal" question.
10. **Soul stills** (Higgsfield, operator's key): same treatment as Nano, or
    out of scope while only exempt accounts reach them?

---

## 7. Build order (revised for section 0)

1. **Trial grant + Create gate.** `ledger.grant(kind="trial", 100)` once per account at
   first sign-in (idempotent on a source ref); Create refuses an account with no plan
   and no balance, message "subscribe or top up". Exempt accounts untouched.
2. **Keyframes behind approve.** `pricing` gains the per-image price (Flash 10 / Pro 33,
   off `nano_banana`'s price table) and `GET /api/prices/actions`; `draw_on_pick` stops
   auto-drawing and becomes `POST /api/concepts/{id}/keyframes` (approve), holding the
   whole strip through `Charge` and settling per still drawn; the MCP `pick` stops
   spending. The Director's Nano node and `/api/generate/run`'s image branch take the
   same hold. Refusal = "top up credits".
3. **Element sheets charged** at the Pro price, shown on the toggle.
4. **Drop `NANO_DAILY_CAP`** (and `NANO_GLOBAL_DAILY_CAP`) from `nano_banana` and
   `generative.cap_error`'s nano entry.
5. **Remove Higgsfield**: `src/higgsfield.py`, its IMAGE_TOOLS entry, refgen's and
   scene_chain's Soul paths moved to Nano; `mcp-subscription` stays in
   `SUBSCRIPTION_SOURCES` for old rows.
6. **MCP `research` / `generate`** hold like a Create for non-exempt callers — which,
   with Create free, means: refused for an account with no plan and no balance.
7. `ledger.reap` learns the nano provider.
8. The studio surfaces (section 4), minus the Create price.
9. One real keyframe approve and one real trial sign-up on a non-exempt test account,
   read back from `credit_entries` before sign-up opens.
