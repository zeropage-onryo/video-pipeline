"""
Tests for src/story_judge.py -- the independent second grader and the
real-engagement virality signal.

virality_signal is pure arithmetic (no network); the judge_spark tests
lean on conftest's no_network fixture to prove it degrades to
{"ok": False, ...} rather than raising when RAG or the model call can't
be reached, which is the only contract scout.scout() relies on.
"""
from src import story_judge

# ---------- virality_signal: pure arithmetic, no network ----------

def test_virality_signal_matches_by_exact_url():
    candidate = {"spark": "a routine performed wrong", "evidence": "",
                 "sources": ["https://example.com/a"]}
    signals = [{"detail": "some viral video", "url": "https://example.com/a",
               "metric": "45,000 views"}]

    result = story_judge.virality_signal(candidate, signals)

    assert result["score"] > 0
    assert "45,000 views" in result["detail"]


def test_virality_signal_falls_back_to_token_overlap():
    candidate = {"spark": "the last check before leaving the garage light on",
                 "evidence": "a routine broken at the door", "sources": []}
    signals = [{"detail": "leaving the garage light on every single night",
               "url": "https://example.com/b", "metric": "9,000 upvotes"}]

    result = story_judge.virality_signal(candidate, signals)

    assert result["score"] > 0
    assert "upvotes" in result["detail"]


def test_virality_signal_no_match_is_zero_not_an_error():
    candidate = {"spark": "a totally unrelated idea", "evidence": "", "sources": []}
    signals = [{"detail": "something else entirely", "url": "https://example.com/c",
               "metric": "9,000 upvotes"}]

    result = story_judge.virality_signal(candidate, signals)

    assert result == {"score": 0.0, "detail": "no measurable signal linked"}


def test_virality_signal_ignores_signals_with_no_parseable_metric():
    candidate = {"spark": "a routine performed wrong", "evidence": "",
                 "sources": ["https://example.com/a"]}
    signals = [{"detail": "no numbers here", "url": "https://example.com/a", "metric": ""}]

    result = story_judge.virality_signal(candidate, signals)

    assert result["score"] == 0.0


def test_virality_signal_scales_with_count():
    small = story_judge.virality_signal(
        {"spark": "x", "evidence": "", "sources": ["u"]},
        [{"detail": "d", "url": "u", "metric": "100 views"}])
    big = story_judge.virality_signal(
        {"spark": "x", "evidence": "", "sources": ["u"]},
        [{"detail": "d", "url": "u", "metric": "180,000 views"}])

    assert big["score"] > small["score"]
    assert big["score"] <= 1.0


# ---------- parse_judge_response ----------

def test_parse_judge_response_reads_fenced_json():
    text = '```json\n{"score": 0.62, "verdict": "the rule is thin", "missing": ["rule"]}\n```'

    result = story_judge.parse_judge_response(text)

    assert result == {"ok": True, "score": 0.62, "verdict": "the rule is thin",
                      "missing": ["rule"]}


def test_parse_judge_response_clamps_out_of_range_score():
    result = story_judge.parse_judge_response('{"score": 4.0, "verdict": "x", "missing": []}')

    assert result["ok"] and result["score"] == 1.0


def test_parse_judge_response_degrades_on_garbage():
    result = story_judge.parse_judge_response("not json at all")

    assert result["ok"] is False
    assert result["score"] is None
    assert "error" in result


def test_parse_judge_response_degrades_on_missing_score():
    result = story_judge.parse_judge_response('{"verdict": "no score field"}')

    assert result["ok"] is False


# ---------- blend ----------

def test_blend_uses_virality_alone_when_no_story_score():
    assert story_judge.blend(None, 0.4) == 0.4


def test_blend_weights_story_over_virality():
    blended = story_judge.blend(1.0, 0.0)

    assert blended == story_judge.STORY_WEIGHT


def test_blend_is_between_the_two_inputs():
    blended = story_judge.blend(0.8, 0.2)

    assert 0.2 < blended < 0.8


# ---------- judge_spark: never raises, degrades under no_network ----------

def test_judge_spark_degrades_gracefully_with_no_network(monkeypatch):
    class FakeModels:
        def generate_content(self, model, contents):
            raise AssertionError("should never reach the model -- RAG should fail first")

    class FakeClient:
        models = FakeModels()

    result = story_judge.judge_spark("a spark", "a rationale", FakeClient(), "fake-model")

    assert result["ok"] is False
    assert result["score"] is None
    assert "error" in result
