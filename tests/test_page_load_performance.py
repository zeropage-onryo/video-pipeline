"""Connection reuse must preserve transactions and request-level authorization."""
from unittest.mock import Mock

import pytest
from starlette.requests import Request

from app import auth
from src import db


def test_pool_reuses_connection_and_rolls_back_failed_write(pg):
    with db.connection_pool(pg, max_size=1) as pool:
        with db.connect(pg) as conn:
            first = conn.info.backend_pid
            assert conn.execute('SHOW TIME ZONE').fetchone()[0] == 'UTC'
            conn.execute('CREATE TABLE pool_probe (value INT)')
            conn.execute('INSERT INTO pool_probe VALUES (1)')
        with pytest.raises(ValueError):
            with db.connect(pg) as conn:
                assert conn.info.backend_pid == first
                conn.execute('INSERT INTO pool_probe VALUES (2)')
                raise ValueError('abort')
        with db.connect(pg) as conn:
            assert conn.info.backend_pid == first
            assert conn.execute('SELECT value FROM pool_probe').fetchall() == [{'value': 1}]
    assert pool.closed
    assert db._pool is None


def test_pool_never_substitutes_another_schema(pg, pg_factory):
    other = pg_factory()
    with db.connection_pool(pg, max_size=1):
        with db.connect(pg) as conn:
            schema = conn.execute('SELECT current_schema()').fetchone()[0]
        with db.connect(other) as conn:
            assert conn.execute('SELECT current_schema()').fetchone()[0] != schema


def test_auth_reuses_lookups_only_within_the_request(monkeypatch):
    monkeypatch.setenv('SESSION_SECRET', 'page-load-test')
    get_user = Mock(return_value={'id': 'reader'})
    memberships = Mock(return_value=[{'id': 1, 'slug': 'zeropage'},
                                     {'id': 2, 'slug': 'antihero'}])
    monkeypatch.setattr(auth.accounts, 'get_user', get_user)
    monkeypatch.setattr(auth.accounts, 'memberships', memberships)
    token = auth._serializer().dumps({'uid': 'reader'})

    def request():
        return Request({'type': 'http', 'headers': [
            (b'cookie', f'zp_session={token}; brand=antihero'.encode())]})

    first = request()
    assert auth.current_user(first)['id'] == 'reader'
    assert auth.current_account(first)['slug'] == 'antihero'
    assert auth.current_account_id(first) == 1
    get_user.assert_called_once()
    memberships.assert_called_once()
    memberships.return_value = []
    with pytest.raises(Exception) as error:
        auth.current_account_id(request())
    assert error.value.status_code == 403
    assert memberships.call_count == get_user.call_count == 2


def test_concept_list_batches_locations_and_matches_single_reads(pg, monkeypatch):
    from contextlib import contextmanager

    from src import preprod

    preprod.init(pg)
    rooms = [preprod.add_location(name, {}, dsn=pg, account_id=None)
             for name in ('Zebra room', 'Amber room')]
    ids = [preprod.save_concept(
        {'title': f'Scene {n}', 'shots': [{'prompt': 'A scene'}]},
        brand='zeropage', location_ids=rooms if n % 2 else [],
        dsn=pg, account_id=None,
    ) for n in range(12)]
    expected = [preprod.get_concept(i, dsn=pg, account_id=None) for i in reversed(ids)]
    original = preprod.connect
    executions = []

    @contextmanager
    def counted(dsn=None):
        with original(dsn) as conn:
            proxy = Mock(wraps=conn)
            yield proxy
            executions.append(proxy.execute.call_count)

    monkeypatch.setattr(preprod, 'connect', counted)
    assert preprod.list_concepts(dsn=pg, account_id=None) == expected
    assert executions == [2]  # fixed query count, regardless of card count
    assert [room['name'] for room in expected[0]['locations']] == ['Amber room', 'Zebra room']


def test_provider_status_works_in_read_only_transaction(pg, monkeypatch):
    """The Queue's renderer status is a READ: it must answer inside a
    read-only transaction, with no DDL on a page load. (It read the BYOK key
    table until 2026-09-26; there are no stored keys now, only FAL_KEY.)"""
    from contextlib import contextmanager

    from src import providers

    monkeypatch.setenv('FAL_KEY', 'test-operator-key')
    with db.connect(pg) as conn:
        conn.execute('SET TRANSACTION READ ONLY')

        @contextmanager
        def read_only(dsn=None):
            yield conn

        monkeypatch.setattr(db, 'connect', read_only)
        state = providers.provider_state('fal', 1, pg)
        assert state['available'] is True
