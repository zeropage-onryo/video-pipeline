#!/usr/bin/env python3
"""
src/research_agent.py -- the research node's engine: a Claude agent that
fills the scout's bank, driving THIS repo's own MCP server.

    orchestrator.research  ->  research_agent.run()
                                    |
                                    |  stdio, no --engine
                                    v
                            python -m src.mcp_server
                                    |
                            bank_spark / bank_reference / list_sparks / ...
                                    v
                            scout_findings + scout_bin
                                    |
    orchestrator.scout  <-----------'   (unchanged: it drains what this fills)

WHY THE MCP TRANSPORT AND NOT A DIRECT IMPORT.

`src/mcp_server.py`'s functions are plain Python and this module could
call them in-process, saving a subprocess and the async plumbing below.
It does not, for one reason that outweighs both: the agent-facing tool
surface would then exist TWICE -- once as MCP tools with the
descriptions and schemas Mike wrote for a model to read, and once as
whatever LangChain tool wrappers were hand-written here. Two definitions
of "what an agent may do to the board" is the drift bug this repo has
already paid for in asset_shelf and refbin, and this copy would be the
one nobody reads.

Going over stdio means the tools the 6am run gets are the SAME twelve
Claude Desktop shows, from the same registration in `build_server`. What
Mike tests by hand is what runs unattended. That is worth a subprocess.

WHY NOT `langchain-mcp-adapters`, WHICH DOES EXACTLY THIS.

Because it cannot be installed here. `langchain-mcp-adapters` 0.3.2
requires `mcp<2.0.0`, and this repo requires `mcp>=2` -- a pin
requirements.txt already calls load-bearing, because v2 renamed FastMCP
to MCPServer and `build_server` imports the new path. Installing the
adapter downgrades mcp to 1.29.1 and `src/mcp_server.py` stops importing
at all: the library meant to drive the server breaks the server. Checked
against the wheel's own metadata, 2026-09-01, not guessed.

So the bridge is written against the `mcp` 2.x client already in the
venv. It is about forty lines and it costs nothing in duplication that
matters, because the tool NAMES, DESCRIPTIONS and SCHEMAS are read off
the running server with `list_tools()` -- they are still written once,
in `build_server`, and this only wraps whatever it reports.

THE SERVER IS LAUNCHED WITHOUT `--engine`, WHICH IS THE POINT.
`ENGINE_TOOLS` (`run_research`, `run_graph`) are the two that spend, and
`run_graph` invokes the very graph this node is a member of. An agent
handed that tool can fire a full nightly run from inside a nightly run,
recursively, at Runway prices. The gate already exists (`engine_enabled`
reads ZEROPAGE_MCP_ENGINE); this just declines to open it, and the
subprocess gets an environment with the variable stripped rather than
trusting .env not to contain it.

NEVER RAISES, AND IS NEVER THE ONLY TIER. It fills the bank; it does not
decide the night. A missing key, a missing package, a dead API or an
agent that banks nothing all end the same way -- the bank is whatever it
was, `scout` reads it, and a thin bank falls through to the sparks.txt
rotation. Three tiers, and this is only the first.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Optional

from . import scout

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DIGEST_PROMPT_PATH = PROJECT_ROOT / "prompts" / "scout_digest_prompt.txt"
BRIEF_PATH = PROJECT_ROOT / "prompts" / "research_agent_brief.txt"

# WHICH MODEL DRIVES IT. Gemini by default, on the key this repo already
# has (Mike's call, 2026-09-01) -- the node is switchable rather than
# tied to a provider, because the argument for it was never about which
# model: it is that SOMETHING in the unattended path has to decide,
# instead of draining a queue nobody filled.
#
# Explicit RESEARCH_PROVIDER wins; otherwise whichever key exists,
# Gemini first. An Anthropic key is optional and nothing here needs one.
PROVIDERS = ("gemini", "anthropic")
DEFAULT_MODELS = {"gemini": "gemini-3-flash-preview",
                  "anthropic": "claude-sonnet-4-6"}
PROVIDER_KEYS = {"gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
                 "anthropic": ("ANTHROPIC_API_KEY",)}


def provider() -> str:
    """Which provider this run would use, or "" for none available."""
    chosen = os.environ.get("RESEARCH_PROVIDER", "").strip().lower()
    if chosen in PROVIDERS:
        return chosen
    for name in PROVIDERS:
        if any(os.environ.get(k) for k in PROVIDER_KEYS[name]):
            return name
    return ""


def model_id(name: str) -> str:
    return os.environ.get("RESEARCH_MODEL") or DEFAULT_MODELS.get(name, "")

# HOW FULL IS FULL. Not a rate limit -- a precondition, which is a
# better fit for a batch that fires this node sixteen times a night.
# "Research only if the bank is thin" makes the first run of the night
# do the work and the other fifteen cost nothing, needs no counter and
# no new table, and self-heals if a pass banks less than it meant to.
BANK_TARGET = int(os.environ.get("RESEARCH_BANK_TARGET", "8"))

# The agent's rope. A react loop with twelve tools can wander, and an
# unattended one has nobody to stop it; this is the wall.
MAX_STEPS = int(os.environ.get("RESEARCH_MAX_STEPS", "40"))

# ONE ATTEMPT PER BRAND PER DAY, marked on disk.
#
# `bank_is_full` alone is not a cap, and the difference bites in exactly
# the case worth guarding: a pass that banks NOTHING leaves the bank as
# thin as it found it, so the next of the night's eight runs researches
# again, and so does the next -- eight paid passes to bank zero sparks.
# A stamp file is the smallest thing that survives between runs, because
# each trigger invocation is its own process and a module-level flag
# would not. Named by date so it clears itself.
STAMP_DIR = PROJECT_ROOT / "data" / ".research"


def _stamp(brand: str) -> Path:
    from datetime import date
    return STAMP_DIR / f"{brand}-{date.today().isoformat()}"


def ready() -> tuple[bool, str]:
    """(ok, reason) -- can this node run at all.

    One place that answers it, so the node reports a precise reason
    instead of an empty result. Every failure here is an ordinary state
    of a machine that has not opted in, not an error.
    """
    name = provider()
    if not name:
        return (False, "no research key set (GEMINI_API_KEY or ANTHROPIC_API_KEY)")
    if not any(os.environ.get(k) for k in PROVIDER_KEYS[name]):
        return (False, f"RESEARCH_PROVIDER={name} but "
                       f"{PROVIDER_KEYS[name][0]} is not set")
    package = ("langchain_google_genai" if name == "gemini"
               else "langchain_anthropic")
    try:
        __import__(package)
        import mcp  # noqa: F401
        from langgraph.prebuilt import create_react_agent  # noqa: F401
    except ImportError as e:
        return (False, f"{e.name} not installed (pip install -r requirements.txt)")
    return (True, "")


def build_model(name: str):
    """The chat model, bound to whatever server-side search it has.

    Search is bound HERE and per provider because the two are not the
    same shape: Anthropic publishes a server-side tool, and Gemini only
    began allowing its google_search tool alongside custom function
    declarations in the Gemini 3 family. So it is attempted and not
    assumed -- a provider that refuses the combination still gets an
    agent, and the crawl signals already in the brief are what it
    researches from. Losing search must not lose the node.
    """
    if name == "anthropic":
        from langchain_anthropic import ChatAnthropic
        model = ChatAnthropic(model=model_id(name), max_tokens=8000)
        return model.bind_tools([{"type": "web_search_20260209",
                                  "name": "web_search"}]), True
    from langchain_google_genai import ChatGoogleGenerativeAI
    model = ChatGoogleGenerativeAI(
        model=model_id(name),
        google_api_key=os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY"))
    return model, False


def bank_is_full(brand: str, dsn=None, target: int = BANK_TARGET) -> bool:
    """Enough unused sparks at or above the floor that researching more
    would be banking into a queue nothing will reach tonight."""
    try:
        rows = scout.list_findings(brand=brand, unused_only=True, limit=100,
                                   dsn=dsn)
    except Exception:
        return False          # unreadable bank -> research, don't skip
    return len([r for r in rows
                if (r.get("score") or 0) >= scout.SCORE_FLOOR]) >= target


def build_brief(brand: str, count: int, dsn=None, tools=None,
                signals: str = "") -> str:
    """The agent's instructions: the digest prompt's rules verbatim,
    plus the part that is only true for an agent with tools.

    `prompts/scout_digest_prompt.txt` is loaded rather than restated so
    the crawl and the agent are held to ONE definition of a spark. It
    contains `{...}` placeholders meant for str.format -- they are left
    alone here and explained instead, because the useful half of that
    file is its argument about what a spark is, not its template.
    """
    try:
        rules = DIGEST_PROMPT_PATH.read_text()
    except OSError:
        rules = ""
    try:
        recent = scout.recent_sparks(brand, dsn=dsn)
    except Exception:
        recent = []
    try:
        brief = BRIEF_PATH.read_text()
    except OSError:
        # The brief is the job description; without it there is no run.
        raise RuntimeError(f"missing {BRIEF_PATH}")
    # The tool list is INJECTED from what the server just published,
    # not written into the prompt file. The public names are `add_spark`
    # and `reference`, not the Python functions' `bank_spark` and
    # `bank_reference` -- a distinction found by running this, not by
    # reading it, and one a rename in build_server would reintroduce.
    listing = "\n".join(
        f"- {t.name}: {(t.description or '').strip().splitlines()[0]}"
        for t in (tools or [])) or "(the server published none)"
    return brief.format(
        brand=brand,
        brand_note=scout.BRAND_NOTES.get(brand, ""),
        count=count,
        max_images=scout.MAX_BIN_IMAGES,
        rules=rules,
        tools=listing,
        signals=signals or "(no web signals this pass — work from the board's "
                           "own history and say so in the rationale)",
        recent="\n".join(f"- {s}" for s in recent) or "(nothing recent)",
    )


def _server_env() -> dict:
    """The subprocess's environment, with the engine gate stripped.

    Explicitly removed rather than merely not set: `.env` is loaded by
    the server itself and `ZEROPAGE_MCP_ENGINE=1` is in Mike's, so
    inheriting os.environ would hand the agent `run_graph` -- the tool
    that invokes the graph this node runs inside.
    """
    env = {k: v for k, v in os.environ.items() if k != "ZEROPAGE_MCP_ENGINE"}
    env["ZEROPAGE_MCP_ENGINE"] = "0"
    return env


def _sync(coro):
    """Run a coroutine from a sync graph node.

    `asyncio.run` raises inside a running loop, and this node has two
    callers that may already be in one -- `langgraph dev` and the web
    app's job thread -- while the cron path is plain sync. So: use the
    simple path when there is no loop, and a private loop on its own
    thread when there is. Getting this wrong fails only under the web
    app, which is the caller least likely to be exercised in a test.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def _result_text(result) -> str:
    """An MCP tool result as the string a model should see.

    Content blocks rather than `.data`, because these tools return dicts
    and the SDK ships them as text blocks; joining is what the model
    would have been shown anyway. An error result keeps its text -- a
    ToolError's message IS the useful part (an unknown id, a brand that
    does not exist), and hiding it leaves the agent with no recovery
    from a bad call except an identical retry.
    """
    parts = []
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    if not parts:
        return str(getattr(result, "structured_content", "") or "")
    return "\n".join(parts)


async def _as_tools(client) -> list:
    """The server's own tools, as LangChain tools.

    Note `input_schema`, not `inputSchema`: the mcp 2.x models are
    snake_case where the wire format and the 1.x SDK were camel. Written
    the old way it raises AttributeError on the first tool -- which is
    the second thing the version pin in requirements.txt is protecting.

    Names, descriptions and argument schemas come off `list_tools()`, so
    they are written once -- in `build_server` -- and this only wraps
    what the server reports. Add a tool there and it appears here with
    no change to this file, which is the whole reason for the transport.
    """
    from langchain_core.tools import StructuredTool

    tools = []
    for spec in (await client.list_tools()).tools:
        def bind(name):
            async def call(**kwargs):
                return _result_text(await client.call_tool(name, kwargs))
            return call
        tools.append(StructuredTool.from_function(
            coroutine=bind(spec.name), name=spec.name,
            description=spec.description or "",
            args_schema=spec.input_schema or {"type": "object", "properties": {}}))
    return tools


def _signals(brand: str) -> str:
    """What the web is saying, as text in the brief.

    `scout.gather_web` already does grounded search with citations, and
    it is the lane that has never failed -- so the agent researches from
    it rather than from a search tool it may not be allowed to hold.
    Gemini only began permitting google_search ALONGSIDE custom function
    declarations in the Gemini 3 family, and a design that needs that
    permission is a design that breaks on a model swap.

    Never fatal. No signals means an agent working from the board's own
    history, which is thinner but still a decision -- and thin beats the
    rotating text file this node exists to replace.
    """
    try:
        from google import genai

        from . import shootgen
        client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY")
                              or os.environ.get("GOOGLE_API_KEY"))
        found = scout.gather_web(brand, client,
                                 os.environ.get("GEMINI_MODEL", shootgen.MODEL))
    except Exception as e:
        print(f"note: no web signals for this pass ({type(e).__name__}: {e}) "
              f"-- researching from the board's own history", file=sys.stderr)
        return ""
    for failed in [f["error"] for f in found if f.get("error")]:
        print(f"note: research lane: {failed}", file=sys.stderr)
    usable = [f for f in found if f.get("detail")]
    return scout.format_signals(usable) if usable else ""


async def _research(brand: str, count: int, dsn, *, python: str) -> dict:
    from mcp import Client, StdioServerParameters

    signals = _signals(brand)
    server = StdioServerParameters(
        command=python,
        # No --engine. See the module docstring.
        # no --db when none was given: the child inherits DATABASE_URL
        args=["-m", "src.mcp_server"] + (["--db", str(dsn)] if dsn else []),
        cwd=str(PROJECT_ROOT),
        env=_server_env(),
    )
    banked_before = len(scout.list_findings(brand=brand, dsn=dsn))
    async with Client(server) as client:
        return await _drive(client, brand, count, dsn, banked_before,
                            signals=signals)


async def _drive(client, brand: str, count: int, dsn, banked_before: int, *,
                 signals: str = "") -> dict:
    """The agent loop, given a connected client.

    Split from `_research` so a test can hand it an in-process
    `MCPServer` -- `mcp.Client` accepts one directly -- and exercise the
    real tool surface without a subprocess or a key.
    """
    from langgraph.prebuilt import create_react_agent

    tools = await _as_tools(client)
    # Built here, with the tools in hand, so the brief names what the
    # server actually published rather than what this file guessed.
    brief = build_brief(brand, count, dsn=dsn, signals=signals,
                        tools=(await client.list_tools()).tools)

    model, _has_search = build_model(provider())
    agent = create_react_agent(model, tools)
    await agent.ainvoke({"messages": [{"role": "user", "content": brief}]},
                        config={"recursion_limit": MAX_STEPS})

    # What it actually DID, read off the database rather than off its
    # closing message. An agent's own summary of its work is the least
    # reliable record of it, and this number is what the night depends on.
    banked = len(scout.list_findings(brand=brand, dsn=dsn)) - banked_before
    images = sum(len(scout.bin_for_finding(r["id"], dsn=dsn))
                 for r in scout.list_findings(brand=brand, unused_only=True,
                                              limit=100, dsn=dsn))
    return {"ok": banked > 0, "banked": banked, "images": images}


def run(brand: str, *, count: int = BANK_TARGET, dsn=None,
        python: Optional[str] = None, force: bool = False) -> dict:
    """One research pass. Never raises.

    Returns {"ok", "banked", "images", "note"}. `ok` is False for every
    reason including "not configured" and "already ran today" -- the
    caller's only correct response to any of them is the same one: carry
    on with whatever the bank already holds.

    `force` skips the once-a-day stamp, for running this by hand.
    """
    ok, reason = ready()
    if not ok:
        return {"ok": False, "banked": 0, "images": 0, "note": reason}
    if bank_is_full(brand, dsn=dsn):
        return {"ok": False, "banked": 0, "images": 0,
                "note": f"bank already holds {BANK_TARGET}+ unused sparks"}
    stamp = _stamp(brand)
    if not force and stamp.exists():
        return {"ok": False, "banked": 0, "images": 0,
                "note": f"already researched {brand} today"}
    try:
        build_brief(brand, count, dsn=dsn)      # fail fast on a bad template
    except Exception as e:
        return {"ok": False, "banked": 0, "images": 0, "note": f"no brief: {e}"}

    # Stamped BEFORE the call, not after. The failure this guards is a
    # pass that banks nothing, and a pass that crashes banks nothing --
    # marking it only on success would retry a broken API seven more
    # times tonight, which is the exact bill this exists to prevent.
    try:
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.touch()
    except OSError as e:
        print(f"note: could not stamp this research pass ({e}) -- it may run "
              f"again tonight", file=sys.stderr)

    # sys.executable, not "python": launchd gives this process the venv's
    # interpreter and PATH holds whatever the plist inherited, which on
    # this machine is not the same one (see ops/connect-launchd notes).
    try:
        result = _sync(_research(brand, count, dsn,
                                 python=python or sys.executable))
    except Exception as e:
        return {"ok": False, "banked": 0, "images": 0,
                "note": f"{type(e).__name__}: {e}"}
    result["note"] = (f"banked {result['banked']} spark(s)"
                      if result["ok"] else "the agent banked nothing")
    return result
