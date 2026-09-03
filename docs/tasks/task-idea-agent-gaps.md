# Task — close the four idea-agent gaps

Found 2026-09-02/03 running spark #38 ("Sixteen Missed Calls") end to end from a
phone-linked Cowork session, against `claude/pilot-dry-run`. Board at the time:
**52 generated, 4 picked, 0 shot**, 45 archived, 2 parked.

**Status 2026-09-03: all four closed on `main` (`9786b06`, `3765c02`, `6dde8ea`,
`b01dab2`; merged as a fast-forward, pushed). §3's diagnosis and §4's were wrong
in the ways their sections now say. One leftover (#135's spark) still needs a
hand.**

**The headline: three of these four are exposure gaps, not missing machinery.**
`preprod.mark_shot()` and `archive_idea(reason=...)` already exist and work —
the MCP tool surface just doesn't reach them. Read §1 and §4 before assuming
anything needs building.

## Already done — do not redo

| Thing | Evidence |
|---|---|
| Local-file route into the ref bin | `ops/ingest-saved-images.py`, takes `--pass-id`. It is what `bank_reference`'s URL-only signature implies is missing. |
| `shot_done` storage + setter | `preprod.mark_shot()` (`src/preprod.py:1182`), column at `:54`, index at `:84`, read by `shoot_rate()` `:1194` and `_status_of()` (`src/mcp_server.py:80`). |
| Archive reasons | `archive_idea(idea_id, archived, reason="")` (`src/mcp_server.py:307`), added 2026-09-01, feeds `avoid_guidance`. |
| Keyframe rendering | #167 parked with `"keyframe rendered — approve in the Queue to spend on the clip"` and a live R2 URL. Only the **clip** step lacks a renderer. |

## Contracts to preserve

1. **`pick` never spends.** It marks a concept as worth rendering and puts it in
   front of the Queue's gate. Nothing added here may call a renderer.
2. **Archiving hides, never deletes.** An unpicked row is the only negative
   signal this system collects.
3. **A reason is never a gate.** Per `archive_idea`'s docstring: an archive that
   fails because nobody picked a word is an archive that does not happen.
4. **References are an enhancement, never a gate** — the standing rule in
   `refbin`. Nothing below may fail a run for want of a photo.

---

## 1. Expose `shoot()` on the MCP surface  — highest priority, ~10 lines — **DONE 2026-09-03 (`9786b06`)**

Every piece is currently produced by hand in Mike's own studio. The one thing
the system most needs to learn — what actually got made — is the one thing it
cannot record. `shoot_rate` has read 0.0% across 52 concepts while work ships.

`preprod.mark_shot()` already does the write. Add the wrapper beside
`pick_idea` (`src/mcp_server.py:293`) and the tool beside `pick`:

```python
def shoot_idea(idea_id: int, shot: bool = True, path=db.DB_PATH,
               account_id: Optional[int] = None) -> dict[str, Any]:
    """Record that this one actually got made -- by any means."""
    account_id = _account(account_id, path)
    preprod.mark_shot(int(idea_id), shot=shot, path=path,
                      account_id=account_id)
    return _card(preprod.get_concept(int(idea_id), path=path,
                                     account_id=account_id))
```

**Settle the definition in the docstring: `shot` means made by any means** —
render lane, Higgsfield, own studio, a camera. If it comes to mean "a render
came back", manual production stays invisible and the column keeps lying.

### Rejected — do not implement: binding `shot` to the Queue's approve button

- Misses the actual case: studio work never passes through the Queue.
- Approve *precedes* the output — it authorises a spend. Failed and discarded
  renders would all count as shot.
- Couples the column to the renderer that is currently missing.

If a counter on approve is wanted, add a separate `approved` one.

**What was done** (`9786b06`): exactly the wrapper above beside `pick_idea`, and
a `shoot(idea_id, shot=True)` tool beside `pick`, annotated as a non-destructive
write with only `idea_id` and `shot` published. The docstring settles the
definition as written here — made by any means, not "a render came back", and
not bound to approve. Tests pin that `shot` outranks `picked` on the card, that
`shoot_rate` moves while `generated` does not, that `shot=false` falls back to
the pick, and that a bad id is a caller error. The connect guide's tool table,
CLAUDE.md and the idea-agent skill ("when he says he made one") name it.

---

## 2. `generate` cannot be handed reference images — **DONE 2026-09-03 (`3765c02`), both fixes**

`orchestrator.py:287` → `bin_for_finding`; `scene_chain.py:355` →
`bin_for_pass`. The graph reads reference photos from the **spark's bin**, keyed
`agent-<finding_id>`, which is where `bank_reference` writes.

**The Studio composer does not write there.** Four images uploaded before a run
on 2026-09-02 left the newest `scout_bin` row at id 39 from 14:58 — hours
earlier. The files hashed into `data/refs/` at 23:49 and rode into the shot's
`refs` list directly.

Consequences: `spark_images(38)` reads 0 no matter how much Studio uploads, and
`generate(spark, brand, goal)` has no refs parameter, so a remote agent cannot
give a run references at all. Ideas #171/#172 only have theirs because they were
started in Studio.

Fix, either:
- a `refs` argument on `generate` that banks to `agent-<finding_id>` first; or
- have the composer also write `scout_bin` rows against the matching finding.

The second is better — it makes one path true for both doors.

**What was done** (`3765c02`): both, because they are the two halves of one
rule — the references behind a direction live in the spark's bin, whichever door
wrote them and whichever door reads them.

- *The MCP door reads the bin.* `run_graph` takes a `finding_id` and `generate`
  exposes it. `mcp_server.resolve_finding` names the finding from that id or by
  matching the spark text on `_spark_key` (the composer's `claims` rule), so
  `add_spark` → `reference` → `generate(spark)` works without carrying an id
  between calls. The bin becomes `reference_photos`; a new
  `orchestrator.run(scout_finding_id=)` carries the id so `planner` claims the
  finding under the run's id and the hold card records its origin. A reworded
  spark passed with a `finding_id` is **refused** with a message rather than
  silently stripped of the photos the way the composer does it — an agent acts
  on text where a person would see a tile vanish. Brand defaults to the
  finding's; a mismatch is a caller error. Both are raised before the job
  starts, so they arrive as tool errors, not failed jobs to poll for.
- *The composer writes the bin.* When a Create IS the spark (`claims` true),
  `scout.bank_urls` banks every uploaded `/refs/` photo under the finding with
  lane `composer`, before the job runs, so a generation that writes nothing still
  leaves the photos behind the spark. Asset-bank picks are excluded — a room or
  the cast is grounding the graph adds for itself. `scout.pass_id_for` is now the
  one place "which pass" is decided; `bank_reference` uses it.
- Not verified live: a real `generate` from a phone against a banked spark (needs
  the engine flag and a Gemini call; credits were depleted that night).

---

## 3. ~~MCP `generate` stops short of judge and keyframe~~ — the diagnosis was wrong

**Corrected 2026-09-03, after reading the rows instead of the cards.** Nothing in
`run_graph` returns early. Two things were being read as one.

**#169–#172 were not MCP runs.** They were written in identical-timestamp pairs
(23:50:04 and 00:15:35) sharing one `prompt_hash` per pair, with no
`written_prompt` on the shot and no `hold_queue` row. That is the shape of
Studio's Create with a count of 2 (`generate_scene_concepts` → `scene_chain.run`).
The graph writes ONE concept per run and `_park` runs on every terminal edge, so
a graph row always has a hold row. Create stops on the board by design (Mike's
call, 2026-08-29): those four were never scored, and were never supposed to be.

**`judge_overall` is not the graph's score.** It is the Dev Studio's MANUAL
taste judge (`/concepts/{id}/grade` and `grade_all`); no automated path has ever
written it. #167's 7.0 is a click, not a verdict, and every graph row reads null
there however the run scored — #173 held at the prompt gate on 5/10 ("too many
sequential character actions") and #174 passed on 7/10 with a keyframe, and both
showed `judge_overall: null`. The graph's real verdict lives in `prompt_scores`
(by `run_id`) and in the hold row's `reason`, and neither reached the MCP surface.
So the two consequences stated above were half right for the wrong reason:
a Studio row cannot park in the Queue from generation (it parks when picked),
and NO row could be read as "scored badly" over MCP — graph rows included.

**What was done instead** (`6dde8ea`): `idea` now carries `origin`
(`graph` / `studio` / `capture`, derived from whether a hold row exists) with a
note saying what a null judge means for that origin, and `gate` — the prompt-gate
score, pass/fail, the judge's reason, every score the run logged (so a rework's
effect is visible), and how the run ended — read by `autonomy.hold_for_concept`
and `prompt_scores_for_run`. `generate` returns the same `gate` with the run, so a
held run needs no second call. `judge_*` keeps its name and its meaning. Verified
on a copy of the live database: #169 → `studio`, no gate; #173 → `graph`, 5/10,
failed; #174 → `graph`, 7/10, passed.

**Rule for reading the board from now on:** read `gate`, never `judge_overall`;
a `studio` row with no gate is unscored, not scored badly.

---

## 4. ~~Expose `reason` on the `archive` tool~~ — was already exposed; the description was the gap

**Corrected 2026-09-03.** By the time this was picked up, the MCP `archive` tool
on `main` already passed `reason` through to `archive_idea`. What was wrong was
its **description**: it named "boring, off-brand, unshootable, seen it, other" —
the vocabulary the Grade tab retired on 2026-09-02 — and an agent writes what the
description names. The live tally held 1 `boring` and 7 `other` beside 9
`weak concept`, and the counted vocabulary is
`preprod.ARCHIVE_REASONS` = weak concept · no turn · no stake · off-brand ·
unshootable · seen it.

Live damage stands as written: #169, #170 and #172 were archived from a phone
for **no turn** — a word that IS in the vocabulary — and recorded nothing.

**What was done** (`b01dab2`):

- The tool description is built from `preprod.ARCHIVE_REASONS` and passed to the
  decorator (the SDK reads the docstring at registration, so setting `__doc__`
  afterwards is silent — found by the test, not by reading). A test asserts every
  counted word is in the published description and the retired ones are not.
- A reason outside the vocabulary is still recorded as given — never a gate —
  but the returned card carries a `reason_note` naming the counted words, because
  the tally counts words and a bucket of one teaches nothing.
- #169, #170 and #172 were backfilled by hand on the live database: the reason
  column only, `archived_at` untouched. #171 is picked, not archived, and was
  left alone.
- The idea-agent skill gained a "when he kills one" step with the vocabulary and
  the rule that an archive never waits on a word.

---

## Leftovers — cleared 2026-09-03 (one still open)

- ~~`data/_agent_inbox/`~~ — the three Midjourney stills are banked under
  `agent-38` (`scout_bin` 40–42, lane `saved`, source `midjourney`) via
  `ops/ingest-saved-images.py … --pass-id agent-38 --source midjourney`, and the
  folder is gone. Spark #38 has images behind it for the first time.
- ~~Orphans in `data/refs/`~~ — **there were none.** `2efac6ac…` and `f6a45132…`
  WERE `mj_cavity_hand` and `mj_torn_wall`: `refbin` is content-addressed, so the
  ingest hashed the PNGs to the same names and gave them the rows they lacked.
  `ea485359…` is `mj_phone_uplight`, already live on #169–#172 and now banked
  too. All three stay. The lesson: a `/refs/` file with no row is an upload that
  never got banked, not junk — check the inbox before deleting.
- ~~`data/pipeline.db.bak-before-agentrefs-2153`~~ — the file was
  `…-agentrefs-2346`; deleted after the full suite passed on the merged tree and
  the live rows read back correctly. Eight older `pipeline.db.b*` backups from
  August remain — not in scope here, but nothing on them is newer than `main`.
- **#135's spark — still open, needs a hand.** The first line, "3am and the
  house is awake", is the real spark; the ~1,200 chars after it are the
  `avoid_guidance` scaffolding the pre-2026-09-01 graph stored in the column.
  Every lesson in that tail is already in `winning_prompts` under `didnt_work`
  (checked 2026-09-03), so the tail can simply go. The write to the live
  database was refused by the session's permission classifier, so run it by
  hand:

  ```bash
  sqlite3 data/pipeline.db \
    "update shoot_concepts set spark='3am and the house is awake' where id=135;"
  ```

## Out of scope

- The clip renderer behind the Queue's spend gate. Separate piece of work.
- The two parked items (#167, #135). **Do not archive them** — they were never
  tested, and a false archive poisons the only negative signal there is.
- SQLite writes over the Cowork folder mount. Not fixable in this repo:
  reads work read-only, writes fail `disk I/O error` because the mount does not
  provide the locking SQLite needs.

## Order

§1 first — smallest, and it is the only thing that lets the system see the work
Mike is actually making. §4 next, same shape and one line. Then §2, because
references are what separate #171 from the 48 rows before it. §3 last — and it
turned out not to be a bug in `run_graph` at all (see the corrected §3).
