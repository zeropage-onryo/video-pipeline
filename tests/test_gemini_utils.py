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
