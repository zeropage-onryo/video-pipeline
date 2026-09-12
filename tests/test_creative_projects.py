"""Project memory is private and stale tabs cannot overwrite saved decisions."""
import pytest

from src import accounts, creative_projects


@pytest.fixture(autouse=True)
def owners(pg):
    accounts.upsert_account("one", "One", dsn=pg)
    accounts.upsert_account("two", "Two", dsn=pg)


def test_saved_project_roundtrip_and_owner_boundaries(pg):
    payload = {'messages': [{'role': 'user', 'content': 'An elevator'}],
               'brief': 'The mirror moves first.', 'refs': ['/refs/photo.jpg']}
    saved = creative_projects.save(None, 1, 'alice', 'Elevator', payload, dsn=pg)
    row = creative_projects.get(saved['id'], 1, 'alice', dsn=pg)
    assert row['payload'] == payload
    assert row['revision'] == 1
    assert creative_projects.get(saved['id'], 1, 'bob', dsn=pg) is None
    assert creative_projects.get(saved['id'], 2, 'alice', dsn=pg) is None
    assert creative_projects.list_projects(1, 'bob', dsn=pg) == []
    assert creative_projects.save(saved['id'], 2, 'alice', 'Hijacked', {}, 1, dsn=pg) is None
    assert creative_projects.save(saved['id'], 1, 'bob', 'Hijacked', {}, 1, dsn=pg) is None


def test_stale_tab_cannot_replace_newer_brief(pg):
    saved = creative_projects.save(None, 1, 'alice', 'Scene', {'brief': 'Original'}, dsn=pg)
    newer = creative_projects.save(saved['id'], 1, 'alice', 'Scene', {'brief': 'Quiet'}, 1, dsn=pg)
    assert newer['revision'] == 2
    assert creative_projects.save(saved['id'], 1, 'alice', 'Scene', {'brief': 'Loud'}, 1, dsn=pg) is None
    assert creative_projects.get(saved['id'], 1, 'alice', dsn=pg)['payload']['brief'] == 'Quiet'


def test_http_routes_derive_owner_and_reject_cross_site_mutation(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app import auth
    from app.creative_projects import router

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[auth.current_account_id] = lambda: 7
    monkeypatch.setattr(auth, 'current_user', lambda request: {'id': 'signed-in-user'})
    seen = {}

    def save(project_id, account_id, user_id, title, payload, revision):
        seen.update(account=account_id, user=user_id, payload=payload)
        return {'id': 'saved', 'revision': 1}

    monkeypatch.setattr(creative_projects, 'save', save)
    client = TestClient(app)
    body = {'title': 'Test', 'account_id': 99, 'user_id': 'someone-else',
            'payload': {'brief': 'A quiet scene'}}
    assert client.post('/creative-projects', json=body).status_code == 403
    assert seen == {}
    assert client.post('/creative-projects', json=body,
                       headers={'X-ZPF-Model-Connection': '1'}).status_code == 200
    assert seen['account'] == 7 and seen['user'] == 'signed-in-user'
    monkeypatch.setattr(creative_projects, 'save', lambda *args: None)
    assert client.post('/creative-projects', json=body,
                       headers={'X-ZPF-Model-Connection': '1'}).status_code == 409
