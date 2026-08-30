#!/usr/bin/env python3
"""
src/scene_chain.py -- the stages a scene goes through, as functions.

    ground -> write_scenes -> attach_refs        [ Create stops here ]
        -> persist_prompt -> keyframe -> park    [ the nightly graph does these ]

One implementation of each stage, three callers (2026-08-29):

- **Studio Create** (`POST /api/scenes/run`) runs the first three and
  STOPS on the concepts board. A person pressing Create wants concepts
  to read, not a minute of billed work they did not ask for.
- **The Director canvas** does the rest by hand, node by node, when
  Michael is steering a particular scene.
- **The nightly graph** (`src/orchestrator.py`) does the rest by itself
  when nobody is watching: it scores each prompt at its own credit gate,
  and only the ones that clear it earn a keyframe and a place in the
  Queue with a still to approve.

That last one is the point. Before this the automation ended every run
with "no usable clips (render is a dry-run stub)" in the hold queue --
structurally complete, and nothing to actually look at in the morning.

Why the caller-side stages are functions and not graph nodes: they ARE
graph nodes, in the graph that already exists. `src/orchestrator.py`
calls them from its own StateGraph, which earns the framework (a retry
edge back into gen_concept, a rework loop, a hold sink reached from four
places). Making a second graph out of them for the request path would be
ceremony -- and the two app-layer capabilities they need (which asset
photos a scene named, and how to resolve a site-relative photo to a
file) are INJECTED as callables, because src/ never imports app/.
"""
from __future__ import annotations

from typing import Callable, Optional

from . import db, imagery, nano_banana, preprod, shootgen

# Enhancing and keyframing are per-scene model calls, so a batch of 4 is
# 4 of each. The cap that actually bites is nano_banana.DAILY_CAP (20/day,
# shared with every Director render) -- nothing here raises it, it just
# reports what it could not do.
MAX_SCENES = 4


def _note(notes: list, text: str) -> None:
    if text and text not in notes:
        notes.append(text)


def ground(idea: str, *, brand: str = "", db_path=None) -> dict:
    """The reference library and the cast, as plain text blocks.

    reference_block is the edge helper (never called from inside a
    generator, so the generators stay hermetic in tests) and never
    raises: no Postgres means an ungrounded run with a stderr note.
    Naming the cast is grounding too, and fails the same way -- softly.
    """
    path = db_path if db_path is not None else db.DB_PATH
    references = ""
    try:
        references = shootgen.reference_block(spark=idea or None, db_path=path)
    except Exception:
        references = ""
    cast = None
    try:
        from . import entities
        cast = shootgen.format_cast(
            entities.list_characters(path=path),
            entities.list_props(path=path), detail=True)
    except Exception:
        cast = None
    return {"references": references, "cast": cast}


def write_scenes(idea: str, brand: str, *, count: int = 1, references: str = "",
                 cast=None, refs=None, image_refs=None, db_path=None,
                 gemini_client=None, template_tag: str = "",
                 on_retry=None) -> dict:
    """N standalone takes on one idea, in ONE call so they are varied
    against each other rather than rolled independently. Raises: with no
    scene there is nothing to work on, and the caller must say so.

    `template_tag` rides into the hashed prompt template, so pick_rate's
    by_prompt breakdown can separate rows produced by different
    pipelines instead of averaging them into one unreadable number."""
    return shootgen.generate_scene_concepts(
        idea, brand, count=max(1, min(MAX_SCENES, count)),
        gemini_client=gemini_client, references=references, cast=cast,
        db_path=db_path if db_path is not None else db.DB_PATH,
        refs=list(refs or []), image_refs=image_refs or None,
        template_tag=template_tag, on_retry=on_retry)


def persist_prompt(concept_id: int, shot_n, text: str, *, db_path=None) -> bool:
    """Store a improved prompt as the one that RENDERS, keeping the
    generator's own words beside it.

    Whatever polished the text -- the orchestrator's promptgen refine,
    the Director canvas's enhance -- the result has to reach the row, or
    Runway renders the draft while the good version lives only in a job
    payload. The model's original is kept as `written_prompt` for two
    reasons: the Dev Studio's grade queue teaches on what the MODEL
    wrote, not on an editor's improvement of it, and the Director canvas
    seeds its User Prompt node from it, so opening a polished concept
    and pressing Run does not enhance an already-enhanced prompt -- a
    paid call that makes it worse, since the instructions compound.

    Returns False when there is nothing to store (same text, or empty);
    never raises on a missing concept -- polish is an enhancement.
    """
    path = db_path if db_path is not None else db.DB_PATH
    text = (text or "").strip()
    if not text:
        return False
    concept = preprod.get_concept(concept_id, path=path)
    if concept is None or not concept.get("shots"):
        return False
    shots = [dict(s) for s in concept["shots"]]
    shot = next((s for s in shots if s.get("n") == shot_n), None)
    if shot is None or (shot.get("prompt") or "").strip() == text:
        return False
    shot.setdefault("written_prompt", shot.get("prompt") or "")
    shot["prompt"] = text
    warnings = shootgen.validate_concept(
        {**concept, "shots": shots},
        [loc["name"] for loc in preprod.list_locations(path=path)],
        use_pov=bool(concept.get("use_pov")),
        allowed_tools=shootgen.ZEROPAGE_AI_TOOLS
        if concept.get("brand") == "zeropage" else None)
    preprod.update_concept_shots(concept_id, {"shots": shots},
                                 warnings=warnings, path=path)
    return True


def keyframe_scene(concept_id: int, shot_n=None, *, db_path=None,
                   resolve_photo=None) -> dict:
    """One still for the scene, attached as the shot's reference_image.

    That field is what Runway anchors the clip on, so this is the frame
    the whole spend hangs off -- which is exactly why it gets looked at
    before anyone approves. Every reference goes in NAMED (label, bytes)
    rather than as a bare picture: four references are four named things
    the model can bind to the prompt's words, not four images it has to
    sort out. Never raises -- nano_banana.generate_from_prompt returns
    its failure as a result, and a scene with no still is still a scene.
    """
    path = db_path if db_path is not None else db.DB_PATH
    concept = preprod.get_concept(concept_id, path=path)
    if concept is None or not concept.get("shots"):
        return {"ok": False, "error": f"no scene {concept_id}"}
    shots = concept["shots"]
    shot = (next((s for s in shots if s.get("n") == shot_n), None)
            if shot_n is not None else shots[0])
    if shot is None:
        return {"ok": False, "error": f"concept {concept_id} has no shot {shot_n}"}
    prompt = (shot.get("prompt") or "").strip()
    if not prompt:
        return {"ok": False, "error": "no prompt to render a keyframe from"}

    references = []
    for url in (shot.get("refs") or []):
        data = imagery.image_bytes_for_gemini(url, resolve_photo=resolve_photo)
        if data:
            references.append((shootgen.reference_label(url), data))

    result = nano_banana.generate_from_prompt(
        prompt, reference_image=references or None, db_path=path,
        concept_id=concept_id)
    if result.get("ok") and result.get("media_url"):
        preprod.set_shot_reference_image(concept_id, shot.get("n", 1),
                                         result["media_url"], path=path)
    return result


def park_scene(concept_id: int, reason: str = "", *, db_path=None) -> None:
    """The end of the automatic half: this scene is waiting on a human
    to spend. An explicit marker, never inferred from having a keyframe
    -- see preprod.set_shot_parked. Only the automation parks; a scene
    Michael made by hand reaches the Queue by being picked."""
    path = db_path if db_path is not None else db.DB_PATH
    concept = preprod.get_concept(concept_id, path=path)
    shot_n = (concept["shots"][0].get("n", 1)
              if concept and concept.get("shots") else 1)
    preprod.set_shot_parked(concept_id, shot_n, reason, path=path)


def run(idea: str, brand: str, *, count: int = 1, refs=None, image_refs=None,
        db_path=None, gemini_client=None, resolve_photo: Optional[Callable] = None,
        attach_refs: Optional[Callable] = None,
        progress: Optional[Callable] = None) -> dict:
    """Ground, write and attach -- what pressing Create does, and where
    it stops. Returns {"scenes": [...], "notes": [...], "prompt_template"}.

    `progress(fraction, detail)` is optional and is how the jobs SSE feed
    narrates the run.
    """
    def say(fraction, detail=""):
        if progress:
            try:
                progress(fraction, detail)
            except Exception:
                pass

    path = db_path if db_path is not None else db.DB_PATH
    notes: list = []

    say(0.15, "grounding in references")
    grounded = ground(idea, brand=brand, db_path=path)

    say(0.4, f"writing {max(1, min(MAX_SCENES, count))} scene(s)")
    # A busy model and a thinking model look identical from outside, and
    # the wait can be minutes -- so retries are narrated on the same feed
    # as the stages, at the stage they interrupt (2026-08-29).
    written = write_scenes(idea, brand, count=count,
                           references=grounded["references"],
                           cast=grounded["cast"], refs=refs,
                           image_refs=image_refs, db_path=path,
                           gemini_client=gemini_client,
                           on_retry=lambda note: say(0.4, note))
    scenes = written.get("scenes") or []
    if not scenes:
        raise RuntimeError("the model returned no usable scene")

    say(0.85, "attaching references")
    grounded_count = 0
    for scene in scenes:
        if attach_refs is None:
            continue
        try:
            if attach_refs(scene["concept_id"], list(refs or [])):
                grounded_count += 1
        except Exception:
            pass          # a missing photo never fails a written scene
    if grounded_count:
        _note(notes, f"{grounded_count} grounded in references")

    return {"scenes": scenes, "notes": notes,
            "prompt_template": written.get("prompt_template")}
