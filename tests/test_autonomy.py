"""
Tests for src/autonomy.py -- channels, the hold queue / dead-man log,
the kill switch, and the evaluator-agreement number the credit gate
reads. Pure SQLite against a throwaway DB.
"""
import pytest

from src import autonomy


@pytest.fixture
def tmp_db(pg):
    path = pg
    autonomy.init(path)
    return path


# ---------- channels ----------

def test_init_seeds_the_two_channels_with_their_postures(tmp_db):
    channels = {c["name"]: c for c in autonomy.list_channels(dsn=tmp_db)}
    assert set(channels) == {"zeropage", "antihero"}
    assert channels["zeropage"]["autonomy"] == "queue"    # auto-generates; approve to post
    assert channels["antihero"]["autonomy"] == "shadow"   # personal brand -- review-gated
    assert all(c["rate_cap"] == 1 for c in channels.values())


def test_init_is_idempotent_and_keeps_promotions(tmp_db):
    autonomy.set_autonomy("zeropage", "auto", dsn=tmp_db)
    autonomy.init(tmp_db)   # re-running init must not reset the promotion
    assert autonomy.get_channel("zeropage", dsn=tmp_db)["autonomy"] == "auto"


def test_promotion_is_a_one_row_change(tmp_db):
    autonomy.set_autonomy("antihero", "auto", dsn=tmp_db)
    assert autonomy.get_channel("antihero", dsn=tmp_db)["autonomy"] == "auto"
    assert autonomy.get_channel("zeropage", dsn=tmp_db)["autonomy"] == "queue"   # untouched, still its own default


def test_set_autonomy_rejects_unknown_levels(tmp_db):
    with pytest.raises(ValueError):
        autonomy.set_autonomy("zeropage", "yolo", dsn=tmp_db)


# ---------- kill switch ----------

def test_kill_switch_round_trip(tmp_db, monkeypatch):
    monkeypatch.delenv("ZEROPAGE_KILL", raising=False)
    assert autonomy.killed(dsn=tmp_db) is False
    autonomy.kill("bad night", dsn=tmp_db)
    assert autonomy.killed(dsn=tmp_db) is True
    autonomy.unkill(dsn=tmp_db)
    assert autonomy.killed(dsn=tmp_db) is False


def test_kill_switch_env_var_needs_no_db_write(tmp_db, monkeypatch):
    monkeypatch.setenv("ZEROPAGE_KILL", "1")
    assert autonomy.killed(dsn=tmp_db) is True


# ---------- hold queue ----------

def test_hold_round_trip_with_payload(tmp_db):
    hold_id = autonomy.to_hold(
        "zeropage", "shadow — grading only", concept_id=7,
        caption="a caption", payload={"prompts": [{"tool": "KLING"}]},
        dsn=tmp_db, account_id=None
    )
    [row] = autonomy.list_hold(dsn=tmp_db, account_id=None)
    assert row["id"] == hold_id
    assert row["channel"] == "zeropage"
    assert row["concept_id"] == 7
    assert row["payload"]["prompts"][0]["tool"] == "KLING"


def test_resolve_hold_grades_a_run(tmp_db):
    hold_id = autonomy.to_hold("zeropage", "shadow", dsn=tmp_db, account_id=None)
    autonomy.resolve_hold(hold_id, "approved", dsn=tmp_db, account_id=None)
    assert autonomy.list_hold(status="held", dsn=tmp_db, account_id=None) == []
    [row] = autonomy.list_hold(status="approved", dsn=tmp_db, account_id=None)
    assert row["id"] == hold_id


def test_resolve_hold_rejects_unknown_status(tmp_db):
    hold_id = autonomy.to_hold("zeropage", "shadow", dsn=tmp_db, account_id=None)
    with pytest.raises(ValueError):
        autonomy.resolve_hold(hold_id, "maybe", dsn=tmp_db, account_id=None)


def test_posts_today_counts_only_posted(tmp_db):
    autonomy.to_hold("zeropage", "held one", dsn=tmp_db, account_id=None)
    autonomy.to_hold("zeropage", "posted one", status="posted", dsn=tmp_db, account_id=None)
    autonomy.to_hold("personal", "other channel", status="posted", dsn=tmp_db, account_id=None)
    assert autonomy.posts_today("zeropage", dsn=tmp_db) == 1


# ---------- the credit-gate number ----------

def test_evaluator_agreement_math(tmp_db):
    for status in ("approved", "approved", "approved", "rejected"):
        hold_id = autonomy.to_hold("zeropage", "shadow", dsn=tmp_db, account_id=None)
        autonomy.resolve_hold(hold_id, status, dsn=tmp_db, account_id=None)
    result = autonomy.evaluator_agreement("zeropage", dsn=tmp_db, account_id=None)
    assert result["graded"] == 4
    assert result["approved"] == 3
    assert result["agreement"] == 0.75


def test_evaluator_agreement_empty_is_none_not_zero(tmp_db):
    assert autonomy.evaluator_agreement(dsn=tmp_db, account_id=None)["agreement"] is None


# ---------- the prompt gate's numbers ----------

def test_prompt_scores_round_trip_and_verdict(tmp_db):
    autonomy.log_prompt_scores("run1", [
        {"prompt": "good one", "score": 9, "pass": True, "reason": "", "dims": {"camera": 2}},
        {"prompt": "weak one", "score": 3, "pass": False, "reason": "no light", "dims": {}},
    ], dsn=tmp_db)

    assert autonomy.first_try_pass_rate(dsn=tmp_db) == {
        "total": 2, "passed": 1, "rate": 0.5}
    assert autonomy.set_prompt_verdicts("run1", "reject", dsn=tmp_db) == 2


def test_prompt_gate_agreement_separates_the_two_error_costs(tmp_db):
    # gate passed, you rejected -> the expensive error (credit burned)
    autonomy.log_prompt_scores("r1", [
        {"prompt": "a", "score": 9, "pass": True, "reason": "", "dims": {}}], dsn=tmp_db)
    autonomy.set_prompt_verdicts("r1", "reject", dsn=tmp_db)
    # gate held, you'd post -> the cheap error (manual approval)
    autonomy.log_prompt_scores("r2", [
        {"prompt": "b", "score": 3, "pass": False, "reason": "x", "dims": {}}], dsn=tmp_db)
    autonomy.set_prompt_verdicts("r2", "post", dsn=tmp_db)
    # two agreements
    autonomy.log_prompt_scores("r3", [
        {"prompt": "c", "score": 9, "pass": True, "reason": "", "dims": {}}], dsn=tmp_db)
    autonomy.set_prompt_verdicts("r3", "post", dsn=tmp_db)
    autonomy.log_prompt_scores("r4", [
        {"prompt": "d", "score": 2, "pass": False, "reason": "y", "dims": {}}], dsn=tmp_db)
    autonomy.set_prompt_verdicts("r4", "reject", dsn=tmp_db)

    result = autonomy.prompt_gate_agreement(dsn=tmp_db)
    assert result["graded"] == 4
    assert result["agreement"] == 0.5
    assert result["passed_but_rejected"] == 1
    assert result["held_but_posted"] == 1


def test_prompt_verdict_rejects_unknown_values(tmp_db):
    with pytest.raises(ValueError):
        autonomy.set_prompt_verdicts("r1", "maybe", dsn=tmp_db)
    assert autonomy.set_prompt_verdicts(None, "post", dsn=tmp_db) == 0


# ---------- corrections ----------

def test_corrections_round_trip(tmp_db):
    cid = autonomy.add_correction("less neon, more silence", dsn=tmp_db)
    [pending] = autonomy.pending_corrections(dsn=tmp_db)
    assert pending["id"] == cid
    autonomy.consume_correction(cid, dsn=tmp_db)
    assert autonomy.pending_corrections(dsn=tmp_db) == []


def test_hold_for_concept_is_the_latest_and_owner_scoped(tmp_db):
    from src import accounts
    mine = accounts.upsert_account("mine", "Mine", dsn=tmp_db)
    theirs = accounts.upsert_account("theirs", "Theirs", dsn=tmp_db)
    autonomy.to_hold("zeropage", "first", concept_id=7, dsn=tmp_db, account_id=mine)
    autonomy.to_hold("zeropage", "second", concept_id=7,
                     payload={"run_id": "r2"}, dsn=tmp_db, account_id=mine)
    row = autonomy.hold_for_concept(7, dsn=tmp_db, account_id=mine)
    assert row["reason"] == "second" and row["payload"] == {"run_id": "r2"}
    assert autonomy.hold_for_concept(7, dsn=tmp_db, account_id=theirs) is None
    assert autonomy.hold_for_concept(8, dsn=tmp_db, account_id=mine) is None


def test_the_readers_answer_nothing_on_a_database_with_no_graph_history(pg):
    fresh = pg                             # db.init_db only: no autonomy.init, no hold_queue yet
    assert autonomy.hold_for_concept(1, dsn=fresh, account_id=None) is None
    assert autonomy.prompt_scores_for_run("r", dsn=fresh) == []


def test_prompt_scores_for_run_keeps_the_order_the_gate_scored_in(tmp_db):
    autonomy.log_prompt_scores("r", [
        {"prompt": "a", "score": 3, "pass": False, "reason": "thin",
         "dims": {"subject": 1}},
        {"prompt": "b", "score": 8, "pass": True, "reason": "", "dims": {}},
    ], dsn=tmp_db)
    rows = autonomy.prompt_scores_for_run("r", dsn=tmp_db)
    assert [(r["score"], r["passed"]) for r in rows] == [(3, False), (8, True)]
    assert rows[0]["dims"] == {"subject": 1}
    assert autonomy.prompt_scores_for_run(None, dsn=tmp_db) == []
    assert autonomy.prompt_scores_for_run("nope", dsn=tmp_db) == []
