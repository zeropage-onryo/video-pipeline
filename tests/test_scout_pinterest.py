"""
The Pinterest lane: pins off the brand's own board, read through the v5
API (imagesearch.pinterest). Replaces the RSS feeds lane in scout()'s
default set (2026-09-08) -- feeds was four generic film-gear blogs with
zero overlap with the world-building direction; this reads material Mike
actually curated. See .research/scout_sources_audit_2026-09-08.md.

Mirrors test_scout_instagram.py's credential-boundary style: dark, not
broken, and it must name the missing credential.
"""
import pytest

import src.imagesearch as imagesearch
from src import scout


@pytest.fixture
def tmp_db(pg, monkeypatch):
    path = pg
    scout.init(path)
    monkeypatch.setenv("DATABASE_URL", path)
    return path


@pytest.fixture(autouse=True)
def no_pinterest_credentials(monkeypatch):
    """Default to unconfigured; tests that want the lane live say so."""
    for name in ("PINTEREST_ACCESS_TOKEN", "PINTEREST_BOARD_ANTIHERO",
                 "PINTEREST_BOARD_ZEROPAGE"):
        monkeypatch.delenv(name, raising=False)


def _configured(monkeypatch, brand="zeropage"):
    monkeypatch.setenv("PINTEREST_ACCESS_TOKEN", "test-pin-token")
    monkeypatch.setenv(f"PINTEREST_BOARD_{brand.upper()}", "the-board")


# ---------- the credential boundary ----------

def test_the_lane_is_dark_without_a_token():
    [signal] = scout.gather_pinterest("zeropage")
    assert signal["lane"] == "pinterest"
    assert "PINTEREST_ACCESS_TOKEN" in signal["error"]


def test_the_lane_is_dark_without_a_board(monkeypatch):
    monkeypatch.setenv("PINTEREST_ACCESS_TOKEN", "test-pin-token")
    [signal] = scout.gather_pinterest("zeropage")
    assert signal["lane"] == "pinterest"
    assert "PINTEREST_BOARD_ZEROPAGE" in signal["error"]


def test_the_lane_is_brand_scoped_on_the_board_env_var(monkeypatch):
    """A token plus ANTIHERO's board must not light up ZEROPAGE -- each
    brand needs its own board named."""
    monkeypatch.setenv("PINTEREST_ACCESS_TOKEN", "test-pin-token")
    monkeypatch.setenv("PINTEREST_BOARD_ANTIHERO", "moto-board")
    [signal] = scout.gather_pinterest("zeropage")
    assert "PINTEREST_BOARD_ZEROPAGE" in signal["error"]


# ---------- the happy path ----------

def test_pins_become_signals(monkeypatch):
    _configured(monkeypatch)
    monkeypatch.setattr(imagesearch, "pinterest", lambda query, brand=None, limit=6: [
        {"source": "pinterest", "image_url": "https://i.pinimg.com/736x/a.jpg",
         "source_url": "https://www.pinterest.com/pin/1/",
         "title": "flooded mall neon sign", "credit": "pinned by you (the-board)"},
    ])
    [signal] = scout.gather_pinterest("zeropage")
    assert signal["lane"] == "pinterest"
    assert signal["detail"] == "flooded mall neon sign"
    assert signal["image"] == "https://i.pinimg.com/736x/a.jpg"
    assert signal["url"] == "https://www.pinterest.com/pin/1/"


def test_no_matching_pins_is_a_named_note_not_a_crash(monkeypatch):
    _configured(monkeypatch)
    monkeypatch.setattr(imagesearch, "pinterest", lambda query, brand=None, limit=6: [])
    [signal] = scout.gather_pinterest("zeropage")
    assert signal["lane"] == "pinterest"
    assert "no pins" in signal["error"]


def test_a_pinterest_exception_is_an_error_not_a_crash(monkeypatch):
    _configured(monkeypatch)

    def boom(query, brand=None, limit=6):
        raise RuntimeError("v5 API is down")

    monkeypatch.setattr(imagesearch, "pinterest", boom)
    [signal] = scout.gather_pinterest("zeropage")
    assert signal["lane"] == "pinterest"
    assert "v5 API is down" in signal["error"]


# ---------- the default lane set ----------

def test_pinterest_is_in_the_default_lane_set_and_feeds_is_not():
    import inspect
    default = inspect.signature(scout.scout).parameters["lanes"].default
    assert "pinterest" in default
    assert "feeds" not in default


# ---------- the bin ----------

def test_pinterest_may_now_bank_a_picture_alongside_instagram(tmp_db):
    """Mike's own curated pin is the same kind of source as his own
    Instagram post -- the image IS the post, not an article's
    illustration of one -- so it earns the same trust feeds/shorts/web
    images never got."""
    signals = [
        {"lane": "shorts", "detail": "t", "image": "https://i.ytimg.com/a.jpg"},
        {"lane": "feeds", "detail": "t", "image": "https://blog/lead.jpg"},
        {"lane": "web", "detail": "t", "image": "https://x/y.jpg"},
        {"lane": "instagram", "detail": "t", "image": "https://cdn.ig/p.jpg",
         "url": "https://instagram.com/p/abc"},
        {"lane": "pinterest", "detail": "t", "image": "https://i.pinimg.com/736x/a.jpg",
         "url": "https://www.pinterest.com/pin/1/"},
    ]
    # a distinct local name per source: stash_images dedupes on what came
    # back, so a stub answering every URL with one path proves only that
    # the dedupe works.
    rows = scout.stash_images("zeropage", "p", signals, dsn=tmp_db,
                              fetch=lambda u: f"/refs/{abs(hash(u))}.jpg")
    assert sorted(r["lane"] for r in rows) == ["instagram", "pinterest"]
