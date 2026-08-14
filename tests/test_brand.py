"""
Brand switcher / full separation (BACKLOG #7): the active brand rides a
cookie, drives generation, and filters holds + analytics so ANTIHERO and
Zero Page never blur.
"""
import pytest
from fastapi.testclient import TestClient

import app.main as app_main
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


def test_holds_are_filtered_to_the_active_brand(tmp_db):
    autonomy.to_hold("antihero", "ANTIHERO-REASON-XYZ", status="held", path=tmp_db)
    autonomy.to_hold("zeropage", "ZEROPAGE-REASON-XYZ", status="held", path=tmp_db)
    client.cookies.set("brand", "zeropage")
    r = client.get("/holds")
    client.cookies.clear()
    assert "ZEROPAGE-REASON-XYZ" in r.text
    assert "ANTIHERO-REASON-XYZ" not in r.text


def test_concepts_generate_uses_the_active_brand(tmp_db, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(app_main.genai, "Client", lambda **k: object())
    monkeypatch.setattr(app_main.shootgen, "reference_block", lambda **k: "")
    captured = {}

    def fake_gen(brand, **k):
        captured["brand"] = brand
        return {"concept": {"title": "X"}, "warnings": [], "concept_id": 1}

    monkeypatch.setattr(app_main.shootgen, "generate_concept", fake_gen)
    client.cookies.set("brand", "zeropage")
    client.post("/concepts/generate", data={"spark": "s"}, follow_redirects=False)
    client.cookies.clear()
    assert captured["brand"] == "zeropage"


def test_videos_brand_column_and_null_inclusive_filter(tmp_db):
    db.add_video("a", "youtube", "2026-08-01", brand="antihero", path=tmp_db)
    db.add_video("z", "youtube", "2026-08-02", brand="zeropage", path=tmp_db)
    db.add_video("legacy", "youtube", "2026-08-03", path=tmp_db)  # untagged
    zp = {v["title"] for v in db.list_videos(brand="zeropage", path=tmp_db)}
    ah = {v["title"] for v in db.list_videos(brand="antihero", path=tmp_db)}
    assert zp == {"z", "legacy"}   # brand match + NULL-inclusive legacy
    assert ah == {"a", "legacy"}
