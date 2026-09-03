"""The research node: Claude filling the bank the scout drains.

The tier that did not exist. `scout` reads a bank and decides nothing,
so on a thin crawl night every run fell through to the same rotating
text file and the concepts read like it (141-148, 2026-09-01).

Nothing here reaches Anthropic or spawns the MCP server — conftest
blocks the network, and the agent call itself is patched. What these
protect is everything AROUND the model call: that it is off unless
asked, that it cannot hand the agent the tool which re-invokes this
graph, that a failure is a quiet fall-through rather than a lost night,
and that it never touches the spark the caller passed.
"""

import pytest

from src import entities, orchestrator, preprod, research_agent, scout


@pytest.fixture
def tmp_db(pg, tmp_path, monkeypatch):
    path = pg
    preprod.init(path)
    entities.init(path)
    scout.init(path)
    monkeypatch.setenv("DATABASE_URL", path)
    # Redirected for every test, not just the ones about it: the stamp is
    # a real file under data/, and a suite that wrote one would silently
    # stop the next real 6am run from researching.
    monkeypatch.setattr(research_agent, "STAMP_DIR", tmp_path / ".research")
    return path


@pytest.fixture
def configured(monkeypatch):
    """Gemini, which is what this actually runs on (Mike's key, his call
    2026-09-02). Nothing here reaches Google -- the agent call is
    patched and conftest blocks the network."""
    monkeypatch.setenv("GEMINI_API_KEY", "not-a-real-key")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("RESEARCH_PROVIDER", raising=False)


# ---------- the gate ----------

def test_the_node_is_a_noop_unless_asked(tmp_db, monkeypatch):
    """Off by default, and off for a Director re-fire. A node that
    quietly spent Anthropic credit on every run would be a surprise on
    a bill, not a feature."""
    called = []
    monkeypatch.setattr(research_agent, "run", lambda *a, **k: called.append(1))

    assert orchestrator.research({"brand": "zeropage"}) == {}
    assert orchestrator.research({"brand": "zeropage", "research": False,
                                  "scout": True}) == {}
    assert called == []


def test_researching_without_scouting_is_refused(tmp_db, monkeypatch):
    """Filling a bank nothing is going to read is spend with no output.
    `--scout` is what reads it, so `--research` alone must not fire."""
    called = []
    monkeypatch.setattr(research_agent, "run", lambda *a, **k: called.append(1))

    assert orchestrator.research({"brand": "zeropage", "research": True}) == {}
    assert called == []


def test_the_node_runs_when_both_are_asked_for(tmp_db, monkeypatch):
    seen = {}

    def fake_run(brand, **kw):
        seen["brand"] = brand
        return {"ok": True, "banked": 3, "images": 6, "note": "banked 3 spark(s)"}

    monkeypatch.setattr(research_agent, "run", fake_run)
    out = orchestrator.research({"brand": "antihero", "research": True,
                                 "scout": True})

    assert seen["brand"] == "antihero"
    assert out["research_note"] == "banked 3 spark(s)"


def test_the_node_never_returns_a_spark(tmp_db, monkeypatch):
    """It writes to the bank; `scout` reads it. Keeping the two apart is
    what lets the crawl and the agent stay interchangeable producers."""
    monkeypatch.setattr(research_agent, "run",
                        lambda *a, **k: {"ok": True, "banked": 1, "images": 0,
                                         "note": "banked 1 spark(s)"})
    out = orchestrator.research({"brand": "zeropage", "research": True,
                                 "scout": True, "spark": "the rotation"})

    assert set(out) == {"research_note"}
    assert "spark" not in out and "goal" not in out


def test_run_defaults_to_not_researching():
    import inspect
    assert inspect.signature(orchestrator.run).parameters["research"].default is False


# ---------- what it will not hand the agent ----------

def test_the_agent_is_never_given_the_tool_that_re_invokes_this_graph(monkeypatch):
    """ENGINE_TOOLS are run_research and run_graph, and run_graph invokes
    the graph this node is a member of. An agent holding it can fire a
    full nightly run from inside a nightly run, recursively, at Runway
    prices. Mike's own .env sets the gate, so inheriting os.environ is
    exactly how it would leak in."""
    from src import mcp_server

    monkeypatch.setenv("ZEROPAGE_MCP_ENGINE", "1")
    env = research_agent._server_env()

    assert env["ZEROPAGE_MCP_ENGINE"] == "0"
    assert not mcp_server.engine_enabled.__module__.startswith("langchain")
    # and the free surface is still the whole point of going over MCP
    assert mcp_server.bank_spark in mcp_server.TOOLS
    assert mcp_server.bank_reference in mcp_server.TOOLS
    assert mcp_server.run_graph in mcp_server.ENGINE_TOOLS


def test_the_rest_of_the_environment_survives(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "keep-me")
    assert research_agent._server_env()["GEMINI_API_KEY"] == "keep-me"


# ---------- not configured is a state, not an error ----------

def test_no_key_is_a_reported_state_not_a_crash(tmp_db, monkeypatch):
    for key in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY",
                "RESEARCH_PROVIDER"):
        monkeypatch.delenv(key, raising=False)
    ok, reason = research_agent.ready()
    assert ok is False and "GEMINI_API_KEY" in reason

    out = research_agent.run("zeropage", dsn=tmp_db)
    assert out["ok"] is False and out["banked"] == 0
    assert "no research key set" in out["note"]


# ---------- which model drives it ----------

def test_gemini_is_the_default_on_the_key_this_repo_already_has(monkeypatch):
    """The node is switchable, not tied to a provider: the argument for
    it was never about which model, it is that SOMETHING in the
    unattended path has to decide."""
    monkeypatch.delenv("RESEARCH_PROVIDER", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    assert research_agent.provider() == "gemini"


def test_an_anthropic_key_alone_is_still_enough(monkeypatch):
    monkeypatch.delenv("RESEARCH_PROVIDER", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    assert research_agent.provider() == "anthropic"
    assert research_agent.ready()[0] is True


def test_an_explicit_provider_wins_and_says_so_when_its_key_is_missing(monkeypatch):
    monkeypatch.setenv("RESEARCH_PROVIDER", "anthropic")
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    assert research_agent.provider() == "anthropic"
    ok, reason = research_agent.ready()
    assert ok is False and "ANTHROPIC_API_KEY" in reason


def test_the_model_id_follows_the_provider(monkeypatch):
    monkeypatch.delenv("RESEARCH_MODEL", raising=False)
    assert research_agent.model_id("gemini").startswith("gemini")
    assert research_agent.model_id("anthropic").startswith("claude")
    monkeypatch.setenv("RESEARCH_MODEL", "pinned-by-hand")
    assert research_agent.model_id("gemini") == "pinned-by-hand"


# ---------- web signals ----------

def test_a_dead_search_lane_costs_signals_not_the_pass(monkeypatch):
    """gather_web is the lane that has never failed, but "never" is not a
    guarantee. No signals means an agent working from the board's own
    history -- thinner, still a decision, still better than a rotation."""
    from src import scout as scout_mod

    def boom(*a, **k):
        raise RuntimeError("Connection reset")
    monkeypatch.setattr(scout_mod, "gather_web", boom)
    assert research_agent._signals("zeropage") == ""


def test_the_brief_says_plainly_when_it_has_no_signals(tmp_db):
    brief = research_agent.build_brief("zeropage", 6, dsn=tmp_db)
    assert "no web signals this pass" in brief
    assert "Never invent a source" in brief


def test_signals_reach_the_brief_when_there_are_some(tmp_db):
    brief = research_agent.build_brief(
        "zeropage", 6, dsn=tmp_db,
        signals="- [web] a thing somebody found (example.com)")
    assert "a thing somebody found" in brief


def test_an_agent_that_blows_up_costs_the_night_nothing(tmp_db, configured,
                                                        monkeypatch):
    """Research is the first of three tiers. A dead API means the crawl's
    bank, and a thin bank means sparks.txt -- never a failed run."""
    def boom(coro):
        coro.close()                      # the fake never awaits it
        raise RuntimeError("overloaded_error")
    monkeypatch.setattr(research_agent, "_sync", boom)

    out = research_agent.run("zeropage", dsn=tmp_db)

    assert out["ok"] is False and out["banked"] == 0
    assert "overloaded_error" in out["note"]


# ---------- the precondition, which is why 16 runs cost one pass ----------

def test_a_full_bank_is_not_researched_again(tmp_db, configured, monkeypatch):
    """The batch fires this node sixteen times a night. "Research only if
    the bank is thin" makes the first run do the work and the other
    fifteen cost nothing, with no counter and no new table."""
    for i in range(research_agent.BANK_TARGET):
        scout.record("zeropage", {"spark": f"banked {i}", "score": 0.9},
                     pass_id="p", dsn=tmp_db)
    monkeypatch.setattr(research_agent, "_sync",
                        lambda coro: pytest.fail("researched a full bank"))

    out = research_agent.run("zeropage", dsn=tmp_db)
    assert out["ok"] is False and "already holds" in out["note"]


def test_sparks_below_the_floor_do_not_count_as_a_full_bank(tmp_db):
    """They are banked and unused and no run will ever take them."""
    for i in range(research_agent.BANK_TARGET + 2):
        scout.record("zeropage", {"spark": f"too weak {i}", "score": 0.1},
                     pass_id="p", dsn=tmp_db)
    assert research_agent.bank_is_full("zeropage", dsn=tmp_db) is False


def test_a_used_spark_does_not_count_either(tmp_db):
    ids = [scout.record("zeropage", {"spark": f"spent {i}", "score": 0.9},
                        pass_id="p", dsn=tmp_db)
           for i in range(research_agent.BANK_TARGET)]
    for finding_id in ids:
        scout.mark_used(finding_id, run_id="r", dsn=tmp_db)
    assert research_agent.bank_is_full("zeropage", dsn=tmp_db) is False


def test_the_brands_have_their_own_banks(tmp_db):
    for i in range(research_agent.BANK_TARGET):
        scout.record("zeropage", {"spark": f"banked {i}", "score": 0.9},
                     pass_id="p", dsn=tmp_db)
    assert research_agent.bank_is_full("zeropage", dsn=tmp_db) is True
    assert research_agent.bank_is_full("antihero", dsn=tmp_db) is False


# ---------- the brief ----------

def test_the_brief_carries_the_digest_prompt_verbatim(tmp_db):
    """One definition of what a spark is, for the crawl and the agent
    both. Restating the rules here is how the two drift until only one
    of them still refuses a camera spec."""
    rules = research_agent.DIGEST_PROMPT_PATH.read_text()
    brief = research_agent.build_brief("zeropage", 6, dsn=tmp_db)

    assert "A SPARK IS A SITUATION, NOT AN IMAGE" in rules      # guard the guard
    assert "A SPARK IS A SITUATION, NOT AN IMAGE" in brief
    # the five-part spine (2026-09-03) that replaced turn/stake -- same
    # rewrite the idea-agent skill got, so the crawl stops handing back
    # moments dressed as stories
    assert "RE-READS THE OPENING" in brief
    assert scout.BRAND_NOTES["zeropage"] in brief
    assert str(scout.MAX_BIN_IMAGES) in brief


def test_the_brief_names_what_is_already_banked(tmp_db):
    scout.record("zeropage", {"spark": "the last check before leaving",
                              "score": 0.9}, pass_id="p", dsn=tmp_db)
    scout.mark_used(1, run_id="r", dsn=tmp_db)

    brief = research_agent.build_brief("zeropage", 6, dsn=tmp_db)
    assert "the last check before leaving" in brief


def test_an_empty_bank_reads_as_such_rather_than_blank(tmp_db):
    assert "(nothing recent)" in research_agent.build_brief("zeropage", 6,
                                                            dsn=tmp_db)


# ---------- one paid attempt per brand per day ----------

def test_a_pass_that_banks_nothing_does_not_retry_all_night(tmp_db, configured,
                                                            monkeypatch, tmp_path):
    """bank_is_full alone is not a cap. A pass that banks NOTHING leaves
    the bank as thin as it found it, so run two of the night's eight
    researches again, and so does run three -- eight paid passes for zero
    sparks. The stamp is what stops that."""
    monkeypatch.setattr(research_agent, "STAMP_DIR", tmp_path / ".research")
    calls = []
    monkeypatch.setattr(research_agent, "_sync", lambda coro: (
        coro.close(), calls.append(1),
        {"ok": False, "banked": 0, "images": 0})[-1])

    first = research_agent.run("zeropage", dsn=tmp_db)
    second = research_agent.run("zeropage", dsn=tmp_db)

    assert calls == [1], "researched twice on one night after banking nothing"
    assert first["banked"] == 0
    assert "already researched" in second["note"]


def test_a_crashed_pass_is_stamped_too(tmp_db, configured, monkeypatch, tmp_path):
    """A pass that crashes banks nothing. Stamping only on success would
    retry a broken API seven more times tonight."""
    monkeypatch.setattr(research_agent, "STAMP_DIR", tmp_path / ".research")

    def boom(coro):
        coro.close()
        raise RuntimeError("overloaded_error")
    monkeypatch.setattr(research_agent, "_sync", boom)

    research_agent.run("zeropage", dsn=tmp_db)
    assert "already researched" in research_agent.run("zeropage", dsn=tmp_db)["note"]


def test_the_brands_are_stamped_apart(tmp_db, configured, monkeypatch, tmp_path):
    monkeypatch.setattr(research_agent, "STAMP_DIR", tmp_path / ".research")
    monkeypatch.setattr(research_agent, "_sync", lambda coro: (
        coro.close(), {"ok": True, "banked": 2, "images": 0})[-1])

    research_agent.run("zeropage", dsn=tmp_db)
    assert research_agent.run("antihero", dsn=tmp_db)["ok"] is True


def test_force_is_how_a_person_re_runs_it_by_hand(tmp_db, configured,
                                                  monkeypatch, tmp_path):
    monkeypatch.setattr(research_agent, "STAMP_DIR", tmp_path / ".research")
    monkeypatch.setattr(research_agent, "_sync", lambda coro: (
        coro.close(), {"ok": True, "banked": 1, "images": 0})[-1])

    research_agent.run("zeropage", dsn=tmp_db)
    assert research_agent.run("zeropage", dsn=tmp_db, force=True)["ok"] is True


# ---------- the bridge, against the real server ----------
#
# `mcp.Client` accepts an MCPServer instance directly and talks to it
# in-process, so these exercise the ACTUAL tool surface -- the same
# registration Claude Desktop gets -- with no subprocess, no key and no
# network. This is the claim the whole design rests on: that the graph
# can drive this repo's own MCP server. Driven through
# `research_agent._sync`, which is also how the graph node calls it.


def _with_tools(path, fn):
    """Open a client on the real server and hand `fn` its tools."""
    from mcp import Client

    from src import mcp_server

    async def go():
        async with Client(mcp_server.build_server(dsn=path)) as client:
            return await fn(await research_agent._as_tools(client))
    return research_agent._sync(go())


def test_the_servers_own_tools_arrive_as_langchain_tools(tmp_db):
    async def check(tools):
        return {t.name: t for t in tools}

    by_name = _with_tools(tmp_db, check)

    # names, descriptions and schemas are READ off the server, never
    # restated here -- add a tool to build_server and it appears
    # NOTE the public names: build_server registers bank_spark as
    # `add_spark` and bank_reference as `reference`. Reading them off the
    # server is exactly why this file does not hardcode them.
    assert {"add_spark", "reference", "sparks", "tonight"} <= set(by_name)
    assert by_name["add_spark"].description, "the tool arrived with no description"
    assert "spark" in by_name["add_spark"].args_schema["properties"]
    # and the database path is never published to the model
    assert "path" not in by_name["add_spark"].args_schema["properties"]


def test_a_tool_call_over_the_transport_really_banks(tmp_db):
    """End to end through MCP: the agent calls bank_spark, and a spark
    the nightly `--scout` run will serve comes out the other side."""
    async def bank(tools):
        return await {t.name: t for t in tools}["add_spark"].ainvoke(
            {"brand": "zeropage", "spark": "setting the table for one too many",
             "rationale": "TURN: the extra place gets cleared  STAKE: grief"})

    out = _with_tools(tmp_db, bank)

    assert "setting the table" in out
    served = scout.next_spark("zeropage", dsn=tmp_db)
    assert served["spark"] == "setting the table for one too many"


def test_a_caller_error_reaches_the_agent_as_words(tmp_db):
    """mcp_server translates its ValueErrors into ToolErrors precisely so
    an agent can tell "you passed a bad id" from "the server is broken".
    If that text were dropped here, its only recovery from either would
    be an identical retry."""
    async def bad(tools):
        return await {t.name: t for t in tools}["add_spark"].ainvoke(
            {"brand": "not-a-brand", "spark": "x"})

    out = _with_tools(tmp_db, bad)
    assert "not-a-brand" in out or "brand" in out.lower()


def test_sync_works_from_inside_a_running_loop(tmp_db):
    """The cron path is sync, but `langgraph dev` and the web app's job
    thread are not. asyncio.run raises inside a running loop, and getting
    this wrong fails only under the caller least likely to be tested."""
    import asyncio

    async def outer():
        return research_agent._sync(_answer())

    async def _answer():
        return "reached"

    assert asyncio.run(outer()) == "reached"


def test_the_brief_names_the_tools_the_server_actually_published(tmp_db):
    """The public names are `add_spark` and `reference`, not the Python
    functions' names. A brief that guessed would send the agent looking
    for tools that do not exist -- which is what the first draft did."""
    from mcp import Client

    from src import mcp_server

    async def go():
        async with Client(mcp_server.build_server(dsn=tmp_db)) as client:
            return research_agent.build_brief(
                "zeropage", 6, dsn=tmp_db,
                tools=(await client.list_tools()).tools)

    brief = research_agent._sync(go())
    assert "- add_spark:" in brief and "- reference:" in brief
    assert "- tonight:" in brief
