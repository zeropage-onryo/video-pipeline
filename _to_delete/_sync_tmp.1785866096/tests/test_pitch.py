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
        # the real shape ingest.py writes: beats are {t, text} dicts, not
        # strings. This test asserted strings once and passed while the
        # code crashed on real data.
        "description": {
            "beats": [
                {"t": 9.1, "text": "hand hesitates over the switch"},
                {"t": 45.6, "text": "room goes red"},
            ],
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
    huge = [{"filename": f"A{i}.mov",
             "description": {"beats": [{"t": 0.0, "text": "x" * 500}], "arc": ""}}
            for i in range(100)]
    assert len(pitch.build_reference_query(huge, max_chars=2000)) <= 2000


def test_build_reference_query_survives_odd_beat_shapes():
    # never crash the whole pitch run over a malformed beat
    odd = [{"filename": "A.mov", "description": {
        "beats": ["a bare string beat", {"text": "no timestamp"}, {"t": 1.0}, None],
        "arc": "an arc"}}]
    text = pitch.build_reference_query(odd)
    assert "a bare string beat" in text
    assert "no timestamp" in text
    assert "an arc" in text


def test_build_prompt_embeds_the_references_block(tmp_path, monkeypatch):
    prompt = pitch.build_prompt(SAMPLE_MANIFEST, "1. [notes.md] keep it dry")
    assert "keep it dry" in prompt
    assert "{references}" not in prompt


def test_build_prompt_without_references_says_so_explicitly():
    prompt = pitch.build_prompt(SAMPLE_MANIFEST)
    assert pitch.NO_REFERENCES_NOTE in prompt
    assert "{references}" not in prompt


def test_pitch_run_scopes_grounding_to_the_pitch_domains(tmp_path, monkeypatch):
    """
    Pitching must never ground against marketing or ai_prompting shelves
    -- those belong to shootgen.py and promptgen.py respectively. This
    is the regression test for that boundary staying in place.
    """
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(SAMPLE_MANIFEST))
    pitches_path = tmp_path / "pitches.json"

    monkeypatch.setattr(pitch, "MANIFEST_PATH", manifest_path)
    monkeypatch.setattr(pitch, "PITCHES_PATH", pitches_path)
    monkeypatch.setattr(pitch, "generate_with_retry",
                        lambda *a, **kw: json.dumps(SAMPLE_PITCHES))
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    calls = []

    def fake_retrieve(*args, **kwargs):
        calls.append(kwargs)
        return {"ok": False, "references": [], "error": "not exercised"}

    monkeypatch.setattr(pitch.rag, "retrieve_references", fake_retrieve)

    pitch.main(db_path=tmp_path / "pipeline.db")

    assert len(calls) == 1
    assert calls[0]["domain"] == pitch.PITCH_DOMAINS
    assert "marketing" not in pitch.PITCH_DOMAINS
    assert "ai_prompting" not in pitch.PITCH_DOMAINS


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


REFERENCES = [{"source": "brief.txt", "chunk": "noir, gritty, high contrast", "score": 0.9}]


def make_score_result(faithfulness, reason="unsupported claim about X"):
    return {"scores": {"faithfulness": faithfulness, "answer_relevancy": 0.9,
                       "contextual_precision": None, "contextual_recall": None},
            "reasons": {"faithfulness": reason, "answer_relevancy": "fine"}}


# ---------- revise_pitch_until_grounded ----------

def test_revise_pitch_skips_when_there_are_no_references():
    pitches, check = pitch.revise_pitch_until_grounded(
        client=None, model="m", manifest=SAMPLE_MANIFEST, references_block="",
        references=[], query_used="q", pitches=SAMPLE_PITCHES,
    )
    assert pitches == SAMPLE_PITCHES
    assert check == {"checked": False, "reason": "no references to check faithfulness against"}


def test_revise_pitch_passes_on_the_first_check_without_regenerating(monkeypatch):
    import src.quality as quality
    calls = []
    monkeypatch.setattr(quality, "score_generation", lambda **kw: (calls.append(kw), make_score_result(0.9))[1])
    monkeypatch.setattr(pitch, "generate_with_retry", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("should not regenerate when the first check already passes")))

    pitches, check = pitch.revise_pitch_until_grounded(
        client=None, model="m", manifest=SAMPLE_MANIFEST, references_block="refs",
        references=REFERENCES, query_used="q", pitches=SAMPLE_PITCHES,
    )

    assert pitches == SAMPLE_PITCHES
    assert check == {"checked": True, "faithfulness": 0.9, "needs_review": False,
                     "attempts": 1, "reason": None}
    assert len(calls) == 1


def test_revise_pitch_regenerates_once_then_escalates_when_still_weak(monkeypatch):
    import src.quality as quality
    monkeypatch.setattr(quality, "score_generation", lambda **kw: make_score_result(0.2))
    regenerated = [{"number": n, "title": f"Revised {n}", "logline": "l", "story_note": "n"} for n in range(1, 11)]
    monkeypatch.setattr(pitch, "generate_with_retry", lambda *a, **k: json.dumps(regenerated))

    pitches, check = pitch.revise_pitch_until_grounded(
        client=None, model="m", manifest=SAMPLE_MANIFEST, references_block="refs",
        references=REFERENCES, query_used="q", pitches=SAMPLE_PITCHES, max_attempts=1,
    )

    # max_attempts=1: the loop scores once, is still weak, but has no
    # budget left to regenerate again -- comes back with the first
    # attempt's (unregenerated) pitches and needs_review=True.
    assert pitches == SAMPLE_PITCHES
    assert check["needs_review"] is True
    assert check["attempts"] == 1
    assert check["faithfulness"] == 0.2


def test_revise_pitch_adopts_a_regenerated_batch_that_passes(monkeypatch):
    import src.quality as quality
    scores = iter([0.2, 0.9])
    monkeypatch.setattr(quality, "score_generation", lambda **kw: make_score_result(next(scores)))
    regenerated = [{"number": n, "title": f"Revised {n}", "logline": "l", "story_note": "n"} for n in range(1, 11)]
    monkeypatch.setattr(pitch, "generate_with_retry", lambda *a, **k: json.dumps(regenerated))

    pitches, check = pitch.revise_pitch_until_grounded(
        client=None, model="m", manifest=SAMPLE_MANIFEST, references_block="refs",
        references=REFERENCES, query_used="q", pitches=SAMPLE_PITCHES, max_attempts=2,
    )

    assert pitches == regenerated
    assert check["needs_review"] is False
    assert check["attempts"] == 2
    assert check["faithfulness"] == 0.9


def test_revise_pitch_skips_gracefully_when_scoring_itself_fails(monkeypatch):
    import src.quality as quality

    def broken(**kw):
        raise RuntimeError("no judge model configured")

    monkeypatch.setattr(quality, "score_generation", broken)

    pitches, check = pitch.revise_pitch_until_grounded(
        client=None, model="m", manifest=SAMPLE_MANIFEST, references_block="refs",
        references=REFERENCES, query_used="q", pitches=SAMPLE_PITCHES,
    )

    assert pitches == SAMPLE_PITCHES
    assert check["checked"] is False
    assert "no judge model configured" in check["reason"]


def test_pitch_run_with_self_correct_flag_runs_the_faithfulness_check(tmp_path, monkeypatch, capsys):
    import src.quality as quality

    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(SAMPLE_MANIFEST))
    pitches_path = tmp_path / "pitches.json"

    monkeypatch.setattr(pitch, "MANIFEST_PATH", manifest_path)
    monkeypatch.setattr(pitch, "PITCHES_PATH", pitches_path)
    monkeypatch.setattr(pitch, "generate_with_retry",
                        lambda *a, **kw: json.dumps(SAMPLE_PITCHES))
    monkeypatch.setattr(pitch.rag, "retrieve_references",
                        lambda *a, **kw: {"ok": True, "references": REFERENCES})
    monkeypatch.setattr(quality, "score_generation", lambda **kw: make_score_result(0.95))
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    pitch.main(db_path=tmp_path / "pipeline.db", self_correct=True)

    assert "Faithfulness check passed: 0.95" in capsys.readouterr().out


def test_pitch_run_without_self_correct_flag_skips_the_faithfulness_check(tmp_path, monkeypatch):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(SAMPLE_MANIFEST))
    pitches_path = tmp_path / "pitches.json"

    monkeypatch.setattr(pitch, "MANIFEST_PATH", manifest_path)
    monkeypatch.setattr(pitch, "PITCHES_PATH", pitches_path)
    monkeypatch.setattr(pitch, "generate_with_retry",
                        lambda *a, **kw: json.dumps(SAMPLE_PITCHES))
    monkeypatch.setattr(pitch.rag, "retrieve_references",
                        lambda *a, **kw: {"ok": True, "references": REFERENCES})
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    # self_correct defaults to False -- no import of src.quality should
    # be needed at all for this call to succeed.
    pitch.main(db_path=tmp_path / "pipeline.db")

    assert len(json.loads(pitches_path.read_text())) == 10


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
