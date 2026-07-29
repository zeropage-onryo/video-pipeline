"""
Tests for pitch.py's database bookkeeping.

The one that matters: generating pitches must never depend on the
database being available. A broken db path prints a warning; it must
never stop pitches.json from being written.
"""

import json

from src import pitch


SAMPLE_MANIFEST = [
    {"filename": "A037_0812_C001.mov", "duration_seconds": 5.0},
]

SAMPLE_PITCHES = [
    {"number": n, "title": f"Story {n}", "logline": f"Line {n}.",
     "story_note": "Opens on A037_0812_C001.mov."}
    for n in range(1, 11)
]


def test_broken_database_does_not_stop_pitches_json(tmp_path, monkeypatch, capsys):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(SAMPLE_MANIFEST))
    pitches_path = tmp_path / "pitches.json"

    monkeypatch.setattr(pitch, "MANIFEST_PATH", manifest_path)
    monkeypatch.setattr(pitch, "PITCHES_PATH", pitches_path)
    monkeypatch.setattr(pitch, "generate_with_retry",
                        lambda *a, **kw: json.dumps(SAMPLE_PITCHES))
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    # A path whose parent is a regular file, not a directory -- db.connect's
    # mkdir(parents=True, exist_ok=True) has nowhere valid to create.
    not_a_dir = tmp_path / "not_a_directory"
    not_a_dir.write_text("x")
    broken_db_path = not_a_dir / "pipeline.db"

    pitch.main(db_path=broken_db_path)

    assert pitches_path.exists()
    assert len(json.loads(pitches_path.read_text())) == 10

    err = capsys.readouterr().err
    assert "warning" in err.lower()
