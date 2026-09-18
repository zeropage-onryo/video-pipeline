"""The board, reachable from the Guide (2026-09-18).

The React studio's Guide answers questions about the board and proposes
actions, Notion-"Ask AI" shaped. This module is the bridge between it
and this repo's OWN MCP server -- the same surface `research_agent`
drives at night -- opened IN-PROCESS: `mcp.Client` accepts an
`MCPServer` instance and talks to it directly, so a request handler
gets the tools with no subprocess, no bearer token and no network.

Reused, not rewritten: tool names, descriptions and argument schemas
come off `list_tools()`, exactly as `research_agent._as_tools` reads
them, so a tool added in `build_server` appears here with no change to
this file. What THIS file adds is the policy the handoff fixed:

- **A closed set, split read from write.** `READ_TOOLS` run on their
  own inside a Guide turn; `WRITE_TOOLS` never run from the model's
  say-so -- the turn returns a proposal, the thread draws a confirm
  card, and the click is what calls `run`. Anything not in either set
  is not published to the model and is refused if named.
- **No engine.** The server is built with `engine=False`, explicitly,
  the way `research_agent._server_env` strips the variable: `.env` has
  `ZEROPAGE_MCP_ENGINE=1` on and the server loads `.env` itself, so
  merely not setting it is not enough. `research` and `generate` are
  not reachable from a chat box.
- **Nothing here spends the clip, or approves one.** No tool in this
  set reaches `generate_video`, and nothing passes `approved=True`; the
  Guide may say "ready to render, here's the price" and point at the
  Queue, whose button is still the click that spends. `pick` (which
  draws a still, cents) is deliberately NOT in the set either: Studio
  types the idea, Pipeline decides, Queue spends -- this is
  read-and-propose and does not absorb the other two.
- **Closed-set ids, never URLs.** The first live research run banked
  six fabricated Unsplash URLs that all 404'd, and a generic CDN path
  that "succeeded" put a Harley product shot on a zeropage spark. An
  omnibox invites exactly that, so `check_args` refuses any argument
  that looks like a URL before the tool sees it: `reference` takes a
  `candidate_id` from `images_for` and nothing else.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from . import mcp_server
from .research_agent import _result_text, _sync

# The four the handoff named, plus `images_for` -- `reference` takes a
# candidate id and nothing else, and the search is where ids come from.
READ_TOOLS = ("board", "sparks", "stats", "tonight", "images_for")
# Return a confirm card into the thread; run only on the click.
WRITE_TOOLS = ("add_spark", "reference")
TOOLS = READ_TOOLS + WRITE_TOOLS

# What a person sees on the confirm card, per write tool.
WRITE_LABELS = {
    "add_spark": "Bank this spark for the nightly run",
    "reference": "Bank this reference image behind the spark",
}

MAX_TOOL_CALLS = 6      # read calls per turn; a Guide answer, not a crawl

_URL = re.compile(r"(?i)\b(?:https?|ftp)://|\bwww\.|\.(?:jpe?g|png|webp|gif)(?:\?|$)")


class Refused(ValueError):
    """A call this bridge will not make -- the message is for the person."""


def is_write(name: str) -> bool:
    return name in WRITE_TOOLS


def available() -> bool:
    """Whether the `mcp` package is importable. The Guide degrades to
    its plain conversation when it is not, rather than 500ing."""
    try:
        import mcp  # noqa: F401
    except ImportError:
        return False
    return True


def build(dsn: Optional[str] = None, account_id: Optional[int] = None):
    """The in-process server, engine OFF, acting as the caller's account."""
    return mcp_server.build_server(dsn=dsn, account_id=account_id, engine=False)


def check_args(name: str, args: dict) -> dict:
    """Refuse a call outside the set, or one carrying a URL.

    The URL rule is checked on every string argument, not only the two
    named `*_url`: a model told "no URLs" puts one in `title` next.
    """
    if name not in TOOLS:
        raise Refused(f"`{name}` is not reachable from the Guide")
    args = dict(args or {})
    for key, value in args.items():
        if isinstance(value, str) and _URL.search(value):
            raise Refused(f"`{name}` does not take a URL ({key}); "
                          "pass a candidate id from images_for instead")
    if name == "reference":
        for key in ("image_url", "source_url"):
            if args.get(key):
                raise Refused("`reference` takes a candidate_id from images_for, never a URL")
            args.pop(key, None)
        if not args.get("candidate_id"):
            raise Refused("`reference` needs a candidate_id from images_for")
    return args


async def specs(client) -> list[dict[str, Any]]:
    """The published tools, as {name, description, input_schema} --
    only the closed set, in the order the server reports them."""
    out = []
    for spec in (await client.list_tools()).tools:
        if spec.name in TOOLS:
            out.append({"name": spec.name, "description": spec.description or "",
                        "input_schema": spec.input_schema or {"type": "object", "properties": {}},
                        "write": is_write(spec.name)})
    return out


async def call(client, name: str, args: dict) -> str:
    """One tool call, policy-checked, as the text a model (or a card)
    should see. A ToolError's text comes back as text -- the message IS
    the useful part (an unknown id, a bad brand)."""
    args = check_args(name, args)
    return _result_text(await client.call_tool(name, args))


def run(name: str, args: dict, *, dsn: Optional[str] = None,
        account_id: Optional[int] = None) -> str:
    """Run ONE tool, synchronously, on a fresh in-process client.

    The confirm card's click lands here (write tools), and it is also
    the simplest way for a test to exercise the bridge end to end.
    """
    from mcp import Client

    # Checked BEFORE the client opens: a refusal raised inside the
    # session's task group comes back wrapped in an ExceptionGroup,
    # which no caller can catch as the Refused it is.
    args = check_args(name, args)

    async def go():
        async with Client(build(dsn=dsn, account_id=account_id)) as client:
            return await call(client, name, args)
    return _sync(go())


def session(dsn: Optional[str] = None, account_id: Optional[int] = None):
    """Everything a Guide turn needs, gathered once: the tool specs for
    the model, and a synchronous `run_tool(name, args)` for the READ
    calls the model makes mid-turn.

    Opens a client per call rather than holding one across the turn:
    the model call in between takes tens of seconds, the turn runs on a
    job thread with no event loop, and an in-process client is cheap to
    open. Returns (specs, run_tool).
    """
    from mcp import Client

    async def list_specs():
        async with Client(build(dsn=dsn, account_id=account_id)) as client:
            return await specs(client)

    tool_specs = _sync(list_specs())

    def run_tool(name: str, args: dict) -> str:
        if is_write(name):
            raise Refused(f"`{name}` writes; it needs a click, not a model")
        return run(name, args, dsn=dsn, account_id=account_id)

    return tool_specs, run_tool
