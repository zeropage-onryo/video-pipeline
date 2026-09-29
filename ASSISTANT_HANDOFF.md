# Handoff: the assistant pill (brain done, UI next)

Read this whole file before you start. Rules that apply the whole way through:
- CLAUDE.md is in force. **Verify by running things, not by reading code.**
- Nothing may spend credits without a person's click.
- Pick images by candidate id. Never use a raw URL.
- A face never comes from the web. Faces come from Elements.
- Don't touch Mike's uncommitted work in this checkout. The current branch is `fix/mcp-as-discovery` and it has dirty files. Do everything in a separate worktree.

## 0. What this is

Mike wants something like invideo's guide: a named personal assistant that lives in a **floating pill** in the bottom-right corner of every studio page. A small emoji avatar sits above the pill, and tapping the pill opens a floating card. The assistant walks the person through seven steps: brief → story → cast → references → shots → stills → clips. **The existing studio design stays as it is. The only addition is the pill.**

Mockup: the Design canvas "ZPF Guided Studio" (claude.ai/artifact/V1ah7SHDZd8mCqDiR1Sspq). Its frames:
- Name your assistant
- The pill on the Studio page
- The pill opened, filling in the composer
- The pill pulling references
- The pill on the Queue, showing credits
- Phone

Spec: `claude/guided_project_spec_2026-09-26.md`. Backend notes: `claude/assistant_brain_built_2026-09-26.md`. Both are docs in the Claude project; the essentials are copied below.

## 1. Land the backend (already written and tested, not pushed)

The patch is at `data/_to_delete/brain/0001-assistant-brain.patch`. It is based on HEAD `eb2fd9f`, the tip of `fix/mcp-as-discovery`. That branch is the base because the reference modules exist only there, not on main.

```bash
git fetch origin
git worktree add ../zpf-assistant-brain -b feat/assistant-brain eb2fd9f
cd ../zpf-assistant-brain
git am "../PRODUCTION PIPLINE .GIT/data/_to_delete/brain/0001-assistant-brain.patch"
# run the suite the way CI does (throwaway Postgres; see docs / tests/conftest.py)
pytest tests/ -q -n 8     # expected: all green; baseline had 2537 passed / 8 xfailed with Mike's WIP applied
ruff check src app tests ops
git push -u origin feat/assistant-brain
# open a PR against fix/mcp-as-discovery
```

(`push-assistant-brain.command` at the repo root does the same steps. Use either one, not both.)

What the patch adds:
- `src/assistant_brain.py`, which provides:
  - **Persona:** `clean_name` and `clean_tone` (tone is one of direct / friendly / hype; there is no free-text personality).
  - **Steps and pages:** `clean_stage` and `clean_page`.
  - **Playbooks:** `playbook(stage)` returns the instructions for one step.
  - **Model choice:** `pick_brain(requested, stage, msg)`. With `auto`, story and shots use reasoning, and so does any message asking for something to be written; everything else uses fast. An explicit pill choice always wins.
  - **Memory:** `memory(brand, account_id)` gathers the brand's look, the anti-reference list, and board picks and passes, read through `taste_judge.gather_signals`.
  - **Tools:**
    - `find_references` is a READ tool. It runs `reference_needs.plan` → `imagesearch.search` → `refcheck.screen`, banks nothing, and costs 0 credits.
    - `keep_references` is a WRITE tool that runs only on a person's click. It runs `imagesearch.get` → `refbin.fetch` and returns `/refs/<sha>.jpg` paths.
  - **Grading:** `check_directions` grades each story direction with `story_judge` and sorts best first.
- `prompts/assistant_brain.txt` (how the assistant works each turn) and `prompts/stages/*.md` (seven playbooks).
- `src/creative_guide.py`:
  - `Answer` gains `questions[{ask, options≤3}]≤3`, `directions[{title, logline, turn}]≤3`, `nudge` and `stage`.
  - `Reply` gains `sheet` (the contact sheet) and judged `directions` (`score`, `verdict`).
  - `respond(..., assistant=dict, judge=)` adds the assistant behaviour.
  - Personal providers use a recursive strict schema. Non-assistant turns keep the old three fields.
- `src/guide_tools.py`:
  - Adds `LOCAL_READ` / `LOCAL_WRITE`.
  - `session(local=True, brand=)` works even without the `mcp` package.
  - `run_tool.attachments["sheet"]` carries the contact sheet back to the reply.
  - `check_args` now also refuses URLs hidden inside list arguments.
- `app/api.py`:
  - `POST /api/creative-guide` accepts `assistant=1`, `assistant_name`, `assistant_tone`, `stage`, `page` and `brain=auto`. **Without `assistant=1`, it behaves exactly as before.**
  - `POST /api/creative-guide/act` with `keep_references` returns `{kept:[{id,url}], refused}`.
- `tests/test_assistant_brain.py`, 49 tests.

**Not yet verified live:** no real Gemini call has been made. Once the patch has landed, run one live turn against a local server:
- `assistant=1`, `stage=references`, message "find me refs for a bartender closing a neon dive bar at 2am".
- Check that `reply.sheet` has keepers and rejected frames with reasons.
- Check that `reply.message` contains no URLs.
- Check that Keep → `/act` returns `/refs/…` paths that the composer accepts as `asset_photos`.

Separate fix: Mike's uncommitted `src/reference_hunt.py` has an unused `from typing import Optional`, which will fail ruff once that WIP is committed. Tell him about it; don't edit his dirty tree.

## 2. Build the pill (the next piece of work)

This is the Next.js app under `web/`. Mount one component in `web/src/app/studio/layout.tsx` so every studio page gets it. Follow the live /studio look:
- Near-black textured background, red `#e4002b` accent.
- Oswald uppercase headings.
- Rounded cards (about 16–26px radius) and pill buttons.

Collapsed state:
- The pill sits bottom-right, about 58px tall, with a red border and a soft red glow.
- A 56px round badge holding the emoji avatar overlaps the pill's top-left corner.
- The pill's text is `<Name> · Step N of 7` on one line, with `nudge` below it. With no project open, the second line reads "Start a project, or ask me anything".
- An occasional speech bubble can appear next to the avatar.

Opened state:
- A floating card about 400px wide, with the avatar on top.
- The card shows:
  - the name and the page it's on
  - seven thin step bars
  - `questions` rendered as chip rows (tapping a chip sends it as the next user message)
  - `directions` as selectable cards showing the judge's score
  - `sheet` as a contact sheet: kept frames selected, rejected frames greyed with their `why`, one click to override
  - a chat input
- **Keep** posts `/api/creative-guide/act {tool:"keep_references"}`, then adds each returned `url` to the composer's picks. Those go out as `asset_photos`: that is the composer's reference contract (`appendReferences` in studio/page.tsx; `_collect_refs` reads `files` and `asset_photos`).
- Picking a direction puts its text into the Studio composer, shows a "Filled by <Name>" tag, and puts a red ring on the **Create** button. **The assistant never presses Create or Approve.**

Every turn sends the conversation plus `assistant=1`, `page=<pathname>`, `stage`, `assistant_name`, `assistant_tone` and `brain=auto`, along with the header in `GUARDED_HEADERS` (`X-ZPF-Model-Connection`, or the route returns 403). The endpoint is job-based: poll `/api/jobs/{id}` and show its `detail` while it runs. `studio-api.ts` already has the Guide helpers; extend them rather than duplicating them.

**Credits:** anywhere the assistant mentions a cost, show credits, never dollars. Use `pricing.display().credits` from the server quote, the same way the Queue's credit button does on branch `feat/studio-credits`. Also:
- Short balance: "Need N cr · have M", plus Buy credits.
- Exempt account: "Not charged".
- BYOK (the person's own API key): "~$x on your key".

Setup screen ("Meet your assistant") collects a name, an emoji (a few presets or any emoji) and a tone (three presets). Store them per account. Adding a small `assistants` table (`account_id`, `name`, `avatar`, `tone`) with tenant scoping via `Depends`, following `account_scoping.md`, is fine. Until it's wired, localStorage is fine for the setup screen.

Phone: the pill spans the full width at the bottom with the avatar above it, and tapping it opens a bottom sheet.

Make sure the pill never covers the Queue's approve bar or the Director canvas controls; move it aside when it would.

## 3. After that (don't start without Mike)

- A `projects` table plus `project_stages` so the step survives a reload.
- Keep/reject teaching: store a person's click against refcheck's verdict.
- Cast sheets, playbook presets (Ad first), and Assemble.

## Definition of done for step 2

- `next build` and eslint are clean.
- Screenshots of the pill at 1440px and 390px on Studio, References and Queue, closed and open.
- One real turn per step type:
  - a question turn with chips
  - a directions turn (with judge scores)
  - a find → keep turn that attaches references to the composer
- Nothing spends credits without a click.
- Report to Mike in plain language, then stop.
