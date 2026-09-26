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

from src import entities, preprod, shootgen


@pytest.fixture
def tmp_db(pg):
    path = pg
    preprod.init(path)
    entities.init(path)
    preprod.add_location("hallway", {"space": "narrow hallway"}, photo_count=2, dsn=path, account_id=None)
    preprod.add_location("garage", {"space": "cold garage"}, photo_count=3, dsn=path, account_id=None)
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
            {"n": 2, "type": "BROLL", "cam": "BMPCC", "location": "garage",
             "desc": "the handle turning, held close", "light": "spill under the door"},
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
    assert "ROUGH CHANNEL DIRECTION" in text
    assert "always take priority" in text


def test_load_brand_returns_zeropage_block():
    text = shootgen.load_brand("zeropage")
    assert "ZERO PAGE" in text
    assert "client" in text.lower()


def test_load_brand_rejects_unknown_brand():
    with pytest.raises(ValueError, match="brand must be one of"):
        shootgen.load_brand("nonsense")


# ---------- prompt ----------

def test_build_concept_prompt_includes_locations_and_brand(tmp_db):
    locations = preprod.list_locations(dsn=tmp_db, account_id=None)
    prompt = shootgen.build_concept_prompt(locations, "antihero", None, "someone at the door")

    assert "hallway" in prompt and "garage" in prompt
    assert "ANTIHERO" in prompt
    assert "someone at the door" in prompt
    for placeholder in ("{locations}", "{brand}", "{client}", "{spark}"):
        assert placeholder not in prompt


def test_run_specific_inputs_outrank_the_channel_note(tmp_db):
    locations = preprod.list_locations(dsn=tmp_db, account_id=None)
    prompt = shootgen.build_concept_prompt(
        locations, "antihero", None, "a bright daytime family comedy")

    assert prompt.index("a bright daytime family comedy") < prompt.index(
        "CHANNEL DIRECTION")
    assert "idea and attached images win" in prompt


def test_build_concept_prompt_without_spark_or_client(tmp_db):
    locations = preprod.list_locations(dsn=tmp_db, account_id=None)
    prompt = shootgen.build_concept_prompt(locations, "antihero", None, None)
    assert "{spark}" not in prompt and "{client}" not in prompt


@pytest.mark.xfail(reason="image_refs visual-note support not implemented yet in build_concept_prompt", strict=False)
def test_build_concept_prompt_notes_attached_images(tmp_db):
    """Ad hoc references from the Studio composer get a plain-language
    note in the prompt so the model treats the attached image parts as
    grounding, not decoration -- separate from the Workflow library's
    `{references}` block."""
    locations = preprod.list_locations(dsn=tmp_db, account_id=None)
    prompt = shootgen.build_concept_prompt(locations, "antihero", None, None,
                                           image_ref_count=2)
    assert "{visual_refs}" not in prompt
    assert "2 images attached" in prompt


@pytest.mark.xfail(reason="image_refs visual-note support not implemented yet in build_concept_prompt", strict=False)
def test_build_concept_prompt_omits_the_visual_note_by_default(tmp_db):
    locations = preprod.list_locations(dsn=tmp_db, account_id=None)
    prompt = shootgen.build_concept_prompt(locations, "antihero", None, None)
    assert "{visual_refs}" not in prompt
    assert "attached below this prompt" not in prompt


# ---------- location lock: a deliberate single-location run vs a shortage ----------

def test_location_variety_note_pushes_variety_by_default_with_few_rooms():
    note = shootgen.location_variety_note([{"name": "garage"}])
    assert "VARIETY NOTE" in note
    assert "LOCATION LOCK" not in note


def test_location_variety_note_locked_stops_pushing_variety():
    note = shootgen.location_variety_note([{"name": "garage"}], lock=True)
    assert "LOCATION LOCK" in note
    assert "VARIETY NOTE" not in note
    assert "deliberate choice" in note


def test_location_variety_note_locked_wins_even_with_plenty_of_rooms():
    """Lock is an explicit override, not just a fallback for scarcity -- it
    should say its piece regardless of how many rooms are on file."""
    many = [{"name": f"room{i}"} for i in range(5)]
    assert shootgen.location_variety_note(many) == ""
    assert "LOCATION LOCK" in shootgen.location_variety_note(many, lock=True)


def test_apply_location_lock_filters_to_the_named_location(tmp_db):
    locations = preprod.list_locations(dsn=tmp_db, account_id=None)
    filtered, locked = shootgen._apply_location_lock(locations, ["garage"])
    assert locked is True
    assert [loc["name"] for loc in filtered] == ["garage"]


def test_apply_location_lock_is_case_insensitive(tmp_db):
    locations = preprod.list_locations(dsn=tmp_db, account_id=None)
    filtered, locked = shootgen._apply_location_lock(locations, ["GARAGE"])
    assert locked is True
    assert [loc["name"] for loc in filtered] == ["garage"]


def test_apply_location_lock_none_means_use_everything(tmp_db):
    locations = preprod.list_locations(dsn=tmp_db, account_id=None)
    filtered, locked = shootgen._apply_location_lock(locations, None)
    assert locked is False
    assert filtered == locations


def test_apply_location_lock_falls_back_to_everything_on_no_match(tmp_db, capsys):
    locations = preprod.list_locations(dsn=tmp_db, account_id=None)
    filtered, locked = shootgen._apply_location_lock(locations, ["basement"])
    assert locked is False
    assert filtered == locations
    assert "none of" in capsys.readouterr().err


def test_build_concept_prompt_lock_location_reaches_the_prompt(tmp_db):
    locations = [loc for loc in preprod.list_locations(dsn=tmp_db, account_id=None) if loc["name"] == "garage"]
    prompt = shootgen.build_concept_prompt(locations, "antihero", None, None,
                                           lock_location=True)
    assert "LOCATION LOCK" in prompt


def test_build_ideas_prompt_lock_location_reaches_the_prompt(tmp_db):
    locations = [loc for loc in preprod.list_locations(dsn=tmp_db, account_id=None) if loc["name"] == "garage"]
    prompt = shootgen.build_ideas_prompt(locations, "antihero", None, None,
                                         lock_location=True)
    assert "LOCATION LOCK" in prompt


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


def test_validate_accepts_every_platform_fal_renders():
    """The legal tool set is the shot.py registry narrowed to what fal
    renders (2026-09-26) -- a platform added to both is legal here with no
    second edit, and a retired one (RUNWAY) or an unrendered dialect
    (OPENART) is flagged."""
    from src import fal
    for platform in fal.PLATFORM_MODELS:
        concept = make_concept(ai={"tool": platform.upper(), "technique": "t", "prompt": "p"})
        assert shootgen.validate_concept(concept, LOCATION_NAMES) == [], platform
    for not_rendered in ("RUNWAY", "HIGGSFIELD", "OPENART"):
        concept = make_concept(ai={"tool": not_rendered, "technique": "t", "prompt": "p"})
        assert shootgen.validate_concept(concept, LOCATION_NAMES), not_rendered


def test_validate_rejects_empty_shot_list():
    warnings = shootgen.validate_concept(make_concept(shots=[]), LOCATION_NAMES)
    assert any("no shots" in w for w in warnings)


def test_validate_allows_a_concept_with_no_ai_slot():
    concept = make_concept()
    del concept["ai"]
    assert shootgen.validate_concept(concept, LOCATION_NAMES) == []


# ---------- scene bible: cross-shot consistency for independently-rendered AI shots ----------

def test_derive_scene_bible_combines_title_logline_grade():
    bible = shootgen.derive_scene_bible("The Waiting", "He waits for someone.", "crushed shadows")
    assert bible == "Scene: The Waiting -- He waits for someone. -- Grade: crushed shadows"


def test_derive_scene_bible_skips_missing_parts():
    assert shootgen.derive_scene_bible(None, None, None) == ""
    assert shootgen.derive_scene_bible("Only Title") == "Scene: Only Title"


def test_apply_scene_bible_prepends_only_to_ai_shots():
    shots = [
        {"source": "CAMERA", "prompt": "irrelevant"},
        {"source": "AI", "prompt": "a door handle turning in the dark"},
    ]
    result = shootgen.apply_scene_bible(shots, "Scene: The Waiting")
    assert result[0]["prompt"] == "irrelevant"  # CAMERA shot untouched
    assert result[1]["prompt"] == "Scene: The Waiting. a door handle turning in the dark"


def test_apply_scene_bible_does_not_double_prepend():
    shots = [{"source": "AI", "prompt": "Scene: The Waiting. already anchored"}]
    result = shootgen.apply_scene_bible(shots, "Scene: The Waiting")
    assert result[0]["prompt"] == "Scene: The Waiting. already anchored"


def test_apply_scene_bible_is_a_noop_without_a_bible():
    shots = [{"source": "AI", "prompt": "unchanged"}]
    assert shootgen.apply_scene_bible(shots, "")[0]["prompt"] == "unchanged"


# ---------- stage one: ideas ----------

IDEAS_RESPONSE = json.dumps({"ideas": [
    {"title": f"Idea {n}", "hook": f"hook {n}", "logline": f"line {n}", "why": f"why {n}"}
    for n in range(8)
]})


def test_build_ideas_prompt_includes_locations_brand_and_count(tmp_db):
    locations = preprod.list_locations(dsn=tmp_db, account_id=None)
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
    saved = preprod.list_concepts(dsn=tmp_db, account_id=None)
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


def test_generate_concept_ideas_degrades_without_locations(pg, capsys, monkeypatch):
    empty = pg
    preprod.init(empty)
    monkeypatch.setattr(shootgen, "generate_with_retry", lambda *a, **kw: IDEAS_RESPONSE)

    result = shootgen.generate_concept_ideas(
        brand="antihero", client=None, gemini_client=None, db_path=empty,
    )
    assert len(result["ideas"]) == 8
    assert "ungrounded" in capsys.readouterr().err


def test_generate_concept_ideas_only_locations_locks_the_prompt(tmp_db, monkeypatch):
    seen = {}

    def fake_generate(client, model, prompt, **_):
        seen["prompt"] = prompt
        return IDEAS_RESPONSE

    monkeypatch.setattr(shootgen, "generate_with_retry", fake_generate)
    shootgen.generate_concept_ideas(
        brand="antihero", client=None, gemini_client=None, db_path=tmp_db,
        only_locations=["garage"],
    )
    assert "LOCATION LOCK" in seen["prompt"]
    assert "hallway" not in seen["prompt"]
    assert "garage" in seen["prompt"]


def test_generate_concept_ideas_without_only_locations_uses_everything(tmp_db, monkeypatch):
    seen = {}

    def fake_generate(client, model, prompt, **_):
        seen["prompt"] = prompt
        return IDEAS_RESPONSE

    monkeypatch.setattr(shootgen, "generate_with_retry", fake_generate)
    shootgen.generate_concept_ideas(
        brand="antihero", client=None, gemini_client=None, db_path=tmp_db,
    )
    assert "hallway" in seen["prompt"] and "garage" in seen["prompt"]
    assert "LOCATION LOCK" not in seen["prompt"]


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
    locations = preprod.list_locations(dsn=tmp_db, account_id=None)
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


SCENE_RESPONSE = ('{"title": "Rewritten", "hook": "a hand", "logline": "he waits", '
                  '"brief": "Ultra-realistic grounded video in 9:16. The scene."}')


def test_write_scene_fills_in_a_chosen_idea(tmp_db, monkeypatch):
    """Stage two writes the idea's ONE scene prompt (2026-08-26). The
    picked title/hook/logline are the label and must survive intact."""
    concept_id = preprod.save_concept(
        {"title": "Void Signal", "hook": "h", "logline": "l"},
        brand="antihero", dsn=tmp_db,
    
        account_id=None,)
    monkeypatch.setattr(shootgen, "generate_with_retry", lambda *a, **kw: SCENE_RESPONSE)

    result = shootgen.write_scene_for_concept(
        concept_id, gemini_client=None, db_path=tmp_db,
    )

    assert result["warnings"] == []
    saved = preprod.get_concept(concept_id, dsn=tmp_db, account_id=None)
    assert saved["has_shot_list"] is True
    assert len(saved["shots"]) == 1
    assert saved["shots"][0]["prompt"].startswith("Ultra-realistic grounded")
    assert saved["title"] == "Void Signal"      # the pick survived
    assert saved["hook"] == "h" and saved["logline"] == "l"


def test_write_scene_seeds_the_prompt_with_the_idea(tmp_db, monkeypatch):
    """The idea is the spark for its own scene, or stage two would write
    something unrelated to what was picked."""
    concept_id = preprod.save_concept(
        {"title": "Void Signal", "hook": "a hand on the handle", "logline": "he waits"},
        brand="antihero", dsn=tmp_db, account_id=None)
    seen = {}

    def fake(client, model, contents, **_):
        seen["prompt"] = contents
        return SCENE_RESPONSE

    monkeypatch.setattr(shootgen, "generate_with_retry", fake)
    shootgen.write_scene_for_concept(concept_id, gemini_client=None, db_path=tmp_db)
    assert "Void Signal" in seen["prompt"]
    assert "a hand on the handle" in seen["prompt"]


def test_write_scene_validates_and_still_saves(tmp_db, monkeypatch):
    """Prompts request, code advises: a warning never loses the scene."""
    concept_id = preprod.save_concept({"title": "T"}, brand="zeropage", dsn=tmp_db, account_id=None)
    monkeypatch.setattr(shootgen, "generate_with_retry", lambda *a, **kw: SCENE_RESPONSE)

    result = shootgen.write_scene_for_concept(
        concept_id, gemini_client=None, db_path=tmp_db, tool="RUNWAY")

    assert any("RUNWAY" in w for w in result["warnings"])   # retired 2026-09-26
    assert preprod.get_concept(concept_id, dsn=tmp_db, account_id=None)["has_shot_list"] is True


def test_write_scene_rejects_a_missing_concept(tmp_db):
    with pytest.raises(ValueError):
        shootgen.write_scene_for_concept(999, gemini_client=None, db_path=tmp_db)

# ---------- POV camera toggle ----------

def test_prompt_offers_the_pov_camera_when_on(tmp_db):
    locations = preprod.list_locations(dsn=tmp_db, account_id=None)
    prompt = shootgen.build_concept_prompt(locations, "antihero", None, None, use_pov=True)
    assert "ACTION5" in prompt
    assert "{pov}" not in prompt


def test_prompt_withholds_the_pov_camera_when_off(tmp_db):
    locations = preprod.list_locations(dsn=tmp_db, account_id=None)
    prompt = shootgen.build_concept_prompt(locations, "antihero", None, None, use_pov=False)
    assert "ACTION5" not in prompt
    assert "BMPCC only" in prompt
    assert "{pov}" not in prompt


def test_shotlist_prompt_respects_the_pov_toggle(tmp_db):
    locations = preprod.list_locations(dsn=tmp_db, account_id=None)
    concept = {"title": "T", "hook": "h", "logline": "l"}
    off = shootgen.build_shotlist_prompt(locations, "antihero", None, concept, use_pov=False)
    assert "ACTION5" not in off
    on = shootgen.build_shotlist_prompt(locations, "antihero", None, concept, use_pov=True)
    assert "ACTION5" in on


def make_pov_concept():
    """make_concept with shot 2 on the action cam -- only legal when
    the POV toggle is on."""
    concept = make_concept()
    concept["shots"][1]["cam"] = "ACTION5"
    concept["shots"][1]["desc"] = "POV of the handle turning"
    return concept


def test_validate_rejects_the_pov_camera_when_it_is_off():
    """Prompts request, code enforces -- turning the camera off has to
    mean the shot list can't quietly use it anyway."""
    warnings = shootgen.validate_concept(make_pov_concept(), LOCATION_NAMES,
                                         use_pov=False)
    assert any("ACTION5" in w for w in warnings)


def test_validate_rejects_the_pov_camera_by_default():
    """POV is off unless asked for: with no use_pov argument the
    validator treats ACTION5 as an unavailable camera."""
    warnings = shootgen.validate_concept(make_pov_concept(), LOCATION_NAMES)
    assert any("ACTION5" in w for w in warnings)


def test_validate_allows_the_pov_camera_when_it_is_on():
    assert shootgen.validate_concept(make_pov_concept(), LOCATION_NAMES,
                                     use_pov=True) == []


def test_scene_warnings_survive_on_the_row(tmp_db, monkeypatch):
    """Warnings are stored on the concept, not just returned."""
    concept_id = preprod.save_concept({"title": "T"}, brand="zeropage", dsn=tmp_db, account_id=None)
    monkeypatch.setattr(shootgen, "generate_with_retry", lambda *a, **kw: SCENE_RESPONSE)
    shootgen.write_scene_for_concept(concept_id, gemini_client=None,
                                     db_path=tmp_db, tool="RUNWAY")
    assert preprod.get_concept(concept_id, dsn=tmp_db, account_id=None)["warnings"]

# ---------- director_prompt: the OpenArt Director rendering ----------
# Pure text composition -- no model call, so these run in microseconds.

def test_director_prompt_weaves_shot_and_story_into_prose():
    concept = make_concept()
    text = shootgen.director_prompt(concept["shots"][0], concept)
    assert "low angle, he steps into frame" in text
    assert "The scene is hallway." in text
    assert "Light: overhead practical." in text
    assert "The Waiting — He waits for someone who never knocks." in text
    assert "Grade: crushed shadows, one warm accent." in text


def test_director_prompt_gives_shot_one_the_hook():
    """Shot 1's whole job is landing the hook; later shots don't repeat it."""
    concept = make_concept()
    first = shootgen.director_prompt(concept["shots"][0], concept)
    second = shootgen.director_prompt(concept["shots"][1], concept)
    assert "a hand already on the door handle" in first
    assert "a hand already on the door handle" not in second


def test_director_prompt_falls_back_to_the_ai_prompt_when_no_desc():
    text = shootgen.director_prompt(
        {"n": 2, "prompt": "a door handle turning in the dark"}, {})
    assert text.startswith("a door handle turning in the dark.")


def test_director_prompt_reads_saved_rows_too():
    """Saved concepts carry grade_note, generation-time dicts carry
    grade -- both sides of save render the same."""
    text = shootgen.director_prompt(
        {"n": 1, "desc": "d"}, {"grade_note": "one warm accent"})
    assert "Grade: one warm accent." in text


def test_director_prompt_skips_what_the_shot_does_not_carry():
    assert shootgen.director_prompt({"n": 3, "desc": "just this"}, {}) == "just this."
