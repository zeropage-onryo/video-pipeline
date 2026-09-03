#!/usr/bin/env python3
"""Cut Michael's own footage into a searchable bank of reference stills.

    venv/bin/python ops/build-frame-bank.py --probe          # 2 clips, no captions
    venv/bin/python ops/build-frame-bank.py --clips 6        # a slice, captioned
    venv/bin/python ops/build-frame-bank.py                  # all 37

Run it more than once safely: a frame already on disk is not re-cut and
`framebank.record` upserts, so adding footage costs only the new clips
and a re-run after a captioning failure re-captions without re-decoding
150GB of ProRes.

WHY IT IS A SCRIPT AND NOT A NODE. Extraction is minutes of ffmpeg over
the whole reel and captioning is a bill; neither belongs on the 6am path,
where a slow step is a night with no concepts. The bank is a standing
asset -- built when the footage changes, read on every run after.

WHAT IT PRODUCES. ~140 frames at one every 30s, JPEG at 960px, with a
modest contrast lift because the clips are tagged bt709 and still come
out milky (a log profile baked in and mislabelled). Captions come from
Gemini and are what `images_for` actually searches, so a frame that
fails to caption is findable only by its clip name until the next run.

ANTIHERO ONLY, and that is a finding rather than a default: every clip
in footage/ is motorcycle build and garage work. Zero Page is served by
the stock lanes in src/imagesearch.py, because a garage frame on a
faceless liminal brand is worse than no reference at all.
"""
import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def main(argv=None) -> int:
    load_dotenv(PROJECT_ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--brand", default="antihero")
    parser.add_argument("--every", type=float, default=None,
                        help="seconds between frames (default 30)")
    parser.add_argument("--clips", type=int, default=0,
                        help="only the first N clips")
    parser.add_argument("--probe", action="store_true",
                        help="2 clips, no captioning, no API calls")
    parser.add_argument("--no-captions", action="store_true")
    args = parser.parse_args(argv)

    from src import framebank

    client = None
    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    if not (args.probe or args.no_captions):
        key = os.environ.get("GEMINI_API_KEY")
        if not key:
            print("note: GEMINI_API_KEY not set — cutting frames without "
                  "captions; re-run once it is set to make them searchable",
                  file=sys.stderr)
        else:
            from google import genai
            client = genai.Client(api_key=key)

    found = framebank.clips()
    if not found:
        print(f"no clips in {framebank.FOOTAGE_DIR}", file=sys.stderr)
        return 1
    print(f"{len(found)} clip(s) in footage/ — cutting"
          f"{' (probe)' if args.probe else ''}…")

    out = framebank.build(brand=args.brand, client=client, model=model,
                          every=args.every or framebank.EVERY_SECONDS,
                          limit_clips=2 if args.probe else args.clips)

    print(f"bank: {out['frames']} frame(s) from {out['clips']} clip(s), "
          f"{out['captioned']} captioned")
    if out["frames"] and not out["captioned"]:
        print("note: nothing is searchable until frames have captions — "
              "images_for matches on caption and tags", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
