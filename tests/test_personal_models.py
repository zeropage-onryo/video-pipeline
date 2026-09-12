"""Personal model isolation and no API-key fallbacks or executable tools."""
import json
import subprocess
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import auth
from app.main import app
from src import creative_guide
from src import personal_models as pm


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(pm, "SESSIONS_ROOT", tmp_path / "sessions")
    monkeypatch.setattr(pm, "_POOL", {})
    monkeypatch.setattr(pm, "_CLAUDE_LOGINS", {})
    monkeypatch.setattr(pm, "_CLAUDE_TURNS", {})


def test_scope_binds_both_person_and_account():
    assert pm.scope_id('a', 1) != pm.scope_id('b', 1)
    assert pm.scope_id('a', 1) != pm.scope_id('a', 2)
    assert '/' not in pm.scope_id('../../a', 1)
    with pytest.raises(pm.ConnectionUnavailable):
        pm.scope_id('', 1)


def test_child_environment_cannot_borrow_operator_credentials(monkeypatch, tmp_path):
    for name in ('OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN',
                 'CLAUDE_CODE_OAUTH_TOKEN', 'CODEX_ACCESS_TOKEN', 'CODEX_HOME',
                 'CLAUDE_CONFIG_DIR', 'DATABASE_URL', 'GEMINI_API_KEY'):
        monkeypatch.setenv(name, 'operator-secret')
    for provider in ('chatgpt', 'claude'):
        env = pm.runtime_env(tmp_path, provider)
        assert 'operator-secret' not in env.values()
    assert pm.runtime_env(tmp_path, 'chatgpt')['CODEX_HOME'] == str(tmp_path)


def test_private_directories(tmp_path):
    directory = pm.runtime_dir(pm.scope_id('a', 1), 'chatgpt')
    assert directory.stat().st_mode & 0o777 == 0o700
    assert directory.parent.stat().st_mode & 0o777 == 0o700


def test_claude_status_does_not_treat_api_auth_as_subscription(monkeypatch):
    monkeypatch.setattr(pm, 'claude_command', lambda *a, **k: SimpleNamespace(
        stdout=json.dumps({'loggedIn': True, 'authMethod': 'api_key'})))
    assert not pm.claude_status('scope')['connected']


def test_claude_passes_images_and_disables_tools(monkeypatch):
    seen = {}
    monkeypatch.setattr(pm, 'claude_status', lambda scope: {'connected': True})

    def run(scope, args, **kwargs):
        seen.update(scope=scope, args=args, **kwargs)
        return SimpleNamespace(returncode=0, stdout=json.dumps({
            'structured_output': {'message': 'Hello', 'choices': [], 'brief': ''}}))

    monkeypatch.setattr(pm, 'claude_command', run)
    reply = pm.claude_generate('private-user', 'prompt', 'instruction', {'type': 'object'},
                              [(b'photo', 'image/jpeg', 'The subject')], 'sonnet')
    assert json.loads(reply)['message'] == 'Hello'
    assert seen['scope'] == 'private-user'
    assert seen['args'][seen['args'].index('--tools') + 1] == ''
    assert '--strict-mcp-config' in seen['args']
    assert '--safe-mode' in seen['args']
    assert '--fallback-model' not in seen['args']
    content = json.loads(seen['input'])['message']['content']
    assert content[-1]['source']['data'] == 'cGhvdG8='


def test_claude_bad_model_never_calls_runtime(monkeypatch):
    monkeypatch.setattr(pm, 'claude_command', lambda *a, **k: pytest.fail('called'))
    with pytest.raises(pm.ConnectionUnavailable):
        pm.claude_generate('private', '', '', {}, [], '--evil')


def test_claude_failures_do_not_expose_runtime_output(monkeypatch):
    monkeypatch.setattr(pm, 'claude_status', lambda scope: {'connected': True})
    monkeypatch.setattr(pm, 'claude_command', lambda *a, **k: SimpleNamespace(
        returncode=1, stdout='secret-token'))
    with pytest.raises(pm.ConnectionUnavailable) as error:
        pm.claude_generate('scope', '', '', {}, [])
    assert 'secret-token' not in str(error.value)


def test_claude_timeout_is_reported(monkeypatch):
    monkeypatch.setattr(pm, 'executable', lambda p: '/test/claude')

    def timed_out(*args, **kwargs):
        raise subprocess.TimeoutExpired('claude', 1)

    monkeypatch.setattr(pm.subprocess, 'run', timed_out)
    with pytest.raises(pm.ConnectionUnavailable, match='too long'):
        pm.claude_command('scope', ['auth', 'status'])


def test_codex_turn_keeps_schema_images_and_no_tools(monkeypatch, tmp_path):
    import queue
    import threading
    session = object.__new__(pm.CodexSession)
    session.turn_lock = threading.Lock()
    session.workspace = tmp_path
    session.events = queue.Queue()
    session.events.put({'method': 'item/completed', 'params': {'threadId': 't',
        'item': {'type': 'agentMessage', 'text': '{"message":"hello"}'}}})
    session.events.put({'method': 'turn/completed', 'params': {'threadId': 't',
        'turn': {'id': 'r', 'status': 'completed'}}})
    monkeypatch.setattr(session, 'status', lambda: {'connected': True})
    monkeypatch.setattr(session, 'models', lambda: [{'id': 'test-model'}])
    calls = []

    def call(method, params=None, **kwargs):
        calls.append((method, params))
        return {'thread': {'id': 't'}, 'turn': {'id': 'r'}}

    monkeypatch.setattr(session, 'call', call)
    reply = session.generate('prompt', 'instructions', {'type': 'object'},
                             [(b'photo', 'image/jpeg', 'Ref')], 'test-model')
    assert json.loads(reply)['message'] == 'hello'
    assert calls[0][1]['sandbox'] == 'read-only'
    assert calls[0][1]['ephemeral']
    assert calls[1][1]['input'][-1]['url'].startswith('data:image/jpeg;base64,')
    assert calls[1][1]['outputSchema'] == {'type': 'object'}
    assert not session.turn_lock.locked()


def test_personal_reply_validation_and_history(monkeypatch):
    seen = {}

    def generate(prompt, instruction, schema, images, model):
        seen.update(prompt=json.loads(prompt), schema=schema)
        return '{"message":"Next choice?", "choices":[], "brief":"Draft"}'

    monkeypatch.setattr(pm, 'codex_session', lambda scope: SimpleNamespace(generate=generate))
    reply = creative_guide.respond_personal(creative_guide.Conversation(messages=[
        {'role': 'user', 'content': 'A mirror'}]), provider='chatgpt', scope='private', model='',
        brand='zeropage', grounding={})
    assert reply['brief'] == 'Draft'
    assert seen['prompt']['conversation']['messages'][0]['content'] == 'A mirror'
    assert not seen['schema']['additionalProperties']
    assert set(seen['schema']['required']) == {'message', 'choices', 'brief'}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(auth, 'current_user', lambda request: {'id': 'alice'})
    app.dependency_overrides[auth.current_account_id] = lambda: 12
    return TestClient(app, headers={"X-ZPF-Model-Connection": "1"})


def test_signin_uses_only_authenticated_scope(client, monkeypatch):
    calls = []
    monkeypatch.setattr(pm, 'codex_session', lambda scope: (
        calls.append(scope) or SimpleNamespace(start_login=lambda: {'url': 'https://auth.openai.com/codex/device',
                                                                  'code': 'TEST-CODE'})))
    response = client.post('/api/model-connections/chatgpt/signin',
        headers={'X-ZPF-Model-Connection': '1'}, json={'user_id': 'bob', 'account_id': 99})
    assert response.status_code == 200
    assert calls == [pm.scope_id('alice', 12)]
    assert set(response.json()) == {'url', 'code'}


def test_cross_site_form_cannot_start_or_disconnect(client, monkeypatch):
    monkeypatch.setattr(pm, 'codex_session', lambda *a: pytest.fail('started'))
    client.headers.pop('X-ZPF-Model-Connection')
    assert client.post('/api/model-connections/chatgpt/signin').status_code == 403
    assert client.post('/api/model-connections/chatgpt/disconnect').status_code == 403


def test_claude_remote_signin_explains_native_callback(client, monkeypatch):
    monkeypatch.setattr(pm, 'claude_login', lambda *a: pytest.fail('opened server browser'))
    response = client.post('/api/model-connections/claude/signin',
                           headers={'X-ZPF-Model-Connection': '1'})
    assert response.status_code == 409


def test_disconnected_personal_provider_never_uses_gemini(client, monkeypatch):
    monkeypatch.setattr(pm, 'codex_session', lambda scope: SimpleNamespace(status=lambda: {'connected': False}))
    monkeypatch.setattr(creative_guide, 'respond', lambda *a, **k: pytest.fail('Gemini fallback'))
    response = client.post('/api/creative-guide', data={'guide_provider': 'chatgpt',
        'conversation': json.dumps({'messages': [{'role': 'user', 'content': 'hello'}]})})
    assert response.status_code == 409


def test_personal_guide_works_without_gemini_key(client, monkeypatch):
    import time

    from app import api
    from src import scene_chain

    seen = {}
    monkeypatch.setattr(api, '_gemini_key', lambda: None)
    monkeypatch.setattr(auth, 'current_account', lambda request: {'slug': 'zeropage'})
    monkeypatch.setattr(pm, 'codex_session', lambda scope: SimpleNamespace(status=lambda: {'connected': True}))
    monkeypatch.setattr(creative_guide, 'respond', lambda *a, **k: pytest.fail('billed Gemini'))
    monkeypatch.setattr(scene_chain, 'ground', lambda *a, **k: {})

    async def refs(form):
        return [], [], []

    def respond(conversation, **kwargs):
        seen.update(kwargs)
        return {'message': 'Done', 'choices': [], 'brief': 'Scene draft'}

    monkeypatch.setattr(api, '_collect_refs', refs)
    monkeypatch.setattr(creative_guide, 'respond_personal', respond)
    response = client.post('/api/creative-guide', data={'guide_provider': 'chatgpt', 'guide_model': 'chosen',
        'conversation': json.dumps({'messages': [{'role': 'user', 'content': 'hello'}]})})
    assert response.status_code == 200
    job_id = response.json()['job_id']
    for _ in range(100):
        job = client.get(f'/api/jobs/{job_id}').json()
        if job['status'] in ('done', 'failed'):
            break
        time.sleep(.01)
    assert job['status'] == 'done', job
    assert job['billing'] == 'personal_plan'
    assert seen['scope'] == pm.scope_id('alice', 12)
    assert seen['model'] == 'chosen'


def test_disconnect_cancels_pending_device_login_before_logout(monkeypatch):
    import threading

    session = object.__new__(pm.CodexSession)
    session.auth_lock = threading.Lock()
    session.login_id = 'pending-login'
    session.login = {'code': 'pending-code'}
    calls = []
    monkeypatch.setattr(session, 'call', lambda method, params=None: calls.append((method, params)))
    session.logout()
    assert calls == [('account/login/cancel', {'loginId': 'pending-login'}), ('account/logout', None)]
    assert session.login is None
    assert session.login_id is None
