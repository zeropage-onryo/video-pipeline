"""
Tests for src/nightly.py -- the runner that replaced the bash walk.

Every one of these is a night the owner actually lost (see the module
docstring and docs/RUNBOOK.md): a DNS miss repeated sixteen times, a
depleted card retried six times a call, a spent image cap explained
sixteen ways, and eleven nights nobody could prove had not run.

Hermetic: `run_one` is the seam, so nothing here generates, and the two
preflight checks that would touch the network are patched. The database
is a throwaway schema -- the nightly_runs row is the one thing that has
to be real.
"""
import socket

import pytest

from src import db, gemini_utils, nightly

SPARKS = ["a spark", "another spark"]
PAIRS = (("antihero", "antihero"), ("zeropage", "zeropage"))


@pytest.fixture
def nightly_db(pg, monkeypatch):
    """A throwaway schema, plus the two env vars the walk writes so
    monkeypatch puts them back afterwards."""
    from src import autonomy
    autonomy.init(pg)
    monkeypatch.setenv("DATABASE_URL", pg)
    monkeypatch.setenv("ZEROPAGE_KEYFRAME", "1")
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    return pg


@pytest.fixture
def healthy_preflight(monkeypatch):
    """db reachable (really), Gemini answering, keyframes available."""
    monkeypatch.setattr(nightly, "check_gemini",
                        lambda client=None: {"ok": True, "detail": "stub answered"})
    monkeypatch.setattr(nightly, "check_image_cap",
                        lambda dsn=None, account_id=None: {
                            "ok": True, "headroom": 12, "used": 8, "everyone": 8,
                            "detail": "8/20 today"})


def _walk(dsn, **kw):
    lines = []
    kw.setdefault("sparks", SPARKS)
    kw.setdefault("pairs", PAIRS)
    summary = nightly.walk(dsn=dsn, account_id=None, log=lines.append, **kw)
    summary["log"] = "\n".join(lines)
    return summary


# --------------------------------------------------------------------------
# classify_error -- the opinion the breaker and the trigger share
# --------------------------------------------------------------------------

@pytest.mark.parametrize("error", [
    socket.gaierror(8, "nodename nor servname provided, or not known"),
    RuntimeError("[Errno 8] nodename nor servname provided"),
    OSError("could not translate host name \"aws-0-pooler.supabase.com\""),
    RuntimeError("429 RESOURCE_EXHAUSTED: your prepayment credits are depleted"),
    RuntimeError("401 UNAUTHENTICATED: API key not valid"),
    ConnectionResetError("connection reset by peer"),
])
def test_systemic_errors_are_classified_systemic(error):
    assert nightly.classify_error(error) == nightly.SYSTEMIC


@pytest.mark.parametrize("error", [
    ValueError("could not parse the judge's verdict"),
    RuntimeError("deadlock detected on relation shoot_concepts"),
    KeyError("shots"),
    RuntimeError("429 RESOURCE_EXHAUSTED: rate limit, retry in 4.2s"),
])
def test_content_errors_are_classified_content(error):
    """Unrecognised is CONTENT on purpose: erring that way costs one run,
    erring the other way costs the night."""
    assert nightly.classify_error(error) == nightly.CONTENT


def test_a_deadlock_is_content_even_though_it_arrives_as_an_operational_error():
    """The ordering that matters. psycopg raises the same base class for
    a dead socket and for one unlucky transaction; reading the content
    markers first is what stops a deadlock ending a healthy night."""
    import psycopg
    assert nightly.classify_error(
        psycopg.OperationalError("deadlock detected")) == nightly.CONTENT
    assert nightly.classify_error(
        psycopg.OperationalError("server closed the connection")) == nightly.SYSTEMIC


# --------------------------------------------------------------------------
# the breaker
# --------------------------------------------------------------------------

def test_a_systemic_failure_stops_the_walk_at_the_first_run(nightly_db, healthy_preflight,
                                                            monkeypatch):
    attempts = []

    def boom(channel, brand, spark, research=True):
        attempts.append(spark)
        return {"ok": False, "kind": nightly.SYSTEMIC,
                "error": "[Errno 8] nodename nor servname provided"}

    monkeypatch.setattr(nightly, "run_one", boom)
    summary = _walk(nightly_db)

    assert len(attempts) == 1, "the other 15 runs would hit the same dead socket"
    assert summary["attempted"] == 1 and summary["failed"] == 1
    assert "systemic" in summary["stopped_reason"]
    assert "Errno 8" in summary["stopped_reason"]


def test_a_content_failure_moves_on_to_the_next_spark(nightly_db, healthy_preflight,
                                                      monkeypatch):
    attempts = []

    def boom(channel, brand, spark, research=True):
        attempts.append((channel, spark))
        return {"ok": False, "kind": nightly.CONTENT,
                "error": "could not parse the judge's verdict"}

    monkeypatch.setattr(nightly, "run_one", boom)
    summary = _walk(nightly_db)

    assert len(attempts) == len(SPARKS) * len(PAIRS)
    assert summary["failed"] == len(attempts)
    assert summary["stopped_reason"] is None


def test_the_breaker_leaves_one_hold_row_saying_why(nightly_db, healthy_preflight,
                                                    monkeypatch):
    from src import autonomy
    monkeypatch.setattr(nightly, "run_one",
                        lambda *a, **k: {"ok": False, "kind": nightly.SYSTEMIC,
                                         "error": "prepayment credits are depleted"})
    _walk(nightly_db)

    holds = [h for h in autonomy.list_hold(dsn=nightly_db, account_id=None)
             if "nightly stopped" in h["reason"]]
    assert len(holds) == 1, "one line about the night, not sixteen about its runs"
    assert "depleted" in holds[0]["reason"]


# --------------------------------------------------------------------------
# the budget
# --------------------------------------------------------------------------

def test_the_walk_stops_when_the_budget_is_spent(nightly_db, healthy_preflight,
                                                 monkeypatch):
    from src import costs
    spent = {"total_usd": 0.0}
    monkeypatch.setattr(costs, "spent_since",
                        lambda ts, dsn=None, account_id=None: dict(spent))

    def one_dollar(channel, brand, spark, research=True):
        spent["total_usd"] += 1.0
        return {"ok": True, "spark": spark, "held": None}

    monkeypatch.setattr(nightly, "run_one", one_dollar)
    summary = _walk(nightly_db, budget=2.0)

    assert summary["attempted"] == 2, "checked BEFORE a run, not after"
    assert summary["stopped_reason"].startswith("budget")
    assert "NIGHTLY_BUDGET_USD" in summary["stopped_reason"]


def test_the_budget_default_survives_a_nonsense_value(monkeypatch):
    monkeypatch.setenv(nightly.BUDGET_ENV, "banana")
    assert nightly.budget_usd() == nightly.DEFAULT_BUDGET_USD
    monkeypatch.setenv(nightly.BUDGET_ENV, "0")
    assert nightly.budget_usd() == nightly.DEFAULT_BUDGET_USD
    monkeypatch.setenv(nightly.BUDGET_ENV, "1.25")
    assert nightly.budget_usd() == 1.25


def test_an_unreadable_meter_does_not_stop_the_night(nightly_db, monkeypatch):
    from src import costs

    def broken(*a, **k):
        raise RuntimeError("no such column")

    monkeypatch.setattr(costs, "spent_since", broken)
    assert nightly._spent("2026-09-07T00:00:00+00:00", nightly_db, account_id=None) == 0.0


# --------------------------------------------------------------------------
# the image cap: drop the keyframes, not the night
# --------------------------------------------------------------------------

def test_a_spent_image_cap_turns_keyframes_off_and_still_walks(nightly_db, monkeypatch):
    import os
    monkeypatch.setattr(nightly, "check_gemini",
                        lambda client=None: {"ok": True, "detail": "stub"})
    monkeypatch.setattr(nightly, "check_image_cap",
                        lambda dsn=None, account_id=None: {
                            "ok": False, "headroom": 0, "used": 20, "everyone": 20,
                            "detail": "20/20 today"})
    seen = []
    monkeypatch.setattr(nightly, "run_one",
                        lambda channel, brand, spark, research=True: seen.append(
                            os.environ.get("ZEROPAGE_KEYFRAME")) or {
                                "ok": True, "spark": spark, "held": None})

    summary = _walk(nightly_db)

    assert seen == ["0"] * (len(SPARKS) * len(PAIRS)), "the runs see the flag"
    assert summary["attempted"] == 4, "concept text is cheap and still worth having"
    assert summary["stopped_reason"] is None
    assert summary["log"].count("image cap already spent") == 1, "said once, not 16 times"


def test_the_walk_puts_back_every_environment_variable_it_changed(nightly_db, monkeypatch):
    """The walk borrows the process environment; it does not keep it.

    Both overrides used to be one-way writes. On the Mac that was
    invisible -- the walk is a subprocess and its environment dies with
    it. On the always-on Fly machine cron and uvicorn share one process
    environment, so a single night that hit the image cap left
    ZEROPAGE_KEYFRAME="0" behind and every Director keyframe after it was
    silently disabled until someone restarted the machine.
    """
    import os
    monkeypatch.setenv("ZEROPAGE_KEYFRAME", "1")
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.delenv(nightly.TRACING_ENV, raising=False)
    monkeypatch.delenv("LANGCHAIN_TRACING_V2", raising=False)
    monkeypatch.setattr(nightly, "check_gemini",
                        lambda client=None: {"ok": True, "detail": "stub"})
    monkeypatch.setattr(nightly, "check_image_cap",
                        lambda dsn=None, account_id=None: {
                            "ok": False, "headroom": 0, "used": 20, "everyone": 20,
                            "detail": "20/20 today"})
    inside = {}
    monkeypatch.setattr(nightly, "run_one",
                        lambda channel, brand, spark, research=True: inside.setdefault(
                            "keyframe", os.environ.get("ZEROPAGE_KEYFRAME")) and None or {
                                "ok": True, "spark": spark, "held": None})

    _walk(nightly_db)

    assert inside["keyframe"] == "0", "the runs still see it turned off"
    assert os.environ["ZEROPAGE_KEYFRAME"] == "1", "and it is put back after"
    assert os.environ["LANGSMITH_TRACING"] == "true", "tracing restored too"
    assert "LANGCHAIN_TRACING_V2" not in os.environ, "one that was unset stays unset"


def test_headroom_is_the_smaller_of_the_two_walls(nightly_db, monkeypatch):
    from src import nano_banana
    monkeypatch.setattr(nano_banana, "DAILY_CAP", 20)
    monkeypatch.setattr(nano_banana, "GLOBAL_DAILY_CAP", 20)
    monkeypatch.setattr(nano_banana, "generations_today",
                        lambda db_path=None, everyone=False, **kw:
                        20 if everyone else 3)
    report = nightly.check_image_cap(nightly_db)
    assert report["headroom"] == 0 and report["ok"] is False


def test_no_ceiling_does_not_read_as_zero_headroom(nightly_db, monkeypatch):
    """2026-09-14. GLOBAL_DAILY_CAP defaults to 0 = OFF. Subtracting it
    blindly made headroom negative, clamped to 0, and reported ok=False --
    which would have stopped the walk every single night on an install that
    had merely turned the installation-wide wall off. The per-account cap
    is the only wall left, and it still counts."""
    from src import nano_banana
    monkeypatch.setattr(nano_banana, "DAILY_CAP", 20)
    monkeypatch.setattr(nano_banana, "GLOBAL_DAILY_CAP", 0)
    monkeypatch.setattr(nano_banana, "generations_today",
                        lambda db_path=None, everyone=False, **kw:
                        999 if everyone else 3)
    report = nightly.check_image_cap(nightly_db)
    assert report["ok"] is True
    assert report["headroom"] == 17          # 20 - 3, the ceiling ignored
    assert "no ceiling" in report["detail"]

    # and the per-account cap still stops the night on its own
    monkeypatch.setattr(nano_banana, "generations_today",
                        lambda db_path=None, everyone=False, **kw:
                        999 if everyone else 20)
    spent = nightly.check_image_cap(nightly_db)
    assert spent["headroom"] == 0 and spent["ok"] is False


# --------------------------------------------------------------------------
# preflight
# --------------------------------------------------------------------------

def test_an_unreachable_database_stops_the_walk_before_run_one(nightly_db, monkeypatch):
    monkeypatch.setattr(nightly, "check_db",
                        lambda dsn=None: {"ok": False, "kind": nightly.SYSTEMIC,
                                          "detail": "[Errno 8] nodename nor servname provided"})
    monkeypatch.setattr(nightly, "run_one",
                        lambda *a, **k: pytest.fail("preflight should have stopped this"))
    summary = _walk(nightly_db)
    assert summary["attempted"] == 0
    assert "database unreachable" in summary["stopped_reason"]


def test_preflight_reports_in_one_line(nightly_db, healthy_preflight):
    report = nightly.preflight(nightly_db, account_id=None)
    line = nightly.preflight_line(report)
    assert line.count("\n") == 0
    assert "db=ok" in line and "gemini=ok" in line


def test_gemini_check_reports_a_depleted_card_as_systemic(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "not-a-real-key")

    def depleted(*a, **k):
        raise RuntimeError("429 RESOURCE_EXHAUSTED: prepayment credits are depleted")

    monkeypatch.setattr(gemini_utils, "generate_with_retry", depleted)
    report = nightly.check_gemini(client=object())
    assert report["ok"] is False and report["kind"] == nightly.SYSTEMIC


# --------------------------------------------------------------------------
# the receipt
# --------------------------------------------------------------------------

def test_the_walk_writes_a_nightly_runs_row(nightly_db, healthy_preflight, monkeypatch):
    monkeypatch.setattr(nightly, "run_one",
                        lambda channel, brand, spark, research=True: {
                            "ok": True, "spark": spark, "held": "shadow — grading only"})
    summary = _walk(nightly_db)

    [row] = db.recent_nightly_runs(dsn=nightly_db)
    assert row["attempted"] == 4 and row["succeeded"] == 4 and row["failed"] == 0
    assert row["stopped_reason"] is None
    assert row["finished_at"], "an unfinished row is how a mid-flight death reads"
    assert row["started_at"] == summary["started_at"]
    assert summary["held"] == 4


def test_a_stopped_walk_records_its_reason_on_the_row(nightly_db, healthy_preflight,
                                                      monkeypatch):
    monkeypatch.setattr(nightly, "run_one",
                        lambda *a, **k: {"ok": False, "kind": nightly.SYSTEMIC,
                                         "error": "connection refused"})
    _walk(nightly_db)
    [row] = db.recent_nightly_runs(dsn=nightly_db)
    assert "systemic" in row["stopped_reason"] and row["failed"] == 1


def test_the_row_is_written_before_the_runs(nightly_db, healthy_preflight, monkeypatch):
    """The eleven silent nights are why. A row that only appears at the
    END cannot tell "died halfway" from "never started"."""
    seen = {}

    def peek(channel, brand, spark, research=True):
        seen["rows"] = db.recent_nightly_runs(dsn=nightly_db)
        return {"ok": True, "spark": spark, "held": None}

    monkeypatch.setattr(nightly, "run_one", peek)
    _walk(nightly_db, sparks=["one"], pairs=(("zeropage", "zeropage"),))
    assert len(seen["rows"]) == 1 and seen["rows"][0]["finished_at"] is None


def test_nightly_runs_is_declared_shared_not_owned():
    """A new table has to land on one side of the tenancy line
    (tests/test_tenancy.py enumerates the live schema). The nightly walk
    is the installation's cron, like scheduled_posts."""
    assert "nightly_runs" in db.SHARED_TABLES
    assert "nightly_runs" not in db.OWNED_TABLES


# --------------------------------------------------------------------------
# LangSmith
# --------------------------------------------------------------------------

def test_tracing_is_turned_off_for_the_walk(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.delenv(nightly.TRACING_ENV, raising=False)
    assert nightly.quiet_langsmith(log=lambda _: None) is True
    import os
    assert os.environ["LANGSMITH_TRACING"] == "false"


def test_tracing_can_be_kept(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv(nightly.TRACING_ENV, "1")
    assert nightly.quiet_langsmith(log=lambda _: None) is False
    import os
    assert os.environ["LANGSMITH_TRACING"] == "true"


# --------------------------------------------------------------------------
# the 429 that must not be retried
# --------------------------------------------------------------------------

def test_a_depleted_429_is_not_retried(monkeypatch):
    """The biggest waste in the log: six attempts per call, times three
    models, times sixteen runs, for a card with no money on it."""
    calls = {"n": 0}

    class Boom:
        class models:
            @staticmethod
            def generate_content(model=None, contents=None):
                calls["n"] += 1
                raise RuntimeError(
                    "429 RESOURCE_EXHAUSTED: your prepayment credits are depleted")

    slept = []
    monkeypatch.setattr(gemini_utils.time, "sleep", lambda s: slept.append(s))

    with pytest.raises(RuntimeError):
        gemini_utils.generate_with_retry(Boom(), "gemini-3-flash-preview", "hi")

    assert calls["n"] == 1, "one attempt, no fallback models -- they bill the same card"
    assert slept == []


def test_a_rate_limit_429_is_still_retried(monkeypatch):
    calls = {"n": 0}

    class Boom:
        class models:
            @staticmethod
            def generate_content(model=None, contents=None):
                calls["n"] += 1
                raise RuntimeError("429 RESOURCE_EXHAUSTED: rate limit, retry in 0.1s")

    monkeypatch.setattr(gemini_utils.time, "sleep", lambda s: None)
    with pytest.raises(RuntimeError):
        gemini_utils.generate_with_retry(Boom(), "gemini-3-flash-preview", "hi")
    assert calls["n"] > 1, "a real rate limit still clears by waiting"


@pytest.mark.parametrize("text,depleted", [
    ("your prepayment credits are depleted", True),
    ("billing account for project 123 is disabled", True),
    ("rate limit exceeded, retry in 4s", False),
    ("503 UNAVAILABLE", False),
])
def test_is_depleted_reads_the_billing_half_of_429(text, depleted):
    assert gemini_utils.is_depleted(RuntimeError(text)) is depleted


# --------------------------------------------------------------------------
# the trigger's half of the classification
# --------------------------------------------------------------------------

def test_the_trigger_labels_a_systemic_crash_and_exits_2(nightly_db, monkeypatch):
    from src import autonomy, orchestrator, trigger

    def boom(*a, **k):
        raise RuntimeError("[Errno 8] nodename nor servname provided")

    monkeypatch.setattr(orchestrator, "run", boom)
    assert trigger.main([]) == 2

    [row] = autonomy.list_hold(dsn=nightly_db, account_id=None)
    assert "systemic" in row["reason"]


def test_run_once_returns_the_kind_instead_of_an_exit_code(nightly_db, monkeypatch):
    from src import orchestrator, trigger

    monkeypatch.setattr(orchestrator, "run",
                        lambda *a, **k: {"spark": "used", "held_reason": "shadow"})
    out = trigger.run_once("asked", channel="zeropage")
    assert out == {"ok": True, "kind": None, "spark": "used", "held": "shadow",
                   "result": {"spark": "used", "held_reason": "shadow"}}


# --------------------------------------------------------------------------
# costs.spent_since -- the reader the budget needed
# --------------------------------------------------------------------------

def test_spent_since_counts_llm_calls_and_renders_after_a_timestamp(nightly_db):
    from src import costs, generative, spend
    from src.shot import Shot

    spend.init(nightly_db)
    generative.init(nightly_db)

    old = "2026-01-01T00:00:00+00:00"
    cut = "2026-09-07T00:00:00+00:00"
    with db.connect(nightly_db) as conn:
        for created, cost in ((old, 5.0), ("2026-09-07T03:30:00+00:00", 0.25)):
            conn.execute(
                "INSERT INTO llm_calls (created_at, stage, model_asked, model_used, "
                "cost_usd) VALUES (%s, 'concepts', 'm', 'm', %s)", (created, cost))
    shot_id = generative.add_shot(Shot(subject="a bike", action="idles"),
                                  dsn=nightly_db, account_id=None)
    gen_id = generative.record_generation(shot_id, "nano", "a prompt",
                                          cost_usd=0.04, dsn=nightly_db,
                                          account_id=None)
    assert gen_id

    out = costs.spent_since(cut, nightly_db, account_id=None)
    assert out["llm_usd"] == 0.25, "the January row is not this walk's spend"
    assert out["render_usd"] == 0.04
    assert out["total_usd"] == 0.29


# --------------------------------------------------------------------------
# how many sparks a night walks
# --------------------------------------------------------------------------
# 2026-09-08, Mike's call: 5 per brand, "we'll increase it once I see it
# gets better". Before this the walk took every line in sparks.txt, which
# had grown to 20 -- a 40-run night nobody had finished grading.

def test_the_default_is_five_sparks_per_brand(monkeypatch):
    monkeypatch.delenv(nightly.SPARKS_ENV, raising=False)
    assert nightly.sparks_per_pair() == 5


def test_the_limit_is_read_per_call(monkeypatch):
    monkeypatch.setenv(nightly.SPARKS_ENV, "12")
    assert nightly.sparks_per_pair() == 12


@pytest.mark.parametrize("value", ["", "0", "-3", "lots"])
def test_a_useless_limit_falls_back_to_the_default_not_to_nothing(monkeypatch, value):
    """A night that walks zero sparks is worse than one that walks five."""
    monkeypatch.setenv(nightly.SPARKS_ENV, value)
    assert nightly.sparks_per_pair() == 5


def test_the_walk_takes_only_that_many_of_each_brand(nightly_db, healthy_preflight,
                                                    monkeypatch):
    monkeypatch.setenv(nightly.SPARKS_ENV, "2")
    ran = []
    monkeypatch.setattr(nightly, "run_one",
                        lambda channel, brand, spark, **kw: ran.append((brand, spark))
                        or {"ok": True, "spark": spark, "held": "h"})

    summary = _walk(nightly_db, sparks=["a", "b", "c", "d", "e"])

    assert summary["attempted"] == 4                    # 2 sparks x 2 pairs
    assert [s for _, s in ran] == ["a", "b", "a", "b"]
    assert "walking 2 of 5 sparks per brand" in summary["log"]


def test_an_explicit_per_pair_beats_the_environment(nightly_db, healthy_preflight,
                                                    monkeypatch):
    monkeypatch.setenv(nightly.SPARKS_ENV, "2")
    monkeypatch.setattr(nightly, "run_one",
                        lambda channel, brand, spark, **kw: {"ok": True,
                                                             "spark": spark})
    assert _walk(nightly_db, sparks=["a", "b", "c"],
                 per_pair=3)["attempted"] == 6


def test_a_short_list_is_not_padded_or_trimmed(nightly_db, healthy_preflight,
                                               monkeypatch):
    monkeypatch.setattr(nightly, "run_one",
                        lambda channel, brand, spark, **kw: {"ok": True,
                                                             "spark": spark})
    summary = _walk(nightly_db, sparks=["a", "b"])
    assert summary["attempted"] == 4
    assert "walking" not in summary["log"]
