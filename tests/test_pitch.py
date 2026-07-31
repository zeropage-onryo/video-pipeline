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


DESCRIBED_MANIFEST = [
    {
        "filename": "A037_0812_C001.mov",
        "duration_seconds": 5.0,
        "description": {
            "beats": ["hand hesitates over the switch", "room goes red"],
            "arc": "stillness broken once",
        },
    },
    {
        "filename": "DJI_0042_0007_D.mov",
        "duration_seconds": 8.0,
        "description": "an old flat-string description from a prior ingest",
    },
]


def test_build_reference_query_mines_clip_descriptions():
    text = pitch.build_reference_query(DESCRIBED_MANIFEST)
    assert "hand hesitates over the switch" in text
    assert "stillness broken once" in text
    assert "an old flat-string description" in text     # old shape still counts


def test_build_reference_query_is_capped():
    huge = [{"filename": f"A{i}.mov", "description": {"beats": ["x" * 500], "arc": ""}}
            for i in range(100)]
    assert len(pitch.build_reference_query(huge, max_chars=2000)) <= 2000


def test_build_prompt_embeds_the_references_block(tmp_path, monkeypatch):
    prompt = pitch.build_prompt(SAMPLE_MANIFEST, "1. [notes.md] keep it dry")
    assert "keep it dry" in prompt
    assert "{references}" not in prompt


def test_build_prompt_without_references_says_so_explicitly():
    prompt = pitch.build_prompt(SAMPLE_MANIFEST)
    assert pitch.NO_REFERENCES_NOTE in prompt
    assert "{references}" not in prompt


def test_pitch_run_survives_rag_being_down(tmp_path, monkeypatch, capsys):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(SAMPLE_MANIFEST))
    pitches_path = tmp_path / "pitches.json"

    monkeypatch.setattr(pitch, "MANIFEST_PATH", manifest_path)
    monkeypatch.setattr(pitch, "PITCHES_PATH", pitches_path)
    monkeypatch.setattr(pitch, "generate_with_retry",
                        lambda *a, **kw: json.dumps(SAMPLE_PITCHES))
    monkeypatch.setattr(pitch.rag, "retrieve_references",
                        lambda *a, **kw: {"ok": False, "references": [],
                                          "error": "connection refused"})
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    pitch.main(db_path=tmp_path / "pipeline.db")

    assert len(json.loads(pitches_path.read_text())) == 10
    assert "without references" in capsys.readouterr().err


def test_broken_database_does_not_stop_pitches_json(tmp_path, monkeypatch, capsys):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(SAMPLE_MANIFEST))
    pitches_path = tmp_path / "pitches.json"

    monkeypatch.setattr(pitch, "MANIFEST_PATH", manifest_path)
    monkeypatch.setattr(pitch, "PITCHES_PATH", pitches_path)
    monkeypatch.setattr(pitch, "generate_with_retry",
                        lambda *a, **kw: json.dumps(SAMPLE_PITCHES))
    # libpq connects below the Python socket module, so conftest's
    # network guard can't catch a real localhost attempt -- patch it out
    monkeypatch.setattr(pitch.rag, "retrieve_references",
                        lambda *a, **kw: {"ok": False, "references": [],
                                          "error": "patched out"})
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


def test_records_the_run_on_a_brand_new_database(tmp_path):
    """
    A fresh clone has no data/pipeline.db. If pitch.py doesn't create
    the schema, the label capture -- the entire point of the module --
    fails to one stderr line buried under ten printed pitches.
    """
    from src import db

    fresh = tmp_path / "brand-new.db"
    pitch.record_pitch_run(
        [{"number": 1, "title": "Story 1", "logline": "l", "story_note": "n"}],
        SAMPLE_MANIFEST,
        db_path=fresh,
    )
    assert db.summary(fresh)["pitch_runs"] == 1
