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

import sys
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


def ground(idea: str, *, brand: str = "", db_path=None, account_id: Optional[int] = None,
          refs: Optional[list] = None) -> dict:
    """The reference library, the cast, and the rooms this run may draw
    on -- all scoped to ONE rule (2026-09-03, Mike's call): named in
    `idea`, or explicitly picked via `refs` (a photo attached through
    the composer's / picker, an upload, or the asset carousel). Nothing
    on the shelf is offered just because it exists any more -- this
    replaces the old default of handing the writer EVERY character and
    prop on file on every single run (cast_for's unfiltered
    entities.list_characters/list_props), the same "always broadcast
    the whole roster" shape generate_scene_concept's cast=None default
    carried on the Director brief path.

    reference_block is the edge helper (never called from inside a
    generator, so the generators stay hermetic in tests) and never
    raises: no Postgres means an ungrounded run with a stderr note.
    Naming the cast is grounding too, and fails the same way -- softly.
    An asset with no photos was never eligible either way -- see
    shootgen.named_assets, which asset_shelf.in_scope calls underneath.
    """
    path = db_path
    references = ""
    try:
        references = shootgen.reference_block(spark=idea or None, db_path=path)
    except Exception:
        references = ""

    cast, locations = None, []
    try:
        cast, locations = scoped_cast_and_locations(
            idea, brand, refs, db_path=path, account_id=account_id)
    except Exception:
        cast, locations = None, []
    return {"references": references, "cast": cast, "locations": locations}


def scoped_cast_and_locations(idea: str, brand: str, refs, *, db_path=None,
                              account_id: Optional[int] = None) -> tuple:
    """The cast text block and the in-scope rooms, on their own --
    split out of ground() so a caller that already has its own
    reference_block (app.api.pipeline_run's scene_grounding, which adds
    the brand's inspiration accounts) doesn't have to query RAG twice
    to also get this half. ground() calls this; don't duplicate its
    body at a second call site."""
    from . import asset_shelf, entities

    path = db_path
    items = asset_shelf.catalogue(db_path=path, account_id=account_id)
    scope = asset_shelf.in_scope(idea, refs, items)
    scoped_names: dict = {"character": set(), "prop": set(), "location": set()}
    for a in scope:
        scoped_names.setdefault(a["category"], set()).add(a["name"])
    characters = [c for c in entities.list_characters(dsn=path, account_id=account_id)
                 if c["name"] in scoped_names["character"]]
    props = [p for p in entities.list_props(dsn=path, account_id=account_id)
            if p["name"] in scoped_names["prop"]]
    # Brand-scoped, same rule the graph follows: a faceless brand gets
    # no cast block, or the {cast} socket instructs it to name a
    # recurring person its own brief forbids -- unchanged by what got
    # named or picked, since the brand rule is the stricter one.
    cast = shootgen.cast_for(brand, characters, props, detail=True)
    locations = [loc for loc in preprod.list_locations(dsn=path, account_id=account_id)
                if loc["name"] in scoped_names["location"]]
    return cast, locations


def write_scenes(idea: str, brand: str, *, count: int = 1, references: str = "",
                 cast=None, refs=None, locations=None, image_refs=None, db_path=None,
                 gemini_client=None, template_tag: str = "",
                 on_retry=None, account_id: Optional[int] = None) -> dict:
    """N standalone takes on one idea, in ONE call so they are varied
    against each other rather than rolled independently. Raises: with no
    scene there is nothing to work on, and the caller must say so.

    `locations` is ground()'s already-computed in-scope set (named in
    the idea, or picked via refs) -- passed through so
    generate_scene_concepts does not recompute a narrower answer with
    picked_locations(refs, on_file), which only ever saw the pick half.
    None (the default for any other caller) falls back to that old
    behaviour, so tests and callers that never adopted ground() keep
    working unchanged.

    `template_tag` rides into the hashed prompt template, so pick_rate's
    by_prompt breakdown can separate rows produced by different
    pipelines instead of averaging them into one unreadable number."""
    return shootgen.generate_scene_concepts(
        idea, brand, count=max(1, min(MAX_SCENES, count)),
        gemini_client=gemini_client, references=references, cast=cast,
        db_path=db_path,
        refs=list(refs or []), locations=locations, image_refs=image_refs or None,
        template_tag=template_tag, account_id=account_id, on_retry=on_retry)


# How many photos of ONE character are worth a reference slot. A face
# is the case the one-photo rule was not written for: a three-quarter
# head turn grounded on a single frontal portrait ages the subject about
# ten years, while the frame it needed sits unused in the same folder
# (2026-08-29). A prop gains almost nothing from a second angle; an
# identity gains most of what it has.
CHARACTER_REF_PHOTOS = 3
# What one generation carries. Matches the composer's MAX_ATTACH and the
# scout's MAX_BIN_IMAGES -- a bin bigger than the cap has a tail that
# can never be used.
MAX_REFS = 6
# Slots HELD for research images when a run has any. Ordering alone was
# not enough: `extra` went last, and last never arrived. A scene naming
# Michael, the Ducati, the jacket and one more asset spends four slots on
# named assets and the remaining two on more angles of the face, so the
# crawl's images were appended to a list that was already full -- every
# concept written on 2026-09-01 came out with six asset-bank photos and
# nothing researched, which is indistinguishable from an empty bin.
#
# The reservation comes out of the EXTRA FACE ANGLES, never out of the
# named assets: a second portrait is a refinement, and identity is the
# thing the whole reference contract exists to protect. So a scene that
# names six assets still gets six -- cast beats inspiration when they
# actually compete -- but the common case stops starving research.
RESEARCH_SLOTS = 2
_DECODES_NATIVELY = {".jpg", ".jpeg", ".png", ".webp"}


def _ordered(photos: list, limit: int) -> list:
    """Up to `limit` of an asset's photos, decodable ones first: a HEIC
    the renderer cannot open is worth less than the third JPEG, so it
    sorts last rather than eating a slot."""
    from pathlib import Path as _P
    urls = [p.split("?")[0] for p in photos if p]
    native = [u for u in urls if _P(u).suffix.lower() in _DECODES_NATIVELY]
    return (native + [u for u in urls if u not in native])[:max(0, limit)]


def attach_refs(concept_id: int, extra: list | None = None, *, db_path=None, account_id: Optional[int] = None) -> list:
    """Store the photos this scene should render against, on its shot.

    Closes the loop `format_cast` opens. The cast block tells the
    generator that Michael and the Ducati have "(reference photos on
    file)" and the scene it writes says so in as many words -- but until
    something attaches those files, the renderer gets the sentence and
    not the face. The Studio path closed this on 2026-08-28; the graph
    kept the old bug until 2026-08-31, which is why the first automated
    keyframes came back with nobody recognisable in them.

    ORDER IS THE POINT, not a detail. Runway anchors a clip on exactly
    ONE frame -- whichever reference is first -- so:

      1. the assets the scene NAMED, identity first (named_assets ranks
         character -> prop -> location, because a full-room photo in the
         anchor slot makes the model reproduce that room instead of the
         scene),
      2. then more angles of the faces, round-robin -- but stopping
         RESEARCH_SLOTS short of the cap when there is research to fit,
      3. then `extra` -- the scout's downloaded research images, LAST
         and never in the anchor slot. Crawled material should inform a
         render, not become its subject.

    Last is not the same as never, which is what step 2 quietly made it
    until 2026-09-01. Being at the back of a queue that always filled
    before reaching you is being excluded, so step 2 now yields.

    Grounding shapes, it never gates: no match, no assets, or a broken
    catalogue all just mean the scene renders on its text.
    """
    path = db_path
    concept = preprod.get_concept(concept_id, dsn=path, account_id=account_id)
    if concept is None or not concept.get("shots"):
        return []
    shots = [dict(s) for s in concept["shots"]]
    shot = shots[0]
    text = " ".join(str(shot.get(k) or "")
                    for k in ("desc", "prompt", "location"))

    picked: list = []
    try:
        from . import asset_shelf
        named = shootgen.named_assets(
            text, asset_shelf.catalogue(db_path=path, account_id=account_id))
    except Exception as e:
        # Say so. This except swallowed an account-scoping mistake for
        # two nights: the catalogue came back empty, every scene "named
        # nothing", and the keyframes rendered with no face in them
        # while the Queue card still said the scene was grounded.
        print(f"note: asset catalogue unavailable, scene renders on its text: {e}",
              file=sys.stderr)
        named = []
    for asset in named:                      # one photo of everything named
        if len(picked) >= MAX_REFS:
            break
        best = _ordered(asset.get("photos") or [], 1)
        if best and best[0] not in picked:
            picked.append(best[0])
    # What the face angles may grow into, leaving room for research.
    # Computed from what `extra` ACTUALLY holds, so a run with no
    # research images still spends every slot on the cast exactly as
    # before -- this reserves for photographs that exist, never for the
    # possibility of some.
    reserved = min(len(extra or []), RESEARCH_SLOTS)
    angle_cap = max(len(picked), MAX_REFS - reserved)

    faces = [a for a in named if a.get("category") == "character"]
    for index in range(1, CHARACTER_REF_PHOTOS):   # more angles of the faces
        for asset in faces:
            if len(picked) >= angle_cap:
                break
            angles = _ordered(asset.get("photos") or [], CHARACTER_REF_PHOTOS)
            if index < len(angles) and angles[index] not in picked:
                picked.append(angles[index])
    for url in (extra or []):                # research images last
        if len(picked) >= MAX_REFS:
            break
        clean = (url or "").split("?")[0]
        if clean and clean not in picked:
            picked.append(clean)

    if not picked or picked == list(shot.get("refs") or []):
        return list(shot.get("refs") or [])
    shot["refs"] = picked
    preprod.update_concept_shots(
        concept_id, {"shots": shots, "duration": concept.get("duration")},
        warnings=concept.get("warnings") or [], dsn=path, account_id=account_id)
    return picked


def as_image_refs(urls: list, *, resolve_photo=None) -> list:
    """Reference URLs -> (bytes, mime, label) triples for a generator
    that can SEE them. `generate_scene_concept` takes these, so the
    scene is WRITTEN from the photographs rather than merely told they
    exist. Unresolvable entries are dropped, never raised."""
    from .gemini_utils import sniff_mime
    if resolve_photo is None:
        from . import asset_shelf
        resolve_photo = asset_shelf.resolve_photo
    out = []
    for url in (urls or [])[:MAX_REFS]:
        data = imagery.image_bytes_for_gemini(url, resolve_photo=resolve_photo)
        if data:
            out.append((data, sniff_mime(data), shootgen.reference_label(url)))
    return out


def persist_prompt(concept_id: int, shot_n, text: str, *, db_path=None, account_id: Optional[int] = None) -> bool:
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
    path = db_path
    text = (text or "").strip()
    if not text:
        return False
    concept = preprod.get_concept(concept_id, dsn=path, account_id=account_id)
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
        [loc["name"] for loc in preprod.list_locations(dsn=path, account_id=account_id)],
        use_pov=bool(concept.get("use_pov")),
        allowed_tools=shootgen.ZEROPAGE_AI_TOOLS
        if concept.get("brand") == "zeropage" else None)
    preprod.update_concept_shots(concept_id, {"shots": shots},
                                 warnings=warnings, dsn=path, account_id=account_id)
    return True


# How many targets one spark gets. Two, not one: a single reference is a
# picture the model copies, two are a range it interpolates within --
# and the second costs the same as the first only once per spark now.
TARGETS_PER_SPARK = 2


def visual_target(concept_id: int, shot: dict, *, spark: str = "",
                  db_path=None, account_id: Optional[int] = None,
                  gemini_client=None, count: int = TARGETS_PER_SPARK) -> list:
    """Give a scene with NO references something to look at, generated
    once PER SPARK and reused by every concept that spark produces.

    THE FAILURE THIS FIXES. keyframe_scene builds its reference list from
    `shot["refs"]` and passes reference_image=None when that list is
    empty -- so Nano renders the still from prompt text alone. For
    Antihero that is rare: the scene names Michael and attach_refs hangs
    his photo on it. For Zero Page it was EVERY scene -- a faceless brand
    has no cast to attach, and the scout's image bin has been empty since
    Instagram's public-content endpoint started refusing (2026-09-02:
    "8 spark(s) from 33 signals - 0 reference image(s) binned"). The
    brand whose whole register is grounded uncanny TEXTURE was the one
    keyframing with nothing to look at.

    WHY PER SPARK AND NOT PER CONCEPT (2026-09-02). One spark produces
    several concepts and they share a world -- same room, same light,
    same materials. Generating per concept paid for that world once per
    concept AND made the batch visually incoherent, since each concept
    got its own unrelated reference. Banking under a spark-derived
    pass_id means the second concept from a spark costs nothing and
    looks like it belongs beside the first.

    The bin is where they go because that is the path that already
    exists: bin_for_pass reads it, the composer renders it, and the URL
    shape is the same /refs/<sha>.jpg a dragged-on photo gets.

    A generated target is NOT a banked crawl image and the row says so
    -- lane="target", source_url="" -- because the bin's other rows are
    EVIDENCE (a frame from a video that travelled, carrying the URL that
    proves it) and this is a visual target for one idea. Conflating them
    would turn a mood board into a citation.

    WHY HIGGSFIELD AND NOT MIDJOURNEY (2026-09-02). This was wired to
    midjourney.generate_image first, because _midjourney_still was
    sitting there half-built. Running it showed the flaw: that path goes
    through AceDataCloud, a paid reseller, and ACEDATA_API_KEY is not
    set -- so it could never have produced an image, and a Midjourney
    subscription would not have helped, since the subscription and the
    reseller are separate bills. Higgsfield is already configured, costs
    $0.05 against Midjourney-via-reseller's $0.27, and returns its
    failures rather than raising.

    Gated by higgsfield.spend_approved() (HIGGSFIELD_SPEND_OK, per-run by
    design -- "an approval that's always on isn't an approval"), and by
    HIGGSFIELD_DAILY_CAP (6) underneath it. Returns [] on anything going
    wrong: a scene with no target keyframes the way it always did.
    """
    from . import higgsfield, scout

    path = db_path
    prompt = (shot.get("prompt") or "").strip()
    if not prompt:
        return []

    # Reuse before spending. Keyed on the spark's normalised form, so a
    # capitalisation difference does not buy the same pictures twice.
    pass_id = f"target-{scout._spark_key(spark)}" if (spark or "").strip() else ""
    if pass_id:
        banked = [r["url"] for r in scout.bin_for_pass(pass_id, dsn=path)]
        if banked:
            return banked

    if not higgsfield.spend_approved():
        return []

    made = []
    try:
        line = shootgen.still_prompt(prompt, gemini_client=gemini_client)
        if not line:
            return []
        for _ in range(max(1, count)):
            # Never raises; a refusal (cap, no key, upstream error) comes
            # back as ok=False, which is a reason to stop rather than to
            # keep paying for the same failure.
            result = higgsfield.generate_image_from_prompt(
                line, db_path=path, account_id=account_id)
            if not result.get("ok"):
                print(f"note: no visual target — {result.get('error')}",
                      file=sys.stderr)
                break
            url = result.get("media_url") or ""
            if url:
                made.append(url)
    except Exception as e:                      # surfaced, never fatal
        print(f"note: visual target stopped ({type(e).__name__}: {e})",
              file=sys.stderr)

    if made and pass_id:
        scout.init(path)
        with db.connect(path) as conn:
            for url in made:
                conn.execute(
                    "INSERT INTO scout_bin (created_at, pass_id, brand, url, "
                    "source_url, title, lane, metric) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                    (scout._now(), pass_id, "", url, "", (spark or "")[:120],
                     "target", ""),
                )
    return made


def _replace_shot(shots: list, shot: dict) -> list:
    """This shot updated, every other shot left alone.

    update_concept_shots REPLACES shots_json wholesale, so handing it
    `[shot]` deletes every other shot on the concept. That was survivable
    while Zero Page concepts came back with one shot; it stops being
    survivable the moment they come back with the two-to-four the brand
    prompt asks for.
    """
    n = shot.get("n")
    return [dict(shot) if s.get("n") == n else s for s in shots]


def keyframe_scene(concept_id: int, shot_n=None, *, db_path=None,
                   resolve_photo=None, gemini_client=None,
                   account_id: Optional[int] = None,
) -> dict:
    """A still per BEAT for the scene, compiled onto the shot.

    SEPARATE IMAGES, NOT ONE COMBINED ONE (Mike, 2026-09-02). A shot
    prompt describes a move -- "tilt up from the hand to his wide-eyed
    face" -- and the move stays, because it is how the shot is directed
    and the generator reads it. But one call asking for one picture of
    that whole move returns one picture OF THE WHOLE MOVE: concept 167
    came back with the hallway, the phone, and a head floating across
    the top third of the frame. So the move is split into its moments
    and each is rendered on its own call, with the full prompt behind it
    for grade, lens and texture and only the beat line saying which
    instant this frame is.

    The FIRST beat becomes the shot's reference_image -- the frame
    Runway anchors the clip on, so the whole spend hangs off it, which
    is exactly why it gets looked at before anyone approves. The rest
    ride on the shot as `frames`, the strip a person scrolls in the
    Queue. A shot the splitter reads as a single moment renders exactly
    one still, the way it always did.

    Every reference goes in NAMED (label, bytes) rather than as a bare
    picture: four references are four named things the model can bind to
    the prompt's words, not four images it has to sort out. Never raises
    -- nano_banana.generate_from_prompt returns its failure as a result,
    and a scene with no still is still a scene.
    """
    path = db_path
    concept = preprod.get_concept(concept_id, dsn=path, account_id=account_id)
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

    if resolve_photo is None:
        # Default rather than drop: the graph calls this with no app
        # around, and "no resolver" used to mean "no references at all"
        # while the card still claimed the scene was grounded.
        from . import asset_shelf
        resolve_photo = asset_shelf.resolve_photo
    # No references at all means the still would be rendered from the
    # prompt text alone -- which is every Zero Page scene, every night.
    # Generate a target first when the spend is approved.
    if not (shot.get("refs") or []):
        made = visual_target(concept_id, shot, spark=concept.get("spark") or "",
                             db_path=path, account_id=account_id)
        if made:
            shot = dict(shot, refs=made)
            preprod.update_concept_shots(
                concept_id, {"shots": _replace_shot(shots, shot)},
                dsn=path, account_id=account_id)

    references = []
    resolved: list = []
    for url in (shot.get("refs") or []):
        data = imagery.image_bytes_for_gemini(url, resolve_photo=resolve_photo)
        if data:
            references.append((shootgen.reference_label(url), data))
            resolved.append(url)

    # Make the prompt agree with the captions. The scene writer names
    # its references "@Image 1" / "@Image 2" -- a syntax nothing here
    # emits and no renderer receives -- so the sentence that said which
    # photograph was the face pointed at nothing, and the face was the
    # only part of the shot with no other way to bind. `resolved`, not
    # `refs`: a reference that failed to decode is not attached, and
    # naming it would promise a picture that never rode along.
    prompt = shootgen.bind_references(prompt, resolved)

    # The moments this shot's move travels through. [] means the shot
    # holds one moment -- render it once, exactly as before beats.
    beats = shootgen.beat_moments(prompt, gemini_client=gemini_client)

    frames: list = []
    result: dict = {}
    for beat in (beats or [""]):
        # No account_id, deliberately: nano's own shot row is created
        # unowned by _shot_row_for_prompt, and record_generation scopes
        # its lookup by account -- so passing one here raises "no shot
        # with id N" on a row that plainly exists. The whole path is
        # account-None and self-consistent; making it tenanted is a
        # change to generative.py, not something to do sideways here.
        result = nano_banana.generate_from_prompt(
            prompt, reference_image=references or None, db_path=path,
            concept_id=concept_id, beat=beat)
        if not (result.get("ok") and result.get("media_url")):
            # Usually NANO_DAILY_CAP. Stop rather than spend the rest of
            # the strip against a wall we have already hit -- and keep
            # the beats that DID render: half a strip is worth looking
            # at, and a failure on beat one is still the failure this
            # function has always returned.
            break
        frames.append({"beat": beat, "url": result["media_url"]})

    if not frames:
        return result or {"ok": False, "error": "no frame rendered"}

    shot_n_actual = shot.get("n", 1)
    preprod.set_shot_reference_image(concept_id, shot_n_actual,
                                     frames[0]["url"], dsn=path,
                                     account_id=account_id)
    if len(frames) > 1:
        try:
            # Re-read: set_shot_reference_image just wrote the anchor,
            # and the in-memory `shot` predates it. Building the strip
            # from the stale copy would erase the frame Runway anchors
            # on -- with the strip's own first entry, silently.
            fresh = preprod.get_concept(concept_id, dsn=path,
                                        account_id=account_id)["shots"]
            current = next(s for s in fresh if s.get("n") == shot_n_actual)
            preprod.update_concept_shots(
                concept_id,
                {"shots": _replace_shot(fresh, dict(current, frames=frames))},
                dsn=path, account_id=account_id)
        except Exception:
            pass       # the anchor frame is stored; the strip is a bonus

    return {"ok": True, "media_url": frames[0]["url"],
            "frames": frames,
            "generation_id": result.get("generation_id"),
            "path": result.get("path"),
            "error": (result.get("error")
                      if len(frames) < len(beats or [""]) else None)}


def park_scene(concept_id: int, reason: str = "", *, db_path=None, account_id: Optional[int] = None) -> None:
    """The end of the automatic half: this scene is waiting on a human
    to spend. An explicit marker, never inferred from having a keyframe
    -- see preprod.set_shot_parked. Only the automation parks; a scene
    Michael made by hand reaches the Queue by being picked."""
    path = db_path
    concept = preprod.get_concept(concept_id, dsn=path, account_id=account_id)
    shot_n = (concept["shots"][0].get("n", 1)
              if concept and concept.get("shots") else 1)
    preprod.set_shot_parked(concept_id, shot_n, reason, dsn=path, account_id=account_id)


def run(idea: str, brand: str, *, count: int = 1, refs=None, image_refs=None,
        db_path=None, gemini_client=None, resolve_photo: Optional[Callable] = None,
        attach_refs: Optional[Callable] = None,
        progress: Optional[Callable] = None,
        account_id: Optional[int] = None) -> dict:
    """Ground, write and attach -- what pressing Create does, and where
    it stops. Returns {"scenes": [...], "notes": [...], "prompt_template"}.

    `progress(fraction, detail)` is optional and is how the jobs SSE feed
    narrates the run. `account_id` is whose concepts these are: it was
    dropped at this boundary until 2026-09-02, so Create wrote ownerless
    rows that the next startup's backfill handed to the bootstrap
    account -- invisible with one operator, a pilot's concepts on Mike's
    board with two.
    """
    def say(fraction, detail=""):
        if progress:
            try:
                progress(fraction, detail)
            except Exception:
                pass

    path = db_path
    notes: list = []

    say(0.15, "grounding in references")
    grounded = ground(idea, brand=brand, db_path=path, account_id=account_id, refs=refs)

    say(0.4, f"writing {max(1, min(MAX_SCENES, count))} scene(s)")
    # A busy model and a thinking model look identical from outside, and
    # the wait can be minutes -- so retries are narrated on the same feed
    # as the stages, at the stage they interrupt (2026-08-29).
    written = write_scenes(idea, brand, count=count,
                           references=grounded["references"],
                           cast=grounded["cast"], refs=refs,
                           locations=grounded["locations"],
                           image_refs=image_refs, db_path=path,
                           gemini_client=gemini_client,
                           on_retry=lambda note: say(0.4, note),
                           account_id=account_id)
    scenes = written.get("scenes") or []
    if not scenes:
        raise RuntimeError("the model returned no usable scene")

    say(0.85, "attaching references")
    grounded_count = 0
    for scene in scenes:
        if attach_refs is None:
            continue
        try:
            if attach_refs(scene["concept_id"], list(refs or []),
                           account_id=account_id):
                grounded_count += 1
        except Exception:
            pass          # a missing photo never fails a written scene
    if grounded_count:
        _note(notes, f"{grounded_count} grounded in references")

    return {"scenes": scenes, "notes": notes,
            "prompt_template": written.get("prompt_template")}
