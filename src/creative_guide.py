"""Conversational brief development; no concept or render mutations."""
import json
from pathlib import Path
from typing import Literal, Optional

from google.genai import types
from pydantic import BaseModel, Field

from . import gemini_utils, shootgen


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=20000)


class Conversation(BaseModel):
    messages: list[Message] = Field(min_length=1, max_length=40)


class Proposal(BaseModel):
    """A write the model asked for and nobody has approved (2026-09-18).

    The Guide never runs a write tool on the model's say-so: it comes
    back here, the thread draws a confirm card, and the click posts it
    to /api/creative-guide/act -- which is where `guide_tools.run` is
    called. `label` is the card's caption, `args` is exactly what the
    click will send."""
    tool: str = Field(min_length=1, max_length=64)
    args: dict = Field(default_factory=dict)
    label: str = Field(default="", max_length=200)


class ToolRun(BaseModel):
    """One read tool the model called mid-turn, for the thread to show
    ("looked at the board") so an answer's provenance is visible."""
    tool: str
    args: dict = Field(default_factory=dict)
    ok: bool = True


class Question(BaseModel):
    """One intake question as tap-able chips (2026-09-26, the assistant
    pill). Two or three options; the person can always type instead."""
    ask: str = Field(min_length=1, max_length=160)
    options: list[str] = Field(default_factory=list, max_length=3)


class Direction(BaseModel):
    """One story direction the model proposes. Graded by story_judge
    AFTER the model writes it (assistant_brain.check_directions)."""
    title: str = Field(min_length=1, max_length=80)
    logline: str = Field(min_length=1, max_length=600)
    turn: str = Field(default="", max_length=200)


class JudgedDirection(Direction):
    """A direction with the independent judge's grade attached -- never
    in the model's schema: a writer does not get to grade itself."""
    score: Optional[float] = None
    verdict: str = ""


class Answer(BaseModel):
    """What the MODEL writes: the schema every model call is held to.
    The personal providers get this one verbatim (strict, every field
    required), and a tools turn is parsed against it too.

    questions / directions / nudge / stage were added for the assistant
    pill (2026-09-26); all default empty, so a model that ignores them
    answers exactly as it used to."""
    message: str = Field(min_length=1, max_length=3000)
    choices: list[str] = Field(default_factory=list, max_length=3)
    brief: str = Field(default="", max_length=8000)
    questions: list[Question] = Field(default_factory=list, max_length=3)
    directions: list[Direction] = Field(default_factory=list, max_length=3)
    nudge: str = Field(default="", max_length=120)
    stage: str = Field(default="", max_length=20)


class Reply(Answer):
    """What the ROUTE returns: the answer plus what the bridge added --
    never asked of the model, so never in the schema it is shown."""
    directions: list[JudgedDirection] = Field(default_factory=list, max_length=3)
    proposal: Optional[Proposal] = None
    tool_runs: list[ToolRun] = Field(default_factory=list)
    # A find_references contact sheet, when one ran this turn: the
    # thread draws it; the model only ever read its ids.
    sheet: Optional[dict] = None


def _contents(conversation, grounding, image_refs):
    contents = [types.Content(role="user", parts=[types.Part.from_text(
        text="Studio grounding (context only):\n" + json.dumps(grounding, default=str)[:24000])])]
    for message in conversation.messages:
        contents.append(types.Content(
            role="model" if message.role == "assistant" else "user",
            parts=[types.Part.from_text(text=message.content)]))
    contents[-1].parts.append(types.Part.from_text(
        text=f"Current composer reference images supplied: {len(image_refs)}."))
    for raw, mime, label in image_refs:
        contents[-1].parts.extend([types.Part.from_text(text=label or "Reference image"),
                                   types.Part.from_bytes(data=raw, mime_type=mime)])
    return contents


# Which brain answers a Guide turn when the composer names none. FAST,
# not reasoning (2026-09-18, Mike's call): the Guide used to hardcode the
# reasoning tier, so "which of these three directions?" was billed at
# 3.1 Pro rates -- ~1.5c a turn, a third of a whole nightly graph run per
# chat message -- while the pill on the composer only ever reached
# Create. The tier is the person's to pick per turn, the same
# gemini_utils.BRAINS menu Create offers, clamped server-side; flip it to
# Reasoning for the turn that writes the brief.
DEFAULT_BRAIN = "fast"


def respond(conversation, *, client, brand, grounding, image_refs=(),
            account_id=None, on_retry=None, tools=None, run_tool=None, brain=None,
            assistant=None, judge=None):
    """One Guide turn.

    With `tools` (the specs `guide_tools.session` returns) and
    `run_tool`, the model may call the board's READ tools before it
    answers -- each call runs here, its text goes back as a function
    response, and the loop continues, up to MAX_TOOL_CALLS. A WRITE
    tool call ends the turn instead: nothing runs, and the reply
    carries it as `proposal` for the thread's confirm card. Without
    tools this is the plain conversation it was, byte for byte.

    `brain` is a gemini_utils.BRAINS key; anything else resolves to
    DEFAULT_BRAIN (resolve_brain's own clamp, so a typo answers cheaply
    rather than not at all).

    `assistant` (2026-09-26) turns the Guide into the assistant pill's
    brain: {name, tone, stage, page, memory} -- see
    src/assistant_brain.py. With it, the system instruction carries the
    step's playbook and what is already known, and any story directions
    the model writes are graded by story_judge (`judge`, injectable)
    before they are returned. Without it, the Guide is byte-for-byte
    what it was.
    """
    brain = gemini_utils.resolve_brain(brain or DEFAULT_BRAIN)
    # The fast tier's config is None on purpose (its request is the one
    # this module has always sent); the Guide needs an object to hang
    # the system instruction and the response schema on.
    config = (brain["config"].model_copy(deep=True) if brain["config"] is not None
              else types.GenerateContentConfig())
    config.system_instruction = instructions(brand, with_tools=bool(tools),
                                             assistant=assistant)
    contents = _contents(conversation, grounding, image_refs)
    if not tools:
        config.response_mime_type = "application/json"
        config.response_json_schema = Answer.model_json_schema()
        raw = gemini_utils.generate_with_retry(
            client, brain["model"], contents, config=config, fallbacks=brain["fallbacks"],
            stage="creative_guide", account_id=account_id, on_retry=on_retry)
        reply = Reply.model_validate_json(raw).model_dump()
    else:
        reply = _respond_with_tools(client, brain, config, contents, tools, run_tool,
                                    account_id=account_id, on_retry=on_retry)
    if assistant is not None:
        reply = _finish(reply, client=client, judge=judge, on_retry=on_retry)
    return reply


def _finish(reply: dict, *, client, judge=None, on_retry=None) -> dict:
    """The assistant's checking step, after the model has answered:
    grade the directions with the independent judge, best first, and
    keep `stage` inside the known steps. Never raises."""
    from . import assistant_brain

    reply["stage"] = assistant_brain.clean_stage(reply.get("stage"))
    if reply.get("directions"):
        if on_retry is not None:
            on_retry("checking the directions")
        try:
            reply["directions"] = assistant_brain.check_directions(
                reply["directions"], client=client, judge=judge)
        except Exception:                       # the unjudged list is still an answer
            pass
    return Reply.model_validate(reply).model_dump()


MAX_TOOL_CALLS = 6


def _respond_with_tools(client, brain, config, contents, tools, run_tool, *,
                        account_id=None, on_retry=None):
    from . import guide_tools

    # Gemini refuses a JSON response schema alongside function
    # declarations, so the answer is asked for as JSON in the
    # instructions and parsed off the text; a turn that comes back
    # unparseable gets ONE more call with the schema and no tools.
    config.tools = [types.Tool(function_declarations=[
        types.FunctionDeclaration(name=t["name"], description=t["description"],
                                  parameters_json_schema=t["input_schema"])
        for t in tools])]
    runs: list[dict] = []
    proposal = None
    for _ in range(MAX_TOOL_CALLS + 1):
        response = gemini_utils.generate_with_retry(
            client, brain["model"], contents, config=config, fallbacks=brain["fallbacks"],
            stage="creative_guide", account_id=account_id, on_retry=on_retry, raw=True)
        calls = list(response.function_calls or [])
        if not calls:
            text = (response.text or "").strip()
            break
        contents.append(response.candidates[0].content)
        parts = []
        for fc in calls:
            name, args = fc.name, dict(fc.args or {})
            if guide_tools.is_write(name):
                # The turn ends on the FIRST write: the card is the answer.
                proposal = {"tool": name, "args": guide_tools.check_args(name, args),
                            "label": guide_tools.WRITE_LABELS.get(name, name)}
                break
            if len(runs) >= MAX_TOOL_CALLS:
                result, ok = "tool budget for this turn is spent; answer now", False
            else:
                try:
                    result, ok = run_tool(name, args), True
                except Exception as exc:          # a refusal or a tool error IS the result
                    result, ok = f"error: {exc}", False
            runs.append({"tool": name, "args": args, "ok": ok})
            if on_retry is not None:
                on_retry(f"looked at {name}")
            parts.append(types.Part.from_function_response(
                name=name, response={"result": result[:12000]}))
        if proposal is not None:
            text = ""
            break
        contents.append(types.Content(role="user", parts=parts))
    else:                                          # loop exhausted without a plain answer
        text = ""

    # A contact sheet a read tool left behind this turn (find_references)
    # rides on the reply for the thread to draw; the model only saw ids.
    sheet = (getattr(run_tool, "attachments", None) or {}).get("sheet")
    if proposal is not None:
        message = (f"I can {proposal['label'].lower()}: "
                   f"{json.dumps(proposal['args'], default=str)}. Confirm on the card to do it.")
        return Reply(message=message, proposal=proposal, tool_runs=runs,
                     sheet=sheet).model_dump()
    reply = _parse_reply(text)
    if reply is None:
        # One more call, schema on, tools off, the conversation so far
        # (tool results included) as context.
        config.tools = None
        config.response_mime_type = "application/json"
        config.response_json_schema = Answer.model_json_schema()
        contents.append(types.Content(role="user", parts=[types.Part.from_text(
            text="Answer now as the JSON described, using what the tools returned.")]))
        raw = gemini_utils.generate_with_retry(
            client, brain["model"], contents, config=config, fallbacks=brain["fallbacks"],
            stage="creative_guide", account_id=account_id, on_retry=on_retry)
        reply = Answer.model_validate_json(raw)
    return Reply(**reply.model_dump(), tool_runs=[ToolRun(**r) for r in runs],
                 sheet=sheet).model_dump()


def _parse_reply(text: str):
    """The model's JSON answer off a tools turn, or None when it is
    not one. Fences are stripped; a bare sentence is not an answer."""
    if not text:
        return None
    try:
        return Answer.model_validate_json(gemini_utils.strip_fences(text))
    except Exception:
        return None


def instructions(brand, with_tools: bool = False, assistant=None):
    root = Path(__file__).resolve().parent.parent
    text = (root / "prompts/creative_guide.txt").read_text()
    if with_tools:
        text += "\n\n" + (root / "prompts/creative_guide_tools.txt").read_text()
    if assistant is not None:
        from . import assistant_brain
        text += "\n\n" + assistant_brain.instructions(
            name=assistant.get("name", ""), tone=assistant.get("tone", ""),
            stage=assistant.get("stage", ""), page=assistant.get("page", ""),
            mem=assistant.get("memory"))
    return text + "\n\nBrand guidance:\n" + shootgen.load_brand(brand)


ASSISTANT_FIELDS = ("questions", "directions", "nudge", "stage")


def _strict(schema: dict) -> dict:
    """A strict structured-output schema: every object closed, every
    property required, no defaults -- at the top level AND in $defs,
    since Question / Direction nest (2026-09-26)."""
    def close(node: dict) -> None:
        if node.get("type") == "object" and "properties" in node:
            node["additionalProperties"] = False
            node["required"] = list(node["properties"])
            for spec in node["properties"].values():
                spec.pop("default", None)
    close(schema)
    for sub in (schema.get("$defs") or {}).values():
        close(sub)
    return schema


def respond_personal(conversation, *, provider, scope, model, brand, grounding, image_refs=(),
                     assistant=None):
    from . import personal_models

    prompt = json.dumps({"grounding": grounding, "conversation": conversation.model_dump(),
                         "reference_images_supplied": len(image_refs)}, default=str)
    schema = Answer.model_json_schema()
    if assistant is None:
        # The plain Guide on a personal plan answers the three fields it
        # always did: a strict schema makes every property REQUIRED, and
        # a person's own model should not be made to emit assistant
        # fields nobody will draw.
        for key in ASSISTANT_FIELDS:
            schema["properties"].pop(key, None)
        schema.pop("$defs", None)
    schema = _strict(schema)
    system = instructions(brand, assistant=assistant)
    if provider == "chatgpt":
        raw = personal_models.codex_session(scope).generate(
            prompt, system, schema, image_refs, model)
    elif provider == "claude":
        raw = personal_models.claude_generate(scope, prompt, system, schema, image_refs, model)
    else:
        raise ValueError("Unknown personal provider")
    reply = Reply.model_validate_json(raw).model_dump()
    if assistant is not None:
        # No judge here: it would bill this install's Gemini for a turn
        # the person's own plan is paying for. Stage is still clamped.
        from . import assistant_brain
        reply["stage"] = assistant_brain.clean_stage(reply.get("stage"))
    return reply
