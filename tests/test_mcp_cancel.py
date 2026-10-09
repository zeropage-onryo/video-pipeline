"""
Cancelling a render from the studio MCP (2026-10-08, docs/tasks/
task-mcp-studio-v2.md step 6).

The rule being guarded is the one the person is told: what a cancel gives
back depends on how far the job got, and the money follows fal's own
answer, never the request alone --

- before the provider call: stopped, the hold released (charge.submitted)
- waiting at fal, or running and fal stops it: fal says so (an error
  payload, a 404/499, no output) -> released
- running and fal finishes it anyway, or it had already finished: kept and
  charged at the quoted price

fal's contract (fal.ai/docs/model-apis/model-endpoints/queue, read
2026-10-08): PUT {cancel_url} -> 202 CANCELLATION_REQUESTED, 400
ALREADY_COMPLETED, 404 NOT_FOUND; a running job "may still complete"; fal
bills only successful outputs.
"""

import asyncio
import json
import threading
import time
import types
import urllib.error
from pathlib import Path

import pytest

from app import jobs
from src import (
    accounts,
    cancellation,
    db,
    fal,
    generative,
    ledger,
    mcp_server,
    pricing,
    quote_redemptions,
)
from src import charge as charging


@pytest.fixture(autouse=True)
def _fresh_registry():
    jobs.clear_all_for_tests()
    yield
    jobs.clear_all_for_tests()


@pytest.fixture
def asked():
    """Run the test body as if the person had asked to stop."""
    token = cancellation.bind(lambda: True)
    yield
    cancellation.reset(token)


def _http_error(code):
    """What fal._request raises for an HTTP error: a RuntimeError carrying
    fal's body, the HTTPError as its cause."""
    try:
        raise urllib.error.HTTPError("https://queue.fal.run/x", code, "x", None, None)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP Error {code}") from e


# --------------------------------------------------------------------------
# before the provider call: the hold goes back, nothing is sent
# --------------------------------------------------------------------------

@pytest.fixture
def funded_account(pg):
    accounts.seed("mike@example.com", dsn=pg)
    ledger.init(pg)
    with db.connect(pg) as conn:
        account_id = int(conn.execute("SELECT MIN(id) AS id FROM accounts").fetchone()["id"])
    ledger.grant(account_id, 1000, "purchase", dsn=pg)
    return {"dsn": pg, "account_id": account_id}


def test_a_cancel_before_the_submit_releases_the_hold(funded_account, asked):
    dsn, acct = funded_account["dsn"], funded_account["account_id"]
    charge = charging.Charge(acct, provider="fal", ref="cancel-before", estimate_usd=0.04,
                             dsn=dsn)
    charge.take()
    assert ledger.available(acct, dsn=dsn) < 1000
    with pytest.raises(cancellation.Cancelled, match="nothing was charged"):
        charge.submitted()
    assert charge.attempted is False          # no provider call: no failed-attempt row owed
    assert ledger.available(acct, dsn=dsn) == 1000


def test_outside_a_cancel_submitted_is_unchanged(funded_account):
    charge = charging.Charge(funded_account["account_id"], provider="fal", ref="plain",
                             estimate_usd=0.04, dsn=funded_account["dsn"])
    charge.take()
    charge.submitted()
    assert charge.attempted is True


# --------------------------------------------------------------------------
# while fal has it: fal's answer decides
# --------------------------------------------------------------------------

SUBMIT = {"request_id": "r1", "status_url": "https://q/s", "response_url": "https://q/r",
          "cancel_url": "https://q/c"}
DONE = {"status": "COMPLETED"}
OUTPUT = {"images": [{"url": "https://cdn/out.jpg"}]}


class FakeFal:
    """The queue, scripted: each status poll pops the next answer (an
    exception is raised); the cancel answers `cancel_reply` (raised when
    it is an exception)."""

    def __init__(self, statuses, cancel_reply, result=OUTPUT):
        self.statuses = list(statuses)
        self.cancel_reply = cancel_reply
        self.result = result
        self.cancels = 0
        self.polls = 0

    def __call__(self, url, payload=None):
        if payload is fal.CANCEL:
            self.cancels += 1
            reply = self.cancel_reply.pop(0) if isinstance(self.cancel_reply, list) \
                else self.cancel_reply
            if isinstance(reply, Exception):
                raise reply
            if callable(reply):
                return reply()
            return reply
        if payload is not None:
            return dict(SUBMIT)
        if url == SUBMIT["status_url"]:
            self.polls += 1
            answer = self.statuses.pop(0) if self.statuses else DONE
            if callable(answer):
                return answer()
            return answer
        if callable(self.result):
            return self.result()
        return self.result


@pytest.fixture(autouse=True)
def _no_wait(monkeypatch):
    monkeypatch.setattr(fal, "POLL_SECONDS", 0)


def _run(fake):
    return fal._submit_and_wait("fal-ai/x", {}, http=fake)


def test_no_cancel_no_put():
    fake = FakeFal([{"status": "IN_QUEUE"}], cancel_reply={"status": "CANCELLATION_REQUESTED"})
    result, _ = _run(fake)
    assert result == OUTPUT and fake.cancels == 0


def test_a_queued_job_that_fal_drops_is_cancelled(asked):
    fake = FakeFal([{"status": "COMPLETED", "detail": "Request was cancelled",
                     "error_type": "client_cancelled"}],
                   cancel_reply={"status": "CANCELLATION_REQUESTED"})
    with pytest.raises(cancellation.Cancelled, match="nothing was charged"):
        _run(fake)
    assert fake.cancels == 1


@pytest.mark.parametrize("code", [404, 410, 499])
def test_a_job_that_is_gone_after_the_cancel_is_cancelled(asked, code):
    def gone():
        _http_error(code)
    fake = FakeFal([gone], cancel_reply={"status": "CANCELLATION_REQUESTED"})
    with pytest.raises(cancellation.Cancelled):
        _run(fake)


def test_a_job_fal_finishes_anyway_is_kept(asked):
    """A running job "may still complete": an output is an output, and it
    is billed -- so it is returned, settled and filed, not thrown away."""
    fake = FakeFal([{"status": "IN_PROGRESS"}], cancel_reply={"status": "CANCELLATION_REQUESTED"})
    result, _ = _run(fake)
    assert result == OUTPUT and fake.cancels == 1


def test_a_job_that_finished_with_no_output_after_the_cancel_is_cancelled(asked):
    fake = FakeFal([], cancel_reply={"status": "CANCELLATION_REQUESTED"}, result={"ok": 1})
    with pytest.raises(cancellation.Cancelled, match="no output"):
        _run(fake)


def test_already_completed_is_too_late(asked):
    def already():
        _http_error(400)
    fake = FakeFal([], cancel_reply=already)
    result, _ = _run(fake)
    assert result == OUTPUT and fake.cancels == 1


def test_not_found_is_cancelled_at_once(asked):
    def missing():
        _http_error(404)
    fake = FakeFal([{"status": "IN_QUEUE"}] * 5, cancel_reply=missing)
    with pytest.raises(cancellation.Cancelled, match="no longer has"):
        _run(fake)
    assert fake.polls == 0


def test_no_answer_from_fal_is_asked_again_and_assumes_nothing(asked):
    """A network error on the cancel is not a cancel: nothing is released
    on it, and the cancel is sent again on the next poll."""
    def down():
        _http_error(503)
    fake = FakeFal([{"status": "IN_QUEUE"}, {"status": "IN_QUEUE"}, {
        "status": "COMPLETED", "detail": "cancelled", "error_type": "client_cancelled"}],
        cancel_reply=[RuntimeError("connection reset"), _raising(down),
                      {"status": "CANCELLATION_REQUESTED"}])
    with pytest.raises(cancellation.Cancelled):
        _run(fake)
    assert fake.cancels == 3


def _raising(fn):
    """A scripted reply that raises when it is played."""
    return lambda: fn()


def test_without_a_cancel_an_error_payload_is_still_a_failure():
    fake = FakeFal([{"status": "COMPLETED", "detail": "boom", "error_type": "x"}],
                   cancel_reply={})
    with pytest.raises(RuntimeError, match="fal job failed") as e:
        _run(fake)
    assert not isinstance(e.value, cancellation.Cancelled)


def test_the_put_has_no_body_and_uses_put(monkeypatch):
    seen = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"status": "CANCELLATION_REQUESTED"}'

    def urlopen(req, timeout=None):
        seen.update(method=req.get_method(), data=req.data, url=req.full_url)
        return Response()

    monkeypatch.setattr(fal, "_credential", lambda account_id=None: "k")
    monkeypatch.setattr(fal.urllib.request, "urlopen", urlopen)
    assert fal._request("https://q/c", fal.CANCEL) == {"status": "CANCELLATION_REQUESTED"}
    assert seen == {"method": "PUT", "data": b"", "url": "https://q/c"}


# --------------------------------------------------------------------------
# the job registry
# --------------------------------------------------------------------------

def _wait(job_id, account_id=None, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        snap = jobs.get(job_id, account_id=account_id)
        if snap and snap["status"] in mcp_server.FINISHED:
            return snap
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} never finished: "
                         f"{jobs.get(job_id, account_id=account_id)}")


def test_a_job_cancelled_while_queued_never_runs(monkeypatch):
    started = []

    class Later:
        def __init__(self, target, daemon=None):
            self.target = target

        def start(self):
            started.append(self.target)

    monkeypatch.setattr(jobs.threading, "Thread", Later)
    ran = []
    job = jobs.start("mcp", "x", lambda j: ran.append(1), cancellable=True)
    jobs.cancel(job["id"])
    started[0]()                         # the worker gets there after the cancel
    assert ran == [] and jobs.get(job["id"])["status"] == "cancelled"


def test_the_worker_can_see_a_cancel_and_says_what_it_gave_back():
    release = threading.Event()

    def body(job):
        release.wait(5)
        assert cancellation.requested()
        raise cancellation.Cancelled("stopped; 10 credits released", result={"ok": False})

    job = jobs.start("mcp", "x", body, cancellable=True)
    jobs.cancel(job["id"])
    release.set()
    snap = _wait(job["id"])
    assert snap["status"] == "cancelled" and "10 credits released" in snap["detail"]
    assert snap["result"] == {"ok": False}


def test_a_job_nobody_made_cancellable_never_sees_one():
    release, seen = threading.Event(), []

    def body(job):
        release.wait(5)
        seen.append(cancellation.requested())
        return {}

    job = jobs.start("q", "queue render", body)
    jobs.cancel(job["id"])
    release.set()
    assert _wait(job["id"])["status"] == "done" and seen == [False]


# --------------------------------------------------------------------------
# what cancel_job says
# --------------------------------------------------------------------------

def _ask(snap, after=None):
    return mcp_server.cancel_studio_job(
        7, job_status=lambda i, account_id=None: snap,
        cancel=lambda i, account_id=None: after, account_id=None)


def test_an_unknown_job_is_a_caller_error():
    with pytest.raises(ValueError, match="no job 7"):
        _ask(None)


def test_a_finished_job_has_nothing_to_cancel_and_says_what_it_cost():
    out = _ask({"id": 7, "status": "done", "credits": 10, "charged": True, "cancellable": True})
    assert out["cancelled"] is False and "nothing to cancel" in out["note"]
    assert "10 credits" in out["note"]


def test_a_job_this_connector_did_not_start_is_not_pretended_at():
    out = _ask({"id": 7, "status": "running", "cancellable": False})
    assert out["cancelled"] is False and "cannot be cancelled" in out["note"]


def test_a_queued_job_is_cancelled_outright():
    out = _ask({"id": 7, "status": "queued", "cancellable": True},
               after={"id": 7, "status": "cancelled"})
    assert out["cancelled"] is True and "nothing was held" in out["note"]


def test_a_running_job_is_asked_and_the_outcomes_are_spelled_out():
    out = _ask({"id": 7, "status": "running", "cancellable": True},
               after={"id": 7, "status": "running"})
    assert out["cancel_requested"] is True and out["cancelled"] is False
    for words in ("nothing charged", "charged at the quoted price", "too late"):
        assert words in out["note"]


def test_cancel_job_is_on_the_studio_never_on_the_listed_server(pg, monkeypatch):
    monkeypatch.setenv(mcp_server.ENGINE_ENV, "1")

    def names(**kw):
        server = mcp_server.build_server(dsn=pg, job_status=lambda i, account_id=None: None,
                                         cancel_job=lambda i, account_id=None: None, **kw)
        return {t.name for t in asyncio.run(server.list_tools())}

    assert "cancel_job" in names(surface="studio")
    assert "cancel_job" in names()                      # the board, under the engine flag
    assert "cancel_job" not in names(listed=True)
    monkeypatch.delenv(mcp_server.ENGINE_ENV)
    assert "cancel_job" not in names()                  # no spending tools, nothing to stop


# --------------------------------------------------------------------------
# the conversation: approve, then cancel mid-job -- real job threads, the
# real ledger and the real image door; only fal's wire is stood in for
# --------------------------------------------------------------------------

@pytest.fixture
def studio(pg, monkeypatch):
    from src import preprod, render_assets
    monkeypatch.setenv("DATABASE_URL", pg)
    monkeypatch.setenv(pricing.SIGNING_ENV, "test-quote-secret")
    generative.init(pg)
    preprod.init(pg)
    accounts.seed("mike@example.com", dsn=pg)
    ledger.init(pg)
    render_assets.init(pg)
    quote_redemptions.init(pg)
    with db.connect(pg) as conn:
        account_id = int(conn.execute("SELECT MIN(id) AS id FROM accounts").fetchone()["id"])
    ledger.grant(account_id, 1000, "purchase", dsn=pg)
    monkeypatch.setattr(fal, "_download",
                        lambda url, out: Path(out).parent.mkdir(parents=True, exist_ok=True)
                        or Path(out).write_bytes(b"\xff\xd8 jpeg"))
    monkeypatch.setattr(fal, "_publish", lambda path, ctype, acct: "https://r2/still.jpg")
    monkeypatch.setattr(render_assets, "_ingest",
                        lambda *a, **k: {"ok": True, "chunks": 1, "error": None})
    server = mcp_server.build_server(dsn=pg, surface="studio", start_job=jobs.start,
                                     job_status=jobs.get, cancel_job=jobs.cancel,
                                     account_id=account_id)
    return types.SimpleNamespace(dsn=pg, account_id=account_id, server=server)


def _call(server, tool, args):
    out = asyncio.run(server.call_tool(tool, args))
    return json.loads(out.content[0].text)


IMAGE = {"prompt": "a dented can on wet tile", "model": "seedream4.5"}


def _fal_wire(monkeypatch, after_cancel):
    """fal's wire: the first status poll blocks until the test has asked
    to cancel (so the cancel lands while fal has the job), then answers
    IN_QUEUE; the cancel is accepted; `after_cancel` is what the next
    poll says."""
    polled, go = threading.Event(), threading.Event()
    seen = {"cancels": 0, "polls": 0}

    def wire(url, payload=None, account_id=None):
        if payload is fal.CANCEL:
            seen["cancels"] += 1
            return {"status": "CANCELLATION_REQUESTED"}
        if payload is not None:
            return dict(SUBMIT)
        if url == SUBMIT["status_url"]:
            seen["polls"] += 1
            if seen["polls"] == 1:
                polled.set()
                go.wait(10)
                return {"status": "IN_QUEUE"}
            return after_cancel
        return OUTPUT

    monkeypatch.setattr(fal, "_request", wire)
    return polled, go, seen


def test_cancel_mid_job_refunds_when_fal_drops_it(studio, monkeypatch):
    polled, go, seen = _fal_wire(monkeypatch, {
        "status": "COMPLETED", "detail": "Request was cancelled", "error_type": "client_cancelled"})
    q = _call(studio.server, "generate_image", IMAGE)["quote"]
    started = _call(studio.server, "generate_image", {**IMAGE, "quote_token": q["quote_token"]})
    assert "cancel_job" in started["note"]
    assert polled.wait(10)                                  # fal has it, credit is held
    assert ledger.available(studio.account_id, dsn=studio.dsn) == 1000 - q["credits"]
    asked = _call(studio.server, "cancel_job", {"job_id": started["job_id"]})
    assert asked["cancel_requested"] is True
    go.set()
    snap = _wait(started["job_id"], studio.account_id)
    assert snap["status"] == "cancelled" and "nothing was charged" in snap["detail"]
    assert seen["cancels"] == 1
    assert ledger.available(studio.account_id, dsn=studio.dsn) == 1000   # given back
    kinds = [e["kind"] for e in ledger.entries(studio.account_id, studio.dsn)]
    assert "release" in kinds and "settle" not in kinds


def test_cancel_mid_job_too_late_keeps_and_charges(studio, monkeypatch):
    polled, go, seen = _fal_wire(monkeypatch, DONE)          # fal finished it anyway
    q = _call(studio.server, "generate_image", IMAGE)["quote"]
    started = _call(studio.server, "generate_image", {**IMAGE, "quote_token": q["quote_token"]})
    assert polled.wait(10)
    _call(studio.server, "cancel_job", {"job_id": started["job_id"]})
    go.set()
    snap = _wait(started["job_id"], studio.account_id)
    assert snap["status"] == "done" and snap["result"]["ok"] is True
    assert snap["result"]["cancel_too_late"] is True and snap["result"]["asset_id"]
    assert ledger.available(studio.account_id, dsn=studio.dsn) == 1000 - q["credits"]


def test_a_clip_cancelled_at_fal_is_released_and_logged_as_an_attempt(
        funded_account, monkeypatch):
    """The video door: fal's receipt is written at submit, so a cancel that
    lands while fal has the clip resolves that receipt (the recovery sweep
    must never pick it up and settle it), releases the hold, and leaves a
    failed generations row -- the attempt reached fal, and every attempt
    is a row."""
    from src import fal_requests
    dsn, acct = funded_account["dsn"], funded_account["account_id"]
    monkeypatch.setenv("FAL_KEY", "k")
    generative.init(dsn)
    from src import preprod
    preprod.init(dsn)
    fake = FakeFal([{"status": "IN_QUEUE"}, {
        "status": "COMPLETED", "detail": "Request was cancelled",
        "error_type": "client_cancelled"}],
        cancel_reply={"status": "CANCELLATION_REQUESTED"},
        result={"video": {"url": "https://cdn/out.mp4"}})
    token = cancellation.bind(lambda: fake.polls >= 1)    # asked once fal has it
    try:
        out = fal.generate_from_prompt("a can", model="ltx2.3", duration=6, http=fake,
                                       db_path=dsn, approved=True, account_id=acct)
    finally:
        cancellation.reset(token)
    assert out["ok"] is False and "nothing was charged" in out["error"]
    assert fake.cancels == 1
    assert ledger.available(acct, dsn=dsn) == 1000
    with db.connect(dsn) as conn:
        receipt = conn.execute("SELECT resolved_at, outcome FROM fal_requests "
                               "WHERE account_id = %s", (acct,)).fetchone()
        rows = conn.execute("SELECT COUNT(*) AS n FROM generations "
                            "WHERE account_id = %s", (acct,)).fetchone()["n"]
    assert receipt["resolved_at"] and "cancelled" in receipt["outcome"]
    assert rows == 1
    assert fal_requests.open_count(acct, dsn=dsn) == 0
