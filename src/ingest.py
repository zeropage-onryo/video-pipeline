#!/usr/bin/env python3
import argparse
import base64
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import whisper
from anthropic import Anthropic
from dotenv import load_dotenv

VIDEO_EXTENSIONS = {".mp4", ".mov", ".braw"}
VISION_MODEL = "claude-haiku-4-5-20251001"
VISION_PROMPT = (
    "These are frames sampled from the start, middle, and end of a video clip. "
    "Describe the shot in 1-2 sentences: subject, action, setting, and camera "
    "movement if apparent. Be concise and factual."
)


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


def extract_frames(path: Path, duration: float) -> list[bytes]:
    fractions = [0.1, 0.5, 0.9]
    timestamps = [duration * f for f in fractions] if duration else [0.0]

    frames = []
    with tempfile.TemporaryDirectory() as tmpdir:
        for i, ts in enumerate(timestamps):
            out_path = Path(tmpdir) / f"frame_{i}.jpg"
            subprocess.run(
                [
                    "ffmpeg", "-y", "-ss", str(ts), "-i", str(path),
                    "-frames:v", "1", "-q:v", "2", str(out_path),
                ],
                capture_output=True, check=True,
            )
            frames.append(out_path.read_bytes())
    return frames


def describe_shot(client: Anthropic, frames: list[bytes]) -> str:
    content = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": base64.standard_b64encode(frame).decode("utf-8"),
            },
        }
        for frame in frames
    ]
    content.append({"type": "text", "text": VISION_PROMPT})

    message = client.messages.create(
        model=VISION_MODEL,
        max_tokens=200,
        messages=[{"role": "user", "content": content}],
    )
    return message.content[0].text.strip()


def main():
    load_dotenv()

    parser = argparse.ArgumentParser(description="Ingest footage: extract metadata, transcribe speech, and describe shots.")
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

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    client = Anthropic(api_key=api_key) if api_key else None
    if videos and not client:
        print("ANTHROPIC_API_KEY not set; skipping visual shot descriptions", file=sys.stderr)

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

        description = None
        if client:
            try:
                frames = extract_frames(video, metadata.get("duration_seconds") or 0)
                description = describe_shot(client, frames)
            except Exception as e:
                print(f"  visual description failed for {video.name}: {e}", file=sys.stderr)

        manifest.append({
            "filename": video.name,
            **metadata,
            "transcript": transcript,
            "description": description,
        })

    args.output.write_text(json.dumps(manifest, indent=2))
    print(f"Wrote {len(manifest)} entries to {args.output}")


if __name__ == "__main__":
    main()
