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

from src import imagery

# The reference->bytes layer and the enhance call moved to
# src/imagery.py (2026-08-29) so the Studio's scene chain could reach
# them from src/, which must never import app/. Exactly ONE alias is
# kept: execute_graph calls enhance() bare, and patching
# workflow_runner.enhance is the established node seam in the tests.
# Everything else is called through `imagery.` on purpose -- an alias
# that can be monkeypatched without affecting the code that runs is
# how a test passes while a real billed call escapes.
enhance = imagery.enhance

# The v1 catalogue. Text-source nodes carry their value in properties;
# the other three call a backend function. Resist growing this list
# until real workflows ask for it.
PURE_TEXT_TYPES = ("zpf/system_prompt", "zpf/user_prompt")
REFERENCE_TYPE = "zpf/reference_image"
# A SET of reference frames -- one asset's photos (a character's three
# frames, a room's two plates) or the composer's uploads -- as one node
# on the Gen Space canvas (2026-09-10). Pure: its value is the list of
# urls it carries. Before it, a scene's references rode invisibly as
# `ref_urls` on every billed node, so the canvas showed a face being
# named in the prompt and nothing that looked like a face.
REFERENCE_SET_TYPE = "zpf/reference_set"
GROUND_TYPE = "zpf/ground"
ENHANCE_TYPE = "zpf/enhance"
GENERATE_TYPE = "zpf/generate"
NANO_TYPE = "zpf/nano_banana"

NODE_TYPES = PURE_TEXT_TYPES + (REFERENCE_TYPE, REFERENCE_SET_TYPE, GROUND_TYPE,
                                ENHANCE_TYPE, GENERATE_TYPE, NANO_TYPE)

# The one port that takes MORE than one wire. Several reference sets
# (the character, the room, the uploads) all feed one billed node, and
# a port that holds a single link would force them through a chain of
# hubs nobody drew. The canvas emits `links: [...]` beside the usual
# `link` on this slot; every other port stays single-link.
MULTI_LINK_PORTS = ("refs",)


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


def _input_values(node: dict, name: str, links: dict, outputs: dict) -> list:
    """Every value wired into a MULTI_LINK port, in wire order, with
    list-valued upstreams (a reference set) flattened. A slot carrying
    only the single-link `link` key still works -- one wire is a list
    of one."""
    for slot in node.get("inputs") or []:
        if slot.get("name") != name:
            continue
        ids = list(slot.get("links") or [])
        if not ids and slot.get("link") is not None:
            ids = [slot["link"]]
        values: list = []
        for link_id in ids:
            link = links.get(link_id)
            upstream = outputs.get(link["origin_id"]) if link else None
            value = upstream["value"] if upstream else None
            if isinstance(value, (list, tuple)):
                values.extend(value)
            elif value:
                values.append(value)
        return values
    return []


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
        return imagery.render_bytes(value)
    target = resolve_photo(value) if resolve_photo else None
    return imagery.upright(target.read_bytes()) if target is not None else None


def render_generate_node(pick: dict, prompt: str, reference: Optional[str], *,
                         resolve_photo=None, db_path=None,
                         account_id: Optional[int] = None, quote=None) -> dict:
    """One Generate-node render on the renderer providers.renderer_for
    picked -- the node's own Run and Run all both come through here, so
    one graph cannot render two different ways depending on which button
    was pressed (2026-09-11: the node used to be Runway-only).

    Runway takes an inline data URI, so a local reference becomes bytes
    here (image_for_runway). Higgsfield and fal take a URL their servers
    FETCH and resolve local references themselves (as_image_url, which
    uploads to R2 or drops the anchor honestly), so they are handed the
    reference and the resolver as-is. Never raises -- the adapters'
    generate_from_prompt contract."""
    from src import providers

    module = providers.VIDEO_PROVIDERS[pick["provider"]]
    kwargs = {"approved": True,     # a person pressed Run -- see spend_approved
              "db_path": db_path, "account_id": account_id,
              "model": pick["model"]}
    if quote is not None:
        # the node's own Run verified a price; Run all never has one
        kwargs["quote"] = quote
    if pick["provider"] == "runway":
        kwargs["reference_image"] = image_for_runway(reference,
                                                     resolve_photo=resolve_photo)
    else:
        kwargs["reference_image"] = reference
        kwargs["resolve_photo"] = resolve_photo
    return module.generate_from_prompt(prompt, **kwargs)


def shot_reference_urls(properties, db_path=None, account_id: Optional[int] = None) -> list:
    """The references stored on the shot this node belongs to, read at
    RUN time rather than trusted from the drawing.

    A Director chain is built with the shot's refs frozen into every
    billed node's ref_urls, and a SAVED canvas wins over a rebuild --
    so a graph drawn before its scene had any references stayed blind
    for good, and attaching photos afterwards changed nothing on a
    re-run (2026-08-28: a shot with a face and a bike on file rendered
    a stranger). A frozen list that HAS something in it still wins; an
    empty one is no longer read as a promise that there is nothing.

    Grounding shapes, it never gates: anything unreadable is no refs.
    """
    concept_id = properties.get("concept_id")
    shot_n = properties.get("shot_n")
    if not concept_id or not shot_n:
        return []
    try:
        from src import preprod
        concept = preprod.get_concept(int(concept_id),
                                      dsn=db_path, account_id=account_id)
    except Exception:
        return []
    for shot in (concept or {}).get("shots") or []:
        if shot.get("n") == shot_n:
            return [url for url in (shot.get("refs") or [])
                    if isinstance(url, str) and url]
    return []


def node_reference_urls(node, properties, links, outputs, port="image",
                       db_path=None) -> list:
    """Every reference image this node should ground on, in priority
    order: whatever is wired into its image port, then the scene's own
    references (ref_urls), then the single image_url fallback.

    One list for all three billed nodes, because the same references
    have to inform the enhance, the keyframe AND the clip -- a scene's
    face and wardrobe are not a property of one step. Deduplicated, so
    wiring the keyframe in does not send it twice."""
    urls, seen = [], set()
    candidates = [_input_value(node, port, links, outputs)]
    # the reference sets wired in on the canvas (2026-09-10) come right
    # after the keyframe port: what is drawn as a wire IS a reference
    candidates.extend(_input_values(node, "refs", links, outputs))
    # the drawing's own list first; only when it is EMPTY is the shot
    # read back (see shot_reference_urls) -- a graph that carries
    # references is never second-guessed
    refs = list(properties.get("ref_urls") or [])
    candidates.extend(refs or shot_reference_urls(properties, db_path))
    candidates.append(properties.get("image_url"))
    for url in candidates:
        if isinstance(url, str) and url and url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def execute_graph(graph: dict, *, gemini_client=None, resolve_photo=None,
                  db_path=None, emit: Optional[Callable] = None,
                  check_cancelled: Optional[Callable] = None,
                  account_id: Optional[int] = None) -> dict:
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
            elif node_type == REFERENCE_SET_TYPE:
                kind = "images"
                value = [u for u in (properties.get("urls") or [])
                         if isinstance(u, str) and u]
            elif node_type == GROUND_TYPE:
                from src import shootgen
                spark = _input_value(node, "spark", links, outputs) \
                    or properties.get("text") or ""
                kind = "text"
                value = shootgen.reference_block(
                    spark=spark.strip() or None,
                    db_path=db_path)
            elif node_type == ENHANCE_TYPE:
                if gemini_client is None:
                    raise RuntimeError("GEMINI_API_KEY not set")
                user = _input_value(node, "user", links, outputs) or ""
                # references: the wired port, plus the scene's own
                # reference images riding invisibly via ref_urls /
                # image_url (the Director chain keeps grounding on the
                # backend). All of them inform the enhance.
                images = node_reference_urls(node, properties, links, outputs,
                                             db_path=db_path)
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
                        db_path=db_path)
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
                urls = node_reference_urls(node, properties, links,
                                           outputs, db_path=db_path)
                # (label, bytes): the caption names the asset the photo
                # belongs to, so four references are four NAMED things
                # rather than four pictures the model has to sort out
                from src import shootgen
                references = [
                    (shootgen.reference_label(url), data)
                    for url, data in (
                        (url, imagery.image_bytes_for_gemini(
                            url, resolve_photo=resolve_photo))
                        for url in urls)
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
                # Deliberately NOT extended to the spend gate, which
                # is a different wall and still the module's own. Since
                # 2026-09-09 a person running this canvas IS the
                # approval, so the call below passes approved=True --
                # what stays refused is an unattended caller, and what
                # stays enforced is each vendor's daily cap.
                #
                # WHICH vendor is this account's to answer (2026-09-11):
                # whatever it holds a key for, cheapest first -- the same
                # providers.renderer_for the node's own Run asks. Skipped
                # only when it holds none at all.
                from src import providers
                pick = providers.renderer_for(account_id,
                                              needs="generate_from_prompt")
                if pick is None:
                    states[node_id] = {
                        "status": "skipped", "kind": None, "output": None,
                        "error": "no video renderer key on this account — "
                                 "add a Runway, Higgsfield or fal key"}
                    mark_downstream_skipped(node_id, f"upstream skipped: {title}")
                    push((index + 1) / total, f"{title} skipped")
                    continue
                # A BILLABLE render needs a signed quote (pricing step 5,
                # 2026-09-18), and Run all has none to carry: the prompt
                # this node renders is the enhance node's output, which
                # did not exist when any price was shown. So it is
                # skipped -- the enhance and the keyframe upstream still
                # ran -- and the clip is approved at its price in the
                # Queue. BYOK, and a server that cannot sign, render here
                # exactly as before.
                from src import pricing
                if pricing.configured() and pricing.billable(account_id, pick["provider"]):
                    states[node_id] = {
                        "status": "skipped", "kind": None, "output": None,
                        "error": "billed in credits — Send to Queue and approve "
                                 "the clip at its quoted price"}
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
                urls = node_reference_urls(node, properties, links, outputs,
                                           db_path=db_path)
                result = render_generate_node(
                    pick, prompt, urls[0] if urls else None,
                    resolve_photo=resolve_photo, db_path=db_path,
                    account_id=account_id)
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
