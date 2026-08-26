"""
The Dev Studio tunables (src/settings.py): stored value > env var >
shipped default, validated writes, exception-free reads -- and the
three call sites (orchestrator gate, CRAG threshold, eval k) actually
reading them live, so a saved change takes effect on the next run
without a restart or a code change.
"""
import pytest

from src import crag, db, settings


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    path = tmp_path / "settings.db"
    db.init_db(path)
    settings.init(path)
    monkeypatch.setattr(db, "DB_PATH", path)
    return path


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for var in ("PROMPT_GATE_MIN", "GRADE_THRESHOLD", "EVAL_K"):
        monkeypatch.delenv(var, raising=False)


def test_defaults_without_store_or_env(tmp_db):
    assert settings.get("prompt_gate_min", path=tmp_db) == 7
    assert settings.get("grade_threshold", path=tmp_db) == 0.55
    assert settings.get("eval_k", path=tmp_db) == 5


def test_env_overrides_default(tmp_db, monkeypatch):
    monkeypatch.setenv("PROMPT_GATE_MIN", "8")
    assert settings.get("prompt_gate_min", path=tmp_db) == 8


def test_stored_value_beats_the_env(tmp_db, monkeypatch):
    monkeypatch.setenv("PROMPT_GATE_MIN", "8")
    settings.set_value("prompt_gate_min", "9", path=tmp_db)
    assert settings.get("prompt_gate_min", path=tmp_db) == 9


def test_clearing_falls_back_to_env_then_default(tmp_db, monkeypatch):
    monkeypatch.setenv("EVAL_K", "10")
    settings.set_value("eval_k", "3", path=tmp_db)
    settings.set_value("eval_k", "", path=tmp_db)   # empty string clears
    assert settings.get("eval_k", path=tmp_db) == 10
    monkeypatch.delenv("EVAL_K")
    assert settings.get("eval_k", path=tmp_db) == 5


def test_set_value_rejects_garbage_and_out_of_range(tmp_db):
    with pytest.raises(ValueError):
        settings.set_value("prompt_gate_min", "eleven", path=tmp_db)
    with pytest.raises(ValueError):
        settings.set_value("prompt_gate_min", "42", path=tmp_db)
    with pytest.raises(ValueError):
        settings.set_value("grade_threshold", "1.5", path=tmp_db)
    with pytest.raises(ValueError):
        settings.set_value("nonsense_key", "1", path=tmp_db)


def test_reads_never_raise_without_the_table(tmp_path, monkeypatch):
    """The call sites live inside the orchestrator and CRAG grading --
    a missing table must degrade to the shipped default, not kill a
    run."""
    empty = tmp_path / "no-tables.db"
    monkeypatch.setattr(db, "DB_PATH", empty)
    assert settings.get("grade_threshold", path=empty) == 0.55


def test_describe_names_the_source(tmp_db, monkeypatch):
    monkeypatch.setenv("EVAL_K", "10")
    settings.set_value("prompt_gate_min", "9", path=tmp_db)
    rows = {r["key"]: r for r in settings.describe(path=tmp_db)}
    assert rows["prompt_gate_min"]["source"] == "settings"
    assert rows["prompt_gate_min"]["value"] == 9
    assert rows["eval_k"]["source"] == "env (EVAL_K)"
    assert rows["grade_threshold"]["source"] == "default"


# --- the three call sites read live -----------------------------------------

def test_crag_grade_reads_the_stored_threshold(tmp_db):
    refs = [{"score": 0.7}]
    assert crag.grade_retrieval(refs)["strong"] is True       # 0.55 default
    settings.set_value("grade_threshold", "0.9", path=tmp_db)
    assert crag.grade_retrieval(refs)["strong"] is False      # stored 0.9
    assert crag.grade_retrieval(refs, threshold=0.5)["strong"] is True  # explicit wins


def test_orchestrator_gate_reads_the_stored_bar(tmp_db):
    from src import orchestrator
    assert orchestrator.prompt_gate_min() == 7
    settings.set_value("prompt_gate_min", "9", path=tmp_db)
    assert orchestrator.prompt_gate_min() == 9


def test_api_eval_k_reads_the_stored_value(tmp_db):
    from app import api as api_mod
    assert api_mod._eval_k() == 5
    settings.set_value("eval_k", "8", path=tmp_db)
    assert api_mod._eval_k() == 8
