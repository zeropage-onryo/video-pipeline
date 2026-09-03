"""
Shared test setup.

The guard below exists because this has now bitten four times: a test
monkeypatches one generator function, the route is changed to call a
different one, the patch silently misses, and the test makes a real
billed API call while still passing. Nothing failed -- the only signal
was the suite getting slower.

So: no test may reach the network. Anything that wants to talk to
Gemini or YouTube has to patch the function it actually calls, and
gets a loud, immediate failure naming the offender if it doesn't.
"""
import os
import socket

import pytest

# The suite runs in the dev posture: the dev-console pages only register
# when DEV_TOOLS=1 (app/main.py), and the page tests hit them. CI has no
# .env, so pin it here -- conftest imports before any test module pulls
# in app.main. The public posture has its own tests (test_dev_tools.py),
# which reload app.main under DEV_TOOLS=0.
os.environ["DEV_TOOLS"] = "1"


from app.main import app as _APP_AT_IMPORT  # noqa: E402  (see account_scope)


class NetworkUseInTest(RuntimeError):
    pass


@pytest.fixture(autouse=True)
def no_network(monkeypatch, request):
    def blocked(*args, **kwargs):
        raise NetworkUseInTest(
            f"{request.node.nodeid} tried to open a network connection. "
            "A real API call in a test usually means a monkeypatch is "
            "patching a function the code under test no longer calls."
        )

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)


@pytest.fixture(autouse=True)
def account_scope():
    """Give every route an account to act as.

    Routes take `account_id: int = Depends(auth.current_account_id)`, and
    FastAPI captures that callable when the route is registered -- so
    monkeypatching the module attribute the way these tests patch
    `auth.current_user` does nothing. `dependency_overrides` is the
    supported seam.

    None is the unowned pool: rows that carry no account_id, which is
    exactly what a fixture database with no seeded accounts holds. So
    every test that was never about ownership keeps asserting what it
    always did. A test that IS about isolation seeds real accounts and
    sets its own override -- see tests/test_tenancy.py.
    """
    import app.main as app_main
    from app import auth

    # Both app objects, and they really can be two. test_dev_tools.py does
    # `importlib.reload(app_main)` to exercise the DEV_TOOLS=0 posture,
    # which builds a NEW FastAPI instance and rebinds app.main.app -- while
    # every other test module still holds the original from its
    # module-level `from app.main import app`. Override only the current
    # one and those modules' requests resolve the real dependency, which
    # then trips over a stubbed account dict that has no "id". That failure
    # only appears when the two files land in the same xdist worker, which
    # is why it looked like flakiness.
    targets = {id(_APP_AT_IMPORT): _APP_AT_IMPORT, id(app_main.app): app_main.app}
    for target in targets.values():
        target.dependency_overrides[auth.current_account_id] = lambda: None
        target.dependency_overrides[auth.dev_account_id] = lambda: None
    yield
    for target in targets.values():
        target.dependency_overrides.pop(auth.current_account_id, None)
        target.dependency_overrides.pop(auth.dev_account_id, None)


# ---------------------------------------------------------------------------
# the throwaway Postgres (docs/tasks/task-postgres-migration.md)
# ---------------------------------------------------------------------------

# Where the port's tests run. NEVER DATABASE_URL: that is the live database
# in any real .env, and this fixture creates and drops schemas. The default
# is the docker-compose box, which is also the throwaway on Mike's machine
# (a role+database of that name on Postgres.app, 2026-09-03).
TEST_DSN = os.environ.get("TEST_DATABASE_URL") or "postgresql://zeropage:zeropage@localhost:5432/zeropage"


@pytest.fixture
def pg():
    """A connection URL onto a fresh, private schema, torn down after.

    Isolation is the schema, carried in the URL itself (`options=-c
    search_path=...`), so the code under test needs no notion of "which
    schema" -- CREATE TABLE IF NOT EXISTS, to_regclass() and
    information_schema all resolve on search_path -- and tests can run in
    parallel against one database. Every id sequence starts at 1 in a
    new schema, which is what the `run_id == 1` assertions rely on.
    """
    import uuid

    import psycopg
    from psycopg.conninfo import make_conninfo

    from src import db

    schema = f"t_{uuid.uuid4().hex[:12]}"
    try:
        admin = psycopg.connect(TEST_DSN, autocommit=True)
    except psycopg.OperationalError as e:  # pragma: no cover - environment
        pytest.fail(
            f"no throwaway Postgres at {TEST_DSN!r} ({e}). Start it "
            "(`docker compose up -d`) or point TEST_DATABASE_URL at one."
        )
    admin.execute(f"CREATE SCHEMA {schema}")
    dsn = make_conninfo(TEST_DSN, options=f"-c search_path={schema}")
    try:
        db.init_db(dsn)
        yield dsn
    finally:
        admin.execute(f"DROP SCHEMA {schema} CASCADE")
        admin.close()


@pytest.fixture
def pg_factory():
    """More throwaway schemas on demand, for a test that needs a SECOND
    database beside `pg` -- an empty one to prove a read degrades, a
    fresh one to prove a seed. Each call is a new schema with NOTHING in
    it (not even db.init_db), torn down with the test."""
    import uuid

    import psycopg
    from psycopg.conninfo import make_conninfo

    admin = psycopg.connect(TEST_DSN, autocommit=True)
    made: list[str] = []

    def make() -> str:
        schema = f"t_{uuid.uuid4().hex[:12]}"
        admin.execute(f"CREATE SCHEMA {schema}")
        made.append(schema)
        return make_conninfo(TEST_DSN, options=f"-c search_path={schema}")

    try:
        yield make
    finally:
        for schema in made:
            admin.execute(f"DROP SCHEMA {schema} CASCADE")
        admin.close()
