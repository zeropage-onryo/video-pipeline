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
def tmp_db(tmp_path):
    path = tmp_path / "test.db"
    db.init_db(path)
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
        brand="zeropage", spark="a bench with one glove", path=tmp_db,
    
        account_id=None,)
    preprod.set_picked(ids[1], path=tmp_db, account_id=None)
    preprod.set_archived(ids[2], path=tmp_db, account_id=None)
    preprod.update_concept_shots(
        ids[3],
        {"shots": [{"n": 1, "type": "BROLL", "source": "AI", "tool": "RUNWAY",
                    "prompt": "a glove on a bench, macro, one continuous take",
                    "location": "hallway"}]},
        path=tmp_db,
    
        account_id=None,)
    preprod.set_shot_parked(ids[3], 1, reason="keyframe rendered", path=tmp_db, account_id=None)
    return tmp_db, ids


# ---------- the board ----------

def test_open_excludes_picked_and_archived(board):
    path, ids = board
    open_ids = [c["id"] for c in mcp_server.list_ideas(path=path)["ideas"]]
    assert ids[0] in open_ids
    assert ids[1] not in open_ids
    assert ids[2] not in open_ids


def test_parked_is_still_open(board):
    """A parked scene is waiting on a person, so it belongs in the list
    of what is waiting on a person. It is a sub-state of open, not a
    fifth column beside it."""
    path, ids = board
    assert ids[3] in [c["id"] for c in mcp_server.list_ideas(path=path)["ideas"]]
    assert ids[3] in [c["id"] for c in
                      mcp_server.list_ideas(status="parked", path=path)["ideas"]]


def test_status_counts_reconcile_with_the_open_list(board):
    """`board` counts are exclusive so they sum to the row count, while
    `list_ideas(status="open")` is not. The stats payload spells the
    second number out rather than leaving it to be derived wrongly."""
    path, _ = board
    stats = mcp_server.pipeline_stats(path=path)
    assert sum(stats["board"].values()) == 4
    assert stats["waiting_on_you"] == len(
        mcp_server.list_ideas(status="open", limit=100, path=path)["ideas"]
    )


def test_card_carries_a_one_line_summary(board):
    path, _ = board
    card = mcp_server.list_ideas(status="parked", path=path)["ideas"][0]
    assert card["summary"]
    assert "\n" not in card["summary"]
    assert len(card["summary"]) <= preprod.SUMMARY_CHARS + 1  # + the ellipsis


def test_get_idea_returns_the_prompt_a_card_omits(board):
    path, ids = board
    card = mcp_server.list_ideas(status="parked", path=path)["ideas"][0]
    full = mcp_server.get_idea(ids[3], path=path)
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
    ], path=path)
    autonomy.to_hold("zeropage", "keyframe rendered — approve in the Queue",
                     concept_id=ids[3], payload={"run_id": "run-1"},
                     path=path, account_id=None)
    full = mcp_server.get_idea(ids[3], path=path)
    assert full["origin"] == "graph"
    assert full["gate"]["score"] == 7 and full["gate"]["passed"] is True
    assert full["gate"]["outcome"].startswith("keyframe rendered")
    assert [x["score"] for x in full["gate"]["scores"]] == [5, 7]   # the rework moved it
    assert full["judge_overall"] is None                            # the taste judge, untouched


def test_a_studio_row_says_it_was_never_scored(board):
    path, ids = board
    full = mcp_server.get_idea(ids[3], path=path)     # has a shot, no hold row
    assert full["origin"] == "studio" and full["gate"] is None
    assert "not scored badly" in full["note"]


def test_a_captured_idea_has_nothing_to_score(tmp_db):
    card = mcp_server.capture_idea("zeropage", "Just a title", path=tmp_db)
    assert mcp_server.get_idea(card["id"], path=tmp_db)["origin"] == "capture"


def test_a_held_run_reports_its_reason_with_the_run(tmp_db, monkeypatch):
    """A phone that asked for a run must not need a second call to
    learn why it held."""
    from src import autonomy, orchestrator
    monkeypatch.setattr(db, "DB_PATH", tmp_db)
    autonomy.init(tmp_db)
    (cid,) = preprod.save_concept_ideas([_idea("Held One")], brand="zeropage",
                                        path=tmp_db, account_id=None)

    def fake_run(goal, **kw):
        autonomy.log_prompt_scores("run-2", [{"prompt": "p", "score": 4, "pass": False,
                                              "reason": "vague", "dims": {}}], path=tmp_db)
        autonomy.to_hold("zeropage", "prompt gate: vague (4/10)", concept_id=cid,
                         payload={"run_id": "run-2"}, path=tmp_db, account_id=None)
        return {"concept_id": cid, "held_reason": "prompt gate: vague (4/10)"}
    monkeypatch.setattr(orchestrator, "run", fake_run)
    out = mcp_server.run_graph("a direction", "zeropage")
    assert out["idea"]["gate"]["score"] == 4 and out["idea"]["gate"]["passed"] is False
    assert out["idea"]["gate"]["outcome"] == out["held_reason"]


def test_search_reaches_into_the_scene_prompt(board):
    """The words worth searching for live in the prompt, not the title
    -- the title is three words the model chose."""
    path, ids = board
    hits = mcp_server.search_ideas("continuous take", path=path)
    assert [c["id"] for c in hits["ideas"]] == [ids[3]]


def test_pick_and_archive_round_trip(board):
    path, ids = board
    assert mcp_server.pick_idea(ids[0], path=path)["status"] == "picked"
    assert mcp_server.archive_idea(ids[0], path=path)["status"] == "archived"
    assert mcp_server.archive_idea(ids[0], archived=False,
                                   path=path)["status"] == "picked"


def test_shoot_is_the_label_shoot_rate_reads(board):
    """`shot` means MADE by any means -- studio, Higgsfield, a camera --
    not "a render came back". It is the only way the system can see
    work that never passed through the Queue, and it must never spend."""
    path, ids = board
    before = mcp_server.pipeline_stats(path=path)["shoot_rate"]
    assert before["shot"] == 0

    mcp_server.pick_idea(ids[0], path=path)
    card = mcp_server.shoot_idea(ids[0], path=path)
    assert card["status"] == "shot"          # shot outranks picked on the card

    after = mcp_server.pipeline_stats(path=path)["shoot_rate"]
    assert after["shot"] == before["shot"] + 1
    assert after["generated"] == before["generated"]
    assert mcp_server.get_idea(ids[0], path=path)["status"] == "shot"

    # Reversible: un-shooting falls back to the pick that was still there.
    assert mcp_server.shoot_idea(ids[0], shot=False, path=path)["status"] == "picked"
    assert mcp_server.pipeline_stats(path=path)["shoot_rate"]["shot"] == before["shot"]


def test_shoot_tool_is_a_write_that_never_spends(tmp_db):
    """Registered beside pick, annotated as a write, and reachable with
    no engine flag -- recording that something got made costs nothing."""
    server = mcp_server.build_server(path=tmp_db)
    by_name = {t.name: t for t in _tools(server)}
    assert "shoot" in by_name
    assert by_name["shoot"].annotations.read_only_hint is False
    assert by_name["shoot"].annotations.destructive_hint is False
    assert set(by_name["shoot"].input_schema["properties"]) == {"idea_id", "shot"}


def test_archiving_never_deletes(board):
    """pick_rate is generated-vs-picked, so a deleted row would make the
    rate read 100% forever and unfalsifiable."""
    path, ids = board
    before = mcp_server.pipeline_stats(path=path)["pick_rate"]["generated"]
    mcp_server.archive_idea(ids[0], path=path)
    assert mcp_server.pipeline_stats(path=path)["pick_rate"]["generated"] == before


def test_captured_idea_has_no_shots_so_it_cannot_move_pick_rate(tmp_db):
    """Capturing on a phone must not touch the number that measures
    generation quality: pick_rate counts one-shot concepts only, and a
    captured idea has none."""
    before = mcp_server.pipeline_stats(path=tmp_db)["pick_rate"]["generated"]
    card = mcp_server.capture_idea("zeropage", "From The Bus", path=tmp_db)
    assert card["is_scene"] is False
    after = mcp_server.pipeline_stats(path=tmp_db)["pick_rate"]["generated"]
    assert after == before


# ---------- sparks ----------

def test_human_spark_outranks_a_crawled_one(tmp_db):
    """A person who types a direction means it. If a crawled finding
    could outscore it, the night would prefer its own research to an
    explicit instruction."""
    scout.record("zeropage", {"spark": "crawled idea", "score": 0.95},
                 lanes="web", path=tmp_db)
    mcp_server.bank_spark("zeropage", "the one I actually want", path=tmp_db)
    assert mcp_server.next_spark("zeropage", path=tmp_db)["spark"] == \
        "the one I actually want"


def test_repeat_spark_is_reported_not_refused(tmp_db):
    """_spark_key stops the CRAWL rediscovering itself. A person
    retyping a direction usually means it, so the collision is
    information, not a rejection."""
    first = mcp_server.bank_spark("zeropage", "a bench with one glove",
                                  path=tmp_db)
    second = mcp_server.bank_spark("zeropage", "A bench with one glove.",
                                   path=tmp_db)
    assert second["duplicate_of"] == [first["id"]]
    assert second["id"] != first["id"]


def test_no_servable_spark_is_a_note_not_an_error(tmp_db):
    """Falling back to the sparks.txt rotation is the healthy degraded
    path -- it is what the pipeline did before the scout existed."""
    scout.record("zeropage", {"spark": "too weak", "score": 0.1}, path=tmp_db)
    result = mcp_server.next_spark("zeropage", path=tmp_db)
    assert result["spark"] is None
    assert "sparks.txt" in result["note"]


def test_spark_images_carry_their_source(tmp_db):
    """These are other people's frames held as mood reference. An
    unattributed tile in front of somebody about to spend a render is
    the wrong affordance."""
    finding_id = scout.record("zeropage", {"spark": "x", "score": 0.9},
                              pass_id="p1", path=tmp_db)
    with db.connect(tmp_db) as conn:
        conn.execute(
            "INSERT INTO scout_bin (created_at, pass_id, brand, url, "
            "source_url, title, lane) VALUES (?,?,?,?,?,?,?)",
            ("2026-08-31", "p1", "zeropage", "/refs/abc.jpg",
             "https://youtube.com/watch?v=1", "A Title", "shorts"),
        )
    images = mcp_server.spark_images(finding_id, path=tmp_db)
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
    fid = scout.record(brand, {"spark": spark, "score": 0.9}, path=tmp_db)
    for n in (1, 2):
        scout.bank_urls(fid, [f"/refs/{n}.jpg"], lane="agent", path=tmp_db)
    return fid


def test_generate_by_finding_id_hands_the_graph_its_bin(tmp_db, monkeypatch, graph_calls):
    monkeypatch.setattr(db, "DB_PATH", tmp_db)
    fid = _banked(tmp_db)
    out = mcp_server.run_graph(brand="zeropage", finding_id=fid)
    [call] = graph_calls
    assert call["spark"] == "a bench with one glove"      # the finding's own
    assert call["reference_photos"] == ["/refs/1.jpg", "/refs/2.jpg"]
    assert call["scout_finding_id"] == fid                # so planner claims it
    assert out["finding_id"] == fid and out["reference_photos"] == call["reference_photos"]


def test_generate_by_spark_text_finds_its_own_photographs(tmp_db, monkeypatch, graph_calls):
    """add_spark -> reference -> generate(spark) must work without the
    agent carrying an id between calls, and fixing the capitals must
    not lose the photos -- the composer's `claims` rule, same key."""
    monkeypatch.setattr(db, "DB_PATH", tmp_db)
    fid = _banked(tmp_db)
    mcp_server.run_graph("A Bench, With One Glove.", "zeropage")
    [call] = graph_calls
    assert call["scout_finding_id"] == fid
    assert call["reference_photos"] == ["/refs/1.jpg", "/refs/2.jpg"]


def test_brand_defaults_to_the_findings_and_a_wrong_one_is_refused(tmp_db, monkeypatch, graph_calls):
    monkeypatch.setattr(db, "DB_PATH", tmp_db)
    fid = _banked(tmp_db, brand="antihero")
    mcp_server.run_graph(finding_id=fid)
    assert graph_calls[0]["brand"] == "antihero"
    with pytest.raises(ValueError, match="banked for 'antihero'"):
        mcp_server.run_graph(brand="zeropage", finding_id=fid)


def test_a_reworded_spark_does_not_inherit_a_findings_photographs(tmp_db, monkeypatch, graph_calls):
    """The composer silently drops the bin when the idea walks away
    from the spark; this door SAYS so, because an agent acts on the
    message where a person would have seen a tile disappear."""
    monkeypatch.setattr(db, "DB_PATH", tmp_db)
    fid = _banked(tmp_db)
    with pytest.raises(ValueError, match="is not finding"):
        mcp_server.run_graph("a monster in the garage", "zeropage", finding_id=fid)
    assert graph_calls == []


def test_an_unbanked_spark_runs_on_the_asset_bank_alone(tmp_db, monkeypatch, graph_calls):
    monkeypatch.setattr(db, "DB_PATH", tmp_db)
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
    server = mcp_server.build_server(path=tmp_db)
    with pytest.raises(ToolError, match="no finding 4242"):
        asyncio.run(server.call_tool("generate", {"finding_id": 4242}))
    props = {t.name: t for t in _tools(server)}["generate"].input_schema["properties"]
    assert "finding_id" in props


def test_engine_tools_are_off_by_default(tmp_db, monkeypatch):
    monkeypatch.delenv(mcp_server.ENGINE_ENV, raising=False)
    server = mcp_server.build_server(path=tmp_db)
    names = {t.name for t in _tools(server)}
    assert "board" in names
    assert "research" not in names and "generate" not in names


def test_engine_tools_register_under_the_flag(tmp_db, monkeypatch):
    monkeypatch.setenv(mcp_server.ENGINE_ENV, "1")
    server = mcp_server.build_server(path=tmp_db)
    names = {t.name for t in _tools(server)}
    assert {"research", "generate"} <= names


def test_path_is_never_published_to_the_model(tmp_db):
    """Every tool binds its database path in the closure. Publishing it
    as an argument would let a remote caller name the file the server
    reads and writes."""
    server = mcp_server.build_server(path=tmp_db)
    for tool in _tools(server):
        assert "path" not in (tool.input_schema.get("properties") or {})


def test_read_only_tools_say_so(tmp_db):
    """The annotation is what lets a client show a confirmation before a
    write and none before a read."""
    server = mcp_server.build_server(path=tmp_db)
    by_name = {t.name: t for t in _tools(server)}
    assert by_name["board"].annotations.read_only_hint is True
    assert by_name["pick"].annotations.read_only_hint is False


def test_caller_errors_reach_the_model(tmp_db):
    """A ValueError from the tool layer must arrive as a ToolError, or
    the SDK replaces its message with a generic crash string and an
    agent cannot tell a bad id from a broken server."""
    import asyncio

    from mcp.server.mcpserver.exceptions import ToolError

    server = mcp_server.build_server(path=tmp_db)
    with pytest.raises(ToolError, match="no idea 999999"):
        asyncio.run(server.call_tool("idea", {"idea_id": 999999}))


# ---------- bad input ----------

@pytest.mark.parametrize("call", [
    lambda p: mcp_server.list_ideas(status="bogus", path=p),
    lambda p: mcp_server.list_ideas(brand="nope", path=p),
    lambda p: mcp_server.get_idea(999999, path=p),
    lambda p: mcp_server.shoot_idea(999999, path=p),
    lambda p: mcp_server.run_graph(brand="zeropage", finding_id=999999),
    lambda p: mcp_server.run_graph("", "zeropage"),
    lambda p: mcp_server.capture_idea("zeropage", "   ", path=p),
    lambda p: mcp_server.capture_idea("nope", "Title", path=p),
    lambda p: mcp_server.bank_spark("zeropage", "  ", path=p),
    lambda p: mcp_server.search_ideas("", path=p),
    lambda p: mcp_server.run_research("zeropage", lanes=["moon"], path=p),
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

    def fake_build(path=None, start_job=None, job_status=None, **kw):
        captured.update(path=path, start_job=start_job, job_status=job_status)
        return FakeServer()

    monkeypatch.setattr(mcp_server, "build_server", fake_build)
    assert mcp_server.main(["--db", str(tmp_db)]) == 0
    assert captured["transport"] == "stdio"
    assert captured["path"] == str(tmp_db)
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
