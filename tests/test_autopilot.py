"""
Tests for autopilot.py -- the L4 path, where the contract IS the gate.

Everything irreversible (generating via platform APIs, posting to
public accounts) sits behind three independent conditions: the env
enable, an explicit per-run approval, and the absence of the kill-switch
file. Dry-run is the default everywhere. These tests pin that no
executor can fire unless all three align -- the gate logic is the
deliverable; the executors themselves are registration points that stay
unwired until real spend is authorized.
"""
import pytest

from src import autopilot


@pytest.fixture
def clean_gate(tmp_path, monkeypatch):
    """A world where the gate state is fully controlled: env off,
    no kill file, executors recorded instead of run."""
    monkeypatch.delenv(autopilot.ENABLE_ENV, raising=False)
    monkeypatch.setattr(autopilot, "KILL_SWITCH_PATH", tmp_path / "autopilot.off")
    fired = []
    monkeypatch.setattr(
        autopilot, "EXECUTORS",
        {"generate": lambda a: fired.append(("generate", a)),
         "post": lambda a: fired.append(("post", a))},
    )
    return fired


PLAN = {"actions": [
    {"kind": "generate", "tool": "veo", "prompt": "a drawer closing"},
    {"kind": "post", "platform": "youtube", "title": "T"},
]}


# ---------- the gate ----------

def test_everything_is_off_by_default(clean_gate):
    result = autopilot.execute(PLAN, approve=True, dry_run=False)
    assert result["executed"] == 0
    assert result["mode"] == "disabled"
    assert clean_gate == []


def test_dry_run_is_the_default_even_when_enabled(clean_gate, monkeypatch):
    monkeypatch.setenv(autopilot.ENABLE_ENV, "1")
    result = autopilot.execute(PLAN, approve=True)
    assert result["mode"] == "dry-run"
    assert result["executed"] == 0
    assert clean_gate == []
    # the dry run still *describes* everything it would have done
    assert len(result["would_execute"]) == 2


def test_no_approval_means_no_execution(clean_gate, monkeypatch):
    monkeypatch.setenv(autopilot.ENABLE_ENV, "1")
    result = autopilot.execute(PLAN, dry_run=False)
    assert result["mode"] == "unapproved"
    assert clean_gate == []


def test_kill_switch_beats_everything(clean_gate, monkeypatch):
    monkeypatch.setenv(autopilot.ENABLE_ENV, "1")
    autopilot.KILL_SWITCH_PATH.write_text("stop")
    result = autopilot.execute(PLAN, approve=True, dry_run=False)
    assert result["mode"] == "killed"
    assert clean_gate == []


def test_all_three_conditions_align_and_executors_fire(clean_gate, monkeypatch):
    monkeypatch.setenv(autopilot.ENABLE_ENV, "1")
    result = autopilot.execute(PLAN, approve=True, dry_run=False)
    assert result["mode"] == "live"
    assert result["executed"] == 2
    assert [kind for kind, _ in clean_gate] == ["generate", "post"]


def test_unwired_action_kinds_are_reported_not_invented(clean_gate, monkeypatch):
    monkeypatch.setenv(autopilot.ENABLE_ENV, "1")
    plan = {"actions": [{"kind": "teleport"}]}
    result = autopilot.execute(plan, approve=True, dry_run=False)
    assert result["executed"] == 0
    assert any("teleport" in s for s in result["skipped"])


# ---------- plan assembly is side-effect free ----------

def test_build_plan_reads_ai_shots_without_touching_anything(tmp_path):
    from src import db, preprod
    path = tmp_path / "test.db"
    db.init_db(path)
    preprod.init(path)
    preprod.add_location("garage", {"space": "g"}, path=path)
    preprod.save_concept(
        {"title": "T", "shots": [
            {"n": 1, "type": "BROLL", "source": "AI", "tool": "VEO",
             "location": "garage", "desc": "d", "prompt": "a drawer closing"},
        ]},
        brand="antihero", path=path,
    )
    plan = autopilot.build_plan(db_path=path)
    kinds = [a["kind"] for a in plan["actions"]]
    assert kinds == ["generate"]
    assert plan["actions"][0]["prompt"] == "a drawer closing"
    assert plan["actions"][0]["tool"] == "VEO"
