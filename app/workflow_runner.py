"""
Server-side execution for a Workflows graph -- the "Run all" behind
POST /api/workflows/{id}/run.

The input is LiteGraph's own serialize() JSON (nodes + links), walked
with Kahn's algorithm: start from nodes with no unmet inputs, run
them, then whatever they unblock. Sequential on purpose -- several
node types are billed, rate-limited API calls (Gemini, Runway), so
independent branches do NOT run concurrently in v1.

Node handlers map onto what already exists rather than reimplementing
it: Ground calls shootgen.reference_block, Enhance calls Gemini through
gemini_utils.generate_with_retry (the director.py path), Generate calls
runway.generate_from_prompt -- whose spend gate (RUNWAY_SPEND_OK) sits
inside runway.generate_video, so a workflow cannot become a second,
ungated route to spend.

A failed node fails, its dependents are skipped, and everything else
still runs -- partial results are results. The caller decides whether
a run with failures is a failed job.
"""
from __future__ import annotations

from typing import Callable, Optional

from src import db, runway
from src.locations import MIME_TYPES

# The v1 catalogue. Text-source nodes carry their value in properties;
# the other three call a backend function. Resist growing this list
# until real workflows ask for it.
PURE_TEXT_TYPES = ("zpf/system_prompt", "zpf/user_prompt")
REFERENCE_TYPE = "zpf/reference_image"
GROUND_TYPE = "zpf/ground"
ENHANCE_TYPE = "zpf/enhance"
GENERATE_TYPE = "zpf/generate"

NODE_TYPES = PURE_TEXT_TYPES + (REFERENCE_TYPE, GROUND_TYPE,
                                ENHANCE_TYPE, GENERATE_TYPE)


def _link_row(link) -> Optional[dict]:
    """serialize() emits links as arrays; be tolerant of the object form
    some LiteGraph builds produce."""
    if isinstance(link, dict):
        return link
    if isinstance(link, (list, tuple)) and len(link) >= 5:
        return {"id": link[0], "origin_id": link[1], "origin_slot": link[2],
                "target_id": link[3], "target_slot": link[4]}
    return None


def topo_order(graph: dict) -> tuple[list, list]:
    """Kahn's algorithm over the serialized graph. Returns (order,
    leftover) -- leftover is non-empty only when the graph has a cycle."""
    nodes = {n["id"]: n for n in graph.get("nodes") or []}
    indegree = {node_id: 0 for node_id in nodes}
    dependents: dict = {node_id: [] for node_id in nodes}
    for raw in graph.get("links") or []:
        link = _link_row(raw)
        if not link:
            continue
        origin, target = link.get("origin_id"), link.get("target_id")
        if origin in nodes and target in nodes:
            indegree[target] += 1
            dependents[origin].append(target)
    ready = sorted(node_id for node_id, deg in indegree.items() if deg == 0)
    order = []
    while ready:
        node_id = ready.pop(0)
        order.append(node_id)
        for target in dependents[node_id]:
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
        ready.sort()
    leftover = [node_id for node_id in nodes if node_id not in order]
    return order, leftover


def _input_value(node: dict, name: str, links: dict, outputs: dict):
    """The value on one named input port, or None when unconnected or
    the upstream node produced nothing."""
    for slot in node.get("inputs") or []:
        if slot.get("name") != name:
            continue
        link = links.get(slot.get("link"))
        if link is None:
            return None
        upstream = outputs.get(link["origin_id"])
        return upstream["value"] if upstream else None
    return None


def image_for_runway(value, resolve_photo=None):
    """A Generate node's reference input -> something Runway can anchor
    on. A picked asset photo is a site-relative URL Runway could never
    fetch, so it becomes bytes here (runway.generate_from_prompt turns
    bytes into a data URI); public URLs and data URIs pass through."""
    if not value or not isinstance(value, str):
        return None
    if value.startswith(("http://", "https://", "data:image/")):
        return value
    target = resolve_photo(value) if resolve_photo else None
    return target.read_bytes() if target is not None else None


def enhance(system: str, user: str, images=None, *, gemini_client,
            resolve_photo=None, model: Optional[str] = None) -> str:
    """The LLM Enhance call: system + user prompt (both optional, empty
    falls back to empty) plus optional reference images as vision input
    -- the same generate_with_retry path director.py and shootgen.py
    already use. Raises on an empty prompt or a dead model: here the
    model call IS the deliverable, the promptgen contract."""
    from google.genai import types

    from src import shootgen
    from src.gemini_utils import generate_with_retry

    text = "\n\n".join(t for t in [(system or "").strip(), (user or "").strip()] if t)
    if not text:
        raise ValueError("nothing to enhance — connect or type a prompt first")
    parts = []
    for image in images or []:
        target = resolve_photo(image) if resolve_photo else None
        if target is not None:
            parts.append(types.Part.from_bytes(
                data=target.read_bytes(),
                mime_type=MIME_TYPES.get(target.suffix.lower(), "image/jpeg")))
        elif isinstance(image, str) and image.startswith(("http://", "https://")):
            # not fetched server-side; named so the model still knows of it
            text += f"\nReference image: {image}"
    parts.append(text)
    return generate_with_retry(gemini_client, model or shootgen.MODEL, parts)


def execute_graph(graph: dict, *, gemini_client=None, resolve_photo=None,
                  db_path=None, emit: Optional[Callable] = None,
                  check_cancelled: Optional[Callable] = None) -> dict:
    """
    Run every node in topological order. Returns {"ok", "order",
    "nodes": {id: {"status", "kind", "output", "error"}}} -- status is
    done | failed | skipped. emit(states, fraction, detail) is called
    after every state change so the caller can push progress (the jobs
    SSE feed); check_cancelled() may raise to abort between nodes.
    """
    nodes = {n["id"]: n for n in graph.get("nodes") or []}
    links = {}
    for raw in graph.get("links") or []:
        link = _link_row(raw)
        if link:
            links[link["id"]] = link

    order, leftover = topo_order(graph)
    states: dict = {}
    outputs: dict = {}

    def push(fraction, detail=""):
        if emit:
            # JSON object keys are strings; keep ids as-is, the client
            # coerces. Copy so a caller can't see a half-mutated dict.
            emit({str(k): dict(v) for k, v in states.items()}, fraction, detail)

    for node_id in leftover:
        states[node_id] = {"status": "skipped", "kind": None, "output": None,
                           "error": "part of a cycle — a graph must flow one way"}

    dependents: dict = {node_id: set() for node_id in nodes}
    for link in links.values():
        if link["origin_id"] in nodes and link["target_id"] in nodes:
            dependents[link["origin_id"]].add(link["target_id"])

    def mark_downstream_skipped(node_id, reason):
        for target in dependents.get(node_id, ()):
            if target not in states or states[target].get("status") is None:
                states[target] = {"status": "skipped", "kind": None,
                                  "output": None, "error": reason}
                mark_downstream_skipped(target, reason)

    total = max(len(order), 1)
    for index, node_id in enumerate(order):
        if check_cancelled:
            check_cancelled()
        if states.get(node_id, {}).get("status") == "skipped":
            continue
        node = nodes[node_id]
        node_type = node.get("type")
        title = node.get("title") or node_type
        states[node_id] = {"status": "running", "kind": None,
                           "output": None, "error": None}
        push(index / total, f"{title}")
        properties = node.get("properties") or {}
        try:
            if node_type in PURE_TEXT_TYPES:
                kind, value = "text", properties.get("text") or ""
            elif node_type == REFERENCE_TYPE:
                kind, value = "image", properties.get("url") or ""
            elif node_type == GROUND_TYPE:
                from src import shootgen
                spark = _input_value(node, "spark", links, outputs) \
                    or properties.get("text") or ""
                kind = "text"
                value = shootgen.reference_block(
                    spark=spark.strip() or None,
                    db_path=db_path if db_path is not None else db.DB_PATH)
            elif node_type == ENHANCE_TYPE:
                if gemini_client is None:
                    raise RuntimeError("GEMINI_API_KEY not set")
                image = _input_value(node, "image", links, outputs)
                kind = "text"
                value = enhance(
                    _input_value(node, "system", links, outputs) or "",
                    _input_value(node, "user", links, outputs) or "",
                    images=[image] if image else None,
                    gemini_client=gemini_client, resolve_photo=resolve_photo)
            elif node_type == GENERATE_TYPE:
                prompt = _input_value(node, "prompt", links, outputs) or ""
                reference = image_for_runway(
                    _input_value(node, "image", links, outputs),
                    resolve_photo=resolve_photo)
                result = runway.generate_from_prompt(
                    prompt, reference_image=reference, db_path=db_path)
                if not result["ok"]:
                    raise RuntimeError(result["error"] or "render failed")
                kind, value = "media", result["media_url"]
            else:
                raise RuntimeError(f"unknown node type {node_type!r}")
        except Exception as e:
            # a cancel must still abort the whole run, not fail one node
            from . import jobs
            if isinstance(e, jobs.JobCancelled):
                raise
            states[node_id] = {"status": "failed", "kind": None,
                               "output": None, "error": str(e)}
            mark_downstream_skipped(node_id, f"upstream failed: {title}")
            push((index + 1) / total, f"{title} failed")
            continue

        outputs[node_id] = {"kind": kind, "value": value}
        states[node_id] = {"status": "done", "kind": kind,
                           "output": value, "error": None}
        push((index + 1) / total, f"{title} done")

    ok = all(s["status"] == "done" for s in states.values()) and not leftover
    return {"ok": ok, "order": order,
            "nodes": {str(k): v for k, v in states.items()}}
