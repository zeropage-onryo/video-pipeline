#!/usr/bin/env python3
import argparse
import json
import subprocess
import sys
from pathlib import Path

import whisper

VIDEO_EXTENSIONS = {".mp4", ".mov", ".braw"}


def probe_video(path: Path) -> dict:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-show_entries", "format=duration",
            "-of", "json",
            str(path),
        ],
        capture_output=True, text=True, check=True,
    )
    data = json.loads(result.stdout)
    streams = data.get("streams", [])
    stream = streams[0] if streams else {}
    duration = data.get("format", {}).get("duration")
    return {
        "duration_seconds": round(float(duration), 2) if duration else None,
        "resolution": f'{stream["width"]}x{stream["height"]}' if stream else None,
    }


def transcribe(model, path: Path) -> str:
    result = model.transcribe(str(path))
    return result["text"].strip()


def main():
    parser = argparse.ArgumentParser(description="Ingest footage: extract metadata and transcribe speech.")
    parser.add_argument("--footage-dir", default="footage", type=Path)
    parser.add_argument("--output", default="manifest.json", type=Path)
    parser.add_argument("--model", default="base", help="Whisper model size")
    args = parser.parse_args()

    if not args.footage_dir.is_dir():
        print(f"Footage directory not found: {args.footage_dir}", file=sys.stderr)
        sys.exit(1)

    videos = sorted(
        p for p in args.footage_dir.iterdir()
        if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS
    )

    if not videos:
        print(f"No video files found in {args.footage_dir}", file=sys.stderr)

    model = whisper.load_model(args.model) if videos else None

    manifest = []
    for video in videos:
        print(f"Processing {video.name}...")

        try:
            metadata = probe_video(video)
        except subprocess.CalledProcessError as e:
            print(f"  ffprobe failed for {video.name}: {e.stderr.strip()}", file=sys.stderr)
            metadata = {"duration_seconds": None, "resolution": None}

        try:
            transcript = transcribe(model, video)
        except Exception as e:
            print(f"  transcription failed for {video.name}: {e}", file=sys.stderr)
            transcript = None

        manifest.append({
            "filename": video.name,
            **metadata,
            "transcript": transcript,
        })

    args.output.write_text(json.dumps(manifest, indent=2))
    print(f"Wrote {len(manifest)} entries to {args.output}")


if __name__ == "__main__":
    main()
