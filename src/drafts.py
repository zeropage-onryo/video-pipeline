"""Draft, then finish (2026-10-11; item 5 of docs/tasks/task-studio-agent.md).

Runway and Higgsfield both let a person look at a cheap low-resolution clip
before paying for the good one. Here a scene is rendered shot by shot, so
the saving compounds: four shots on the dearest model at 1080p are four
full-price guesses.

A DRAFT is not a new kind of render. It is the Queue's ordinary approve at
the picked model's cheapest resolution -- `fal.draft_resolution`, read off
the same dated price table as every quote -- and it is offered only where
that tier is strictly cheaper than what the model renders at by default.
Nothing is stored to say "this is a draft": a clip's Assets row already
carries the model and the resolution it was rendered at, and `of_row`
reads them.

FINISH keeps the take the person liked. A second render at a higher
resolution is a different clip -- the models here take no seed that would
reproduce one (Seedance 2.5's schema has none, checked 2026-10-11) -- so
finishing is the upscale effect (src/effects.py `upscale`, Topaz, 2x) run
on the draft itself, and the finished clip is put on the shot in the
draft's place. It is the effects door with a target, never a second way to
spend: the same checks, the same quote, the same hold. The draft stays on
the Assets wall.

`src/` never imports `app/`: the routes call in.
"""
from __future__ import annotations

from typing import Any, Optional

from . import fal

# what finishing a draft runs, and at what setting
FINISH_EFFECT = "upscale"
FINISH_OPTIONS = {"upscale_factor": 2}


def of_row(row: Optional[dict]) -> Optional[dict]:
    """{"frame", "model"} when this Assets row is a clip rendered at its
    model's draft resolution, else None. A row from any other tool, an
    image, a model no longer in the table: None."""
    if not row or row.get("media_kind") != "video":
        return None
    meta = row.get("metadata") or {}
    model = row.get("model") or meta.get("model")
    frame = meta.get("resolution")
    if model and frame and fal.is_draft(str(model), str(frame)):
        return {"frame": str(frame), "model": str(model)}
    return None


def _index(account_id: Optional[int], dsn: Optional[str]) -> dict:
    from .cut import assemble
    return assemble._asset_index(account_id, dsn)


def _row_for(index: dict, media_url: Optional[str]) -> Optional[dict]:
    from . import media
    if not media_url:
        return None
    return index.get(media_url) or index.get(media.tail_for(media_url) or "")


def in_concept(concept: dict, *, account_id: Optional[int], dsn: Optional[str] = None,
               index: Optional[dict] = None) -> list[dict[str, Any]]:
    """The clips of this scene that are drafts, in shot order:
    [{"shot_n", "part", "label", "ref", "frame", "model"}]. `ref` is the
    clip's render id (`gen:<id>`), which is how Finish names it. `index`
    lets a listing build the Assets index once for many scenes."""
    from .cut import assemble
    index = index if index is not None else _index(account_id, dsn)
    out = []
    for slot in assemble.clip_slots(concept):
        row = _row_for(index, slot["media_url"])
        draft = of_row(row)
        if draft and not row.get("deleted_at"):
            out.append({"shot_n": slot["shot_n"], "part": slot["part"], "label": slot["label"],
                        "ref": f"gen:{row['id']}", **draft})
    return out


def on_the_wall(rows: list, *, account_id: Optional[int],
                dsn: Optional[str] = None) -> dict[int, dict]:
    """{asset id: {"frame", "model"}} for the rows that are a draft AND are
    still the clip on their shot. A draft that was finished stays on the
    wall as a render like any other: calling it a draft there would point
    at a Finish button that no longer exists."""
    from . import media, preprod
    from .cut import assemble
    found = {r["id"]: of_row(r) for r in rows if r.get("concept_id") and of_row(r)}
    if not found:
        return {}
    by_concept: dict[int, set] = {}
    wanted = sorted({r["concept_id"] for r in rows if r["id"] in found})
    for concept in preprod.get_concepts(wanted, dsn, account_id=account_id):
        held = set()
        for slot in assemble.clip_slots(concept):
            if slot["media_url"]:
                held.update(k for k in (slot["media_url"], media.tail_for(slot["media_url"])) if k)
        by_concept[concept["id"]] = held
    out = {}
    for r in rows:
        if r["id"] not in found:
            continue
        url = (r.get("media_url") or "").strip()
        held = by_concept.get(r["concept_id"], set())
        if url in held or (media.tail_for(url) or "") in held:
            out[r["id"]] = found[r["id"]]
    return out


def finish_target(ref: str, *, account_id: Optional[int],
                  dsn: Optional[str] = None) -> dict[str, Any]:
    """The shot a finished clip will be put on, or ValueError.

    `ref` must be a clip of this account's (`gen:<id>`) that is, right now,
    the clip on a shot of one of its scenes. A clip that has since been
    replaced is refused: finishing it would overwrite the newer one."""
    from . import preprod, render_assets
    from .cut import assemble
    kind, _, rest = str(ref or "").strip().partition(":")
    if kind != "gen" or not rest.isdigit():
        raise ValueError("a finish names the draft by its render id (gen:<id>)")
    row = render_assets.get(int(rest), dsn, account_id=account_id)
    if not row or row.get("deleted_at") or row.get("media_kind") != "video":
        raise ValueError("no such clip")
    concept_id = row.get("concept_id")
    concept = (preprod.get_concept(concept_id, dsn, account_id=account_id)
               if concept_id else None)
    if concept is None:
        raise ValueError("that clip is not a scene's shot, so there is nothing to finish onto")
    index = _index(account_id, dsn)
    for slot in assemble.clip_slots(concept):
        on_slot = _row_for(index, slot["media_url"])
        if on_slot and on_slot["id"] == row["id"]:
            return {"asset_id": row["id"], "concept_id": int(concept_id),
                    "shot_n": slot["shot_n"], "part": slot["part"], "label": slot["label"],
                    "title": concept.get("title") or f"Scene {concept_id}",
                    "draft": of_row(row)}
    raise ValueError("that clip is no longer on its shot (it was replaced)")


def attach(target: dict, media_url: str, asset_id: Optional[int], *,
           account_id: Optional[int], dsn: Optional[str] = None) -> None:
    """Put the finished clip on the shot in the draft's place, and file the
    new render under the same scene on the Assets wall. Raises on a scene
    or a shot that is gone; the caller decides what a paid-for clip that
    could not be attached means (it is on the wall either way)."""
    from . import preprod, render_assets, timeline
    if target.get("part"):
        timeline.attach_part(target["concept_id"], target["shot_n"], target["part"],
                             "media_url", media_url, db_path=dsn, account_id=account_id)
    else:
        kwargs = {"dsn": dsn} if dsn is not None else {}
        preprod.set_shot_media_url(target["concept_id"], target["shot_n"], media_url,
                                   **kwargs, account_id=account_id)
    if asset_id:
        render_assets.link(int(asset_id), dsn, account_id=account_id,
                           concept_id=target["concept_id"], shot_n=target["shot_n"])
