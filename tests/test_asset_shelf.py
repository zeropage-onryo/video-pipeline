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

from src import asset_shelf, entities, locations, preprod

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
def tmp_db(pg, monkeypatch):
    path = pg
    preprod.init(path)
    entities.init(path)
    monkeypatch.setenv("DATABASE_URL", path)
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


# --- catalogue() and in_scope() ---------------------------------------------
# 2026-09-03, Mike's call: a Create run (and the nightly graph) should
# ground only on what the idea/spark names, or what was explicitly
# picked -- never the whole asset bank by default. catalogue() is the
# candidate list; in_scope() is the filter.

def test_catalogue_carries_text_for_alias_matching(tmp_db, photo_dirs):
    """named_assets/asset_aliases read asset["text"] for multi-word
    proper nouns -- a catalogue missing it silently loses every alias
    beyond a bare name (the same gap _assets_all() in app/api.py never
    had)."""
    _seed(tmp_db, photo_dirs)
    (photo_dirs["location"] / "garage").mkdir(parents=True)
    (photo_dirs["location"] / "garage" / "a.png").write_bytes(TINY_PNG)

    items = asset_shelf.catalogue(db_path=tmp_db)
    mike = next(i for i in items if i["name"] == "Mike")
    assert mike["category"] == "character"
    assert mike["text"] == "deadpan"          # notes win over role
    assert mike["photos"]
    garage = next(i for i in items if i["name"] == "garage")
    assert "narrow hallway" in garage["text"]  # flattened location description


def test_in_scope_matches_a_name_in_the_text(tmp_db, photo_dirs):
    _seed(tmp_db, photo_dirs)
    (photo_dirs["location"] / "garage").mkdir(parents=True)
    (photo_dirs["location"] / "garage" / "a.png").write_bytes(TINY_PNG)
    items = asset_shelf.catalogue(db_path=tmp_db)

    scope = asset_shelf.in_scope("Mike walks into the garage", [], items)
    assert {a["name"] for a in scope} == {"Mike", "garage"}


def test_in_scope_is_empty_when_nothing_is_named_or_picked(tmp_db, photo_dirs):
    _seed(tmp_db, photo_dirs)
    items = asset_shelf.catalogue(db_path=tmp_db)
    assert asset_shelf.in_scope("a ritual at dusk", [], items) == []


def test_in_scope_honours_an_explicit_pick_even_when_unnamed(tmp_db, photo_dirs):
    """The / picker -- or a composer upload/carousel click -- attaches a
    photo whose URL names the asset's slug, the same shape a picked
    location photo has always used. That has to pull the asset in even
    when the idea text never says its name."""
    _seed(tmp_db, photo_dirs)
    items = asset_shelf.catalogue(db_path=tmp_db)
    helmet = next(i for i in items if i["name"] == "Helmet")

    scope = asset_shelf.in_scope("a ritual at dusk", helmet["photos"][:1], items)
    assert {a["name"] for a in scope} == {"Helmet"}


def test_in_scope_does_not_double_count_a_named_and_picked_asset(tmp_db, photo_dirs):
    _seed(tmp_db, photo_dirs)
    items = asset_shelf.catalogue(db_path=tmp_db)
    mike = next(i for i in items if i["name"] == "Mike")

    scope = asset_shelf.in_scope("Mike gears up", mike["photos"][:1], items)
    assert [a["name"] for a in scope] == ["Mike"]


def test_in_scope_ignores_an_asset_with_no_photos(tmp_db, photo_dirs):
    """Named in the text is not enough on its own -- named_assets has
    always required a photo to attach, and in_scope must not relax
    that just because the caller is a pre-generation cast check now
    instead of a post-generation ref-attach."""
    _seed(tmp_db, photo_dirs, with_photos=False)
    items = asset_shelf.catalogue(db_path=tmp_db)
    assert asset_shelf.in_scope("Mike gears up", [], items) == []


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
    preprod.add_location("garage", SAMPLE_SPACE, photo_count=1, dsn=tmp_db, account_id=None)
    cid = entities.add_character("Mike", role="protagonist", notes="deadpan",
                                 dsn=tmp_db, account_id=None)
    pid = entities.add_prop("Helmet", category="gear", dsn=tmp_db, account_id=None)
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
    assert entities.get_character(cid, dsn=tmp_db, account_id=None)["description"]["look"]
    # ...and in the chunk, which is the whole point
    mike = next(r for r in shelf if r["source"] == "assets/character-mike")
    assert "leather jacket" in mike["text"]


def test_backfill_skips_already_described_assets(tmp_db, photo_dirs, shelf,
                                                 monkeypatch):
    """Re-describing is a billed call for no new information."""
    cid, _ = _seed(tmp_db, photo_dirs)
    entities.set_description("character", cid, CHARACTER_VISION, dsn=tmp_db, account_id=None)
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
                                 dsn=tmp_db, account_id=None)
    entities.set_description("character", cid, CHARACTER_VISION, dsn=tmp_db, account_id=None)
    desc = entities.get_character(cid, dsn=tmp_db, account_id=None)["description"]
    assert desc["notes"] == "deadpan"          # the human's text survives
    assert desc["look"].startswith("a man in a cracked")


def test_set_description_rejects_unknown_kinds_and_ids(tmp_db):
    with pytest.raises(ValueError):
        entities.set_description("spaceship", 1, {}, dsn=tmp_db, account_id=None)
    with pytest.raises(ValueError):
        entities.set_description("character", 999, {}, dsn=tmp_db, account_id=None)


# ---------- "this failed, THIS is what worked" ----------
# The pairing exists because the obvious alternative teaches backwards:
# edit the box to the working prompt, hit deny, and the good prompt lands
# on the avoid shelf.

FAILED = "a bike in a garage, cinematic, 8k"
WORKED = "handheld, 35mm, a Ducati idling in a low-key garage; practical light"


@pytest.fixture
def winners_db(pg, monkeypatch):
    from src import winners
    path = pg
    winners.init(path)
    monkeypatch.setenv("DATABASE_URL", path)
    return path


@pytest.fixture
def rag_docs(monkeypatch):
    """Capture what each shelf actually receives."""
    from src import rag as rag_mod

    class Conn:
        def close(self):
            pass

    docs = []
    monkeypatch.setattr(rag_mod, "connect", lambda db_url=None: Conn())
    monkeypatch.setattr(rag_mod, "init_store", lambda c: None)
    monkeypatch.setattr(rag_mod, "make_client", lambda: object())
    monkeypatch.setattr(rag_mod, "ingest_records",
                        lambda recs, client, conn: docs.extend(recs) or len(recs))
    return docs


def test_record_pair_writes_both_halves_to_both_shelves(winners_db, rag_docs):
    from src import winners
    result = winners.record_pair("runway", FAILED, WORKED, note="too vague",
                                 dsn=winners_db)
    assert result["paired"] and result["ingested"]

    rows = {w["verdict"]: w for w in winners.list_all(dsn=winners_db)}
    assert rows["didnt_work"]["prompt"] == FAILED
    assert rows["worked"]["prompt"] == WORKED
    # linked both ways, so either half can render the other
    assert rows["didnt_work"]["pair_id"] == rows["worked"]["id"]
    assert rows["worked"]["pair_id"] == rows["didnt_work"]["id"]

    shelves = {d["domain"] for d in rag_docs}
    assert shelves == {"avoid_prompts", "winning_prompts"}


def test_each_paired_doc_names_the_other(winners_db, rag_docs):
    """The lesson is the contrast; a doc holding one side can't teach it."""
    from src import winners
    winners.record_pair("runway", FAILED, WORKED, dsn=winners_db)
    avoid = next(d for d in rag_docs if d["domain"] == "avoid_prompts")
    winning = next(d for d in rag_docs if d["domain"] == "winning_prompts")

    assert FAILED in avoid["text"] and WORKED in avoid["text"]
    assert "DID work" in avoid["text"]
    assert WORKED in winning["text"] and FAILED in winning["text"]
    assert "failed" in winning["text"].lower()


def test_unpaired_entries_are_unchanged(winners_db, rag_docs):
    """A plain verdict must render exactly as before the pairing existed."""
    from src import winners
    winners.record_and_learn("runway", FAILED, verdict="didnt_work",
                             dsn=winners_db)
    [doc] = rag_docs
    assert doc["domain"] == "avoid_prompts"
    assert "What was written instead" not in doc["text"]


def test_record_pair_requires_the_working_prompt(winners_db):
    from src import winners
    with pytest.raises(ValueError):
        winners.record_pair("runway", FAILED, "   ", dsn=winners_db)


def test_record_pair_survives_a_down_store(winners_db):
    """Both rows must persist even when neither can be embedded."""
    from src import winners
    result = winners.record_pair("runway", FAILED, WORKED, dsn=winners_db)
    assert result["ingested"] is False and result["error"]
    assert len(winners.list_all(dsn=winners_db)) == 2
