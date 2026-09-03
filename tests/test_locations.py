"""
Tests for locations.py -- describing the spaces you can shoot in.

Mirrors ingest.py's vision step (photos -> Gemini -> structured
description) but for places rather than clips, and incremental for the
same reason: a description already paid for shouldn't be paid for
twice.
"""
import json

import pytest

from src import locations, preprod


@pytest.fixture
def tmp_db(pg):
    path = pg
    preprod.init(path)
    return path


@pytest.fixture
def locations_dir(tmp_path):
    """locations/<name>/*.jpg -- a directory per space."""
    root = tmp_path / "locations"
    for name in ("hallway", "garage"):
        space = root / name
        space.mkdir(parents=True)
        (space / "01.jpg").write_bytes(b"fake-jpeg-bytes")
        (space / "02.jpg").write_bytes(b"fake-jpeg-bytes")
    return root


VALID_DESCRIPTION = json.dumps({
    "space": "narrow hallway with a door at the end",
    "light_sources": ["overhead practical"],
    "textures": ["scuffed paint"],
    "angles": ["low from the doorway"],
    "constraints": "tight, no wide lens",
})


# ---------- discovery ----------

def test_find_location_dirs_returns_each_space(locations_dir):
    found = locations.find_location_dirs(locations_dir)
    assert [name for name, _ in found] == ["garage", "hallway"]


def test_find_location_dirs_counts_photos(locations_dir):
    found = dict(locations.find_location_dirs(locations_dir))
    assert len(found["hallway"]) == 2


def test_find_location_dirs_ignores_non_images(locations_dir):
    (locations_dir / "hallway" / "notes.txt").write_text("not a photo")
    found = dict(locations.find_location_dirs(locations_dir))
    assert len(found["hallway"]) == 2


def test_find_location_dirs_skips_empty_dirs(locations_dir):
    (locations_dir / "empty_room").mkdir()
    found = dict(locations.find_location_dirs(locations_dir))
    assert "empty_room" not in found


def test_find_location_dirs_missing_root_is_safe(tmp_path):
    assert locations.find_location_dirs(tmp_path / "nope") == []


# ---------- parsing ----------

def test_parse_description_reads_json():
    parsed = locations.parse_description(VALID_DESCRIPTION)
    assert parsed["space"].startswith("narrow hallway")
    assert parsed["light_sources"] == ["overhead practical"]


def test_parse_description_strips_fences():
    parsed = locations.parse_description(f"```json\n{VALID_DESCRIPTION}\n```")
    assert parsed["space"].startswith("narrow hallway")


def test_parse_description_rejects_missing_space():
    with pytest.raises(ValueError, match="space"):
        locations.parse_description(json.dumps({"textures": ["x"]}))


# ---------- describe_locations ----------

def test_describe_locations_saves_each_space(tmp_db, locations_dir, monkeypatch):
    monkeypatch.setattr(locations, "generate_with_retry",
                        lambda *a, **kw: VALID_DESCRIPTION)

    result = locations.describe_locations(
        locations_dir, client=None, db_path=tmp_db,
    )

    assert result["described"] == 2
    saved = preprod.list_locations(dsn=tmp_db, account_id=None)
    assert [loc["name"] for loc in saved] == ["garage", "hallway"]
    assert saved[0]["description"]["space"].startswith("narrow hallway")
    assert saved[0]["photo_count"] == 2


def test_describe_locations_is_incremental(tmp_db, locations_dir, monkeypatch):
    """A space already described isn't re-sent to the model."""
    preprod.add_location("hallway", {"space": "already known"}, photo_count=2, dsn=tmp_db, account_id=None)

    calls = []

    def counting(*a, **kw):
        calls.append(1)
        return VALID_DESCRIPTION

    monkeypatch.setattr(locations, "generate_with_retry", counting)

    result = locations.describe_locations(locations_dir, client=None, db_path=tmp_db)

    assert len(calls) == 1  # garage only
    assert result["described"] == 1
    assert result["skipped"] == 1
    assert preprod.get_location_by_name("hallway", dsn=tmp_db, account_id=None)["description"]["space"] == (
        "already known"
    )


def test_describe_locations_force_redescribes(tmp_db, locations_dir, monkeypatch):
    preprod.add_location("hallway", {"space": "stale"}, photo_count=2, dsn=tmp_db, account_id=None)
    monkeypatch.setattr(locations, "generate_with_retry",
                        lambda *a, **kw: VALID_DESCRIPTION)

    locations.describe_locations(locations_dir, client=None, db_path=tmp_db, force=True)

    updated = preprod.get_location_by_name("hallway", dsn=tmp_db, account_id=None)
    assert updated["description"]["space"].startswith("narrow hallway")


def test_describe_locations_survives_one_bad_response(tmp_db, locations_dir, monkeypatch):
    """One unusable description shouldn't lose the other space."""
    responses = iter(["not json at all", VALID_DESCRIPTION])
    monkeypatch.setattr(locations, "generate_with_retry", lambda *a, **kw: next(responses))

    result = locations.describe_locations(locations_dir, client=None, db_path=tmp_db)

    assert result["described"] == 1
    assert result["failed"] == 1
    assert [loc["name"] for loc in preprod.list_locations(dsn=tmp_db, account_id=None)] == ["hallway"]
