# ZPF Pricing Module & Signed Quotes — Build Spec

Written 2026-09-17. Handoff constraints in `task-pricing-and-quotes-handoff.md`.

## Scope and the one invariant

Two pieces, built together because the second is meaningless without the first:

1. **`src/pricing.py`** — the only code in the repo that turns a render intent into a number of credits.
2. **Signed quotes** — an HMAC wrapper around that number, so the thing that renders is provably the thing that was priced and approved.

### The invariant

Unchanged and not up for negotiation: **the gate sits inside `generate_video` / `generate_image`, where the money is actually spent, so no caller can spend around it.** What changes is only what the gate is handed — a boolean becomes a signed quote. The env-var fallback stays for the unattended paths (`orchestrator.generate_render`, `autopilot`), exactly as it works today.

### The guarantee this buys

> The server never charges more than the quote the human approved.

Mechanically: `hold(quote.credits)` before the submit, `settle(min(actual, quote.credits))` after. Overage is the operator's loss, never the customer's surprise. That answers the loudest complaint in the category — credit burn — which the competitive research already flagged as the defensible thing.

### Deliberately out of scope

- **The LLM half.** Concepts, judges, scout, prompt gate, RAG. Cost of goods for the subscription, not metered line items. The ledger design already settled this; don't reopen it here.
- **Stripe, plans, invoices, the purchase flow.** `grant()` gets called from a webhook later. This spec ends at "credits are correctly quoted, held and settled."
- **BYOK renders take no quote and no hold.** A customer who paid their own provider is already charged; quoting the render and then not debiting it puts a price on a page that never becomes a ledger entry. `account_keys.key_and_source` already returns `"account"` / `"env"` — branch on it at the top of `quote()` and return `None`.
- **Real per-render provider invoices.** fal publishes per-second rates; Runway and Higgsfield do not. `settle` uses the estimator's number as actual until a real invoice exists. A documented approximation, not a problem to solve now.

## `src/pricing.py` — the quote function

One module, one public entry point. Everything that shows a price or takes money calls it: the Queue card, the empty-approve branch, the Director Generate node, the REST API, the MCP tools.

### Signature

```python
def quote(
    *,
    account_id: int,          # keyword-only, no default — data-layer rule
    shot: dict,               # the shots row, for timeline + content hash
    part: int | None = None,  # timeline part number; None = whole scene
    provider: str | None = None,   # preference; None means resolve
    model: str | None = None,
    seconds: float | None = None,  # None means derive
) -> Quote | None:            # None == BYOK, nothing to charge
```

Keyword-only with no default on `account_id` follows the existing layer rule — a forgotten argument is a `TypeError` at the call, not a silent read of the unowned pool.

### The five steps, in order

1. **BYOK check.** `account_keys.key_and_source(account_id, provider)` → if `"account"`, return `None`. Do this first so no downstream step can accidentally price a render that will never be debited.
2. **Resolve the renderer.** Delegate to `providers.renderer_for(account_id, provider, model, needs=…)`. Do not re-implement the cheapest-available fallback — that logic is already correct and already used by both the card and the empty-approve branch, and a second copy is how card and quote start disagreeing.
3. **Resolve seconds.** `timeline.fit_seconds` for a part, `timeline.scene_seconds` for a whole scene, then round **up** to the model's legal length. This is the existing `check_timeline_choice` behaviour; move it in here rather than calling it from outside.
4. **Provider cost.** `providers._ESTIMATORS[model](seconds, **params)` → USD. Promote `_ESTIMATORS` to public (`ESTIMATORS`) while you're in there; it is about to have callers outside its own module.
5. **Apply the band.** Markup, floor, rounding — see the next section.

### The Quote object

A frozen dataclass. Every field is in the signed payload, so nothing here may be a float that round-trips badly or an object whose repr can drift.

| Field | Type | Notes |
| --- | --- | --- |
| `pricing_version` | `str` | e.g. `"2026-09-17-video-v1"` |
| `account_id` | `int` |  |
| `shot_id` | `int` |  |
| `part` | `int \| None` |  |
| `provider` | `str` | resolved, never the preference |
| `model` | `str` | resolved |
| `seconds` | `int` | after round-up; integer, not float |
| `provider_usd_micros` | `int` | USD × 1,000,000 — no floats on the money path |
| `credits` | `int` | what gets held |
| `content_hash` | `str` | see below |
| `line_items` | `tuple` | `(label, credits, qty, unit)` for display |

### Two things it must not do

- **No DB writes.** `quote()` is pure given its inputs. The cap check (`generative.cap_error`) and the balance check stay where they are — a quote is a price, not a permission. Conflating them means a user near their cap sees no price at all instead of a price and a reason.
- **No second `run_id` namespace.** If a quote ever gets persisted, key it on the orchestrator's `uuid4().hex` string, not `pitch_runs.id`. The repo already has two `run_id` namespaces and typing the column INTEGER looks like it works and aggregates nothing.

## Markup, floor, and price bands

### The formula

```python
CREDIT_CENTS = 1          # 1 credit = 1 cent of CHARGE (ledger's existing unit)
MARKUP = 2.4              # charge / provider cost
CREDIT_FLOOR = 10         # per render, per part

credits = max(
    ceil(provider_usd_micros * MARKUP / 10_000),   # micros -> cents, round up
    CREDIT_FLOOR,
)
```

Integer math the whole way. `provider_usd_micros` is USD × 1,000,000, so the division by 10,000 lands in cents with no float on the money path. This is the same discipline `ledger.credits_for_usd` already applies; `pricing` becomes its only caller and `credits_for_usd` stops being called directly from anywhere else.

**Today's effective markup is 1.0x** — `credits_for_usd` converts at cost. Setting `MARKUP` is the first real pricing decision in the repo.

### Why 2.4

BrainrotShorts charges roughly $2.40 per $1 of provider spend on its generative calls, with a 10-credit floor. At 2.4x a $49 plan carrying 4,900 credits fully consumed costs you ~$20 of provider spend — 58% gross margin, before the LLM half, which is unmetered cost of goods. That's the right neighbourhood for a bundled-credit creative tool. Move the constant, not the call sites.

### The band problem, with numbers

This is the part that decides whether the plan survives contact with a user. A 5-second clip on a $49 / 4,900-credit plan:

| Renderer | Provider cost | Credits @2.4x | Clips per plan |
| --- | --- | --- | --- |
| kling turbo / wan (cheap tier) | ~$0.21 | 50 | ~98 |
| Higgsfield / kling standard | ~$0.35 | 84 | ~58 |
| Runway Gen-4 | ~$0.75 | 180 | ~27 |
| **Veo 3** | **~$3.20** | **768** | **~6** |

Six Veo clips empties the month. A user who doesn't know the difference between the dropdown options burns their plan in an afternoon and leaves the 1.2-star review you are explicitly trying to differentiate against.

### Bands, not a free-for-all

Declare a band per model in one table beside `ESTIMATORS`:

```python
BANDS = {
    "kling2.1":  Band(tier="standard", max_seconds=10),
    "gen4":      Band(tier="standard", max_seconds=10),
    "veo3":      Band(tier="premium",  max_seconds=8),
}
```

Two rules the quote enforces:

1. **A model above the account's tier does not quote — it refuses with the tier name.** Not a silent downgrade: a silent downgrade means the user got a cheaper render than the one they picked and nobody told them.
2. **`max_seconds` caps the quote, not the render.** The render length already comes from `fit_seconds`; the band is what stops a 30-second Veo quote existing at all.

### Two decisions only you can make

- **Does the free/pilot tier get premium models at all?** Recommendation: no. `invite()` + per-account `DAILY_CAP` already gives capped free credits with no provider signup; adding Veo to that is how one pilot user costs more than the pilot is worth.
- **What happens at zero credits with a key on file?** Either refuse, or fall through to BYOK if the account has one. Falling through is friendlier and is already structurally supported, since a BYOK render takes no hold. Pick one and write it down — this is the case that generates support tickets.

## The signed quote payload

### Wire format

Three dot-separated parts, URL-safe base64, no padding. Deliberately JWT-shaped without being a JWT — no algorithm negotiation, so there is no `alg: none` to get wrong.

```
zpfq.<base64url(canonical_json)>.<base64url(hmac_sha256)>
```

The `zpfq.` prefix makes a quote greppable in logs and unmistakable for an API key (`zpf_`) or a provider key.

### The signed body

```json
{
  "v": 1,
  "pv": "2026-09-17-video-v1",
  "acct": 1,
  "shot": 361,
  "part": 2,
  "prov": "higgsfield",
  "model": "kling2.1",
  "secs": 5,
  "usd_micros": 350000,
  "credits": 84,
  "chash": "9f2c1a…",
  "iat": 1789675340,
  "exp": 1789678940
}
```

Short keys on purpose: this rides in request bodies and gets logged, and canonical JSON means every byte is load-bearing.

### Canonical JSON

The signature is over bytes, so serialisation must be deterministic:

```python
json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
```

No floats anywhere in the body. `usd_micros` is an int, `credits` is an int, `secs` is an int. A float in a signed payload is a signature that breaks on a different Python minor version.

### The content hash — reuse, don't invent

`shot["timeline"]["source"]` is **already** a hash of prompt + refs, computed for staleness-on-read so `ensure` knows when to re-plan. That is exactly the property a quote needs: if the prompt or the reference set changed, the quote is about a different render.

```python
chash = shot["timeline"]["source"]                      # timeline path
chash = sha256(prompt + "\x00" + "\x00".join(refs))     # no-timeline path
```

**Do not write a second hash function.** A scene with one window or none has no timeline, so the fallback is needed — put both behind `pricing.content_hash(shot, part)` and let nothing else compute it. Two hashes of the same thing is how a quote starts passing for a render the user did not see.

### Expiry

One hour (`QUOTE_TTL = 3600`). Long enough that a user can quote, get up, and come back; short enough that a price band change propagates within a session. `iat` is there so an expired quote can be reported as *expired* rather than *invalid* — those are different messages to a user and only one of them is alarming.

### What is deliberately NOT in the payload

- **The prompt text.** It is in the content hash. Putting it in the body makes quotes kilobytes long and puts scene text in every log line.
- **A nonce or single-use marker.** Quotes are idempotent by design: re-approving the same part with the same quote should be refused by `_render_timeline`'s existing skip-parts-with-clips logic, not by quote bookkeeping. Adding replay protection here means a server-side quote store, which is a table, a sweep and a new failure mode for a problem you don't have.
- **The account's balance.** A quote is a price. Affordability is checked at `hold()`, which is the only place that can check it without a race.

## Verification and the signing secret

### `verify()`

```python
def verify(token: str, *, account_id: int, shot: dict, part: int | None) -> Quote:
    """Raises QuoteRefused. Never returns a bool."""
```

Raising rather than returning a bool is deliberate and matches the ledger's rule that every write raises: a verification whose result can be ignored by a caller that forgot an `if` is not a gate.

### The five refusal cases

| Case | `QuoteRefused.reason` | What the user sees |
| --- | --- | --- |
| HMAC mismatch, malformed, wrong prefix | `bad_signature` | "This quote isn't valid. Get a fresh price." |
| `exp` in the past | `expired` | "This price is over an hour old. Re-quote." |
| `chash` ≠ current content hash | `stale_content` | "The scene changed since this price. Re-quote." |
| `acct` ≠ the caller's tenant | `wrong_account` | Generic refusal, logged loudly |
| `pv` not in `SUPPORTED_PRICING_VERSIONS` | `retired_pricing` | "Prices changed. Re-quote." |

**Compare the HMAC with `hmac.compare_digest`,** not `==`. And `wrong_account` should never happen through the UI — if it fires, someone is replaying another tenant's quote, so it gets a log line at warning with the request id, not a silent 403.

`stale_content` is the one that earns the whole design. It is what makes "the thing that rendered is the thing that was priced" true rather than aspirational: edit the prompt after quoting and the old quote stops working.

### `QUOTE_SIGNING_SECRET` is its own secret

Not `ACCOUNT_KEYS_SECRET`. The reason is rotation cost:

- `ACCOUNT_KEYS_SECRET` is the Fernet key wrapping every stored customer provider credential. Rotating it means every BYOK user re-enters every key. The `.env` comment already says never rotate it without doing that.
- `QUOTE_SIGNING_SECRET` rotating invalidates at most one hour of outstanding quotes. Users press the button again.

Tying them together makes the cheap rotation as expensive as the catastrophic one. Generate 32 random bytes, urlsafe-b64, same as the account-keys secret was generated.

**Missing secret behaviour, matching the renderer-keys panel precedent:** return `503` with the generation command, never a `500`, and never sign with a default. A hardcoded fallback secret is a quote anyone on the internet can mint.

### Not the same key across environments

Dev, the Fly deployment and any future staging get different secrets. A dev-minted quote must not verify in production — that is the whole point of signing it.

## Wiring: the gate and the ledger

### `spend_approved` changes shape, not location

It stays inside `generate_video` / `generate_image`. Only the argument changes:

```python
# now
def spend_approved(approved: bool | None = None) -> bool

# after
def spend_approved(quote: Quote | None = None, *, approved: bool | None = None) -> bool
```

Resolution order, which preserves today's semantics exactly:

1. A **verified** `Quote` → approved. (Verification happens at the route, not here — this function receives a `Quote`, never a token.)
2. An explicit `approved` bool → wins in both directions, as it does today. This is what keeps `spend_approved(False)` refusing even with the env var armed.
3. The `*_SPEND_OK` env var → fallback only when nobody answered, which is still the unattended paths: `orchestrator.generate_render`, `autopilot`, and `providers.usable()` for the graph's failover.

**Do not delete the env var.** Deleting it leaves the unattended paths with no way to be armed at all. That was settled on 09-09 and nothing here changes it.

### The five human callers, migrated

All five currently pass `approved=True`. Each becomes: verify the token → pass the `Quote`.

| Caller | Where the token comes from |
| --- | --- |
| `queue_approve` | request body, minted by `queue_pending` |
| `shot_generate` | request body, minted by the board card |
| `/api/generate/run` (video branch) | request body |
| `/api/workflows/exec/generate` | request body |
| `workflow_runner` Generate node | node config, minted at Run |

A request with no token and no `approved` falls to the env var and therefore refuses in normal operation. That is the correct default.

### The ledger sandwich

The critical ordering rule from the ledger design is unchanged and must stay unchanged: **money is spent at one instant — the HTTP submit inside the adapter — so the ledger writes before it.**

```
verify(token)                    # route
  ↓
hold(account_id, quote.credits)  # refuse here => no HTTP call is ever made
  ↓
mark_submitted()
  ↓
<provider submit>                # generate_video
  ↓
settle(min(actual, quote.credits))   # the cap — or release() on failure
```

`ledger.hold_for_render` is already the named seam and already names the three submit sites. This spec does not move it; it gives it a number to hold.

**`min(actual, quote.credits)` is the guarantee.** Without the `min`, a provider that bills more than the estimator predicted charges the customer for your estimator's error. Log the overage; eat it.

### The timeline loop

`_render_timeline` loops parts and stops at the first failure so approving again resumes. That means **one quote per part**, not one per scene. Quote the parts together for display (`Approve · render 2 shots ~$0.50` already does this), sign them individually, and hold per part as the loop reaches it. Holding the whole scene up front means a scene that fails on part 1 has part 2's credit locked until the reaper sweeps.

### The cap check stays where it is

`generative.cap_error` counts from the `generations` table so a stuck loop hits a database wall rather than one a process remembers. Caps are not a pricing concern and must not move into `pricing.py`. Two independent walls is the correct number here.

## Build order and migration

Six steps. Each ends somewhere the suite is green and the studio still works, so none of them has to land in one sitting.

**1 · `pricing.quote()` with `MARKUP = 1.0`.** Pure function, no callers changed. Identical numbers to today, so the Queue's price labels don't move. Ships behind nothing.

**2 · Point the display at it.** `queue_pending`, the empty-approve branch and the Director node read their price from `pricing.quote()` instead of calling estimators directly. Still no signing, still no money. This is the step that surfaces any disagreement between the card and the quote while it is still cosmetic.

**3 · Delete the JS duplicate.** `fitSeconds` in the Queue JS duplicates `timeline.fit_seconds`. Serve the number from the quote in the pending payload and delete the client-side copy. Two implementations of a price is how a user gets shown one number and charged another.

**4 · Signing.** `sign()` / `verify()`, `QUOTE_SIGNING_SECRET`, tokens minted in the pending payload and echoed back on approve. Accept a missing token (fall through to `approved`) so nothing breaks while the front ends catch up.

**5 · Make the token required, raise `MARKUP`.** One commit, because raising the markup without requiring the token means the unsigned path silently undercharges.

**6 · Wire `hold_for_render`.** Now it has a number to hold and a cap to settle under.

### Do this first, before step 1

**Get one clip through `generate_for_shot` → a `generations` row → a `media_url`.** As of 09-14 nothing ever had: all 106 `generations` rows are `tool='nano'` keyframes, zero from runway/fal/veo/higgsfield, and the 12 concepts carrying a `media_url` came through hand-driving the Runway app, which writes no `generations` row.

Everything in this spec prices, signs and meters that path. Building billing on a path that has never executed means the first real render is also the first test of six new systems at once. One clip first.

### The fix this unblocks

`nightly_runs.spent_usd` under-reports by ~10x and ~10,000x, so the `NIGHTLY_BUDGET_USD` breaker reads a meter stuck near zero and cannot fire. Once `pricing` is the single source of a render's cost, the nightly path writes the same number everything else does and the breaker becomes real. Worth doing in step 2 while you're already in there.

### Files touched

| File | Change |
| --- | --- |
| `src/pricing.py` | new |
| `src/providers.py` | `_ESTIMATORS` → `ESTIMATORS`, add `BANDS` |
| `src/generative.py` | `spend_approved` signature |
| `src/{runway,fal,veo,higgsfield}.py` | thread `quote` where `approved` goes |
| `src/ledger.py` | `hold_for_render` takes a `Quote` |
| `app/api.py` | verify at the five callers |
| `app/static/zpf/*.js` | echo the token, delete `fitSeconds` |
| `.env` | `QUOTE_SIGNING_SECRET` |
| `tests/conftest.py` | `QUOTE_SIGNING_SECRET` into `POSTURE_ENV` |

That last row matters: the suite inherits your real `.env`, and a signing secret present on your Mac but absent in CI is exactly the `test_env_posture` failure class that has bitten twice already.

## Test plan

The standard this repo already holds itself to: **a test that does not fail when the fix is reverted proves nothing.** The concurrency test in the ledger was verified to fail with the advisory lock removed; the scoping tests were verified by reverting the fix and watching them go red. Same here — for each test below, revert the line it guards and confirm it fails before you keep it.

### `tests/test_pricing.py`

- A quote is deterministic: same inputs, same credits, same signature bytes.
- The floor binds — a sub-cent provider cost still quotes 10 credits.
- Rounding is **up**, never down, at every boundary.
- `MARKUP` is honoured: set it to 1.0 and 2.4 in the same test and assert the ratio.
- A premium-band model on a standard-tier account refuses **and names the tier**. Assert the message, not just the raise — a silent downgrade passing as a refusal is the bug this prevents.
- **BYOK returns `None`.** Seed an account key, assert no quote and no hold. This is the one that stops double-charging.

### `tests/test_quotes.py`

- Round-trip: `verify(sign(q)) == q`.
- One flipped byte in each of the three token parts → `bad_signature`.
- `exp` in the past → `expired`, not `bad_signature`. Different message to the user.
- **Edit the prompt after signing → `stale_content`.** The headline test. If this one passes with the content hash removed, the hash isn't wired in.
- A quote minted for account 1 presented by account 2 → `wrong_account`.
- A retired `pv` → `retired_pricing`.
- Missing `QUOTE_SIGNING_SECRET` → 503 with the generation command, never a 500, never a signed token.

### Integration, against a stub adapter

- **A refused hold means no HTTP call.** Assert the stub adapter's submit was never entered. This is the ordering invariant the whole ledger design rests on, and it is the one that will get broken by a future refactor that looks harmless.
- Actual cost above the quote → settled at `quote.credits`, overage logged. The cap, proven.
- Provider failure after submit → `release`, credits back.
- Submitted with no usable row → **`ORPHANED`, outstanding, not released.** Releasing an orphan hands back credit for a billed render and erases the only trace.
- Timeline part 1 succeeds, part 2 fails → part 1 settled, part 2 released, re-approve resumes at part 2 and quotes only part 2.

### Tenancy

The static SQL scanner in `test_tenancy.py` fails on any statement reaching an owned table without an owner. If quotes ever get persisted, that guard covers the new table automatically — **do not add an allowlist entry for it.** Every existing allowlist entry carries a reason; a quote table has none.

Also: `conftest`'s `account_scope` override returns `None`, so a test about ownership must seed a real account and set its own `dependency_overrides`. A green test under the None override is not evidence of correct scoping.

### Posture

Run it the way CI runs it. `QUOTE_SIGNING_SECRET` goes in `POSTURE_ENV`, and the suite must not inherit a real one from `.env` — that is the `test_env_posture` failure mode where eleven tests passed on GitHub and failed on your Mac.

## As built — steps 1–3 (2026-09-17), and where this spec was wrong about the code

Steps 1–3 are on `claude/pricing-quotes-handoff-944336`. `MARKUP` is `"1.0"`; nothing is signed, required or held. Steps 4–6 are not started.

Where the code disagreed with the spec above, the code won and the reason is here:

1. **The BYOK check cannot come first.** `key_and_source(account_id, provider)` needs a vendor, and with `provider=None` there is not one until the renderer is resolved. Order is resolve → price → BYOK. It also goes through `account_keys.key_source` + `ledger.is_billable` (the one rule, which never raises) rather than comparing `"account"` a second time.
2. **`ESTIMATORS` is keyed by provider and takes `(model, seconds, frame)`**, not `[model](seconds, **params)`. `frame` is not optional: Seedance and fal bill per resolution tier, so `Quote` and `quote()` carry `frame`, which the field table omits. It will need a key in the signed body (`frame`).
3. **`shot["timeline"]["source"]` is the wrong thing to sign.** It is what the timeline was *planned from* and only moves when `timeline.ensure` next runs, so between a prompt edit and the re-plan it still names the old prompt: a quote checked against it survives exactly the edit `stale_content` exists to catch. `pricing.content_hash` calls `timeline.source_hash(prompt, refs)` on the live shot — the same function, so still one hash, identical to the stored value whenever the timeline is current. (It is sha1[:16], not sha256; nothing new was written.) `test_editing_the_prompt_changes_the_hash_before_any_replan` fails if it is switched back.
4. **`renderer_for` is a preference-with-fallback, so it cannot resolve an explicit pick.** Handed `provider="fal"` on an account with no fal key it answers Runway — a quote for something nobody chose. An explicit provider is honoured exactly (and refused if illegal, as `check_render_choice` always did); only an empty intent resolves, through `providers.render_default`, which is `renderer_for` under the plan and is what the card and the empty approve already shared.
5. **A whole scene's default length is the model's default, not `timeline.scene_seconds`.** `scene_seconds` is the length the *writer* fills (composer select / env, 10 by default); the Queue card opens on the model's own default (5s on Runway). Using `scene_seconds` would have doubled every label at step 1, which has to move none.
6. **`shot_id` is the concept id.** A scene is one `shoot_concepts` row with its shot inside `shots_json`; there is no shots row to point at. `quote()` takes it as a required keyword (`shot_id=`), since a shot dict does not know its concept.
7. **`MARKUP = 2.4` as a float is a latent off-by-one.** `100000 * 1.1 == 110000.00000000001`, which ceils to 12 credits for an 11-credit render. (2.4 happens to be safe on every price checked; 1.1 and 2.2 are not.) `MARKUP` is a string read through `Fraction`; a float typed there is read via `str()`.
8. **There is no account tier anywhere in the repo.** `BANDS` exists (`providers.BANDS`, every catalogue model banded, an unbanded model reads as premium) and `quote(tier=...)` refuses with the tier named, but with no tier passed nothing is enforced — enforcing a default would have made Veo unquotable today. `max_seconds` is `None` (the model's own maximum) on every standard model, because LTX is legal to 20s today and a cap of 10 would refuse quotes the Queue currently gives. Both are yours to set.
9. **The 10-credit floor is not "identical numbers".** At 1.0x a render under $0.10 quotes 10 credits where `credits_for_usd` said fewer. It only shows in `credits`; every dollar label still prints the provider estimate, so no label moved.

Found while wiring the display (step 2's purpose):

- **Approve and the card disagreed on a resumed timed scene.** `check_timeline_choice` priced *all* windows; the card and `_render_timeline` count only shots still without a clip. Both now price what is left.
- **The Director's Generate chip was Runway's price on every account**, including one that can only render on Higgsfield. The concept now serves `generate` (one clip, on the renderer `workflow_exec_generate` resolves).
- **The React Queue had no idea a scene could be timed** and labelled one as a single clip at the card's duration. It is the production front end, so that was the live number.

Not done, deliberately:

- **`nightly_runs.spent_usd`.** The meter (`costs.spent_since`) just sums `generations.cost_usd`; the under-report is in what the *adapters write* — `runway.py:433` omits `ratio`, `fal.py:840` omits `resolution`, and the `generate_from_prompt` rows (`runway.py:798`, `fal.py:1023`, `higgsfield.py:947`) omit `duration`. Fixing it means editing all four adapters' write sites, which is steps 4–6's territory. Those five lines are the fix.
- `ledger.credits_for_usd` still has its one caller, `hold_for_render` (step 6). `test_at_cost_it_charges_what_the_ledger_always_did` pins the two together at 1.0x for every model.
- `QUOTE_SIGNING_SECRET` is not in `POSTURE_ENV` yet because nothing reads it yet; it goes in with the first line of step 4.
