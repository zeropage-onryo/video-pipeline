"""
Tests for src/trigger.py -- the scheduled shadow-run trigger.

Hermetic: orchestrator.run is patched, so nothing generates; the crash
path runs against a throwaway schema via DATABASE_URL.
"""
import socket

import pytest

from src import autonomy, trigger

# ---------- spark rotation ----------

def test_load_sparks_skips_comments_and_blanks(tmp_path):
    f = tmp_path / "sparks.txt"
    f.write_text("# a comment\n\ngearing up ritual\n  \nthe last check\n")
    assert trigger.load_sparks(f) == ["gearing up ritual", "the last check"]


def test_load_sparks_missing_file_is_empty_not_fatal(tmp_path):
    assert trigger.load_sparks(tmp_path / "nope.txt") == []


def test_pick_spark_rotates_deterministically():
    sparks = ["a", "b", "c"]
    assert trigger.pick_spark(sparks, 0) == "a"
    assert trigger.pick_spark(sparks, 4) == "b"
    # same day -> same spark, so a crashed night re-runs identically
    assert trigger.pick_spark(sparks, 4) == trigger.pick_spark(sparks, 4)


def test_pick_spark_empty_list_falls_back():
    assert trigger.pick_spark([], 12) == "tonight's shadow slate"


def test_repo_sparks_file_has_material():
    assert len(trigger.load_sparks()) >= 3


# ---------- main ----------

@pytest.fixture
def tmp_db(pg, monkeypatch):
    path = pg
    autonomy.init(path)
    monkeypatch.setenv("DATABASE_URL", path)
    return path


def test_main_fires_the_rotated_spark(tmp_db, monkeypatch):
    from src import orchestrator
    calls = {}

    def fake_run(spark, brand="antihero", channel="zeropage", **kw):
        calls.update(spark=spark, brand=brand, channel=channel)
        return {"attempts": 1, "concept_id": 9, "hold_id": 3,
                "held_reason": "shadow — grading only"}

    monkeypatch.setattr(orchestrator, "run", fake_run)

    assert trigger.main([]) == 0
    assert calls["channel"] == "zeropage"
    assert calls["spark"] in trigger.load_sparks()   # rotation, not a constant


def test_main_omits_brand_by_default_letting_it_follow_channel(tmp_db, monkeypatch):
    """--brand has no hardcoded default anymore -- it's None unless passed
    explicitly, so orchestrator.run() is the one place brand-follows-channel
    is decided. A --brand default here that disagreed with --channel's is
    exactly what produced hold_queue row 13 / concept 111 on 2026-08-14."""
    from src import orchestrator
    calls = {}

    def fake_run(spark, brand=None, channel="zeropage", **kw):
        calls.update(brand=brand, channel=channel)
        return {"attempts": 1, "concept_id": 9, "hold_id": 3,
                "held_reason": "shadow — grading only"}

    monkeypatch.setattr(orchestrator, "run", fake_run)

    trigger.main([])
    assert calls["brand"] is None
    assert calls["channel"] == "zeropage"


def test_main_explicit_spark_wins(tmp_db, monkeypatch):
    from src import orchestrator
    calls = {}
    monkeypatch.setattr(orchestrator, "run",
                        lambda spark, **kw: calls.update(spark=spark) or
                        {"attempts": 1, "hold_id": 1, "held_reason": "x"})

    trigger.main(["--spark", "someone knocked"])
    assert calls["spark"] == "someone knocked"


def test_main_crash_still_writes_the_dead_man_row(tmp_db, monkeypatch):
    from src import orchestrator

    def boom(*a, **k):
        raise RuntimeError("gemini fell over")

    monkeypatch.setattr(orchestrator, "run", boom)

    assert trigger.main([]) == 1
    [row] = autonomy.list_hold(dsn=tmp_db, account_id=None)
    assert "trigger crashed" in row["reason"]
    assert "gemini fell over" in row["reason"]


# ---------- classify_error: is the concept broken, or the world ----------

@pytest.mark.parametrize("error", [
    socket.gaierror(8, "nodename nor servname provided, or not known"),
    RuntimeError("[Errno 8] nodename nor servname provided"),
    OSError("could not translate host name \"aws-0-pooler.supabase.com\""),
    RuntimeError("429 RESOURCE_EXHAUSTED: your prepayment credits are depleted"),
    RuntimeError("401 UNAUTHENTICATED: API key not valid"),
    ConnectionResetError("connection reset by peer"),
])
def test_systemic_errors_are_classified_systemic(error):
    assert trigger.classify_error(error) == trigger.SYSTEMIC


@pytest.mark.parametrize("error", [
    ValueError("could not parse the judge's verdict"),
    RuntimeError("deadlock detected on relation shoot_concepts"),
    KeyError("shots"),
    RuntimeError("429 RESOURCE_EXHAUSTED: rate limit, retry in 4.2s"),
])
def test_content_errors_are_classified_content(error):
    """Unrecognised is CONTENT on purpose: erring that way costs one run,
    erring the other way stops a loop on a healthy world."""
    assert trigger.classify_error(error) == trigger.CONTENT


def test_a_deadlock_is_content_even_though_it_arrives_as_an_operational_error():
    """The ordering that matters. psycopg raises the same base class for
    a dead socket and for one unlucky transaction; reading the content
    markers first is what keeps a deadlock from reading as a dead database."""
    import psycopg
    assert trigger.classify_error(
        psycopg.OperationalError("deadlock detected")) == trigger.CONTENT
    assert trigger.classify_error(
        psycopg.OperationalError("server closed the connection")) == trigger.SYSTEMIC


# ---------- the crash path's kind and exit code ----------

def test_the_trigger_labels_a_systemic_crash_and_exits_2(tmp_db, monkeypatch):
    from src import orchestrator

    def boom(*a, **k):
        raise RuntimeError("[Errno 8] nodename nor servname provided")

    monkeypatch.setattr(orchestrator, "run", boom)
    assert trigger.main([]) == 2

    [row] = autonomy.list_hold(dsn=tmp_db, account_id=None)
    assert "systemic" in row["reason"]


def test_run_once_returns_the_kind_instead_of_an_exit_code(tmp_db, monkeypatch):
    from src import orchestrator

    monkeypatch.setattr(orchestrator, "run",
                        lambda *a, **k: {"spark": "used", "held_reason": "shadow"})
    out = trigger.run_once("asked", channel="zeropage")
    assert out == {"ok": True, "kind": None, "spark": "used", "held": "shadow",
                   "result": {"spark": "used", "held_reason": "shadow"}}
