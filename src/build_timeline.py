#!/usr/bin/env python3
import json
import sys
from pathlib import Path

from resolve_edit import base_name, build_clip_index, get_resolve

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONCEPTS_PATH = PROJECT_ROOT / "concepts.json"


def cut_field(cut: dict, *keys):
    for key in keys:
        if key in cut:
            return cut[key]
    return None


def build_timeline_for_edit(media_pool, project, clip_index: dict, edit: dict):
    title = edit.get("title", "Untitled")
    edit_list = edit.get("edit_list", [])

    subclips = []
    skipped = []
    for cut in edit_list:
        filename = cut_field(cut, "clip", "filename", "file")
        in_point = cut_field(cut, "in", "in_point", "start")
        out_point = cut_field(cut, "out", "out_point", "end")

        clip = clip_index.get(base_name(filename)) if filename else None
        if not clip or in_point is None or out_point is None:
            skipped.append(filename)
            continue

        fps = float(clip.GetClipProperty("FPS") or 24)
        subclips.append({
            "mediaPoolItem": clip,
            "startFrame": round(in_point * fps),
            "endFrame": round(out_point * fps),
        })

    if not subclips:
        print(f"  {title}: no usable clips, skipped entirely")
        return

    timeline = media_pool.CreateEmptyTimeline(title)
    if not timeline:
        print(f"  {title}: failed to create timeline (name may already exist)")
        return

    project.SetCurrentTimeline(timeline)
    added = media_pool.AppendToTimeline(subclips)

    status = "ok" if added else "AppendToTimeline reported failure"
    print(f"  {title}: {len(subclips)}/{len(edit_list)} cuts added ({status})")
    if skipped:
        print(f"    skipped (not in Resolve media pool): {skipped}")


def main():
    if not CONCEPTS_PATH.exists():
        print(f"{CONCEPTS_PATH} not found — run src/editgen.py first", file=sys.stderr)
        sys.exit(1)

    concepts = json.loads(CONCEPTS_PATH.read_text())

    resolve = get_resolve()
    project = resolve.GetProjectManager().GetCurrentProject()
    if project is None:
        raise RuntimeError("No project open in DaVinci Resolve. Open a project first.")

    media_pool = project.GetMediaPool()
    clip_index = build_clip_index(media_pool.GetRootFolder())

    print(f"Building {len(concepts)} timeline(s)...")
    for edit in concepts:
        build_timeline_for_edit(media_pool, project, clip_index, edit)


if __name__ == "__main__":
    main()
