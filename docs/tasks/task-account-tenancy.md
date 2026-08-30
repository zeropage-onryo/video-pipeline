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

- [ ] Add `account_id INTEGER REFERENCES accounts(id)` to `shoot_concepts`, `locations`,
      `characters`, `props`, `generations`, `videos`, `scene_briefs`.
- [ ] Additive `ALTER TABLE` in each module's own `init()` — the `preprod.py` pattern already used
      for `picked_at`. No migration framework, no destructive change.
- [ ] Backfill every existing row to the bootstrap account so current data keeps working.
- [ ] Index `(account_id, id DESC)` on `shoot_concepts` — it's the shape every list query uses.

**Decide first:** is the tenancy boundary the **account** or the **brand**? Today `brand` is the
only scoping dimension and `antihero` / `zeropage` are two brands of one operator. An outside user
needs their own brands, so `account_id` is the real boundary and `brand` becomes a dimension
*inside* it. Getting this backwards means doing the pass twice.

## 2. Reads — no query returns another account's rows

- [ ] `list_concepts(account_id, ...)` — required argument, not optional with a default. An optional
      arg is a leak waiting for the one call site that forgets it.
- [ ] `get_concept(concept_id, account_id)` — returns `None` on mismatch, exactly as it does for a
      missing id. Don't distinguish "not yours" from "not found"; that difference is an enumeration
      oracle.
- [ ] Same treatment for locations, characters, props, generations, videos, holds, scene briefs.
- [ ] Audit every `SELECT` in `src/` for a missing `account_id` predicate. Grep for `FROM ` and read
      each one.

## 3. Writes — ownership set on create, checked on mutate

- [ ] Every insert stamps `account_id` from `auth.current_account`, never from a request parameter.
- [ ] `update_concept_shots`, `set_shot_media_url`, `delete_concept`, the verdict routes, director
      mode — all verify ownership before mutating.
- [ ] `delete_all_concepts()` with no argument currently wipes the whole table. Make `account_id`
      required.

## 4. Caps — per account, per day

- [ ] `runway._used()`, `veo._used()`, `midjourney._used()`, `nano_banana._used()` take `account_id`
      and add it to the `WHERE`.
- [ ] Keep a **global** ceiling as well as the per-account one. Per-account alone means ten users
      times six renders is sixty renders on your card.
- [ ] Decide whose key pays. Options: your key with a hard per-account quota (simplest for a pilot),
      or bring-your-own-key per account (no cost exposure, more onboarding friction). For 5–10
      invited users, your key plus a low quota is the right call.

## 5. Tests — the ones that would have caught this

- [ ] Two accounts, one concept each: A's list returns exactly one row and never B's.
- [ ] A fetching B's concept by id returns `None`.
- [ ] A's renders don't count against B's cap.
- [ ] A cannot mutate or delete B's concept.
- [ ] Regression test: assert no `SELECT` against an owned table lacks an `account_id` predicate.

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
