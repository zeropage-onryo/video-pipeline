"""
Tests for rework.py -- the L3 stage: given what actually performed,
propose the next slate with the reasoning tied to the evidence.

Same hermetic discipline as shootgen: the generator takes its evidence
and references as plain arguments retrieved at the edge, the model call
is monkeypatched, and the human pick stays the recorded label because
proposals land as ordinary concept ideas in preprod.
"""
import json

import pytest

from src import db, preprod, rework


@pytest.fixture
def tmp_db(tmp_path):
    path = tmp_path / "test.db"
    db.init_db(path)
    preprod.init(path)
    preprod.add_location("garage", {"space": "cold garage"}, path=path)
    return path


SIGNALS = {
    "sample": 6, "median": 500.0,
    "winning_topics": {"workshop": 3}, "losing_topics": {"gear": 3},
    "winning_hooks": {"cold-open": 2}, "losing_hooks": {"talking-head": 3},
    "winning_title_words": {"ritual": 3},
}

SLATE_RESPONSE = json.dumps({"ideas": [
    {"title": "Ritual Two", "hook": "h", "logline": "l",
     "evidence": "workshop topic beat the median 3x"},
    {"title": "Ritual Three", "hook": "h", "logline": "l",
     "evidence": "cold-open hooks won the window"},
]})


def test_format_signals_names_the_evidence():
    block = rework.format_signals(SIGNALS)
    assert "workshop" in block and "gear" in block
    assert "ritual" in block
    assert "6 scored videos" in block


def test_format_signals_with_no_sample_says_so():
    assert "no performance data" in rework.format_signals({"sample": 0}).lower()


def test_build_rework_prompt_fills_every_placeholder(tmp_db):
    locations = preprod.list_locations(path=tmp_db)
    prompt = rework.build_rework_prompt(
        locations, brand="antihero", signals=SIGNALS, count=4,
        references="REF BLOCK",
    )
    assert "workshop" in prompt and "REF BLOCK" in prompt and "garage" in prompt
    for placeholder in ("{locations}", "{brand}", "{signals}", "{count}", "{references}"):
        assert placeholder not in prompt


def test_propose_slate_saves_ideas_with_their_evidence(tmp_db, monkeypatch):
    monkeypatch.setattr(rework, "generate_with_retry", lambda *a, **kw: SLATE_RESPONSE)
    result = rework.propose_slate(
        brand="antihero", signals=SIGNALS, gemini_client=None,
        db_path=tmp_db, references="",
    )
    assert len(result["ideas"]) == 2
    assert result["ideas"][0]["evidence"].startswith("workshop")
    # proposals are ordinary concept ideas -- the human pick (planning
    # one) stays the recorded label, measured by shortlist_rate
    saved = preprod.list_concepts(path=tmp_db)
    assert {c["title"] for c in saved} == {"Ritual Two", "Ritual Three"}


def test_propose_slate_degrades_without_performance_data(tmp_db, monkeypatch, capsys):
    monkeypatch.setattr(rework, "generate_with_retry", lambda *a, **kw: SLATE_RESPONSE)
    result = rework.propose_slate(
        brand="antihero", signals={"sample": 0}, gemini_client=None,
        db_path=tmp_db, references="",
    )
    assert len(result["ideas"]) == 2
    assert "no performance data" in capsys.readouterr().err.lower()
