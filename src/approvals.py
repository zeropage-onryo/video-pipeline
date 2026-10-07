"""One exception for a refused approve, shared by the routes and the MCP tools.

The priced approves (`app/api.py`'s keyframes and render routes) used to
answer a refusal only as an HTTP response, which a tool in `src/` cannot
read. Their bodies now raise this and the routes translate it to the
JSON error they always sent; the MCP `approve` tool translates it to a
ToolError. It lives in `src/` because `src/` never imports `app/`, and
both sides need the one class.
"""
from __future__ import annotations


class ApproveRefused(Exception):
    """A deliberate no from an approve, with the HTTP status and code the
    route would have answered."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = int(status)
        self.code = code
        self.message = message
