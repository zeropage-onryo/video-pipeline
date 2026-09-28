"""Give a rendered clip the Asset Bank row it was never given.

A clip on a concept's shot is cut by its `gen:<generated_assets.id>`
handle (src/cut/), so a clip with no generated_assets row cannot be cut
at all -- Assemble refuses it by name ("shot 1's clip is not in the Asset
Bank") rather than fall back to a URL. Rows are missing for clips filed
before their writer recorded one: the manual lane only started writing
them at 17:35 UTC on 2026-09-18, and #375 -- the first concept to go all
the way to a posted video -- was imported at 16:36 the same day.

For every slot (a shot, or a timed scene's part) whose clip no row
matches, this finds the ONE `generations` row of the same account whose
output file has the clip's file name, and writes the row
`render_assets.record` would have written then: same tool, model, prompt,
params, concept and shot. Anything with no generations row, or with more
than one candidate, is reported and LEFT ALONE -- a guessed provenance is
worse than a missing one.

Idempotent (record() upserts on generation_id) and additive. Run from the
project root, with the target database exported (like src.accounts, this
never reads .env on its own):

    python -m ops.backfill_render_assets            # report only
    python -m ops.backfill_render_assets --write
"""
from __future__ import annotations

import argparse
import json
import os
from typing import Any, Optional

from src import db, media, render_assets
from src.cut import assemble


def _name(path_or_url: str) -> str:
    return os.path.basename((path_or_url or "").split("?")[0])


def plan(dsn: Optional[str] = None) -> list[dict[str, Any]]:
    """Every unbanked clip on a live or archived concept, with the
    generations row that made it (or why there is none)."""
    with db.connect(dsn) as conn:
        concepts = conn.execute(
            "SELECT id, account_id, brand, shots_json FROM shoot_concepts "
            "WHERE account_id IS NOT NULL ORDER BY id").fetchall()
        gens = conn.execute(
            "SELECT id, account_id, tool, prompt, output_path, params_json FROM generations "
            "WHERE output_path IS NOT NULL AND account_id IS NOT NULL").fetchall()
    by_name: dict[tuple, list] = {}
    for g in gens:
        by_name.setdefault((g["account_id"], _name(g["output_path"])), []).append(g)

    indexes: dict[int, dict] = {}
    out = []
    for c in concepts:
        acct = c["account_id"]
        if acct not in indexes:
            indexes[acct] = assemble._asset_index(acct, dsn)
        index = indexes[acct]
        for slot in assemble.clip_slots({"shots": json.loads(c["shots_json"] or "[]")}):
            url = slot["media_url"]
            if not url or index.get(url) or index.get(media.tail_for(url) or ""):
                continue
            hits = by_name.get((acct, _name(url)), [])
            # a generations row that names a DIFFERENT concept is not this clip
            hits = [g for g in hits
                    if json.loads(g["params_json"] or "{}").get("concept_id") in (None, c["id"])]
            item = {"concept_id": c["id"], "account_id": acct, "brand": c["brand"],
                    "slot": slot["label"], "shot_n": slot["shot_n"], "media_url": url}
            if len(hits) == 1:
                item["generation"] = dict(hits[0])
            else:
                item["skip"] = ("no generations row names this file" if not hits
                                else f"{len(hits)} generations rows name this file")
            out.append(item)
    return out


def write(item: dict, dsn: Optional[str] = None) -> int:
    g = item["generation"]
    params = json.loads(g["params_json"] or "{}")
    row = render_assets.record(
        generation_id=g["id"], tool=g["tool"], model=params.get("model") or g["tool"],
        media_kind="video", prompt=g["prompt"], media_url=item["media_url"],
        output_path=g["output_path"], project=item["brand"],
        concept_id=item["concept_id"], shot_n=item["shot_n"],
        metadata={**params, "backfilled": "ops/backfill_render_assets.py"},
        account_id=item["account_id"], dsn=dsn)
    return row["id"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--write", action="store_true", help="write the rows (default: report)")
    args = ap.parse_args()
    items = plan()
    if not items:
        print("every clip on a concept already has its Asset Bank row")
        return 0
    for item in items:
        where = f"#{item['concept_id']} {item['slot']} {item['media_url']}"
        if "skip" in item:
            print(f"LEFT ALONE  {where} -- {item['skip']}")
            continue
        gid = item["generation"]["id"]
        if args.write:
            print(f"WROTE       {where} -> generated_assets #{write(item)} (generation {gid})")
        else:
            print(f"WOULD WRITE {where} <- generation {gid}")
    if not args.write:
        print("report only -- run with --write to record them")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
