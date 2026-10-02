"""
Scene-brief mode: one cohesive whole-scene prompt in the proven skeleton,
stored per brand and pasteable into a video model. Generation is mocked;
the prompt skeleton, storage, and the mode=scene route run for real.
"""
import pytest
from fastapi.testclient import TestClient

import app.main as app_main
from app.main import app
from src import inspiration, preprod, shootgen, winners

client = TestClient(app)


@pytest.fixture
def tmp_db(pg, monkeypatch):
    path = pg
    preprod.init(path)
    inspiration.init(path)
    winners.init(path)
    monkeypatch.setenv("DATABASE_URL", path)
    return path


def test_save_list_delete_scene_briefs(tmp_db):
    a = preprod.save_scene_brief("antihero", "Portal Room", "the brief text",
                                 spark="x", dsn=tmp_db, account_id=None)
    preprod.save_scene_brief("zeropage", "Other", "zp brief", dsn=tmp_db, account_id=None)
    ah = preprod.list_scene_briefs(brand="antihero", dsn=tmp_db, account_id=None)
    assert len(ah) == 1 and ah[0]["title"] == "Portal Room"
    assert ah[0]["brief"] == "the brief text"
    preprod.delete_scene_brief(a, dsn=tmp_db, account_id=None)
    assert preprod.list_scene_briefs(brand="antihero", dsn=tmp_db, account_id=None) == []


def test_build_scene_brief_prompt_has_the_full_skeleton():
    p = shootgen.build_scene_brief_prompt("antihero")
    for marker in ("OPEN LINE", "STYLE", "BEATS", "SOUND", "AVOID", "9:16"):
        assert marker in p
    # the per-brand look (2026-09-05) replaces the "raw handheld, matte"
    # house style that flattened every reference carrying it
    assert "{look}" not in p and "ANTIHERO LOOK" in p
    assert "raw handheld, close wide-angle" not in p


def test_scene_brief_marks_brand_as_fallback_context():
    p = shootgen.build_scene_brief_prompt(
        "antihero", spark="a sunlit romantic comedy")
    assert p.index("a sunlit romantic comedy") < p.index("CHANNEL DIRECTION")
    assert "idea and attached images win" in p


def test_gold_standard_is_injected_into_the_scene_brief_prompt():
    p = shootgen.build_scene_brief_prompt("antihero")
    assert "GOLD-STANDARD EXAMPLE" in p and "match the SHAPE" in p
    assert "three-tier white cake" in p   # the exemplar itself is present
    assert "NEVER its subject, specific content or look" in p   # shape, not subject


# guards: retire_gold_standard -- the exemplar leaves the winners shelf
# (row AND chunks), nothing is seeded back, and only the exact note goes
def test_boot_retires_the_gold_standard_winner_and_seeds_nothing(tmp_db, monkeypatch):
    from src import rag
    dropped = []

    class Store:
        def close(self):
            pass

    monkeypatch.setattr(rag, "connect", lambda *a, **k: Store())
    monkeypatch.setattr(rag, "delete_source", lambda conn, source: dropped.append(source) or 4)
    old = winners.add("runway", "a giant monster on the bed",
                      note=app_main.GOLD_STANDARD_NOTE, dsn=tmp_db)
    with app_main.db.connect(tmp_db) as conn:
        conn.execute("UPDATE winning_prompts SET rag_source = %s, ingested = 1 WHERE id = %s",
                     (f"winning_prompts/entry-{old}.txt", old))
    mine = winners.add("ltx", "a prompt a person taught", note="gold standard for my ad",
                       dsn=tmp_db)

    app_main.retire_gold_standard()
    app_main.retire_gold_standard()          # a second boot finds nothing to do

    notes = {w["id"]: w["note"] for w in winners.list_all(dsn=tmp_db)}
    assert old not in notes and mine in notes
    assert app_main.GOLD_STANDARD_NOTE not in notes.values()     # nothing seeded back
    assert dropped == [f"winning_prompts/entry-{old}.txt"]


def test_realism_recipe_is_in_the_shot_prompts():
    from pathlib import Path
    prompts = Path(shootgen.PROMPTS_DIR)
    for f in ("concept_prompt.txt", "shotlist_prompt.txt"):
        text = (prompts / f).read_text()
        assert "RENDER REAL, NOT GLOSSY" in text
        assert "no glossy CGI" in text


# ---------- a concept IS one scene and one prompt (2026-08-26) ----------

def test_scene_concept_saves_exactly_one_prompt(pg, monkeypatch):
    """The whole point of the restructure: one concept, one shot, one
    paste-ready prompt -- the thing generated, graded, and rendered."""
    from src import entities, preprod, shootgen
    path = pg
    preprod.init(path)
    entities.init(path)
    monkeypatch.setattr(
        shootgen, "generate_with_retry",
        lambda client, model, contents, **_:
        '{"title": "Concrete Camouflage", "brief": "Ultra-realistic grounded video in 9:16…"}')

    result = shootgen.generate_scene_concept(
        brand="antihero", spark="a breathing pillar", gemini_client=object(),
        db_path=path)

    saved = preprod.get_concept(result["concept_id"], dsn=path, account_id=None)
    assert saved["title"] == "Concrete Camouflage"
    assert len(saved["shots"]) == 1
    shot = saved["shots"][0]
    assert shot["source"] == "AI" and shot["n"] == 1
    assert shot["prompt"].startswith("Ultra-realistic grounded video")


def test_scene_concept_does_not_prepend_the_scene_bible(pg, monkeypatch):
    """The bible holds SEPARATE shots to one look. With one shot there is
    nothing to hold, and it would just be noise in the paste."""
    from src import entities, preprod, shootgen
    path = pg
    preprod.init(path)
    entities.init(path)
    monkeypatch.setattr(
        shootgen, "generate_with_retry",
        lambda client, model, contents, **_: '{"title": "T", "brief": "the prompt text"}')

    result = shootgen.generate_scene_concept(
        brand="antihero", gemini_client=object(), db_path=path)
    prompt = preprod.get_concept(result["concept_id"], dsn=path, account_id=None)["shots"][0]["prompt"]
    assert prompt == "the prompt text"
    assert not prompt.startswith("Scene:")


def test_scene_concept_validates_the_tool_per_brand(pg, monkeypatch):
    """Zero Page's tool allow-list still applies -- warnings advise, as
    everywhere else, and never block the save."""
    from src import entities, preprod, shootgen
    path = pg
    preprod.init(path)
    entities.init(path)
    monkeypatch.setattr(
        shootgen, "generate_with_retry",
        lambda client, model, contents, **_: '{"title": "T", "brief": "b"}')

    result = shootgen.generate_scene_concept(
        brand="zeropage", gemini_client=object(), db_path=path, tool="RUNWAY")
    assert result["warnings"]                       # RUNWAY is retired (2026-09-26)
    assert preprod.get_concept(result["concept_id"], dsn=path, account_id=None) is not None
