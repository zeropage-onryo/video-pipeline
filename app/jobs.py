"""
In-process job registry for the /ui workspace.

Model-touching work (generate, plan, eval) runs in a daemon thread so
the API can answer immediately with a job id; progress and completion
are pushed to every subscribed SSE client. Single-operator tool on
localhost, so this is deliberately a dict guarded by a lock, not
Celery, not a table -- a restart clears the queue, and the queue view
says exactly that by being empty.

A job function receives its own job dict and may call progress() and
check cancelled() between steps. Cancellation is cooperative: a job
that never checks simply reports itself uncancellable and the UI
renders no Cancel button for it (no orphan controls, no lying ones).

Every job carries the account that started it (2026-09-02). In-memory
is fine; unattributed is not: the dry run's pilot user saw a job
labelled "Mike's private render" on /api/jobs and got 200 from its
cancel. The registry stays one dict, one process, one worker -- reads
and mutations just say whose jobs they mean, the same rule the tables
follow, with None meaning the unowned pool (a CLI, a test) exactly as
it does in the data layer.
"""
import asyncio
import itertools
import threading
import uuid
from datetime import datetime, timezone
from typing import Callable, Optional

_lock = threading.Lock()
_jobs: dict[int, dict] = {}
_ids = itertools.count(1)

# THIS PROCESS (2026-10-08). Ids restart at 1 with the registry, so a job
# id means nothing without the boot it was handed out in: the stream says
# this first, and a tab that saw another boot drops what it held instead
# of matching a new job 7 with an old one.
BOOT = uuid.uuid4().hex[:12]

# what a fresh subscriber is replayed: every live job, and this many of the
# newest finished ones -- a long-running process keeps every job it ever
# ran, and a reconnect must not resend all of them
REPLAY_FINISHED = 50

# (event loop, queue) pairs -- publish happens from worker threads, so
# each push is marshalled onto the subscriber's own loop.
_subscribers: list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = []


class JobCancelled(Exception):
    """Raised inside a job fn when it observes its cancel flag."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def snapshot(job: dict) -> dict:
    """A copy safe to serialise -- internal fields stay behind."""
    return {k: v for k, v in job.items() if not k.startswith("_")}


def _publish(job: dict) -> None:
    snap = snapshot(job)
    with _lock:
        subscribers = list(_subscribers)
    for loop, queue in subscribers:
        try:
            loop.call_soon_threadsafe(queue.put_nowait, snap)
        except RuntimeError:
            pass  # subscriber's loop is gone; unsubscribe cleans it up


def create(kind: str, label: str, cancellable: bool = False, *,
           account_id: Optional[int] = None) -> dict:
    with _lock:
        job = {
            "id": next(_ids),
            "kind": kind,
            "label": label,
            "status": "queued",
            "progress": 0.0,
            "detail": "",
            "error": None,
            "ref_id": None,
            "cancellable": cancellable,
            "started_at": _now(),
            "ended_at": None,
            "account_id": account_id,
            "_cancel": False,
        }
        _jobs[job["id"]] = job
    _publish(job)
    return job


def update(job_id: int, **fields) -> Optional[dict]:
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            return None
        job.update(fields)
    _publish(job)
    return job


def progress(job: dict, fraction: float, detail: str = "") -> None:
    fields = {"progress": max(0.0, min(1.0, fraction))}
    if detail:
        fields["detail"] = detail
    update(job["id"], **fields)


def cancelled(job: dict) -> bool:
    with _lock:
        current = _jobs.get(job["id"])
        return bool(current and current["_cancel"])


def check_cancelled(job: dict) -> None:
    if cancelled(job):
        raise JobCancelled()


def start(kind: str, label: str, fn: Callable[[dict], Optional[dict]],
          cancellable: bool = False, *,
          account_id: Optional[int] = None) -> dict:
    """
    Run fn(job) in a daemon thread. fn's return dict (if any) is folded
    into the finished job -- e.g. {"ref_id": 12, "detail": "..."}.
    `account_id` is whose job this is; every route passes the one it
    resolved, so the rail only ever shows a person their own work.
    """
    job = create(kind, label, cancellable=cancellable, account_id=account_id)

    def runner():
        # every Gemini call this job makes is metered to its account
        # (src/spend.py) -- bound here, in the worker thread, because a
        # contextvar set in the request thread never reaches it
        from src import spend
        spend.bind(account_id=account_id)
        _meter_credits(job["id"])
        update(job["id"], status="running")
        try:
            result = fn(job) or {}
            update(job["id"], status="done", progress=1.0,
                   ended_at=_now(), **result)
        except JobCancelled:
            update(job["id"], status="cancelled", ended_at=_now())
        except Exception as e:  # surfaced, never silent
            update(job["id"], status="failed", error=str(e), ended_at=_now())

    threading.Thread(target=runner, daemon=True).start()
    return job


def _meter_credits(job_id: int) -> None:
    """What this job spends, on the job, as it spends it (2026-10-08). Every
    Charge made in this worker thread (src/charge.metering) reports here:
    `credits` is what has been debited (or, uncharged, what it would have
    cost), `credits_held` what is held right now -- a multi-shot render's
    running cost -- and `charged` False only when nothing was billed. Lazy
    and best-effort: this registry imports nothing heavy at module level
    (the MCP stdio server loads it), and a job that cannot meter still runs."""
    try:
        from src import charge
    except Exception:  # noqa: BLE001
        return
    tally = {"held": 0, "spent": 0, "charged": None}

    def heard(event: str, credits: int, held: int, charged: bool) -> None:
        if event == "hold":
            tally["held"] += held
        elif event == "settle":
            tally["held"] -= held
            tally["spent"] += credits
        elif event == "release":
            tally["held"] -= held
        elif event == "spent":
            tally["spent"] += credits
        tally["charged"] = charged if tally["charged"] is None else (tally["charged"] or charged)
        update(job_id, credits=tally["spent"], credits_held=max(0, tally["held"]),
               charged=bool(tally["charged"]))

    charge.metering(heard)


def owned_by(job: Optional[dict], account_id: Optional[int]) -> bool:
    """The one predicate every read and mutation goes through. NULL is
    the unowned pool, matched only by None -- `IS`, not `=`."""
    return job is not None and job.get("account_id") == account_id


def cancel(job_id: int, *, account_id: Optional[int] = None) -> Optional[dict]:
    """None for someone else's job, same as for a missing id."""
    with _lock:
        job = _jobs.get(job_id)
        if not owned_by(job, account_id):
            return None
        if job["status"] == "queued":
            job.update(status="cancelled", ended_at=_now())
        elif job["status"] == "running" and job["cancellable"]:
            job["_cancel"] = True
            job["detail"] = "cancel requested"
    _publish(job)
    return job


def remove(job_id: int, *, account_id: Optional[int] = None) -> Optional[bool]:
    """Clear a finished job from the rail. Running jobs stay visible.
    None when there is no such job of yours (the route's 404), False
    when it is yours but not finished (409), True when cleared."""
    with _lock:
        job = _jobs.get(job_id)
        if not owned_by(job, account_id):
            return None
        if job["status"] in ("queued", "running"):
            return False
        del _jobs[job_id]
    _publish_gone(job_id, account_id)
    return True


def clear_finished(*, account_id: Optional[int] = None) -> int:
    """Clear every finished job of this account's at once -- the tray's
    "Clear finished". Returns how many went."""
    with _lock:
        done = [jid for jid, j in _jobs.items()
                if owned_by(j, account_id) and j["status"] not in ("queued", "running")]
        for jid in done:
            del _jobs[jid]
    for jid in done:
        _publish_gone(jid, account_id)
    return len(done)


def _publish_gone(job_id: int, account_id: Optional[int]) -> None:
    """Tell the stream a job was cleared, so every open tab drops it. Never
    used to be said at all: a job cleared in one tab stayed in the others."""
    with _lock:
        subscribers = list(_subscribers)
    note = {"id": job_id, "account_id": account_id, "gone": True}
    for loop, queue in subscribers:
        try:
            loop.call_soon_threadsafe(queue.put_nowait, note)
        except RuntimeError:
            pass


def replay(*, account_id: Optional[int] = None,
           finished: int = REPLAY_FINISHED) -> list[dict]:
    """What a fresh subscriber is sent: every live job of this account's
    and its `finished` newest finished ones, newest first."""
    rows = list_jobs(account_id=account_id)
    live = [j for j in rows if j["status"] in ("queued", "running")]
    ended = [j for j in rows if j["status"] not in ("queued", "running")][:finished]
    return sorted(live + ended, key=lambda j: j["id"], reverse=True)


def get(job_id: int, *, account_id: Optional[int] = None) -> Optional[dict]:
    with _lock:
        job = _jobs.get(job_id)
        return snapshot(job) if owned_by(job, account_id) else None


def list_jobs(active: Optional[bool] = None, *,
              account_id: Optional[int] = None) -> list[dict]:
    with _lock:
        rows = [snapshot(j) for j in _jobs.values()
                if owned_by(j, account_id)]
    if active is True:
        rows = [j for j in rows if j["status"] in ("queued", "running")]
    return sorted(rows, key=lambda j: j["id"], reverse=True)


def subscribe() -> asyncio.Queue:
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    with _lock:
        _subscribers.append((loop, queue))
    return queue


def unsubscribe(queue: asyncio.Queue) -> None:
    with _lock:
        _subscribers[:] = [(lp, q) for lp, q in _subscribers if q is not queue]


def clear_all_for_tests() -> None:
    with _lock:
        _jobs.clear()
        _subscribers.clear()
