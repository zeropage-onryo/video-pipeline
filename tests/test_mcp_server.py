"""
Tests for the MCP surface.

Two things here are worth more than the coverage.

`test_no_render_connector_is_imported` walks the module's own AST for
the connectors that spend real money. The docstring in mcp_server.py
promises this surface cannot buy a clip; a docstring cannot fail CI, and
the way that promise would actually break is somebody adding a
convenience import six months from now, in a file whose header still
says otherwise.

`test_caller_errors_reach_the_model` pins the ToolError translation. The
SDK relays a ToolError's message and replaces every other exception with
"Error executing tool <name>", so without the translation an agent
cannot tell a bad id from a broken server -- and its only recovery from
either is to retry the identical call. That is a behaviour, not a
detail, and it is invisible from reading the tool functions.
"""
import ast
from pathlib import Path

import pytest

from src import db, mcp_server, preprod, scout


@pytest.fixture
def tmp_db(pg):
    path = pg
    preprod.init(path)
    scout.init(path)
    return path


def _idea(title, **kw):
    return {"title": title, "hook": kw.get("hook", "a hook"),
            "logline": kw.get("logline", "")}


@pytest.fixture
def board(tmp_db):
    """Four concepts, one of each state the board can be in."""
    ids = preprod.save_concept_ideas(
        [_idea("Open One"), _idea("Picked One"), _idea("Archived One"),
         _idea("Parked One")],
        brand="zeropage", spark="a bench with one glove", dsn=tmp_db,
    
        account_id=None,)
    preprod.set_picked(ids[1], dsn=tmp_db, account_id=None)
    preprod.set_archived(ids[2], dsn=tmp_db, account_id=None)
    preprod.update_concept_shots(
        ids[3],
        {"shots": [{"n": 1, "type": "BROLL", "source": "AI", "tool": "RUNWAY",
                    "prompt": "a glove on a bench, macro, one continuous take",
                    "location": "hallway"}]},
        dsn=tmp_db,
    
        account_id=None,)
    preprod.set_shot_parked(ids[3], 1, reason="keyframe rendered", dsn=tmp_db, account_id=None)
    return tmp_db, ids


# ---------- the board ----------

def test_open_excludes_picked_and_archived(board):
    path, ids = board
    open_ids = [c["id"] for c in mcp_server.list_ideas(dsn=path)["ideas"]]
    assert ids[0] in open_ids
    assert ids[1] not in open_ids
    assert ids[2] not in open_ids


def test_parked_is_still_open(board):
    """A parked scene is waiting on a person, so it belongs in the list
    of what is waiting on a person. It is a sub-state of open, not a
    fifth column beside it."""
    path, ids = board
    assert ids[3] in [c["id"] for c in mcp_server.list_ideas(dsn=path)["ideas"]]
    assert ids[3] in [c["id"] for c in
                      mcp_server.list_ideas(status="parked", dsn=path)["ideas"]]


def test_status_counts_reconcile_with_the_open_list(board):
    """`board` counts are exclusive so they sum to the row count, while
    `list_ideas(status="open")` is not. The stats payload spells the
    second number out rather than leaving it to be derived wrongly."""
    path, _ = board
    stats = mcp_server.pipeline_stats(dsn=path)
    assert sum(stats["board"].values()) == 4
    assert stats["waiting_on_you"] == len(
        mcp_server.list_ideas(status="open", limit=100, dsn=path)["ideas"]
    )


def test_card_carries_a_one_line_summary(board):
    path, _ = board
    card = mcp_server.list_ideas(status="parked", dsn=path)["ideas"][0]
    assert card["summary"]
    assert "\n" not in card["summary"]
    assert len(card["summary"]) <= preprod.SUMMARY_CHARS + 1  # + the ellipsis


def test_get_idea_returns_the_prompt_a_card_omits(board):
    path, ids = board
    card = mcp_server.list_ideas(status="parked", dsn=path)["ideas"][0]
    full = mcp_server.get_idea(ids[3], dsn=path)
    assert "shots" not in card
    assert full["shots"][0]["prompt"].startswith("a glove on a bench")
    assert full["park_reason"] == "keyframe rendered"


# ---------- the graph's verdict, on the card ----------
#
# `judge_overall` is the Dev Studio's manual taste judge and no automated
# path writes it, so on 2026-09-02 an agent read four Studio Create rows
# (never scored, by design) as unjudged graph runs, and would have read a
# graph row held at 5/10 the same way. The verdict lives in hold_queue +
# prompt_scores, and the card now says which door wrote the row.

def test_a_graph_row_carries_the_gates_verdict(board):
    from src import autonomy
    path, ids = board
    autonomy.init(path)
    autonomy.log_prompt_scores("run-1", [
        {"prompt": "v1", "score": 5, "pass": False, "reason": "too many beats", "dims": {}},
        {"prompt": "v2", "score": 7, "pass": True, "reason": "", "dims": {}},
    ], dsn=path)
    autonomy.to_hold("zeropage", "keyframe rendered — approve in the Queue",
                     concept_id=ids[3], payload={"run_id": "run-1"},
                     dsn=path, account_id=None)
    full = mcp_server.get_idea(ids[3], dsn=path)
    assert full["origin"] == "graph"
    assert full["gate"]["score"] == 7 and full["gate"]["passed"] is True
    assert full["gate"]["outcome"].startswith("keyframe rendered")
    assert [x["score"] for x in full["gate"]["scores"]] == [5, 7]   # the rework moved it
    assert full["judge_overall"] is None                            # the taste judge, untouched


def test_a_studio_row_says_it_was_never_scored(board):
    path, ids = board
    full = mcp_server.get_idea(ids[3], dsn=path)     # has a shot, no hold row
    assert full["origin"] == "studio" and full["gate"] is None
    assert "not scored badly" in full["note"]


def test_a_captured_idea_has_nothing_to_score(tmp_db):
    card = mcp_server.capture_idea("zeropage", "Just a title", dsn=tmp_db)
    assert mcp_server.get_idea(card["id"], dsn=tmp_db)["origin"] == "capture"


def test_a_captured_idea_points_at_a_tool_every_caller_has(tmp_db):
    """The 2026-10-08 second-account walk: the card told a directory user
    to use `generate`, which the listed server does not offer.
    `write_scene` is on both servers."""
    card = mcp_server.capture_idea("zeropage", "Just a title", dsn=tmp_db)
    assert "`write_scene`" in card["next"] and "generate" not in card["next"]
    assert "write_scene" in mcp_server.LISTED_TOOLS


def test_a_held_run_reports_its_reason_with_the_run(tmp_db, monkeypatch):
    """A phone that asked for a run must not need a second call to
    learn why it held."""
    from src import autonomy, orchestrator
    monkeypatch.setenv("DATABASE_URL", tmp_db)
    autonomy.init(tmp_db)
    (cid,) = preprod.save_concept_ideas([_idea("Held One")], brand="zeropage",
                                        dsn=tmp_db, account_id=None)

    def fake_run(goal, **kw):
        autonomy.log_prompt_scores("run-2", [{"prompt": "p", "score": 4, "pass": False,
                                              "reason": "vague", "dims": {}}], dsn=tmp_db)
        autonomy.to_hold("zeropage", "prompt gate: vague (4/10)", concept_id=cid,
                         payload={"run_id": "run-2"}, dsn=tmp_db, account_id=None)
        return {"concept_id": cid, "held_reason": "prompt gate: vague (4/10)"}
    monkeypatch.setattr(orchestrator, "run", fake_run)
    out = mcp_server.run_graph("a direction", "zeropage")
    assert out["idea"]["gate"]["score"] == 4 and out["idea"]["gate"]["passed"] is False
    assert out["idea"]["gate"]["outcome"] == out["held_reason"]


def test_search_reaches_into_the_scene_prompt(board):
    """The words worth searching for live in the prompt, not the title
    -- the title is three words the model chose."""
    path, ids = board
    hits = mcp_server.search_ideas("continuous take", dsn=path)
    assert [c["id"] for c in hits["ideas"]] == [ids[3]]


def test_pick_and_archive_round_trip(board):
    path, ids = board
    assert mcp_server.pick_idea(ids[0], dsn=path)["status"] == "picked"
    assert mcp_server.archive_idea(ids[0], dsn=path)["status"] == "archived"
    assert mcp_server.archive_idea(ids[0], archived=False,
                                   dsn=path)["status"] == "picked"


def test_shoot_is_the_label_shoot_rate_reads(board):
    """`shot` means MADE by any means -- studio, Higgsfield, a camera --
    not "a render came back". It is the only way the system can see
    work that never passed through the Queue, and it must never spend."""
    path, ids = board
    before = mcp_server.pipeline_stats(dsn=path)["shoot_rate"]
    assert before["shot"] == 0

    mcp_server.pick_idea(ids[0], dsn=path)
    card = mcp_server.shoot_idea(ids[0], dsn=path)
    assert card["status"] == "shot"          # shot outranks picked on the card

    after = mcp_server.pipeline_stats(dsn=path)["shoot_rate"]
    assert after["shot"] == before["shot"] + 1
    assert after["generated"] == before["generated"]
    assert mcp_server.get_idea(ids[0], dsn=path)["status"] == "shot"

    # Reversible: un-shooting falls back to the pick that was still there.
    assert mcp_server.shoot_idea(ids[0], shot=False, dsn=path)["status"] == "picked"
    assert mcp_server.pipeline_stats(dsn=path)["shoot_rate"]["shot"] == before["shot"]


def test_shoot_tool_is_a_write_that_never_spends(tmp_db):
    """Registered beside pick, annotated as a write, and reachable with
    no engine flag -- recording that something got made costs nothing."""
    server = mcp_server.build_server(dsn=tmp_db)
    by_name = {t.name: t for t in _tools(server)}
    assert "shoot" in by_name
    assert by_name["shoot"].annotations.read_only_hint is False
    assert by_name["shoot"].annotations.destructive_hint is False
    assert set(by_name["shoot"].input_schema["properties"]) == {"idea_id", "shot"}


def test_archive_records_the_reason_and_says_so_when_it_is_off_vocabulary(board):
    """A reason is never a gate, but the tally counts words, so an
    uncounted word is said back rather than silently filed."""
    path, ids = board
    card = mcp_server.archive_idea(ids[0], reason="no turn", dsn=path)
    assert card["status"] == "archived" and "reason_note" not in card
    assert preprod.get_concept(ids[0], dsn=path, account_id=None)["archive_reason"] == "no turn"

    card = mcp_server.archive_idea(ids[1], reason="boring", dsn=path)
    assert card["status"] == "archived"                       # still archived
    assert "weak concept" in card["reason_note"]
    assert preprod.get_concept(ids[1], dsn=path, account_id=None)["archive_reason"] == "boring"

    assert "reason_note" not in mcp_server.archive_idea(ids[3], dsn=path)   # no word, no nag


def test_archive_tool_names_every_counted_reason(tmp_db):
    """The description is what an agent writes from. Typed by hand it
    named a vocabulary the Grade tab had already retired."""
    server = mcp_server.build_server(dsn=tmp_db)
    desc = {t.name: t for t in _tools(server)}["archive"].description
    for word in preprod.ARCHIVE_REASONS:
        assert word in desc
    assert "boring" not in desc and "other" not in desc.split(" · ")


def test_archiving_never_deletes(board):
    """pick_rate is generated-vs-picked, so a deleted row would make the
    rate read 100% forever and unfalsifiable."""
    path, ids = board
    before = mcp_server.pipeline_stats(dsn=path)["pick_rate"]["generated"]
    mcp_server.archive_idea(ids[0], dsn=path)
    assert mcp_server.pipeline_stats(dsn=path)["pick_rate"]["generated"] == before


def test_captured_idea_has_no_shots_so_it_cannot_move_pick_rate(tmp_db):
    """Capturing on a phone must not touch the number that measures
    generation quality: pick_rate counts one-shot concepts only, and a
    captured idea has none."""
    before = mcp_server.pipeline_stats(dsn=tmp_db)["pick_rate"]["generated"]
    card = mcp_server.capture_idea("zeropage", "From The Bus", dsn=tmp_db)
    assert card["is_scene"] is False
    after = mcp_server.pipeline_stats(dsn=tmp_db)["pick_rate"]["generated"]
    assert after == before


# ---------- sparks ----------

def test_human_spark_outranks_a_crawled_one(tmp_db):
    """A person who types a direction means it. If a crawled finding
    could outscore it, the night would prefer its own research to an
    explicit instruction."""
    scout.record("zeropage", {"spark": "crawled idea", "score": 0.95},
                 lanes="web", dsn=tmp_db)
    mcp_server.bank_spark("zeropage", "the one I actually want", dsn=tmp_db)
    assert mcp_server.next_spark("zeropage", dsn=tmp_db)["spark"] == \
        "the one I actually want"


def test_repeat_spark_is_reported_not_refused(tmp_db):
    """_spark_key stops the CRAWL rediscovering itself. A person
    retyping a direction usually means it, so the collision is
    information, not a rejection."""
    first = mcp_server.bank_spark("zeropage", "a bench with one glove",
                                  dsn=tmp_db)
    second = mcp_server.bank_spark("zeropage", "A bench with one glove.",
                                   dsn=tmp_db)
    assert second["duplicate_of"] == [first["id"]]
    assert second["id"] != first["id"]


def test_no_servable_spark_is_a_note_not_an_error(tmp_db):
    """Falling back to the sparks.txt rotation is the healthy degraded
    path -- it is what the pipeline did before the scout existed."""
    scout.record("zeropage", {"spark": "too weak", "score": 0.1}, dsn=tmp_db)
    result = mcp_server.next_spark("zeropage", dsn=tmp_db)
    assert result["spark"] is None
    assert "sparks.txt" in result["note"]


def test_spark_images_carry_their_source(tmp_db):
    """These are other people's frames held as mood reference. An
    unattributed tile in front of somebody about to spend a render is
    the wrong affordance."""
    finding_id = scout.record("zeropage", {"spark": "x", "score": 0.9},
                              pass_id="p1", dsn=tmp_db)
    with db.connect(tmp_db) as conn:
        conn.execute(
            "INSERT INTO scout_bin (created_at, pass_id, brand, url, "
            "source_url, title, lane) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            ("2026-08-31", "p1", "zeropage", "/refs/abc.jpg",
             "https://youtube.com/watch?v=1", "A Title", "shorts"),
        )
    images = mcp_server.spark_images(finding_id, dsn=tmp_db)
    assert images["count"] == 1
    assert images["images"][0]["source_url"] == "https://youtube.com/watch?v=1"


# ---------- what it refuses ----------

FORBIDDEN = {"runway", "veo", "nano_banana", "imagery", "autopilot",
             "instagram", "scheduling"}


def test_no_render_connector_is_imported():
    """The header promises this surface cannot buy a clip. A docstring
    cannot fail CI; this can. The way the promise breaks is a
    convenience import added later to a file whose header still says
    otherwise."""
    source = Path(mcp_server.__file__).read_text()
    imported = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom):
            imported.update(alias.name for alias in node.names)
            if node.module:
                imported.add(node.module.split(".")[0])
        elif isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
    assert not (FORBIDDEN & imported), f"render connector imported: {FORBIDDEN & imported}"


def test_graph_refuses_to_run_with_render_live(monkeypatch):
    """ZEROPAGE_RENDER=1 turns generate_render from a dry stub into real
    Veo spend. A remote caller must never be what trips it."""
    monkeypatch.setenv("ZEROPAGE_RENDER", "1")
    with pytest.raises(mcp_server.Refused, match="ZEROPAGE_RENDER"):
        mcp_server.run_graph("a spark", "zeropage")


# ---------- generate reaches the spark's references ----------
#
# run_graph used to take a spark string and nothing else, and
# orchestrator.run with an explicit spark never reads the bin -- so an
# agent could bank six photographs behind a spark with `reference` and
# then generate from that spark with none of them (2026-09-02: #169-#172
# had refs only when started in Studio).

@pytest.fixture
def graph_calls(monkeypatch):
    from src import orchestrator
    calls = []

    def fake_run(goal, **kw):
        calls.append(dict(kw, goal=goal))
        return {"concept_id": None, "attempts": 1}
    monkeypatch.setattr(orchestrator, "run", fake_run)
    return calls


def _banked(tmp_db, spark="a bench with one glove", brand="zeropage"):
    fid = scout.record(brand, {"spark": spark, "score": 0.9}, dsn=tmp_db)
    for n in (1, 2):
        scout.bank_urls(fid, [f"/refs/{n}.jpg"], lane="agent", dsn=tmp_db)
    return fid


def test_generate_by_finding_id_hands_the_graph_its_bin(tmp_db, monkeypatch, graph_calls):
    monkeypatch.setenv("DATABASE_URL", tmp_db)
    fid = _banked(tmp_db)
    out = mcp_server.run_graph(brand="zeropage", finding_id=fid)
    [call] = graph_calls
    assert call["spark"] == "a bench with one glove"      # the finding's own
    assert call["reference_photos"] == ["/refs/1.jpg", "/refs/2.jpg"]
    assert call["scout_finding_id"] == fid                # so planner claims it
    assert out["finding_id"] == fid and out["reference_photos"] == call["reference_photos"]


def test_research_and_generate_ask_the_create_gate(tmp_db, monkeypatch, graph_calls):
    """2026-09-29: research and generate spend Gemini for their caller, so
    they ask charge.create_refusal like Studio's Create -- and a refusal is
    Refused (stop asking), never a ValueError (ask again), and happens
    before the graph or the crawl runs."""
    from src import charge
    from src import scout as scout_mod
    monkeypatch.setenv("DATABASE_URL", tmp_db)
    monkeypatch.setattr(charge, "create_refusal",
                        lambda account_id, dsn=None: charge.CREATE_REFUSAL)
    monkeypatch.setattr(scout_mod, "scout",
                        lambda **kw: pytest.fail("crawled past the gate"))
    with pytest.raises(mcp_server.Refused, match="subscribe or top up"):
        mcp_server.run_graph("a bench with one glove", "zeropage")
    with pytest.raises(mcp_server.Refused, match="subscribe or top up"):
        mcp_server.run_research("zeropage", lanes=["web"], dsn=tmp_db)
    assert graph_calls == []

    monkeypatch.setattr(charge, "create_refusal", lambda account_id, dsn=None: None)
    mcp_server.run_graph("a bench with one glove", "zeropage")
    assert len(graph_calls) == 1


def test_generate_by_spark_text_finds_its_own_photographs(tmp_db, monkeypatch, graph_calls):
    """add_spark -> reference -> generate(spark) must work without the
    agent carrying an id between calls, and fixing the capitals must
    not lose the photos -- the composer's `claims` rule, same key."""
    monkeypatch.setenv("DATABASE_URL", tmp_db)
    fid = _banked(tmp_db)
    mcp_server.run_graph("A Bench, With One Glove.", "zeropage")
    [call] = graph_calls
    assert call["scout_finding_id"] == fid
    assert call["reference_photos"] == ["/refs/1.jpg", "/refs/2.jpg"]


def test_brand_defaults_to_the_findings_and_a_wrong_one_is_refused(tmp_db, monkeypatch, graph_calls):
    monkeypatch.setenv("DATABASE_URL", tmp_db)
    fid = _banked(tmp_db, brand="antihero")
    mcp_server.run_graph(finding_id=fid)
    assert graph_calls[0]["brand"] == "antihero"
    with pytest.raises(ValueError, match="banked for 'antihero'"):
        mcp_server.run_graph(brand="zeropage", finding_id=fid)


def test_a_reworded_spark_does_not_inherit_a_findings_photographs(tmp_db, monkeypatch, graph_calls):
    """The composer silently drops the bin when the idea walks away
    from the spark; this door SAYS so, because an agent acts on the
    message where a person would have seen a tile disappear."""
    monkeypatch.setenv("DATABASE_URL", tmp_db)
    fid = _banked(tmp_db)
    with pytest.raises(ValueError, match="is not finding"):
        mcp_server.run_graph("a monster in the garage", "zeropage", finding_id=fid)
    assert graph_calls == []


def test_an_unbanked_spark_runs_on_the_asset_bank_alone(tmp_db, monkeypatch, graph_calls):
    monkeypatch.setenv("DATABASE_URL", tmp_db)
    out = mcp_server.run_graph("a direction nobody banked", "zeropage")
    [call] = graph_calls
    assert call["reference_photos"] == [] and call["scout_finding_id"] is None
    assert out["finding_id"] is None


def test_generate_tool_resolves_the_finding_before_the_job_starts(tmp_db, monkeypatch):
    """A bad id must come back as a ToolError now, not as a failed job
    the agent has to poll for."""
    import asyncio

    from mcp.server.mcpserver.exceptions import ToolError

    monkeypatch.setenv("ZEROPAGE_MCP_ENGINE", "1")
    server = mcp_server.build_server(dsn=tmp_db)
    with pytest.raises(ToolError, match="no finding 4242"):
        asyncio.run(server.call_tool("generate", {"finding_id": 4242}))
    props = {t.name: t for t in _tools(server)}["generate"].input_schema["properties"]
    assert "finding_id" in props


def test_engine_tools_are_off_by_default(tmp_db, monkeypatch):
    monkeypatch.delenv(mcp_server.ENGINE_ENV, raising=False)
    server = mcp_server.build_server(dsn=tmp_db)
    names = {t.name for t in _tools(server)}
    assert "board" in names
    assert "research" not in names and "generate" not in names


def test_engine_tools_register_under_the_flag(tmp_db, monkeypatch):
    monkeypatch.setenv(mcp_server.ENGINE_ENV, "1")
    server = mcp_server.build_server(dsn=tmp_db)
    names = {t.name for t in _tools(server)}
    assert {"research", "generate"} <= names


def test_path_is_never_published_to_the_model(tmp_db):
    """Every tool binds its database path in the closure. Publishing it
    as an argument would let a remote caller name the file the server
    reads and writes."""
    server = mcp_server.build_server(dsn=tmp_db)
    for tool in _tools(server):
        assert "path" not in (tool.input_schema.get("properties") or {})


def test_read_only_tools_say_so(tmp_db):
    """The annotation is what lets a client show a confirmation before a
    write and none before a read."""
    server = mcp_server.build_server(dsn=tmp_db)
    by_name = {t.name: t for t in _tools(server)}
    assert by_name["board"].annotations.read_only_hint is True
    assert by_name["pick"].annotations.read_only_hint is False


def test_caller_errors_reach_the_model(tmp_db):
    """A ValueError from the tool layer must arrive as a ToolError, or
    the SDK replaces its message with a generic crash string and an
    agent cannot tell a bad id from a broken server."""
    import asyncio

    from mcp.server.mcpserver.exceptions import ToolError

    server = mcp_server.build_server(dsn=tmp_db)
    with pytest.raises(ToolError, match="no idea 999999"):
        asyncio.run(server.call_tool("idea", {"idea_id": 999999}))


# ---------- bad input ----------

@pytest.mark.parametrize("call", [
    lambda p: mcp_server.list_ideas(status="bogus", dsn=p),
    lambda p: mcp_server.list_ideas(brand="nope", dsn=p),
    lambda p: mcp_server.get_idea(999999, dsn=p),
    lambda p: mcp_server.shoot_idea(999999, dsn=p),
    lambda p: mcp_server.run_graph(brand="zeropage", finding_id=999999),
    lambda p: mcp_server.run_graph("", "zeropage"),
    lambda p: mcp_server.capture_idea("zeropage", "   ", dsn=p),
    lambda p: mcp_server.capture_idea("nope", "Title", dsn=p),
    lambda p: mcp_server.bank_spark("zeropage", "  ", dsn=p),
    lambda p: mcp_server.search_ideas("", dsn=p),
    lambda p: mcp_server.run_research("zeropage", lanes=["moon"], dsn=p),
])
def test_bad_input_raises_a_value_error(call, tmp_db):
    with pytest.raises(ValueError):
        call(tmp_db)


def _tools(server):
    import asyncio

    return asyncio.run(server.list_tools())


# ---------- the stdio entry point ----------

def test_main_runs_stdio_and_never_blocks_on_the_engine(tmp_db, monkeypatch):
    """Claude Desktop launches this process and talks down a pipe, so
    two things have to be true before the first tool call: the tables
    exist (a fresh clone would otherwise answer `board` with "no such
    table"), and a job registry is wired in -- a graph run takes minutes
    and a tool call that blocks that long is one the desktop times out.
    """
    captured = {}

    class FakeServer:
        def run(self, transport):
            captured["transport"] = transport

    def fake_build(dsn=None, start_job=None, job_status=None, **kw):
        captured.update(dsn=dsn, start_job=start_job, job_status=job_status)
        return FakeServer()

    monkeypatch.setattr(mcp_server, "build_server", fake_build)
    assert mcp_server.main(["--db", str(tmp_db)]) == 0
    assert captured["transport"] == "stdio"
    assert captured["dsn"] == str(tmp_db)
    assert callable(captured["start_job"]) and callable(captured["job_status"])


def test_engine_flag_is_the_same_switch_as_the_env_var(tmp_db, monkeypatch):
    monkeypatch.delenv(mcp_server.ENGINE_ENV, raising=False)

    class FakeServer:
        def run(self, transport):
            pass

    monkeypatch.setattr(mcp_server, "build_server",
                        lambda **kw: FakeServer())
    mcp_server.main(["--db", str(tmp_db), "--engine"])
    assert mcp_server.engine_enabled()


# ---------- picking from a phone spends nothing ----------
# From 2026-09-08 a pick from the phone drew the scene's still. Since
# 2026-09-29 a still costs credits, and every spend of credits sits behind
# a priced approve a person presses (the Queue card's "Draw keyframes"), so
# the pick is back to recording the choice and saying what drawing costs.

def _scene(path, title="Cold Open", prompt="P", **shot):
    base = {"n": 1, "type": "BROLL", "source": "AI", "tool": "RUNWAY",
            "desc": title, "prompt": prompt}
    base.update(shot)
    return preprod.save_concept(
        {"title": title, "hook": "", "logline": "", "shots": [base]},
        brand="zeropage", prompt_template="T", dsn=path, account_id=None)


@pytest.fixture
def stills(monkeypatch):
    from src import scene_chain
    calls = []
    monkeypatch.delenv("ZEROPAGE_KEYFRAME_ON_PICK", raising=False)
    monkeypatch.setattr(scene_chain, "keyframe_scene",
                        lambda cid, n=None, **kw: calls.append((cid, n)) or
                        {"ok": True, "media_url": "https://example.test/k.jpg",
                         "frames": ["b"]})
    return calls


def test_picking_from_a_phone_draws_nothing_and_says_the_price(tmp_db, stills):
    from src import nano_banana, pricing
    cid = _scene(tmp_db)
    card = mcp_server.pick_idea(cid, dsn=tmp_db)
    assert card["status"] == "picked"
    assert stills == []                                   # nothing drawn
    each = pricing.still_credits(nano_banana.MODEL)
    assert card["keyframes"]["stills"] == 1
    assert card["keyframes"]["credits"] == each
    assert "Draw keyframes" in card["keyframes"]["note"]
    assert "keyframe" not in card                         # the old field is gone


def test_unpicking_draws_nothing(tmp_db, stills):
    cid = _scene(tmp_db)
    card = mcp_server.pick_idea(cid, picked=False, dsn=tmp_db)
    assert "keyframes" not in card
    assert stills == []


def test_a_scene_that_already_has_a_still_quotes_nothing(tmp_db, stills):
    cid = _scene(tmp_db, reference_image="https://example.test/old.jpg")
    card = mcp_server.pick_idea(cid, dsn=tmp_db)
    assert "keyframes" not in card
    assert stills == []


def test_with_drawing_off_there_is_nothing_to_quote(tmp_db, stills, monkeypatch):
    monkeypatch.setenv("ZEROPAGE_KEYFRAME_ON_PICK", "0")
    cid = _scene(tmp_db)
    assert "keyframes" not in mcp_server.pick_idea(cid, dsn=tmp_db)
    assert stills == []


def test_the_clip_is_still_not_reachable_from_here(tmp_db, stills):
    """Picking must not be able to call a renderer -- or, since
    2026-09-29, the image model."""
    cid = _scene(tmp_db)
    mcp_server.pick_idea(cid, dsn=tmp_db)
    source = Path(mcp_server.__file__).read_text()
    imported = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom):
            imported.update(alias.name for alias in node.names)
            if node.module:
                imported.add(node.module.split(".")[0])
        elif isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
    assert not (FORBIDDEN & imported)


# ---------- what the directory publishes (2026-10-07) ----------
#
# A listed connector is read by strangers. Every tool's title, description
# and hints come from constants (TITLES / DESCRIPTIONS / HINTS) and the
# test pins them there, screens the vocabulary, and checks the caps and
# error shapes the connector checklist grades.

def _published(server):
    return {t.name: t for t in _tools(server)}


def _result(call_result):
    """The dict a tool returned. The studio surface answers with
    structuredContent (2026-10-09, step 7) and a human line as its first
    text block; the board and listed servers still return a `-> dict`,
    serialised as JSON text."""
    import json

    if call_result.structured_content is not None:
        return call_result.structured_content
    return json.loads(call_result.content[0].text)


def test_every_tool_is_published_from_its_constant(tmp_db, monkeypatch):
    monkeypatch.setenv(mcp_server.ENGINE_ENV, "1")
    server = mcp_server.build_server(dsn=tmp_db, job_status=lambda i, account_id=None: None,
                                     approve_render=lambda *a: {},
                                     approve_keyframes=lambda *a: {},
                                     cancel_job=lambda i, account_id=None: None)
    studio = mcp_server.build_server(dsn=tmp_db, surface="studio",
                                     job_status=lambda i, account_id=None: None,
                                     cancel_job=lambda i, account_id=None: None)
    # the board carries every tool but the studio-only one (import_file reads
    # the local disk); the studio adds it -- together, every constant
    tools = {**_published(studio), **_published(server)}
    assert set(tools) == set(mcp_server.TITLES) == set(mcp_server.DESCRIPTIONS) \
        == set(mcp_server.HINTS)
    for name, tool in tools.items():
        assert tool.title == mcp_server.TITLES[name]
        assert tool.description == mcp_server.DESCRIPTIONS[name]
        hints = mcp_server.HINTS[name]
        ann = tool.annotations
        assert ann.title == tool.title
        assert ann.read_only_hint is hints["read"]
        assert ann.destructive_hint is hints["destructive"]
        assert ann.idempotent_hint is hints["idempotent"]
        assert ann.open_world_hint is hints["open_world"]
        assert len(name) <= 64


def test_descriptions_carry_no_operator_vocabulary(tmp_db, monkeypatch):
    """"The nightly", "the Dev Studio", a venv command: words a directory
    user does not have, screened out of every title and description."""
    monkeypatch.setenv(mcp_server.ENGINE_ENV, "1")
    server = mcp_server.build_server(dsn=tmp_db, job_status=lambda i, account_id=None: None,
                                     approve_render=lambda *a: {},
                                     approve_keyframes=lambda *a: {},
                                     cancel_job=lambda i, account_id=None: None)
    for name, tool in _published(server).items():
        text = f"{tool.title} {tool.description}".lower()
        for word in mcp_server.INTERNAL_WORDS:
            assert word.lower() not in text, f"{name}: {word!r}"
    assert "nightly" not in mcp_server.INSTRUCTIONS.lower()


def test_hints_are_true_to_what_the_tool_does(tmp_db):
    """archive is reversible (not destructive); imagine_reference spends
    (destructive); a read is read-only and idempotent; the tools that reach
    the web say so."""
    h = mcp_server.HINTS
    assert h["archive"]["destructive"] is False and h["archive"]["idempotent"] is True
    assert h["imagine_reference"]["destructive"] is True
    assert h["imagine_reference"]["read"] is False
    assert all(h[n]["read"] and h[n]["idempotent"]
               for n in ("board", "idea", "search", "stats", "sparks", "tonight", "images", "job"))
    assert all(h[n]["open_world"] for n in ("images_for", "reference", "research"))
    assert not any(h[n]["read"] for n in ("capture", "pick", "shoot", "archive", "add_spark"))


def test_vocabularies_are_published_as_enums(tmp_db, monkeypatch):
    monkeypatch.setenv(mcp_server.ENGINE_ENV, "1")
    server = mcp_server.build_server(dsn=tmp_db)
    tools = _published(server)
    status = tools["board"].input_schema["properties"]["status"]
    assert status["enum"] == list(mcp_server.STATUSES)
    brand = tools["capture"].input_schema["properties"]["brand"]
    assert brand["enum"] == list(preprod.BRANDS)
    assert brand["default"] == mcp_server.DEFAULT_BRAND
    lanes = tools["research"].input_schema["properties"]["lanes"]
    assert any(opt.get("items", {}).get("enum") == list(scout.KNOWN_LANES)
               for opt in lanes.get("anyOf", [lanes]))


def test_a_stranger_can_capture_without_naming_a_brand(tmp_db):
    server = mcp_server.build_server(dsn=tmp_db)
    import asyncio

    out = _result(asyncio.run(server.call_tool("capture", {"title": "A door that breathes"})))
    assert out["brand"] == mcp_server.DEFAULT_BRAND
    assert out["status"] == "open"


def test_the_listing_cap_is_said_out_loud(tmp_db):
    """A list that stops at the cap with no word looks complete."""
    preprod.save_concept_ideas([_idea(f"Idea {i}") for i in range(30)],
                               brand="zeropage", dsn=tmp_db, account_id=None)
    out = mcp_server.list_ideas(dsn=tmp_db)
    assert out["count"] == mcp_server.LIST_LIMIT == len(out["ideas"])
    assert out["truncated"] is True and "narrow" in out["note"]
    assert mcp_server.list_ideas(limit=100, dsn=tmp_db)["truncated"] is False
    hits = mcp_server.search_ideas("Idea", limit=10, dsn=tmp_db)
    assert hits["count"] == 10 and hits["truncated"] is True
    assert mcp_server.search_ideas("Idea 7", dsn=tmp_db)["truncated"] is False
    # the cap is named in the description a stranger reads
    assert "maximum 100" in mcp_server.DESCRIPTIONS["board"]


def test_images_for_an_unknown_direction_is_an_error_not_an_empty_list(tmp_db):
    import asyncio

    from mcp.server.mcpserver.exceptions import ToolError

    server = mcp_server.build_server(dsn=tmp_db)
    with pytest.raises(ToolError, match="no finding 424242"):
        asyncio.run(server.call_tool("images", {"finding_id": 424242}))
    fid = _banked(tmp_db)
    assert mcp_server.spark_images(fid, dsn=tmp_db)["count"] == 2


def test_writes_act_as_the_explicit_account_the_server_was_built_for(pg):
    """build_server(account_id=X) is how the Guide opens a server for a
    signed-in request. capture/pick/shoot/archive used to ignore it and
    fall through to the bootstrap account (AUDIT.md F-9)."""
    import asyncio

    from conftest import seed_two

    from src import accounts

    preprod.init(pg)
    scout.init(pg)
    seed_two("mike@example.com", dsn=pg)
    with db.connect(pg) as conn:
        other = conn.execute("SELECT id FROM accounts WHERE slug='antihero'").fetchone()["id"]
    bootstrap = accounts.resolve_account(dsn=pg)
    assert bootstrap != other

    server = mcp_server.build_server(dsn=pg, account_id=other)
    card = _result(asyncio.run(server.call_tool("capture", {"title": "Theirs"})))
    picked = _result(asyncio.run(server.call_tool("pick", {"idea_id": card["id"]})))
    assert picked["status"] == "picked"
    assert [c["title"] for c in preprod.list_concepts(dsn=pg, account_id=other)] == ["Theirs"]
    assert preprod.list_concepts(dsn=pg, account_id=bootstrap) == []


# ---------- Claude writes the scene, the studio renders it (2026-10-07) ----

SCENE = ("Ultra-realistic grounded video in 9:16; the attached photo is the exact face. "
         "Style: soft window light, true colour, a 35mm frame at chest height. "
         "(0-4s) Sam lifts the lid of a dented biscuit tin and freezes. "
         "(4-10s) Hard cut to the hallway: Sam backs away from the open door, the tin "
         "still in one hand. No background music. Only diegetic sound: the tin lid, "
         "a floorboard. Avoid: plastic sheen, cartoon reactions.")
FACE = "/characters/sam/photo/face.jpg"


@pytest.fixture
def studio(tmp_db, monkeypatch):
    """One idea and one element photo, the catalogue stood in for (the
    photos live on disk and in R2; what is under test is the gate)."""
    from src import asset_shelf

    monkeypatch.setenv("FAL_KEY", "OPERATOR-FAL")
    monkeypatch.delenv("QUOTE_SIGNING_SECRET", raising=False)
    monkeypatch.setattr(asset_shelf, "catalogue",
                        lambda dsn=None, account_id=None:
                        [{"category": "character", "name": "Sam", "text": "a tired courier",
                          "photos": [FACE, "/characters/sam/photo/side.jpg"]},
                         {"category": "prop", "name": "Tin", "text": "", "photos": []}])
    (idea_id,) = preprod.save_concept_ideas(
        [{"title": "The Tin", "hook": "a dented tin", "logline": "Sam finds a tin."}],
        brand="zeropage", dsn=tmp_db, account_id=None)
    return tmp_db, idea_id


def test_elements_lists_the_accounts_photos_as_refs(studio):
    path, _ = studio
    out = mcp_server.list_elements(dsn=path)
    assert [e["name"] for e in out["elements"]] == ["Sam", "Tin"]
    assert out["elements"][0]["photos"][0] == {"ref": FACE, "label": "face.jpg"}
    assert out["elements"][1]["photos"] == []


def test_write_scene_refuses_what_elements_did_not_issue(studio):
    path, idea = studio
    with pytest.raises(ValueError, match="not one of your elements"):
        mcp_server.write_scene(idea, SCENE, refs=["https://example.com/face.jpg"], dsn=path)
    with pytest.raises(ValueError, match="not one of your elements"):
        mcp_server.write_scene(idea, SCENE, refs=["/characters/other/photo/x.jpg"], dsn=path)
    with pytest.raises(ValueError, match="too short"):
        mcp_server.write_scene(idea, "a man and a tin", refs=[FACE], dsn=path)
    with pytest.raises(ValueError, match="placeholder"):
        mcp_server.write_scene(idea, SCENE + " {look}", refs=[FACE], dsn=path)
    with pytest.raises(ValueError, match="no idea 424242"):
        mcp_server.write_scene(424242, SCENE, refs=[FACE], dsn=path)


def test_write_scene_with_no_photos_is_refused_by_the_reference_gate(studio, monkeypatch):
    path, idea = studio
    monkeypatch.setattr(preprod, "refs_required", lambda: True)
    with pytest.raises(ValueError, match="attach at least one"):
        mcp_server.write_scene(idea, SCENE, refs=[], dsn=path)
    # and nothing was written
    assert preprod.get_concept(idea, dsn=path, account_id=None)["shots"] == []


def test_write_scene_grounds_a_captured_idea_with_the_rule_on(studio, monkeypatch):
    """Production runs with the reference rule ON. A captured idea comes
    back from get_concept with a top-level `refs: []`, which the gate
    read before the new shot's refs -- so every write_scene on a captured
    idea was refused as ungrounded (2026-10-08)."""
    path, idea = studio
    monkeypatch.setattr(preprod, "refs_required", lambda: True)
    assert preprod.get_concept(idea, dsn=path, account_id=None).get("refs") == []
    out = mcp_server.write_scene(idea, SCENE, seconds=10, refs=[FACE], dsn=path)
    assert out["shots_written"] == 2
    concept = preprod.get_concept(idea, dsn=path, account_id=None)
    assert concept["shots"][0]["refs"] == [FACE]
    assert preprod.reference_gate(concept) is None


def test_write_scene_saves_the_timed_shots_without_a_model_call(studio):
    from src import timeline

    path, idea = studio
    out = mcp_server.write_scene(idea, SCENE, seconds=10, refs=[FACE, FACE], dsn=path)
    assert out["shots_written"] == 2 and out["seconds"] == 10
    shot = preprod.get_concept(idea, dsn=path, account_id=None)["shots"][0]
    assert shot["prompt"] == SCENE and shot["refs"] == [FACE]
    assert shot["n"] == 1 and shot["source"] == "AI" and shot["written_by"] == "chat"
    tl = shot["timeline"]
    assert tl["planner"] == "split" and [p["n"] for p in tl["parts"]] == [1, 2]
    assert tl["parts"][0]["refs"] == [FACE]
    assert timeline.is_current(shot)          # ensure() will not re-plan it
    assert preprod.reference_gate(preprod.get_concept(idea, dsn=path, account_id=None)) is None
    # a prompt with no windows is one shot
    out = mcp_server.write_scene(idea, SCENE.replace("(0-4s) ", "").replace("(4-10s) ", ""),
                                 seconds=8, refs=[FACE], dsn=path)
    shot = preprod.get_concept(idea, dsn=path, account_id=None)["shots"][0]
    assert out["shots_written"] == 1 and "timeline" not in shot and shot["seconds"] == 8


def test_quote_prices_the_stills_and_the_clip_and_says_what_is_affordable(studio):
    path, idea = studio
    with pytest.raises(ValueError, match="no scene prompt yet"):
        mcp_server.quote_render(idea, dsn=path)
    mcp_server.write_scene(idea, SCENE, refs=[FACE], dsn=path)
    q = mcp_server.quote_render(idea, dsn=path)
    assert q["keyframes"]["stills"] == 2 and q["keyframes"]["credits"] > 0
    assert q["clip"]["timed"] is True and len(q["clip"]["renders"]) == 2
    assert q["clip"]["signed"] is False and q["clip"]["renders"][0]["token"] is None
    assert q["credits_needed"] == q["keyframes"]["credits"] + q["clip"]["credits"]
    # the unowned pool has no balance to check, so nothing is refused here
    assert q["balance"] is None and q["affordable"] is True
    with pytest.raises(ValueError, match="bad renderer choice"):
        mcp_server.quote_render(idea, model="no-such-model", dsn=path)


def test_approve_runs_the_injected_bodies_and_translates_a_refusal(studio):
    import asyncio

    from mcp.server.mcpserver.exceptions import ToolError

    from src.approvals import ApproveRefused

    path, idea = studio
    seen = []

    def render(concept_id, account_id, body):
        seen.append(("clip", concept_id, body))
        if not body.get("tokens"):
            raise ApproveRefused(400, "missing_quote", "no quote for this render")
        return {"job_id": 7, "render": {"provider": body["provider"]}}

    def keyframes(concept_id, account_id):
        seen.append(("keyframes", concept_id))
        raise ApproveRefused(402, "out_of_credits", "top up")

    server = mcp_server.build_server(dsn=path, approve_render=render,
                                     approve_keyframes=keyframes)
    assert "approve" in {t.name for t in _tools(server)}
    with pytest.raises(ToolError, match="missing_quote.*`quote`"):
        asyncio.run(server.call_tool("approve", {"idea_id": idea, "provider": "fal"}))
    out = _result(asyncio.run(server.call_tool(
        "approve", {"idea_id": idea, "provider": "fal", "tokens": ["zpfq.x.y"]})))
    assert out["job_id"] == 7 and "job" in out["note"]
    with pytest.raises(ToolError, match="out_of_credits: top up"):
        asyncio.run(server.call_tool("approve", {"idea_id": idea, "what": "keyframes"}))
    assert [s[0] for s in seen] == ["clip", "clip", "keyframes"]
    assert seen[1][2]["tokens"] == ["zpfq.x.y"]


def test_approve_is_absent_without_the_approve_bodies(tmp_db):
    names = {t.name for t in _tools(mcp_server.build_server(dsn=tmp_db))}
    assert "quote" in names and "approve" not in names


# ---------- the studio surface: generation only, everything approved (2026-10-07) ----------
# Mike's call: the MCP Claude Desktop launches is for making images, video
# and effects with Claude, never for adding to the board; and every one of
# the three is quoted first and spent only after a yes in chat.

BOARD_ONLY = {"board", "idea", "search", "capture", "pick", "shoot", "archive",
              "add_spark", "write_scene", "quote", "tonight", "sparks", "images",
              "reference", "imagine_reference", "stats", "research", "generate"}
SPENDS = {"generate_image", "generate_video", "apply_effect"}


def _job_status(i, account_id=None):
    return None


def _cancel_job(i, account_id=None):
    return None


def test_the_studio_surface_has_no_board_tools(tmp_db, monkeypatch):
    monkeypatch.delenv(mcp_server.ENGINE_ENV, raising=False)
    server = mcp_server.build_server(dsn=tmp_db, surface="studio", job_status=_job_status,
                                     cancel_job=_cancel_job)
    names = {t.name for t in _tools(server)}
    assert names == set(mcp_server.STUDIO_TOOLS)   # the spending doors need no engine flag
    assert not names & BOARD_ONLY


def test_the_studio_surface_ignores_the_engine_flag(tmp_db, monkeypatch):
    monkeypatch.setenv(mcp_server.ENGINE_ENV, "1")
    names = {t.name for t in _tools(mcp_server.build_server(dsn=tmp_db, surface="studio"))}
    assert "research" not in names and "generate" not in names
    assert SPENDS <= names


def test_the_board_surface_keeps_every_tool(tmp_db, monkeypatch):
    monkeypatch.setenv(mcp_server.ENGINE_ENV, "1")
    names = {t.name for t in _tools(mcp_server.build_server(dsn=tmp_db, job_status=_job_status,
                                                            cancel_job=_cancel_job))}
    assert set(mcp_server.STUDIO_TOOLS) - {"import_file"} <= names
    assert "import_file" not in names        # the local disk is the studio's (stdio) only
    assert (BOARD_ONLY - {"approve"}) <= names


def test_the_board_spends_only_under_the_engine_flag(tmp_db, monkeypatch):
    monkeypatch.delenv(mcp_server.ENGINE_ENV, raising=False)
    names = {t.name for t in _tools(mcp_server.build_server(dsn=tmp_db))}
    assert {"image_models", "video_models", "effects", "renders", "prompt_craft"} <= names
    assert not names & SPENDS


def test_the_listed_server_never_carries_the_studio_doors(tmp_db, monkeypatch):
    monkeypatch.setenv(mcp_server.ENGINE_ENV, "1")
    names = {t.name for t in _tools(mcp_server.build_server(dsn=tmp_db, listed=True))}
    assert names <= set(mcp_server.LISTED_TOOLS)
    assert not names & SPENDS


@pytest.mark.parametrize("kwargs", [{"surface": "everything"},
                                    {"surface": "studio", "listed": True}])
def test_an_impossible_surface_is_refused(tmp_db, kwargs):
    with pytest.raises(ValueError):
        mcp_server.build_server(dsn=tmp_db, **kwargs)


@pytest.mark.parametrize("argv, env, want", [
    ([], None, "studio"),                              # what Claude Desktop gets
    (["--surface", "board"], None, "board"),           # what the research agent asks for
    ([], "board", "board"),
    ([], "typo", "studio"),                            # a typo is the safe server
])
def test_main_serves_the_studio_surface_by_default(tmp_db, monkeypatch, argv, env, want):
    captured = {}

    class FakeServer:
        def run(self, transport):
            pass

    monkeypatch.setattr(mcp_server, "build_server",
                        lambda **kw: captured.update(kw) or FakeServer())
    if env is None:
        monkeypatch.delenv(mcp_server.SURFACE_ENV, raising=False)
    else:
        monkeypatch.setenv(mcp_server.SURFACE_ENV, env)
    mcp_server.main(["--db", str(tmp_db)] + argv)
    assert captured["surface"] == want


def test_the_research_agent_asks_for_the_board():
    source = (Path(__file__).resolve().parent.parent / "src" / "research_agent.py").read_text()
    assert '"--surface", "board"' in source


def test_the_studio_instructions_carry_no_operator_vocabulary():
    text = mcp_server.STUDIO_INSTRUCTIONS.lower()
    for word in mcp_server.INTERNAL_WORDS:
        assert word.lower() not in text, word
    assert "quote_token" in text and "approve_usd" not in text


# ---------- references by id ----------

def _stub_sources(monkeypatch, assets=None, cands=None, photos=None, project_refs=None):
    from src import asset_shelf, fal, imagesearch, projects, render_assets
    monkeypatch.setattr(projects, "scene_refs",
                        lambda dsn=None, account_id=None, project_id=None: [
                            {"ref": r, "concept_ids": [1], "project_ids": [2]}
                            for r in (project_refs or [])])
    monkeypatch.setattr(render_assets, "get",
                        lambda i, dsn=None, account_id=None: (assets or {}).get(i))
    monkeypatch.setattr(imagesearch, "get", lambda c, dsn=None: (cands or {}).get(c))
    monkeypatch.setattr(asset_shelf, "catalogue", lambda dsn=None, account_id=None: [
        {"category": "character", "name": "Sam", "text": "",
         "photos": list(photos if photos is not None else ["https://r2/s1.jpg", "https://r2/s2.jpg"])}])
    monkeypatch.setattr(asset_shelf, "storable_ref", lambda url: "sam/" + url.rsplit("/", 1)[-1])
    monkeypatch.setattr(asset_shelf, "fetch_url", lambda raw, acct=None: raw)
    monkeypatch.setattr(fal, "as_image_url",
                        lambda v, **kw: v if str(v).startswith("https://") else None)


def test_references_resolve_by_id(monkeypatch):
    _stub_sources(monkeypatch,
                  assets={5: {"media_kind": "image", "media_url": "https://r2/a.png"}},
                  cands={"c1": {"image_url": "https://r2/c.jpg", "source": "web"}})
    refs = [p["ref"] for p in mcp_server.list_elements()["elements"][0]["photos"]]
    assert refs == ["sam/s1.jpg", "sam/s2.jpg"]
    out = mcp_server.resolve_references(["gen:5", refs[0], refs[1], "candidate:c1", "gen:5"],
                                        limit=10, who="X")
    assert out == ["https://r2/a.png", "https://r2/s1.jpg", "https://r2/s2.jpg",
                   "https://r2/c.jpg"]


@pytest.mark.parametrize("ref", [
    "https://x/a.png", "file:///etc/passwd", "gen:99", "gen:6", "gen:7",
    "sam/nobody.jpg", "element:character/sam", "candidate:nope", "junk",
])
def test_bad_references_are_refused(ref, monkeypatch):
    _stub_sources(monkeypatch,
                  assets={6: {"media_kind": "video", "media_url": "https://r2/v.mp4"},
                          7: {"media_kind": "image", "media_url": "https://r2/d.png",
                              "deleted_at": "x"}})
    with pytest.raises(ValueError):
        mcp_server.resolve_references([ref], limit=4, who="X")


def test_reference_limits_are_enforced_before_spend(monkeypatch):
    _stub_sources(monkeypatch)
    with pytest.raises(ValueError, match="takes no reference"):
        mcp_server.resolve_references(["sam/s1.jpg"], limit=0, who="FLUX 1.1 Pro")
    with pytest.raises(ValueError, match="at most 1"):
        mcp_server.resolve_references(["sam/s1.jpg", "sam/s2.jpg"], limit=1, who="X")
    assert mcp_server.resolve_references([], limit=0, who="X") == []


def test_an_unfetchable_reference_is_refused(monkeypatch):
    _stub_sources(monkeypatch, assets={5: {"media_kind": "image", "media_url": "/local/a.png"}})
    with pytest.raises(ValueError, match="fetchable"):
        mcp_server.resolve_references(["gen:5"], limit=4, who="X")


# ---------- the approval: credits, a signed token, once (2026-10-08) ----------

@pytest.fixture
def signed(monkeypatch):
    """Quotes sign only where a test says so (conftest strips the secret)."""
    monkeypatch.setenv("QUOTE_SIGNING_SECRET", "test-quote-secret")


def _wallet(monkeypatch, balance=1000, exempt=False):
    """An account's balance and exemption without a database: the two reads
    the gate makes."""
    from src import ledger
    monkeypatch.setattr(ledger, "credit_exempt", lambda a, dsn=None: exempt)
    monkeypatch.setattr(mcp_server, "_balance",
                        lambda a, dsn: balance if a is not None else None)


def _approved(fn, **kwargs):
    """A person's yes, as the two calls it takes: the quote, then the SAME
    call with its token."""
    q = fn(**kwargs)
    assert q["needs_approval"] is True and q["quote"]["quote_token"], q
    return q, fn(**kwargs, quote_token=q["quote"]["quote_token"])


# ---------- images ----------

def _stub_still(monkeypatch):
    from src import fal
    calls = []

    def fake(prompt, **kw):
        calls.append({"prompt": prompt, **kw})
        return {"ok": True, "media_url": "https://x/y.jpg", "asset_id": 3}

    monkeypatch.setattr(fal, "generate_image_from_prompt", fake)
    return calls


def test_image_models_projects_the_catalogue():
    from src import fal
    out = mcp_server.list_image_models()
    assert [m["id"] for m in out["models"]] == list(fal.IMAGE_MODEL_NAMES)
    assert out["default"] == fal.DEFAULT_IMAGE_MODEL and out["aspects"] == list(fal.IMAGE_SIZES)
    limits = {m["id"]: m["max_references"] for m in out["models"]}
    assert limits["flux-pro1.1"] == 0 and limits["gpt-image-2"] == 16


def test_an_image_is_quoted_before_anything_is_spent(monkeypatch, signed):
    from src import fal, ledger
    calls = _stub_still(monkeypatch)
    _wallet(monkeypatch, balance=500)
    out = mcp_server.run_image("a can", model="seedream4.5", account_id=7)
    assert out["needs_approval"] is True and out["ok"] is False and out["can_approve"]
    usd = fal.image_usd("seedream4.5")
    q = out["quote"]
    assert q["usd"] == usd and q["credits"] == ledger.charge_credits(usd)
    assert q["charged"] is True and q["balance"] == 500
    assert q["balance_after"] == 500 - q["credits"]
    assert q["quote_token"].startswith("zpfq.") and q["expires_at"]
    assert f"costs {q['credits']} credits" in out["note"] and "quote_token" in out["note"]
    with pytest.raises(ValueError, match="stale_content"):     # said yes to another model
        mcp_server.run_image("a can", model="nano-banana-pro", account_id=7,
                             quote_token=q["quote_token"])
    assert calls == []


def test_an_approved_image_renders_the_chosen_model(monkeypatch, signed):
    calls = _stub_still(monkeypatch)
    _wallet(monkeypatch)
    q, out = _approved(mcp_server.run_image, prompt="  a  can ", model="ideogram4.5",
                       aspect="4:5", account_id=7)
    (c,) = calls
    assert c["prompt"] == "a can" and c["model"] == "ideogram4.5" and c["aspect"] == "4:5"
    assert c["approved"] is True and c["account_id"] == 7
    assert c["source"] == "mcp" and c["bank"] is True and c["reference_urls"] is None
    # the hold is the number the person said yes to, handed down signed
    assert c["quote"].credits == q["quote"]["credits"] and c["quote"].provider == "fal"
    assert c["quote"].account_id == 7 and c["quote"].tool == "generate_image"
    assert out["ok"] and out["quote"]["usd"] == 0.06 and out["asset_id"] == 3


def test_image_references_are_passed_and_priced(monkeypatch, signed):
    from src import fal
    _stub_sources(monkeypatch)
    calls = _stub_still(monkeypatch)
    _, out = _approved(mcp_server.run_image, prompt="a can", model="flux2-pro",
                       references=["sam/s1.jpg"])
    assert calls[0]["reference_urls"] == ["https://r2/s1.jpg"]
    assert out["quote"]["usd"] == fal.image_usd("flux2-pro", references=1) \
        > fal.image_usd("flux2-pro")
    with pytest.raises(ValueError, match="no reference"):
        mcp_server.run_image("a can", model="flux-pro1.1", references=["sam/s1.jpg"])


@pytest.mark.parametrize("kwargs", [
    {"prompt": "  "},
    {"prompt": "a can", "model": "midjourney"},
    {"prompt": "a can", "model": "flux2-pro", "aspect": "7:3"},
])
def test_run_image_refuses_instead_of_clamping(kwargs, monkeypatch, signed):
    calls = _stub_still(monkeypatch)
    with pytest.raises(ValueError):
        mcp_server.run_image(**kwargs, quote_token="zpfq.a.b")
    assert calls == []


# ---------- video ----------

def _stub_render(monkeypatch):
    from src import fal
    calls = []

    def fake(prompt, **kw):
        calls.append({"prompt": prompt, **kw})
        return {"ok": True, "media_url": "https://x/clip.mp4", "generation_id": 1}

    monkeypatch.setattr(fal, "generate_from_prompt", fake)
    return calls


def test_video_models_projects_the_queues_menu():
    from src import providers
    out = mcp_server.list_video_models()
    assert [m["id"] for m in out["models"]] == [m["id"] for m in providers.models_for("fal")]


def test_a_clip_is_quoted_and_a_changed_length_is_caught(monkeypatch, signed):
    calls = _stub_render(monkeypatch)
    out = mcp_server.run_video("a can", model="ltx2.3", seconds=6)
    assert out["needs_approval"] is True and out["quote"]["model"] == "ltx2.3"
    assert out["quote"]["usd"] > 0 and out["quote"]["credits"] > 0
    with pytest.raises(ValueError, match="stale_content"):     # said yes to 6s, asked for 10s
        mcp_server.run_video("a can", model="ltx2.3", seconds=10,
                             quote_token=out["quote"]["quote_token"])
    with pytest.raises(ValueError, match="stale_content"):     # ...or reworded the prompt
        mcp_server.run_video("a can on a table", model="ltx2.3", seconds=6,
                             quote_token=out["quote"]["quote_token"])
    assert calls == []


def test_an_approved_price_renders_the_chosen_model_and_length(monkeypatch, signed):
    calls = _stub_render(monkeypatch)
    _wallet(monkeypatch)
    monkeypatch.setattr(mcp_server, "resolve_references",
                        lambda refs, **kw: ["https://x/still.png"] if refs else [])
    q, out = _approved(mcp_server.run_video, prompt="a  can ", model="ltx2.3", seconds=6,
                       reference="gen:12", account_id=7)
    quote = q["quote"]
    assert out["ok"] and out["quote"]["from_image"] is True
    (c,) = calls
    assert c["quote"].credits == quote["credits"] and c["quote"].tool == "generate_video"
    assert c["model"] == "ltx2.3" and c["duration"] == 6 and c["prompt"] == "a can"
    assert c["resolution"] == quote["frame"] and c["reference_image"] == "https://x/still.png"
    assert c["approved"] is True and c["account_id"] == 7 and c["source"] == "mcp"
    assert c["bank"] is True


@pytest.mark.parametrize("kwargs", [
    {"prompt": "  "},
    {"prompt": "a can", "model": "runway-gen4"},
    {"prompt": "a can", "model": "ltx2.3", "seconds": 7},
    {"prompt": "a can", "model": "ltx2.3", "frame": "144p"},
    {"prompt": "a can", "reference": "https://x/a.png"},
])
def test_video_refuses_instead_of_clamping(kwargs, monkeypatch, signed):
    _stub_sources(monkeypatch)
    calls = _stub_render(monkeypatch)
    with pytest.raises(ValueError):
        mcp_server.run_video(**kwargs, quote_token="zpfq.a.b")
    assert calls == []


def test_a_signed_in_caller_is_sent_to_the_queue(monkeypatch):
    calls = _stub_render(monkeypatch)
    token = mcp_server.CALLER_ACCOUNT.set(5)
    try:
        with pytest.raises(mcp_server.Refused, match="Queue"):
            mcp_server.run_video("a can", model="ltx2.3", seconds=6, quote_token="t")
    finally:
        mcp_server.CALLER_ACCOUNT.reset(token)
    assert calls == []


def test_the_tool_quotes_inline_and_runs_an_approval_as_a_job(tmp_db, monkeypatch, signed):
    """No quote_token: the quote, no job. A bad token: refused in the
    request, before a job exists. The quote's own token: a job id -- and
    the same token again is the same job, never a second one."""
    import asyncio

    from mcp.server.mcpserver.exceptions import ToolError

    from src import quote_redemptions
    quote_redemptions.init(tmp_db)
    _stub_render(monkeypatch)
    started = []

    def start_job(kind, label, fn, cancellable=False, account_id=None):
        started.append(label)
        assert cancellable is True          # a spend can be stopped
        return {"id": 41, "status": "running"}

    server = mcp_server.build_server(dsn=tmp_db, surface="studio", start_job=start_job,
                                     job_status=_job_status)
    args = {"prompt": "a can", "model": "ltx2.3", "seconds": 6}
    quote = _result(asyncio.run(server.call_tool("generate_video", args)))
    assert quote["needs_approval"] is True and started == []
    token = quote["quote"]["quote_token"]
    with pytest.raises(ToolError, match="bad_signature"):
        asyncio.run(server.call_tool("generate_video", {**args, "quote_token": token[:-4]}))
    with pytest.raises(ToolError, match="stale_content"):
        asyncio.run(server.call_tool("generate_video",
                                     {**args, "seconds": 10, "quote_token": token}))
    assert started == []
    out = _result(asyncio.run(server.call_tool(
        "generate_video", {**args, "quote_token": token})))
    assert out["job_id"] == 41 and started == ["video ltx2.3"]
    again = _result(asyncio.run(server.call_tool(
        "generate_video", {**args, "quote_token": token})))
    assert again["job_id"] == 41 and again["already_used"] is True
    assert started == ["video ltx2.3"]                 # one yes, one job


# ---------- effects ----------

def _stub_effect(monkeypatch):
    from src import effects
    calls = []

    def fake(effect, urls, prompt, opts, **kw):
        calls.append({"effect": effect, "urls": urls, "prompt": prompt, "opts": opts, **kw})
        return {"ok": True, "media_url": "https://x/fx.mp4", "asset_id": 9}

    monkeypatch.setattr(effects, "run", fake)
    return calls


def test_effects_lists_the_catalogue_and_samples_long_enums():
    from src import effects
    out = mcp_server.list_effects()
    assert [e["id"] for e in out["effects"]] == list(effects.EFFECT_NAMES)
    kling = next(e for e in out["effects"] if e["id"] == "kling-effect")
    scene = kling["options"]["effect_scene"]
    assert scene["count"] == len(effects.KLING_EFFECTS) and len(scene["values"]) == effects.SAMPLE
    full = mcp_server.list_effects(effect="kling-effect")["effects"][0]
    assert full["options"]["effect_scene"]["values"] == list(effects.KLING_EFFECTS)
    assert {e["category"] for e in mcp_server.list_effects(category="finish")["effects"]} == {"finish"}
    with pytest.raises(ValueError):
        mcp_server.list_effects(effect="explode-everything")


def test_an_effect_is_quoted_then_run_at_the_approved_price(monkeypatch, signed):
    from src import effects
    calls = _stub_effect(monkeypatch)
    monkeypatch.setattr(mcp_server, "resolve_references",
                        lambda refs, **kw: [f"https://r2/{r}.jpg" for r in refs])
    args = dict(effect="kling-effect", sources=["gen:4"],
                options={"effect_scene": "bullet_time_360", "duration": "10"})
    q = mcp_server.run_effect(**args)
    assert q["needs_approval"] and calls == []
    assert q["quote"]["usd"] == round(0.056 * 10, 4)
    assert q["quote"]["options"] == {"effect_scene": "bullet_time_360", "duration": "10"}
    with pytest.raises(ValueError, match="stale_content"):      # a different option
        mcp_server.run_effect(**{**args, "options": {"effect_scene": "bullet_time_360",
                                                     "duration": "5"}},
                              quote_token=q["quote"]["quote_token"])
    out = mcp_server.run_effect(**args, quote_token=q["quote"]["quote_token"])
    assert out["ok"] and calls[0]["usd"] == q["quote"]["usd"]
    assert calls[0]["quote"].credits == q["quote"]["credits"]
    assert calls[0]["urls"] == ["https://r2/gen:4.jpg"] and calls[0]["source"] == "mcp"
    endpoint, body = effects.build_body("kling-effect", ["u"], "", calls[0]["opts"])
    assert endpoint.endswith("/effects") and body["input_image_urls"] == ["u"]
    assert body["effect_scene"] == "bullet_time_360" and body["duration"] == "10"


@pytest.mark.parametrize("kwargs, match", [
    ({"effect": "nope"}, "effect must be"),
    ({"effect": "kling-effect", "sources": ["gen:1"]}, "needs `effect_scene`"),
    ({"effect": "kling-effect", "sources": ["gen:1"],
      "options": {"effect_scene": "made_up"}}, "not one of"),
    ({"effect": "kling-effect", "sources": ["gen:1"],
      "options": {"effect_scene": "heart_gesture"}}, "exactly 2"),
    ({"effect": "pixverse-effect", "sources": ["gen:1"],
      "options": {"effect": "Kiss", "duration": "8"}}, "not one of"),
    ({"effect": "remove-background", "sources": ["gen:1"], "prompt": "make it pop"},
     "takes no prompt"),
    ({"effect": "flux-kontext-pro", "sources": ["gen:1"]}, "needs a prompt"),
    ({"effect": "flux-kontext-pro", "sources": ["gen:1", "gen:2"], "prompt": "x"},
     "exactly 1"),
    ({"effect": "camera-move", "sources": ["gen:1"], "prompt": "x",
      "options": {"camera_movement": "whip_pan", "speed": "fast"}}, "takes options"),
    ({"effect": "upscale", "sources": ["gen:1"], "options": {"upscale_factor": 1}},
     "without target_fps"),
])
def test_effect_refusals_happen_before_any_spend(monkeypatch, kwargs, match, signed):
    calls = _stub_effect(monkeypatch)
    monkeypatch.setattr(mcp_server, "resolve_references", lambda refs, **kw: list(refs))
    with pytest.raises(ValueError, match=match):
        mcp_server.run_effect(**kwargs, quote_token="zpfq.a.b")
    assert calls == []


def test_a_finishing_pass_is_priced_off_the_measured_clip(monkeypatch):
    from src import effects, render_assets
    calls = _stub_effect(monkeypatch)
    monkeypatch.setattr(render_assets, "get", lambda i, dsn=None, **kw: {
        "id": i, "media_kind": "video", "media_url": "https://r2/c.mp4", "output_path": ""})
    monkeypatch.setattr(effects, "probe_video",
                        lambda t: {"seconds": 10.0, "width": 720, "height": 1280, "fps": 24.0})
    q = mcp_server.run_effect("upscale", sources=["gen:3"])
    # 1280 * 2 = 2560 tall out -> the >1080p band, $0.08/s, 24fps -> no doubling
    assert q["quote"]["usd"] == 0.8 and q["quote"]["source_clip"]["seconds"] == 10.0
    q60 = mcp_server.run_effect("upscale", sources=["gen:3"], options={"target_fps": 60})
    assert q60["quote"]["usd"] == 1.6
    snd = mcp_server.run_effect("add-sound", sources=["gen:3"], prompt="rain on tin")
    assert snd["quote"]["usd"] == 0.01
    _, body = effects.build_body("add-sound", ["u"], "rain on tin", {}, {"seconds": 10.0})
    assert body["duration"] == 10 and body["video_url"] == "u"
    assert calls == []


def test_a_clip_source_must_be_a_render_on_the_wall(monkeypatch):
    from src import render_assets
    monkeypatch.setattr(render_assets, "get", lambda i, dsn=None, **kw: {
        "id": i, "media_kind": "image", "media_url": "https://r2/a.png"})
    for bad, match in [("https://x/y.mp4", "gen:<asset id>"),
                       ("sam/s1.jpg", "gen:<asset id>"),
                       ("gen:5", "takes a clip")]:
        with pytest.raises(ValueError, match=match):
            mcp_server.run_effect("upscale", sources=[bad])


def test_add_sound_refuses_a_clip_past_thirty_seconds(monkeypatch):
    from src import effects, render_assets
    monkeypatch.setattr(render_assets, "get", lambda i, dsn=None, **kw: {
        "id": i, "media_kind": "video", "media_url": "https://r2/c.mp4"})
    monkeypatch.setattr(effects, "probe_video",
                        lambda t: {"seconds": 31.0, "width": 720, "height": 1280, "fps": 24.0})
    with pytest.raises(ValueError, match="up to 30s"):
        mcp_server.run_effect("add-sound", sources=["gen:3"], prompt="wind")


# ---------- renders and the prompt guides ----------

def test_renders_lists_the_wall_as_ids(monkeypatch):
    from src import media, render_assets
    rows = [{"id": i, "media_kind": "video" if i % 2 else "image", "model": "m",
             "provider": "P", "prompt": "x" * 300, "media_url": f"https://r2/{i}"}
            for i in range(30, 0, -1)]
    monkeypatch.setattr(render_assets, "list_all", lambda dsn=None, account_id=None: rows)
    monkeypatch.setattr(media, "url_for", lambda url, account_id=None: url + "?minted")
    out = mcp_server.list_renders(kind="image", limit=3, account_id=1)
    assert [r["id"] for r in out["renders"]] == ["gen:30", "gen:28", "gen:26"]
    assert out["renders"][0]["media_url"].endswith("?minted")
    assert len(out["renders"][0]["prompt"]) == 160
    assert len(mcp_server.list_renders(limit=1000, account_id=1)["renders"]) == 30
    with pytest.raises(ValueError):        # audio is a kind since 2026-10-09 (uploads)
        mcp_server.list_renders(kind="gif", account_id=1)


def _shelf(monkeypatch, refs=None, ok=True):
    from src import rag
    monkeypatch.setattr(rag, "retrieve_references",
                        lambda text, **kw: {"ok": ok, "references":
                                            [{"source": "seedance.md", "chunk": c}
                                             for c in refs or []],
                                            "error": None if ok else "no key"})


def test_refine_hands_back_the_studios_instruction_with_the_shelf(tmp_db, monkeypatch):
    _shelf(monkeypatch, ["lead with the subject, then the camera"])
    out = mcp_server.get_prompt_craft("refine", "(0-3s) a glove on a bench",
                                      model="ltx2.3", dsn=tmp_db)
    assert "(0-3s) a glove on a bench" in out["instruction"]
    assert "lead with the subject" in out["instruction"] and out["references_found"] == 1


def test_refine_survives_an_unreachable_shelf(tmp_db, monkeypatch):
    _shelf(monkeypatch, ok=False)
    out = mcp_server.get_prompt_craft("refine", "a glove on a bench", tool="LTX", dsn=tmp_db)
    assert out["references_found"] == 0 and out["lookup_error"] == "no key"
    assert "a glove on a bench" in out["instruction"]


def test_the_other_steps_return_the_studios_rubrics(tmp_db):
    assert mcp_server.get_prompt_craft("enhance", "x", dsn=tmp_db)["instruction"]
    still = mcp_server.get_prompt_craft("still", "a push-in on a glove", dsn=tmp_db)
    assert "STILL" in still["instruction"] and "a push-in on a glove" in still["instruction"]
    beats = mcp_server.get_prompt_craft("beats", "tilt up", count=3, dsn=tmp_db)
    assert "at most 3" in beats["instruction"]


@pytest.mark.parametrize("kwargs", [
    {"step": "write", "prompt": "x"},
    {"step": "refine", "prompt": ""},
    {"step": "refine", "prompt": "x"},
    {"step": "refine", "prompt": "x", "model": "runway-gen4"},
])
def test_prompt_craft_refuses_what_it_cannot_serve(kwargs, tmp_db, monkeypatch):
    _shelf(monkeypatch)
    with pytest.raises(ValueError):
        mcp_server.get_prompt_craft(**kwargs, dsn=tmp_db)


# ---------- projects from Claude (2026-10-08) ----------
# Make a project here, reopen one made in the studio, and pull what it
# already has: its scenes, the reference images they used, its renders and
# its chat -- the same rows the studio's projects board draws.

def _project_db(tmp_db, monkeypatch):
    from src import projects, render_assets
    projects.init(tmp_db)
    render_assets.init(tmp_db)
    monkeypatch.setattr(render_assets, "_ingest",
                        lambda *a, **k: {"ok": True, "chunks": 1, "error": None})
    return tmp_db


def _scene_in(path, project_id, title, refs, **shot):
    from src import projects
    cid = preprod.save_concept(
        {"title": title, "hook": "", "logline": "",
         "shots": [{"n": 1, "type": "BROLL", "source": "AI", "tool": "RUNWAY", "desc": "d",
                    "prompt": f"{title}: a woman lifts the lid", "refs": refs, **shot}]},
        brand="zeropage", prompt_template="T", dsn=path, account_id=None)
    if project_id is not None:
        projects.tag_concepts([cid], project_id, path, account_id=None)
    return cid


def test_a_project_made_here_is_listed_and_reopened(tmp_db, monkeypatch):
    path = _project_db(tmp_db, monkeypatch)
    made = mcp_server.make_project("  Perfume   ad ", brief="gold, slow",
                                   look="soft window light", dsn=path)
    assert made["title"] == "Perfume ad" and "project_id=" in made["next"]
    listed = mcp_server.list_project_cards(dsn=path)
    assert [p["id"] for p in listed["projects"]] == [made["id"]]
    card = listed["projects"][0]
    assert card["has_look"] is True and card["brief"] == "gold, slow" and card["scenes"] == 0
    opened = mcp_server.get_project(made["id"], dsn=path)
    assert opened["look"] == "soft window light" and opened["brief"] == "gold, slow"
    assert opened["scenes"] == opened["references"] == opened["renders"] == opened["chat"] == []
    with pytest.raises(ValueError, match="needs a name"):
        mcp_server.make_project("   ", dsn=path)
    with pytest.raises(ValueError, match="no project"):
        mcp_server.get_project(999999, dsn=path)


def test_reopening_a_studio_project_brings_its_scenes_references_renders_and_chat(
        tmp_db, monkeypatch):
    from src import projects, render_assets
    path = _project_db(tmp_db, monkeypatch)
    project = projects.create("Ghost can", "an energy drink ad", path, account_id=None)
    pid = project["id"]
    first = _scene_in(path, pid, "first", ["/refs/aaa.jpg", "/characters/sam/photo/face.jpg"],
                      reference_image="https://r2/still.png")
    second = _scene_in(path, pid, "second", ["/refs/aaa.jpg", "/refs/bbb.jpg"],
                       media_url="https://r2/clip.mp4")
    _scene_in(path, None, "elsewhere", ["/refs/zzz.jpg"])
    on_scene = render_assets.record(
        generation_id=1, tool="fal", model="ltx2.3", media_kind="video", prompt="p",
        media_url="https://r2/clip.mp4", concept_id=second, dsn=path, account_id=None)
    filed = render_assets.record(
        generation_id=2, tool="fal", model="flux2-pro", media_kind="image",
        prompt="made in chat", media_url="https://r2/f.png",
        metadata={"project_id": pid}, dsn=path, account_id=None)
    render_assets.record(generation_id=3, tool="fal", model="flux2-pro", media_kind="image",
                         prompt="no project", media_url="https://r2/other.png",
                         dsn=path, account_id=None)
    for i in range(15):
        projects.append_message(pid, "user" if i % 2 == 0 else "assistant",
                                f"turn {i:02d} " + ("x" * 2000 if i == 14 else ""),
                                path, account_id=None,
                                tool_calls={"brief": "b"} if i == 13 else None)
    monkeypatch.setattr(mcp_server.scout, "sources_for_refs", lambda names, dsn=None: {
        "bbb.jpg": {"source_url": "https://example.com/page", "title": "a can on ice"}})

    out = mcp_server.get_project(pid, dsn=path)
    assert {s["title"] for s in out["scenes"]} == {"first", "second"}
    refs = {r["ref"]: r for r in out["references"]}
    assert list(refs) == ["/refs/aaa.jpg", "/characters/sam/photo/face.jpg", "/refs/bbb.jpg"]
    assert refs["/refs/aaa.jpg"]["scenes"] == [first, second]
    assert refs["/refs/bbb.jpg"]["page"] == "https://example.com/page"
    assert refs["/refs/bbb.jpg"]["label"] == "a can on ice"
    assert refs["/characters/sam/photo/face.jpg"]["kind"] == "character"
    assert {r["id"] for r in out["renders"]} == {f"gen:{on_scene['id']}", f"gen:{filed['id']}"}
    assert len(out["chat"]) == mcp_server.CHAT_PREVIEW and out["chat_has_more"] is True
    assert out["chat"][-1]["truncated"] is True
    assert len(out["chat"][-1]["content"]) == mcp_server.CHAT_EXCERPT
    assert out["chat"][-2]["carried"] == ["brief"]

    page = mcp_server.project_history(pid, limit=10, dsn=path)
    assert [t["content"][:7] for t in page["turns"]] == [f"turn {i:02d}" for i in range(5, 15)]
    assert page["has_more"] is True and len(page["turns"][-1]["content"]) > 2000
    older = mcp_server.project_history(pid, before=page["next_before"], limit=10, dsn=path)
    assert [t["content"][:7] for t in older["turns"]] == [f"turn {i:02d}" for i in range(5)]
    assert older["has_more"] is False


def test_another_accounts_project_cannot_be_read_or_filed_into(pg):
    from conftest import seed_two

    from src import accounts, projects
    preprod.init(pg)
    scout.init(pg)
    projects.init(pg)
    seed_two("mike@example.com", dsn=pg)
    with db.connect(pg) as conn:
        other = conn.execute("SELECT id FROM accounts WHERE slug='antihero'").fetchone()["id"]
    mine = accounts.resolve_account(dsn=pg)
    theirs = projects.create("Theirs", "", pg, account_id=other)
    projects.append_message(theirs["id"], "user", "a secret", pg, account_id=other)
    assert mcp_server.list_project_cards(dsn=pg, account_id=mine)["projects"] == []
    for call in (lambda: mcp_server.get_project(theirs["id"], dsn=pg, account_id=mine),
                 lambda: mcp_server.project_history(theirs["id"], dsn=pg, account_id=mine),
                 lambda: mcp_server.run_image("a can", model="seedream4.5",
                                              project_id=theirs["id"], dsn=pg,
                                              account_id=mine)):
        with pytest.raises(ValueError, match="no project"):
            call()


def test_a_projects_references_can_be_used_again(monkeypatch):
    _stub_sources(monkeypatch, project_refs=["https://r2/old.jpg"])
    assert mcp_server.resolve_references(["https://r2/old.jpg", "sam/s1.jpg"], limit=4,
                                         who="X") == ["https://r2/old.jpg", "https://r2/s1.jpg"]
    with pytest.raises(ValueError, match="not a reference id"):
        mcp_server.resolve_references(["https://r2/never-used.jpg"], limit=4, who="X")


def test_renders_and_effects_are_filed_under_the_project_named(tmp_db, monkeypatch, signed):
    path = _project_db(tmp_db, monkeypatch)
    project = mcp_server.make_project("Ad", dsn=path)
    pid = project["id"]
    stills, clips, fx = _stub_still(monkeypatch), _stub_render(monkeypatch), _stub_effect(monkeypatch)
    quote, _ = _approved(mcp_server.run_image, prompt="a can", model="seedream4.5",
                         project_id=pid, dsn=path)
    assert quote["quote"]["project"] == {"id": pid, "title": "Ad"}
    assert stills[0]["project_id"] == pid
    with pytest.raises(ValueError, match="stale_content"):     # the yes was for that project
        mcp_server.run_image("a can", model="seedream4.5", dsn=path,
                             quote_token=quote["quote"]["quote_token"])
    _approved(mcp_server.run_video, prompt="a can", model="ltx2.3", seconds=6,
              project_id=pid, dsn=path)
    assert clips[0]["project_id"] == pid
    monkeypatch.setattr(mcp_server, "resolve_references", lambda refs, **kw: list(refs))
    _approved(mcp_server.run_effect, effect="remove-background", sources=["gen:1"],
              project_id=pid, dsn=path)
    assert fx[0]["project_id"] == pid
    with pytest.raises(ValueError, match="no project 999999"):
        mcp_server.run_image("a can", model="seedream4.5", project_id=999999, dsn=path)
    assert len(stills) == 1


def test_the_project_tools_are_on_every_surface(tmp_db, monkeypatch):
    """Studio, board and -- since 2026-10-08, Mike's call -- the listed
    server: a person's projects are their own rows."""
    monkeypatch.setenv(mcp_server.ENGINE_ENV, "1")
    tools = {"projects", "project", "project_chat", "create_project", "save_chat"}
    for kwargs in ({"surface": "studio"}, {}, {"listed": True}):
        names = {t.name for t in _tools(mcp_server.build_server(dsn=tmp_db, **kwargs))}
        assert tools <= names, kwargs
    assert tools <= set(mcp_server.LISTED_TOOLS)


def test_save_chat_files_the_conversation_and_reopening_shows_it(tmp_db, monkeypatch):
    path = _project_db(tmp_db, monkeypatch)
    pid = mcp_server.make_project("Ghost can", dsn=path)["id"]
    turns = [{"role": "user", "content": "make it colder"},
             {"role": "assistant", "content": "Here is a colder still."}]
    out = mcp_server.save_project_chat(pid, turns, dsn=path)
    assert out["saved"] == 2 and out["title"] == "Ghost can" and "saved" in out["note"]
    again = mcp_server.save_project_chat(pid, turns, dsn=path)
    assert again["saved"] == 0 and "nothing new" in again["note"]
    chat = mcp_server.get_project(pid, dsn=path)["chat"]
    assert [(t["role"], t["content"], t["via"]) for t in chat] == [
        ("user", "make it colder", "mcp"), ("assistant", "Here is a colder still.", "mcp")]
    assert "carried" not in chat[0]
    page = mcp_server.project_history(pid, dsn=path)
    assert [t["via"] for t in page["turns"]] == ["mcp", "mcp"]
    with pytest.raises(ValueError, match="no turns"):
        mcp_server.save_project_chat(pid, [], dsn=path)
    with pytest.raises(ValueError, match="no project"):
        mcp_server.save_project_chat(999999, turns, dsn=path)


def test_save_chat_through_the_tool_on_the_studio_and_listed_servers(tmp_db, monkeypatch):
    import asyncio

    from mcp.server.mcpserver.exceptions import ToolError
    path = _project_db(tmp_db, monkeypatch)
    pid = mcp_server.make_project("Tool", dsn=path)["id"]
    server = mcp_server.build_server(dsn=path, surface="studio")
    out = _result(asyncio.run(server.call_tool("save_chat", {
        "project_id": pid, "turns": [{"role": "user", "content": "hello"}]})))
    assert out["saved"] == 1
    with pytest.raises(ToolError):
        asyncio.run(server.call_tool("save_chat", {
            "project_id": pid, "turns": [{"role": "system", "content": "x"}]}))
    listed = mcp_server.build_server(dsn=path, listed=True)
    out = _result(asyncio.run(listed.call_tool("save_chat", {
        "project_id": pid, "turns": [{"role": "assistant", "content": "hi back"}]})))
    assert out["saved"] == 1
    assert [t["content"] for t in mcp_server.project_history(pid, dsn=path)["turns"]] == [
        "hello", "hi back"]


def test_another_accounts_project_takes_no_chat(pg):
    from conftest import seed_two

    from src import accounts, projects
    preprod.init(pg)
    scout.init(pg)
    projects.init(pg)
    seed_two("mike@example.com", dsn=pg)
    with db.connect(pg) as conn:
        other = conn.execute("SELECT id FROM accounts WHERE slug='antihero'").fetchone()["id"]
    mine = accounts.resolve_account(dsn=pg)
    theirs = projects.create("Theirs", "", pg, account_id=other)
    with pytest.raises(ValueError, match="no project"):
        mcp_server.save_project_chat(theirs["id"], [{"role": "user", "content": "x"}],
                                     dsn=pg, account_id=mine)
    assert projects.messages(theirs["id"], pg, account_id=other)["items"] == []


def test_a_long_chat_page_stops_before_it_is_too_big_to_carry(tmp_db, monkeypatch):
    from src import projects
    path = _project_db(tmp_db, monkeypatch)
    pid = mcp_server.make_project("Long", dsn=path)["id"]
    monkeypatch.setattr(mcp_server, "CHAT_PAGE_CHARS", 250)
    for i in range(6):
        projects.append_message(pid, "user", f"{i}" + "x" * 99, path, account_id=None)
    page = mcp_server.project_history(pid, limit=6, dsn=path)
    assert [t["content"][0] for t in page["turns"]] == ["4", "5"]
    assert page["has_more"] is True
    rest = mcp_server.project_history(pid, before=page["next_before"], limit=6, dsn=path)
    assert [t["content"][0] for t in rest["turns"]] == ["2", "3"] and rest["has_more"]


@pytest.mark.parametrize("kwargs", [{}, {"listed": True}, {"surface": "studio"}])
def test_every_surface_builds_under_python_3_11s_rules(tmp_db, monkeypatch, kwargs):
    """The Fly image runs Python 3.11, where pydantic refuses a
    `typing.TypedDict` in a tool's arguments -- and a server that fails to
    build leaves /mcp unmounted in production (2026-10-08, after #165) while
    CI on 3.12 stays green. So every surface is built here with pydantic
    answering as it does on 3.11, every optional tool registered."""
    import pydantic._internal._generate_schema as schema
    monkeypatch.setattr(schema, "_SUPPORTS_TYPEDDICT", False)
    monkeypatch.setenv(mcp_server.ENGINE_ENV, "1")
    server = mcp_server.build_server(
        dsn=tmp_db, job_status=lambda i, account_id=None: None,
        approve_render=lambda *a: {}, approve_keyframes=lambda *a: {}, **kwargs)
    names = {t.name for t in _tools(server)}
    assert "save_chat" in names and "job" in names


# ---------- element sheets from chat (2026-10-08) ----------
# Mike: "create an element sheet tool". The studio's own drawer
# (element_sheet.draw, what the Elements card's button runs), quoted first
# and drawn only after the yes, saved on the element where the studio keeps it.

def _sheet_world(monkeypatch, tmp_path, photos=("IMG_1.jpg",), has_key=True):
    from src import asset_shelf, element_sheet, media
    folder = tmp_path / "characters" / "maya"
    folder.mkdir(parents=True)
    for p in photos:
        (folder / p).write_bytes(b"\xff\xd8 jpeg")
    urls = [f"/characters/maya/photo/{p}" for p in photos]
    monkeypatch.setattr(asset_shelf, "catalogue", lambda dsn=None, account_id=None: [
        {"category": "character", "name": "Maya", "photos": urls, "text": "curly hair, mustard sweater"},
        {"category": "prop", "name": "Lamp", "photos": [], "text": ""}])
    monkeypatch.setattr(asset_shelf, "PHOTO_DIRS", {**asset_shelf.PHOTO_DIRS,
                                                    "character": tmp_path / "characters"})
    monkeypatch.setattr(asset_shelf, "resolve_photo",
                        lambda url, *a, **k: tmp_path / url.replace("/photo/", "/").lstrip("/"))
    monkeypatch.setattr(element_sheet, "available", lambda account_id=None: has_key)
    monkeypatch.setattr(element_sheet, "price_usd", lambda: 0.134)
    mirrored, drawn = [], []
    monkeypatch.setattr(media, "mirror", lambda *a, **k: mirrored.append(a))

    def fake_draw(kind, name, files, out_dir, **kw):
        drawn.append({"kind": kind, "name": name, "files": list(files), "out_dir": out_dir, **kw})
        out = out_dir / "sheet.jpg"
        out.write_bytes(b"sheet")
        return {"ok": True, "path": out, "generation_id": 41, "error": None}

    monkeypatch.setattr(element_sheet, "draw", fake_draw)
    return drawn, mirrored


def test_a_sheet_is_quoted_before_anything_is_drawn(monkeypatch, tmp_path, signed):
    from src import ledger
    drawn, _ = _sheet_world(monkeypatch, tmp_path)
    _wallet(monkeypatch)
    q = mcp_server.run_element_sheet("character", "maya", account_id=1)
    assert q["needs_approval"] and q["ok"] is False and drawn == []
    assert q["quote"]["usd"] == 0.134 and q["quote"]["replaces_sheet"] is False
    assert q["quote"]["credits"] == ledger.charge_credits(0.134) == 33
    assert q["quote"]["element"] == {"kind": "character", "name": "Maya"}
    with pytest.raises(ValueError, match="wrong_render"):       # not a token for this tool
        mcp_server.run_image("a can", model="seedream4.5", account_id=1,
                             quote_token=q["quote"]["quote_token"])
    assert drawn == []


def test_an_approved_sheet_is_drawn_from_the_real_photos_and_saved(monkeypatch, tmp_path, signed):
    drawn, mirrored = _sheet_world(monkeypatch, tmp_path, photos=("IMG_1.jpg", "sheet.jpg"))
    _wallet(monkeypatch)
    q, out = _approved(mcp_server.run_element_sheet, kind="character", name="Maya",
                       account_id=1)
    assert out["ok"] is True and out["quote"]["replaces_sheet"] is True
    # the still adapter holds it, at the signed price
    assert drawn[0]["quote"].provider == "nano" and drawn[0]["quote"].credits == 33
    assert [f.name for f in drawn[0]["files"]] == ["IMG_1.jpg"]    # never grounds on the old sheet
    assert drawn[0]["out_dir"] == tmp_path / "characters" / "maya"
    assert drawn[0]["notes"] == "curly hair, mustard sweater"
    assert mirrored and mirrored[0][1] == "characters/maya/sheet.jpg"
    assert out["sheet"].endswith("sheet.jpg") and out["generation_id"] == 41


@pytest.mark.parametrize("kind, name, match", [
    ("creature", "Maya", "kind must be one of"),
    ("character", "Nobody", "no character named"),
    ("prop", "Lamp", "no photos"),
])
def test_sheet_refusals_happen_before_any_spend(monkeypatch, tmp_path, kind, name, match):
    drawn, _ = _sheet_world(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match=match):
        mcp_server.run_element_sheet(kind, name, quote_token="zpfq.a.b", account_id=1)
    assert drawn == []


def test_no_image_key_is_a_refusal_not_a_retry(monkeypatch, tmp_path):
    drawn, _ = _sheet_world(monkeypatch, tmp_path, has_key=False)
    with pytest.raises(mcp_server.Refused):
        mcp_server.run_element_sheet("character", "Maya", account_id=1)
    assert drawn == []


def test_a_failed_draw_comes_back_as_ok_false(monkeypatch, tmp_path, signed):
    from src import element_sheet
    _sheet_world(monkeypatch, tmp_path)
    _wallet(monkeypatch)
    monkeypatch.setattr(element_sheet, "draw", lambda *a, **k: {
        "ok": False, "path": None, "generation_id": None, "error": "the sheet did not render"})
    _, out = _approved(mcp_server.run_element_sheet, kind="character", name="Maya",
                       account_id=1)
    assert out["ok"] is False and "did not render" in out["error"]


def test_element_sheet_is_on_the_studio_surface_only_behind_the_approval(tmp_db, monkeypatch):
    monkeypatch.delenv(mcp_server.ENGINE_ENV, raising=False)
    studio = {t.name for t in _tools(mcp_server.build_server(dsn=tmp_db, surface="studio"))}
    assert "element_sheet" in studio
    board = {t.name for t in _tools(mcp_server.build_server(dsn=tmp_db))}
    assert "element_sheet" not in board          # board: only under the engine flag
