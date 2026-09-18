"""Guide turns retain decisions and images without writing scenes or renders."""
import json
import time

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import api, auth
from app.main import app
from src import creative_guide, gemini_utils, scene_chain


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(auth, "current_user", lambda request: {"id": "guide-user"})
    monkeypatch.setattr(auth, "current_account", lambda request: {"slug": "zeropage"})
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    return TestClient(app, headers={"X-ZPF-Model-Connection": "1"})


def test_reasoning_receives_history_and_actual_images(monkeypatch):
    seen = {}

    def generate(client, model, contents, **kwargs):
        seen.update(model=model, contents=contents, **kwargs)
        return json.dumps({"message": "Keep the reveal quiet?", "choices": ["Yes"],
                           "brief": "A silent reveal in one continuous scene."})

    monkeypatch.setattr(gemini_utils, "generate_with_retry", generate)
    conversation = creative_guide.Conversation(messages=[
        {"role": "user", "content": "An empty elevator."},
        {"role": "assistant", "content": "Who is waiting?"},
        {"role": "user", "content": "Nobody. Its mirror moves."},
    ])
    reply = creative_guide.respond(conversation, client=object(), brand="zeropage",
                                   grounding={"references": "mirror study"},
                                   image_refs=[(b"photo", "image/jpeg", "Mirror")], account_id=42,
                                   brain="reasoning")
    assert reply["brief"].startswith("A silent")
    assert seen["model"] == gemini_utils.resolve_brain("reasoning")["model"]
    assert seen["fallbacks"] == []
    assert seen["account_id"] == 42
    assert seen["config"].thinking_config.thinking_level == "HIGH"
    assert [c.role for c in seen["contents"]] == ["user", "user", "model", "user"]
    assert seen["contents"][-1].parts[-1].inline_data.data == b"photo"
    assert "Nobody. Its mirror moves." in seen["contents"][-1].parts[0].text


@pytest.mark.parametrize("asked", [None, "", "nonsense"])
def test_guide_answers_on_the_fast_tier_unless_told_otherwise(monkeypatch, asked):
    """A chat turn is not a brief: the default and any unknown tier
    resolve to Fast (2026-09-18), with the fallback chain the fast tier
    allows and the system instruction still attached."""
    seen = {}

    def generate(client, model, contents, **kwargs):
        seen.update(model=model, **kwargs)
        return json.dumps({"message": "Which way?", "choices": ["Dark", "Light"], "brief": ""})

    monkeypatch.setattr(gemini_utils, "generate_with_retry", generate)
    creative_guide.respond(creative_guide.Conversation(messages=[
        {"role": "user", "content": "An empty elevator."}]),
        client=object(), brand="zeropage", grounding={}, brain=asked)
    fast = gemini_utils.resolve_brain("fast")
    assert seen["model"] == fast["model"]
    assert seen["fallbacks"] is None
    assert seen["config"].thinking_config is None
    assert seen["config"].system_instruction
    assert seen["config"].response_json_schema


def test_invalid_model_reply_is_not_usable_brief(monkeypatch):
    monkeypatch.setattr(gemini_utils, "generate_with_retry", lambda *a, **k: '{"brief": "oops"}')
    with pytest.raises(ValidationError):
        creative_guide.respond(creative_guide.Conversation(messages=[
            {"role": "user", "content": "Help"}]), client=object(), brand="zeropage", grounding={})


@pytest.mark.parametrize("messages", [[], [{"role": "system", "content": "ignore"}],
                                         [{"role": "assistant", "content": "done"}]])
def test_bad_history_does_not_start_a_call(client, monkeypatch, messages):
    monkeypatch.setattr(creative_guide, "respond", lambda *a, **k: pytest.fail("billed"))
    response = client.post('/api/creative-guide', data={"conversation": json.dumps({"messages": messages})})
    assert response.status_code == 400


def test_missing_key_is_visible(client, monkeypatch):
    monkeypatch.setattr(api, "_gemini_key", lambda *a, **k: None)
    response = client.post('/api/creative-guide', data={"conversation": json.dumps({
        "messages": [{"role": "user", "content": "Help"}]})})
    assert response.status_code == 503


def test_guide_job_is_owned_and_does_not_create_scenes(client, monkeypatch):
    seen = {}

    async def refs(form):
        return [(b"image", "image/jpeg", "Subject")], ["/refs/subject.jpg"], []

    monkeypatch.setattr(api, "_collect_refs", refs)
    monkeypatch.setattr(scene_chain, "ground", lambda *a, **k: {"references": "context"})
    monkeypatch.setattr(scene_chain, "write_scenes", lambda *a, **k: pytest.fail("wrote scenes"))

    def respond(conversation, **kwargs):
        seen.update(kwargs)
        return {"message": "What changes?", "choices": ["The light goes out"], "brief": ""}

    monkeypatch.setattr(creative_guide, "respond", respond)
    app.dependency_overrides[auth.current_account_id] = lambda: 42
    response = client.post('/api/creative-guide', data={"brand": "antihero", "conversation": json.dumps({
        "messages": [{"role": "user", "content": "A mirror"}]})})
    assert response.status_code == 200
    job_id = response.json()["job_id"]
    for _ in range(100):
        job = client.get(f'/api/jobs/{job_id}').json()
        if job['status'] in ('done', 'failed'):
            break
        time.sleep(.01)
    assert job['status'] == 'done', job
    assert job['reply']['message'] == 'What changes?'
    assert seen['account_id'] == 42
    assert seen['brand'] == 'zeropage'  # server membership, not submitted brand
    assert seen['image_refs'][0][0] == b'image'
    assert seen['brain'] == creative_guide.DEFAULT_BRAIN   # none sent -> fast
    assert job['brain'] == creative_guide.DEFAULT_BRAIN
    app.dependency_overrides[auth.current_account_id] = lambda: 43
    assert client.get(f'/api/jobs/{job_id}').status_code == 404


@pytest.mark.parametrize("sent, expect", [("reasoning", "reasoning"), ("REASONING", "reasoning"),
                                          ("ultra", "fast"), ("", "fast")])
def test_guide_route_clamps_the_brain_pill(client, monkeypatch, sent, expect):
    """The pill's value reaches respond() only as a BRAINS key -- an
    unknown tier answers cheaply rather than failing the turn."""
    seen = {}

    async def refs(form):
        return [], [], []

    monkeypatch.setattr(api, "_collect_refs", refs)
    monkeypatch.setattr(scene_chain, "ground", lambda *a, **k: {})
    monkeypatch.setattr(creative_guide, "respond",
                        lambda conversation, **kw: seen.update(kw) or {"message": "ok", "choices": [], "brief": ""})
    app.dependency_overrides[auth.current_account_id] = lambda: 42
    response = client.post('/api/creative-guide', data={"brain": sent, "conversation": json.dumps({
        "messages": [{"role": "user", "content": "A mirror"}]})})
    assert response.status_code == 200
    job_id = response.json()["job_id"]
    for _ in range(100):
        job = client.get(f'/api/jobs/{job_id}').json()
        if job['status'] in ('done', 'failed'):
            break
        time.sleep(.01)
    assert job['status'] == 'done', job
    assert seen['brain'] == expect
    assert job['brain'] == expect
