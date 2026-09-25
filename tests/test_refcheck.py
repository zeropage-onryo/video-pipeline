"""The clean-frame gate (2026-09-24): somebody looks at the picture.

The failure this exists for is scout_bin_images.md — six YouTube
monetisation thumbnails banked behind a Zero Page scene, every automatic
guard green, found only by opening the files.
"""
import json
import re

from src import refcheck


class _Resp:
    def __init__(self, text):
        self.text = text


class _Client:
    def __init__(self, *texts):
        self.texts, self.calls = list(texts), []
        self.models = self

    def generate_content(self, model=None, contents=None, **kw):
        self.calls.append(contents)
        return _Resp(self.texts.pop(0) if self.texts else "")


def _frames(rows):
    return json.dumps({"frames": rows})


def _images(n, start=1):
    return [{"id": f"c{i}", "bytes": b"\xff\xd8\xff-jpeg-ish"} for i in range(start, start + n)]


def test_a_kept_frame_carries_its_caption_and_reason():
    client = _Client(_frames([
        {"id": "c1", "keep": True, "flags": [], "why": "wet tiled corridor, sodium glow",
         "caption": "the water line and the light on it"}]))
    result = refcheck.check(_images(1), {"role": "place", "want": "the corridor"},
                            client=client, model="m", look="GRADE sodium.", anti=[])
    assert result["ok"] and result["checked"]
    [verdict] = result["verdicts"]
    assert verdict["keep"] and verdict["caption"] == "the water line and the light on it"


def test_a_hard_flag_rejects_the_frame_whatever_the_model_concluded():
    """The thumbnail case: a model can be talked into liking one; code cannot."""
    client = _Client(_frames([
        {"id": "c1", "keep": True, "flags": ["text_overlay", "logo"],
         "why": "great energy", "caption": "hero shot"}]))
    result = refcheck.check(_images(1), client=client, model="m")
    [verdict] = result["verdicts"]
    assert verdict["keep"] is False
    assert "text_overlay" in verdict["why"] and "not a clean frame" in verdict["why"]
    assert result["ok"] is False


def test_every_hard_flag_is_a_flag_the_model_is_offered():
    assert set(refcheck.HARD_FLAGS) <= set(refcheck.FLAGS)


def test_a_frame_the_answer_skipped_is_not_kept_by_default():
    client = _Client(_frames([{"id": "c1", "keep": True, "flags": [], "why": "", "caption": ""}]))
    result = refcheck.check(_images(2), client=client, model="m")
    kept = {v["id"]: v["keep"] for v in result["verdicts"]}
    assert kept == {"c1": True, "c2": False}
    assert [v["why"] for v in result["verdicts"] if v["id"] == "c2"] == ["not judged"]


def test_an_id_nobody_sent_is_dropped_rather_than_trusted():
    client = _Client(_frames([
        {"id": "c1", "keep": True, "flags": [], "why": "ok", "caption": "a"},
        {"id": "invented", "keep": True, "flags": [], "why": "ok", "caption": "b"}]))
    result = refcheck.check(_images(1), client=client, model="m")
    assert [v["id"] for v in result["verdicts"]] == ["c1"]


def test_the_frames_are_sent_in_batches_each_labelled_by_its_id():
    n = refcheck.MAX_BATCH + 2
    client = _Client(_frames([]), _frames([]))
    refcheck.check(_images(n), client=client, model="m")
    assert len(client.calls) == 2
    first = client.calls[0]
    assert first[0] == "FRAME c1"
    assert first[-1].startswith("You are looking at")
    assert sum(1 for part in first if isinstance(part, str) and part.startswith("FRAME ")) \
        == refcheck.MAX_BATCH


def test_a_batch_that_could_not_be_looked_at_says_so_instead_of_keeping():
    class Boom(_Client):
        def generate_content(self, **kw):
            raise RuntimeError("503")

    result = refcheck.check(_images(2), client=Boom(), model="m")
    assert result["checked"] is False and result["ok"] is False
    assert all(v["keep"] is False for v in result["verdicts"])
    assert "could not be looked at" in result["note"]


def test_no_client_is_an_honest_unchecked_answer_not_a_raise(monkeypatch):
    from src import gemini_utils

    def no_key(*a, **kw):
        raise RuntimeError("no GEMINI_API_KEY")

    monkeypatch.setattr(gemini_utils, "client_for", no_key)
    result = refcheck.check(_images(1))
    assert result["ok"] is False and result["checked"] is False
    assert result["verdicts"][0]["why"] == "no model client"


def test_unreadable_json_keeps_nothing():
    result = refcheck.check(_images(2), client=_Client("sorry, I can't"), model="m")
    assert [v["keep"] for v in result["verdicts"]] == [False, False]


def test_screen_fetches_checks_and_hands_back_the_survivors():
    candidates = [{"id": "c1", "image_url": "https://x/1.jpg", "source_url": "https://x/p1"},
                  {"id": "c2", "image_url": "https://x/2.jpg", "source_url": "https://x/p2"}]
    client = _Client(_frames([
        {"id": "c1", "keep": True, "flags": [], "why": "clean", "caption": "the doorway"},
        {"id": "c2", "keep": False, "flags": ["stock_gloss"], "why": "sellable", "caption": ""}]))
    result = refcheck.screen(candidates, {"role": "place", "query": "doorway"},
                             fetch=lambda url: b"\xff\xd8\xff bytes",
                             client=client, model="m")
    assert [c["id"] for c in result["keepers"]] == ["c1"]
    assert result["keepers"][0]["kept_for"] == "the doorway"
    assert result["keepers"][0]["role"] == "place"
    assert [c["id"] for c in result["rejected"]] == ["c2"]
    assert result["rejected"][0]["flags"] == ["stock_gloss"]


def test_screen_with_nothing_fetchable_is_empty_and_says_which_half_failed():
    result = refcheck.screen([{"id": "c1", "image_url": "https://x/1.jpg"}],
                             fetch=lambda url: None, client=_Client(), model="m")
    assert result["keepers"] == [] and result["checked"] is False
    assert result["note"] == "no candidate image could be fetched"


def test_the_prompt_fills_with_no_placeholder_left():
    text = refcheck.build_prompt({"role": "light", "want": "sodium glow", "query": "sodium"},
                                 look="GRADE sodium and damp.", anti=["beige prestige drama"],
                                 count=3)
    assert "3 frame(s)" in text and "beige prestige drama" in text
    assert "watermark" in text and "sodium glow" in text
    assert not re.findall(r"\{(count|role|want|query|look|anti|flags|hard)\}", text)
