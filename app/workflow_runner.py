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
a run with failures is a failed job. A connector that was never
configured (Runway with no API secret) is SKIPPED rather than failed --
an unadapted tool honestly staying dry is the designed behaviour, not a
break. The spend gate is different and still fails loudly: a configured
Runway without this run's approval must refuse where everyone can see
it.
"""
from __future__ import annotations

from typing import Callable, Optional

from src import db, runway
from src.gemini_utils import sniff_mime

# The v1 catalogue. Text-source nodes carry their value in properties;
# the other three call a backend function. Resist growing this list
# until real workflows ask for it.
PURE_TEXT_TYPES = ("zpf/system_prompt", "zpf/user_prompt")
REFERENCE_TYPE = "zpf/reference_image"
GROUND_TYPE = "zpf/ground"
ENHANCE_TYPE = "zpf/enhance"
GENERATE_TYPE = "zpf/generate"
NANO_TYPE = "zpf/nano_banana"

NODE_TYPES = PURE_TEXT_TYPES + (REFERENCE_TYPE, GROUND_TYPE,
                                ENHANCE_TYPE, GENERATE_TYPE, NANO_TYPE)


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


def render_bytes(value):
    """An upstream node's /renders/ URL -> that file's bytes, or None.
    Shared by both reference resolvers: a render is a local file no
    model provider can fetch by URL, and the path is user-influenced,
    so anything escaping data/renders/ is refused."""
    from pathlib import Path

    root = (Path(__file__).resolve().parent.parent / "data" / "renders").resolve()
    target = (root / value[len("/renders/"):]).resolve()
    if root in target.parents and target.is_file():
        return target.read_bytes()
    return None


MAX_FETCH_BYTES = 15 * 1024 * 1024      # Gemini's inline request budget is ~20MB
FETCH_TIMEOUT = 10


def _public_host(host) -> bool:
    """SSRF guard: reference URLs come out of the graph JSON, which is
    user-controlled, and this fetch runs on the server. Only addresses
    outside the private ranges are allowed, so a pasted URL can never
    make the app read its own network."""
    import ipaddress
    import socket

    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            return False
    return bool(infos)


def fetch_image_bytes(url):
    """A public image URL -> its bytes, or None. Never raises.

    This exists because R2 went live: once storage is configured every
    stored reference image and every keyframe is an https URL, and
    NEITHER model can fetch one. Gemini takes inline bytes only, so
    before this an https reference was silently dropped (Nano) or
    degraded to a line of text naming the URL (enhance) -- the reference
    looked attached on the canvas and reached no model at all."""
    from urllib.parse import urlparse

    import requests

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return None
    if not _public_host(parsed.hostname):
        return None
    try:
        with requests.get(url, stream=True, timeout=FETCH_TIMEOUT) as response:
            response.raise_for_status()
            kind = (response.headers.get("content-type") or "").split(";")[0].strip()
            if kind and not kind.startswith("image/"):
                return None
            data = b""
            for chunk in response.iter_content(64 * 1024):
                data += chunk
                if len(data) > MAX_FETCH_BYTES:
                    return None            # too big to ride inline; drop it
        return data or None
    except Exception:
        return None                        # a reference is an enhancement, never a gate




def image_bytes_for_gemini(value, resolve_photo=None):
    """Any reference input -> raw bytes Gemini can take as vision input
    (it never fetches URLs itself). A data URI decodes; an upstream
    render's /renders/ URL resolves against data/renders/; a picked
    asset photo resolves through resolve_photo; a public http(s) URL is
    fetched. Local resolution is tried first -- a file on this disk
    beats a round trip. None when nothing resolves: a reference is an
    enhancement, never a gate."""
    import base64

    if not value or not isinstance(value, str):
        return None
    if value.startswith("data:image/"):
        try:
            return base64.b64decode(value.split(",", 1)[1])
        except Exception:
            return None
    if value.startswith("/renders/"):
        return render_bytes(value)
    if value.startswith(("http://", "https://")):
        return fetch_image_bytes(value)
    target = resolve_photo(value) if resolve_photo else None
    return target.read_bytes() if target is not None else None


def image_for_runway(value, resolve_photo=None):
    """A Generate node's reference input -> something Runway can anchor
    on. A picked asset photo is a site-relative URL Runway could never
    fetch, so it becomes bytes here (runway.generate_from_prompt turns
    bytes into a data URI); public URLs and data URIs pass through.

    An upstream Nano Banana keyframe is the same problem: /renders/ is
    local until R2 is configured, so it becomes bytes too -- otherwise
    the keyframe silently stops anchoring the clip the moment it is
    wired in, which is the whole point of the chain."""
    if not value or not isinstance(value, str):
        return None
    if value.startswith(("http://", "https://", "data:image/")):
        return value
    if value.startswith("/renders/"):
        return render_bytes(value)
    target = resolve_photo(value) if resolve_photo else None
    return target.read_bytes() if target is not None else None


def enhance(system: str, user: str, images=None, *, gemini_client,
            resolve_photo=None, model: Optional[str] = None,
            references: str = "") -> str:
    """The Gemini 2.5 Flash enhance call: system + user prompt plus
    optional reference images as vision input -- the same
    generate_with_retry path director.py and shootgen.py already use.
    An empty system falls back to the prompt-enhancement instruction
    (prompts/enhance_system.txt via workflows._enhance_system_text), so
    a bare user prompt is still ENHANCED with vivid detail rather than
    echoed to an uninstructed model. `references` is the optional RAG
    grounding block (the Ground node's output) folded in as its own
    labelled section -- grounding material, not the instruction.
    Raises on an empty prompt or a dead model: here the model call IS
    the deliverable, the promptgen contract."""
    from google.genai import types

    from src import shootgen, workflows
    from src.gemini_utils import generate_with_retry

    system = (system or "").strip()
    user = (user or "").strip()
    references = (references or "").strip()
    if not (system or user or references):
        raise ValueError("nothing to enhance — connect or type a prompt first")
    if not system:
        system = workflows._enhance_system_text()
    blocks = [system]
    if references:
        blocks.append("REFERENCES — ground the prompt in these:\n" + references)
    if user:
        blocks.append(user)
    text = "\n\n".join(blocks)
    parts = []
    for image in images or []:
        # every reference the same way, local file or public URL -- the
        # model must SEE it. Naming a URL in the text (what this did
        # before) tells a model that cannot fetch URLs that one exists,
        # which is indistinguishable from no reference at all.
        data = image_bytes_for_gemini(image, resolve_photo=resolve_photo)
        if data:
            parts.append(types.Part.from_bytes(
                data=data, mime_type=sniff_mime(data)))
        elif isinstance(image, str) and image.startswith(("http://", "https://")):
            # unreachable (private host, too big, dead link): say so,
            # rather than pretending the reference landed
            text += f"\nReference image (could not be loaded): {image}"
    parts.append(text)
    return generate_with_retry(gemini_client, model or shootgen.MODEL, parts)


def node_reference_urls(node, properties, links, outputs, port="image") -> list:
    """Every reference image this node should ground on, in priority
    order: whatever is wired into its image port, then the scene's own
    references (ref_urls), then the single image_url fallback.

    One list for all three billed nodes, because the same references
    have to inform the enhance, the keyframe AND the clip -- a scene's
    face and wardrobe are not a property of one step. Deduplicated, so
    wiring the keyframe in does not send it twice."""
    urls, seen = [], set()
    candidates = [_input_value(node, port, links, outputs)]
    candidates.extend(properties.get("ref_urls") or [])
    candidates.append(properties.get("image_url"))
    for url in candidates:
        if isinstance(url, str) and url and url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


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
                user = _input_value(node, "user", links, outputs) or ""
                # references: the wired port, plus the scene's own
                # reference images riding invisibly via ref_urls /
                # image_url (the Director chain keeps grounding on the
                # backend). All of them inform the enhance.
                images = node_reference_urls(node, properties, links, outputs)
                kind = "text"
                # references passed only when present, so older graphs
                # (and tests patching enhance without the param) run
                # unchanged. auto_ground pulls the RAG block server-side
                # -- same degrade contract as everywhere: "" on failure.
                extra = {}
                refs = _input_value(node, "references", links, outputs)
                if not refs and properties.get("auto_ground"):
                    from src import shootgen
                    refs = shootgen.reference_block(
                        spark=user.strip() or None,
                        db_path=db_path if db_path is not None else db.DB_PATH)
                if refs:
                    extra["references"] = refs
                value = enhance(
                    _input_value(node, "system", links, outputs) or "",
                    user,
                    images=images or None,
                    gemini_client=gemini_client, resolve_photo=resolve_photo,
                    **extra)
            elif node_type == NANO_TYPE:
                from src import nano_banana
                prompt = _input_value(node, "prompt", links, outputs) or ""
                # every reference, not just one: the face AND the jacket
                references = [
                    data for data in (
                        image_bytes_for_gemini(url, resolve_photo=resolve_photo)
                        for url in node_reference_urls(node, properties, links, outputs))
                    if data
                ]
                result = nano_banana.generate_from_prompt(
                    prompt, reference_image=references, db_path=db_path)
                if not result["ok"]:
                    raise RuntimeError(result["error"] or "render failed")
                kind, value = "image", result["media_url"]
            elif node_type == GENERATE_TYPE:
                # A connector that was never configured is not a broken
                # graph -- an unadapted tool honestly stays dry. Skipping
                # (not failing) keeps a chain whose keyframe rendered
                # from reporting itself as a failure on every run.
                # Deliberately NOT extended to the spend gate: a
                # configured Runway with no per-run approval must still
                # refuse loudly, through the module's own wall.
                if not runway.has_key():
                    states[node_id] = {
                        "status": "skipped", "kind": None, "output": None,
                        "error": "Runway not configured — RUNWAYML_API_SECRET is unset"}
                    mark_downstream_skipped(node_id, f"upstream skipped: {title}")
                    push((index + 1) / total, f"{title} skipped")
                    continue
                prompt = _input_value(node, "prompt", links, outputs) or ""
                # Runway anchors a clip on exactly ONE frame (its API
                # takes a single prompt_image), so of the references this
                # node carries only the first is usable -- the wired
                # keyframe when there is one, else the scene's own
                # reference. The rest already informed the prompt that
                # got here, which is how they reach the clip at all.
                urls = node_reference_urls(node, properties, links, outputs)
                reference = image_for_runway(
                    urls[0] if urls else None, resolve_photo=resolve_photo)
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
