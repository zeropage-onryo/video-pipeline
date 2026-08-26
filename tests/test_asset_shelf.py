"""
The RAG `assets` shelf: what makes a location, character, or prop
retrievable.

The library is text-only, so a reference photo can never be a row --
the description is the searchable artifact. These cover the shared
chunk format (one writer's output must equal the other's, or a
re-ingest duplicates instead of replacing), the vision step for cast
and props, and the backfill.

Hermetic: every vision call is patched at the function the code
actually calls, and rag.connect is refused unless a test wires a fake.
"""
import pytest

from src import asset_shelf, db, entities, locations, preprod

SAMPLE_SPACE = {"space": "narrow hallway", "light_sources": ["overhead practical"],
                "textures": ["scuffed paint"], "angles": ["low from the doorway"],
                "constraints": "tight, no wide lens"}

CHARACTER_VISION = {
    "look": "a man in a cracked black leather jacket, mid-thirties",
    "features": ["scar through the left eyebrow", "silver ring, right thumb"],
    "materials": ["black leather", "faded indigo denim"],
    "continuity": "jacket stays zipped to mid-chest",
}


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    path = tmp_path / "shelf.db"
    db.init_db(path)
    preprod.init(path)
    entities.init(path)
    monkeypatch.setattr(db, "DB_PATH", path)
    return path


@pytest.fixture(autouse=True)
def no_real_store(monkeypatch):
    def refused(db_url=None):
        raise ConnectionError("no rag store in tests")

    monkeypatch.setattr(asset_shelf.rag, "connect", refused)


@pytest.fixture
def shelf(monkeypatch):
    """A reachable fake store that records what was written."""
    class Conn:
        def close(self):
            pass

    records = []
    monkeypatch.setattr(asset_shelf.rag, "connect", lambda db_url=None: Conn())
    monkeypatch.setattr(asset_shelf.rag, "init_store", lambda c: None)
    monkeypatch.setattr(asset_shelf.rag, "make_client", lambda: object())
    monkeypatch.setattr(asset_shelf.rag, "ingest_records",
                        lambda recs, client, conn: records.extend(recs) or len(recs))
    return records


@pytest.fixture
def photo_dirs(tmp_path, monkeypatch):
    dirs = {}
    for kind in ("location", "character", "prop"):
        d = tmp_path / (kind + "s")
        d.mkdir()
        dirs[kind] = d
    monkeypatch.setattr(asset_shelf, "PHOTO_DIRS", dirs)
    return dirs


TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
    b"\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05"
    b"\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


# --- the shared format ------------------------------------------------------

def test_source_key_is_stable_per_asset():
    assert asset_shelf.source_key("character", "mike") == "assets/character-mike"


def test_slugify_matches_the_directory_rule():
    assert asset_shelf.slugify("Mike — On Camera") == "mike--on-camera"
    assert asset_shelf.slugify("../../etc/evil") == "etcevil"


def test_flatten_description_reads_both_shapes():
    space = asset_shelf.flatten_description(SAMPLE_SPACE)
    assert "space: narrow hallway" in space
    assert "light sources: overhead practical" in space

    person = asset_shelf.flatten_description(CHARACTER_VISION)
    assert "look: a man in a cracked black leather jacket" in person
    assert "scar through the left eyebrow" in person


def test_flatten_description_keeps_unknown_keys():
    """A future vision field must not silently vanish from the shelf."""
    assert "mood: wired" in asset_shelf.flatten_description(
        {"look": "x", "mood": "wired"})


def test_flatten_description_survives_junk():
    assert asset_shelf.flatten_description(None) == ""
    assert asset_shelf.flatten_description("not json") == "not json"


def test_chunk_text_carries_the_appearance():
    text = asset_shelf.chunk_text("character", "Mike", {
        "role": "protagonist", "notes": "deadpan",
        "description": CHARACTER_VISION})
    assert text.startswith("CHARACTER: Mike")
    assert "role: protagonist" in text
    assert "leather jacket" in text          # the searchable part
    assert "scar through the left eyebrow" in text


def test_ingest_one_never_raises_when_the_store_is_down():
    out = asset_shelf.ingest_one("prop", "helmet", "Helmet", {"category": "gear"})
    assert out["ok"] is False and out["chunks"] == 0 and out["error"]


def test_drop_one_never_raises_when_the_store_is_down():
    asset_shelf.drop_one("prop", "helmet")      # must not raise


# --- the vision step --------------------------------------------------------

def test_entity_prompt_asks_for_visible_facts_only():
    prompt = locations.build_entity_prompt("character", "Mike", 3)
    assert "3 photo(s)" in prompt and "Mike" in prompt
    assert "Do not guess at names, brands, or backstory" in prompt
    assert '"continuity"' in prompt


def test_parse_entity_description_rejects_a_missing_look():
    assert locations.parse_entity_description('{"look": "a man"}')["look"] == "a man"
    with pytest.raises(ValueError):
        locations.parse_entity_description('{"features": []}')


def test_describe_entity_refuses_an_unknown_kind():
    with pytest.raises(ValueError):
        locations.describe_entity(object(), "spaceship", "X", [])


# --- the backfill -----------------------------------------------------------

def _seed(tmp_db, photo_dirs, with_photos=True):
    preprod.add_location("garage", SAMPLE_SPACE, photo_count=1, path=tmp_db)
    cid = entities.add_character("Mike", role="protagonist", notes="deadpan",
                                 path=tmp_db)
    pid = entities.add_prop("Helmet", category="gear", path=tmp_db)
    if with_photos:
        for kind, slug in (("character", "mike"), ("prop", "helmet")):
            d = photo_dirs[kind] / slug
            d.mkdir(parents=True)
            (d / "a.png").write_bytes(TINY_PNG)
    return cid, pid


def test_backfill_ingests_everything_on_disk(tmp_db, photo_dirs, shelf):
    _seed(tmp_db, photo_dirs)
    result = asset_shelf.backfill(db_path=tmp_db)
    assert result["ingested"] == 3 and result["failed"] == 0
    sources = {r["source"] for r in shelf}
    assert sources == {"assets/location-garage", "assets/character-mike",
                       "assets/prop-helmet"}
    assert all(r["domain"] == "assets" for r in shelf)


def test_backfill_without_describe_makes_no_vision_call(tmp_db, photo_dirs, shelf,
                                                        monkeypatch):
    _seed(tmp_db, photo_dirs)

    def boom(*a, **k):
        raise AssertionError("describe=False must not call vision")

    monkeypatch.setattr(locations, "describe_entity", boom)
    result = asset_shelf.backfill(db_path=tmp_db, describe=False)
    assert result["described"] == 0


def test_backfill_describes_undescribed_cast_and_stores_it(tmp_db, photo_dirs,
                                                           shelf, monkeypatch):
    cid, _ = _seed(tmp_db, photo_dirs)
    seen = []

    def fake(client, kind, name, photos):
        seen.append((kind, name, len(photos)))
        return CHARACTER_VISION

    monkeypatch.setattr(locations, "describe_entity", fake)
    result = asset_shelf.backfill(db_path=tmp_db, describe=True,
                                  gemini_client=object())

    assert result["described"] == 2                    # character + prop
    assert ("character", "Mike", 1) in seen
    # stored on the row...
    assert entities.get_character(cid, path=tmp_db)["description"]["look"]
    # ...and in the chunk, which is the whole point
    mike = next(r for r in shelf if r["source"] == "assets/character-mike")
    assert "leather jacket" in mike["text"]


def test_backfill_skips_already_described_assets(tmp_db, photo_dirs, shelf,
                                                 monkeypatch):
    """Re-describing is a billed call for no new information."""
    cid, _ = _seed(tmp_db, photo_dirs)
    entities.set_description("character", cid, CHARACTER_VISION, path=tmp_db)
    calls = []
    monkeypatch.setattr(locations, "describe_entity",
                        lambda *a, **k: calls.append(a) or CHARACTER_VISION)
    result = asset_shelf.backfill(db_path=tmp_db, describe=True,
                                  gemini_client=object())
    assert result["described"] == 1                    # the prop only
    assert [c[1] for c in calls] == ["prop"]


def test_backfill_counts_assets_with_no_photos(tmp_db, photo_dirs, shelf):
    _seed(tmp_db, photo_dirs, with_photos=False)
    result = asset_shelf.backfill(db_path=tmp_db, describe=True,
                                  gemini_client=object())
    assert result["skipped_no_photos"] == 2
    assert result["ingested"] == 3                     # still shelved as text


def test_backfill_reports_a_failure_without_losing_the_rest(tmp_db, photo_dirs,
                                                            shelf, monkeypatch):
    _seed(tmp_db, photo_dirs)

    def flaky(client, kind, name, photos):
        if kind == "character":
            raise RuntimeError("vision unavailable")
        return CHARACTER_VISION

    monkeypatch.setattr(locations, "describe_entity", flaky)
    result = asset_shelf.backfill(db_path=tmp_db, describe=True,
                                  gemini_client=object())
    assert result["failed"] == 1
    assert "vision unavailable" in result["errors"][0]
    assert result["described"] == 1                    # the prop still landed
    assert result["ingested"] == 3                     # every asset still shelved


def test_backfill_survives_a_down_store(tmp_db, photo_dirs):
    """no_real_store is still in force -- the walk completes and reports."""
    _seed(tmp_db, photo_dirs)
    result = asset_shelf.backfill(db_path=tmp_db)
    assert result["ingested"] == 0 and result["failed"] == 3


def test_set_description_merges_over_typed_notes(tmp_db):
    cid = entities.add_character("Mike", description={"notes": "deadpan"},
                                 path=tmp_db)
    entities.set_description("character", cid, CHARACTER_VISION, path=tmp_db)
    desc = entities.get_character(cid, path=tmp_db)["description"]
    assert desc["notes"] == "deadpan"          # the human's text survives
    assert desc["look"].startswith("a man in a cracked")


def test_set_description_rejects_unknown_kinds_and_ids(tmp_db):
    with pytest.raises(ValueError):
        entities.set_description("spaceship", 1, {}, path=tmp_db)
    with pytest.raises(ValueError):
        entities.set_description("character", 999, {}, path=tmp_db)
