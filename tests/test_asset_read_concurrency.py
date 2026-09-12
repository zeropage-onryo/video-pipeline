"""Asset catalogue reads must not migrate tables or deadlock each other."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from app import auth
from app.main import app
from src import db, entities, preprod, render_assets


@pytest.mark.parametrize('initialized', [False, True])
def test_generated_asset_reads_are_read_only(pg, monkeypatch, initialized):
    if initialized:
        render_assets.init(pg)
        with db.connect(pg) as conn:
            conn.execute("INSERT INTO generated_assets "
                         "(created_at,generation_id,tool,model,media_kind,prompt,media_url) "
                         "VALUES ('today',1,'runway','test','video','A scene','/renders/test.mp4')")
    with db.connect(pg) as conn:
        conn.execute('SET TRANSACTION READ ONLY')

        @contextmanager
        def read_only(dsn=None):
            yield conn

        monkeypatch.setattr(db, 'connect', read_only)
        rows = render_assets.list_all(pg, account_id=None)
        assert len(rows) == int(initialized)
        if rows:
            assert rows[0]['media_url'] == '/renders/test.mp4'
            assert rows[0]['provider'] == 'Runway'


def test_assets_and_media_can_load_simultaneously(pg, monkeypatch):
    preprod.init(pg)
    entities.init(pg)
    render_assets.init(pg)
    monkeypatch.setenv('DATABASE_URL', pg)
    monkeypatch.setattr(auth, 'current_user', lambda request: {'id': 'reader'})

    def fetch(path):
        client = TestClient(app, raise_server_exceptions=False)
        try:
            response = client.get(path)
            assert response.status_code == 200, response.text
            assert response.json()['items'] == []
        finally:
            client.close()

    with db.connection_pool(pg, max_size=4):
        with ThreadPoolExecutor(max_workers=6) as workers:
            list(workers.map(fetch, ['/api/assets', '/api/media?kind=all'] * 12))
