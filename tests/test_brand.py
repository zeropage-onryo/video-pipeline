"""
Brand switcher / full separation (BACKLOG #7): the active brand rides a
cookie, drives generation, and filters holds + analytics so ANTIHERO and
Zero Page never blur.
"""
import time

import pytest
from fastapi.testclient import TestClient

from app.main import DEFAULT_BRAND, active_brand, app
from src import autonomy, db, preprod

client = TestClient(app)


class _Req:
    def __init__(self, cookies):
        self.cookies = cookies


def test_active_brand_default_and_validation():
    assert active_brand(_Req({})) == DEFAULT_BRAND
    assert active_brand(_Req({"brand": "bogus"})) == DEFAULT_BRAND
    assert active_brand(_Req({"brand": "zeropage"})) == "zeropage"


def test_set_brand_sets_cookie_and_honours_next():
    r = client.post("/brand/zeropage", data={"next": "/holds"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/holds"
    assert "brand=zeropage" in r.headers.get("set-cookie", "")
    client.cookies.clear()


def test_set_brand_rejects_unknown_brand_and_offsite_next():
    r = client.post("/brand/nope", data={"next": "https://evil.example"},
                    follow_redirects=False)
    assert "brand=antihero" in r.headers.get("set-cookie", "")
    assert r.headers["location"] == "/studio"   # safe_next rejected the offsite path
    client.cookies.clear()


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    path = tmp_path / "app.db"
    db.init_db(path)
    preprod.init(path)
    autonomy.init(path)
    monkeypatch.setattr(db, "DB_PATH", path)
    return path


def test_holds_are_filtered_to_the_active_brand(tmp_db, monkeypatch):
    """The hold queue is /ui's Pipeline view now (the /holds page is a
    redirect); brand scoping rides /api/holds' ?channel filter, which
    the view passes from the active brand."""
    from app import auth
    stub = {"id": 1, "email": "t@example.com", "display_name": "T"}
    monkeypatch.setattr(auth, "current_user", lambda request: stub)
    autonomy.to_hold("antihero", "ANTIHERO-REASON-XYZ", status="held", path=tmp_db)
    autonomy.to_hold("zeropage", "ZEROPAGE-REASON-XYZ", status="held", path=tmp_db)
    reasons = [h["reason"] for h in
               client.get("/api/holds?channel=zeropage").json()["items"]]
    assert reasons == ["ZEROPAGE-REASON-XYZ"]


def test_generation_uses_the_active_brand(tmp_db, monkeypatch):
    """The brand cookie drives which brand a scene is written for --
    through /api/pipeline/run now that /concepts/generate is gone."""
    import src.shootgen as shootgen
    from app import api as api_mod
    from app import auth, jobs

    stub = {"id": 1, "email": "t@example.com", "display_name": "T"}
    monkeypatch.setattr(auth, "current_user", lambda request: stub)
    monkeypatch.setattr(api_mod, "_gemini_key", lambda: "k")
    monkeypatch.setattr(api_mod, "scene_grounding", lambda brand, spark: "")
    monkeypatch.setattr("google.genai.Client", lambda **k: object())
    captured = {}

    def fake_gen(brand, **k):
        captured["brand"] = brand
        return {"concept": {"title": "X"}, "warnings": [], "concept_id": 1}

    monkeypatch.setattr(shootgen, "generate_scene_concept", fake_gen)
    client.cookies.set("brand", "zeropage")
    job_id = client.post("/api/pipeline/run", data={"prompt": "s"}).json()["job_id"]
    client.cookies.clear()
    for _ in range(200):
        if jobs.get(job_id)["status"] in ("done", "failed"):
            break
        time.sleep(0.02)
    assert captured["brand"] == "zeropage"


def test_videos_brand_column_and_null_inclusive_filter(tmp_db):
    db.add_video("a", "youtube", "2026-08-01", brand="antihero", path=tmp_db, account_id=None)
    db.add_video("z", "youtube", "2026-08-02", brand="zeropage", path=tmp_db, account_id=None)
    db.add_video("legacy", "youtube", "2026-08-03", path=tmp_db, account_id=None)  # untagged
    zp = {v["title"] for v in db.list_videos(brand="zeropage", path=tmp_db, account_id=None)}
    ah = {v["title"] for v in db.list_videos(brand="antihero", path=tmp_db, account_id=None)}
    assert zp == {"z", "legacy"}   # brand match + NULL-inclusive legacy
    assert ah == {"a", "legacy"}
