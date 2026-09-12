"""Conversational brief development; no concept or render mutations."""
import json
from pathlib import Path
from typing import Literal

from google.genai import types
from pydantic import BaseModel, Field

from . import gemini_utils, shootgen


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=20000)


class Conversation(BaseModel):
    messages: list[Message] = Field(min_length=1, max_length=40)


class Reply(BaseModel):
    message: str = Field(min_length=1, max_length=3000)
    choices: list[str] = Field(default_factory=list, max_length=3)
    brief: str = Field(default="", max_length=8000)


def respond(conversation, *, client, brand, grounding, image_refs=(),
            account_id=None, on_retry=None):
    brain = gemini_utils.resolve_brain("reasoning")
    config = brain["config"].model_copy(deep=True)
    config.system_instruction = instructions(brand)
    config.response_mime_type = "application/json"
    config.response_json_schema = Reply.model_json_schema()
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
    raw = gemini_utils.generate_with_retry(
        client, brain["model"], contents, config=config, fallbacks=brain["fallbacks"],
        stage="creative_guide", account_id=account_id, on_retry=on_retry)
    return Reply.model_validate_json(raw).model_dump()


def instructions(brand):
    return ((Path(__file__).resolve().parent.parent / "prompts/creative_guide.txt").read_text()
            + "\n\nBrand guidance:\n" + shootgen.load_brand(brand))


def respond_personal(conversation, *, provider, scope, model, brand, grounding, image_refs=()):
    from . import personal_models

    prompt = json.dumps({"grounding": grounding, "conversation": conversation.model_dump(),
                         "reference_images_supplied": len(image_refs)}, default=str)
    schema = Reply.model_json_schema()
    schema["additionalProperties"] = False
    schema["required"] = list(schema["properties"])
    for spec in schema["properties"].values():
        spec.pop("default", None)
    if provider == "chatgpt":
        raw = personal_models.codex_session(scope).generate(
            prompt, instructions(brand), schema, image_refs, model)
    elif provider == "claude":
        raw = personal_models.claude_generate(scope, prompt, instructions(brand), schema, image_refs, model)
    else:
        raise ValueError("Unknown personal provider")
    return Reply.model_validate_json(raw).model_dump()
