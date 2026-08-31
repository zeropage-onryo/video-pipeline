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
    preprod.add_location("garage", {"space": "g"}, path=path, account_id=None)
    preprod.save_concept(
        {"title": "T", "shots": [
            {"n": 1, "type": "BROLL", "source": "AI", "tool": "VEO",
             "location": "garage", "desc": "d", "prompt": "a drawer closing"},
        ]},
        brand="antihero", path=path,
    
        account_id=None,)
    plan = autopilot.build_plan(db_path=path)
    kinds = [a["kind"] for a in plan["actions"]]
    assert kinds == ["generate"]
    assert plan["actions"][0]["prompt"] == "a drawer closing"
    assert plan["actions"][0]["tool"] == "VEO"


def test_build_plan_emits_post_only_once_media_exists(tmp_path):
    """The plan never invents deliverables: a post action appears only
    when a shot carries a rendered media_url for Meta to fetch -- and,
    for Zero Page, only once the concept has cleared the uncanny gate."""
    from src import db, preprod
    path = tmp_path / "test.db"
    db.init_db(path)
    preprod.init(path)
    preprod.add_location("garage", {"space": "g"}, path=path, account_id=None)
    preprod.save_concept(
        {"title": "No media yet", "hook": "h", "shots": [
            {"n": 1, "type": "BROLL", "source": "AI", "tool": "VEO",
             "location": "garage", "desc": "d", "prompt": "p"},
        ]},
        brand="zeropage", path=path,
    
        account_id=None,)
    cid = preprod.save_concept(
        {"title": "Rendered", "hook": "the hook", "shots": [
            {"n": 1, "type": "BROLL", "source": "AI", "tool": "VEO",
             "location": "garage", "desc": "d", "prompt": "p",
             "media_url": "https://cdn.example/rendered.mp4"},
        ]},
        brand="zeropage", path=path,
    
        account_id=None,)
    preprod.save_uncanny_score(
        cid, {"overall": 9, "passed": True, "reasons": []}, path=path, account_id=None)
    plan = autopilot.build_plan(db_path=path)
    posts = [a for a in plan["actions"] if a["kind"] == "post"]
    assert len(posts) == 1
    assert posts[0]["video_url"] == "https://cdn.example/rendered.mp4"
    assert posts[0]["platform"] == "instagram"
    assert posts[0]["caption"] == "the hook"


# ---------- the real post adapter, still caged ----------

def test_real_post_adapter_is_registered():
    assert autopilot.EXECUTORS["post"] is autopilot._post_dispatch


def test_post_dispatch_routes_by_platform(monkeypatch):
    from src import instagram, youtube
    ig_calls = []
    yt_calls = []
    monkeypatch.setattr(instagram, "execute_post_action", lambda a: ig_calls.append(a))
    monkeypatch.setattr(youtube, "execute_post_action", lambda a: yt_calls.append(a))

    autopilot._post_dispatch({"platform": "instagram"})
    autopilot._post_dispatch({})   # default -> instagram
    autopilot._post_dispatch({"platform": "youtube"})

    assert len(ig_calls) == 2
    assert len(yt_calls) == 1


def test_gate_modes_never_touch_instagram_with_real_adapter(tmp_path, monkeypatch):
    """The adapter being wired must not weaken the gate: disabled /
    unapproved / dry-run still execute nothing and never reach the API."""
    from src import instagram
    monkeypatch.setattr(autopilot, "KILL_SWITCH_PATH", tmp_path / "autopilot.off")

    def explode(*a, **k):
        raise AssertionError("instagram touched outside live mode")

    monkeypatch.setattr(instagram, "post_reel", explode)
    plan = {"actions": [{"kind": "post", "platform": "instagram",
                         "video_url": "https://x/v.mp4", "caption": "c"}]}

    monkeypatch.delenv(autopilot.ENABLE_ENV, raising=False)
    assert autopilot.execute(plan, approve=True, dry_run=False)["executed"] == 0

    monkeypatch.setenv(autopilot.ENABLE_ENV, "1")
    assert autopilot.execute(plan, dry_run=False)["executed"] == 0       # unapproved
    assert autopilot.execute(plan, approve=True)["executed"] == 0        # dry-run


def test_live_mode_calls_the_instagram_adapter(tmp_path, monkeypatch):
    from src import instagram
    monkeypatch.setattr(autopilot, "KILL_SWITCH_PATH", tmp_path / "autopilot.off")
    monkeypatch.setenv(autopilot.ENABLE_ENV, "1")
    monkeypatch.setenv("IG_USER_ID", "user-9")
    monkeypatch.setenv("IG_ACCESS_TOKEN", "tok")

    calls = []
    monkeypatch.setattr(
        instagram, "post_reel",
        lambda *a, **k: (calls.append(a), {"ok": True, "media_id": "m-1",
                                           "step": "publish", "error": None})[1],
    )
    plan = {"actions": [{"kind": "post", "platform": "instagram",
                         "video_url": "https://x/v.mp4", "caption": "c"}]}
    result = autopilot.execute(plan, approve=True, dry_run=False)
    assert result["mode"] == "live"
    assert result["executed"] == 1
    assert len(calls) == 1
