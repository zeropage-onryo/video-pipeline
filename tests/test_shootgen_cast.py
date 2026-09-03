"""
Cast & prop grounding for shootgen -- one level down from format_locations:
named characters and props with reference stills on file, so a generated
prompt can call them by name instead of re-describing appearance from
scratch every time.

Unlike reference_block (which hits Postgres/RAG and is retrieved at the
edge), characters/props are a plain SQLite read like locations, so they're
fetched directly inside generate_concept/generate_shot_list rather than
passed in pre-fetched. Most shoots use none of this -- an empty cast is
the common case, not an error state -- so the fallback note has to read
as "nothing on file", never as a warning.
"""
import json

import pytest

from src import entities, preprod, shootgen


@pytest.fixture
def tmp_db(pg):
    path = pg
    preprod.init(path)
    entities.init(path)
    preprod.add_location("hallway", {"space": "narrow hallway"}, photo_count=2, dsn=path, account_id=None)
    return path


# ---------- format_cast ----------

def test_format_cast_lists_characters_and_props():
    characters = [{"name": "Mike", "role": "protagonist", "photo_count": 4, "notes": ""}]
    props = [{"name": "Ducati frame", "category": "vehicle", "photo_count": 2, "notes": ""}]
    block = shootgen.format_cast(characters, props)
    assert "Mike" in block and "protagonist" in block
    assert "Ducati frame" in block and "vehicle" in block


def test_format_cast_flags_reference_photos_only_when_present():
    with_photos = shootgen.format_cast(
        [{"name": "Mike", "photo_count": 3}], [])
    without_photos = shootgen.format_cast(
        [{"name": "Mike", "photo_count": 0}], [])
    assert "reference photos on file" in with_photos
    assert "reference photos on file" not in without_photos


def test_format_cast_empty_when_nothing_on_file():
    assert shootgen.format_cast([], []) == ""


MIKE_ON_FILE = {
    "name": "Mike", "role": "protagonist", "photo_count": 6,
    "notes": "Stills of myself for my personal social media page.",
    "description": {
        "notes": "Stills of myself for my personal social media page.",
        "look": "A fair-skinned male with dark brown hair and a short mustache.",
        "features": ["Short, dark mustache", "Brown eyes"],
        "continuity": "The mustache and the hairstyle must remain consistent.",
    },
}


def test_format_cast_can_carry_the_appearance_the_description_already_holds():
    """The renders kept aging Mike up and losing the moustache, and the
    prompt never once said he had one: the cast line sent `notes`, which
    says why his photos exist, not what he looks like. The photo and the
    sentence do different jobs and the sentence was missing."""
    block = shootgen.format_cast([MIKE_ON_FILE], [], detail=True)
    assert "short mustache" in block
    assert "must remain consistent" in block


def test_format_cast_stays_lean_for_ideation():
    """Default off: ideation needs to know WHO is on file, and a cast of
    five with full descriptions crowds out the ideas."""
    block = shootgen.format_cast([MIKE_ON_FILE], [])
    assert "Mike" in block
    assert "short mustache" not in block


def test_format_cast_detail_survives_an_asset_with_no_description():
    """Half the rows are older than the describe step. A missing
    description is a thinner line, never a crash."""
    block = shootgen.format_cast(
        [{"name": "Mike", "photo_count": 2}],
        [{"name": "Helmet", "photo_count": 1, "description": "not a dict"}],
        detail=True)
    assert "Mike" in block and "Helmet" in block


def test_the_scene_writer_grounds_in_appearance_and_ideation_does_not(tmp_db,
                                                                      monkeypatch):
    """The two paths want different things from the same table. Only the
    scene writers' output becomes a prompt a renderer grounds."""
    entities.add_character(
        "Mike", role="protagonist", photo_count=6,
        description=MIKE_ON_FILE["description"], dsn=tmp_db, account_id=None)
    captured = {}

    def fake_generate(client, model, prompt):
        captured["prompt"] = prompt
        return json.dumps({"plan": {"duration": "12s", "shots": [
            {"n": 1, "type": "CHARACTER", "source": "CAMERA", "cam": "BMPCC",
             "location": "hallway", "desc": "d", "light": "l"},
        ]}})

    monkeypatch.setattr(shootgen, "generate_with_retry", fake_generate)
    concept_id = preprod.save_concept(
        {"title": "Void Signal", "hook": "h", "logline": "l"},
        brand="antihero", dsn=tmp_db, account_id=None)
    shootgen.write_scene_for_concept(concept_id, gemini_client=None, db_path=tmp_db)
    assert "short mustache" in captured["prompt"]

    def fake_concept(client, model, prompt):
        captured["prompt"] = prompt
        return response_for({
            "title": "T", "hook": "h", "logline": "l", "duration": "12s",
            "shots": [{"n": 1, "type": "CHARACTER", "source": "CAMERA", "cam": "BMPCC",
                       "location": "hallway", "desc": "d", "light": "l"}],
        })

    monkeypatch.setattr(shootgen, "generate_with_retry", fake_concept)
    shootgen.generate_concept(brand="antihero", gemini_client=None, db_path=tmp_db)
    assert "short mustache" not in captured["prompt"]


# ---------- build_concept_prompt / build_shotlist_prompt ----------

def test_build_concept_prompt_injects_cast():
    locs = [{"name": "shop", "description": {"space": "garage"}}]
    prompt = shootgen.build_concept_prompt(
        locs, "antihero", cast="- Mike — protagonist (reference photos on file)")
    assert "Mike" in prompt and "reference photos on file" in prompt
    assert "{cast}" not in prompt


def test_build_concept_prompt_falls_back_without_cast():
    locs = [{"name": "shop", "description": {"space": "garage"}}]
    prompt = shootgen.build_concept_prompt(locs, "antihero", cast="")
    assert shootgen.NO_CAST_NOTE in prompt
    assert "{cast}" not in prompt


def test_build_shotlist_prompt_injects_cast():
    locs = [{"name": "shop", "description": {"space": "garage"}}]
    concept = {"title": "T", "hook": "h", "logline": "l"}
    prompt = shootgen.build_shotlist_prompt(
        locs, "antihero", None, concept, cast="- Helmet — wardrobe (reference photos on file)")
    assert "Helmet" in prompt and "{cast}" not in prompt


def test_build_shotlist_prompt_falls_back_without_cast():
    locs = [{"name": "shop", "description": {"space": "garage"}}]
    concept = {"title": "T", "hook": "h", "logline": "l"}
    prompt = shootgen.build_shotlist_prompt(locs, "antihero", None, concept)
    assert shootgen.NO_CAST_NOTE in prompt


# ---------- end to end: generate_concept / generate_shot_list pull cast from the db ----------

def response_for(concept):
    return json.dumps({"concept": concept})


def test_generate_concept_grounds_in_named_cast(tmp_db, monkeypatch):
    entities.add_character("Mike", role="protagonist", photo_count=5, dsn=tmp_db, account_id=None)
    entities.add_prop("Ducati frame", category="vehicle", photo_count=3, dsn=tmp_db, account_id=None)

    captured = {}

    def fake_generate(client, model, prompt):
        captured["prompt"] = prompt
        return response_for({
            "title": "T", "hook": "h", "logline": "l", "duration": "12s",
            "shots": [{"n": 1, "type": "CHARACTER", "source": "CAMERA", "cam": "BMPCC",
                       "location": "hallway", "desc": "d", "light": "l"}],
        })

    monkeypatch.setattr(shootgen, "generate_with_retry", fake_generate)

    shootgen.generate_concept(brand="antihero", gemini_client=None, db_path=tmp_db)

    assert "Mike" in captured["prompt"]
    assert "Ducati frame" in captured["prompt"]
    assert "reference photos on file" in captured["prompt"]


def test_generate_concept_degrades_to_no_cast_note_when_nothing_on_file(tmp_db, monkeypatch):
    captured = {}

    def fake_generate(client, model, prompt):
        captured["prompt"] = prompt
        return response_for({
            "title": "T", "hook": "h", "logline": "l", "duration": "12s",
            "shots": [{"n": 1, "type": "CHARACTER", "source": "CAMERA", "cam": "BMPCC",
                       "location": "hallway", "desc": "d", "light": "l"}],
        })

    monkeypatch.setattr(shootgen, "generate_with_retry", fake_generate)

    shootgen.generate_concept(brand="antihero", gemini_client=None, db_path=tmp_db)

    assert shootgen.NO_CAST_NOTE in captured["prompt"]


def test_write_scene_grounds_in_named_cast(tmp_db, monkeypatch):
    entities.add_character("Mike", role="protagonist", photo_count=5, dsn=tmp_db, account_id=None)
    concept_id = preprod.save_concept(
        {"title": "Void Signal", "hook": "h", "logline": "l"},
        brand="antihero", dsn=tmp_db,
    
        account_id=None,)

    captured = {}

    def fake_generate(client, model, prompt):
        captured["prompt"] = prompt
        return json.dumps({"plan": {"duration": "12s", "shots": [
            {"n": 1, "type": "CHARACTER", "source": "CAMERA", "cam": "BMPCC",
             "location": "hallway", "desc": "d", "light": "l"},
        ]}})

    monkeypatch.setattr(shootgen, "generate_with_retry", fake_generate)

    shootgen.write_scene_for_concept(concept_id, gemini_client=None, db_path=tmp_db)

    assert "Mike" in captured["prompt"]
