> **Shipped 2026-08-31** on `claude/account-tenancy` — `5f66f59` (schema),
> `b7216d8` (reads), `3ddf55a` (writes, caps, entry points). Every box below is
> ticked except section 6, which is deployment and the pilot invites.
>
> Four things this plan did not predict, all found by running rather than
> reading, all now covered by tests in `tests/test_tenancy.py`:
>
> 1. **The boundary question resolves the other way.** `accounts` already IS the
>    brand table, so `account_id` became the scoping key and `brand` a label —
>    but then the brand pill, which switches `current_account`, would have
>    scoped every query to an account the backfill gave nothing. `current_account_id`
>    resolves the tenant; `current_account` still resolves the brand.
> 2. **`locations.name` was globally UNIQUE**, so no second account could own a
>    "Garage". The rebuild that fixes it sits next to a foreign key, and the two
>    obvious ways to write it both destroy `concept_locations`.
> 3. **The entry points are not a footnote.** After the backfill nobody owns
>    nothing, so a CLI or the nightly graph running as "nobody" reads an empty
>    database and reports a clean run. `--account` and
>    `accounts.resolve_account()` exist for that, not for tidiness.
> 4. **The caps needed the seam kept.** Routing the check past each tool's own
>    `generations_today()` would have silently un-patched the tests that stop a
>    "capped" render making a real billed call.

# Task — account tenancy (the launch blocker)

**Why this exists.** `accounts.py`, `auth.py` and capability gating are built and working, but the
data layer underneath them has no owner. Two signed-in users would share one pool of concepts, and
the render caps are global, so the first user each day exhausts everyone's budget. Until this is
done the product cannot be shown to a second person, however small the pilot.

**Verified 2026-08-27, on `main`:**

```
list_concepts()  ->  SELECT * FROM shoot_concepts ORDER BY id DESC LIMIT ?
get_concept(id)  ->  SELECT * FROM shoot_concepts WHERE id = ?
runway._used()   ->  SELECT COUNT(*) FROM generations WHERE tool='runway' AND created_at >= ?
```

No `account_id` column exists on `shoot_concepts`. No ownership check on read. IDs are sequential
integers, so any concept is reachable by guessing.

**Scope:** one weekend. Not a rewrite — an ownership column, filtered reads, and scoped caps.

---

## 1. Schema — give every owned row an owner

- [x] Add `account_id INTEGER REFERENCES accounts(id)` to `shoot_concepts`, `locations`,
      `characters`, `props`, `generations`, `videos`, `scene_briefs`.
- [x] Additive `ALTER TABLE` in each module's own `init()` — the `preprod.py` pattern already used
      for `picked_at`. No migration framework, no destructive change.
- [x] Backfill every existing row to the bootstrap account so current data keeps working.
- [x] Index `(account_id, id DESC)` on `shoot_concepts` — it's the shape every list query uses.

**Decide first:** is the tenancy boundary the **account** or the **brand**? Today `brand` is the
only scoping dimension and `antihero` / `zeropage` are two brands of one operator. An outside user
needs their own brands, so `account_id` is the real boundary and `brand` becomes a dimension
*inside* it. Getting this backwards means doing the pass twice.

## 2. Reads — no query returns another account's rows

- [x] `list_concepts(account_id, ...)` — required argument, not optional with a default. An optional
      arg is a leak waiting for the one call site that forgets it.
- [x] `get_concept(concept_id, account_id)` — returns `None` on mismatch, exactly as it does for a
      missing id. Don't distinguish "not yours" from "not found"; that difference is an enumeration
      oracle.
- [x] Same treatment for locations, characters, props, generations, videos, holds, scene briefs.
- [x] Audit every `SELECT` in `src/` for a missing `account_id` predicate. Grep for `FROM ` and read
      each one.

## 3. Writes — ownership set on create, checked on mutate

- [x] Every insert stamps `account_id` from `auth.current_account`, never from a request parameter.
- [x] `update_concept_shots`, `set_shot_media_url`, `delete_concept`, the verdict routes, director
      mode — all verify ownership before mutating.
- [x] `delete_all_concepts()` with no argument currently wipes the whole table. Make `account_id`
      required.

## 4. Caps — per account, per day

- [x] `runway._used()`, `veo._used()`, `midjourney._used()`, `nano_banana._used()` take `account_id`
      and add it to the `WHERE`.
- [x] Keep a **global** ceiling as well as the per-account one. Per-account alone means ten users
      times six renders is sixty renders on your card.
- [x] Decide whose key pays. Options: your key with a hard per-account quota (simplest for a pilot),
      or bring-your-own-key per account (no cost exposure, more onboarding friction). For 5–10
      invited users, your key plus a low quota is the right call.

## 5. Tests — the ones that would have caught this

- [x] Two accounts, one concept each: A's list returns exactly one row and never B's.
- [x] A fetching B's concept by id returns `None`.
- [x] A's renders don't count against B's cap.
- [x] A cannot mutate or delete B's concept.
- [x] Regression test: assert no `SELECT` against an owned table lacks an `account_id` predicate.

## 6. Then, and only then

- [ ] Deploy somewhere real (it's localhost-only today).
- [ ] Rotate any secret that has been in `.env` on a dev machine.
- [ ] Invite 5–10 filmmakers by manual `account_members` INSERT — the v1 posture is already built
      for exactly this.
- [ ] Watch what they do, and write down what broke.

---

## Out of scope, deliberately

Invite UI, password reset, email verification, billing, sign-out-everywhere. A pilot of ten people
runs fine on manual INSERT and a direct message. Build these when the pilot says they're needed,
not before — the same reasoning that removed beat-sync and the Resolve integration.
