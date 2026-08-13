"""
Tests for shootgen.py -- generating shoot concepts from real locations.

Same split promptgen.py follows: the model's only job is producing a
concept, and validate_concept turns rule breaks into visible warnings.
"Prompts request, code advises" -- the rooms ground every idea, and a
mismatch is flagged for the human, never silently discarded and never
a rejection. A concept may mix CAMERA and AI shots freely; AI shots
name a tool from the shot.py platform registry.
"""
import json

import pytest

from src import db, entities, preprod, shootgen


@pytest.fixture
def tmp_db(tmp_path):
    path = tmp_path / "test.db"
    db.init_db(path)
    preprod.init(path)
    entities.init(path)
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


def test_build_concept_prompt_notes_attached_images(tmp_db):
    """Ad hoc references from the Studio composer get a plain-language
    note in the prompt so the model treats the attached image parts as
    grounding, not decoration -- separate from the Workflow library's
    `{references}` block."""
    locations = preprod.list_locations(path=tmp_db)
    prompt = shootgen.build_concept_prompt(locations, "antihero", None, None,
                                           image_ref_count=2)
    assert "{visual_refs}" not in prompt
    assert "2 images attached" in prompt


def test_build_concept_prompt_omits_the_visual_note_by_default(tmp_db):
    locations = preprod.list_locations(path=tmp_db)
    prompt = shootgen.build_concept_prompt(locations, "antihero", None, None)
    assert "{visual_refs}" not in prompt
    assert "attached below this prompt" not in prompt


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


def test_validate_accepts_any_number_of_shots():
    """The 6-shot cap is retired: a concept mixing real and AI shots
    can run as long as the story needs. Shoot discipline is the
    prompt's guidance, not the validator's business."""
    shots = [
        {"n": n, "type": "BROLL", "cam": "BMPCC", "location": "hallway",
         "desc": "d", "light": "l"}
        for n in range(1, 12)
    ]
    assert shootgen.validate_concept(make_concept(shots=shots), LOCATION_NAMES) == []


def test_validate_accepts_multiple_ai_shots():
    """Real and AI are co-inputs: any shot may be generated instead of
    captured, and there is no per-concept AI ceiling."""
    shots = [
        {"n": 1, "type": "CHARACTER", "source": "CAMERA", "cam": "BMPCC",
         "location": "hallway", "desc": "d", "light": "l"},
        {"n": 2, "type": "BROLL", "source": "AI", "tool": "VEO",
         "location": "garage", "desc": "d", "prompt": "a drawer closing"},
        {"n": 3, "type": "BROLL", "source": "AI", "tool": "SEEDANCE",
         "location": "garage", "desc": "d", "prompt": "dust in the light"},
    ]
    assert shootgen.validate_concept(make_concept(shots=shots), LOCATION_NAMES) == []


def test_validate_warns_on_unknown_source():
    concept = make_concept()
    concept["shots"][0]["source"] = "DREAM"
    warnings = shootgen.validate_concept(concept, LOCATION_NAMES)
    assert any("source" in w for w in warnings)


def test_validate_warns_on_ai_shot_with_unknown_tool():
    shots = [{"n": 1, "type": "BROLL", "source": "AI", "tool": "SORA",
              "location": "garage", "desc": "d", "prompt": "p"}]
    warnings = shootgen.validate_concept(make_concept(shots=shots), LOCATION_NAMES)
    assert any("tool" in w for w in warnings)


def test_validate_warns_on_ai_shot_without_a_prompt():
    """An AI shot with no prompt is a slot nobody can act on."""
    shots = [{"n": 1, "type": "BROLL", "source": "AI", "tool": "VEO",
              "location": "garage", "desc": "d"}]
    warnings = shootgen.validate_concept(make_concept(shots=shots), LOCATION_NAMES)
    assert any("prompt" in w for w in warnings)


def test_validate_skips_cam_check_for_ai_shots():
    """cam names a physical body; an AI shot doesn't have one."""
    shots = [{"n": 1, "type": "BROLL", "source": "AI", "tool": "KLING",
              "location": "garage", "desc": "d", "prompt": "p"}]
    assert shootgen.validate_concept(make_concept(shots=shots), LOCATION_NAMES) == []


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


def test_validate_warns_on_invented_location_for_a_camera_shot():
    """A CAMERA shot must ground in a real room -- you can only film
    where you actually are, so a hallucinated room is flagged."""
    concept = make_concept()
    concept["shots"][0]["source"] = "CAMERA"
    concept["shots"][0]["location"] = "rooftop helipad"
    warnings = shootgen.validate_concept(concept, LOCATION_NAMES)
    assert any("rooftop helipad" in w for w in warnings)


def test_validate_allows_an_invented_location_for_an_ai_shot():
    """An AI shot invents/extends the scene, so an unlisted location is
    legal there -- this is what lets concepts range beyond one room."""
    concept = make_concept()
    concept["shots"][0] = {
        "n": 1, "type": "BROLL", "source": "AI", "tool": "RUNWAY",
        "location": "a rain-slicked alley at night",
        "desc": "the bike rolls out into the wet street",
        "prompt": "a superbike rolling into a neon-lit rain-slicked alley",
    }
    warnings = shootgen.validate_concept(concept, LOCATION_NAMES)
    assert not any("location" in w for w in warnings), warnings


def test_validate_warns_on_unknown_legacy_ai_tool():
    concept = make_concept(ai={"tool": "SORA", "technique": "x", "prompt": "y"})
    warnings = shootgen.validate_concept(concept, LOCATION_NAMES)
    assert any("tool" in w for w in warnings)


def test_validate_accepts_every_registered_platform():
    """The legal tool set is the shot.py registry, not a hardcoded
    pair -- a platform added there is legal here with no second edit."""
    from src import shot as shot_mod
    for tool in shot_mod.TOOLS:
        concept = make_concept(ai={"tool": tool.upper(), "technique": "t", "prompt": "p"})
        assert shootgen.validate_concept(concept, LOCATION_NAMES) == [], tool


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


def test_generate_concept_sends_attached_images_as_vision_parts(tmp_db, monkeypatch):
    """image_refs (bytes, mime_type) pairs from the Studio composer must
    actually reach the model as multimodal content, not just get
    mentioned in the text -- otherwise "ground this in the photo I
    attached" would silently do nothing."""
    from google.genai import types

    seen = {}

    def fake_generate_with_retry(client, model, contents):
        seen["contents"] = contents
        return response_for(make_concept())

    monkeypatch.setattr(shootgen, "generate_with_retry", fake_generate_with_retry)

    shootgen.generate_concept(
        brand="antihero", spark="someone at the door", client=None,
        gemini_client=None, db_path=tmp_db,
        image_refs=[(b"fake-jpeg-bytes", "image/jpeg")],
    )

    contents = seen["contents"]
    assert isinstance(contents, list)
    assert isinstance(contents[0], str)  # the text prompt comes first
    assert "someone at the door" in contents[0]
    assert isinstance(contents[1], types.Part)


def test_generate_concept_without_images_sends_a_plain_string(tmp_db, monkeypatch):
    """No attachments -- the call shape is unchanged from before this
    feature existed (a bare prompt string, not a one-item list)."""
    seen = {}

    def fake_generate_with_retry(client, model, contents):
        seen["contents"] = contents
        return response_for(make_concept())

    monkeypatch.setattr(shootgen, "generate_with_retry", fake_generate_with_retry)
    shootgen.generate_concept(brand="antihero", client=None, gemini_client=None, db_path=tmp_db)
    assert isinstance(seen["contents"], str)


def test_generate_concept_degrades_without_locations(tmp_path, capsys):
    """No described spaces means an ungrounded run with a stderr note,
    not a dead one -- the same contract reference_block keeps for a
    missing library. Grounding is an enhancement, never a gate."""
    empty = tmp_path / "empty.db"
    db.init_db(empty)
    preprod.init(empty)
    entities.init(empty)

    def fake_generate(*a, **kw):
        return response_for(make_concept())

    import unittest.mock
    with unittest.mock.patch.object(shootgen, "generate_with_retry", fake_generate):
        result = shootgen.generate_concept(
            brand="antihero", client=None, gemini_client=None, db_path=empty,
        )

    assert result["concept"]["title"] == "The Waiting"
    assert "ungrounded" in capsys.readouterr().err
    # every location the model used is unknown to an empty db -- that's
    # a visible warning, not a rejection
    assert any("location" in w for w in result["warnings"])


# ---------- stage one: ideas ----------

IDEAS_RESPONSE = json.dumps({"ideas": [
    {"title": f"Idea {n}", "hook": f"hook {n}", "logline": f"line {n}", "why": f"why {n}"}
    for n in range(8)
]})


def test_build_ideas_prompt_includes_locations_brand_and_count(tmp_db):
    locations = preprod.list_locations(path=tmp_db)
    prompt = shootgen.build_ideas_prompt(locations, "antihero", None, "a door", count=8)

    assert "hallway" in prompt and "garage" in prompt
    assert "ANTIHERO" in prompt
    assert "a door" in prompt
    assert "8" in prompt
    for placeholder in ("{locations}", "{brand}", "{client}", "{spark}", "{count}"):
        assert placeholder not in prompt


def test_parse_ideas_response_returns_all_ideas():
    ideas = shootgen.parse_ideas_response(IDEAS_RESPONSE)
    assert len(ideas) == 8
    assert ideas[0]["title"] == "Idea 0"


def test_parse_ideas_response_strips_fences():
    assert len(shootgen.parse_ideas_response(f"```json\n{IDEAS_RESPONSE}\n```")) == 8


def test_parse_ideas_response_rejects_an_idea_without_a_title():
    bad = json.dumps({"ideas": [{"hook": "h", "logline": "l"}]})
    with pytest.raises(ValueError, match="title"):
        shootgen.parse_ideas_response(bad)


def test_parse_ideas_response_rejects_an_empty_batch():
    with pytest.raises(ValueError, match="no ideas"):
        shootgen.parse_ideas_response(json.dumps({"ideas": []}))


def test_generate_concept_ideas_saves_them_all(tmp_db, monkeypatch):
    monkeypatch.setattr(shootgen, "generate_with_retry", lambda *a, **kw: IDEAS_RESPONSE)

    result = shootgen.generate_concept_ideas(
        brand="antihero", spark="a door", client=None,
        gemini_client=None, count=8, db_path=tmp_db,
    )

    assert len(result["concept_ids"]) == 8
    saved = preprod.list_concepts(path=tmp_db)
    assert len(saved) == 8
    assert all(c["has_shot_list"] is False for c in saved)
    assert all(c["brand"] == "antihero" for c in saved)


def test_generate_concept_ideas_makes_one_call_not_n(tmp_db, monkeypatch):
    """Eight ideas should cost one request, not eight."""
    calls = []
    monkeypatch.setattr(
        shootgen, "generate_with_retry",
        lambda *a, **kw: (calls.append(1), IDEAS_RESPONSE)[1],
    )
    shootgen.generate_concept_ideas(
        brand="antihero", client=None, gemini_client=None, count=8, db_path=tmp_db,
    )
    assert len(calls) == 1


def test_generate_concept_ideas_degrades_without_locations(tmp_path, capsys, monkeypatch):
    empty = tmp_path / "empty.db"
    db.init_db(empty)
    preprod.init(empty)
    monkeypatch.setattr(shootgen, "generate_with_retry", lambda *a, **kw: IDEAS_RESPONSE)

    result = shootgen.generate_concept_ideas(
        brand="antihero", client=None, gemini_client=None, db_path=empty,
    )
    assert len(result["ideas"]) == 8
    assert "ungrounded" in capsys.readouterr().err


# ---------- stage two: the shot list for a chosen idea ----------

PLAN_RESPONSE = json.dumps({"plan": {
    "duration": "12s",
    "shots": [
        {"n": 1, "type": "CHARACTER", "cam": "BMPCC", "location": "hallway",
         "desc": "low angle", "light": "practical"},
    ],
    "ai": {"tool": "KLING", "technique": "t", "prompt": "p"},
    "edit": "hard cuts",
    "grade": "crushed",
}})


def test_build_shotlist_prompt_includes_the_chosen_idea(tmp_db):
    locations = preprod.list_locations(path=tmp_db)
    concept = {"title": "Void Signal", "hook": "a thumb", "logline": "he waits"}
    prompt = shootgen.build_shotlist_prompt(locations, "antihero", None, concept)

    assert "Void Signal" in prompt and "a thumb" in prompt and "he waits" in prompt
    assert "hallway" in prompt
    for placeholder in ("{title}", "{hook}", "{logline}", "{locations}", "{brand}", "{client}"):
        assert placeholder not in prompt


def test_parse_plan_response_reads_the_plan():
    plan = shootgen.parse_plan_response(PLAN_RESPONSE)
    assert plan["duration"] == "12s"
    assert len(plan["shots"]) == 1


def test_parse_plan_response_rejects_a_plan_with_no_shots():
    with pytest.raises(ValueError, match="no shots"):
        shootgen.parse_plan_response(json.dumps({"plan": {"shots": []}}))


def test_generate_shot_list_fills_in_a_chosen_idea(tmp_db, monkeypatch):
    concept_id = preprod.save_concept(
        {"title": "Void Signal", "hook": "h", "logline": "l"},
        brand="antihero", path=tmp_db,
    )
    monkeypatch.setattr(shootgen, "generate_with_retry", lambda *a, **kw: PLAN_RESPONSE)

    result = shootgen.generate_shot_list(
        concept_id, gemini_client=None, db_path=tmp_db,
    )

    assert result["warnings"] == []
    saved = preprod.get_concept(concept_id, path=tmp_db)
    assert saved["has_shot_list"] is True
    assert saved["title"] == "Void Signal"  # the idea survived
    assert [loc["name"] for loc in saved["locations"]] == ["hallway"]


def test_generate_shot_list_validates_the_plan(tmp_db, monkeypatch):
    concept_id = preprod.save_concept({"title": "T"}, brand="antihero", path=tmp_db)
    bad = json.loads(PLAN_RESPONSE)
    bad["plan"]["shots"][0]["location"] = "rooftop helipad"
    monkeypatch.setattr(shootgen, "generate_with_retry", lambda *a, **kw: json.dumps(bad))

    result = shootgen.generate_shot_list(concept_id, gemini_client=None, db_path=tmp_db)

    assert any("rooftop helipad" in w for w in result["warnings"])
    assert preprod.get_concept(concept_id, path=tmp_db)["has_shot_list"] is True


def test_generate_shot_list_rejects_missing_concept(tmp_db):
    with pytest.raises(ValueError, match="no concept"):
        shootgen.generate_shot_list(999, gemini_client=None, db_path=tmp_db)


# ---------- POV camera toggle ----------

def test_prompt_offers_the_pov_camera_when_on(tmp_db):
    locations = preprod.list_locations(path=tmp_db)
    prompt = shootgen.build_concept_prompt(locations, "antihero", None, None, use_pov=True)
    assert "ACTION5" in prompt
    assert "{pov}" not in prompt


def test_prompt_withholds_the_pov_camera_when_off(tmp_db):
    locations = preprod.list_locations(path=tmp_db)
    prompt = shootgen.build_concept_prompt(locations, "antihero", None, None, use_pov=False)
    assert "ACTION5" not in prompt
    assert "BMPCC only" in prompt
    assert "{pov}" not in prompt


def test_shotlist_prompt_respects_the_pov_toggle(tmp_db):
    locations = preprod.list_locations(path=tmp_db)
    concept = {"title": "T", "hook": "h", "logline": "l"}
    off = shootgen.build_shotlist_prompt(locations, "antihero", None, concept, use_pov=False)
    assert "ACTION5" not in off
    on = shootgen.build_shotlist_prompt(locations, "antihero", None, concept, use_pov=True)
    assert "ACTION5" in on


def test_validate_rejects_the_pov_camera_when_it_is_off():
    """Prompts request, code enforces -- turning the camera off has to
    mean the shot list can't quietly use it anyway."""
    warnings = shootgen.validate_concept(make_concept(), LOCATION_NAMES, use_pov=False)
    assert any("ACTION5" in w for w in warnings)


def test_validate_allows_the_pov_camera_when_it_is_on():
    assert shootgen.validate_concept(make_concept(), LOCATION_NAMES, use_pov=True) == []


def test_generate_concept_threads_the_pov_setting_through(tmp_db, monkeypatch):
    seen = {}

    def fake(client, model, prompt):
        seen["prompt"] = prompt
        return response_for(make_concept(shots=[
            {"n": 1, "type": "CHARACTER", "cam": "BMPCC", "location": "hallway",
             "desc": "d", "light": "l"},
        ]))

    monkeypatch.setattr(shootgen, "generate_with_retry", fake)
    shootgen.generate_concept(
        brand="antihero", client=None, gemini_client=None, use_pov=False, db_path=tmp_db,
    )
    assert "ACTION5" not in seen["prompt"]


def test_generated_concept_keeps_its_warnings_in_the_database(tmp_db, monkeypatch):
    """The docs promise "saved, warnings attached" -- prove the second half."""
    bad = make_concept()
    bad["shots"][0]["location"] = "rooftop helipad"
    monkeypatch.setattr(shootgen, "generate_with_retry", lambda *a, **kw: response_for(bad))

    result = shootgen.generate_concept(
        brand="antihero", client=None, gemini_client=None, db_path=tmp_db,
    )
    stored = preprod.get_concept(result["concept_id"], path=tmp_db)["warnings"]
    assert any("rooftop helipad" in w for w in stored)


def test_shot_list_warnings_survive_too(tmp_db, monkeypatch):
    concept_id = preprod.save_concept({"title": "T"}, brand="antihero", path=tmp_db)
    bad = json.loads(PLAN_RESPONSE)
    bad["plan"]["shots"][0]["location"] = "rooftop helipad"
    monkeypatch.setattr(shootgen, "generate_with_retry", lambda *a, **kw: json.dumps(bad))

    shootgen.generate_shot_list(concept_id, gemini_client=None, db_path=tmp_db)
    stored = preprod.get_concept(concept_id, path=tmp_db)["warnings"]
    assert any("rooftop helipad" in w for w in stored)


def test_shot_list_inherits_the_concepts_pov_setting(tmp_db, monkeypatch):
    """
    Planning happens after generating, so the shot list must take the
    camera choice from the concept rather than defaulting it back on --
    otherwise you get ACTION5 shots for a shoot with no action cam, and
    validate_concept won't flag them either.
    """
    concept_id = preprod.save_concept(
        {"title": "T"}, brand="antihero", use_pov=False, path=tmp_db,
    )
    seen = {}

    def fake(client, model, prompt):
        seen["prompt"] = prompt
        return PLAN_RESPONSE

    monkeypatch.setattr(shootgen, "generate_with_retry", fake)
    shootgen.generate_shot_list(concept_id, gemini_client=None, db_path=tmp_db)
    assert "ACTION5" not in seen["prompt"]
