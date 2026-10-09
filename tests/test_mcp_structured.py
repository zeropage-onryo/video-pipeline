"""
Typed results on the studio MCP (2026-10-09, docs/tasks/task-mcp-studio-v2.md
step 7).

Every studio tool publishes an outputSchema and answers with
structuredContent that validates against it, plus a short human line as
its first text block (and, while MIRROR_JSON, the same payload as JSON for
a client that never reads structuredContent). The board and listed
servers are untouched. The calls below are real wherever that is cheap --
the shapes have to fit what the tools actually return, not a fixture's
idea of it.
"""

import asyncio
import json

import pytest

from app import jobs
from src import mcp_server, mcp_shapes, preprod, pricing, scout


@pytest.fixture
def studio_db(pg, monkeypatch):
    from src import entities, projects, render_assets
    preprod.init(pg)
    scout.init(pg)
    entities.init(pg)
    render_assets.init(pg)
    projects.init(pg)
    monkeypatch.setattr(render_assets, "_ingest",
                        lambda *a, **k: {"ok": True, "chunks": 1, "error": None})
    jobs.clear_all_for_tests()
    yield pg
    jobs.clear_all_for_tests()


def _server(dsn, **kw):
    return mcp_server.build_server(dsn=dsn, surface="studio", job_status=jobs.get,
                                   cancel_job=jobs.cancel, **kw)


def _call(server, tool, args=None):
    return asyncio.run(server.call_tool(tool, args or {}))


def _check(res, tool):
    """The contract, for one answer: structured content that validates,
    a first text block that is one short line, the JSON mirror equal to
    the structured content."""
    assert not res.is_error, res.content[0].text
    data = res.structured_content
    mcp_shapes.SHAPES[tool].model_validate(data)
    first = res.content[0].text
    assert "\n" not in first and len(first) <= mcp_shapes.LINE_MAX
    assert not first.lstrip().startswith("{")
    if mcp_shapes.MIRROR_JSON:
        assert json.loads(res.content[1].text) == data
    return data, first


def test_every_studio_tool_has_a_shape_and_a_line():
    assert set(mcp_shapes.SHAPES) == set(mcp_server.STUDIO_TOOLS) == set(mcp_shapes.SUMMARIES)


def test_the_studio_publishes_output_schemas_and_the_other_servers_do_not(studio_db, monkeypatch):
    monkeypatch.setenv(mcp_server.ENGINE_ENV, "1")
    studio = asyncio.run(_server(studio_db).list_tools())
    assert len(studio) == len(mcp_server.STUDIO_TOOLS)
    assert all(t.output_schema and t.output_schema.get("properties") for t in studio)
    # the arguments are the tool's own, unchanged by the wrapper
    image = next(t for t in studio if t.name == "generate_image")
    assert {"prompt", "model", "aspect", "references", "quote_token",
            "project_id"} == set(image.input_schema["properties"])
    for kw in ({}, {"listed": True}):
        other = asyncio.run(mcp_server.build_server(
            dsn=studio_db, job_status=jobs.get, cancel_job=jobs.cancel, **kw).list_tools())
        assert not [t.name for t in other if t.output_schema]


def test_projects_round_trip_typed(studio_db):
    server = _server(studio_db)
    made, line = _check(_call(server, "create_project", {"title": "Ad", "brief": "a can"}),
                        "create_project")
    assert line == f"Created project {made['id']} \"Ad\"."
    saved, _ = _check(_call(server, "save_chat", {"project_id": made["id"], "turns": [
        {"role": "user", "content": "hello"}]}), "save_chat")
    assert saved["saved"] == 1
    listing, line = _check(_call(server, "projects"), "projects")
    assert listing["projects"][0]["id"] == made["id"] and line == "1 project."
    full, line = _check(_call(server, "project", {"project_id": made["id"]}), "project")
    assert full["chat"][0]["content"] == "hello" and "1 chat turn shown" in line
    chat, _ = _check(_call(server, "project_chat", {"project_id": made["id"]}), "project_chat")
    assert chat["count"] == 1


def test_the_catalogues_are_typed(studio_db):
    server = _server(studio_db)
    for tool, args in (("image_models", {}), ("video_models", {}), ("effects", {}),
                       ("renders", {}), ("elements", {}),
                       ("prompt_craft", {"step": "enhance", "prompt": "a can on tile"})):
        _check(_call(server, tool, args), tool)


def test_image_search_is_typed(studio_db, monkeypatch):
    monkeypatch.setattr(mcp_server, "find_images", lambda *a, **k: {
        "query": "wet tile", "sources": ["openverse"], "count": 1, "note": "",
        "images": [{"id": "c1", "shows": "tile", "source": "openverse", "credit": "cc0"}]})
    data, line = _check(_call(_server(studio_db), "images_for", {"query": "wet tile"}),
                        "images_for")
    assert data["images"][0]["id"] == "c1" and line == "1 candidate image for \"wet tile\"."


def test_a_quote_is_typed_with_its_price_and_token(studio_db, monkeypatch):
    monkeypatch.setenv(pricing.SIGNING_ENV, "test-quote-secret")
    data, line = _check(_call(_server(studio_db), "generate_image",
                              {"prompt": "a can", "model": "seedream4.5"}), "generate_image")
    assert data["state"] == "quote" and data["quote"]["quote_token"].startswith("zpfq.")
    assert data["quote"]["credits"] == 10 and line.startswith("Quote: 10 credits")


def test_a_finished_render_job_lifts_what_a_viewer_needs(studio_db):
    job = jobs.create("mcp", "image seedream4.5", cancellable=True)
    jobs.update(job["id"], status="done", progress=1.0, credits=10, charged=True,
                result={"ok": True, "media_url": "https://r2/m/1/renders/x.jpg",
                        "asset_id": 82, "generation_id": 7})
    server = _server(studio_db)
    data, line = _check(_call(server, "job", {"job_id": job["id"]}), "job")
    assert data["media_url"].endswith("x.jpg") and data["asset_id"] == 82
    assert data["ref"] == "gen:82" and data["media_kind"] == "image"
    assert line == f"Job {job['id']} done: gen:82 (10 credits)."
    cancel, line = _check(_call(server, "cancel_job", {"job_id": job["id"]}), "cancel_job")
    assert cancel["cancelled"] is False and "nothing to cancel" in line


def test_a_failed_render_inside_a_done_job_says_so():
    data = mcp_shapes.enrich("job", {"id": 3, "status": "done",
                                     "result": {"ok": False, "error": "fal refused it"}})
    assert mcp_shapes.line("job", data) == \
        "Job 3 done, but the work did not complete: fal refused it."


@pytest.mark.parametrize("payload, state, words", [
    ({"needs_approval": True, "can_approve": True,
      "quote": {"credits": 33, "charged": True, "balance": 100, "balance_after": 67}},
     "quote", "Quote: 33 credits (balance 100 -> 67)"),
    ({"needs_approval": True, "can_approve": False, "quote": {"credits": 33}},
     "quote", "cannot be approved here"),
    ({"ok": False, "refused": "insufficient_credits", "needs": 33, "available": 5},
     "refused", "needs 33 credits, the balance is 5"),
    ({"job_id": 41, "status": "running", "label": "image x"}, "started", "Started job 41"),
    ({"job_id": 41, "already_used": True}, "already_used", "Nothing new was started"),
    ({"ok": True, "asset_id": 9, "media_url": "https://r2/a.png"}, "done", "Done: gen:9"),
    ({"ok": False, "error": "no key"}, "failed", "Failed: no key"),
])
def test_every_spend_state_reads_as_one_line(payload, state, words):
    data = mcp_shapes.enrich("generate_image", payload)
    mcp_shapes.SpendResult.model_validate(data)
    assert data["state"] == state and words in mcp_shapes.line("generate_image", data)


def test_an_answer_that_does_not_fit_its_shape_fails_loudly(studio_db):
    """The SDK validates every answer against the published schema, so a
    tool whose payload drifted from its shape is an error, never a quietly
    wrong answer."""
    from mcp.server.mcpserver.exceptions import UnexpectedToolError
    job = jobs.create("mcp", "x")
    jobs.update(job["id"], status="exploded")
    with pytest.raises(UnexpectedToolError):       # the SDK's crash, not a quiet answer
        _call(_server(studio_db), "job", {"job_id": job["id"]})


def test_without_the_mirror_the_text_is_only_the_line(studio_db, monkeypatch):
    monkeypatch.setattr(mcp_shapes, "MIRROR_JSON", False)
    res = _call(_server(studio_db), "image_models")
    assert len(res.content) == 1 and res.structured_content["models"]


def test_a_datetime_on_a_row_becomes_a_string():
    from datetime import datetime, timezone
    when = datetime(2026, 10, 9, tzinfo=timezone.utc)
    assert mcp_shapes.jsonable({"at": when}) == {"at": str(when)}
