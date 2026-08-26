"""
Inspiration accounts: the researched defaults seed on init, a chosen
account's formula is folded into generation, and the store is editable.
Generation itself is mocked -- only the seeding, grounding, and routing run.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from src import db, inspiration

client = TestClient(app)


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    from src import preprod
    path = tmp_path / "app.db"
    db.init_db(path)
    preprod.init(path)              # reference_block reads the described rooms
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
    """The accounts steer every real generation. This grounding used to
    live on the dev console's /concepts/generate; it moved to the live
    path (api.scene_grounding) when that route went with its page, and
    without a test here it would have died silently."""
    from app import api as api_mod
    monkeypatch.setattr(api_mod.rag, "connect",
                        lambda db_url=None: (_ for _ in ()).throw(ConnectionError("no store")))
    references = api_mod.scene_grounding("antihero", "a night ride")
    assert "INSPIRATION GROUNDING" in references
    assert "layed_black" in references


def test_zeropage_generation_does_not_auto_ground(tmp_db, monkeypatch):
    """Brand-scoped: ANTIHERO's moto/noir riffs must never leak into
    Zero Page's faceless ideation."""
    from app import api as api_mod
    monkeypatch.setattr(api_mod.rag, "connect",
                        lambda db_url=None: (_ for _ in ()).throw(ConnectionError("no store")))
    references = api_mod.scene_grounding("zeropage", "a night ride")
    assert "layed_black" not in references


def test_scene_grounding_survives_a_dead_inspiration_store(tmp_db, monkeypatch):
    """Grounding is an enhancement, never a gate."""
    from app import api as api_mod
    monkeypatch.setattr(api_mod.rag, "connect",
                        lambda db_url=None: (_ for _ in ()).throw(ConnectionError("no store")))

    def boom(**kwargs):
        raise RuntimeError("inspiration table missing")

    monkeypatch.setattr(api_mod.inspiration, "combined_grounding", boom)
    assert api_mod.scene_grounding("antihero", "spark") == ""


def test_add_and_delete_routes(tmp_db):
    client.post("/inspiration/add",
                data={"handle": "newone", "note": "n", "profile": "p"},
                follow_redirects=False)
    assert inspiration.get("newone", path=tmp_db) is not None
    client.post("/inspiration/newone/delete", follow_redirects=False)
    assert inspiration.get("newone", path=tmp_db) is None
