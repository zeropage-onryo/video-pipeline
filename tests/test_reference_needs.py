"""The Reference Map (2026-09-24): one scene -> the visual questions in
it, a face never hunted on the web, and a deterministic map when the
planner cannot answer."""
import json
import re

from src import reference_needs, spend


class _Resp:
    def __init__(self, text):
        self.text = text


class _Client:
    """Every fake client in this suite implements this and nothing else."""
    def __init__(self, text):
        self.text, self.calls = text, []
        self.models = self

    def generate_content(self, model=None, contents=None, **kw):
        self.calls.append((model, contents))
        return _Resp(self.text)


SCENE = ("A nurse walks the length of a flooded hospital corridor at night, "
         "counting doors. The last one is already open.")


def _answer(needs):
    return json.dumps({"needs": needs})


def test_the_map_is_parsed_and_a_face_is_never_a_web_need():
    client = _Client(_answer([
        {"role": "place", "query": "flooded hospital corridor night", "want": "the water line", "specified": True},
        {"role": "face", "query": "tired nurse portrait", "want": "who she is", "specified": False},
        {"role": "light", "query": "green fluorescent tube reflections wet floor", "specified": False},
    ]))
    result = reference_needs.plan(SCENE, brand="zeropage", client=client, model="m")
    assert result["ok"] and result["planner"] == "model"
    roles = [n["role"] for n in result["needs"]]
    assert roles == ["place", "face", "light"]
    face = [n for n in result["needs"] if n["role"] == "face"][0]
    assert face["source"] == "elements"
    assert [n["role"] for n in reference_needs.web_needs(result["needs"])] == ["place", "light"]


def test_open_questions_are_hunted_before_the_ones_the_scene_answers():
    needs = [reference_needs._need("place", "corridor", specified=True),
             reference_needs._need("light", "tube glow", specified=False)]
    assert [n["role"] for n in reference_needs.open_needs(needs)] == ["light", "place"]


def test_an_unknown_role_a_repeat_and_a_flood_are_all_dropped():
    rows = [{"role": "catering", "query": "sandwiches"},
            {"role": "place", "query": "wet corridor"},
            {"role": "place", "query": "Wet Corridor"}]
    rows += [{"role": "prop", "query": f"thing {i}"} for i in range(10)]
    needs = reference_needs.parse(_answer(rows))
    assert "catering" not in [n["role"] for n in needs]
    assert len(needs) == reference_needs.MAX_NEEDS
    assert [n["query"] for n in needs].count("wet corridor") == 1


def test_a_query_written_as_a_sentence_is_cut_back_to_surfaces():
    long = ("she realises the door was never locked and that the water has "
            "been rising since the beginning of the night shift somehow")
    [need] = reference_needs.parse(_answer([{"role": "mood", "query": long}]))
    assert len(need["query"].split()) <= reference_needs.MAX_QUERY_WORDS
    assert "realises" not in need["query"]


def test_an_unreadable_answer_falls_back_to_the_split_and_says_so():
    result = reference_needs.plan(SCENE, client=_Client("not json at all"), model="m")
    assert result["ok"] is False and result["planner"] == "split"
    assert [n["role"] for n in result["needs"]] == ["mood"]
    assert result["needs"][0]["query"]


def test_a_planner_that_raises_never_takes_the_pass_with_it():
    class Boom(_Client):
        def generate_content(self, **kw):
            raise RuntimeError("503")

    result = reference_needs.plan(SCENE, client=Boom(""), model="m")
    assert result["planner"] == "split" and result["needs"]
    assert "failed" in result["note"]


def test_empty_text_asks_for_nothing():
    result = reference_needs.plan("   ", client=_Client(_answer([])), model="m")
    assert result["needs"] == [] and result["ok"] is False


def test_anti_references_read_a_brand_file_and_skip_comments(tmp_path, monkeypatch):
    monkeypatch.setattr(reference_needs, "PROMPTS_DIR", tmp_path)
    (tmp_path / "anti_references_zeropage.txt").write_text(
        "# what it must not be\nstock office photography\n\nbeige prestige drama\n")
    assert reference_needs.anti_references("zeropage") == [
        "stock office photography", "beige prestige drama"]
    assert reference_needs.anti_references("antihero") == []


def test_the_prompt_fills_with_no_placeholder_left():
    """The JSON shape the answer must take stays in the prompt (its braces
    are doubled in the template); what must NOT survive is a {name} the
    format call was supposed to fill."""
    text = reference_needs.build_prompt(SCENE, look="GRADE sodium and damp.",
                                        anti=["beige prestige drama"])
    assert "flooded hospital corridor" in text and "beige prestige drama" in text
    assert "GRADE sodium and damp." in text
    assert not re.findall(r"\{(scene|look|anti|roles|count)\}", text)


def test_the_stage_is_in_the_closed_set_so_the_meter_keeps_it():
    assert "reference_map" in spend.STAGES and "reference_check" in spend.STAGES
