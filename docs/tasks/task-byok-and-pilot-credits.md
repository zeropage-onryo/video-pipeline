# Task — whose credits do pilot users spend? (BYOK, and the positioning behind it)

**Status: not started. This is a decision doc plus the build behind whichever way
the decision goes.** Written 2026-09-01, out of two questions Mike asked back to
back after account tenancy shipped:

> "If I'm having other users wouldn't they use their own credits / apis"

> "well how can i make it like higgsfield or runway, the point is to get users
> using my ai production studio for content?"

The first is a billing question with a small answer. The second is a positioning
question with a large one, and it decides whether the first is even worth
building. Both are here because they are the same question seen from two ends.

---

## 1. What is true today (verified 2026-09-01 on `claude/account-tenancy`)

**Every API key in this repo is a process-wide environment lookup made at call
time.** There is no per-account key storage anywhere, and no code path that could
use one. The billed-render key sites are five functions:

```
src/runway.py:179      _make_client()   RUNWAYML_API_SECRET
src/veo.py:89          _make_client()   GEMINI_API_KEY | GOOGLE_API_KEY
src/midjourney.py:94   _request()       ACEDATA_API_KEY
src/higgsfield.py:249  _credentials()   HIGGSFIELD_API_KEY_ID + _SECRET
src/nano_banana.py:109 _client()        genai.Client() -- reads the env itself
```

The cheap non-render path (Gemini text: `shootgen`, `taste_judge`,
`uncanny_judge`, `scout`, `rag`, `promptgen`, `quality`, `scheduling`,
`locations`, `grounded_answer`, `rework`, `asset_shelf`) resolves
`GEMINI_API_KEY`/`GOOGLE_API_KEY` inline at roughly twenty more sites.

Two things follow from that:

- **Every render a pilot user makes today bills Mike's cards.** Tenancy scoped
  the *data*; it did nothing to the *spend*. The per-account cap is the only
  thing between a pilot user and Mike's Google Cloud bill.
- **BYOK is now a small change, and it is small precisely because tenancy
  shipped.** `account_id` is already threaded through every render path —
  `GenState`, `generative.used_today`, each tool's `generations_today`, and the
  CLI/graph entry points that resolve it. The missing piece is a key resolver
  that takes the `account_id` the call site already has.

`nano_banana._client()` is the one awkward site: it calls `genai.Client()` with
no argument and lets the SDK read the environment, so it cannot accept a
per-account key without being changed to pass `api_key=` explicitly.

### What a render actually costs

| tool | per unit | gate today |
|---|---|---|
| veo (8s clip) | **$3.20** | cap only — **no `SPEND_OK` env gate** |
| midjourney (still) | $0.27 | `MIDJOURNEY_SPEND_OK=1` |
| runway (gen4_turbo, 5s) | $0.25 | `RUNWAY_SPEND_OK=1` |
| higgsfield (clip) | $0.40 | `HIGGSFIELD_SPEND_OK=1` |
| nano banana (still) | ~$0 | cap only |

At the shipped defaults (`VEO_DAILY_CAP=6`, `RUNWAY_DAILY_CAP=6`,
`MIDJOURNEY_DAILY_CAP=10`, `HIGGSFIELD_DAILY_CAP=6`) one account's theoretical
daily maximum is about **$26**, of which veo is ~74%. Ten pilot users all
running flat out is ~$260/day. Nobody runs flat out, but the cap is the only
number that bounds it, so the cap is the budget.

**Veo is the outlier twice over:** most expensive per call, and the only billed
tool with no second `SPEND_OK` wall. Every other tool needs an explicit
per-command approval that Mike controls; veo needs only to be under the cap.
Whatever is decided about BYOK, that asymmetry is worth closing on its own.

---

## 2. The positioning argument (why BYOK might be the wrong first move)

Higgsfield and Runway are **model companies**. They own the inference, so
reselling clips at a margin is their business. This repo does not own inference —
it rents it from five vendors. Competing with them on "a place to press generate"
means reselling their inference at a worse price with no cost advantage, which is
a losing position no amount of engineering fixes.

What this repo has that they do not is the **pipeline with taste in it**:

- `scout` pulling real reference from what actually performs
- `taste_judge` scored against Mike's own graded history, not a generic aesthetic
- `uncanny_judge` catching the tells that make AI video read as AI
- `winning_prompts`, `pick_rate` / `shoot_rate`, attempts-to-keeper — a feedback
  loop that gets *better with use*
- reference grounding, and the nightly orchestrator that runs the whole thing
  unattended and parks results for approval

None of that is "a model with a text box". A user's tenth run should be better
than their first because the system learned their taste — that is the product,
and it is the only part a model company cannot copy by shipping a new checkpoint.

So the honest read: **the binding constraint is distribution, not architecture.**
Nothing in section 3 gets a single user. If the choice is between building BYOK
and putting a working demo in front of ten people, the demo wins, and BYOK gets
built the week someone asks "can I use my own Runway key" — by which point it is
a day of work, not a rewrite.

---

## 3. The recommended shape, if and when it is built

**Split the path by cost, not by principle:**

- **Mike's keys pay for the cheap, high-frequency steps** — concept generation,
  the judges, scout, RAG, captions, nano stills. Cents per run, and they are the
  part that produces the taste loop. Charging a user for them, or asking for a
  key before they can see anything, kills the first-run experience that is the
  whole pitch.
- **The user's key pays for the expensive renders** — veo, runway, midjourney,
  higgsfield. Dollars per clip, no margin in it for Mike, and a user who wants
  volume already has accounts with these vendors.

That gives a free tier that costs Mike ~nothing per user (concepts, judged
prompts, stills, parked scenes) and a render step that is either capped on Mike's
keys or unlimited on the user's. It also removes the single worst failure mode of
the pilot: one enthusiastic user burning the shared veo budget by lunchtime.

### Build sketch

- [ ] **`account_keys` table** in `src/accounts.py`'s `SCHEMA`, alongside
      `account_members`: `(account_id, provider, ciphertext, created_at,
      last_used_at, label)`, `PRIMARY KEY (account_id, provider)`. Follow the
      pattern the shipped tenancy work used — additive, `CREATE TABLE IF NOT
      EXISTS`, no rebuild.
- [ ] **Encryption at rest.** A key in plaintext in `pipeline.db` means the
      nightly file-copy backups now contain other people's credentials. One
      `ZEROPAGE_KEY_SECRET` in the environment, Fernet or equivalent, and the
      column holds ciphertext only. This is the part that makes the task a real
      task rather than a table.
- [ ] **`accounts.key_for(account_id, provider) -> str | None`** — the account's
      key, decrypted, else `None`. `None` means fall back to the environment,
      which keeps every existing test and every solo-operator path working
      untouched.
- [ ] **Five call-site swaps** — the functions listed in section 1, each taking
      `account_id` (already available at every caller) and asking `key_for`
      before the env. `nano_banana._client()` also needs `api_key=` passed
      explicitly.
- [ ] **Redaction.** `runway._safe_error` and `midjourney._safe_error` scrub the
      *environment's* key out of error text. With per-account keys they must
      scrub the key that was actually used, or one user's key lands in another
      user's error page.
- [ ] **Caps become conditional.** An account on its own key should not be
      counted against Mike's `GLOBAL_DAILY_CAP` — that ceiling exists to protect
      his bill. Per-account `DAILY_CAP` still applies (it protects the user).
- [ ] **A settings page** to paste a key, showing which providers are on Mike's
      keys and which are on the user's, with last-used. Never render the key
      back — store, verify with a cheap probe call, and show a masked tail.
- [ ] **Close the veo gap** — give veo a `VEO_SPEND_OK` gate like the other three
      billed tools, or write down why it deliberately has none. Worth doing
      regardless of everything above.

### What it costs, honestly

Onboarding friction. "Paste your Runway API secret" is a wall in front of a
product that has not yet proved itself to that user. Every BYOK product pays this
and the ones that survive it are the ones where the user already wanted the thing
badly enough. That is an argument for BYOK being an *upgrade path*, not the front
door — which is exactly the split above.

---

## 4. The decision Mike has to make

1. **Do pilot users render on Mike's keys or their own?** Recommended: Mike's
   keys, hard-capped, for the first handful of people — the caps already exist and
   the numbers above are survivable at that size. BYOK when someone asks.
2. **If Mike's keys: what are the real `*_GLOBAL_DAILY_CAP` numbers?** Still
   unset from the last session — every ceiling currently defaults to the
   per-account cap, which means the *installation* ceiling equals *one account's*
   allowance and the second pilot user gets nothing. **This is a live bug for any
   pilot with more than one person in it, whatever is decided about BYOK.**
3. **Is the next session pointed at BYOK, or at the demo?** Section 2 argues the
   demo. This doc exists so the answer can be "BYOK" later without re-deriving
   any of it.
