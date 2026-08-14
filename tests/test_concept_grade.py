"""
Surfacing the taste + performance judge in the UI (BACKLOG #5): scores are
stored on the concept and a grade button scores on demand. The LLM call is
mocked; storage, the route, and the ungraded-only batch run for real.
"""
import pytest
from fastapi.testclient import TestClient

import app.main as app_main
from app.main import app
from src import autonomy, db, entities, inspiration, preprod, winners

client = TestClient(app)


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    path = tmp_path / "app.db"
    db.init_db(path)
    preprod.init(path)
    entities.init(path)
    autonomy.init(path)
    winners.init(path)
    inspiration.init(path)
    monkeypatch.setattr(db, "DB_PATH", path)
    return path


def _concept(title="A concept"):
    return {"title": title, "hook": "h", "logline": "l", "shots": []}


def test_save_judge_score_persists_on_the_concept(tmp_db):
    cid = preprod.save_concept(_concept(), "antihero", path=tmp_db)
    preprod.save_judge_score(
        cid, {"overall": 8, "taste_fit": 9, "performance": 7, "reasons": ["r1", "r2"]},
        path=tmp_db)
    c = preprod.get_concept(cid, path=tmp_db)
    assert c["judge_overall"] == 8 and c["judge_taste"] == 9 and c["judge_perf"] == 7
    assert "r1" in c["judge_reason"]


def test_grade_route_scores_and_stores(tmp_db, monkeypatch):
    cid = preprod.save_concept(_concept(), "antihero", path=tmp_db)
    monkeypatch.setattr(
        app_main.taste_judge, "score_concept",
        lambda concept, **k: {"overall": 8.0, "taste_fit": 9.0, "performance": 7.0,
                              "reasons": ["echoes The Last Check"], "graded": True})
    r = client.post(f"/concepts/{cid}/grade", follow_redirects=False)
    assert r.status_code == 303 and "/concepts" in r.headers["location"]
    assert preprod.get_concept(cid, path=tmp_db)["judge_overall"] == 8.0


def test_grade_all_scores_only_ungraded(tmp_db, monkeypatch):
    c1 = preprod.save_concept(_concept("one"), "antihero", path=tmp_db)
    c2 = preprod.save_concept(_concept("two"), "antihero", path=tmp_db)
    preprod.save_judge_score(
        c1, {"overall": 5, "taste_fit": 5, "performance": 5, "reasons": []}, path=tmp_db)
    calls = []

    def fake(concept, **k):
        calls.append(concept["id"])
        return {"overall": 6.0, "taste_fit": 6.0, "performance": 6.0,
                "reasons": [], "graded": True}

    monkeypatch.setattr(app_main.taste_judge, "score_concept", fake)
    client.post("/concepts/grade-all", follow_redirects=False)
    assert calls == [c2]   # the already-graded one is skipped


def test_discard_deletes_the_concept(tmp_db):
    cid = preprod.save_concept(_concept("gone"), "antihero", path=tmp_db)
    r = client.post(f"/concepts/{cid}/discard", follow_redirects=False)
    assert r.status_code == 303 and "/concepts" in r.headers["location"]
    assert preprod.get_concept(cid, path=tmp_db) is None


def test_discard_all_clears_only_the_active_brand(tmp_db):
    a = preprod.save_concept(_concept("keep? no"), "antihero", path=tmp_db)
    z = preprod.save_concept(_concept("other brand"), "zeropage", path=tmp_db)
    client.cookies.set("brand", "antihero")
    r = client.post("/concepts/discard-all", follow_redirects=False)
    client.cookies.clear()
    assert r.status_code == 303
    assert preprod.get_concept(a, path=tmp_db) is None       # active brand wiped
    assert preprod.get_concept(z, path=tmp_db) is not None   # other brand untouched


def test_concepts_are_brand_scoped_and_rail_switches(tmp_db):
    preprod.save_concept(_concept("AH ONLY ONE"), "antihero", path=tmp_db)
    preprod.save_concept(_concept("ZP ONLY ONE"), "zeropage", path=tmp_db)
    client.cookies.set("brand", "zeropage")
    r = client.get("/concepts")
    client.cookies.clear()
    # switching to zeropage shows only its concepts...
    assert "ZP ONLY ONE" in r.text
    assert "AH ONLY ONE" not in r.text
    # ...and the rail carries a switch to the other brand
    assert "/brand/antihero" in r.text
