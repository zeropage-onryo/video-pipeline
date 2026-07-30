"""
Tests for shootgen.py -- generating shoot concepts from real locations.

Same split promptgen.py follows: the model's only job is producing a
concept, and validate_concept is what enforces it. "Prompts request,
code enforces" -- the prompt asks for at most 6 shots and a real
location name, validate_concept is what makes those true.
"""
import json

import pytest

from src import db, preprod, shootgen


@pytest.fixture
def tmp_db(tmp_path):
    path = tmp_path / "test.db"
    db.init_db(path)
    preprod.init(path)
    preprod.add_location("hallway", {"space": "narrow hallway"}, photo_count=2, path=path)
    preprod.add_location("garage", {"space": "cold garage"}, photo_count=3, path=path)
    return path


def make_concept(**overrides):
    concept = {
        "title": "The Waiting",
        "hook": "a hand already on the door handle",
        "duration": "12s",
        "logline": "He waits for someone who never knocks.",
        "shots": [
            {"n": 1, "type": "CHARACTER", "cam": "BMPCC", "location": "hallway",
             "desc": "low angle, he steps into frame", "light": "overhead practical"},
            {"n": 2, "type": "BROLL", "cam": "ACTION5", "location": "garage",
             "desc": "POV of the handle turning", "light": "spill under the door"},
        ],
        "ai": {"tool": "KLING", "technique": "image-to-video off shot 2",
               "prompt": "a door handle turning in the dark"},
        "edit": "hard cuts, silence until the handle",
        "grade": "crushed shadows, one warm accent",
    }
    concept.update(overrides)
    return concept


def response_for(concept):
    return json.dumps({"concept": concept})


LOCATION_NAMES = ["hallway", "garage"]


# ---------- brands ----------

def test_load_brand_returns_antihero_block():
    text = shootgen.load_brand("antihero")
    assert "ANTIHERO" in text
    assert "crushed shadows" in text


def test_load_brand_returns_zeropage_block():
    text = shootgen.load_brand("zeropage")
    assert "ZERO PAGE" in text
    assert "client" in text.lower()


def test_load_brand_rejects_unknown_brand():
    with pytest.raises(ValueError, match="brand must be one of"):
        shootgen.load_brand("nonsense")


# ---------- prompt ----------

def test_build_concept_prompt_includes_locations_and_brand(tmp_db):
    locations = preprod.list_locations(path=tmp_db)
    prompt = shootgen.build_concept_prompt(locations, "antihero", None, "someone at the door")

    assert "hallway" in prompt and "garage" in prompt
    assert "ANTIHERO" in prompt
    assert "someone at the door" in prompt
    for placeholder in ("{locations}", "{brand}", "{client}", "{spark}"):
        assert placeholder not in prompt


def test_build_concept_prompt_without_spark_or_client(tmp_db):
    locations = preprod.list_locations(path=tmp_db)
    prompt = shootgen.build_concept_prompt(locations, "antihero", None, None)
    assert "{spark}" not in prompt and "{client}" not in prompt


# ---------- parsing ----------

def test_parse_concept_response_reads_concept():
    parsed = shootgen.parse_concept_response(response_for(make_concept()))
    assert parsed["title"] == "The Waiting"
    assert len(parsed["shots"]) == 2


def test_parse_concept_response_strips_fences():
    fenced = f"```json\n{response_for(make_concept())}\n```"
    assert shootgen.parse_concept_response(fenced)["title"] == "The Waiting"


# ---------- validation: prompts request, code enforces ----------

def test_validate_accepts_a_good_concept():
    assert shootgen.validate_concept(make_concept(), LOCATION_NAMES) == []


def test_validate_rejects_more_than_six_shots():
    shots = [
        {"n": n, "type": "BROLL", "cam": "BMPCC", "location": "hallway",
         "desc": "d", "light": "l"}
        for n in range(1, 8)
    ]
    warnings = shootgen.validate_concept(make_concept(shots=shots), LOCATION_NAMES)
    assert any("at most 6 shots" in w for w in warnings)


def test_validate_rejects_unknown_shot_type():
    concept = make_concept()
    concept["shots"][0]["type"] = "MONTAGE"
    warnings = shootgen.validate_concept(concept, LOCATION_NAMES)
    assert any("type" in w for w in warnings)


def test_validate_rejects_unknown_camera():
    concept = make_concept()
    concept["shots"][0]["cam"] = "IPHONE"
    warnings = shootgen.validate_concept(concept, LOCATION_NAMES)
    assert any("cam" in w for w in warnings)


def test_validate_rejects_invented_location():
    """The whole point is grounding in real spaces -- a hallucinated
    room defeats it."""
    concept = make_concept()
    concept["shots"][0]["location"] = "rooftop helipad"
    warnings = shootgen.validate_concept(concept, LOCATION_NAMES)
    assert any("rooftop helipad" in w for w in warnings)


def test_validate_rejects_unknown_ai_tool():
    concept = make_concept(ai={"tool": "SORA", "technique": "x", "prompt": "y"})
    warnings = shootgen.validate_concept(concept, LOCATION_NAMES)
    assert any("tool" in w for w in warnings)


def test_validate_rejects_empty_shot_list():
    warnings = shootgen.validate_concept(make_concept(shots=[]), LOCATION_NAMES)
    assert any("no shots" in w for w in warnings)


def test_validate_allows_a_concept_with_no_ai_slot():
    concept = make_concept()
    del concept["ai"]
    assert shootgen.validate_concept(concept, LOCATION_NAMES) == []


# ---------- generate_concept ----------

def test_generate_concept_saves_and_links_locations(tmp_db, monkeypatch):
    monkeypatch.setattr(shootgen, "generate_with_retry",
                        lambda *a, **kw: response_for(make_concept()))

    result = shootgen.generate_concept(
        brand="antihero", spark="someone at the door",
        client=None, gemini_client=None, db_path=tmp_db,
    )

    assert result["warnings"] == []
    saved = preprod.get_concept(result["concept_id"], path=tmp_db)
    assert saved["title"] == "The Waiting"
    assert saved["brand"] == "antihero"
    assert {loc["name"] for loc in saved["locations"]} == {"hallway", "garage"}


def test_generate_concept_saves_even_with_warnings(tmp_db, monkeypatch):
    """
    A concept that breaks a rule is still worth keeping and looking at
    -- the warnings ride along on it rather than throwing the whole
    generation away.
    """
    bad = make_concept()
    bad["shots"][0]["location"] = "rooftop helipad"
    monkeypatch.setattr(shootgen, "generate_with_retry", lambda *a, **kw: response_for(bad))

    result = shootgen.generate_concept(
        brand="antihero", client=None, gemini_client=None, db_path=tmp_db,
    )

    assert result["warnings"]
    assert preprod.get_concept(result["concept_id"], path=tmp_db) is not None


def test_generate_concept_needs_at_least_one_location(tmp_path):
    """Without a described space there's nothing to ground a concept
    in, so this fails loudly rather than inventing rooms."""
    empty = tmp_path / "empty.db"
    db.init_db(empty)
    preprod.init(empty)

    with pytest.raises(ValueError, match="no locations"):
        shootgen.generate_concept(
            brand="antihero", client=None, gemini_client=None, db_path=empty,
        )
