# Remove the brand labels (scoped 2026-10-04, not started)

**Mike's call:** the brand concept goes entirely. The creative half is already
gone (2026-10-04: no brand look files, no brand notes, no `brands.txt`, no
`BRAND_NOTES`, no likeness path, no `HOUSE_LOOK`, no `ZEROPAGE_FORMATS`, no
`CAST_BRANDS`, no brand-keyed crawl queries, no Zero Page templates). What is
left is the LABEL: the strings `"antihero"` / `"zeropage"` (and `"both"`)
carried on rows, cookies, routes, loops and tests. This doc scopes removing it.
Nothing here is built yet.

## Two facts that shape the plan

- **The `brand` cookie is also the account switcher.** `app/auth.py`
  `current_account` matches `request.cookies["brand"]` against the user's
  account slugs (verified 2026-10-04); `POST /brand/{name}` sets it and
  `/api/me` reads it. Removing the cookie without a replacement removes
  account switching.
- **"zeropage" is not only the brand.** It is also the database name in the
  DSN (`src/db.py`), the Fly app names, the seeded account slug, every
  `ZEROPAGE_*` env var, the MCP server name and the wordmark. A blind
  grep-and-replace breaks all of those. The `antihero` ACCOUNT was deleted on
  2026-09-28, but most code still defaults a missing brand to `"antihero"`.

## Inventory (from a read-only survey, 2026-10-04)

| area | what carries the brand | size |
| --- | --- | --- |
| Database | `shoot_concepts.brand` and `scene_briefs.brand` (NOT NULL, `preprod.py`); `scout_findings.brand` + `idx_scout_brand_used`, `scout_bin.brand` (`scout.py`); `inspiration_accounts.brand` (allows `both`); `workflows.brand`; `videos.brand`; `channels` rows named `zeropage`/`antihero` with `hold_queue.channel` holding the name (`autonomy.py`); `generated_assets.project` filled with the brand (`render_assets.py`, `fal.py`, `ops/render_queue.py`). `scheduled_posts` has none. | 8 columns, 1 index, live rows |
| Constants | `preprod.BRANDS`, `inspiration.BRANDS` (+`both`), `scout.BRANDS`; `app/main.py` `BRANDS` / `DEFAULT_BRAND` / `BRAND_META`; `autopilot.AUTO_POST_BRANDS`; `ValueError` brand checks in preprod, shootgen, scout, inspiration; MCP `_check` calls | ~25 sites |
| Routes / cookies | `brand` cookie (1-year) via `POST /brand/{name}`; `?brand=` / form `brand` on `/api/pipeline/*`, `/api/scenes/run`, `/api/scout/*`, `/api/queue/*`, `/api/director/landing`, `/api/generate/run`, `/api/analytics/*`, `/api/workflows`, `/api/cut/ready`; `/api/holds?channel=` | ~30 sites |
| Pipeline | ~110 functions take `brand`: shootgen (`load_brand`, the `{brand}` slot, `ZEROPAGE_AI_TOOLS` branches), scene_chain, orchestrator (`state["brand"]`, `brand_gate` runs the uncanny judge on zeropage only, channel/brand coupling in `run()`), nightly (`PAIRS`, per-brand scout), trigger, research_agent (per-brand stamps), scout (`PINTEREST_BOARD_<BRAND>`, `scout_sources.txt` brand tags), imagesearch (per-brand subreddits), uncanny_judge, autopilot (`channel_targets`), rework, refgen, reference_needs (reads `anti_references_<brand>.txt`, none exist), assistant_brain, guide_tools, creative_guide | large |
| Accounts | `accounts.seed` makes slug `zeropage`; `RESERVED_SLUGS`; `invite --brand` is really the slug; `tests/conftest.py` still seeds an `antihero` account | small |
| Front ends | React: `shell.tsx` (brand = account slug; the switcher), `studio-api.ts` (`?brand=` on ~7 calls; `switchAccount` posts `/brand`), pipeline / queue / cut / elements / studio pages, assistant-pill, flow-workspace, director-arrival, concept-card, the Next proxy rule for `/brand`. Vanilla `/ui`: shared.js, app.js, analytics.js, queue.js, scenes.js, genspace.js, studio.js, pipeline.js; templates zpf.html, _rail.html, accounts.html, dev_studio.html | ~14 React files, ~10 vanilla |
| Tests | 85 of ~135 files mention a brand (some only the DSN); `tests/test_brand.py` is entirely this feature; heaviest: test_orchestrator, test_scout, test_api, test_scout_api, test_tenancy, test_scenes_pick, test_mcp_server, test_shootgen, test_preprod | large |
| Ops | `run_morning_prompts.sh` and `ops/fly/run-nightly.sh` loop `for BRAND in antihero zeropage`; ops/bank.py, archive_ungrounded.py, render_queue.py, repair-missing-refs.py, billing_walkthrough.py, ingest-saved-images.py | ~10 scripts |

## Risks

- **Live data**: NOT NULL brand columns and the `channels` / `hold_queue` rows
  need a migration; other tenants' rows were labelled `antihero` by default.
- **The cookie/switcher coupling** (above).
- **External MCP clients**: `capture`, `add_spark`, `tonight`, `research` and
  `generate` take `brand`, some require it.
- **Env vars keyed by brand** (`PINTEREST_BOARD_<BRAND>`; check Fly secrets).
- **The uncanny judge** (kept by Mike's call) only runs for zeropage; with no
  brand it needs a new trigger or retirement, and `AUTO_POST_BRANDS` with it.

## Suggested order

1. Split account switching off the brand: an `account` cookie and route, with
   `/brand/{slug}` kept as an alias for a while. Update `auth`, `/api/me`, the
   React switcher, `accounts.html`, `app.js`, `_rail.html` and the proxy.
2. Make the server ignore `?brand=` and form `brand`; make MCP `brand`
   optional and ignored. Then stop the front ends sending it.
3. Strip `brand` from the pipeline (shootgen, scene_chain, orchestrator, scout,
   research, nightly, the shell loops, imagesearch). Decide `brand_gate` /
   uncanny judge and `AUTO_POST_BRANDS`.
4. Collapse `channels` to one and migrate `hold_queue.channel`.
5. Database last: stop writing, drop NOT NULL, then drop the columns and
   `idx_scout_brand_used`; redefine `generated_assets.project`.
6. Tests: delete `test_brand.py`, fix the conftest `antihero` account, update
   fixtures.
7. Clean up env vars, the research stamp files and the `scout_sources.txt`
   brand tags.
