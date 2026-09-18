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

`output_roots_in_tmp` below is the same idea for the OTHER thing a test
can do to a real machine: write to it. See its docstring.
"""
import importlib
import os
import socket
from pathlib import Path

import pytest

# The suite runs in the dev posture: the dev-console pages only register
# when DEV_TOOLS=1 (app/main.py), and the page tests hit them. CI has no
# .env, so pin it here -- conftest imports before any test module pulls
# in app.main. The public posture has its own tests (test_dev_tools.py),
# which reload app.main under DEV_TOOLS=0.
os.environ["DEV_TOOLS"] = "1"

# The reference rule (2026-09-08): in production a spark with no pictures
# behind it does not get written from at all -- `orchestrator.planner`
# holds the run. Pinned OFF here, deliberately, and for one reason: every
# graph test in this suite was written to exercise something else (the
# retry edge, the prompt gate, the keyframe, tenancy) and hands the graph
# a bare spark, so leaving it on would turn eighty-odd unrelated tests
# into assertions about reference images. The rule has its own tests,
# which turn it ON explicitly -- tests/test_reference_rule.py -- the same
# arrangement ZEROPAGE_GATES uses, where the default is what the suite
# runs under and the other mode is pinned per test.
os.environ["ZEROPAGE_REQUIRE_REFS"] = "0"


from app.main import app as _APP_AT_IMPORT  # noqa: E402  (see account_scope)

# Modules that are ABOUT the reference rule turn it back on for
# themselves. Keeping the list here rather than a fixture in each file is
# deliberate: the rule grew from two directions on the same day and the
# thing that would actually go wrong is a third enforcement point landing
# with its tests written under the suite default, passing, and testing
# nothing. A module named for the rule is opted in by being named.
REFS_RULE_MODULES = {"test_reference_gate", "test_reference_rule"}


@pytest.fixture(autouse=True)
def _refs_rule(request, monkeypatch):
    """ZEROPAGE_REQUIRE_REFS on for the rule's own tests, off elsewhere.

    A test whose NAME says it is about an ungrounded scene opts in too --
    those live in files that are mostly about something else (the queue,
    the board), and splitting them out would separate them from the
    fixtures they share."""
    module = request.module.__name__.rsplit(".", 1)[-1]
    if module in REFS_RULE_MODULES or "ungrounded" in request.node.name:
        monkeypatch.setenv("ZEROPAGE_REQUIRE_REFS", "1")


class NetworkUseInTest(RuntimeError):
    pass


# THE SUITE RUNS AS CI RUNS IT (2026-09-08). Everything below is a
# DEPLOYMENT POSTURE that lives in .env on Mike's machine and nowhere in
# CI, so a suite that inherits it is two different suites -- eleven
# orchestrator tests fail on his Mac and pass on GitHub, and the one that
# actually mattered (a reference photo's canonical URL) silently swapped
# what a dozen assertions were checking without either run saying which
# it got. A test that is ABOUT one of these sets it itself; monkeypatch
# unwinds these deletes in order, so a setenv inside a test still wins.
#
# A fixture and not a module-level pop, because app.main calls
# load_dotenv() at import and would put every one of them straight back.
R2_ENV = ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY",
          "R2_BUCKET", "R2_PUBLIC_BASE_URL")

POSTURE_ENV = R2_ENV + (
    "ZEROPAGE_KEYFRAME",         # the night's stills, off since 2026-09-08
    "ZEROPAGE_UNCANNY",          # the on-brand judge, off on his machine
    "ZEROPAGE_GRAPH_SCOUT",      # a run that names no direction reads the bank
    "ZEROPAGE_GRAPH_RESEARCH",   # ... and the research agent runs
    "ZEROPAGE_SCENE_SECONDS",    # the scene length the writers fill (timeline.py)
    "LANGSMITH_TRACING",         # tracing is a live POST; the guard fails it
    "QUOTE_SIGNING_SECRET",      # quotes sign only where a test says so
)


@pytest.fixture(autouse=True)
def r2_off(monkeypatch):
    """Shipped defaults, not this machine's .env."""
    for name in POSTURE_ENV:
        monkeypatch.delenv(name, raising=False)


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


PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Every module-level path that names somewhere this project WRITES on the
# real machine: (module, attribute, where it lives under the project root).
# The last field is what makes the redirect faithful -- RENDER_DIR has to
# stay *inside* RENDERS_ROOT or `_local_render_bytes`'s containment check
# refuses the very file the test just wrote.
#
# A test that drives a render patches the HTTP layer, not the output path,
# and the fake downloader writes 2048 zero bytes because that is what
# passes the size QC. Nothing about that is wrong -- but with RENDER_DIR
# still pointing at data/renders/higgsfield/, every one of those stubs
# landed in the owner's real render directory, named wf-<stamp>.mp4 like
# any real clip and indistinguishable from one in a listing or in the
# Queue. Twenty had accumulated there before anyone noticed.
OUTPUT_ROOTS = (
    ("src.higgsfield", "RENDERS_ROOT", "data/renders"),
    ("src.higgsfield", "RENDER_DIR", "data/renders/higgsfield"),
    ("src.fal", "RENDERS_ROOT", "data/renders"),
    ("src.fal", "RENDER_DIR", "data/renders/fal"),
    ("src.runway", "RENDERS_ROOT", "data/renders"),
    ("src.runway", "RENDER_DIR", "data/renders/runway"),
    ("src.veo", "RENDERS_ROOT", "data/renders"),
    ("src.veo", "RENDER_DIR", "data/renders/veo"),
    ("src.nano_banana", "RENDER_DIR", "data/renders/nano"),
    ("src.orchestrator", "GENERATED_ROOT", "footage/generated"),
    ("src.autopilot", "GENERATED_DIR", "footage/generated"),
    ("src.autopilot", "KILL_SWITCH_PATH", "data/autopilot.off"),
    ("src.refbin", "REFS_DIR", "data/refs"),
    ("src.research_agent", "STAMP_DIR", "data/.research"),
    # A personal model login is a folder of session files. Registered for
    # the same reason as the rest: the first test that connects one would
    # otherwise write a real credential store into data/.
    ("src.personal_models", "SESSIONS_ROOT", "data/model_sessions"),
    ("src.promote_winners", "QUEUE_PATH", "data/promotion_queue.json"),
    ("src.db", "DB_PATH", "data/pipeline.db"),
    ("app.main", "RENDERS_DIR", "data/renders"),
    ("app.main", "UPLOAD_REFS_DIR", "data/refs"),
    ("app.main", "THUMB_DIR", "data/thumbs"),
    ("app.api", "UPLOAD_REFS_DIR", "data/refs"),
    ("ops.render_queue", "RENDERS_ROOT", "data/renders"),
    ("ops.render_queue", "RENDER_DIR", "data/renders/higgsfield"),
    ("ops.render_queue", "RUNWAY_RENDER_DIR", "data/renders/runway"),
    ("ops.bank", "PLANS_DIR", "data/idea_agent"),
)


@pytest.fixture(autouse=True)
def output_roots_in_tmp(tmp_path, monkeypatch):
    """No test writes into the real data/ or footage/ tree.

    Autouse on purpose, and the reason is the whole point: the tests that
    littered data/renders/higgsfield/ with 2048-byte stubs were not tests
    that got the redirect wrong, they were tests that never thought about
    output paths at all. An opt-in fixture is exactly the thing they would
    not have opted into. So the default is tmp_path and a module has to be
    *registered* (OUTPUT_ROOTS above) rather than remembered.

    A test that already points one of these at its own tmp dir keeps
    working: it patches the same attribute afterwards, so its value wins,
    and monkeypatch unwinds both in order.

    tests/test_output_roots.py is the other half -- it fails if a new
    output root appears that nobody added here.
    """
    root = tmp_path / "project"
    for name in ("data", "footage"):
        (root / name).mkdir(parents=True, exist_ok=True)
    for module_name, attr, relative in OUTPUT_ROOTS:
        module = importlib.import_module(module_name)
        monkeypatch.setattr(module, attr, root / relative, raising=True)
    return root


@pytest.fixture(autouse=True)
def no_spend_context():
    """The LLM meter's attribution is a contextvar (src/spend.py). A test
    that drives the orchestrator or binds one must not leave it set for
    the next test in the same worker."""
    from src import spend
    token = spend._context.set(None)
    yield
    try:
        spend._context.reset(token)
    except Exception:
        pass


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
