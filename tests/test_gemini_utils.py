"""The retry ladder every Gemini call in this project climbs.

Untested until 2026-08-29, when a Create that looked like it hung for
minutes turned out to be spending them asleep: a 503 body carries no
"retry in Xs" hint the way a 429 does, so every overload took the full
flat 20 seconds, six times, across three models. The measured 503
cleared on a retry 1.5s later.
"""
import time
from types import SimpleNamespace

import pytest

from src import gemini_utils


def answering(text="ok"):
    return SimpleNamespace(text=text)


class FakeClient:
    """A client whose every call is scripted: an exception to raise or a
    response to return, per attempt."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

        def generate_content(model, contents):
            self.calls.append(model)
            step = self.script.pop(0) if self.script else answering()
            if isinstance(step, Exception):
                raise step
            return step

        self.models = SimpleNamespace(generate_content=generate_content)


@pytest.fixture
def no_sleeping(monkeypatch):
    slept = []
    monkeypatch.setattr(time, "sleep", lambda s: slept.append(s))
    monkeypatch.setattr(gemini_utils.time, "sleep", lambda s: slept.append(s))
    return slept


# --- how long to wait -------------------------------------------------------

def test_an_explicit_cooldown_wins_outright():
    """A 429 states its own cooldown; guessing under it earns another."""
    assert gemini_utils.retry_delay(
        RuntimeError("429 RESOURCE_EXHAUSTED, retry in 7.5s"), 0) == 9.5


def test_everything_else_backs_off_from_one_second():
    """The common case is a 503 that clears in about a second. It used
    to cost twenty, every time."""
    delays = [gemini_utils.retry_delay(RuntimeError("503 UNAVAILABLE"), n)
              for n in range(7)]
    assert delays == [1.0, 2.0, 4.0, 8.0, 16.0, 20.0, 20.0]
    assert max(delays) == gemini_utils.MAX_RETRY_DELAY


# --- how many times, and on which model -------------------------------------

def test_a_busy_model_is_retried_then_handed_off(no_sleeping):
    """A model with a fallback behind it gets a short budget: a preview
    endpoint is the first thing squeezed under load, and six attempts at
    it before trying a stable sibling is backwards."""
    busy = RuntimeError("503 UNAVAILABLE. high demand")
    client = FakeClient([busy] * gemini_utils.FALLTHROUGH_RETRIES + [answering("wrote it")])
    assert gemini_utils.generate_with_retry(client, "preview-model", "x") == "wrote it"
    assert client.calls[:gemini_utils.FALLTHROUGH_RETRIES] == \
        ["preview-model"] * gemini_utils.FALLTHROUGH_RETRIES
    assert client.calls[-1] == gemini_utils.FALLBACK_MODELS[0]
    assert no_sleeping == [1.0, 2.0]          # not 20, 20


def test_the_last_model_keeps_asking_because_it_has_nowhere_to_go(no_sleeping):
    """Whichever model ends the chain gets the full budget. Note the
    chain is [model] + the fallbacks it is not, so naming a fallback as
    the primary reorders it rather than shortening the ladder."""
    busy = RuntimeError("503 UNAVAILABLE")
    client = FakeClient([busy] * 50)
    with pytest.raises(RuntimeError):
        gemini_utils.generate_with_retry(client, "preview-model", "x")
    chain = ["preview-model"] + gemini_utils.FALLBACK_MODELS
    assert client.calls.count(chain[-1]) == gemini_utils.MAX_RETRIES
    for earlier in chain[:-1]:
        assert client.calls.count(earlier) == gemini_utils.FALLTHROUGH_RETRIES


def test_the_whole_ladder_costs_seconds_not_minutes(no_sleeping):
    """The point of the change. Six attempts at a flat 20s across three
    models was about five minutes of a job spent asleep."""
    client = FakeClient([RuntimeError("503 UNAVAILABLE")] * 60)
    with pytest.raises(RuntimeError):
        gemini_utils.generate_with_retry(client, "preview-model", "x")
    assert sum(no_sleeping) < 60


def test_a_real_error_is_never_retried(no_sleeping):
    """A refusal is an answer, not a blip."""
    client = FakeClient([ValueError("400 INVALID_ARGUMENT")])
    with pytest.raises(ValueError):
        gemini_utils.generate_with_retry(client, "m", "x")
    assert len(client.calls) == 1 and no_sleeping == []


def test_a_first_try_that_works_neither_sleeps_nor_falls_back(no_sleeping):
    client = FakeClient([answering("straight through")])
    assert gemini_utils.generate_with_retry(client, "m", "x") == "straight through"
    assert client.calls == ["m"] and no_sleeping == []


# --- saying so --------------------------------------------------------------

def test_a_caller_can_hear_that_it_is_waiting(no_sleeping):
    """These notes went only to stderr, which is nowhere if the person
    is looking at a progress bar. A busy model and a thinking model are
    the same spinner otherwise."""
    heard = []
    client = FakeClient([RuntimeError("503 UNAVAILABLE"), answering()])
    gemini_utils.generate_with_retry(client, "m", "x", on_retry=heard.append)
    assert len(heard) == 1
    assert "busy" in heard[0] and "retrying in 1s" in heard[0]


def test_the_handoff_is_announced_too(no_sleeping):
    heard = []
    busy = RuntimeError("503 UNAVAILABLE")
    client = FakeClient([busy] * gemini_utils.FALLTHROUGH_RETRIES + [answering()])
    gemini_utils.generate_with_retry(client, "preview-model", "x", on_retry=heard.append)
    assert any("trying a fallback model" in note for note in heard)


def test_telling_someone_is_never_worth_failing_a_run(no_sleeping):
    """on_retry is narration: a listener that raises -- a closed SSE
    feed, a job already gone -- must not take the generation down with
    it. Deliberately `except Exception`, so a Ctrl-C still interrupts."""
    def broken(_note):
        raise RuntimeError("the feed went away")

    client = FakeClient([RuntimeError("503 UNAVAILABLE"), answering("fine")])
    assert gemini_utils.generate_with_retry(
        client, "m", "x", on_retry=broken) == "fine"

    def interrupted(_note):
        raise KeyboardInterrupt

    client = FakeClient([RuntimeError("503 UNAVAILABLE"), answering()])
    with pytest.raises(KeyboardInterrupt):
        gemini_utils.generate_with_retry(client, "m", "x", on_retry=interrupted)


def test_every_existing_caller_is_unaffected(no_sleeping):
    """on_retry is keyword-only with a default: ~25 call sites pass
    three positional arguments and must keep working untouched."""
    client = FakeClient([answering("ok")])
    assert gemini_utils.generate_with_retry(client, "m", "x") == "ok"


# --- which brain writes (2026-09-09) ----------------------------------------
# The composer's picker and the nightly graph both resolve through
# gemini_utils.BRAINS. Two things are worth pinning: that the fast tier's
# request is byte-for-byte the one this module has always sent, and that
# the reasoning tier refuses a substitute rather than being answered by
# flash-lite -- a scene written by the cheapest model in the repo saves,
# lands on the board, and reads identically to one that was not.

class ConfigClient:
    """A client that records the `config` it was handed, and objects if it
    is handed one at all when it should not be.

    Deliberately mirrors FakeClient's narrower signature above: every
    other fake in this suite implements generate_content(model, contents)
    and nothing else, which is exactly why generate_with_retry omits the
    keyword rather than passing None."""

    def __init__(self):
        self.configs = []
        self.calls = []

        def generate_content(model, contents, config=None):
            self.calls.append(model)
            self.configs.append(config)
            return answering("wrote it")

        self.models = SimpleNamespace(generate_content=generate_content)


def test_the_fast_tier_sends_no_config_at_all():
    """Not `config=None` -- nothing. The old fakes take two keywords."""
    client = ConfigClient()
    gemini_utils.generate_with_retry(client, "m", "x")
    assert client.configs == [None]          # its own default, never ours

    plain = FakeClient([answering("ok")])    # takes NO config keyword
    assert gemini_utils.generate_with_retry(plain, "m", "x") == "ok"


def test_a_thinking_config_reaches_the_model():
    client = ConfigClient()
    spec = gemini_utils.resolve_brain("reasoning")
    gemini_utils.generate_with_retry(client, spec["model"], "x",
                                     config=spec["config"])
    assert client.calls == [gemini_utils.REASONING_MODEL]
    assert client.configs[0].thinking_config.thinking_level == "HIGH"


def test_the_reasoning_tier_refuses_a_substitute(no_sleeping):
    """The whole point. With the default chain a 503 would have been
    answered by gemini-3.1-flash-lite and saved as if nothing happened."""
    busy = RuntimeError("503 UNAVAILABLE")
    client = FakeClient([busy] * 50)
    spec = gemini_utils.resolve_brain("reasoning")
    with pytest.raises(gemini_utils.SubstitutionRefused):
        gemini_utils.generate_with_retry(client, spec["model"], "x",
                                         fallbacks=spec["fallbacks"])
    assert set(client.calls) == {gemini_utils.REASONING_MODEL}
    for cheaper in gemini_utils.FALLBACK_MODELS:
        assert cheaper not in client.calls


def test_no_opinion_is_not_the_same_as_no_substitute(no_sleeping):
    """`fallbacks=None` must keep the old ladder: it is what every
    existing caller passes by not passing anything."""
    busy = RuntimeError("503 UNAVAILABLE")
    client = FakeClient([busy] * gemini_utils.FALLTHROUGH_RETRIES + [answering("ok")])
    assert gemini_utils.generate_with_retry(client, "m", "x", fallbacks=None) == "ok"
    assert client.calls[-1] == gemini_utils.FALLBACK_MODELS[0]


def test_an_unknown_tier_writes_a_cheap_scene_rather_than_failing():
    """This is reached from a form field and an env var on a 3:30am job.
    A typo must not lose the night."""
    for name in ("", None, "resoning", "REASONING"):
        spec = gemini_utils.resolve_brain(name)
        assert spec["brain"] in gemini_utils.BRAINS
    assert gemini_utils.resolve_brain("nonsense")["brain"] == gemini_utils.DEFAULT_BRAIN
    assert gemini_utils.resolve_brain("REASONING")["brain"] == "reasoning"


def test_the_fast_tier_is_the_model_shootgen_actually_uses():
    """One literal. A second copy of the model name is how the picker and
    the writer drift into disagreeing."""
    from src import shootgen
    assert shootgen.MODEL == gemini_utils.FAST_MODEL
    assert gemini_utils.resolve_brain("fast")["model"] == shootgen.MODEL


def test_every_offered_tier_is_priced():
    """An UNPRICED reasoning run would leave /costs unable to say what
    the expensive tier cost, which is the one question it exists for."""
    from src import spend
    table = spend.prices()
    for option in gemini_utils.brain_options():
        assert gemini_utils.resolve_brain(option["id"])["model"] in table
