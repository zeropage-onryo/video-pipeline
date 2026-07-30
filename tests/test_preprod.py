"""
Tests for preprod.py -- the pre-production spine.

The pipeline's existing tables all describe footage that already
exists. These describe places you *could* shoot and concepts you
haven't shot yet, which is the phase that runs before ingest.

The one that matters: test_shot_label_is_recorded. You generate N
concepts and actually shoot some; that choice is the same kind of
ground-truth label as ideas.selected, and it's free to capture.
"""
import json

import pytest

from src import db, preprod


@pytest.fixture
def tmp_db(tmp_path):
    path = tmp_path / "test.db"
    db.init_db(path)
    preprod.init(path)
    return path


SAMPLE_DESCRIPTION = {
    "space": "narrow hallway, door at the far end",
    "light_sources": ["overhead practical", "spill from kitchen"],
    "textures": ["scuffed paint", "worn floorboards"],
    "angles": ["low from the doorway", "flat down the length of the hall"],
    "constraints": "no room for a wide lens past 3 feet",
}

SAMPLE_SHOTS = [
    {"n": 1, "type": "CHARACTER", "cam": "BMPCC", "location": "hallway",
     "desc": "low angle, he steps into frame", "light": "overhead practical only"},
    {"n": 2, "type": "BROLL", "cam": "ACTION5", "location": "hallway",
     "desc": "POV of the door handle turning", "light": "spill from kitchen"},
]


# ---------- locations ----------

def test_init_creates_tables(tmp_db):
    assert preprod.summary(tmp_db) == {
        "locations": 0, "shoot_concepts": 0,
    }


def test_add_location_stores_description(tmp_db):
    loc_id = preprod.add_location("hallway", SAMPLE_DESCRIPTION, photo_count=3, path=tmp_db)
    loc = preprod.get_location(loc_id, path=tmp_db)
    assert loc["name"] == "hallway"
    assert loc["photo_count"] == 3
    assert loc["description"]["space"].startswith("narrow hallway")


def test_add_location_is_idempotent_by_name(tmp_db):
    """Re-describing a location updates it rather than duplicating."""
    preprod.add_location("hallway", SAMPLE_DESCRIPTION, photo_count=3, path=tmp_db)
    preprod.add_location("hallway", {"space": "updated"}, photo_count=4, path=tmp_db)

    locations = preprod.list_locations(path=tmp_db)
    assert len(locations) == 1
    assert locations[0]["description"]["space"] == "updated"
    assert locations[0]["photo_count"] == 4


def test_get_location_by_name(tmp_db):
    preprod.add_location("garage", SAMPLE_DESCRIPTION, path=tmp_db)
    assert preprod.get_location_by_name("garage", path=tmp_db)["name"] == "garage"
    assert preprod.get_location_by_name("nowhere", path=tmp_db) is None


def test_list_locations_empty_is_safe(tmp_db):
    assert preprod.list_locations(path=tmp_db) == []


# ---------- concepts ----------

def test_save_concept_round_trips(tmp_db):
    loc_id = preprod.add_location("hallway", SAMPLE_DESCRIPTION, path=tmp_db)
    concept = {
        "title": "The Waiting",
        "hook": "a hand already on the door handle",
        "logline": "He waits for someone who never knocks.",
        "duration": "12s",
        "shots": SAMPLE_SHOTS,
        "ai": {"tool": "KLING", "technique": "image-to-video off shot 2",
               "prompt": "a door handle turning in the dark, crushed shadows"},
        "edit": "hard cuts, silence until the handle",
        "grade": "crushed shadows, one warm accent",
    }

    concept_id = preprod.save_concept(
        concept, brand="antihero", spark="someone at the door",
        location_ids=[loc_id], path=tmp_db,
    )

    saved = preprod.get_concept(concept_id, path=tmp_db)
    assert saved["title"] == "The Waiting"
    assert saved["brand"] == "antihero"
    assert len(saved["shots"]) == 2
    assert saved["ai"]["tool"] == "KLING"
    assert saved["shot_done"] == 0
    assert [loc["name"] for loc in saved["locations"]] == ["hallway"]


def test_save_concept_requires_a_title(tmp_db):
    with pytest.raises(ValueError, match="title"):
        preprod.save_concept({"shots": SAMPLE_SHOTS}, brand="antihero", path=tmp_db)


def test_shot_label_is_recorded(tmp_db):
    """
    The label that makes this measurable: which generated concepts you
    actually went and shot.
    """
    ids = [
        preprod.save_concept(
            {"title": f"Concept {n}", "shots": SAMPLE_SHOTS}, brand="antihero", path=tmp_db,
        )
        for n in range(4)
    ]

    preprod.mark_shot(ids[1], path=tmp_db)
    preprod.mark_shot(ids[2], path=tmp_db)

    assert preprod.get_concept(ids[1], path=tmp_db)["shot_done"] == 1
    assert preprod.get_concept(ids[0], path=tmp_db)["shot_done"] == 0

    rate = preprod.shoot_rate(path=tmp_db)
    assert rate["generated"] == 4
    assert rate["shot"] == 2
    assert rate["rate"] == 0.5


def test_mark_shot_is_reversible(tmp_db):
    concept_id = preprod.save_concept(
        {"title": "Concept", "shots": SAMPLE_SHOTS}, brand="antihero", path=tmp_db,
    )
    preprod.mark_shot(concept_id, path=tmp_db)
    preprod.mark_shot(concept_id, shot=False, path=tmp_db)
    assert preprod.get_concept(concept_id, path=tmp_db)["shot_done"] == 0


def test_shoot_rate_empty_is_safe(tmp_db):
    assert preprod.shoot_rate(path=tmp_db)["rate"] is None


def test_list_concepts_newest_first(tmp_db):
    for n in range(3):
        preprod.save_concept(
            {"title": f"Concept {n}", "shots": SAMPLE_SHOTS}, brand="antihero", path=tmp_db,
        )
    titles = [c["title"] for c in preprod.list_concepts(path=tmp_db)]
    assert titles == ["Concept 2", "Concept 1", "Concept 0"]


def test_concept_records_prompt_hash_for_comparison(tmp_db):
    """Same reason pitch_runs hashes its prompt: so a prompt change
    can be measured against the shoot rate it produced."""
    a = preprod.save_concept(
        {"title": "A", "shots": SAMPLE_SHOTS}, brand="antihero",
        prompt_template="version one", path=tmp_db,
    )
    b = preprod.save_concept(
        {"title": "B", "shots": SAMPLE_SHOTS}, brand="antihero",
        prompt_template="version two", path=tmp_db,
    )
    hash_a = preprod.get_concept(a, path=tmp_db)["prompt_hash"]
    hash_b = preprod.get_concept(b, path=tmp_db)["prompt_hash"]
    assert hash_a and hash_b and hash_a != hash_b


def test_concept_survives_json_round_trip(tmp_db):
    """shots/ai are stored as JSON text; they must come back as objects."""
    concept_id = preprod.save_concept(
        {"title": "T", "shots": SAMPLE_SHOTS, "ai": {"tool": "RUNWAY"}},
        brand="zeropage", client="a bar", path=tmp_db,
    )
    saved = preprod.get_concept(concept_id, path=tmp_db)
    assert isinstance(saved["shots"], list)
    assert saved["shots"][0]["cam"] == "BMPCC"
    assert saved["client"] == "a bar"
    assert json.loads(json.dumps(saved["shots"])) == SAMPLE_SHOTS


# ---------- two-stage: ideas, then shot lists ----------

def test_save_concept_allows_an_idea_with_no_shots(tmp_db):
    """Stage one saves ideas; the shot list comes later."""
    concept_id = preprod.save_concept(
        {"title": "Void Signal", "hook": "a thumb above a dark screen",
         "logline": "He waits for a call."},
        brand="antihero", path=tmp_db,
    )
    saved = preprod.get_concept(concept_id, path=tmp_db)
    assert saved["shots"] == []
    assert saved["has_shot_list"] is False


def test_update_concept_shots_fills_in_the_plan(tmp_db):
    concept_id = preprod.save_concept(
        {"title": "Void Signal", "hook": "h", "logline": "l"},
        brand="antihero", path=tmp_db,
    )
    preprod.update_concept_shots(
        concept_id,
        {"duration": "12s", "shots": SAMPLE_SHOTS,
         "ai": {"tool": "KLING", "technique": "t", "prompt": "p"},
         "edit": "hard cuts", "grade": "crushed"},
        location_ids=[],
        path=tmp_db,
    )
    saved = preprod.get_concept(concept_id, path=tmp_db)
    assert saved["has_shot_list"] is True
    assert len(saved["shots"]) == 2
    assert saved["duration"] == "12s"
    assert saved["ai"]["tool"] == "KLING"
    assert saved["edit_note"] == "hard cuts"
    # the idea's own fields survive
    assert saved["title"] == "Void Signal"
    assert saved["hook"] == "h"


def test_update_concept_shots_links_locations(tmp_db):
    loc_id = preprod.add_location("hallway", SAMPLE_DESCRIPTION, path=tmp_db)
    concept_id = preprod.save_concept({"title": "T"}, brand="antihero", path=tmp_db)
    preprod.update_concept_shots(
        concept_id, {"shots": SAMPLE_SHOTS}, location_ids=[loc_id], path=tmp_db,
    )
    assert [loc["name"] for loc in preprod.get_concept(concept_id, path=tmp_db)["locations"]] == [
        "hallway"
    ]


def test_update_concept_shots_rejects_missing_concept(tmp_db):
    with pytest.raises(ValueError, match="no concept"):
        preprod.update_concept_shots(999, {"shots": SAMPLE_SHOTS}, path=tmp_db)


def test_save_concept_ideas_saves_a_batch(tmp_db):
    ideas = [
        {"title": f"Idea {n}", "hook": f"hook {n}", "logline": f"line {n}"}
        for n in range(8)
    ]
    ids = preprod.save_concept_ideas(
        ideas, brand="antihero", spark="a door", prompt_template="v1", path=tmp_db,
    )
    assert len(ids) == 8
    assert preprod.summary(tmp_db)["shoot_concepts"] == 8
    assert all(c["has_shot_list"] is False for c in preprod.list_concepts(path=tmp_db))


def test_shortlist_rate_measures_which_ideas_got_a_shot_list(tmp_db):
    """
    The pick: of the ideas generated, which were worth planning. Same
    shape as pitch selection, one stage earlier than actually shooting.
    """
    ids = preprod.save_concept_ideas(
        [{"title": f"Idea {n}"} for n in range(4)], brand="antihero", path=tmp_db,
    )
    preprod.update_concept_shots(ids[0], {"shots": SAMPLE_SHOTS}, path=tmp_db)

    rate = preprod.shortlist_rate(path=tmp_db)
    assert rate["generated"] == 4
    assert rate["shortlisted"] == 1
    assert rate["rate"] == 0.25


def test_shortlist_rate_empty_is_safe(tmp_db):
    assert preprod.shortlist_rate(path=tmp_db)["rate"] is None
