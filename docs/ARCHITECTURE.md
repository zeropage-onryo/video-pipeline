# Architecture

How ZPF Studio actually runs. Two paths, deliberately different: a **request path** that a person
triggers and waits on, and an **autonomous path** that runs unattended overnight with gates the
request path doesn't need.

Start with the request path — it's the one that produces every video today.

**Contents**
- [The request path](#the-request-path) — Create button to finished clip
- [The LangGraph orchestrator](#the-langgraph-orchestrator--the-autonomous-path) — the autonomous run
- [Known divergences](#two-known-divergences-between-this-graph-and-the-product)

---

## The request path

What actually happens when you press Create in the Studio. No graph, no autonomy gates — a straight
line, because a person is standing there waiting for it.

```
/ui composer ──▶ POST /api/pipeline/run
                      │
                      ├── api.scene_grounding: reference_block (RAG) + the brand's inspiration lanes
                      │
                      ▼
              shootgen.generate_scene_concepts(idea, brand, count)
                      │   several scenes, ONE call, so they vary against each other
                      ▼
              saved as ordinary shoot_concepts rows (shots = one element each)
                      │
                      │  you pick one ──▶ picked_at ──▶ pick_rate
                      ▼
              Director canvas ── app/workflow_runner.py executes node by node
                      │
                      ├─ enhance (Gemini 3 Flash, system prompt from prompts/enhance_system.txt,
                      │           auto_ground pulls RAG + the shot's reference image as INLINE BYTES)
                      ├─ Nano Banana Pro ──▶ keyframe ──▶ attached to the shot as reference_image
                      └─ Runway ──▶ clip ──▶ attached to the shot as media_url
```

**Reference images are fetched, never named.** Neither model can retrieve a URL. Once renders moved
to R2 and every reference became an `https://…r2.dev/…` link, naming it in the prompt text silently
became no grounding at all — the model was told an image existed and never saw one.
`workflow_runner.fetch_image_bytes` pulls it server-side (SSRF-guarded, `image/*` only, size-capped,
never raises) and attaches real bytes with the mime read from the magic number. Attaching bytes is
only half of it: a `REFERENCE_NOTE` tells the model what the reference is *for* — match subject,
wardrobe, props, location; do **not** copy its framing — because bytes with no instruction leave it
guessing between copy, continue and ignore.

**Video prompts are converted before they reach an image model.** Every prompt this pipeline writes
describes video, and an image model handed camera moves and a 9:16 duration answers in prose
("Understood, I will apply these guidelines…") and spends a call returning no image. The pure
`as_still_frame()` runs first. The image call also carries its own retry on `RESOURCE_EXHAUSTED` /
`UNAVAILABLE`, deliberately on the *same* model — the shared fallback list is text models, which
cannot draw.


---

## The LangGraph orchestrator — the autonomous path

`src/orchestrator.py` is the autonomous content graph, registered as `"zeropage"` in
`langgraph.json` and traced to LangSmith. A rendered walkthrough of every node, edge, and
gate lives in [`docs/architecture.html`](docs/architecture.html) — open it in a browser.

```
planner -> ensure_locations -> ground_entities -> ground_rag -> gen_concept -> evaluate
                                                        ^______________|  (corrective retry)
evaluate --pass--> structure_prompt -> score_prompts -> generate_render -> qc_clip -> caption -> publish
                                            ^     |          \                \
                                            |     v           -> hold          -> hold  (dead-man log)
                                        revise_prompts
```

**Note:** this graph is the *autonomous* path — the nightly unattended run. It is **not** the path
the Studio uses. A Create button in `/ui` goes through `POST /api/pipeline/run` to the scene engine
directly; see [The request path](#the-request-path) above.

**Left third — grounding and ideation, live.** `planner` mints a run id and reads the
channel's autonomy setting; `ensure_locations` requires at least one described space on
file; `ground_entities` formats the picked (or all) characters/props into the `{cast}`
block; `ground_rag` queries the CRAG-graded reference library, degrading to an ungrounded
run with a note rather than failing. That shared CRAG function records score-only telemetry in
SQLite (never retrieved document text): first score, retry score, threshold, rewrite/re-query/adoption
decisions, and the versioned library fingerprint. `/studio` displays those private diagnostics while
`/ui` only consumes the resulting retrieval behavior. `gen_concept` calls `shootgen.generate_concept` and
folds any prior critique — plus any pending human corrections from `/holds` — into the
spark before generating. `evaluate` combines shootgen's code-enforced `warnings` with an
optional LLM-judge (`JUDGE=1`) and routes: pass moves on, fail retries `gen_concept` up to
`MAX_ATTEMPTS` (3), and running out of retries parks the run.

**Retrieval evaluation.** The Dev Studio runs every labelled golden query through both the base
one-shot retriever and the full CRAG path. It keeps score improvement separate from correctness:
a rewritten query may have a higher cosine score and still miss the expected source. Stored runs
therefore include base/CRAG Hit@k and MRR, re-query/adoption/success rates, expected-source rate,
and fingerprints for the golden set, configuration, and reference library. Deltas are only shown
when those identities match.

**Generated assets.** Successful Nano Banana and Runway calls write the normal `generations`
attempt row and a `generated_assets` Asset Bank row only after usable media exists. That second row
keeps the durable/local media URL, exact prompt, model, media type, and scene identifiers. Its prompt
description is indexed on the same RAG `assets` shelf used by photographed assets. Asset publication
is best-effort so SQLite or pgvector downtime cannot turn a completed paid render into a failed job.
The media API defaults to images for reference pickers; the Asset gallery explicitly asks for all
media so Runway clips are browseable without being passed into image-only inputs.

**The credit gate.** `structure_prompt` extracts each AI shot's paste-ready prompt;
`score_prompts` runs every one through a two-layer judge — a zero-cost structural check,
then a strict LLM rubric (subject/camera/motion/lighting/coherence, 0–2 each, bar
`PROMPT_GATE_MIN`) that fails closed, so an unreadable verdict scores 0 rather than
passing by default. Every score is logged before a credit could be spent. All prompts in a
run must pass or the whole run holds — no partial renders.

**The render and posting line.** `generate_render` dispatches on the shot's tool through a connector
map — `{"VEO": veo, "RUNWAY": runway}`, Runway wired 2026-08-12 — and only fires for real when
`ZEROPAGE_RENDER=1`; otherwise every clip returns `ok=False` by design, and an unadapted tool stays
honestly dry. `qc_clip` checks
the file is really there and really a video (size, `ffprobe` duration) before allowing a
caption. `publish` reads the channel's autonomy (`shadow` | `queue` | `auto`, never a
global flag) and the kill switch — no posting API is wired yet, so even an `auto` channel
currently parks with an explicit reason rather than pretending to post.

**The sink.** Five different failure points converge on one `hold` node, which inspects
state to write a human-readable reason to `autonomy.hold_queue` — the dead-man log every
run writes to, pass, fail, or crash. Grading a hold on `/holds` (approved/rejected) is what
earns a channel promotion toward `auto`.

**Two known divergences between this graph and the product**, recorded rather than papered over:
`gen_concept` still calls `shootgen.generate_concept`, the legacy multi-shot generator, while the
Studio moved to one-scene-one-prompt on 2026-08-26; and `ensure_locations` still hard-fails a run
with no described location, even though grounding became opt-in everywhere else. Both mean the
autonomous path can refuse work the Studio would happily do. Neither is load-bearing yet — the graph
parks at `publish` regardless — but they are the first things to reconcile before autonomy matters.

---

## Stale artifact

`docs/architecture.html` is a rendered node/edge diagram linked from earlier versions of this doc.
It predates both the Runway connector (2026-08-12) and the `revise_prompts` node — it contains
neither, and no reference to Nano Banana. Regenerate or delete it; a diagram that disagrees with the
code is worse than no diagram.
