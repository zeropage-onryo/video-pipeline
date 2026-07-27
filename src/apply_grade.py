#!/usr/bin/env python3
"""Applies the Zero Page Films Batman grade (grades/zero_page_batman.drx)
to every clip on the given timelines."""
import argparse
import sys
from pathlib import Path

from resolve_edit import get_resolve

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_GRADE_PATH = PROJECT_ROOT / "grades" / "zero_page_batman.drx"
DEFAULT_TIMELINE_NAMES = ["Manual Precision", "Paper Trails", "Barrier Entry"]


def find_timeline(project, name):
    for i in range(1, project.GetTimelineCount() + 1):
        t = project.GetTimelineByIndex(i)
        if t.GetName() == name:
            return t
    return None


def main():
    parser = argparse.ArgumentParser(description="Apply the saved Batman grade to timeline clips.")
    parser.add_argument("timelines", nargs="*", default=DEFAULT_TIMELINE_NAMES, help="Timeline names to grade")
    parser.add_argument("--grade", type=Path, default=DEFAULT_GRADE_PATH, help="Path to the .drx grade file")
    args = parser.parse_args()

    if not args.grade.exists():
        print(f"Grade file not found: {args.grade}", file=sys.stderr)
        sys.exit(1)

    resolve = get_resolve()
    project = resolve.GetProjectManager().GetCurrentProject()

    for name in args.timelines:
        timeline = find_timeline(project, name)
        if not timeline:
            print(f"{name}: timeline not found, skipped")
            continue

        project.SetCurrentTimeline(timeline)
        items = timeline.GetItemListInTrack("video", 1)
        ok = timeline.ApplyGradeFromDRX(str(args.grade), 0, items)
        print(f"{name}: grade applied to {len(items)} clips ({'ok' if ok else 'failed'})")


if __name__ == "__main__":
    main()
