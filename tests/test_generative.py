"""Tests for the Shot renderers and generation tracking."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import db, generative as gen  # noqa: E402
from src.shot import Shot, render, render_all, RENDERERS  # noqa: E402


def make_shot(**kw):
    base = dict(subject="a gloved hand", action="closes a steel drawer",
                camera="push_in", size="close",
                setting="empty workshop at night",
                lighting="single overhead practical")
    base.update(kw)
    return Shot(**base)


@pytest.fixture
def tmp_db(tmp_path):
    p = tmp_path / "t.db"
    db.init_db(p)
    gen.init(p)
    return p


# ---------- Shot validation ----------

def test_free_text_camera_rejected():
    with pytest.raises(ValueError, match="camera must be one of"):
        make_shot(camera="swooshes around dramatically")


def test_empty_subject_rejected():
    with pytest.raises(ValueError, match="subject is required"):
        make_shot(subject="  ")


def test_empty_action_rejected():
    with pytest.raises(ValueError, match="action is required"):
        make_shot(action="")


def test_bad_size_rejected():
    with pytest.raises(ValueError, match="size must be one of"):
        make_shot(size="closeish")


def test_absurd_duration_rejected():
    with pytest.raises(ValueError, match="duration_s"):
        make_shot(duration_s=90)


# ---------- renderers ----------

def test_every_tool_renders_non_empty():
    shot = make_shot()
    out = render_all(shot)
    assert set(out) == set(RENDERERS)
    assert all(v.strip() for v in out.values())


def test_renderers_disagree():
    """If two tools produce identical text the layer is pointless."""
    out = render_all(make_shot())
    assert len(set(out.values())) == len(out)


def test_house_look_in_every_prompt():
    out = render_all(make_shot())
    for tool, prompt in out.items():
        assert "crushed shadows" in prompt, f"{tool} dropped the house look"


def test_camera_vocabulary_is_translated_not_leaked():
    """The enum value itself must never appear in output."""
    for cam in ("push_in", "pull_out", "crane_up", "pan_left"):
        for prompt in render_all(make_shot(camera=cam)).values():
            assert cam not in prompt


def test_veo_carries_negative_inline():
    assert "Avoid:" in render(make_shot(), "veo")


def test_optional_fields_leave_no_dangling_punctuation():
    bare = Shot(subject="rain", action="falls on asphalt")
    for prompt in render_all(bare).values():
        assert ", ," not in prompt
        assert not prompt.strip().endswith(",")


def test_unknown_tool_rejected():
    with pytest.raises(ValueError, match="tool must be one of"):
        render(make_shot(), "sora")


def test_renderers_are_pure():
    shot = make_shot()
    before = shot.as_dict()
    render_all(shot)
    assert shot.as_dict() == before


# ---------- tracking ----------

def test_attempts_increment_per_tool(tmp_db):
    sid = gen.add_shot(make_shot(), path=tmp_db)
    a = gen.record_generation(sid, "runway", "p1", path=tmp_db)
    b = gen.record_generation(sid, "runway", "p2", path=tmp_db)
    c = gen.record_generation(sid, "kling", "p3", path=tmp_db)
    with db.connect(tmp_db) as conn:
        rows = {r["id"]: r["attempt"] for r in
                conn.execute("SELECT id, attempt FROM generations")}
    assert rows[a] == 1 and rows[b] == 2
    assert rows[c] == 1


def test_empty_prompt_rejected(tmp_db):
    sid = gen.add_shot(make_shot(), path=tmp_db)
    with pytest.raises(ValueError, match="prompt cannot be empty"):
        gen.record_generation(sid, "runway", "   ", path=tmp_db)


def test_unknown_tool_rejected_on_write(tmp_db):
    sid = gen.add_shot(make_shot(), path=tmp_db)
    with pytest.raises(ValueError, match="tool must be one of"):
        gen.record_generation(sid, "sora", "x", path=tmp_db)


def test_generation_for_missing_shot_rejected(tmp_db):
    with pytest.raises(ValueError, match="no shot"):
        gen.record_generation(999, "runway", "x", path=tmp_db)


def test_keeping_resolves_the_shot(tmp_db):
    sid = gen.add_shot(make_shot(), path=tmp_db)
    assert len(gen.open_shots(tmp_db)) == 1
    g = gen.record_generation(sid, "veo", "p", path=tmp_db)
    gen.mark_kept(g, output_path="gen/hand_01.mp4", path=tmp_db)
    assert gen.open_shots(tmp_db) == []
    assert gen.get_shot(sid, tmp_db)["resolved"] == 1


def test_spec_round_trips(tmp_db):
    sid = gen.add_shot(make_shot(camera="orbit"), path=tmp_db)
    spec = gen.get_shot(sid, tmp_db)["spec"]
    assert spec["camera"] == "orbit"
    assert spec["subject"] == "a gloved hand"


def test_attempts_to_keeper_counts_the_winner(tmp_db):
    sid = gen.add_shot(make_shot(), path=tmp_db)
    for i in range(4):
        g = gen.record_generation(sid, "runway", f"p{i}", cost_usd=0.5, path=tmp_db)
    gen.mark_kept(g, path=tmp_db)

    rows = gen.attempts_to_keeper(path=tmp_db)
    assert len(rows) == 1
    assert rows[0]["attempts"] == 4
    assert rows[0]["total_cost"] == 2.0


def test_tool_scoreboard_ranks_by_hit_rate(tmp_db):
    s1 = gen.add_shot(make_shot(), path=tmp_db)
    for i in range(5):
        g = gen.record_generation(s1, "runway", f"a{i}", cost_usd=1.0, path=tmp_db)
    gen.mark_kept(g, path=tmp_db)

    s2 = gen.add_shot(make_shot(subject="a door"), path=tmp_db)
    g2 = gen.record_generation(s2, "kling", "b0", cost_usd=1.0, path=tmp_db)
    gen.mark_kept(g2, path=tmp_db)

    board = {b["tool"]: b for b in gen.tool_scoreboard(tmp_db)}
    assert board["runway"]["hit_rate"] == 0.2
    assert board["kling"]["hit_rate"] == 1.0
    assert board["runway"]["cost_per_keeper"] == 5.0


def test_abandoned_shots_excluded_from_scoreboard(tmp_db):
    """A shot you gave up on shouldn't punish whichever tool you tried."""
    good = gen.add_shot(make_shot(), path=tmp_db)
    g = gen.record_generation(good, "veo", "x", path=tmp_db)
    gen.mark_kept(g, path=tmp_db)

    dud = gen.add_shot(make_shot(subject="impossible thing"), path=tmp_db)
    for i in range(8):
        gen.record_generation(dud, "veo", f"y{i}", path=tmp_db)

    board = {b["tool"]: b for b in gen.tool_scoreboard(tmp_db)}
    assert board["veo"]["attempts"] == 1


def test_failure_reasons_grouped(tmp_db):
    sid = gen.add_shot(make_shot(), path=tmp_db)
    for reason in ("morphing hands", "morphing hands", "wrong lighting"):
        g = gen.record_generation(sid, "runway", "p", path=tmp_db)
        gen.mark_rejected(g, reason, path=tmp_db)
    top = gen.failure_reasons(path=tmp_db)
    assert top[0] == {"reason": "morphing hands", "n": 2}


def test_winning_prompts_fewest_attempts_first(tmp_db):
    slow = gen.add_shot(make_shot(), path=tmp_db)
    for i in range(6):
        g = gen.record_generation(slow, "runway", f"slow{i}", path=tmp_db)
    gen.mark_kept(g, path=tmp_db)

    fast = gen.add_shot(make_shot(subject="a door"), path=tmp_db)
    g2 = gen.record_generation(fast, "kling", "fast", path=tmp_db)
    gen.mark_kept(g2, path=tmp_db)

    winners = gen.winning_prompts(path=tmp_db)
    assert winners[0]["prompt"] == "fast"
    assert winners[0]["attempts"] == 1


def test_shot_links_to_a_pitch(tmp_db):
    run = db.save_pitch_run(
        [{"number": 1, "title": "Manual Precision", "logline": "x",
          "story_note": "y"}], path=tmp_db)
    with db.connect(tmp_db) as conn:
        idea_id = conn.execute("SELECT id FROM ideas WHERE run_id = ?",
                               (run,)).fetchone()[0]
    sid = gen.add_shot(make_shot(), idea_id=idea_id, slot_index=2, path=tmp_db)
    assert gen.get_shot(sid, tmp_db)["idea_id"] == idea_id


def test_shot_for_missing_idea_rejected(tmp_db):
    with pytest.raises(ValueError, match="no idea"):
        gen.add_shot(make_shot(), idea_id=999, path=tmp_db)
