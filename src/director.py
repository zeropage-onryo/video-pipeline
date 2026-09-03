"""
Director mode for the scene board: one note in, a revised scene out.

The conversational half OpenArt's Director has and the static board
didn't: "shot 2 slower", "hold the reveal a beat longer", "move it to
the bedroom" -- each note is one billed model call that revises the
stored shot plan in place, validated by the same code that checks a
fresh generation (shootgen.validate_concept, advisory as always), and
saved through preprod.update_concept_shots so the concept's picked
title/hook/logline are never touched.

Two protections keep a note from quietly destroying work:
- Attached material survives: a revised shot with the same "n" keeps
  its reference_image and media_url unless the model explicitly
  returned new ones -- a wording change must not detach a clip you
  already rendered.
- Broken output never lands: an unparseable response, an empty shot
  list, or a plan that lost more than half the shots is an error
  result, and the stored scene stays exactly as it was.
"""
import json
from pathlib import Path
from typing import Optional

from . import preprod
from .gemini_utils import generate_with_retry, strip_fences

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
MODEL = "gemini-3-flash-preview"

# fields that ride along by shot "n" when the revision omits them
CARRIED_FIELDS = ("reference_image", "media_url")


def build_direct_prompt(concept: dict, note: str, locations_block: str) -> str:
    template = (PROMPTS_DIR / "direct_prompt.txt").read_text()
    return (
        template
        .replace("{note}", note)
        .replace("{title}", concept.get("title") or "")
        .replace("{hook}", concept.get("hook") or "")
        .replace("{logline}", concept.get("logline") or "")
        .replace("{duration}", concept.get("duration") or "unspecified")
        .replace("{edit}", concept.get("edit_note") or concept.get("edit") or "none")
        .replace("{shots}", json.dumps(concept.get("shots") or [], indent=1))
        .replace("{locations}", locations_block or "(no described locations on file)")
    )


def _carry_over(old_shots: list, new_shots: list) -> list:
    by_n = {s.get("n"): s for s in old_shots}
    for shot in new_shots:
        old = by_n.get(shot.get("n"))
        if not old:
            continue
        for field in CARRIED_FIELDS:
            if old.get(field) and not shot.get(field):
                shot[field] = old[field]
    return new_shots


def _summarise(old_shots: list, new_shots: list) -> str:
    old_by_n = {s.get("n"): s for s in old_shots}
    changed = [str(s.get("n")) for s in new_shots
               if old_by_n.get(s.get("n")) != s]
    added = [str(s.get("n")) for s in new_shots if s.get("n") not in old_by_n]
    removed = [str(n) for n in old_by_n if n not in {s.get("n") for s in new_shots}]
    parts = []
    if changed:
        parts.append(f"revised shot(s) {', '.join(changed)}")
    if added:
        parts.append(f"added {', '.join(added)}")
    if removed:
        parts.append(f"removed {', '.join(removed)}")
    return " · ".join(parts) or "no shot changed"


def direct_scene(concept_id: int, note: str, gemini_client=None,
                 model: str = MODEL, db_path=None,
                 account_id: Optional[int] = None,
) -> dict:
    """
    Never raises: {"ok", "summary", "warnings", "error"}. The stored
    scene is only replaced by a plan that parsed, kept its shots, and
    re-validated -- anything less leaves it untouched and says why.
    """
    from . import shootgen

    note = (note or "").strip()
    kwargs = {"dsn": db_path} if db_path is not None else {}
    try:
        if not note:
            return {"ok": False, "error": "an empty note directs nothing"}
        concept = preprod.get_concept(concept_id, **kwargs, account_id=account_id)
        if concept is None:
            return {"ok": False, "error": f"no concept {concept_id}"}
        old_shots = concept.get("shots") or []
        if not old_shots:
            return {"ok": False,
                    "error": "this concept has no shot plan yet — approve it first"}

        locations = preprod.list_locations(**kwargs, account_id=account_id)
        prompt = build_direct_prompt(
            concept, note, shootgen.format_locations(locations))

        text = generate_with_retry(gemini_client, model, prompt)
        try:
            plan = json.loads(strip_fences(text))
        except (ValueError, TypeError) as e:
            return {"ok": False, "error": f"unparseable revision: {e}"}

        new_shots = plan.get("shots") or []
        if not new_shots:
            return {"ok": False, "error": "the revision came back with no shots"}
        asked_for_cuts = any(word in note.lower()
                             for word in ("remove", "drop", "cut", "delete", "merge"))
        if len(new_shots) < len(old_shots) and not asked_for_cuts:
            return {"ok": False,
                    "error": f"revision dropped from {len(old_shots)} to "
                             f"{len(new_shots)} shots — refused, the note didn't ask "
                             f"for cuts"}

        new_shots = _carry_over(old_shots, new_shots)
        warnings = shootgen.validate_concept(
            {**concept, "shots": new_shots},
            [loc["name"] for loc in locations],
            use_pov=bool(concept.get("use_pov")),
        )
        preprod.update_concept_shots(
            concept_id,
            {"duration": plan.get("duration"), "shots": new_shots,
             "edit": plan.get("edit")},
            warnings=warnings, **kwargs, account_id=account_id)

        return {"ok": True, "summary": _summarise(old_shots, new_shots),
                "warnings": warnings, "error": None}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def refine_shot_prompt(concept_id: int, shot_n, gemini_client=None,
                       model: str = MODEL, db_path=None,
                       account_id: Optional[int] = None,
) -> dict:
    """
    Never raises. Technique-aware polish for ONE shot's AI prompt --
    promptgen.refine_prompt against the ai_prompting shelf, written
    back only when the refinement actually changed something and passed
    promptgen's own sanity guard (which falls back to the original on
    anything broken).
    """
    from . import promptgen, rag, shootgen

    # promptgen.refine_prompt ships with in-progress work; until it
    # lands, polish reports itself unavailable rather than crashing --
    # the same degrade contract as director_prompt in the API.
    refine = getattr(promptgen, "refine_prompt", None)
    refine_domain = getattr(promptgen, "REFINE_DOMAIN", ("ai_prompting",))
    if refine is None:
        return {"ok": False,
                "error": "prompt polish (promptgen.refine_prompt) hasn't "
                         "landed in this build yet"}

    kwargs = {"dsn": db_path} if db_path is not None else {}
    try:
        concept = preprod.get_concept(concept_id, **kwargs, account_id=account_id)
        if concept is None:
            return {"ok": False, "error": f"no concept {concept_id}"}
        shots = concept.get("shots") or []
        shot = next((s for s in shots if s.get("n") == shot_n), None)
        if shot is None:
            return {"ok": False, "error": f"no shot {shot_n}"}
        raw = (shot.get("prompt") or "").strip()
        if not raw:
            return {"ok": False, "error": f"shot {shot_n} has no AI prompt"}

        tool = shot.get("tool") or ""
        query = (f"{tool} prompting technique for photorealistic AI video generation"
                 if tool else "AI video prompting technique")
        from . import accounts
        retrieval = rag.retrieve_references(
            query, k=5, domain=refine_domain,
            prefer_project=accounts.slug_of(account_id, **kwargs))
        references = rag.format_references(retrieval["references"]) \
            if retrieval.get("ok") and retrieval.get("references") else ""
        if not references:
            return {"ok": False,
                    "error": "no technique references reachable — "
                             "polish needs the ai_prompting shelf"}

        refined = refine(raw, tool, gemini_client,
                         model=model, references=references)
        if refined.strip() == raw:
            return {"ok": True, "changed": False,
                    "summary": "already technique-clean — kept as is", "error": None}

        shot["prompt"] = refined
        locations = preprod.list_locations(**kwargs, account_id=account_id)
        warnings = shootgen.validate_concept(
            {**concept, "shots": shots},
            [loc["name"] for loc in locations],
            use_pov=bool(concept.get("use_pov")),
        )
        preprod.update_concept_shots(
            concept_id,
            {"duration": concept.get("duration"), "shots": shots,
             "edit": concept.get("edit_note") or concept.get("edit")},
            warnings=warnings, **kwargs, account_id=account_id)
        return {"ok": True, "changed": True,
                "summary": f"shot {shot_n} prompt polished for {tool or 'its tool'}",
                "error": None}
    except Exception as e:
        return {"ok": False, "error": str(e)}
