#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = PROJECT_ROOT / "manifest.json"

RESOLVE_SCRIPT_API = "/Applications/DaVinci Resolve Studio.app/Contents/Resources/Developer/Scripting"
RESOLVE_SCRIPT_LIB = "/Applications/DaVinci Resolve Studio.app/Contents/Libraries/Fusion/fusionscript.so"


def get_resolve():
    os.environ.setdefault("RESOLVE_SCRIPT_LIB", RESOLVE_SCRIPT_LIB)
    sys.path.append(f"{RESOLVE_SCRIPT_API}/Modules")
    import DaVinciResolveScript as dvr

    resolve = dvr.scriptapp("Resolve")
    if resolve is None:
        raise RuntimeError(
            "Could not connect to DaVinci Resolve. Make sure Resolve is running with a "
            "project open, and that Preferences > General > External scripting using "
            "is set to 'Local'."
        )
    return resolve


def load_manifest() -> list[dict]:
    return json.loads(MANIFEST_PATH.read_text())


def base_name(filename: str) -> str:
    return filename.rsplit(".", 1)[0]


def build_clip_index(root_folder) -> dict:
    """Maps base filename (no extension) -> MediaPoolItem for every clip in the media pool."""
    index = {}
    for clip in root_folder.GetClipList():
        name = clip.GetClipProperty("File Name")
        if name and "." in name:
            index[base_name(name)] = clip
    return index


def match_manifest_to_clips(manifest: list[dict], clip_index: dict):
    matched = []
    unmatched_manifest = []
    for entry in manifest:
        clip = clip_index.get(base_name(entry["filename"]))
        if clip:
            matched.append((entry, clip))
        else:
            unmatched_manifest.append(entry["filename"])

    manifest_basenames = {base_name(e["filename"]) for e in manifest}
    unmatched_clips = [
        name for name in clip_index if name not in manifest_basenames
    ]
    return matched, unmatched_manifest, unmatched_clips


def create_timeline(media_pool, name: str, clip_items: list):
    timeline = media_pool.CreateEmptyTimeline(name)
    media_pool.AppendToTimeline(clip_items)
    return timeline


def main():
    manifest = load_manifest()

    resolve = get_resolve()
    project = resolve.GetProjectManager().GetCurrentProject()
    if project is None:
        raise RuntimeError("No project open in DaVinci Resolve. Open a project first.")

    media_pool = project.GetMediaPool()
    root_folder = media_pool.GetRootFolder()
    clip_index = build_clip_index(root_folder)

    matched, unmatched_manifest, unmatched_clips = match_manifest_to_clips(manifest, clip_index)

    print(f"Matched {len(matched)} / {len(manifest)} manifest entries to media pool clips")
    if unmatched_manifest:
        print("In manifest but missing from Resolve project:")
        for name in unmatched_manifest:
            print(f"  - {name}")
    if unmatched_clips:
        print("In Resolve project but missing a description in manifest:")
        for name in unmatched_clips:
            print(f"  - {name}")

    # TODO: send matched entries' descriptions to an LLM with an editing prompt,
    # get back three ordered clip-selection lists, then call create_timeline() per list.
    for entry, clip in matched:
        print(f"{entry['filename']}: {entry.get('description')}")


if __name__ == "__main__":
    main()
