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
    "add_spark": "Bank this spark for a later run",
    "reference": "Bank this reference image behind the spark",
}

# The assistant's own tools (src/assistant_brain.py, 2026-09-26): not on
# the MCP server, run in this process. find_references is a READ (it
# hunts and looks, banks nothing, spends no credits); keep_references
# is a WRITE and waits for the click like every other write here.
# Published only when a turn asks for them (`session(local=True)`), so
# the board's closed set above is unchanged for every other caller.
LOCAL_READ = ("find_references", "search_footage")
LOCAL_WRITE = ("keep_references",)
LOCAL_TOOLS = LOCAL_READ + LOCAL_WRITE
WRITE_LABELS["keep_references"] = "Keep these references and attach them to the composer"
MAX_KEEP_IDS = 12

# THE BRAIN MAKES (2026-10-04, Mike's call: "it is all in one place where
# you can toggle between image and video that are connected to the
# reasoning/brain"). The composer has no Guide toggle any more: every
# send is a Guide turn, and the model decides whether the person is
# talking an idea through or asking for the thing -- a still, or a
# written scene. These two are WRITE tools in the proposal sense (the
# turn ends on the call, nothing runs here) with one difference from
# add_spark: the STUDIO runs them, not /creative-guide/act. The reply's
# proposal names the tool and the prompt the model wrote, and the
# composer posts it to the same doors a send used to post to directly
# (/api/generate/run for an image, /api/scenes/run for a scene), so the
# spend gates, the charge and the job registry are exactly what they
# were. `run` refuses them: a server that made a still off a POST body
# would be the Director's Generate node without its price. Published
# only when a turn asks (`session(maker=True)`), so the pill is unchanged.
MAKE_TOOLS = ("make_image", "make_video", "make_element_sheet")
WRITE_LABELS["make_image"] = "Generate this image"
WRITE_LABELS["make_video"] = "Write this scene"
# THE ELEMENT SHEET FROM THE COMPOSER (2026-10-09, Mike: "can you create an
# element sheet of myself" with five photos attached made a loose 4:5
# still). A make tool like the other two -- proposed here, run by the
# studio on the step card's Approve -- but what it runs is the Elements
# create route (POST /api/assets/characters with the composer's
# references as photo_urls, sheet on), so the person is saved as a
# character AND the sheet is element_sheet.draw: the landing page's
# five-panel prompt, 16:9, on the real photos. Nothing here spends.
SHEET_TOOL = "make_element_sheet"
WRITE_LABELS[SHEET_TOOL] = "Save as a character and draw the reference sheet"
MAX_SHEET_NAME = 80
MAX_SHEET_NOTES = 300
MAX_MAKE_PROMPT = 4000
MAKE_SECONDS = (4, 30)          # timeline.scene_seconds' clamp
MAKE_SHOTS = (1, 8)
MAKE_SPECS = (
    {
        "name": "make_image",
        "description": (
            "Generate ONE still from a prompt, on the image model the person picked "
            "in the composer. Call it ONLY when the person asked for an image in this "
            "turn in so many words (make / generate / draw / show me / render it / "
            "do it) or confirmed an offer you made -- never when they are bouncing "
            "ideas, asking a question, or giving notes. The prompt is what the image "
            "model is handed, in plain visual language: subject, setting, light, lens, "
            "mood. Keep every reference the person attached in mind; they ride along."),
        "input_schema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "The image, described plainly."},
                "aspect": {"type": "string",
                           "description": "Optional: 1:1, 4:5, 3:4, 9:16, 16:9, 21:9 -- "
                                          "only when they asked for a shape."},
            },
            "required": ["prompt"],
        },
        "write": True,
    },
    {
        "name": "make_video",
        "description": (
            "Write ONE video scene from an idea: the studio's scene writer turns it "
            "into timed shots with its references, filed under the open project when there is "
            "one "
            "(nothing is rendered; the Queue spends). Call it ONLY when the person "
            "asked for the scene in this turn in so many words or confirmed an offer "
            "you made -- never while they are still deciding. The prompt is the idea "
            "as agreed: subject, turn, setting, look, pacing, sound, constraints."),
        "input_schema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "The scene idea, as agreed."},
                "seconds": {"type": "integer",
                            "description": "Optional total length, 4-30, only when asked."},
                "shots": {"type": "integer",
                          "description": "Optional shot count, only when they named one."},
            },
            "required": ["prompt"],
        },
        "write": True,
    },
    {
        "name": SHEET_TOOL,
        "description": (
            "Save the PERSON in the attached photos as a character element and draw "
            "its reference sheet: one wide image, five panels -- full-body front, "
            "three-quarter, side profile, back, and a head-and-shoulders close-up -- "
            "the same face and clothes in every panel. Call it when the person asks "
            "for an element sheet, character sheet, reference sheet or turnaround of "
            "themselves or of someone in the photos they attached -- never make_image "
            "for that. It needs attached photos of the person; with none attached, ask "
            "for them instead of calling. The name is what the person called them "
            "(their own first name when it is them and you know it, else ask). Notes "
            "only when they said what the character should wear."),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string",
                         "description": "The character's name, as the person gave it."},
                "notes": {"type": "string",
                          "description": "Optional: what they wear in the sheet, only "
                                         "when the person said. Empty keeps the clothes "
                                         "in the photos."},
            },
            "required": ["name"],
        },
        "write": True,
    },
)

# PROJECTS ARE MADE THROUGH THE GUIDE (2026-10-07, Mike's call: "projects
# are only created through the Guide -- either the user tells the Guide
# to make one, or a Guide conversation is saved as a project. There is no
# 'New project' form or button on the board."). Two WRITE tools in the
# proposal sense -- the turn ends on the call, the pill or the composer
# draws the confirm card, and the click posts /creative-guide/act, which
# runs `run_project_tool` with the thread the client holds:
#   create_project    -- a named project (title, optional brief). The
#                        conversation stays an ordinary chat.
#   save_as_project   -- the conversation so far BECOMES a project: its
#                        turns are copied into the project's history and
#                        the scenes it made are filed under it.
# Published on every local turn (the pill, the composer's brain). A turn
# that already runs inside a project is told so (creative_guide.project_note)
# and asked not to propose either. Nothing here spends.
PROJECT_TOOLS = ("create_project", "save_as_project")
WRITE_LABELS["create_project"] = "Create this project"
WRITE_LABELS["save_as_project"] = "Save this conversation as a project"
MAX_PROJECT_TITLE = 120
MAX_PROJECT_BRIEF = 8000
MAX_SAVED_TURNS = 200
MAX_SAVED_SCENES = 40
PROJECT_SPECS = (
    {
        "name": "create_project",
        "description": (
            "Create a studio PROJECT -- the container a piece of work's scenes live "
            "in, with its own brief and memory. Call it ONLY when the person asked "
            "for a project in so many words ('make a project for the Nike spot', "
            "'start a new project called X') and never when they are just talking "
            "about an idea. Never call it inside a conversation that is already in "
            "a project. The title is theirs or a short name for the work; the brief "
            "is only what they said about who it is for, the look, and the rules."),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "The project's name."},
                "brief": {"type": "string",
                          "description": "Optional: FOR / LOOK / ALWAYS / NEVER lines "
                                         "from what the person said. Leave empty "
                                         "rather than invent one."},
            },
            "required": ["title"],
        },
        "write": True,
    },
    {
        "name": "save_as_project",
        "description": (
            "Turn THIS conversation into a project: it is saved with every turn so "
            "far and the scenes made in it, under the title given. Call it ONLY "
            "when the person asked to save or keep this conversation as a project "
            "('make this a project', 'save this as a project called X'). Never "
            "inside a conversation already in a project."),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string",
                          "description": "The project's name -- theirs, or a short "
                                         "name for what the conversation is about."},
                "brief": {"type": "string",
                          "description": "Optional: the brief as agreed so far, in "
                                         "FOR / LOOK / ALWAYS / NEVER lines."},
            },
            "required": ["title"],
        },
        "write": True,
    },
)

MAX_TOOL_CALLS = 6      # read calls per turn; a Guide answer, not a crawl

_URL = re.compile(r"(?i)\b(?:https?|ftp)://|\bwww\.|\.(?:jpe?g|png|webp|gif)(?:\?|$)")


class Refused(ValueError):
    """A call this bridge will not make -- the message is for the person."""


# Board tools the model is not offered when the local hunt is: they
# overlap find_references and their results never reach the screen.
HIDDEN_WITH_LOCAL = frozenset({"images_for"})


def is_write(name: str) -> bool:
    return (name in WRITE_TOOLS or name in LOCAL_WRITE or name in MAKE_TOOLS
            or name in PROJECT_TOOLS)


def is_local(name: str) -> bool:
    return name in LOCAL_TOOLS


def is_project(name: str) -> bool:
    """A project tool: proposed by the model, run by /creative-guide/act
    with the conversation the client holds (run_project_tool)."""
    return name in PROJECT_TOOLS


def is_make(name: str) -> bool:
    """A make tool: proposed by the model, run by the STUDIO (the
    composer's own send), never by this module."""
    return name in MAKE_TOOLS


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
    if (name not in TOOLS and name not in LOCAL_TOOLS and name not in MAKE_TOOLS
            and name not in PROJECT_TOOLS):
        raise Refused(f"`{name}` is not reachable from the Guide")
    args = dict(args or {})
    for key, value in args.items():
        values = value if isinstance(value, list) else [value]
        if any(isinstance(v, str) and _URL.search(v) for v in values):
            raise Refused(f"`{name}` does not take a URL ({key}); "
                          "pass a candidate id from images_for instead")
    if name == "keep_references":
        ids = args.get("candidate_ids")
        if not isinstance(ids, list) or not ids or not all(isinstance(i, str) and i.strip()
                                                           for i in ids):
            raise Refused("`keep_references` needs candidate_ids from find_references")
        args = {"candidate_ids": [i.strip() for i in ids][:MAX_KEEP_IDS]}
    if name == "find_references":
        if not str(args.get("scene") or "").strip():
            raise Refused("`find_references` needs the scene to hunt for")
        args = {"scene": str(args["scene"])[:2000],
                "departments": [str(d)[:20] for d in (args.get("departments") or [])
                                if isinstance(d, str)][:7],
                "avoid": [str(a)[:120] for a in (args.get("avoid") or [])
                          if isinstance(a, str)][:8]}
    if name == "search_footage":
        if not str(args.get("query") or "").strip():
            raise Refused("`search_footage` needs something to look for")
        k = args.get("k")
        args = {"query": str(args["query"])[:300],
                "k": k if isinstance(k, int) and not isinstance(k, bool) else 8}
    if name == SHEET_TOOL:
        who = " ".join(str(args.get("name") or "").split())
        if not who:
            raise Refused(f"`{name}` needs the character's name")
        args = {"name": who[:MAX_SHEET_NAME],
                "notes": " ".join(str(args.get("notes") or "").split())[:MAX_SHEET_NOTES]}
    elif name in MAKE_TOOLS:
        prompt = " ".join(str(args.get("prompt") or "").split())
        if not prompt:
            raise Refused(f"`{name}` needs the prompt to make it from")
        clean: dict = {"prompt": prompt[:MAX_MAKE_PROMPT]}
        if name == "make_image":
            aspect = str(args.get("aspect") or "").strip()
            if re.fullmatch(r"\d{1,2}:\d{1,2}", aspect):
                clean["aspect"] = aspect
        else:
            for key, (lo, hi) in (("seconds", MAKE_SECONDS), ("shots", MAKE_SHOTS)):
                value = args.get(key)
                if isinstance(value, bool) or not isinstance(value, int):
                    continue
                clean[key] = max(lo, min(hi, value))
        args = clean
    if name in PROJECT_TOOLS:
        title = " ".join(str(args.get("title") or "").split())
        if not title:
            raise Refused(f"`{name}` needs a title for the project")
        args = {"title": title[:MAX_PROJECT_TITLE],
                "brief": str(args.get("brief") or "").strip()[:MAX_PROJECT_BRIEF]}
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
        account_id: Optional[int] = None, brand: str = "",
        attachments: Optional[dict] = None, on_step=None) -> str:
    """Run ONE tool, synchronously, on a fresh in-process client.

    The confirm card's click lands here (write tools), and it is also
    the simplest way for a test to exercise the bridge end to end.
    The assistant's own tools run here too, with no MCP client at all.
    """
    # Checked BEFORE the client opens: a refusal raised inside the
    # session's task group comes back wrapped in an ExceptionGroup,
    # which no caller can catch as the Refused it is.
    args = check_args(name, args)
    if is_make(name):
        # the studio's send runs these against the generation routes,
        # where the price, the charge and the job are; a server that made
        # a still off this body would be a second spend door with no card
        raise Refused(f"`{name}` is made by the studio's own send, not here")
    if is_project(name):
        # needs the conversation the client holds: run_project_tool
        raise Refused(f"`{name}` takes the conversation; the act route runs it")
    if is_local(name):
        from . import assistant_brain
        return assistant_brain.run_local(name, args, brand=brand, account_id=account_id,
                                         dsn=dsn, attachments=attachments, on_step=on_step)

    from mcp import Client

    async def go():
        async with Client(build(dsn=dsn, account_id=account_id)) as client:
            return await call(client, name, args)
    return _sync(go())


def run_project_tool(name: str, args: dict, *, account_id: int, conversation=None,
                     scenes=None, dsn: Optional[str] = None) -> dict:
    """The confirm card's click on create_project / save_as_project.

    `conversation` is the thread as the client holds it -- [{role,
    content, tool_calls?}] -- and `scenes` the concept ids its sends
    made; both are user content filed under `account_id` and nothing
    else is read off them. A concept that is not this account's is
    simply not filed (projects.tag_concepts' own predicate). Returns
    {project, summary}; raises Refused for a bad call."""
    from . import projects

    if not is_project(name):
        raise Refused(f"`{name}` is not a project tool")
    args = check_args(name, args)
    try:
        project = projects.create(args["title"], args.get("brief") or "", dsn,
                                  account_id=account_id)
    except ValueError as exc:
        raise Refused(str(exc)) from exc
    copied = filed = 0
    if name == "save_as_project":
        turns = [t for t in (conversation if isinstance(conversation, list) else [])
                 if isinstance(t, dict)][-MAX_SAVED_TURNS:]
        copied = projects.copy_messages(project["id"], turns, dsn, account_id=account_id)
        ids = [int(i) for i in (scenes if isinstance(scenes, list) else [])
               if isinstance(i, int) and not isinstance(i, bool) and i > 0][:MAX_SAVED_SCENES]
        if ids:
            filed = projects.tag_concepts(ids, project["id"], dsn, account_id=account_id)
    summary = f"project “{project['title']}” created"
    if name == "save_as_project":
        summary += (f" with {copied} turn{'s' if copied != 1 else ''}"
                    + (f" and {filed} scene{'s' if filed != 1 else ''}" if filed else ""))
    return {"project": project, "summary": summary}


def session(dsn: Optional[str] = None, account_id: Optional[int] = None,
            *, local: bool = False, brand: str = "", maker: bool = False,
            makes: Optional[tuple] = None, on_step=None):
    """Everything a Guide turn needs, gathered once: the tool specs for
    the model, and a synchronous `run_tool(name, args)` for the READ
    calls the model makes mid-turn.

    Opens a client per call rather than holding one across the turn:
    the model call in between takes tens of seconds, the turn runs on a
    job thread with no event loop, and an in-process client is cheap to
    open. Returns (specs, run_tool).

    `local=True` (the assistant pill) also publishes find_references /
    keep_references, and works without the `mcp` package -- then the
    assistant can still hunt references even where the board is not
    reachable. `run_tool.attachments` collects what a read tool left
    for the reply (the contact sheet).

    `maker=True` (the composer's send, 2026-10-04) also publishes
    make_image / make_video -- proposals the studio runs, see MAKE_TOOLS.

    `makes` narrows the make tools a maker turn is handed (the assistant
    pill gets ("make_image",) -- 2026-10-08); None is every one.

    `on_step(done, of, detail)` hears a local tool's progress
    (find_references' hunt), for the job the turn runs in.
    """
    tool_specs: list = []
    if available():
        from mcp import Client

        async def list_specs():
            async with Client(build(dsn=dsn, account_id=account_id)) as client:
                return await specs(client)

        tool_specs = _sync(list_specs())
    elif not local:
        raise Refused("the board's tools are not installed here")
    if local:
        from . import assistant_brain
        # `images_for` hands the model ids and captions and nothing the
        # person can see: a chat turn that used it "found references" and
        # drew no images (2026-10-01, the composer's Guide). Where the
        # contact-sheet hunt is published it is the only image search.
        tool_specs = [s for s in tool_specs if s.get("name") not in HIDDEN_WITH_LOCAL]
        tool_specs = tool_specs + [dict(s) for s in assistant_brain.LOCAL_SPECS]
        # projects are made through the Guide (2026-10-07): offered on the
        # same turns the assistant's own tools are, i.e. the pill and the
        # composer's brain -- never to a caller that asked for the board alone
        tool_specs = tool_specs + [dict(s) for s in PROJECT_SPECS]
    if maker:
        tool_specs = tool_specs + [dict(s) for s in MAKE_SPECS
                                   if makes is None or s["name"] in makes]

    attachments: dict = {}

    def run_tool(name: str, args: dict) -> str:
        if is_write(name):
            raise Refused(f"`{name}` writes; it needs a click, not a model")
        if is_local(name) and not local:
            raise Refused(f"`{name}` is not reachable from the Guide")
        return run(name, args, dsn=dsn, account_id=account_id, brand=brand,
                   attachments=attachments, on_step=on_step)

    run_tool.attachments = attachments
    return tool_specs, run_tool
