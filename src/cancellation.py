"""
"The person asked to stop this" -- carried from the job registry into the
adapters (2026-10-08, docs/tasks/task-mcp-studio-v2.md step 6).

A cancel is requested in one thread (the MCP `cancel_job` call) and has to
be noticed in another (the job's worker, deep inside an adapter). The job
registry lives in app/ and src/ never imports app/, so the registry binds a
CHECK here, in the worker thread, the way it binds the credit meter
(charge.metering) and the LLM meter (spend.bind); the adapters ask
`requested()` at the two places a cancel can still change what is spent:

- `charge.Charge.submitted()` -- the last line before the provider call.
  A cancel seen there releases the hold and raises `Cancelled`: nothing
  was sent, nothing is charged.
- `fal._submit_and_wait`'s poll loop -- the job is at fal. A cancel seen
  there is sent to fal's cancel URL, and fal's answer decides the money
  (see that function): no output, released; an output after all, charged
  and kept.

Outside a job, or in a job that was never made cancellable, `requested()`
is False and nothing anywhere behaves differently.
"""
from __future__ import annotations

import contextvars
from typing import Any, Callable, Optional

_check: contextvars.ContextVar[Optional[Callable[[], bool]]] = contextvars.ContextVar(
    "cancel_check", default=None)


class Cancelled(Exception):
    """A cancel took effect: the work stopped and its hold was released.
    `result` is what the caller had to say about it (the tool's own
    result), carried to the job's record."""

    def __init__(self, message: str, result: Optional[dict[str, Any]] = None):
        super().__init__(message)
        self.result = result


def bind(check: Optional[Callable[[], bool]]) -> contextvars.Token:
    """Ask `check` whether a cancel was requested, for the rest of this
    context (the job's worker thread). Returns the token to reset with."""
    return _check.set(check)


def reset(token: contextvars.Token) -> None:
    _check.reset(token)


def requested() -> bool:
    """Has the person asked to stop the work running in this context? A
    check that raises reads as no: this is never what breaks a render."""
    check = _check.get()
    if check is None:
        return False
    try:
        return bool(check())
    except Exception:  # noqa: BLE001 -- see docstring
        return False


__all__ = ["Cancelled", "bind", "reset", "requested"]
