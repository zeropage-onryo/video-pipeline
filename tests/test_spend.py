"""
The LLM meter (src/spend.py) and the cost tracker (src/costs.py).

The five checks docs/tasks/task-cost-tracker.md names: a metered call
writes one row with the model that ANSWERED (proven by forcing a
fallback); a metering failure does not fail the generation; an account
sees only its own spend; a free render is reported as free, not $0.00;
and the cost-per-keeper figure counts the rejected attempts on the same
shot. Plus the price table's arithmetic, since token counts are not a
bill. Against the throwaway Postgres (conftest's `pg`), like every
table since 2026-09-03.
"""
import time
from types import SimpleNamespace

import pytest

from src import accounts, autonomy, costs, db, gemini_utils, generative, spend
from src.shot import Shot


def answering(text="ok", prompt=100, output=50, cached=None, thoughts=None):
    return SimpleNamespace(
        text=text,
        usage_metadata=SimpleNamespace(
            prompt_token_count=prompt, candidates_token_count=output,
            cached_content_token_count=cached, thoughts_token_count=thoughts))


class FakeClient:
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
def tmp_db(pg, monkeypatch):
    dsn = pg
    generative.init(dsn)
    autonomy.init(dsn)
    spend.init(dsn)
    accounts.init(dsn)
    # real account rows: llm_calls.account_id is a foreign key, and a
    # row for an account that does not exist is (rightly) refused
    for slug in ("three", "seven", "nine"):
        accounts.upsert_account(slug, slug.upper(), dsn=dsn)
    # calls that pass no dsn (the retry helper's) land on the same schema
    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    monkeypatch.setattr(gemini_utils.time, "sleep", lambda s: None)
    return dsn


def rows(dsn, sql="SELECT * FROM llm_calls ORDER BY id", args=()):
    with db.connect(dsn) as conn:
        return [dict(r) for r in conn.execute(sql, args)]


# --- the price table -------------------------------------------------------

def test_cost_prices_cached_tokens_at_the_cached_rate_and_thoughts_as_output():
    cost = spend.estimate_cost("gemini-3-flash-preview", prompt_tokens=1_000_000,
                               output_tokens=1_000_000, cached_tokens=500_000,
                               thought_tokens=1_000_000)
    # 500k input @0.50 + 500k cached @0.05 + (1M output + 1M thoughts) @3.00
    assert cost == pytest.approx(0.25 + 0.025 + 6.00)


def test_an_image_model_prices_per_image_and_an_unknown_model_prices_none():
    assert spend.estimate_cost("gemini-2.5-flash-image", images=2) == pytest.approx(0.078)
    # a keyframe reports ~1290 output tokens -- those ARE the image, never billed twice
    assert spend.estimate_cost("gemini-2.5-flash-image", prompt_tokens=400,
                               output_tokens=1291, images=1) == pytest.approx(0.039 + 400 * 0.30 / 1e6)
    assert spend.estimate_cost("some-model-nobody-priced", output_tokens=10) is None


def test_prices_can_be_overridden_from_env_without_touching_a_call_site(monkeypatch):
    monkeypatch.setenv("SPEND_PRICES_JSON", '{"gemini-3-flash-preview": {"output": 6.0}}')
    assert spend.estimate_cost("gemini-3-flash-preview", output_tokens=1_000_000) == 6.0
    monkeypatch.setenv("SPEND_PRICES_JSON", "not json")
    assert spend.estimate_cost("gemini-3-flash-preview", output_tokens=1_000_000) == 3.0


# --- the meter ---------------------------------------------------------------

def test_a_metered_call_records_the_model_that_answered(tmp_db):
    """Forced fallback: asked for the preview, answered by flash-lite.
    A caller pricing its own call would have priced the wrong model."""
    unavailable = RuntimeError("503 UNAVAILABLE")
    client = FakeClient([unavailable, unavailable, unavailable, answering("hi")])
    seven = accounts.resolve_account("seven", dsn=tmp_db)
    text = gemini_utils.generate_with_retry(client, "gemini-3-flash-preview", "q",
                                            stage="concepts", account_id=seven, run_id="r1")
    assert text == "hi"
    calls = rows(tmp_db, "SELECT * FROM llm_calls WHERE ok = 1")
    assert len(calls) == 1
    call = calls[0]
    assert call["model_asked"] == "gemini-3-flash-preview"
    assert call["model_used"] == "gemini-3.1-flash-lite"
    assert call["stage"] == "concepts" and call["account_id"] == seven and call["run_id"] == "r1"
    assert call["prompt_tokens"] == 100 and call["output_tokens"] == 50
    assert call["cost_usd"] == pytest.approx((100 * 0.25 + 50 * 1.50) / 1e6)
    assert call["ms"] is not None


def test_a_metering_failure_never_fails_the_generation(tmp_db, monkeypatch):
    def boom(*a, **k):
        raise TypeError("accounting bug")
    monkeypatch.setattr(spend.db, "connect", boom)
    assert gemini_utils.generate_with_retry(FakeClient([answering("still ok")]),
                                            "gemini-3-flash-preview", "q") == "still ok"
    # and a response with no usage_metadata at all is a row, not a crash
    monkeypatch.undo()
    monkeypatch.setenv("DATABASE_URL", tmp_db)
    bare = SimpleNamespace(text="bare")
    assert gemini_utils.generate_with_retry(FakeClient([bare]), "gemini-3-flash-preview",
                                            "q") == "bare"
    [call] = rows(tmp_db, "SELECT * FROM llm_calls WHERE model_used = 'gemini-3-flash-preview'")
    assert call["prompt_tokens"] is None and call["cost_usd"] is None    # unpriced, not $0
    assert spend.by_stage(tmp_db, account_id=None)[0]["unpriced"] == 1


def test_a_hard_failure_is_recorded_as_not_ok_and_still_raised(tmp_db):
    client = FakeClient([RuntimeError("400 INVALID_ARGUMENT")])
    with pytest.raises(RuntimeError):
        gemini_utils.generate_with_retry(client, "gemini-3-flash-preview", "q", stage="crag")
    [call] = rows(tmp_db)
    assert call["ok"] == 0 and call["cost_usd"] is None and call["stage"] == "crag"


def test_an_unlisted_stage_is_stored_as_unknown_not_refused(tmp_db):
    assert spend.record_call(stage="judgey", model_asked="gemini-3-flash-preview",
                             response=answering(), dsn=tmp_db) is not None
    assert rows(tmp_db)[0]["stage"] == "unknown"


def test_the_bound_context_attributes_calls_a_caller_did_not_label(tmp_db):
    """jobs.start binds the job's account; orchestrator.run binds the run
    -- so the 42 callers need no plumbing of their own."""
    three = accounts.resolve_account("three", dsn=tmp_db)
    token = spend.bind(account_id=three, run_id="night-1")
    try:
        gemini_utils.generate_with_retry(FakeClient([answering()]), "gemini-3-flash-preview", "q")
    finally:
        spend.unbind(token)
    [call] = rows(tmp_db)
    assert (call["account_id"], call["run_id"]) == (three, "night-1")
    gemini_utils.generate_with_retry(FakeClient([answering()]), "gemini-3-flash-preview", "q")
    assert rows(tmp_db)[-1]["account_id"] is None      # unbound again


def test_a_langchain_turn_is_read_the_same_way():
    message = SimpleNamespace(type="ai", usage_metadata={
        "input_tokens": 10, "output_tokens": 4,
        "input_token_details": {"cache_read": 2},
        "output_token_details": {"reasoning": 1}})
    assert spend.usage_from_langchain(message) == {
        "prompt_tokens": 10, "output_tokens": 4, "cached_tokens": 2, "thought_tokens": 1}


def test_reprice_recomputes_from_the_raw_counts(tmp_db, monkeypatch):
    """Token counts are not a bill: a wrong price table is a
    re-computation, not a lost measurement."""
    spend.record_call(stage="concepts", model_asked="gemini-3-flash-preview",
                      response=answering(prompt=1000, output=1000), dsn=tmp_db)
    before = rows(tmp_db)[0]["cost_usd"]
    monkeypatch.setenv("SPEND_PRICES_JSON", '{"gemini-3-flash-preview": {"input": 1.0, "output": 1.0}}')
    assert spend.reprice(tmp_db, account_id=None) == 1
    after = rows(tmp_db)[0]["cost_usd"]
    assert before != after and after == pytest.approx(2000 / 1e6)
    assert spend.reprice(tmp_db, account_id=None) == 0        # idempotent


# --- ownership ---------------------------------------------------------------

def test_an_account_sees_only_its_own_spend(tmp_db):
    a = accounts.resolve_account("three", dsn=tmp_db)
    b = accounts.resolve_account("seven", dsn=tmp_db)
    for owner, n in ((a, 3), (b, 1)):
        for _ in range(n):
            spend.record_call(stage="concepts", model_asked="gemini-3-flash-preview",
                              response=answering(), account_id=owner, run_id=f"run-{owner}",
                              dsn=tmp_db)
    assert sum(s["calls"] for s in spend.by_stage(tmp_db, account_id=a)) == 3
    assert sum(s["calls"] for s in spend.by_stage(tmp_db, account_id=b)) == 1
    assert [r["run_id"] for r in spend.by_run(tmp_db, account_id=b)] == [f"run-{b}"]
    assert spend.spent_today(tmp_db, account_id=b)["calls"] == 1
    assert spend.spent_today_everyone(tmp_db)["calls"] == 4      # the one deliberate global
    assert costs.summary(tmp_db, account_id=b)["today"]["llm"]["calls"] == 1


# --- the four numbers ----------------------------------------------------------

def _shot(dsn, account_id=None):
    return generative.add_shot(Shot(subject="a drawer", action="closing"),
                               dsn=dsn, account_id=account_id)


def test_a_free_render_is_reported_as_free_not_as_zero_spend(tmp_db):
    shot = _shot(tmp_db)
    generative.record_generation(shot, "nano", "p", dsn=tmp_db, account_id=None)   # cost NULL
    generative.record_generation(shot, "runway", "p", cost_usd=0.25, dsn=tmp_db, account_id=None)
    render = costs.render_costs(tmp_db, account_id=None)
    assert render["attempts"] == 2 and render["free"] == 1
    assert render["spend"] == 0.25                     # the NULL is not folded in as 0


def test_cost_per_keeper_counts_the_losers_on_the_same_shot(tmp_db):
    shot = _shot(tmp_db)
    g1 = generative.record_generation(shot, "runway", "p", cost_usd=0.25, dsn=tmp_db, account_id=None)
    g2 = generative.record_generation(shot, "runway", "p", cost_usd=0.25, dsn=tmp_db, account_id=None)
    g3 = generative.record_generation(shot, "runway", "p", cost_usd=0.25, dsn=tmp_db, account_id=None)
    generative.mark_rejected(g1, "morphed", dsn=tmp_db, account_id=None)
    generative.mark_rejected(g2, "morphed", dsn=tmp_db, account_id=None)
    generative.mark_kept(g3, dsn=tmp_db, account_id=None)
    summary = costs.summary(tmp_db, account_id=None)
    [board] = summary["render"]["scoreboard"]
    assert board["attempts"] == 3 and board["kept"] == 1
    assert board["cost_per_keeper"] == 0.75            # three attempts paid for one keeper
    [keeper] = summary["render"]["keepers"]
    assert keeper["total_attempts_all_tools"] == 3 and float(keeper["total_cost"]) == 0.75
    assert summary["waste"]["rejected_attempts"] == 2
    assert summary["waste"]["rejected_spend"] == 0.5


def test_cost_per_stage_per_night_names_the_token_hog(tmp_db):
    for stage, out in (("concepts", 4000), ("taste_judge", 300), ("crag", 100)):
        spend.record_call(stage=stage, model_asked="gemini-3-flash-preview",
                          response=answering(output=out), run_id="night-7", dsn=tmp_db)
    summary = costs.summary(tmp_db, account_id=None)
    assert summary["llm"]["by_stage"][0]["stage"] == "concepts"
    [night] = summary["llm"]["by_run"]
    assert night["run_id"] == "night-7" and night["calls"] == 3
    assert night["top_stage"] == "concepts", (night, summary["llm"]["by_stage"])
    assert summary["llm"]["latest_run"]["run_id"] == "night-7"


def test_today_against_the_caps_reads_both_walls(tmp_db, monkeypatch):
    from src import runway
    monkeypatch.setattr(runway, "DAILY_CAP", 2)
    monkeypatch.setattr(runway, "GLOBAL_DAILY_CAP", 3)
    nine = accounts.resolve_account("nine", dsn=tmp_db)
    generative.record_generation(_shot(tmp_db), "runway", "p", cost_usd=0.25, dsn=tmp_db,
                                 account_id=None)
    generative.record_generation(_shot(tmp_db, nine), "runway", "p", cost_usd=0.25, dsn=tmp_db,
                                 account_id=nine)
    today = costs.today(tmp_db, account_id=None)
    runway_row = next(t for t in today["tools"] if t["tool"] == "runway")
    assert (runway_row["used"], runway_row["cap"]) == (1, 2)
    assert (runway_row["everyone"], runway_row["ceiling"]) == (2, 3)
    assert runway_row["spend_env"] == "RUNWAY_SPEND_OK"
    assert next(t for t in today["tools"] if t["tool"] == "nano")["spend_env"] is None
