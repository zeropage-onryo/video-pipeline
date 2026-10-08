"""The job feed the studio's activity tray rides on (2026-10-08).

- what a job SPENT is on the job, exactly, as it spends it: the charge
  meter (src/charge.metering) reports every hold, settle and release made
  inside the job's worker thread, and an uncharged render that ran says
  what it would have cost, marked not charged;
- a cleared job is SAID on the stream (it never was), one at a time or all
  finished ones at once;
- a fresh subscriber is replayed the live jobs and the newest finished
  ones, not every job the process ever ran;
- the stream opens with a retry hint and the process's boot id, and tells
  every proxy not to compress it.

No ledger, no provider, no model: the ledger calls are stood in for.
"""
import asyncio
import json
import time

import pytest

from app import api as api_mod
from app import jobs
from src import charge, ledger


@pytest.fixture(autouse=True)
def fresh_registry():
    jobs.clear_all_for_tests()
    yield
    jobs.clear_all_for_tests()


class _Quote:
    def __init__(self, credits, account_id=7, provider="fal"):
        self.credits = credits
        self.account_id = account_id
        self.provider = provider


@pytest.fixture
def fake_ledger(monkeypatch):
    """A ledger that holds for account 7 and nobody else (None = exempt)."""
    monkeypatch.setattr(ledger, "init", lambda dsn=None: None)
    monkeypatch.setattr(ledger, "hold_for_render",
                        lambda account_id, **k: 501 if account_id == 7 else None)
    monkeypatch.setattr(ledger, "mark_submitted", lambda hold_id, dsn=None: "ok")
    monkeypatch.setattr(ledger, "settle", lambda hold_id, credits=0, cap=0, **k: min(credits, cap))
    monkeypatch.setattr(ledger, "release", lambda hold_id, reason, dsn=None: 87)
    monkeypatch.setattr(ledger, "charge_credits", lambda usd: 87)
    import src.billing as billing
    monkeypatch.setattr(billing, "release_due", lambda *a, **k: None)


def _heard():
    events = []
    token = charge.metering(lambda *e: events.append(e))
    return events, token


def test_the_meter_hears_a_hold_and_its_settle(fake_ledger):
    events, token = _heard()
    try:
        c = charge.Charge(7, provider="fal", ref="a.mp4", estimate_usd=0.36, quote=_Quote(87))
        c.take()
        c.submitted()
        assert c.settle() == 87
        assert c.settle() == 0                   # idempotent: said once
    finally:
        charge._meter.reset(token)
    assert events == [("hold", 87, 87, True), ("settle", 87, 87, True)]


def test_a_released_hold_spends_nothing(fake_ledger):
    events, token = _heard()
    try:
        c = charge.Charge(7, provider="fal", ref="b.mp4", estimate_usd=0.36)
        c.take()
        c.release("provider said no")
    finally:
        charge._meter.reset(token)
    assert events == [("hold", 87, 87, True), ("release", 0, 87, True)]


def test_an_uncharged_render_says_what_it_would_have_cost(fake_ledger):
    """The operator's exempt account holds nothing -- and the tray still
    says "87 cr · not charged", as the Queue does. One that never reached
    the provider says nothing at all."""
    events, token = _heard()
    try:
        ran = charge.Charge(None, provider="fal", ref="c.mp4", estimate_usd=0.36, quote=_Quote(87, None))
        ran.take()
        ran.submitted()
        assert ran.settle() == 0
        gated = charge.Charge(None, provider="fal", ref="d.mp4", estimate_usd=0.36)
        gated.take()
        gated.settle()
    finally:
        charge._meter.reset(token)
    assert events == [("spent", 87, 0, False)]


def test_a_listener_that_raises_never_touches_the_money(fake_ledger):
    def boom(*_):
        raise RuntimeError("tray fell over")

    token = charge.metering(boom)
    try:
        c = charge.Charge(7, provider="fal", ref="e.mp4", estimate_usd=0.36)
        c.take()
        assert c.settle() == 87
    finally:
        charge._meter.reset(token)


def _wait(job_id, timeout=5):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        job = jobs.get(job_id, account_id=7)
        if job and job["status"] in ("done", "failed", "cancelled"):
            return job
        time.sleep(0.02)
    raise AssertionError("job never finished")


def test_a_job_carries_what_it_spent_shot_by_shot(fake_ledger):
    """Two shots settle, one is released: the job says 174 credits spent,
    nothing held, charged -- the tray's running cost, landed."""
    seen = []

    def work(job):
        for n, outcome in enumerate(("settle", "settle", "release")):
            c = charge.Charge(7, provider="fal", ref=f"s{n}.mp4", estimate_usd=0.36)
            c.take()
            seen.append(jobs.get(job["id"], account_id=7)["credits_held"])
            c.settle() if outcome == "settle" else c.release("no")
        return {"ref_id": 3}

    job = _wait(jobs.start("render", "approved · Ridge Line", work, account_id=7)["id"])
    assert (job["credits"], job["credits_held"], job["charged"]) == (174, 0, True)
    assert seen == [87, 87, 87]                 # each shot's hold, while it ran


def test_an_exempt_job_says_not_charged(fake_ledger):
    def work(job):
        c = charge.Charge(None, provider="fal", ref="x.mp4", estimate_usd=0.36)
        c.take()
        c.submitted()
        c.settle()

    job = _wait(jobs.start("render", "approved", work, account_id=7)["id"])
    assert (job["credits"], job["charged"]) == (87, False)


def test_a_job_that_spends_nothing_has_no_credits_field():
    job = _wait(jobs.start("guide", "creative guide", lambda j: {"reply": "hi"}, account_id=7)["id"])
    assert "credits" not in job


def _drain(queue):
    out = []
    while not queue.empty():
        out.append(queue.get_nowait())
    return out


def test_a_cleared_job_is_said_on_the_stream():
    async def run():
        queue = jobs.subscribe()
        try:
            done = jobs.create("render", "r", account_id=7)
            jobs.update(done["id"], status="done")
            live = jobs.create("render", "r2", account_id=7)
            jobs.update(live["id"], status="running")
            await asyncio.sleep(0)
            _drain(queue)
            assert jobs.remove(live["id"], account_id=7) is False     # running stays
            assert jobs.remove(done["id"], account_id=7) is True
            await asyncio.sleep(0)
            return done["id"], _drain(queue)
        finally:
            jobs.unsubscribe(queue)

    cleared, said = asyncio.run(run())
    assert said == [{"id": cleared, "account_id": 7, "gone": True}]


def test_clearing_finished_clears_only_this_accounts_finished_jobs():
    mine = [jobs.create("render", f"m{i}", account_id=7) for i in range(3)]
    for j in mine[:2]:
        jobs.update(j["id"], status="done")
    theirs = jobs.create("render", "t", account_id=8)
    jobs.update(theirs["id"], status="done")
    assert jobs.clear_finished(account_id=7) == 2
    assert [j["id"] for j in jobs.list_jobs(account_id=7)] == [mine[2]["id"]]
    assert jobs.get(theirs["id"], account_id=8) is not None


def test_a_fresh_subscriber_gets_the_live_jobs_and_the_newest_finished(monkeypatch):
    finished = []
    for i in range(6):
        j = jobs.create("render", f"f{i}", account_id=7)
        jobs.update(j["id"], status="done")
        finished.append(j["id"])
    live = jobs.create("render", "live", account_id=7)
    jobs.update(live["id"], status="running")
    ids = [j["id"] for j in jobs.replay(account_id=7, finished=3)]
    # the live one and the three newest finished, newest first
    assert ids == [live["id"], *reversed(finished[-3:])]


def test_the_stream_opens_with_a_retry_hint_and_the_boot_and_is_never_compressed():
    j = jobs.create("render", "replayed", account_id=7)
    jobs.update(j["id"], status="done")
    jobs.create("render", "someone else's", account_id=8)

    async def first_frames():
        resp = await api_mod.jobs_stream(account_id=7)
        frames = []
        async for chunk in resp.body_iterator:
            frames.append(chunk)
            if len(frames) == 3:
                break
        await resp.body_iterator.aclose()
        return resp, frames

    resp, frames = asyncio.run(first_frames())
    assert "no-transform" in resp.headers["cache-control"]
    assert frames[0] == "retry: 3000\n\n"
    assert frames[1] == f"event: hello\ndata: {json.dumps({'boot': jobs.BOOT})}\n\n"
    assert frames[2].startswith("event: job\n") and '"label": "replayed"' in frames[2]


def test_bulk_clear_is_a_route_that_declares_its_account():
    from fastapi.testclient import TestClient

    import app.main as app_main
    from app import auth

    done = jobs.create("render", "r", account_id=None)
    jobs.update(done["id"], status="done")
    client = TestClient(app_main.app)
    app_main.app.dependency_overrides[auth.require_user_api] = lambda: {"id": "u"}
    try:
        res = client.delete("/api/jobs")
    finally:
        app_main.app.dependency_overrides.pop(auth.require_user_api, None)
    assert res.status_code == 200 and res.json() == {"cleared": 1}
