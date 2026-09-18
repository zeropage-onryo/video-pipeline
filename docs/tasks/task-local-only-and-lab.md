# Local-only, and the Lab

**Written 2026-09-14.** Two jobs that look like one: (1) bring every byte of this
pipeline home so it runs with no cloud store behind it, and (2) build a SEPARATE
app beside the Studio for the data / training / looping side.

Mike's framing, verbatim: *"I just want it to retrieve all the data locally and
can only be run on my computer, I want to create a better app/crm for it — for
data, training, and looping. It's a separate crm/app from the actual studio."*

Settled up front:

- **One database, two apps.** The Studio writes concepts, picks and renders; the
  Lab reads those same rows to grade, score and teach. Not two stores.
- **The Lab covers four things:** grade what the machine made, run and read the
  evals, feed the reference library, watch the numbers.

---

## The honest part first

The UI is not the bottleneck and a nicer one will not fix the thing that is
actually wrong. Read off the live database today:

| | |
|---|---|
| concepts written | 254 |
| archived with a reason | ~178 |
| **picked** | **4** |
| scored by the taste judge | 0 |
| golden eval cases | 8 |
| recorded eval runs | 1 |

The feedback data is thin. Eight golden cases and one run cannot tell you whether
a change helped — a prettier chart over that is a prettier chart over noise. So
the Lab earns its keep on exactly one measure: **does it make grading fast enough
that you actually do it.** Everything below is designed around that, and the
numbers screen is the last thing built, not the first.

---

## Phase 1 — the data comes home

Smaller than it looks. The live Supabase store is **24 MB across 39 tables**.

| step | what |
|---|---|
| 1 | `pg_dump` Supabase to a dated file. Keep it — this is the rollback. |
| 2 | Local `zeropage` db on the Homebrew `postgresql@17` already running on the Mac, `CREATE EXTENSION vector` |
| 3 | `pg_restore` |
| 4 | Flip `DATABASE_URL` and `RAG_DATABASE_URL` in `.env` to `postgresql://localhost/zeropage` |
| 5 | Verify by count, not by vibe: 254 concepts, 522 rag chunks, 2205 llm_calls, 313 holds |

Note `SUPABASE_RAG_DATABASE_URL` stays in `.env` as the address of the backup,
commented, so the way back is written down rather than remembered.

## Phase 2 — cut the last cords

**a) The reference photos — 93% of this is already done and nobody noticed.**

185 unique reference / keyframe / clip URLs are stored on concepts. **172 of them
already have their bytes on the Mac.** Only **12 are missing**, all on concepts
351 / 353 / 361, and CLAUDE.md already records some of those as pointing at bin
files that exist nowhere.

The URLs themselves still say `https://pub-62d6…r2.dev/…`, which is a string
problem, not a bytes problem: `asset_shelf.r2_key` maps a local path to an R2 key,
so running it backwards is deterministic.

- `ops/localize_shot_refs.py` — the mirror of the existing `canonicalize_shot_refs.py`.
  Reports first, `--write` to act. Rewrites an R2 URL to its local route **only when
  the local file is really there**, exactly the rule the forward pass used.
- **Fetch the 12 missing files BEFORE anything is torn down.** The bucket is public
  and reachable today; it will not be after.
- R2 credentials are already gone from `.env`, so `storage.configured()` is False
  and nothing has been mirroring up for a while. Going local ratifies a state the
  machine is half in already.

**b) Sign-in.** `/ui` and every `/api` route require a Supabase session, and
Supabase Auth needs the network. A machine-only app does not want an identity
provider. Add a `ZEROPAGE_LOCAL=1` posture that resolves every request to the
bootstrap account — the same degrade `auth.dev_account_id` already does for the
dev console, and for the same stated reason. Contained in `app/auth.py`; the
multi-tenant path stays intact underneath for any future pilot.

**c) The deploys.** Stop `zeropage-studio` and `zeropage-web`. Keep the dump.

**What still needs the internet, and always will:** the model APIs — Gemini,
Runway, fal, Higgsfield. Local means the *data* is yours, not that the renderers
are.

## Phase 3 — restyle the Dev Studio (NOT a new app)

**Corrected 2026-09-14, Mike:** *"I believe there's already a studio dev I just
want to make it more appealing the frontend of it."* There is no second app. The
Dev Studio at `/studio` already carries all four surfaces — Stats, Grade, Teach,
RAG Library, Settings, Dataset. The job is the frontend.

**The diagnosis, and it is not a matter of taste.** The brand identity is already
in the repo and the app skin threw it away:

- `app/static/style.css` — near-black, **film grain overlay**, **Bebas Neue**
  display over IBM Plex Mono labels, bone `#CDC9C0` text, hot red `#E23B2E`.
  A real film-noir identity.
- `app/static/skin.css` — the `.sk` system every engine page actually uses. Same
  red, same mono, but Helvetica Neue for everything, no display face, no grain.
  Generic dark admin panel.

So the Dev Studio inherits a competent but characterless skin while the studio's
own identity sits unused one file over. Reclaiming it is the single biggest move
and costs nothing new.

**What else is wrong, structurally:**

- Six tabs as horizontal pills push the content down and carry no counts — you
  cannot see from the tab bar that 184 concepts are waiting.
- Every block is the same panel at the same weight, so nothing leads. The page
  opens on DISTRIBUTION (a zero) rather than on the thing that needs him.
- Grade is a stacked list, not a working two-pane surface. It should be queue on
  the left, card on the right, keyboard-driven.
- Stat tiles use the body face; numbers are the point of that row and should
  carry the display face.

**The pass:**

1. Rail instead of pills — persistent, with live counts (Grade 184, Library 522).
2. Lead the Stats tab with what is actually waiting, red-accented, one button in.
3. Bebas for page titles and stat numerals; grain overlay back; bone for display.
4. Grade becomes two panes with `A` / `T` / `P` / `→` bound.
5. Honest empty states that say what a zero means instead of showing a blank box.

Mockup published for review before any template is touched. The CSS ports
straight into `skin.css`; the markup changes are `dev_studio.html`,
`_dev_grade.html`, `_dev_graded.html`, `_dev_library.html`.
