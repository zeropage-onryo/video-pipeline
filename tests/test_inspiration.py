"""
Inspiration accounts: the researched defaults seed on init, a chosen
account's formula is folded into generation, and the store is editable.
Generation itself is mocked -- only the seeding, grounding, and routing run.
"""
import pytest
from fastapi.testclient import TestClient

import app.main as app_main
from app.main import app
from src import db, inspiration

client = TestClient(app)


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    path = tmp_path / "app.db"
    db.init_db(path)
    inspiration.init(path)          # seeds the three researched defaults
    monkeypatch.setattr(db, "DB_PATH", path)
    return path


def test_init_seeds_the_three_defaults_and_is_idempotent(tmp_db):
    handles = {a["handle"] for a in inspiration.list_accounts(path=tmp_db)}
    assert {"layed_black", "manny.walkerrr", "alexisglere"} <= handles
    n = len(inspiration.list_accounts(path=tmp_db))
    inspiration.init(tmp_db)        # re-init must not duplicate
    assert len(inspiration.list_accounts(path=tmp_db)) == n


def test_add_cleans_the_handle_and_upserts(tmp_db):
    inspiration.add("@Kaye.Creatives", "AI", "profile text", path=tmp_db)
    a = inspiration.get("kaye.creatives", path=tmp_db)
    assert a and a["note"] == "AI"
    inspiration.add("kaye.creatives", "AI v2", "new profile", path=tmp_db)
    assert inspiration.get("kaye.creatives", path=tmp_db)["profile"] == "new profile"


def test_grounding_block_wraps_with_the_no_copy_rule(tmp_db):
    block = inspiration.grounding_block(inspiration.get("layed_black", path=tmp_db))
    assert "riff" in block.lower() and "never copy" in block.lower()
    assert "layed_black" in block


def test_combined_grounding_lists_every_account(tmp_db):
    block = inspiration.combined_grounding(path=tmp_db)
    for h in ("layed_black", "manny.walkerrr", "alexisglere"):
        assert h in block
    assert "never copy" in block.lower()


def test_antihero_generation_auto_grounds_on_inspiration(tmp_db, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr(app_main.genai, "Client", lambda **k: object())
    monkeypatch.setattr(app_main.shootgen, "reference_block", lambda **k: "")
    captured = {}

    def fake_ideas(brand, references, **k):
        captured["brand"], captured["references"] = brand, references
        return {"ideas": []}

    monkeypatch.setattr(app_main.shootgen, "generate_concept_ideas", fake_ideas)
    client.cookies.set("brand", "antihero")
    client.post("/concepts/generate", data={"mode": "ideas"}, follow_redirects=False)
    client.cookies.clear()
    assert captured["brand"] == "antihero"
    assert "INSPIRATION GROUNDING" in captured["references"]
    assert "layed_black" in captured["references"]


def test_zeropage_generation_does_not_auto_ground(tmp_db, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr(app_main.genai, "Client", lambda **k: object())
    monkeypatch.setattr(app_main.shootgen, "reference_block", lambda **k: "")
    captured = {}

    def fake_ideas(brand, references, **k):
        captured["references"] = references
        return {"ideas": []}

    monkeypatch.setattr(app_main.shootgen, "generate_concept_ideas", fake_ideas)
    client.cookies.set("brand", "zeropage")
    client.post("/concepts/generate", data={"mode": "ideas"}, follow_redirects=False)
    client.cookies.clear()
    assert "INSPIRATION GROUNDING" not in captured["references"]


def test_add_and_delete_routes(tmp_db):
    client.post("/inspiration/add",
                data={"handle": "newone", "note": "n", "profile": "p"},
                follow_redirects=False)
    assert inspiration.get("newone", path=tmp_db) is not None
    client.post("/inspiration/newone/delete", follow_redirects=False)
    assert inspiration.get("newone", path=tmp_db) is None
