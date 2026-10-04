"""
Inspiration accounts: nothing is seeded on init (no brand ideas, 2026-10-04),
an added account's formula is folded into generation, and the store is
editable.
Generation itself is mocked -- only the seeding, grounding, and routing run.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from src import inspiration

client = TestClient(app)


@pytest.fixture
def tmp_db(pg, monkeypatch):
    from src import preprod
    path = pg
    preprod.init(path)              # reference_block reads the described rooms
    inspiration.init(path)          # seeds nothing any more
    inspiration.add("sample.creator", "a test account", "a test formula: one hero "
                    "object, re-shot in new light", brand="antihero", dsn=path)
    monkeypatch.setenv("DATABASE_URL", path)
    return path


def test_init_seeds_no_brand_accounts_and_is_idempotent(tmp_db):
    handles = {a["handle"] for a in inspiration.list_accounts(dsn=tmp_db)}
    assert handles == {"sample.creator"}          # only what the test added
    assert inspiration.DEFAULT_ACCOUNTS == []
    n = len(inspiration.list_accounts(dsn=tmp_db))
    inspiration.init(tmp_db)        # re-init must not duplicate
    assert len(inspiration.list_accounts(dsn=tmp_db)) == n


def test_add_cleans_the_handle_and_upserts(tmp_db):
    inspiration.add("@Kaye.Creatives", "AI", "profile text", dsn=tmp_db)
    a = inspiration.get("kaye.creatives", dsn=tmp_db)
    assert a and a["note"] == "AI"
    inspiration.add("kaye.creatives", "AI v2", "new profile", dsn=tmp_db)
    assert inspiration.get("kaye.creatives", dsn=tmp_db)["profile"] == "new profile"


def test_grounding_block_wraps_with_the_no_copy_rule(tmp_db):
    block = inspiration.grounding_block(inspiration.get("sample.creator", dsn=tmp_db))
    assert "riff" in block.lower() and "never copy" in block.lower()
    assert "sample.creator" in block


def test_combined_grounding_lists_every_account(tmp_db):
    block = inspiration.combined_grounding(dsn=tmp_db)
    assert "sample.creator" in block
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
    assert "sample.creator" in references


def test_zeropage_generation_does_not_auto_ground(tmp_db, monkeypatch):
    """Brand-scoped: ANTIHERO's moto/noir riffs must never leak into
    Zero Page's faceless ideation."""
    from app import api as api_mod
    monkeypatch.setattr(api_mod.rag, "connect",
                        lambda db_url=None: (_ for _ in ()).throw(ConnectionError("no store")))
    references = api_mod.scene_grounding("zeropage", "a night ride")
    assert "sample.creator" not in references


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
    assert inspiration.get("newone", dsn=tmp_db) is not None
    client.post("/inspiration/newone/delete", follow_redirects=False)
    assert inspiration.get("newone", dsn=tmp_db) is None
