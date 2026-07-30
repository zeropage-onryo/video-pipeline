"""
Tests for genlog.py -- the small CLI that logs generation attempts
after you've actually generated in the tool's own UI. No generation
APIs get called here; this only ever records a decision already made.
"""

import pytest

from src import db, genlog
from src import generative as gen
from src.shot import Shot


@pytest.fixture
def tmp_db(tmp_path):
    path = tmp_path / "test.db"
    db.init_db(path)
    gen.init(path)
    return path


@pytest.fixture
def shot_id(tmp_db):
    shot = Shot(subject="a gloved hand", action="closes a steel drawer")
    return gen.add_shot(shot, path=tmp_db)


def test_record_logs_a_generation_and_prints_id(shot_id, tmp_db, capsys):
    genlog.main(["record", str(shot_id), "runway", "a gloved hand closes a drawer"],
                db_path=tmp_db)

    out = capsys.readouterr().out
    assert "Recorded generation" in out

    with db.connect(tmp_db) as conn:
        row = conn.execute("SELECT tool, prompt FROM generations").fetchone()
    assert row["tool"] == "runway"
    assert row["prompt"] == "a gloved hand closes a drawer"


def test_record_rejects_unknown_tool(shot_id, tmp_db):
    with pytest.raises(SystemExit):
        genlog.main(["record", str(shot_id), "sora", "some prompt"], db_path=tmp_db)


def test_keep_marks_generation_and_resolves_shot(shot_id, tmp_db, capsys):
    gen_id = gen.record_generation(shot_id, "veo", "a prompt", path=tmp_db)

    genlog.main(["keep", str(gen_id)], db_path=tmp_db)

    assert "kept" in capsys.readouterr().out.lower()
    assert gen.get_shot(shot_id, tmp_db)["resolved"] == 1


def test_reject_stores_the_reason(shot_id, tmp_db, capsys):
    gen_id = gen.record_generation(shot_id, "kling", "a prompt", path=tmp_db)

    genlog.main(["reject", str(gen_id), "morphing"], db_path=tmp_db)

    assert "rejected" in capsys.readouterr().out.lower()
    with db.connect(tmp_db) as conn:
        reason = conn.execute(
            "SELECT reject_reason FROM generations WHERE id = ?", (gen_id,)
        ).fetchone()[0]
    assert reason == "morphing"


def test_reject_rejects_reason_outside_controlled_vocabulary(shot_id, tmp_db):
    gen_id = gen.record_generation(shot_id, "kling", "a prompt", path=tmp_db)
    with pytest.raises(SystemExit):
        genlog.main(["reject", str(gen_id), "vibes felt off"], db_path=tmp_db)


def test_reject_other_is_a_valid_reason(shot_id, tmp_db):
    gen_id = gen.record_generation(shot_id, "kling", "a prompt", path=tmp_db)
    genlog.main(["reject", str(gen_id), "other"], db_path=tmp_db)  # must not raise
