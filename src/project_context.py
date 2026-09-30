"""The project a generation is running inside, for the prompts that read it.

A ContextVar rather than a parameter because the brand block is read in a
dozen prompt builders (`shootgen.load_brand`) several calls below the route
that knows the project, and threading an argument through every one of them
is how one builder gets missed and quietly writes without the brief. The
routes set it around the work (`active(project)`); scene_chain's worker
threads run on copied contexts, so they see it too. Unset means no project:
the studio's neutral block alone.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, Optional

_ACTIVE: ContextVar[Optional[dict]] = ContextVar("zeropage_project", default=None)


def current() -> Optional[dict]:
    return _ACTIVE.get()


@contextmanager
def active(project: Optional[dict]) -> Iterator[None]:
    token = _ACTIVE.set(project)
    try:
        yield
    finally:
        _ACTIVE.reset(token)


def block() -> str:
    """The text appended to the brand block, or "" outside a project."""
    project = current()
    if not project:
        return ""
    from . import projects
    return projects.brief_block(project)
