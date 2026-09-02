> **Superseded 2026-08-29.** The premise was wrong in an instructive way: it assumed the
> Studio's Create button should run the whole pipeline. Mike's call is the opposite —
> Create stops at the concepts board, the Director canvas does the rest by hand, and the
> *automation* is what runs end to end. So the node functions were extracted
> (`src/imagery.py`, `src/scene_chain.py`) and plugged into the StateGraph that already
> exists (`src/orchestrator.py`'s new `keyframe` node) rather than into a new one. The
> checkpointer and the `interrupt()` were not built — see BACKLOG item 9 for why, and
> `docs/ARCHITECTURE.md` for what runs now. The Runway anchor fix and the
> keyframe-before-spend gate did ship. Kept for the reasoning, not as a plan.

# Task — put LangGraph under the Studio's render path

## The mistake to avoid first

The obvious move is to route `POST /api/pipeline/run` through `src/orchestrator.py`. **Don't.**
That graph is the *autonomy* path: channels, kill switch, hold queue, dead-man log, a `publish` node
that parks on purpose. A person standing in the Studio pressing Create wants none of it. Wiring the
request path through autonomy gates means every interactive generation acquires machinery designed
for unattended overnight runs.

The two paths should stay two paths. What they should *share* is node functions, not a graph.

## What's actually wrong today

Three facts, verified on `main` 2026-08-27:

| Where | What | Consequence |
|---|---|---|
| `src/orchestrator.py:782` | `return g.compile()` — no checkpointer | No resume, no interrupt, no time travel. LangGraph is being used as a DAG runner. |
| `app/workflow_runner.py:293` | `execute_graph` runs Kahn topo-order straight through, in memory | A failure at the Runway node discards the Nano Banana Pro keyframe you already paid for. |
| `app/jobs.py:8` | "not Celery, not a table — a restart clears the queue" | Restart mid-render and the run is gone with no record of how far it got. |

And the one that matters most: **the keyframe approval isn't real.** The README says the clip starts
from "a still you already approved," but `execute_graph` runs every node in one pass — nothing
pauses to let you approve anything. The approval is a description of intent, not a mechanism.

## What LangGraph actually buys here

Not orchestration — you already have that. These four:

1. **A checkpointer** → resume a failed render without re-paying for the keyframe.
2. **`interrupt()`** → the keyframe approval becomes a real gate instead of a claim.
3. **`astream_events`** → native streaming replaces the hand-rolled `push(fraction, detail)`.
4. **LangSmith tracing on the path that does the work** — today only the nightly run is traced, so
   the untraced path is the one generating every video.

## The thing that makes this easier than it looks

The Director canvas is nominally an arbitrary user-wired graph, which sounds incompatible with a
statically-defined `StateGraph`. In practice it isn't: the active shot's chain is always the same
five nodes — prompt → instructions → enhance (Gemini 3 Flash) → Nano Banana Pro keyframe → Runway
clip. The arbitrary-wiring flexibility is theoretical.

So define that chain as a static graph, and keep the canvas as the *authoring and inspection*
surface over it. No dynamic graph compilation needed.

---

## Phase 1 — checkpoint the existing graph (half a day, zero behaviour change)

- [ ] Add `langgraph-checkpoint-sqlite` to `requirements.txt`. Pin `langgraph` too — it's currently
      unpinned, and this is a library that moves.
- [ ] `src/orchestrator.py`: `g.compile(checkpointer=SqliteSaver.from_conn_string(...))` against
      `data/pipeline.db`, the DB everything else already uses.
- [ ] Every invocation passes `config={"configurable": {"thread_id": run_id}}` — you already mint a
      `run_id` in `planner`, so use that.
- [ ] Verify: kill a run mid-flight, re-invoke with the same `thread_id`, confirm it resumes rather
      than restarting.

Do this first because it's isolated, reversible, and proves the checkpointer works before anything
depends on it.

## Phase 2 — extract the node functions (the real work)

The five canvas operations in `workflow_runner.py` are already nearly pure — inputs in, dict out.
Lift them so both executors call the same code.

- [ ] New `src/nodes.py`: `ground`, `enhance`, `nano_keyframe`, `runway_clip`, each taking a state
      dict and returning a partial state dict — LangGraph's node signature.
- [ ] Move the hard-won details with them, unchanged: `fetch_image_bytes` (SSRF guard, `image/*`
      only, size cap), `REFERENCE_NOTE`, `as_still_frame()`, and the same-model retry on
      `RESOURCE_EXHAUSTED` / `UNAVAILABLE`. **These are the bugs already paid for — do not
      reimplement them.**
- [ ] `workflow_runner.execute_graph` keeps working, now delegating to `src/nodes.py`.
- [ ] Tests pass unchanged. If they don't, the extraction changed behaviour.

## Phase 3 — the render graph, with the approval gate

- [ ] `src/render_graph.py`:

```
enhance ──▶ nano_keyframe ──▶ [interrupt: approve?] ──▶ runway_clip ──▶ attach
                    ▲                    │
                    └──── regenerate ◀───┘
```

- [ ] `interrupt()` before `runway_clip`, surfacing the keyframe URL. Three resume options:
      **approve** (proceed), **regenerate** (loop back to `nano_keyframe`, optionally with an edited
      prompt), **abandon**.
- [ ] Resume with `Command(resume={"decision": ...})` keyed on the same `thread_id`.
- [ ] The interrupt is the whole point: Nano costs cents, Runway costs real money. Never spend the
      second without a human confirming the first.

## Phase 4 — wire it to the UI

- [ ] `app/jobs.py` gains a **persisted** interrupted-run record — a small SQLite table, not the
      in-memory registry, since an awaiting-approval run must survive a restart. The existing
      "restart clears the queue" posture is fine for progress, wrong for a paused run.
- [ ] Stream `astream_events` into the existing SSE feed rather than manual `push()`. Keep the wire
      format identical so the front end doesn't change in this phase.
- [ ] Canvas renders the interrupt as what it already looks like: the keyframe, an Approve button, a
      Regenerate button.
- [ ] `LANGSMITH_TRACING=true` now covers the request path.

## Phase 5 — reconcile the divergences

Only once the above works. Both are recorded in `docs/ARCHITECTURE.md`:

- [ ] `gen_concept` still calls the legacy multi-shot `shootgen.generate_concept`; the Studio moved
      to one-scene-one-prompt on 2026-08-26. Point it at `generate_scene_concept`.
- [ ] `ensure_locations` still hard-fails a run with no described location, though grounding went
      opt-in everywhere else. Make it advisory, consistent with degrade-don't-break.

---

## How to know it worked

Not "LangGraph is integrated." These:

- Kill the process during a render; restart; the run resumes and the keyframe is not regenerated.
- A Runway failure leaves the approved keyframe attached to the shot, and retrying doesn't re-bill
  the image call.
- Every Studio generation appears in LangSmith with per-node timings.
- No render spends Runway credit without a human having approved the still.

## Out of scope

Dynamic compilation of arbitrary user-drawn graphs, multi-shot scene chaining, swapping `jobs.py`
for Celery. The chain is five fixed nodes and a scene is one shot — build for that, and revisit if
either stops being true.

## Honest cost

Phases 1–2 are low-risk and independently valuable. Phase 3 is where it gets real, and the interrupt
is a genuine behaviour change: renders stop being fire-and-forget and start requiring a person. That
is the correct trade for paid renders, but it is a trade — and if the tenancy pass
(`task-account-tenancy.md`) is the actual gate to a pilot, that one ships first. This makes the
product better; that one makes it showable.
