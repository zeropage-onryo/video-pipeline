"""
Tests for promote_winners: pulling proven db.py winners into RAG.

candidate_winners()/render_reference_doc() only touch the SQLite side and
run against a real tmp_db, same pattern as test_generative.py/test_pitch.py.
propose()/approve()/reject()/run_auto() also touch rag.py, so those get
their rag.connect/init_store/list_sources/make_client/ingest_records
patched out -- no real Postgres or Gemini call, same contract conftest's
no_network guard enforces everywhere else.
"""
import json

import pytest

from src import db
from src import promote_winners as pw


@pytest.fixture
def tmp_db(pg):
    p = pg
    return p


@pytest.fixture
def queue_path(tmp_path, monkeypatch):
    p = tmp_path / "promotion_queue.json"
    monkeypatch.setattr(pw, "QUEUE_PATH", p)
    return p


class FakeConn:
    """Stands in for a live rag connection; only used as a sentinel /
    passed to patched rag functions, never actually queried."""

    def close(self):
        pass


def seed_winner_and_dud(db_path, posted_at="2026-06-01"):
    """
    Two videos posted the same day, measured at day 7: one well above
    what the other did, so benchmark() has a real median to compare
    against and only one candidate clears MIN_MULTIPLE.
    """
    winner_id = db.add_video("Winner", "youtube", posted_at, dsn=db_path, account_id=None)
    dud_id = db.add_video("Dud", "youtube", posted_at, dsn=db_path, account_id=None)
    # captured 7 days after posted_at, matching the default at_days=7
    db.record_metrics(winner_id, views=10_000, captured_at="2026-06-08T00:00:00",
                      dsn=db_path, account_id=None)
    db.record_metrics(dud_id, views=1_000, captured_at="2026-06-08T00:00:00",
                      dsn=db_path, account_id=None)
    return winner_id, dud_id


# ---------- candidate_winners ----------

def test_candidate_winners_filters_by_min_multiple(tmp_db):
    winner_id, dud_id = seed_winner_and_dud(tmp_db)
    out = pw.candidate_winners(posted_within_days=None, db_path=tmp_db)
    ids = {c["video_id"] for c in out}
    assert winner_id in ids
    assert dud_id not in ids


def test_candidate_winners_empty_with_no_metrics(tmp_db):
    assert pw.candidate_winners(posted_within_days=None, db_path=tmp_db) == []


def test_candidate_winners_excludes_already_promoted(tmp_db, monkeypatch):
    winner_id, _ = seed_winner_and_dud(tmp_db)
    monkeypatch.setattr(
        pw.rag, "list_sources",
        lambda conn: [{"source": pw.source_key(winner_id), "domain": pw.DOMAIN,
                       "project": None, "chunks": 1, "added": "x"}],
    )
    monkeypatch.setattr(pw.rag, "init_store", lambda conn: None)
    out = pw.candidate_winners(posted_within_days=None, db_path=tmp_db, conn=FakeConn())
    assert out == []


def test_candidate_winners_multiple_reflects_median(tmp_db):
    winner_id, _ = seed_winner_and_dud(tmp_db)
    out = pw.candidate_winners(posted_within_days=None, db_path=tmp_db)
    [c] = out
    assert c["video_id"] == winner_id
    # median of {10_000, 1_000} is 5_500 -> winner is ~1.8x
    assert c["multiple"] == pytest.approx(10_000 / 5_500)


# ---------- render_reference_doc ----------

def test_render_reference_doc_includes_performance_context():
    doc = pw.render_reference_doc({
        "title": "Winner", "platform": "youtube",
        "logline": "A hand closes a drawer.", "story_note": "Cold open.",
        "hook_type": "cold_open", "topic": "workshop",
        "score": 10_000, "metric": "views", "median": 5_500,
        "multiple": 1.82, "measured_at_days": 7.0,
    })
    assert "Winner" in doc and "youtube" in doc
    assert "A hand closes a drawer." in doc
    assert "1.8x" in doc
    assert "5,500" in doc and "10,000" in doc


def test_render_reference_doc_survives_missing_optional_fields():
    doc = pw.render_reference_doc({
        "title": "Winner", "platform": "youtube",
        "logline": None, "story_note": None, "hook_type": None, "topic": None,
        "score": 10_000, "metric": "views", "median": 5_500,
        "multiple": 1.82, "measured_at_days": 7.0,
    })
    assert "WINNING CONCEPT" in doc
    assert "Performance:" in doc


# ---------- propose / approve / reject (rag.py patched out) ----------

@pytest.fixture
def no_rag_network(monkeypatch):
    """propose/approve/run_auto all call rag.connect()/make_client() --
    stand those up as no-ops so nothing tries a real Postgres or Gemini
    connection (conftest's no_network guard would fail the test loudly
    if one of these leaked through unpatched)."""
    monkeypatch.setattr(pw.rag, "connect", lambda *a, **k: FakeConn())
    monkeypatch.setattr(pw.rag, "make_client", lambda: object())
    monkeypatch.setattr(pw.rag, "init_store", lambda conn: None)
    monkeypatch.setattr(pw.rag, "list_sources", lambda conn: [])


def test_propose_writes_queue_without_ingesting(tmp_db, queue_path, no_rag_network, monkeypatch):
    winner_id, _ = seed_winner_and_dud(tmp_db)
    calls = []
    monkeypatch.setattr(pw.rag, "ingest_records", lambda *a, **k: calls.append(a))

    queue = pw.propose(posted_within_days=None, db_path=tmp_db)

    assert calls == []  # propose never ingests
    assert [c["video_id"] for c in queue] == [winner_id]
    assert json.loads(queue_path.read_text()) == queue


def test_approve_ingests_and_clears_the_queue(queue_path, no_rag_network, monkeypatch):
    queue_path.write_text(json.dumps([
        {"video_id": 1, "idea_id": None, "title": "Winner", "platform": "youtube",
         "metric": "views", "score": 10_000, "median": 5_500, "multiple": 1.82,
         "doc": "WINNING CONCEPT -- Winner (youtube)\n..."},
    ]))
    captured = {}

    def fake_ingest(records, client, conn):
        captured["records"] = records
        return len(records)

    monkeypatch.setattr(pw.rag, "ingest_records", fake_ingest)

    result = pw.approve()

    assert result == {"promoted": 1, "video_ids": [1]}
    assert captured["records"][0]["domain"] == pw.DOMAIN
    assert captured["records"][0]["source"] == pw.source_key(1)
    assert json.loads(queue_path.read_text()) == []


def test_approve_with_ids_leaves_the_rest_queued(queue_path, no_rag_network, monkeypatch):
    queue_path.write_text(json.dumps([
        {"video_id": 1, "idea_id": None, "title": "A", "platform": "youtube",
         "metric": "views", "score": 10_000, "median": 5_500, "multiple": 1.82, "doc": "A"},
        {"video_id": 2, "idea_id": None, "title": "B", "platform": "youtube",
         "metric": "views", "score": 9_000, "median": 5_500, "multiple": 1.6, "doc": "B"},
    ]))
    monkeypatch.setattr(pw.rag, "ingest_records", lambda records, client, conn: len(records))

    result = pw.approve(video_ids=[1])

    assert result == {"promoted": 1, "video_ids": [1]}
    remaining = json.loads(queue_path.read_text())
    assert [c["video_id"] for c in remaining] == [2]


def test_approve_on_empty_queue_is_a_no_op(queue_path, no_rag_network, monkeypatch):
    calls = []
    monkeypatch.setattr(pw.rag, "ingest_records", lambda *a, **k: calls.append(a))
    assert pw.approve() == {"promoted": 0, "video_ids": []}
    assert calls == []


def test_reject_drops_without_ingesting(queue_path, no_rag_network, monkeypatch):
    queue_path.write_text(json.dumps([
        {"video_id": 1, "idea_id": None, "title": "A", "platform": "youtube",
         "metric": "views", "score": 10_000, "median": 5_500, "multiple": 1.82, "doc": "A"},
    ]))
    calls = []
    monkeypatch.setattr(pw.rag, "ingest_records", lambda *a, **k: calls.append(a))

    result = pw.reject([1])

    assert result == {"dropped": 1}
    assert calls == []
    assert json.loads(queue_path.read_text()) == []


# ---------- run_auto ----------

def test_run_auto_only_promotes_above_the_stricter_threshold(tmp_db, no_rag_network, monkeypatch):
    # winner is ~1.8x median -- clears MIN_MULTIPLE (1.2) but not
    # AUTO_THRESHOLD (2.0), so run --auto must promote nothing here.
    seed_winner_and_dud(tmp_db)
    calls = []
    monkeypatch.setattr(pw.rag, "ingest_records", lambda *a, **k: calls.append(a))

    result = pw.run_auto(posted_within_days=None, db_path=tmp_db)

    assert result == {"promoted": 0, "video_ids": []}
    assert calls == []


def test_run_auto_promotes_candidates_that_clear_the_bar(tmp_db, no_rag_network, monkeypatch):
    # three videos so the median (the middle one, 2_000) sits far enough
    # below the winner to clear AUTO_THRESHOLD -- with only two videos
    # the median is their average and a winner can never reach 2x it.
    winner_id = db.add_video("Blowout", "youtube", "2026-06-01", dsn=tmp_db, account_id=None)
    mid_id = db.add_video("Mid", "youtube", "2026-06-01", dsn=tmp_db, account_id=None)
    dud_id = db.add_video("Dud", "youtube", "2026-06-01", dsn=tmp_db, account_id=None)
    db.record_metrics(winner_id, views=100_000, captured_at="2026-06-08T00:00:00", dsn=tmp_db, account_id=None)
    db.record_metrics(mid_id, views=2_000, captured_at="2026-06-08T00:00:00", dsn=tmp_db, account_id=None)
    db.record_metrics(dud_id, views=1_000, captured_at="2026-06-08T00:00:00", dsn=tmp_db, account_id=None)

    captured = {}
    monkeypatch.setattr(
        pw.rag, "ingest_records",
        lambda records, client, conn: captured.setdefault("records", records),
    )

    result = pw.run_auto(posted_within_days=None, db_path=tmp_db)

    assert result == {"promoted": 1, "video_ids": [winner_id]}
    assert captured["records"][0]["source"] == pw.source_key(winner_id)


# ---------- never touches the network directly ----------

def test_promote_winners_module_never_imports_requests():
    # sanity check on the "never raises / hermetic" contract this
    # repo's other never-raises modules (youtube.py) hold to: this
    # module's only network surface is through rag.py, which is what
    # every test above patches.
    import inspect

    source = inspect.getsource(pw)
    assert "import requests" not in source


def test_render_reference_doc_carries_field_patterns_when_given_signals():
    """With derived signals, the doc names the traits that made the
    window's winners win -- retrievable pattern, not just one video."""
    doc = pw.render_reference_doc(
        {
            "title": "Winner", "platform": "youtube",
            "hook_type": "cold-open", "topic": "workshop",
            "score": 10_000, "metric": "views", "median": 5_500,
            "multiple": 1.82, "measured_at_days": 7.0,
        },
        signals={
            "sample": 6, "median": 5_500,
            "winning_topics": {"workshop": 3}, "losing_topics": {"gear": 3},
            "winning_hooks": {"cold-open": 2}, "losing_hooks": {"talking-head": 3},
            "winning_title_words": {"ritual": 3},
        },
    )
    assert "Patterns across this window's winners" in doc
    assert "workshop" in doc and "cold-open" in doc
    assert "talking-head" in doc          # the losing pattern is named too


def test_render_reference_doc_without_signals_is_unchanged():
    doc = pw.render_reference_doc({
        "title": "Winner", "platform": "youtube",
        "score": 10_000, "metric": "views", "median": 5_500,
        "multiple": 1.82, "measured_at_days": 7.0,
    })
    assert "Patterns" not in doc
