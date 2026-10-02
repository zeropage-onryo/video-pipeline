"""How many shots a scene is cut into (2026-10-02).

Mike: "It can generate as many shots as are needed by the prompt" -- not a
habitual three. And, the same day: "I don't want just one continuous shot
unless asked for in the prompt or chatting with the agent", and "while
chatting with the agent we can bring it down to 2 shots ... it's a scene by
scene basis". So:

- the writers are told the count is the idea's: two or more windows by
  default, one only when a single take was asked for, and a count the idea
  already sets is kept -- with no worked example anchoring a number;
- nothing caps the count any more (timeline.MAX_PARTS dropped every window
  past the 8th off the card, the price and the render, without a word);
- code ADVISES rather than rejects: a scene whose count is not what was
  asked carries a visible warning, and is still saved;
- the length is a slider: the route hands out bounds, any whole second
  between them is legal.
"""
import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from src import preprod, pricing, shootgen, timeline

client = TestClient(app)


@pytest.fixture(autouse=True)
def signed_in(monkeypatch):
    from app import auth
    stub = {"id": 1, "email": "test@example.com", "display_name": "Test"}
    monkeypatch.setattr(auth, "current_user", lambda request: stub)
    monkeypatch.setattr(
        auth, "current_account",
        lambda request, user=None: {"slug": "zeropage", "display_name": "ZERO PAGE"})


@pytest.fixture
def tmp_db(pg, monkeypatch):
    preprod.init(pg)
    monkeypatch.setenv("DATABASE_URL", pg)
    return pg


def timed(n, seconds=2):
    """A scene prompt with n timed windows of `seconds` each."""
    beats = " ".join(f"({i * seconds}-{(i + 1) * seconds}s) shot {i + 1} happens."
                     for i in range(n))
    return f"Ultra-realistic grounded video in 9:16.\n3. BEATS: {beats}\n4. SOUND: rain."


# --- no cap ------------------------------------------------------------------

def test_every_window_is_kept_however_many_there_are():
    assert not hasattr(timeline, "MAX_PARTS")
    windows = timeline.parse_windows(timed(12))
    assert len(windows) == 12
    assert windows[-1]["start"] == 22 and windows[-1]["text"] == "shot 12 happens"


def test_a_long_scene_is_planned_and_priced_shot_for_shot(monkeypatch):
    """The cap used to trim the card, the price and the render alike, so
    the 9th shot of a scene was never shown, charged or made."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    plan = timeline.plan(timed(10, seconds=3), ["/refs/a.jpg"])
    assert [p["n"] for p in plan["parts"]] == list(range(1, 11))
    assert plan["seconds"] == 30
    monkeypatch.setenv("FAL_KEY", "test-key")
    shot = {"n": 1, "prompt": timed(10, seconds=3), "refs": ["/refs/a.jpg"]}
    shown = pricing.display(account_id=None, shot=shot, shot_id=1,
                            provider="fal", model="ltx2.3")
    assert len(shown["durations"]) == 10


# --- who decided the count ----------------------------------------------------

@pytest.mark.parametrize("asked, want", [
    ("make it 2 shots", 2),
    ("bring it down to 2 shots", 2),
    ("cut it into three shots", 3),
    ("a 4-shot sequence in the rain", 4),
    ("5 shots total", 5),
    ("in 4 shots first; actually make it 2 shots", 2),   # the change of mind wins
    ("(0-4s) he turns. (4-10s) hard cut to the street.", 2),   # the Guide's brief
    ("a man waits for a bus", None),
    # not a request about the edit
    ("he fires two shots at the bottle", None),
    ("two shots of espresso on the counter", None),
])
def test_a_requested_count_is_read_off_what_the_person_asked(asked, want):
    assert timeline.requested_shots(asked) == want


@pytest.mark.parametrize("asked", [
    "one continuous shot down the hallway",
    "a single take, no cuts",
    "shoot it as a oner",
    "one long take",
    "(0-10s) the whole thing in one go",      # a brief with one window
    "make it 1 shot",
])
def test_a_single_take_request_is_recognised(asked):
    assert timeline.one_take_requested(asked)


@pytest.mark.parametrize("asked", [
    "a man waits for a bus", "a long shot of the city at night",
    "make it 2 shots", "a quiet morning"])
def test_everything_else_is_not_a_single_take_request(asked):
    assert not timeline.one_take_requested(asked)


def test_one_continuous_take_nobody_asked_for_is_flagged():
    warned = timeline.shot_count_warnings("(0-10s) he walks the hallway.", "a man walks home")
    assert len(warned) == 1 and "one continuous take" in warned[0]
    # a scene with no clock at all renders as one clip too
    assert timeline.shot_count_warnings("he walks the hallway", "a man walks home")


def test_one_continuous_take_that_was_asked_for_is_fine():
    assert timeline.shot_count_warnings("(0-10s) he walks.", "one continuous shot of him walking") == []


def test_a_count_the_person_set_is_checked_scene_by_scene():
    assert timeline.shot_count_warnings(timed(2), "make it 2 shots") == []
    warned = timeline.shot_count_warnings(timed(4), "bring it down to 2 shots")
    assert warned == ["shot 1: asked for 2 shots, the scene was written as 4"]
    # the Guide's brief carries its own windows: that count is the one asked
    brief = "(0-5s) close on the key. (5-10s) hard cut to the door."
    assert timeline.shot_count_warnings(timed(3), brief)
    assert timeline.shot_count_warnings(timed(2), brief) == []


def test_a_cut_scene_with_no_count_asked_is_fine():
    for n in (2, 5, 9):
        assert timeline.shot_count_warnings(timed(n), "a man waits for a bus") == []


# --- the writers: told, then checked -------------------------------------------

def test_both_writers_let_the_idea_set_the_count():
    brief = shootgen.build_scene_brief_prompt("zeropage", spark="x", seconds=14)
    takes = shootgen.build_scenes_prompt("x", "zeropage", 1, [], seconds=14)
    for text in (brief, takes):
        # no worked three-window example to anchor on
        assert "(0-3s), (3-7s), (7-10s)" not in text
        assert "TWO OR MORE" in text
        assert "explicitly asks for a single take" in text
        assert "keep exactly that many" in text
        # the gold standard is one take; its count is not part of its shape
        assert "not its single continuous" in text
        # the slider's length reaches the writer, any whole second
        assert "14s" in text and "{seconds}" not in text


def test_the_guide_cuts_scenes_and_lets_the_person_change_the_count():
    from pathlib import Path
    prompts = Path(shootgen.PROMPTS_DIR)
    for name in ("creative_guide.txt", "assistant_brain.txt"):
        text = (prompts / name).read_text()
        assert "two or more" in text
        assert "one continuous shot" in text
        assert "re-cut THAT scene" in text
    direct = (prompts / "direct_prompt.txt").read_text()
    assert "different number of shots" in direct
    assert "(0-3s), (3-7s), (7-10s)" not in direct


def _writer_answers(monkeypatch, *prompts):
    def fake(client_, model, contents, **_):
        return json.dumps({"scenes": [{"title": f"T{i}", "prompt": p}
                                      for i, p in enumerate(prompts)]})
    monkeypatch.setattr("src.shootgen.generate_with_retry", fake)


def test_create_saves_an_unasked_single_take_with_a_warning(tmp_db, monkeypatch):
    """Advice, not a gate: the scene is saved and on the board either way."""
    _writer_answers(monkeypatch, "(0-10s) he walks the hallway.")
    result = shootgen.generate_scene_concepts(
        "a man walks home", "zeropage", count=1, db_path=tmp_db)
    saved = preprod.get_concept(result["scenes"][0]["concept_id"], dsn=tmp_db, account_id=None)
    assert any("one continuous take" in w for w in saved["warnings"])


def test_create_keeps_quiet_when_the_count_is_what_was_asked(tmp_db, monkeypatch):
    _writer_answers(monkeypatch, timed(2, seconds=5))
    result = shootgen.generate_scene_concepts(
        "(0-6s) close on the key. (6-10s) hard cut to the door.", "zeropage",
        count=1, db_path=tmp_db)
    assert result["scenes"][0]["warnings"] == []


def test_create_flags_a_count_the_writer_ignored(tmp_db, monkeypatch):
    _writer_answers(monkeypatch, timed(5))
    result = shootgen.generate_scene_concepts(
        "a chase through the market, in 2 shots", "zeropage", count=1, db_path=tmp_db)
    assert result["scenes"][0]["warnings"] == [
        "shot 1: asked for 2 shots, the scene was written as 5"]


def test_the_brief_writer_checks_the_direction_not_the_steer(tmp_db, monkeypatch):
    """The steer is craft notes and winning prompts; a winning prompt's own
    windows are not the person asking for that many shots."""
    monkeypatch.setattr("src.shootgen.generate_with_retry",
                        lambda *a, **k: json.dumps({"title": "T", "brief": timed(4)}))
    result = shootgen.generate_scene_concept(
        spark="a chase through the market", steer="worked before: (0-5s) a. (5-10s) b.",
        brand="zeropage", db_path=tmp_db, cast="", references="")
    assert result["warnings"] == []


# --- the length is a slider -----------------------------------------------------

def test_the_route_hands_the_slider_its_bounds(monkeypatch):
    monkeypatch.delenv(timeline.SCENE_SECONDS_ENV, raising=False)
    body = client.get("/api/scene-lengths").json()
    assert body["min"] == timeline.MIN_SCENE_SECONDS
    assert body["max"] == timeline.MAX_SCENE_SECONDS
    assert body["min"] <= body["default"] <= body["max"]


def test_any_whole_second_between_the_bounds_is_a_legal_length():
    for s in range(timeline.MIN_SCENE_SECONDS, timeline.MAX_SCENE_SECONDS + 1):
        assert timeline.scene_seconds(s) == s
        assert timeline.scene_seconds(str(s)) == s
