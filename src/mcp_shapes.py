"""
What the studio MCP's tools hand back, typed ONCE (2026-10-09,
docs/tasks/task-mcp-studio-v2.md step 7).

Every tool on the studio surface (`mcp_server.STUDIO_TOOLS`) publishes an
`outputSchema` from the model named here and answers with
`structuredContent` that validates against it: ids, credits, the balance,
`media_url`, `asset_id`, the job's state. The same models are what the
inline viewer (steps 3 + 4) will read, which is why they live in one
place rather than beside each tool.

THE TEXT IS A SHORT HUMAN LINE -- AND, FOR NOW, THE JSON TOO. What a
client hands its model is the client's choice, and the evidence is not
first-party: Claude Code reportedly reads `structuredContent` and drops
the text, claude.ai forwards both, and nothing published says what Claude
Desktop does (checked 2026-10-09). A client that read only the text would
lose the `quote_token` and every id, and the approval flow with them. So
the first text block is the human line and the second is the same payload
as JSON -- the MCP spec's own advice for clients that predate structured
output. `MIRROR_JSON` is the one switch: turn it off once a live check on
the client in use shows the model reads `structuredContent`.

The models are OPEN (`extra="allow"`): they type the fields a caller and a
viewer rely on, and let the rest of a tool's payload through untouched, so
adding a field to a tool never makes its answer fail validation. The board
and listed surfaces are not wrapped; they return what they always did.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Literal, Optional

from pydantic import BaseModel, ConfigDict

# See the module docstring: the JSON copy of the payload in the text
# content, for a client that never reads structuredContent.
MIRROR_JSON = True

LINE_MAX = 300


class _Open(BaseModel):
    model_config = ConfigDict(extra="allow")


# --- money and work ----------------------------------------------------------

class Quote(_Open):
    """What a spending tool will run and what it costs. The tool's own
    detail (model, aspect, effect, options, element...) rides alongside."""
    usd: Optional[float] = None
    credits: Optional[int] = None
    charged: Optional[bool] = None
    balance: Optional[int] = None
    balance_after: Optional[int] = None
    quote_token: Optional[str] = None
    expires_at: Optional[str] = None


SpendState = Literal["quote", "refused", "started", "already_used", "done", "failed"]


class SpendResult(_Open):
    """generate_image / generate_video / apply_effect / element_sheet.
    `state` says which of the two calls this was and how it went: a
    `quote` (nothing spent), `refused` (a short balance: `needs`,
    `available`), `started` (a job: poll `job`), `already_used` (this
    approval started `job_id` before), or -- with no job registry --
    `done` / `failed` inline."""
    state: SpendState
    ok: Optional[bool] = None
    needs_approval: bool = False
    can_approve: Optional[bool] = None
    refused: Optional[str] = None
    needs: Optional[int] = None
    available: Optional[int] = None
    quote: Optional[Quote] = None
    job_id: Optional[int] = None
    status: Optional[str] = None
    label: Optional[str] = None
    already_used: bool = False
    media_url: Optional[str] = None
    asset_id: Optional[int] = None
    ref: Optional[str] = None
    generation_id: Optional[int] = None
    sheet: Optional[str] = None
    error: Optional[str] = None
    note: Optional[str] = None


JobStatus = Literal["queued", "running", "done", "failed", "cancelled"]


class Job(_Open):
    """One background job. A finished render's `media_url`, `asset_id`,
    `ref` (the `gen:<id>` that names it from then on) and `media_kind`
    are lifted off its result, so a viewer never has to dig."""
    id: int
    status: JobStatus
    kind: Optional[str] = None
    label: Optional[str] = None
    progress: Optional[float] = None
    detail: Optional[str] = None
    error: Optional[str] = None
    cancellable: bool = False
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    credits: Optional[int] = None
    credits_held: Optional[int] = None
    charged: Optional[bool] = None
    result: Optional[Any] = None
    media_url: Optional[str] = None
    media_kind: Optional[Literal["image", "video"]] = None
    asset_id: Optional[int] = None
    ref: Optional[str] = None


class JoinPlan(_Open):
    clips: list[str]
    seconds: float
    canvas: dict[str, Any] = {}
    transition: str = "cut"
    crossfade_s: Optional[float] = None
    music: Optional[str] = None
    letterboxed: list[str] = []
    notes: list[str] = []
    credits: int = 0


class JoinResult(_Open):
    """assemble_clips: `started` (a job: poll `job`; its result carries the
    joined clip's `media_url`, `asset_id` and `ref`), or -- with no job
    registry -- `done` / `failed` inline. Never a quote: it spends nothing."""
    state: Literal["started", "done", "failed"]
    plan: JoinPlan
    ok: Optional[bool] = None
    job_id: Optional[int] = None
    status: Optional[str] = None
    label: Optional[str] = None
    media_url: Optional[str] = None
    asset_id: Optional[int] = None
    ref: Optional[str] = None
    seconds: Optional[float] = None
    cut_project: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    note: Optional[str] = None


class ImportResult(_Open):
    """import_file: the `asset:<id>` a file from this computer became."""
    id: str                       # asset:<id>
    kind: Literal["image", "video"]
    filename: str
    ok: bool = True
    seconds: Optional[float] = None
    width: Optional[int] = None
    height: Optional[int] = None
    size_bytes: Optional[int] = None
    note: Optional[str] = None


class CancelResult(_Open):
    job_id: int
    status: JobStatus
    cancelled: bool
    cancel_requested: bool = False
    label: Optional[str] = None
    note: str = ""


# --- what the studio holds ----------------------------------------------------

class RenderItem(_Open):
    id: str                       # gen:<id> -- a reference or effect source
    kind: Optional[str] = None
    model: Optional[str] = None
    provider: Optional[str] = None
    prompt: str = ""
    media_url: Optional[str] = None
    created_at: Optional[str] = None


class RenderList(_Open):
    count: int
    renders: list[RenderItem]
    note: Optional[str] = None


class ElementPhoto(_Open):
    ref: str
    label: Optional[str] = None


class Element(_Open):
    kind: str
    name: str
    description: str = ""
    photos: list[ElementPhoto] = []


class ElementList(_Open):
    count: int
    elements: list[Element]
    note: Optional[str] = None


class ImageCandidate(_Open):
    id: str                       # candidate:<id> names it
    shows: str = ""
    source: Optional[str] = None
    credit: str = ""


class ImageSearch(_Open):
    query: str
    count: int
    images: list[ImageCandidate]
    sources: list[Any] = []
    note: Optional[str] = None


class ProjectCard(_Open):
    id: int
    title: str
    brief: str = ""
    has_look: bool = False
    scenes: int = 0
    picked: int = 0
    rendered: int = 0
    archived: bool = False
    updated_at: Optional[str] = None
    cover: Optional[str] = None


class ProjectList(_Open):
    count: int
    projects: list[ProjectCard]
    note: Optional[str] = None


class Turn(_Open):
    id: int
    role: str
    at: Optional[str] = None
    content: str = ""


class ProjectReference(_Open):
    ref: str
    kind: str = ""
    label: Optional[str] = None
    url: Optional[str] = None
    page: Optional[str] = None
    scenes: list[int] = []


class ProjectScene(_Open):
    id: int
    title: str = ""
    status: Optional[str] = None
    prompt: str = ""
    still: Optional[str] = None
    clip: Optional[str] = None


class ProjectRender(RenderItem):
    scene: Optional[int] = None


class Project(_Open):
    id: int
    title: str
    brief: str = ""
    look: str = ""
    archived: bool = False
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    learned: list[Any] = []
    scenes: list[ProjectScene] = []
    scenes_truncated: bool = False
    references: list[ProjectReference] = []
    references_truncated: bool = False
    renders: list[ProjectRender] = []
    chat: list[Turn] = []
    chat_has_more: bool = False
    next: Optional[str] = None


class ProjectChat(_Open):
    project_id: int
    title: str
    count: int
    turns: list[Turn]
    has_more: bool = False
    next_before: Optional[int] = None
    note: Optional[str] = None


class ProjectMade(_Open):
    id: int
    title: str
    brief: str = ""
    look: str = ""
    next: Optional[str] = None


class ChatSaved(_Open):
    project_id: int
    title: str
    saved: int = 0
    note: Optional[str] = None


# --- the catalogues -------------------------------------------------------------

class ImageModels(_Open):
    default: str
    available: bool
    aspects: list[str] = []
    models: list[dict[str, Any]]


class VideoModels(_Open):
    default: str
    available: bool
    models: list[dict[str, Any]]


class EffectList(_Open):
    available: bool
    categories: list[str] = []
    effects: list[dict[str, Any]]


class PromptCraft(_Open):
    step: str
    instruction: str
    how: str = ""
    input: Optional[str] = None
    tool: Optional[str] = None


SPEND_TOOLS = ("generate_image", "generate_video", "apply_effect", "element_sheet")

SHAPES: dict[str, type[BaseModel]] = {
    "projects": ProjectList,
    "project": Project,
    "project_chat": ProjectChat,
    "create_project": ProjectMade,
    "save_chat": ChatSaved,
    "elements": ElementList,
    "images_for": ImageSearch,
    "image_models": ImageModels,
    "video_models": VideoModels,
    "effects": EffectList,
    "renders": RenderList,
    "prompt_craft": PromptCraft,
    **{name: SpendResult for name in SPEND_TOOLS},
    "job": Job,
    "cancel_job": CancelResult,
    "assemble_clips": JoinResult,
    "import_file": ImportResult,
}


# --- shaping a payload --------------------------------------------------------------

def _kind_of(url: Optional[str]) -> Optional[str]:
    tail = (url or "").split("?", 1)[0].lower()
    if tail.endswith((".mp4", ".mov", ".webm", ".m4v")):
        return "video"
    if tail.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")):
        return "image"
    return None


def spend_state(payload: dict) -> str:
    if payload.get("needs_approval"):
        return "quote"
    if payload.get("refused"):
        return "refused"
    if payload.get("already_used"):
        return "already_used"
    if payload.get("job_id") is not None:
        return "started"
    return "done" if payload.get("ok") else "failed"


def enrich(tool: str, payload: dict) -> dict:
    """The tool's payload plus what is derived for a reader: a spend's
    `state` (and its result's `ref`), a job's media lifted off its
    result. Additive only -- nothing the tool said is changed."""
    out = dict(payload)
    if tool in SPEND_TOOLS:
        out["state"] = spend_state(out)
        if out.get("asset_id") is not None and not out.get("ref"):
            out["ref"] = f"gen:{out['asset_id']}"
    elif tool == "assemble_clips":
        out["state"] = ("started" if out.get("job_id") is not None
                        else "done" if out.get("ok") else "failed")
    elif tool == "job":
        result = out.get("result")
        if isinstance(result, dict):
            for key in ("media_url", "asset_id", "media_kind"):
                if result.get(key) is not None and out.get(key) is None:
                    out[key] = result[key]
        if out.get("media_kind") not in ("image", "video"):
            out["media_kind"] = _kind_of(out.get("media_url"))
        if out.get("asset_id") is not None and not out.get("ref"):
            out["ref"] = f"gen:{out['asset_id']}"
    return out


def _n(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def _spend_line(p: dict) -> str:
    q = p.get("quote") or {}
    state = p["state"]
    if state == "quote":
        if not p.get("can_approve"):
            return f"Quote: {q.get('credits')} credits; it cannot be approved here (no signing secret)."
        if q.get("charged") is False:
            return (f"Quote: {q.get('credits')} credits, not charged to this account. "
                    "Waiting for a yes; approve with quote_token.")
        balance = (f" (balance {q['balance']} -> {q['balance_after']})"
                   if q.get("balance") is not None else "")
        return f"Quote: {q.get('credits')} credits{balance}. Waiting for a yes; approve with quote_token."
    if state == "refused":
        return (f"Refused: needs {p.get('needs')} credits, the balance is "
                f"{p.get('available')}. Top up first; do not retry.")
    if state == "already_used":
        return (f"Already approved: job {p.get('job_id')}. Nothing new was started or charged."
                if p.get("job_id") is not None else
                "Already approved; nothing new was started or charged.")
    if state == "started":
        return f"Started job {p.get('job_id')} ({p.get('label')}). Poll `job`."
    if state == "done":
        made = p.get("ref") or p.get("sheet") or p.get("media_url") or "the result"
        return f"Done: {made}."
    return f"Failed: {p.get('error') or 'no result'}."


def _job_line(p: dict) -> str:
    head = f"Job {p.get('id')} {p.get('status')}"
    status = p.get("status")
    if status in ("queued", "running"):
        pct = p.get("progress")
        return head + (f" ({round(pct * 100)}%)" if pct else "") + (
            f": {p['detail']}" if p.get("detail") else "") + "."
    if status == "cancelled":
        return head + (f": {p['detail']}" if p.get("detail") else ".")
    if status == "failed":
        return head + f": {p.get('error') or 'no reason given'}."
    result = p.get("result") if isinstance(p.get("result"), dict) else {}
    if result and result.get("ok") is False:
        return head + f", but the work did not complete: {result.get('error') or 'no result'}."
    made = p.get("ref") or p.get("media_url")
    return head + (f": {made}" if made else "") + (
        f" ({p['credits']} credits)" if p.get("credits") else "") + "."


def _join_line(p: dict) -> str:
    plan = p.get("plan") or {}
    n = len(plan.get("clips") or [])
    if p["state"] == "started":
        return (f"Joining {n} clips into one video (about {plan.get('seconds')}s) as job "
                f"{p.get('job_id')} -- no credits are spent. Poll `job`.")
    if p["state"] == "done":
        return f"Joined {n} clips: {p.get('ref') or p.get('media_url')} -- no credits were spent."
    return f"The join failed: {p.get('error') or 'no result'}. Nothing was spent."


SUMMARIES: dict[str, Callable[[dict], str]] = {
    "projects": lambda p: _n(p.get("count", 0), "project") + ".",
    "project": lambda p: (f"Project {p.get('id')} \"{p.get('title')}\": "
                          f"{_n(len(p.get('scenes') or []), 'scene')}, "
                          f"{_n(len(p.get('references') or []), 'reference')}, "
                          f"{_n(len(p.get('renders') or []), 'render')}, "
                          f"{_n(len(p.get('chat') or []), 'chat turn')} shown."),
    "project_chat": lambda p: (f"{_n(p.get('count', 0), 'turn')} from project "
                               f"{p.get('project_id')}"
                               + ("; older turns exist." if p.get("has_more") else ".")),
    "create_project": lambda p: f"Created project {p.get('id')} \"{p.get('title')}\".",
    "save_chat": lambda p: (f"Saved {_n(p.get('saved', 0), 'turn')} to project "
                            f"{p.get('project_id')}."),
    "elements": lambda p: _n(p.get("count", 0), "element") + ".",
    "images_for": lambda p: (f"{_n(p.get('count', 0), 'candidate image')} for "
                             f"\"{p.get('query')}\"."),
    "image_models": lambda p: (f"{_n(len(p.get('models') or []), 'image model')} "
                               f"(default {p.get('default')})."),
    "video_models": lambda p: (f"{_n(len(p.get('models') or []), 'video model')} "
                               f"(default {p.get('default')})."),
    "effects": lambda p: _n(len(p.get("effects") or []), "effect") + ".",
    "renders": lambda p: _n(p.get("count", 0), "render") + ", newest first.",
    "prompt_craft": lambda p: (f"The studio's {p.get('step')} guide, filled in -- apply "
                               "it yourself."),
    **{name: _spend_line for name in SPEND_TOOLS},
    "job": _job_line,
    "cancel_job": lambda p: p.get("note") or f"Job {p.get('job_id')}: {p.get('status')}.",
    "assemble_clips": lambda p: _join_line(p),
    "import_file": lambda p: (f"Imported {p.get('filename')} as {p.get('id')} ({p.get('kind')}"
                              + (f", {p['width']}x{p['height']}" if p.get("width") else "")
                              + (f", {p['seconds']:.1f}s" if p.get("seconds") else "") + ")."),
}


def line(tool: str, payload: dict) -> str:
    """The short human line for a payload already enriched: one line, at
    most LINE_MAX characters."""
    text = " ".join(str(SUMMARIES[tool](payload)).split())
    return text if len(text) <= LINE_MAX else text[:LINE_MAX - 3].rstrip() + "..."


def jsonable(payload: dict) -> dict:
    """Plain JSON types only -- a datetime off a row becomes its string."""
    return json.loads(json.dumps(payload, default=str))


def result(tool: str, payload: dict):
    """The CallToolResult a studio tool answers with: the human line (and
    the JSON mirror while MIRROR_JSON) as text, the payload as
    structuredContent. The SDK validates it against SHAPES[tool] before it
    leaves, so a shape that drifted from its tool fails loudly here."""
    from mcp.types import CallToolResult, TextContent
    data = jsonable(enrich(tool, payload))
    content = [TextContent(type="text", text=line(tool, data))]
    if MIRROR_JSON:
        content.append(TextContent(type="text", text=json.dumps(data, indent=2)))
    return CallToolResult(content=content, structured_content=data)


__all__ = ["MIRROR_JSON", "SHAPES", "SUMMARIES", "SPEND_TOOLS", "enrich", "line",
           "jsonable", "result", "spend_state"]
