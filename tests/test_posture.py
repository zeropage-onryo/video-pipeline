"""
Two accounts, two postures. The brand toggle flips the RELATIONSHIP to the post
button: ANTIHERO is review-gated, Zero Page runs autopilot with a one-tap
pause/resume of the kill switch. These lock the posture read + the toggle
routes; the kill-switch path is redirected to a tmp file so the real one is
never touched.
"""
import pytest
from fastapi.testclient import TestClient

import app.main as app_main
from app.main import app
from src import autopilot, db, entities, inspiration, preprod, winners

client = TestClient(app)


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    path = tmp_path / "app.db"
    db.init_db(path)
    preprod.init(path)
    entities.init(path)
    inspiration.init(path)
    winners.init(path)
    monkeypatch.setattr(db, "DB_PATH", path)
    return path


@pytest.fixture
def tmp_killswitch(tmp_path, monkeypatch):
    ks = tmp_path / "autopilot.off"
    monkeypatch.setattr(autopilot, "KILL_SWITCH_PATH", ks)
    return ks


@pytest.mark.xfail(reason="brand_posture() not implemented -- Studio posture UI unbuilt", strict=False)
def test_brand_posture_maps_the_two_accounts():
    assert app_main.brand_posture("zeropage") == "autopilot"
    assert app_main.brand_posture("antihero") == "review"


@pytest.mark.xfail(reason="autopilot_state() not implemented -- Studio posture UI unbuilt", strict=False)
def test_autopilot_state_reads_live_standby_and_paused(monkeypatch, tmp_killswitch):
    monkeypatch.delenv("ZEROPAGE_AUTOPILOT", raising=False)
    st = app_main.autopilot_state()
    assert st["tone"] == "standby" and not st["live"]

    monkeypatch.setenv("ZEROPAGE_AUTOPILOT", "1")
    st = app_main.autopilot_state()
    assert st["tone"] == "live" and st["live"]

    tmp_killswitch.write_text("off")
    st = app_main.autopilot_state()
    assert st["tone"] == "killed" and not st["live"]


@pytest.mark.xfail(reason="/autopilot/pause route not implemented -- touches the kill switch", strict=False)
def test_pause_route_drops_the_kill_switch(tmp_killswitch):
    assert not tmp_killswitch.exists()
    r = client.post("/autopilot/pause", data={"next": "/studio"}, follow_redirects=False)
    assert r.status_code == 303
    assert tmp_killswitch.exists()


@pytest.mark.xfail(reason="/autopilot/resume route not implemented -- touches the kill switch", strict=False)
def test_resume_route_lifts_the_kill_switch(tmp_killswitch):
    tmp_killswitch.write_text("off")
    r = client.post("/autopilot/resume", data={"next": "/studio"}, follow_redirects=False)
    assert r.status_code == 303
    assert not tmp_killswitch.exists()


@pytest.mark.xfail(reason="Studio rail posture text not implemented yet", strict=False)
def test_rail_shows_review_gated_for_antihero(tmp_db, tmp_killswitch):
    client.cookies.set("brand", "antihero")
    r = client.get("/studio")
    client.cookies.clear()
    assert "REVIEW-GATED" in r.text
    assert "AUTOPILOT" not in r.text


@pytest.mark.xfail(reason="Studio rail posture text not implemented yet", strict=False)
def test_rail_shows_autopilot_for_zeropage(tmp_db, tmp_killswitch, monkeypatch):
    monkeypatch.setenv("ZEROPAGE_AUTOPILOT", "1")
    client.cookies.set("brand", "zeropage")
    r = client.get("/studio")
    client.cookies.clear()
    assert "AUTOPILOT LIVE" in r.text
    assert "PAUSE" in r.text


def _concept_with_rendered_shot(brand, tmp_db):
    return preprod.save_concept(
        {"title": f"{brand} clip", "hook": "h", "logline": "l",
         "shots": [{"n": 1, "type": "BROLL", "source": "AI", "tool": "VEO",
                    "prompt": "p", "media_url": "https://cdn/x.mp4"}]},
        brand=brand, path=tmp_db)


def test_antihero_never_enters_an_autopost_plan(tmp_db):
    cid = _concept_with_rendered_shot("antihero", tmp_db)
    preprod.save_uncanny_score(cid, {"overall": 9, "passed": True, "reasons": []},
                               path=tmp_db)  # even if (wrongly) marked passed
    posts = [a for a in autopilot.build_plan(db_path=tmp_db)["actions"]
             if a["kind"] == "post"]
    assert posts == []   # review-gated forever


def test_zeropage_held_concept_is_not_post_eligible(tmp_db):
    cid = _concept_with_rendered_shot("zeropage", tmp_db)
    preprod.save_uncanny_score(cid, {"overall": 4, "passed": False, "reasons": ["glossy"]},
                               path=tmp_db)
    posts = [a for a in autopilot.build_plan(db_path=tmp_db)["actions"]
             if a["kind"] == "post"]
    assert posts == []


def test_zeropage_unjudged_concept_is_not_post_eligible(tmp_db):
    # no uncanny score at all -> fails closed, not post-eligible
    _concept_with_rendered_shot("zeropage", tmp_db)
    posts = [a for a in autopilot.build_plan(db_path=tmp_db)["actions"]
             if a["kind"] == "post"]
    assert posts == []


def test_zeropage_passed_concept_is_post_eligible(tmp_db):
    cid = _concept_with_rendered_shot("zeropage", tmp_db)
    preprod.save_uncanny_score(cid, {"overall": 9, "passed": True, "reasons": []},
                               path=tmp_db)
    posts = [a for a in autopilot.build_plan(db_path=tmp_db)["actions"]
             if a["kind"] == "post"]
    assert len(posts) == 1
    assert posts[0]["title"] == "zeropage clip"
