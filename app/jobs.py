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
"""
import asyncio
import itertools
import threading
from datetime import datetime, timezone
from typing import Callable, Optional

_lock = threading.Lock()
_jobs: dict[int, dict] = {}
_ids = itertools.count(1)

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


def create(kind: str, label: str, cancellable: bool = False) -> dict:
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
          cancellable: bool = False) -> dict:
    """
    Run fn(job) in a daemon thread. fn's return dict (if any) is folded
    into the finished job -- e.g. {"ref_id": 12, "detail": "..."}.
    """
    job = create(kind, label, cancellable=cancellable)

    def runner():
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


def cancel(job_id: int) -> Optional[dict]:
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            return None
        if job["status"] == "queued":
            job.update(status="cancelled", ended_at=_now())
        elif job["status"] == "running" and job["cancellable"]:
            job["_cancel"] = True
            job["detail"] = "cancel requested"
    _publish(job)
    return job


def remove(job_id: int) -> bool:
    """Clear a finished job from the rail. Running jobs stay visible."""
    with _lock:
        job = _jobs.get(job_id)
        if job is None or job["status"] in ("queued", "running"):
            return False
        del _jobs[job_id]
    return True


def get(job_id: int) -> Optional[dict]:
    with _lock:
        job = _jobs.get(job_id)
        return snapshot(job) if job else None


def list_jobs(active: Optional[bool] = None) -> list[dict]:
    with _lock:
        rows = [snapshot(j) for j in _jobs.values()]
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
