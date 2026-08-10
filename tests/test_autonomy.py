"""
Tests for src/autonomy.py -- channels, the hold queue / dead-man log,
the kill switch, and the evaluator-agreement number the credit gate
reads. Pure SQLite against a throwaway DB.
"""
import pytest

from src import autonomy, db


@pytest.fixture
def tmp_db(tmp_path):
    path = tmp_path / "test.db"
    db.init_db(path)
    autonomy.init(path)
    return path


# ---------- channels ----------

def test_init_seeds_both_channels_as_shadow(tmp_db):
    channels = {c["name"]: c for c in autonomy.list_channels(path=tmp_db)}
    assert set(channels) == {"zeropage", "personal"}
    assert all(c["autonomy"] == "shadow" for c in channels.values())
    assert all(c["rate_cap"] == 1 for c in channels.values())


def test_init_is_idempotent_and_keeps_promotions(tmp_db):
    autonomy.set_autonomy("zeropage", "auto", path=tmp_db)
    autonomy.init(tmp_db)   # re-running init must not reset the promotion
    assert autonomy.get_channel("zeropage", path=tmp_db)["autonomy"] == "auto"


def test_promotion_is_a_one_row_change(tmp_db):
    autonomy.set_autonomy("personal", "queue", path=tmp_db)
    assert autonomy.get_channel("personal", path=tmp_db)["autonomy"] == "queue"
    assert autonomy.get_channel("zeropage", path=tmp_db)["autonomy"] == "shadow"


def test_set_autonomy_rejects_unknown_levels(tmp_db):
    with pytest.raises(ValueError):
        autonomy.set_autonomy("zeropage", "yolo", path=tmp_db)


# ---------- kill switch ----------

def test_kill_switch_round_trip(tmp_db, monkeypatch):
    monkeypatch.delenv("ZEROPAGE_KILL", raising=False)
    assert autonomy.killed(path=tmp_db) is False
    autonomy.kill("bad night", path=tmp_db)
    assert autonomy.killed(path=tmp_db) is True
    autonomy.unkill(path=tmp_db)
    assert autonomy.killed(path=tmp_db) is False


def test_kill_switch_env_var_needs_no_db_write(tmp_db, monkeypatch):
    monkeypatch.setenv("ZEROPAGE_KILL", "1")
    assert autonomy.killed(path=tmp_db) is True


# ---------- hold queue ----------

def test_hold_round_trip_with_payload(tmp_db):
    hold_id = autonomy.to_hold(
        "zeropage", "shadow — grading only", concept_id=7,
        caption="a caption", payload={"prompts": [{"tool": "KLING"}]},
        path=tmp_db,
    )
    [row] = autonomy.list_hold(path=tmp_db)
    assert row["id"] == hold_id
    assert row["channel"] == "zeropage"
    assert row["concept_id"] == 7
    assert row["payload"]["prompts"][0]["tool"] == "KLING"


def test_resolve_hold_grades_a_run(tmp_db):
    hold_id = autonomy.to_hold("zeropage", "shadow", path=tmp_db)
    autonomy.resolve_hold(hold_id, "approved", path=tmp_db)
    assert autonomy.list_hold(status="held", path=tmp_db) == []
    [row] = autonomy.list_hold(status="approved", path=tmp_db)
    assert row["id"] == hold_id


def test_resolve_hold_rejects_unknown_status(tmp_db):
    hold_id = autonomy.to_hold("zeropage", "shadow", path=tmp_db)
    with pytest.raises(ValueError):
        autonomy.resolve_hold(hold_id, "maybe", path=tmp_db)


def test_posts_today_counts_only_posted(tmp_db):
    autonomy.to_hold("zeropage", "held one", path=tmp_db)
    autonomy.to_hold("zeropage", "posted one", status="posted", path=tmp_db)
    autonomy.to_hold("personal", "other channel", status="posted", path=tmp_db)
    assert autonomy.posts_today("zeropage", path=tmp_db) == 1


# ---------- the credit-gate number ----------

def test_evaluator_agreement_math(tmp_db):
    for status in ("approved", "approved", "approved", "rejected"):
        hold_id = autonomy.to_hold("zeropage", "shadow", path=tmp_db)
        autonomy.resolve_hold(hold_id, status, path=tmp_db)
    result = autonomy.evaluator_agreement("zeropage", path=tmp_db)
    assert result["graded"] == 4
    assert result["approved"] == 3
    assert result["agreement"] == 0.75


def test_evaluator_agreement_empty_is_none_not_zero(tmp_db):
    assert autonomy.evaluator_agreement(path=tmp_db)["agreement"] is None


# ---------- the prompt gate's numbers ----------

def test_prompt_scores_round_trip_and_verdict(tmp_db):
    autonomy.log_prompt_scores("run1", [
        {"prompt": "good one", "score": 9, "pass": True, "reason": "", "dims": {"camera": 2}},
        {"prompt": "weak one", "score": 3, "pass": False, "reason": "no light", "dims": {}},
    ], path=tmp_db)

    assert autonomy.first_try_pass_rate(path=tmp_db) == {
        "total": 2, "passed": 1, "rate": 0.5}
    assert autonomy.set_prompt_verdicts("run1", "reject", path=tmp_db) == 2


def test_prompt_gate_agreement_separates_the_two_error_costs(tmp_db):
    # gate passed, you rejected -> the expensive error (credit burned)
    autonomy.log_prompt_scores("r1", [
        {"prompt": "a", "score": 9, "pass": True, "reason": "", "dims": {}}], path=tmp_db)
    autonomy.set_prompt_verdicts("r1", "reject", path=tmp_db)
    # gate held, you'd post -> the cheap error (manual approval)
    autonomy.log_prompt_scores("r2", [
        {"prompt": "b", "score": 3, "pass": False, "reason": "x", "dims": {}}], path=tmp_db)
    autonomy.set_prompt_verdicts("r2", "post", path=tmp_db)
    # two agreements
    autonomy.log_prompt_scores("r3", [
        {"prompt": "c", "score": 9, "pass": True, "reason": "", "dims": {}}], path=tmp_db)
    autonomy.set_prompt_verdicts("r3", "post", path=tmp_db)
    autonomy.log_prompt_scores("r4", [
        {"prompt": "d", "score": 2, "pass": False, "reason": "y", "dims": {}}], path=tmp_db)
    autonomy.set_prompt_verdicts("r4", "reject", path=tmp_db)

    result = autonomy.prompt_gate_agreement(path=tmp_db)
    assert result["graded"] == 4
    assert result["agreement"] == 0.5
    assert result["passed_but_rejected"] == 1
    assert result["held_but_posted"] == 1


def test_prompt_verdict_rejects_unknown_values(tmp_db):
    with pytest.raises(ValueError):
        autonomy.set_prompt_verdicts("r1", "maybe", path=tmp_db)
    assert autonomy.set_prompt_verdicts(None, "post", path=tmp_db) == 0


# ---------- corrections ----------

def test_corrections_round_trip(tmp_db):
    cid = autonomy.add_correction("less neon, more silence", path=tmp_db)
    [pending] = autonomy.pending_corrections(path=tmp_db)
    assert pending["id"] == cid
    autonomy.consume_correction(cid, path=tmp_db)
    assert autonomy.pending_corrections(path=tmp_db) == []
