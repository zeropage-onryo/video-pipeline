#!/usr/bin/env python3
"""
Generate shoot concepts from the spaces you actually have.

The rest of the pipeline is footage-first: it reasons about clips that
already exist. This runs before any of that -- it takes the described
locations and proposes concepts and shot lists for footage you haven't
shot yet, grounded in real rooms rather than an imagined set.

Two layers, same discipline as promptgen.py: the model's only job is
producing a concept. validate_concept is what enforces the rules --
"prompts request, code enforces". A concept that breaks a rule is
still saved, with its warnings attached, because it's worth looking at
and deciding on rather than silently discarding.
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

from . import entities, preprod, rag
from . import shot as shot_module
from .db import DB_PATH, init_db
from .gemini_utils import generate_with_retry, strip_fences

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = PROJECT_ROOT / "prompts"

MODEL = "gemini-3-flash-preview"

DEFAULT_IDEA_COUNT = 5
SHOT_TYPES = ("CHARACTER", "BROLL")
SHOT_SOURCES = ("CAMERA", "AI")
CAMERAS = ("BMPCC", "ACTION5")
# The legal AI tool set is the shot.py platform registry — uppercase to
# match how concepts name tools. One registry, no second list to drift.
AI_TOOLS = tuple(t.upper() for t in shot_module.TOOLS)

# Zero Page's real, currently-usable tool set -- deliberately narrower than
# AI_TOOLS above. Everything else in the shot.py registry (Veo/Kling/
# Seedance/LTX/Wan) is real infrastructure for other brands and stays in
# AI_TOOLS for them, but Michael only actually generates Zero Page's AI
# shots on these two, so the shot-plan prompt and its validation are
# scoped to just these. Filtered from AI_TOOLS rather than hardcoded a
# second time, so it can never name a tool the registry doesn't have.
ZEROPAGE_AI_TOOLS = tuple(t for t in AI_TOOLS if t in ("HIGGSFIELD", "RUNWAY"))

NO_LOCATIONS_NOTE = (
    "note: no described locations -- generating ungrounded. Photograph and "
    "describe a space to ground concepts in real rooms."
)

NO_REFERENCES_NOTE = (
    "(no reference library available -- generate from the rooms and brand alone)"
)

NO_CAST_NOTE = (
    "(no characters or props on file yet -- describe appearance in the prompt "
    "as needed)"
)

NO_EXAMPLE_NOTE = "(no gold-standard example on file)"

# Appended to the text prompt only when image_refs is non-empty (see
# generate_concept) -- without this, nothing in the prompt tells the
# model that images were attached at all, since the templates were
# written before vision input existed on this path.
IMAGE_REFS_NOTE = (
    "\n\n(One or more reference images are attached above -- ground this "
    "concept in what they actually show: the space, the object, the "
    "subject, the light. Don't ignore them and write a generic idea.)"
)

# Zero Page rides FORMAT skeletons, not rooms. These are evergreen vertical
# short-form structures that travel -- the vehicle each faceless-uncanny beat
# rides. They are the static seed; the format-trend feed (refresh_metrics /
# RAG) can override this list with what's actually spiking, but Zero Page can
# always generate from these alone. Kept here rather than a file because they
# are structural, not brand wording -- a fixed vocabulary the trend feed ranks
# against, not something edited per-run.
ZEROPAGE_FORMATS = [
    ("The Reveal", "Hold on an ordinary frame, then one element shifts or is "
     "revealed to be wrong. The reveal is the whole video."),
    ("Slow Push-In", "One continuous push toward a subject until the wrong "
     "detail fills the frame. No cuts, escalating unease."),
    ("Freeze on the Wrong Thing", "Motion, then a hard stop on a detail that "
     "shouldn't be there. The freeze names the wrongness."),
    ("POV Walk-In", "First-person entering a space and discovering the "
     "uncanny thing. The viewer arrives at it with the camera."),
    ("Seamless Loop", "The last frame flows into the first so it repeats "
     "forever, the wrongness compounding on each pass."),
    ("Satisfying, Then Broken", "A satisfying, tactile process (pouring, "
     "stacking, cleaning) that turns wrong at the last beat."),
    ("Text-Hook Cold Open", "An on-screen line poses a question in second 1; "
     "the grounded visual answers it wrong."),
    ("The Repetition Break", "A repeated action or pattern establishes a "
     "rhythm, then one repetition breaks it in a way that shouldn't happen."),
]


def ranked_formats(**kwargs):
    # -> list of (name, how) tuples, or None on failure (CI pins Python 3.9,
    # so no bare `X | None` return annotation here -- that needs 3.10+).
    """format_feed.rank_formats(), wired into the actual generation calls.
    None on any failure -- build_ideas_prompt/build_concept_prompt already
    fall back to the static evergreen ZEROPAGE_FORMATS order when formats is
    None, so this stays an enhancement, never a gate, same contract as
    reference_block / ground_rag."""
    try:
        from . import format_feed  # local import -- see docstring above
        return format_feed.rank_formats(**kwargs)
    except Exception as e:
        print(f"note: format feed degraded to evergreens: {e}", file=sys.stderr)
        return None


def format_skeletons(formats=None) -> str:
    """The hot-format menu Zero Page rides, as the model sees it. Defaults to
    the evergreen ZEROPAGE_FORMATS; the trend feed passes a ranked live list
    later. Never a gate -- an empty/failed feed falls back to the evergreens."""
    formats = formats or ZEROPAGE_FORMATS
    return "\n".join(f"- {name}: {how}" for name, how in formats)

# Ideation's automatic layer (changed 2026-08-20, narrowed further from
# the first opt-in-everything pass): craft/structuring advice -- platform
# mechanics, edit anatomy, what earns a swipe/watch -- not the brand's own
# assets. Always pulled by background search, same as it always was.
# Never ai_prompting, which is AI-video-tool prompt syntax for a later
# stage (promptgen.py), not "what should we shoot" material.
AUTO_IDEATION_DOMAINS = ("marketing",)

# The brand's own assets: voice (personal_brand), look (cinematography),
# and performance history (proven_results, winning_prompts). Opt-in only
# -- pulled by EXACT name via rag.fetch_by_sources when reference_block's
# picked_sources names them, never by background semantic search. Nothing
# picked means nothing from these shelves, not even an attempt. See
# reference_block's docstring.
ASSET_IDEATION_DOMAINS = ("personal_brand", "cinematography", "proven_results", "winning_prompts")

# What you (or /ui) directly taught the pipeline about its OWN output --
# approve/deny + edited-prompt verdicts (winners.py's winning_prompts /
# avoid_prompts, written from both the dev page's per-concept and per-shot
# "TEACH THIS..." controls) and /ui's concept-denial notes (api.py's
# 'denials' shelf). This is human judgment on prior generations, not brand
# voice/look -- closer to the craft-advice shelf than to ASSET_IDEATION_DOMAINS
# -- so unlike those, it's auto-queried by background semantic search the
# same way AUTO_IDEATION_DOMAINS is. Every chunk here is already
# self-labeled at ingest time (winners._render_doc's "WINNING ... PROMPT"
# vs "AVOID -- a ... prompt that DID NOT work"; api.py's "DENIED CONCEPT"),
# so the retrieved text itself tells the model which way to read it --
# nothing extra to frame here. Whatever gets taught on the dev page (or
# denied on /ui) now actually shapes the next generation on BOTH surfaces,
# since both call this same function.
LEARNED_IDEATION_DOMAINS = ("winning_prompts", "avoid_prompts", "denials")


def build_reference_query(locations: list, spark=None, client=None,
                          max_chars: int = 4000) -> str:
    """
    The retrieval query for ideation: the creative direction actually in
    play -- the spark, the client/spec, and the mood of the described
    rooms (their space, textures, constraints) -- so the library returns
    tone/structure notes close to what's being made. The ideation
    analogue of pitch.py's build_reference_query, which queries with the
    footage itself.
    """
    parts: list = []
    if spark:
        parts.append(spark)
    if client:
        parts.append(client)
    for loc in locations:
        description = loc.get("description") or {}
        if description.get("space"):
            parts.append(description["space"])
        for key in ("textures", "constraints"):
            value = description.get(key)
            if isinstance(value, list):
                parts.extend(value)
            elif value:
                parts.append(value)
    return " ".join(str(p) for p in parts)[:max_chars]


def reference_block(spark=None, client=None, db_path=None, picked_sources=None) -> str:
    """
    Retrieve grounding references for an ideation run and return the
    formatted block, or "" if nothing applies. Never raises -- the same
    enhancement-not-dependency contract pitch.py keeps. This is the
    *edge* helper: call it from entry points (CLI, web routes), not from
    inside the tested generate functions, so those stay hermetic.

    Three layers (split 2026-08-20 so ideas don't quietly ground on the
    brand's own assets; the learned layer added 2026-08-24):

    - AUTO_IDEATION_DOMAINS (craft/structuring advice, not personal
      assets) is always queried by background semantic search, same as
      it always was.
    - LEARNED_IDEATION_DOMAINS (your own approve/deny + edited-prompt
      verdicts, from either UI) is ALSO always queried by background
      semantic search, right alongside the craft shelf -- added
      2026-08-24 so teaching a prompt on the dev page (or denying a
      concept on /ui) actually changes what gets generated next,
      instead of just sitting in the store unread.
    - ASSET_IDEATION_DOMAINS (the brand's own voice/look/performance
      history) is opt-in only: pulled by EXACT source name via
      rag.fetch_by_sources when the caller names them in
      picked_sources -- no embedding call, no similarity ranking,
      because that selection already happened. Nothing in
      picked_sources means nothing from these shelves, not even an
      attempt.

    References are de-duplicated by (source, chunk) before formatting,
    since an opt-in pick from ASSET_IDEATION_DOMAINS (winning_prompts)
    can otherwise show up twice -- once picked exactly, once surfaced
    again by the new LEARNED_IDEATION_DOMAINS semantic search.
    """
    kwargs = {"path": db_path} if db_path is not None else {}
    locations = preprod.list_locations(**kwargs)
    query = build_reference_query(locations, spark=spark, client=client)

    references = []

    if picked_sources:
        picked = rag.fetch_by_sources(picked_sources)
        if picked["ok"] and picked["references"]:
            print(f"Grounding in {len(picked['references'])} selected asset reference(s)",
                  file=sys.stderr)
            references.extend(picked["references"])
        elif not picked["ok"]:
            print(f"note: generating without selected assets: {picked.get('error')}",
                  file=sys.stderr)

    if query.strip():
        retrieval = rag.retrieve_references(query, domain=AUTO_IDEATION_DOMAINS)
        if retrieval["ok"] and retrieval["references"]:
            print(f"Grounding in {len(retrieval['references'])} craft reference(s)",
                  file=sys.stderr)
            references.extend(retrieval["references"])
        elif not retrieval["ok"]:
            reason = retrieval.get("error", "reference library is empty")
            print(f"note: generating without craft references: {reason}", file=sys.stderr)

        learned = rag.retrieve_references(query, domain=LEARNED_IDEATION_DOMAINS)
        if learned["ok"] and learned["references"]:
            print(f"Grounding in {len(learned['references'])} taught reference(s) "
                  "-- your own approve/deny history", file=sys.stderr)
            references.extend(learned["references"])
        elif not learned["ok"]:
            reason = learned.get("error", "nothing taught yet")
            print(f"note: generating without taught references: {reason}", file=sys.stderr)

    seen = set()
    deduped = []
    for ref in references:
        key = (ref.get("source"), ref.get("chunk"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(ref)

    return rag.format_references(deduped)


def load_brand(brand: str) -> str:
    """
    One brand block out of prompts/brands.txt, keyed by [name]. Kept in
    a text file rather than Python so the wording is editable without
    touching code, same as brief.txt.
    """
    if brand not in preprod.BRANDS:
        raise ValueError(f"brand must be one of {preprod.BRANDS}, got {brand!r}")

    text = (PROMPTS_DIR / "brands.txt").read_text()
    marker = f"[{brand}]"
    if marker not in text:
        raise ValueError(f"no [{brand}] block in prompts/brands.txt")

    block = text.split(marker, 1)[1]
    # stop at the next [block] header, if any
    for line in block.splitlines():
        if line.startswith("[") and line.rstrip().endswith("]"):
            block = block.split(line, 1)[0]
            break
    return block.strip()


def location_variety_note(locations: list, lock: bool = False) -> str:
    """When few real rooms are on file, camera shots are necessarily stuck
    there -- but AI shots never have to be. Without this, ideas quietly
    reuse the one photographed room concept after concept, because the
    model has nowhere else it's been told it CAN go. '' once there's
    enough real variety on file that this stops being the bottleneck.

    `lock=True` means the filmmaker deliberately picked this location (or
    these locations) for this run -- not a shortage. That's the opposite
    instruction: stop pushing toward AI-invented environments and lean
    into the one space instead. Set by generate_concept/generate_concept_ideas
    whenever the caller passes `only_locations`."""
    if lock:
        return (
            f"\nLOCATION LOCK: this run is intentionally anchored to "
            f"{'this location' if len(locations) == 1 else 'these locations'} -- "
            "that's a deliberate choice for this shoot, not a shortage. Don't "
            "invent alternate AI environments to manufacture variety; build the "
            "idea to make full, specific use of the space that's actually being shot."
        )
    if len(locations) > 2:
        return ""
    have = len(locations)
    return (
        f"\nVARIETY NOTE: only {have} real location{'s' if have != 1 else ''} "
        "on file right now, so leaning on AI-invented environments for most AI "
        "shots -- rather than always extending the same real room -- is what "
        "keeps ideas from feeling repetitive. Don't set every idea in the one "
        "room just because it's the one that's photographed; invent the space "
        "the story actually wants and match it to the grade."
    )


def format_locations(locations: list) -> str:
    """The described spaces, as the model sees them."""
    lines = []
    for loc in locations:
        description = loc.get("description") or {}
        lines.append(f"- {loc['name']}: {description.get('space', 'no description')}")
        for key in ("light_sources", "textures", "angles"):
            values = description.get(key)
            if values:
                lines.append(f"    {key.replace('_', ' ')}: {', '.join(values)}")
        if description.get("constraints"):
            lines.append(f"    constraints: {description['constraints']}")
    return "\n".join(lines)


# The other half of format_cast (below). format_cast tells the model
# which assets exist and marks the ones carrying "(reference photos on
# file)"; this reads the finished scene back and says WHICH of them it
# actually used, so their photos can be attached to the shot.
#
# Without it the loop is open in the worst possible way: the prompt
# says "Michael (reference photos on file)" because format_cast told it
# to, the photos sit right there in characters/michael, and nothing
# ever hands them to the renderer -- the model is told a reference
# exists and then never shown it.

_ALIAS_STOP = {"The", "A", "An", "This", "That", "These", "Those", "His",
               "Her", "Its", "Their", "My", "Our", "Shots", "Stills"}


def asset_aliases(asset: dict) -> list[str]:
    """The names this asset can be recognised by in a written scene: its
    own name, plus any multi-word proper noun in its notes.

    Two consecutive capitalised words, deliberately -- a prop named
    "Motorcycle" whose notes say "A Ducati Panigale 959" has to be
    findable when the scene calls it a Ducati, and "Ducati Panigale" is
    a safe thing to match on where a lone capitalised word is not
    (every sentence starts with one). Conservative on purpose: a missed
    alias costs one un-attached photo, a false one attaches a reference
    the shot was never supposed to resemble.
    """
    aliases = []
    name = (asset.get("name") or "").strip()
    if name:
        aliases.append(name)
    # Punctuation and digits are TOKENS here, not skipped: without them
    # "A Ducati Panigale 959. Michael's personal vehicle" reads as one
    # unbroken run and yields the alias "Ducati Panigale Michael",
    # which matches nothing and belongs to nobody.
    tokens = re.findall(r"[A-Za-z][A-Za-z'\-]*|[^A-Za-z\s]+",
                        asset.get("text") or "")
    run: list[str] = []
    for token in tokens:
        if token[0].isalpha() and token[0].isupper() and token not in _ALIAS_STOP:
            run.append(token.split("'")[0])
            continue
        if len(run) >= 2:
            aliases.append(" ".join(run))
        run = []
    if len(run) >= 2:
        aliases.append(" ".join(run))
    return aliases


_LABEL_ROLE = {
    "characters": "the EXACT face and likeness",
    "props": "the EXACT object",
    "locations": "the location",
}


def reference_label(url: str) -> str:
    """A one-line caption naming the asset a reference photo belongs to.

    Four bare pictures is not four references. Both platforms this
    project targets bind an image to a NAME the prompt then uses --
    Runway takes `{uri, tag}` and documents the tag as "used to
    reference the image in prompt text"; Higgsfield rewrites
    `<<<element>>>` into `@element_name`. Gemini has no tag field, so
    the binding is made its own way: a caption immediately before the
    image. A shot with two characters and two props otherwise leaves
    the model to guess which photo is the face (2026-08-28).

    The name comes off the URL, not the database: the slug IS the
    asset's name run through _slug, so reversing it cannot disagree
    with the row, needs no query, and still works for an asset that has
    since been renamed. "" for anything unrecognised -- an unlabelled
    reference is the old behaviour, never an error.
    """
    parts = (url or "").split("?")[0].strip("/").split("/")
    if len(parts) == 2 and parts[0] == "refs":
        return "Reference photo supplied with this prompt:"
    if len(parts) != 4 or parts[2] != "photo":
        return ""
    role = _LABEL_ROLE.get(parts[0])
    if role is None:
        return ""
    name = parts[1].replace("-", " ").replace("_", " ").strip().title()
    return f"Reference photo — {name}, {role}:"


def named_assets(text: str, assets: list) -> list[dict]:
    """Which of these assets the scene actually names, identity first.

    Order is the point, not a detail. Runway anchors a clip on exactly
    ONE frame, so whatever lands first is what the clip will look like:
    a character, then the prop they are handling, and a location LAST --
    a full-room photo in that slot makes the model reproduce that room
    instead of the scene, which is the documented way to waste a
    generation.
    """
    haystack = " " + re.sub(r"\s+", " ", text or "").lower() + " "
    rank = {"character": 0, "prop": 1, "location": 2}
    hits = []
    for asset in assets:
        if not asset.get("photos"):
            continue          # nothing to attach; naming it is not enough
        at = None
        for alias in asset_aliases(asset):
            if len(alias) < 3:
                continue
            found = re.search(r"(?<![\w])" + re.escape(alias.lower()) + r"(?![\w])",
                              haystack)
            if found and (at is None or found.start() < at):
                at = found.start()
        if at is not None:
            hits.append((rank.get(asset.get("category"), 3), at, asset))
    # category first, then WHO THE SCENE OPENS ON. Two characters are
    # not interchangeable in the anchor slot: the scene that begins on
    # Michael's hand should anchor on Michael, not on the monster he
    # meets later, and alphabetical or table order gets that wrong half
    # the time.
    hits.sort(key=lambda h: (h[0], h[1]))
    return [asset for _, _, asset in hits]


def format_cast(characters: list, props: list) -> str:
    """
    Named characters and props that have reference stills on file --
    one level down from the room to what's actually in it, same
    reasoning as format_locations. Not every shoot has any (most
    don't); an empty list here just means nothing is named yet, not
    that the shoot is missing something.

    A character/prop without photo_count still gets listed -- it's
    still worth naming by name for continuity across shots -- but only
    ones with photos are told to lean on the reference image instead
    of prompt text for appearance.
    """
    lines = []
    for c in characters:
        ref = " (reference photos on file)" if c.get("photo_count") else ""
        role = f" — {c['role']}" if c.get("role") else ""
        notes = c.get("notes") or (c.get("description") or {}).get("notes")
        lines.append(f"- {c['name']}{role}{ref}" + (f": {notes}" if notes else ""))
    for p in props:
        ref = " (reference photos on file)" if p.get("photo_count") else ""
        category = f" — {p['category']}" if p.get("category") else ""
        notes = p.get("notes") or (p.get("description") or {}).get("notes")
        lines.append(f"- {p['name']}{category}{ref}" + (f": {notes}" if notes else ""))
    return "\n".join(lines)


POV_ON = ('- Camera B ("ACTION5"): DJI Osmo Action 5 Pro, for POV / body-mount\n'
          "  shots.")
POV_OFF = "- No POV camera available this shoot — BMPCC only."


def apply_pov(template: str, use_pov: bool) -> str:
    """
    The POV camera is a real physical constraint, so it has to reach
    both the prompt and the validator. Off means the model is never
    offered ACTION5 and never told it is a legal value.
    """
    return (
        template
        .replace("{pov}", POV_ON if use_pov else POV_OFF)
        .replace("{cam_rule}", '- Every shot\'s "cam" is exactly '
                 + ("BMPCC or ACTION5." if use_pov else "BMPCC."))
        .replace("{cam_values}", '"BMPCC or ACTION5"' if use_pov else '"BMPCC"')
    )


def build_concept_prompt(locations: list, brand: str, client=None, spark=None,
                         use_pov: bool = False, references: str = "",
                         cast: str = "", formats=None,
                         lock_location: bool = False) -> str:
    # Zero Page runs its OWN engine -- faceless, fully-AI, format-driven, not
    # grounded in his rooms. Antihero keeps the solo-filmmaker-at-home engine.
    if brand == "zeropage":
        template = (PROMPTS_DIR / "concept_zeropage.txt").read_text()
        return (
            template
            .replace("{formats}", format_skeletons(formats))
            .replace("{brand}", load_brand(brand))
            .replace("{client}", f"CLIENT / SPEC TYPE: {client}" if client else "")
            .replace("{spark}", f"TREND / SPARK: {spark}" if spark else "")
            .replace("{references}", references or NO_REFERENCES_NOTE)
            .replace("{example}", gold_standard_example() or NO_EXAMPLE_NOTE)
        )
    template = apply_pov((PROMPTS_DIR / "concept_prompt.txt").read_text(), use_pov)
    return (
        template
        .replace("{locations}", format_locations(locations))
        .replace("{brand}", load_brand(brand))
        .replace("{client}", f"CLIENT / SPEC TYPE: {client}" if client else "")
        .replace("{spark}", f"CREATIVE SPARK FROM THE FILMMAKER: {spark}" if spark else "")
        .replace("{references}", references or NO_REFERENCES_NOTE)
        .replace("{cast}", cast or NO_CAST_NOTE)
        .replace("{example}", gold_standard_example() or NO_EXAMPLE_NOTE)
        .replace("{location_variety_note}", location_variety_note(locations, lock=lock_location))
    )


def build_ideas_prompt(locations: list, brand: str, client=None, spark=None,
                       count: int = DEFAULT_IDEA_COUNT, references: str = "",
                       formats=None, lock_location: bool = False) -> str:
    # Zero Page rides format skeletons + an uncanny beat, faceless and
    # room-free; Antihero grounds ideas in his real spaces and recurring star.
    if brand == "zeropage":
        template = (PROMPTS_DIR / "concept_ideas_zeropage.txt").read_text()
        return (
            template
            .replace("{formats}", format_skeletons(formats))
            .replace("{brand}", load_brand(brand))
            .replace("{client}", f"CLIENT / SPEC TYPE: {client}" if client else "")
            .replace("{spark}", f"TREND / SPARK: {spark}" if spark else "")
            .replace("{count}", str(count))
            .replace("{references}", references or NO_REFERENCES_NOTE)
        )
    template = (PROMPTS_DIR / "concept_ideas_prompt.txt").read_text()
    return (
        template
        .replace("{locations}", format_locations(locations))
        .replace("{brand}", load_brand(brand))
        .replace("{client}", f"CLIENT / SPEC TYPE: {client}" if client else "")
        .replace("{spark}", f"CREATIVE SPARK FROM THE FILMMAKER: {spark}" if spark else "")
        .replace("{count}", str(count))
        .replace("{references}", references or NO_REFERENCES_NOTE)
        .replace("{location_variety_note}", location_variety_note(locations, lock=lock_location))
    )


def parse_ideas_response(text: str) -> list:
    """Stage one's testable seam: raw model text -> a list of ideas."""
    data = json.loads(strip_fences(text))
    ideas = data.get("ideas", data if isinstance(data, list) else [])
    if not ideas:
        raise ValueError("no ideas in response")
    for i, idea in enumerate(ideas, start=1):
        if not (idea.get("title") or "").strip():
            raise ValueError(f"idea {i} has no title")
    return ideas


def build_shotlist_prompt(locations: list, brand: str, client, concept: dict,
                          use_pov: bool = False, cast: str = "") -> str:
    # Zero Page ships without a shoot -- every shot is AI-generated and
    # faceless, so stage two has to run the same zeropage engine as stage
    # one (build_concept_prompt / build_ideas_prompt) instead of the
    # solo-filmmaker-at-home template. Without this branch, the real cast
    # and locations on file (a named recurring character, his actual
    # vehicle/room) leak straight into a Zero Page AI shot prompt.
    if brand == "zeropage":
        template = (PROMPTS_DIR / "shotlist_prompt_zeropage.txt").read_text()
        return (
            template
            .replace("{brand}", load_brand(brand))
            .replace("{client}", f"CLIENT / SPEC TYPE: {client}" if client else "")
            .replace("{title}", concept.get("title") or "")
            .replace("{format}", concept.get("format") or "")
            .replace("{hook}", concept.get("hook") or "")
            .replace("{logline}", concept.get("logline") or "")
            .replace("{example}", gold_standard_example() or NO_EXAMPLE_NOTE)
        )
    template = apply_pov((PROMPTS_DIR / "shotlist_prompt.txt").read_text(), use_pov)
    return (
        template
        .replace("{locations}", format_locations(locations))
        .replace("{brand}", load_brand(brand))
        .replace("{client}", f"CLIENT / SPEC TYPE: {client}" if client else "")
        .replace("{title}", concept.get("title") or "")
        .replace("{hook}", concept.get("hook") or "")
        .replace("{logline}", concept.get("logline") or "")
        .replace("{cast}", cast or NO_CAST_NOTE)
        .replace("{example}", gold_standard_example() or NO_EXAMPLE_NOTE)
    )


def parse_plan_response(text: str) -> dict:
    """
    Stage two's testable seam: raw model text -> the shot plan. Zero
    Page's plan is a scene concept -- "scenes" (Scene -> Shots, see
    prompts/shotlist_prompt_zeropage.txt) -- instead of a flat "shots"
    array, so a plan is valid with either shape; generate_shot_list is
    what flattens scenes into shots for storage.
    """
    data = json.loads(strip_fences(text))
    plan = data.get("plan", data)
    if not plan.get("shots") and not plan.get("scenes"):
        raise ValueError("plan has no shots")
    return plan


def _flatten_zeropage_scenes(scenes: list) -> list:
    """
    Zero Page's shot-plan schema is Scene -> Shots -- a scene concept with
    shot ideas and prompts per scene, not a flat shot list, so it folds
    directly into OpenArt Director's own Story -> Scenes -> Shots model
    later (see prompts/shotlist_prompt_zeropage.txt).

    Storage stays flat: every existing consumer of a concept's shots --
    preprod.set_shot_media_url, preprod.set_shot_reference_image, the
    /concepts/.../shots/{shot_n}/reference route, autopilot's posting
    gate, format_concept_as_text -- addresses a shot by one global "n"
    and reads "location" straight off the shot. Rather than teach all of
    those about nesting, this renumbers shots 1..N across every scene and
    stamps each with the scene it came from (scene_n, scene_title) and
    the scene's location, so nothing downstream needs to know scenes
    exist -- concepts.html groups by scene_title purely for display.
    """
    flat = []
    n = 1
    for scene in scenes or []:
        location = (scene.get("location") or "").strip()
        scene_title = (scene.get("title") or "").strip()
        scene_n = scene.get("n")
        for shot in scene.get("shots") or []:
            shot = dict(shot)
            shot["n"] = n
            shot.setdefault("location", location)
            if scene_title:
                shot["scene_title"] = scene_title
            if scene_n is not None:
                shot["scene_n"] = scene_n
            flat.append(shot)
            n += 1
    return flat


def _apply_location_lock(locations: list, only_locations) -> tuple:
    """
    Every generation call defaults to every real room on file -- that's
    the right default so ideas range across the whole space you've
    photographed. `only_locations` (a list of location names) is the
    per-run override: "I'm choosing to shoot in just this room today,"
    not "I only have one room." Returns (locations, lock) -- the
    filtered list (unfiltered if nothing matched or nothing was asked
    for) and whether to tell the model this was a deliberate choice
    rather than a shortage.

    A name that doesn't match anything on file is a caller mistake, not
    a reason to silently generate against every room -- same
    never-silently-wrong instinct as the rest of this module -- so it's
    logged and the full set is used instead of guessing.
    """
    if not only_locations:
        return locations, False
    wanted = {str(n).strip().lower() for n in only_locations}
    filtered = [loc for loc in locations if loc["name"].strip().lower() in wanted]
    if not filtered:
        print(f"note: none of {list(only_locations)} matched locations on file "
              "-- using every location instead", file=sys.stderr)
        return locations, False
    return filtered, True


def derive_scene_bible(title=None, logline=None, grade=None) -> str:
    """
    A short, code-owned consistency anchor built from data already on
    the concept -- no extra API call. Exists because a concept's AI
    shots are each rendered independently by an external video tool
    (Kling, Veo, Runway...) that never sees the other shots; without
    something forcing the same character/scene/grade language into
    every one of them, two shots from the same concept can come back
    looking like they're from different scenes even though the model
    wrote both prompts in the same call.
    """
    parts = []
    if title:
        parts.append(f"Scene: {title}")
    if logline:
        parts.append(str(logline).strip())
    if grade:
        parts.append(f"Grade: {grade}")
    return " -- ".join(p for p in parts if p)


def apply_scene_bible(shots: list, bible: str) -> list:
    """
    Prepend the scene bible to every AI shot's own generation prompt, in
    place. Code-enforced, not model-requested -- "prompts request, code
    enforces," the same discipline validate_concept keeps -- because a
    template asking the model to "stay consistent" is a request it can
    silently ignore for any one shot, and that shot is the one that
    renders wrong. A no-op without a bible or without AI shots; never
    double-prepends a shot whose prompt already opens with it (rework
    passes re-run this).
    """
    if not bible:
        return shots
    for shot in shots or []:
        if shot.get("source") != "AI":
            continue
        prompt = (shot.get("prompt") or "").strip()
        if prompt and not prompt.startswith(bible):
            shot["prompt"] = f"{bible}. {prompt}"
    return shots


def generate_concept_ideas(brand: str, client=None, spark=None, gemini_client=None,
                           model: str = MODEL, count: int = DEFAULT_IDEA_COUNT,
                           use_pov: bool = False, db_path=None,
                           references: str = "", formats=None,
                           only_locations=None) -> dict:
    """
    Stage one: several cheap ideas in a single call, so they can be
    varied against each other rather than rolled independently. No shot
    lists -- an idea you discard shouldn't have cost shot detail.

    `references` is passed in already retrieved, by the caller at the
    edge (reference_block), so this stays pure with respect to the
    reference library and testable without a store.

    `only_locations` pins this one run to a subset of locations on file
    (see _apply_location_lock) -- omit it and every location applies,
    same as before this existed.
    """
    kwargs = {"path": db_path} if db_path is not None else {}
    locations = preprod.list_locations(**kwargs)
    if not locations:
        # Grounding is an enhancement, never a gate -- the same degrade
        # contract reference_block keeps when the library is down.
        print(NO_LOCATIONS_NOTE, file=sys.stderr)

    locations, lock_location = _apply_location_lock(locations, only_locations)

    if formats is None:
        formats = ranked_formats(**kwargs)

    prompt = build_ideas_prompt(locations, brand, client, spark, count,
                                references=references, formats=formats,
                                lock_location=lock_location)
    ideas = parse_ideas_response(generate_with_retry(gemini_client, model, prompt))

    concept_ids = preprod.save_concept_ideas(
        ideas, brand=brand, client=client, spark=spark,
        prompt_template=prompt, use_pov=use_pov, **kwargs,
    )
    return {"concept_ids": concept_ids, "ideas": ideas}


def gold_standard_example() -> str:
    """The canonical proven prompt (prompts/gold_standard.md), injected as the
    exemplar every scene brief is measured against. '' if the file is absent --
    the exemplar is an enhancement, never a hard dependency."""
    try:
        return (PROMPTS_DIR / "gold_standard.md").read_text().strip()
    except OSError:
        return ""


def build_scene_brief_prompt(brand: str, spark=None, references: str = "",
                             cast=None) -> str:
    """The winning skeleton: one cohesive whole-scene prompt (character refs
    -> grounded style -> beats -> diegetic sound -> avoid-list), matched
    against the gold-standard exemplar."""
    template = (PROMPTS_DIR / "scene_brief_prompt.txt").read_text()
    example = gold_standard_example() or "(no gold-standard example on file)"
    return (template
            .replace("{brand}", load_brand(brand))
            .replace("{spark}", f"CREATIVE SPARK FROM THE FILMMAKER: {spark}" if spark else "")
            .replace("{references}", references or NO_REFERENCES_NOTE)
            .replace("{cast}", cast or NO_CAST_NOTE)
            .replace("{example}", example))


def parse_scene_brief_response(text: str) -> dict:
    """`hook` and `logline` are the human-readable summary a card shows;
    they're optional so an older response (or a model that skips them)
    still parses -- the `brief` is the deliverable, they're the label."""
    data = json.loads(strip_fences(text))
    return {"title": (data.get("title") or "Untitled scene").strip(),
            "hook": (data.get("hook") or "").strip(),
            "logline": (data.get("logline") or "").strip(),
            "brief": (data.get("brief") or "").strip()}


def generate_scene_brief(brand: str, spark=None, gemini_client=None,
                         model: str = MODEL, references: str = "", cast=None) -> dict:
    """One cohesive whole-scene prompt in the proven skeleton -- for a video
    model that renders a full scene from a single description (Veo / Sora /
    Kling / OpenArt Director). Pure w.r.t. the reference library: `references`
    arrives already retrieved by the caller."""
    prompt = build_scene_brief_prompt(brand, spark=spark, references=references, cast=cast)
    return parse_scene_brief_response(generate_with_retry(gemini_client, model, prompt))


DEFAULT_SCENE_TOOL = "RUNWAY"


def generate_scene_concept(brand: str, spark=None, gemini_client=None,
                           model: str = MODEL, references: str = "", cast=None,
                           db_path=None, tool: str = DEFAULT_SCENE_TOOL,
                           image_refs=None) -> dict:
    """
    A concept IS one scene, and the scene IS one prompt (2026-08-26).

    The two-stage idea -> shot-list shape split a concept across up to six
    independently-rendered prompts, which is what the scene bible existed
    to paper over. One paste-ready whole-scene prompt is what the video
    models actually want, so the concept carries exactly one shot and that
    shot's prompt is the deliverable -- the thing generated, graded, and
    rendered.

    Reuses build_scene_brief_prompt: the proven gold-standard skeleton
    (grounded style -> beats -> diegetic sound -> avoid-list) rather than
    a second template that would drift from it. Saved as an ordinary
    shoot_concepts row with a one-element shots list, so the scene board,
    Director, render, and autopilot all keep working unmodified.

    No scene bible is prepended: it exists to hold SEPARATE shots to one
    look, and there are no separate shots to hold.
    """
    kwargs = {"path": db_path} if db_path is not None else {}
    # cast=None means "everything on file", "" means explicitly none --
    # the same convention generate_concept keeps.
    if cast is None:
        cast = format_cast(entities.list_characters(**kwargs),
                           entities.list_props(**kwargs))
    prompt = build_scene_brief_prompt(brand, spark=spark, references=references,
                                      cast=cast)
    contents = prompt
    if image_refs:
        from google.genai import types
        # A caption before each photo, same binding the keyframe uses.
        # This step WRITES the scene, and the scene text is what
        # named_assets later reads back to decide which assets get
        # attached -- so a photo misread here propagates all the way to
        # the render. Refs may be (data, mime) or (data, mime, label).
        contents = []
        for ref in image_refs:
            data, mime = ref[0], ref[1]
            label = ref[2] if len(ref) > 2 else ""
            if label:
                contents.append(label)
            contents.append(types.Part.from_bytes(data=data, mime_type=mime))
        contents.append(prompt)
    parsed = parse_scene_brief_response(
        generate_with_retry(gemini_client, model, contents))

    shot = {"n": 1, "type": "BROLL", "source": "AI",
            "tool": (tool or DEFAULT_SCENE_TOOL).upper(),
            "desc": parsed["logline"] or parsed["title"],
            "prompt": parsed["brief"]}
    concept = {"title": parsed["title"], "hook": parsed["hook"],
               "logline": parsed["logline"], "shots": [shot]}
    location_names = [loc["name"] for loc in preprod.list_locations(**kwargs)]
    allowed = ZEROPAGE_AI_TOOLS if brand == "zeropage" else None
    warnings = validate_concept(concept, location_names, allowed_tools=allowed)
    concept_id = preprod.save_concept(
        concept, brand=brand, spark=spark, prompt_template=prompt,
        warnings=warnings, **kwargs)
    return {"concept_id": concept_id, "concept": concept, "warnings": warnings}


def build_scenes_prompt(idea: str, brand: str, count: int, locations: list,
                        references: str = "", cast=None) -> str:
    """N standalone scene prompts off ONE idea, in the same proven
    skeleton build_scene_brief_prompt uses -- the difference is plural
    and independent: these are competing takes to pick between, not
    parts of one video."""
    template = (PROMPTS_DIR / "scenes_prompt.txt").read_text()
    example = gold_standard_example() or "(no gold-standard example on file)"
    return (template
            .replace("{count}", str(count))
            .replace("{idea}", (idea or "").strip() or "(no idea given — surprise me)")
            .replace("{brand}", load_brand(brand))
            .replace("{cast}", cast or NO_CAST_NOTE)
            .replace("{locations}", format_locations(locations))
            .replace("{references}", references or NO_REFERENCES_NOTE)
            .replace("{example}", example))


def parse_scenes_response(text: str) -> list:
    """Tolerant of the two shapes a model reaches for: the documented
    {"scenes": [...]} and a bare array. Anything without a prompt is
    dropped here rather than saved as an unrenderable row."""
    data = json.loads(strip_fences(text))
    raw = data.get("scenes") if isinstance(data, dict) else data
    scenes = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        prompt = (item.get("prompt") or item.get("brief") or "").strip()
        if not prompt:
            continue
        scenes.append({
            "title": (item.get("title") or "Untitled scene").strip(),
            "location": (item.get("location") or "").strip(),
            "prompt": prompt,
        })
    return scenes


def generate_scene_concepts(idea: str, brand: str, count: int = 4,
                            gemini_client=None, model: str = MODEL,
                            references: str = "", cast=None, db_path=None,
                            tool: str = DEFAULT_SCENE_TOOL,
                            refs=None, image_refs=None) -> dict:
    """
    One idea -> N scenes to PICK BETWEEN (2026-08-26).

    generate_scene_concept writes the one scene a Create button asks
    for. This writes several in a single call, so they are varied
    against each other rather than rolled independently (the
    generate_concept_ideas reasoning), and the human picks -- which is
    the label preprod.pick_rate counts.

    Each scene is saved in exactly the shape generate_scene_concept
    uses: an ordinary shoot_concepts row with a ONE-element shots list.
    No second data model, so the scene board, Director, render and
    autopilot keep working unmodified.

    `refs` are the asset-photo URLs this batch was written against; they
    ride ON the shot so they reach every node of the Director chain
    later. `image_refs` are those same photos as bytes for THIS call's
    vision input.
    """
    kwargs = {"path": db_path} if db_path is not None else {}
    locations = preprod.list_locations(**kwargs)
    if not locations:
        print(NO_LOCATIONS_NOTE, file=sys.stderr)
    prompt = build_scenes_prompt(idea, brand, count, locations,
                                 references=references, cast=cast)
    contents = prompt
    if image_refs:
        from google.genai import types
        # A caption before each photo, same binding the keyframe uses.
        # This step WRITES the scene, and the scene text is what
        # named_assets later reads back to decide which assets get
        # attached -- so a photo misread here propagates all the way to
        # the render. Refs may be (data, mime) or (data, mime, label).
        contents = []
        for ref in image_refs:
            data, mime = ref[0], ref[1]
            label = ref[2] if len(ref) > 2 else ""
            if label:
                contents.append(label)
            contents.append(types.Part.from_bytes(data=data, mime_type=mime))
        contents.append(prompt)
    scenes = parse_scenes_response(generate_with_retry(gemini_client, model, contents))

    location_names = [loc["name"] for loc in locations]
    allowed = ZEROPAGE_AI_TOOLS if brand == "zeropage" else None
    saved = []
    for scene in scenes:
        shot = {"n": 1, "type": "BROLL", "source": "AI",
                "tool": (tool or DEFAULT_SCENE_TOOL).upper(),
                "desc": scene["title"], "prompt": scene["prompt"],
                "refs": list(refs or [])}
        if scene.get("location"):
            shot["location"] = scene["location"]
        concept = {"title": scene["title"], "hook": "", "logline": "",
                   "shots": [shot]}
        warnings = validate_concept(concept, location_names, allowed_tools=allowed)
        concept_id = preprod.save_concept(
            concept, brand=brand, spark=idea, prompt_template=prompt,
            warnings=warnings, **kwargs)
        saved.append({"concept_id": concept_id, "title": scene["title"],
                      "warnings": warnings})
    return {"scenes": saved, "prompt_template": prompt}


def write_scene_for_concept(concept_id: int, gemini_client=None,
                            model: str = MODEL, references: str = "", cast=None,
                            db_path=None, tool: str = DEFAULT_SCENE_TOOL) -> dict:


    """
    Stage two, for an idea you chose: write ITS scene prompt.

    Replaces generate_shot_list (deleted 2026-08-26). The old stage two
    exploded one idea into up to six independently-rendered prompts; now
    an idea becomes exactly one scene, the same artifact
    generate_scene_concept writes from scratch -- so an idea that arrives
    from anywhere (the ideas stage, rework's evidence-grounded slate) has
    a path to a real prompt instead of being a dead end.

    The picked title/hook/logline are the LABEL and are never rewritten;
    this fills in the shots only, through update_concept_shots.
    """
    kwargs = {"path": db_path} if db_path is not None else {}
    concept = preprod.get_concept(concept_id, **kwargs)
    if concept is None:
        raise ValueError(f"no concept {concept_id}")

    # the idea itself is the spark for its scene
    spark = " -- ".join(str(part) for part in (
        concept.get("title"), concept.get("hook"), concept.get("logline"),
        concept.get("spark")) if part)
    if cast is None:
        cast = format_cast(entities.list_characters(**kwargs),
                           entities.list_props(**kwargs))
    prompt = build_scene_brief_prompt(concept.get("brand") or "antihero",
                                      spark=spark, references=references, cast=cast)
    parsed = parse_scene_brief_response(
        generate_with_retry(gemini_client, model, prompt))

    shot = {"n": 1, "type": "BROLL", "source": "AI",
            "tool": (tool or DEFAULT_SCENE_TOOL).upper(),
            "desc": concept.get("logline") or concept.get("title") or "",
            "prompt": parsed["brief"]}
    location_names = [loc["name"] for loc in preprod.list_locations(**kwargs)]
    allowed = ZEROPAGE_AI_TOOLS if concept.get("brand") == "zeropage" else None
    warnings = validate_concept({**concept, "shots": [shot]}, location_names,
                                use_pov=bool(concept.get("use_pov")),
                                allowed_tools=allowed)
    preprod.update_concept_shots(concept_id, {"shots": [shot]},
                                 warnings=warnings, **kwargs)
    return {"concept_id": concept_id, "shots": [shot], "warnings": warnings}

def parse_concept_response(text: str) -> dict:
    """The testable seam: raw model text -> the concept dict."""
    data = json.loads(strip_fences(text))
    concept = data.get("concept", data)
    if not concept.get("title"):
        raise ValueError("concept has no title")
    return concept


def validate_concept(concept: dict, location_names: list, use_pov: bool = False,
                     allowed_tools=None) -> list:
    """
    Check the model's output against what the prompt asked for and
    return visible warnings. Nothing here blocks: a concept that breaks
    a rule is still saved with its warnings attached, because it is
    worth looking at and deciding on. Grounding shapes the generation;
    a mismatch is advice to the human, not a gate.

    A shot's source is CAMERA (you capture it; `cam` names the body) or
    AI (a platform generates it; `tool` + `prompt` say how). No source
    means CAMERA -- every concept written before the de-cap.

    `allowed_tools` narrows which AI tool names pass -- Zero Page's plans
    should be checked against ZEROPAGE_AI_TOOLS (Higgsfield/Runway only),
    not every tool in the shot.py registry; omit it and every registered
    tool is legal, same as before this existed.
    """
    allowed_tools = allowed_tools or AI_TOOLS
    warnings = []
    shots = concept.get("shots") or []

    if not shots:
        warnings.append("concept has no shots")

    for i, shot in enumerate(shots, start=1):
        n = shot.get("n", i)
        if shot.get("type") not in SHOT_TYPES:
            warnings.append(f"shot {n}: type must be one of {SHOT_TYPES}, got {shot.get('type')!r}")

        source = shot.get("source", "CAMERA")
        if source not in SHOT_SOURCES:
            warnings.append(
                f"shot {n}: source must be one of {SHOT_SOURCES}, got {source!r}"
            )
        elif source == "AI":
            # cam names a physical body; an AI shot doesn't have one.
            if shot.get("tool") not in allowed_tools:
                warnings.append(
                    f"shot {n}: AI tool must be one of {allowed_tools}, got {shot.get('tool')!r}"
                )
            if not (shot.get("prompt") or "").strip():
                warnings.append(f"shot {n}: AI shot has no generation prompt")
        else:
            allowed_cams = CAMERAS if use_pov else ("BMPCC",)
            if shot.get("cam") not in allowed_cams:
                warnings.append(
                    f"shot {n}: cam must be one of {allowed_cams}, got {shot.get('cam')!r}"
                )

        location = shot.get("location")
        # Camera shots must name a real room -- you can only film where you
        # actually are. AI shots may invent or extend a space (the model
        # generates the scene), so an unlisted location is allowed there and
        # is not flagged. This is what lets concepts range beyond one room.
        if source != "AI" and location not in location_names:
            warnings.append(f"shot {n}: unknown location {location!r} -- not a described space")

    # legacy shape: one concept-level ai dict instead of per-shot source
    ai = concept.get("ai")
    if ai and ai.get("tool") not in allowed_tools:
        warnings.append(f"ai tool must be one of {allowed_tools}, got {ai.get('tool')!r}")

    return warnings


def _sentence(text: str) -> str:
    text = text.strip()
    return text if text[-1:] in ".!?…" else text + "."


def director_prompt(shot: dict, concept=None) -> str:
    # concept: dict or None (CI pins Python 3.9, so no `dict | None`
    # annotation here -- same constraint ranked_formats notes above).
    """
    The OpenArt Director version of one planned shot: flowing natural
    language with the story context the terse per-tool prompts drop --
    subject, setting, mood, what happens, why it matters to the beat --
    the way you'd actually describe a shot to a director. Director is
    conversational (checked 2026-08-20; see shot.CAMERA_PROSE's note),
    so readability is the format, and there's no API: this text exists
    to be pasted into Director's chat by hand.

    Pure -- composed from what the shot row already carries, no model
    call, so a hundred of these cost nothing. A shot's reference_image
    is deliberately NOT mentioned here: attachments travel next to the
    description (the UI shows the capture beside this text), never
    inside it, same contract as veo_parameters().
    """
    concept = concept or {}
    sentences = []

    body = (shot.get("desc") or "").strip() or (shot.get("prompt") or "").strip()
    if body:
        sentences.append(_sentence(body))
    location = (shot.get("location") or "").strip()
    if location:
        sentences.append(_sentence(f"The scene is {location}"))
    light = (shot.get("light") or "").strip()
    if light:
        sentences.append(_sentence(f"Light: {light}"))

    title = (concept.get("title") or "").strip()
    logline = (concept.get("logline") or "").strip()
    if title or logline:
        story = " — ".join(p for p in (title, logline) if p)
        sentences.append(_sentence(f"Story context: {story}"))
    hook = (concept.get("hook") or "").strip()
    if hook and shot.get("n") == 1:
        sentences.append(_sentence(
            f"This shot opens the piece and has to land the hook: {hook}"))
    # concept dicts at generation time say "grade"; saved rows say
    # "grade_note" -- accept both so this works on either side of save
    grade = (concept.get("grade") or concept.get("grade_note") or "").strip()
    if grade:
        sentences.append(_sentence(f"Grade: {grade}"))

    return " ".join(sentences)


def generate_concept(brand: str, client=None, spark=None, gemini_client=None,
                     model: str = MODEL, use_pov: bool = False, db_path=None,
                     references: str = "", cast=None, formats=None,
                     only_locations=None, image_refs=None) -> dict:
    """
    One concept, grounded in the described locations, validated and
    saved. Returns {"concept_id", "concept", "warnings"}.

    Like generate_concept_ideas, `references` arrives already retrieved
    from the edge rather than being fetched here. `cast` follows the
    same contract: None means "everything on file" (the default the CLI
    keeps); a caller that picked specific characters/props passes the
    already-formatted block, and "" explicitly means no cast.

    `only_locations` pins this one run to a subset of locations on file
    (see _apply_location_lock) -- omit it and every location applies,
    same as before this existed.

    `image_refs` is an optional list of (image_bytes, mime_type) pairs --
    ad hoc reference photos attached for this one generation (see
    app/main.py's studio composer / _split_studio_references). When
    present they ride into the same Gemini call as real vision input --
    the model actually sees them, not just a text description -- using
    the same Part.from_bytes-then-text-last shape
    locations.describe_location already uses elsewhere in this codebase.
    None/empty means text-only, exactly as before this parameter existed.
    """
    kwargs = {"path": db_path} if db_path is not None else {}
    locations = preprod.list_locations(**kwargs)
    if not locations:
        print(NO_LOCATIONS_NOTE, file=sys.stderr)

    locations, lock_location = _apply_location_lock(locations, only_locations)

    if cast is None:
        cast = format_cast(entities.list_characters(**kwargs), entities.list_props(**kwargs))

    if formats is None:
        formats = ranked_formats(**kwargs)

    prompt = build_concept_prompt(locations, brand, client, spark, use_pov=use_pov,
                                  references=references, cast=cast, formats=formats,
                                  lock_location=lock_location)

    contents = prompt
    if image_refs:
        contents = [
            types.Part.from_bytes(data=data, mime_type=mime_type)
            for data, mime_type in image_refs
        ] + [prompt + IMAGE_REFS_NOTE]

    concept = parse_concept_response(generate_with_retry(gemini_client, model, contents))

    bible = derive_scene_bible(concept.get("title"), concept.get("logline"), concept.get("grade"))
    concept["shots"] = apply_scene_bible(concept.get("shots"), bible)

    location_names = [loc["name"] for loc in locations]
    allowed_tools = ZEROPAGE_AI_TOOLS if brand == "zeropage" else None
    warnings = validate_concept(concept, location_names, use_pov=use_pov, allowed_tools=allowed_tools)

    used = {shot.get("location") for shot in concept.get("shots") or []}
    location_ids = [loc["id"] for loc in locations if loc["name"] in used]

    concept_id = preprod.save_concept(
        concept, brand=brand, client=client, spark=spark,
        location_ids=location_ids, prompt_template=prompt,
        warnings=warnings, use_pov=use_pov, **kwargs,
    )
    return {"concept_id": concept_id, "concept": concept, "warnings": warnings}


def format_concept_as_text(concept: dict, warnings=None) -> str:
    """Readable on the day, next to the camera."""
    lines = [
        concept.get("title", "untitled"),
        f"  {concept.get('duration', '?')} — {concept.get('logline', '')}",
        f"  HOOK: {concept.get('hook', '')}",
        "",
    ]
    for shot in concept.get("shots") or []:
        lines.append(
            f"  {shot.get('n', '?'):>2}. [{shot.get('type', '?')}/{shot.get('cam', '?')}] "
            f"{shot.get('location', '?')}"
        )
        lines.append(f"      {shot.get('desc', '')}")
        if shot.get("light"):
            lines.append(f"      light: {shot['light']}")

    ai = concept.get("ai")
    if ai:
        lines += ["", f"  AI [{ai.get('tool', '?')}]: {ai.get('technique', '')}",
                  f"      {ai.get('prompt', '')}"]
    if concept.get("edit"):
        lines += ["", f"  EDIT: {concept['edit']}"]
    if concept.get("grade"):
        lines.append(f"  GRADE: {concept['grade']}")
    for warning in warnings or []:
        lines.append(f"  WARNING: {warning}")
    return "\n".join(lines)


def main(db_path=None):
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Generate shoot concepts grounded in your described locations. "
                    "Two stages: ideas first, then a shot list for the ones you pick."
    )
    parser.add_argument("--brand", choices=preprod.BRANDS, default="antihero")
    parser.add_argument("--client", default=None, help="client or spec type (zeropage only)")
    parser.add_argument("--spark", default=None, help="a direction to build the ideas around")
    parser.add_argument("--count", type=int, default=DEFAULT_IDEA_COUNT,
                        help="how many ideas to generate (one call regardless)")
    parser.add_argument("--scene", type=int, default=None, metavar="CONCEPT_ID",
                        help="skip idea generation and write the scene prompt "
                             "for this concept id")
    parser.add_argument("--only-location", action="append", default=None, metavar="NAME",
                        help="pin this run to one location on file (repeatable for more "
                             "than one) -- a deliberate choice, so the variety nudge "
                             "toward AI-invented environments is skipped")
    args = parser.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY (or GOOGLE_API_KEY) not set", file=sys.stderr)
        sys.exit(1)

    path = db_path if db_path is not None else DB_PATH
    init_db(path=path)
    preprod.init(path=path)
    entities.init(path=path)

    gemini_client = genai.Client(api_key=api_key)

    if args.scene is not None:
        try:
            result = write_scene_for_concept(
                args.scene, gemini_client=gemini_client,
                references=reference_block(spark=args.spark, client=args.client,
                                           db_path=path),
                db_path=path,
            )
        except ValueError as e:
            print(e, file=sys.stderr)
            sys.exit(1)

        concept = preprod.get_concept(args.scene, path=path)
        print(f"\nConcept {args.scene}")
        print(format_concept_as_text(concept, result["warnings"]))
        return

    references = reference_block(spark=args.spark, client=args.client, db_path=path)
    try:
        result = generate_concept_ideas(
            brand=args.brand, client=args.client, spark=args.spark,
            gemini_client=gemini_client, count=args.count, db_path=path,
            references=references, only_locations=args.only_location,
        )
    except ValueError as e:
        print(e, file=sys.stderr)
        sys.exit(1)

    print(f"\n{len(result['ideas'])} ideas — pick the ones worth shooting:\n")
    for concept_id, idea in zip(result["concept_ids"], result["ideas"]):
        print(f"  [{concept_id}] {idea['title']}")
        print(f"       hook: {idea.get('hook', '')}")
        print(f"       {idea.get('logline', '')}")
        if idea.get("why"):
            print(f"       ({idea['why']})")
        print()

    print("Plan a shoot for one:")
    print(f"  venv/bin/python -m src.shootgen --scene {result['concept_ids'][0]}")


if __name__ == "__main__":
    main()
