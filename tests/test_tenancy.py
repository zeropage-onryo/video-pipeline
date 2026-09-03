"""
Tenancy -- every owned row carries the account that owns it.

Stage one: the schema and its seed. The ownership *predicates* get their
own tests further down; what is proved here is the shape every fresh
install runs through -- init before seed, rows written unowned, the seed
claiming them -- and the two properties the locations schema has to hold
at once: two accounts can each own a place called "Garage", and one
account cannot own two.

Until 2026-09-03 this block tested a SQLite table rebuild (UNIQUE(name)
to UNIQUE(account_id, name), which SQLite could not ALTER away) and the
repair for a join table that a RENAME had rewritten to reference
`locations_old`. Both failure modes were real, both were observed on a
copy of the live database, and both are in git history. Neither can
occur on Postgres, where the final shape is simply the CREATE TABLE
(src/preprod.py), so the tests that pinned the rebuild's *mechanics*
went with it and the ones that pin its *properties* stayed, on the
throwaway Postgres (conftest's `pg`).
"""
import ast
import pathlib
import re

import psycopg
import pytest

from src import (
    account_keys,
    accounts,
    autonomy,
    db,
    entities,
    generative,
    preprod,
    render_assets,
    workflows,
)


def _one(dsn, query, args=()):
    with db.connect(dsn) as conn:
        return conn.execute(query, args).fetchone()[0]


@pytest.fixture
def unowned(pg):
    """A populated schema in the shape a database has BEFORE it is seeded:
    preprod's tables exist, rows are in them, nothing owns them yet. On
    SQLite this was a file that predated tenancy; on Postgres no such
    file can exist, but init-before-seed is still the order every fresh
    install runs in, and a row written under it is still unowned."""
    preprod.init(pg)
    with db.connect(pg) as conn:
        conn.execute("INSERT INTO locations (created_at, name) VALUES ('t', 'Garage')")
        conn.execute("INSERT INTO locations (created_at, name) VALUES ('t', 'Alley')")
        conn.execute(
            "INSERT INTO shoot_concepts (created_at, brand, title, shots_json) "
            "VALUES ('t', 'zeropage', 'A concept', '[]')"
        )
        conn.execute("INSERT INTO concept_locations (concept_id, location_id) VALUES (1, 1)")
        conn.execute("INSERT INTO concept_locations (concept_id, location_id) VALUES (1, 2)")
    return pg


@pytest.fixture
def migrated(unowned):
    accounts.seed("mike@example.com", dsn=unowned)
    preprod.init(unowned)     # idempotence is part of the contract
    return unowned


# --------------------------------------------------------------------------
# the column
# --------------------------------------------------------------------------

def test_every_owned_table_grows_an_account_id(pg):
    preprod.init(pg)
    entities.init(pg)
    generative.init(pg)
    autonomy.init(pg)
    workflows.init(pg)
    render_assets.init(pg)
    account_keys.init(pg)
    with db.connect(pg) as conn:
        for table in db.OWNED_TABLES:
            assert "account_id" in db.columns(conn, table), f"{table} has no owner"


def test_existing_rows_are_claimed_by_the_bootstrap_account(migrated):
    owner = _one(migrated, "SELECT MIN(id) FROM accounts")
    for table in ("locations", "shoot_concepts"):
        unowned = _one(migrated, f"SELECT count(*) FROM {table} WHERE account_id IS NULL")
        assert unowned == 0, f"{table} left rows with no owner"
        assert _one(
            migrated, f"SELECT count(*) FROM {table} WHERE account_id = %s", (owner,)
        ) > 0


def test_init_before_seed_leaves_rows_unowned_rather_than_guessing(unowned):
    preprod.init(unowned)
    assert _one(unowned, "SELECT count(*) FROM locations WHERE account_id IS NULL") == 2


def test_seeding_afterwards_claims_them(unowned):
    accounts.seed("mike@example.com", dsn=unowned)
    assert _one(unowned, "SELECT count(*) FROM locations WHERE account_id IS NULL") == 0


# --------------------------------------------------------------------------
# the join table
# --------------------------------------------------------------------------

def test_the_join_table_points_at_the_real_tables(migrated):
    """Both FKs name the table itself. On SQLite a rename once rewrote
    this one to `locations_old`; pinned so the shape cannot drift to
    anything that is not the real table, and so the rows are intact."""
    with db.connect(migrated) as conn:
        refs = {r[0] for r in conn.execute(
            "SELECT confrelid::regclass::text FROM pg_constraint "
            "WHERE conrelid = 'concept_locations'::regclass AND contype = 'f'"
        )}
    assert refs == {"locations", "shoot_concepts"}
    assert _one(migrated, "SELECT count(*) FROM concept_locations") == 2


def test_the_cascade_still_fires(migrated):
    with db.connect(migrated) as conn:
        conn.execute("DELETE FROM locations WHERE name = 'Alley'")
    assert _one(migrated, "SELECT count(*) FROM concept_locations") == 1


# --------------------------------------------------------------------------
# two accounts, one name
# --------------------------------------------------------------------------

def test_two_accounts_can_each_own_a_garage(migrated):
    other = _one(migrated, "SELECT id FROM accounts WHERE slug = 'antihero'")
    with db.connect(migrated) as conn:
        conn.execute(
            "INSERT INTO locations (created_at, name, account_id) VALUES ('t', 'Garage', %s)",
            (other,),
        )
    assert _one(migrated, "SELECT count(*) FROM locations WHERE name = 'Garage'") == 2


def test_one_account_still_cannot_own_two_garages(migrated):
    owner = _one(migrated, "SELECT account_id FROM locations WHERE name = 'Garage'")
    with pytest.raises(psycopg.errors.UniqueViolation):
        with db.connect(migrated) as conn:
            conn.execute(
                "INSERT INTO locations (created_at, name, account_id) VALUES ('t', 'Garage', %s)",
                (owner,),
            )


def test_ownerless_rows_still_collide_the_way_they_used_to(pg):
    """NULLs are distinct inside a UNIQUE on Postgres exactly as on SQLite:
    without the COALESCE in preprod.LOCATIONS_UNIQUE two unowned
    "hallway"s would both exist, and add_location's upsert would quietly
    stop upserting for every caller that has no account yet."""
    preprod.init(pg)
    with db.connect(pg) as conn:
        conn.execute("INSERT INTO locations (created_at, name) VALUES ('t', 'hallway')")
    with pytest.raises(psycopg.errors.UniqueViolation):
        with db.connect(pg) as conn:
            conn.execute("INSERT INTO locations (created_at, name) VALUES ('t', 'hallway')")


def test_add_location_still_upserts_by_name(pg):
    preprod.init(pg)
    first = preprod.add_location("hallway", photo_count=3, dsn=pg, account_id=None)
    again = preprod.add_location("hallway", photo_count=4, dsn=pg, account_id=None)
    assert first == again
    assert _one(pg, "SELECT count(*) FROM locations") == 1
    assert _one(pg, "SELECT photo_count FROM locations WHERE id = %s", (first,)) == 4


# --------------------------------------------------------------------------
# reads -- one account cannot see another's rows
# --------------------------------------------------------------------------

@pytest.fixture
def two_accounts(pg):
    """Two accounts, one concept, one location and one character each."""
    path = pg
    preprod.init(path)
    entities.init(path)
    generative.init(path)
    accounts.seed("mike@example.com", dsn=path)
    with db.connect(path) as conn:
        a = conn.execute("SELECT id FROM accounts WHERE slug='zeropage'").fetchone()["id"]
        b = conn.execute("SELECT id FROM accounts WHERE slug='antihero'").fetchone()["id"]
        for owner, tag in ((a, "A"), (b, "B")):
            conn.execute(
                "INSERT INTO shoot_concepts (created_at, brand, title, shots_json, "
                "account_id) VALUES ('t', 'zeropage', %s, '[]', %s)", (f"{tag} concept", owner))
            conn.execute(
                "INSERT INTO locations (created_at, name, account_id) VALUES ('t', %s, %s)",
                (f"{tag} place", owner))
            conn.execute(
                "INSERT INTO characters (name, created_at, account_id) VALUES (%s, 't', %s)",
                (f"{tag} person", owner))
    return path, a, b


def test_a_list_returns_only_your_own(two_accounts):
    path, a, b = two_accounts
    assert [c["title"] for c in preprod.list_concepts(dsn=path, account_id=a)] == ["A concept"]
    assert [c["title"] for c in preprod.list_concepts(dsn=path, account_id=b)] == ["B concept"]


def test_fetching_someone_elses_concept_by_id_is_indistinguishable_from_missing(two_accounts):
    """Ids are sequential integers. If "not yours" answered differently
    from "no such row", counting from 1 would map the whole table."""
    path, a, b = two_accounts
    theirs = preprod.list_concepts(dsn=path, account_id=b)[0]["id"]
    assert preprod.get_concept(theirs, dsn=path, account_id=a) is None
    assert preprod.get_concept(999_999, dsn=path, account_id=a) is None
    assert preprod.get_concept(theirs, dsn=path, account_id=b) is not None


def test_locations_and_cast_are_scoped_too(two_accounts):
    path, a, b = two_accounts
    assert [x["name"] for x in preprod.list_locations(dsn=path, account_id=a)] == ["A place"]
    assert [x["name"] for x in entities.list_characters(dsn=path, account_id=b)] == ["B person"]
    theirs = entities.list_characters(dsn=path, account_id=b)[0]["id"]
    assert entities.get_character(theirs, dsn=path, account_id=a) is None


def test_counts_do_not_leak_how_much_work_the_other_account_has_done(two_accounts):
    path, a, b = two_accounts
    assert preprod.summary(dsn=path, account_id=a) == {"locations": 1, "shoot_concepts": 1}
    assert entities.summary(dsn=path, account_id=b) == {"characters": 1, "props": 0}


def test_the_unowned_pool_is_its_own_scope(two_accounts):
    """account_id=None addresses rows that predate tenancy. It must not
    be a skeleton key onto everybody's."""
    path, a, b = two_accounts
    assert preprod.list_concepts(dsn=path, account_id=None) == []


# --------------------------------------------------------------------------
# writes -- ownership is stamped on create and checked on mutate
# --------------------------------------------------------------------------

def test_a_new_concept_is_stamped_with_its_creator(two_accounts):
    path, a, b = two_accounts
    new_id = preprod.save_concept(
        {"title": "Mine", "shots": []}, brand="zeropage", dsn=path, account_id=a)
    assert preprod.get_concept(new_id, dsn=path, account_id=a)["title"] == "Mine"
    assert preprod.get_concept(new_id, dsn=path, account_id=b) is None


def test_you_cannot_mutate_someone_elses_concept(two_accounts):
    """set_picked already raised "no concept N" on a rowcount of 0, and
    with the owner in the WHERE clause that now covers "not yours" too --
    which is the right error, because it is the same one a genuinely
    missing id gives. The mutation must not land either way."""
    path, a, b = two_accounts
    theirs = preprod.list_concepts(dsn=path, account_id=b)[0]["id"]
    with pytest.raises(ValueError):
        preprod.set_picked(theirs, True, dsn=path, account_id=a)
    assert preprod.get_concept(theirs, dsn=path, account_id=b)["picked_at"] is None

    preprod.set_picked(theirs, True, dsn=path, account_id=b)
    assert preprod.get_concept(theirs, dsn=path, account_id=b)["picked_at"] is not None


def test_you_cannot_delete_someone_elses_concept(two_accounts):
    path, a, b = two_accounts
    theirs = preprod.list_concepts(dsn=path, account_id=b)[0]["id"]
    preprod.delete_concept(theirs, dsn=path, account_id=a)
    assert preprod.get_concept(theirs, dsn=path, account_id=b) is not None


def test_clearing_the_slate_clears_only_your_own(two_accounts):
    """This one used to be `DELETE FROM shoot_concepts` with no argument."""
    path, a, b = two_accounts
    removed = preprod.delete_all_concepts(dsn=path, account_id=a)
    assert removed == 1
    assert preprod.list_concepts(dsn=path, account_id=a) == []
    assert len(preprod.list_concepts(dsn=path, account_id=b)) == 1


def test_a_concept_cannot_be_pinned_to_someone_elses_location(two_accounts):
    """location_ids arrives from a request. Without the ownership check
    a guessed integer links your concept to a stranger's room -- and the
    concept card would then render its name."""
    path, a, b = two_accounts
    theirs = preprod.list_locations(dsn=path, account_id=b)[0]["id"]
    mine = preprod.save_concept(
        {"title": "Borrowed", "shots": []}, brand="zeropage",
        location_ids=[theirs], dsn=path, account_id=a)
    assert preprod.get_concept(mine, dsn=path, account_id=a)["locations"] == []


def test_cast_and_props_are_stamped_and_checked(two_accounts):
    path, a, b = two_accounts
    cid = entities.add_character("Rider", dsn=path, account_id=a)
    assert entities.get_character(cid, dsn=path, account_id=b) is None
    entities.delete_character(cid, dsn=path, account_id=b)
    assert entities.get_character(cid, dsn=path, account_id=a) is not None


# --------------------------------------------------------------------------
# caps -- your renders are not billed to their day, and neither is the card
# --------------------------------------------------------------------------

def _log_render(path, account_id, tool="runway", n=1):
    from src.shot import Shot
    shot_id = generative.add_shot(
        Shot(subject="a bike", action="idles"), dsn=path, account_id=account_id)
    for _ in range(n):
        generative.record_generation(
            shot_id, tool, "a prompt", dsn=path, account_id=account_id)


def test_one_accounts_renders_do_not_count_against_anothers_cap(two_accounts):
    path, a, b = two_accounts
    _log_render(path, a, n=3)
    assert generative.used_today("runway", path, account_id=a) == 3
    assert generative.used_today("runway", path, account_id=b) == 0


def test_the_per_account_cap_refuses_before_the_ceiling_does(two_accounts):
    path, a, _b = two_accounts
    _log_render(path, a, n=2)
    refusal = generative.cap_error(
        "runway", 1, account_id=a, per_account=2, ceiling=99,
        dsn=path, env_prefix="RUNWAY")
    assert refusal is not None and "daily cap" in refusal


def test_the_global_ceiling_catches_what_per_account_caps_cannot(two_accounts):
    """Two accounts, each comfortably inside its own cap, together over
    the ceiling. Per-account limits alone are ten pilot users times six
    renders on one card, every one of them within their rights."""
    path, a, b = two_accounts
    _log_render(path, a, n=3)
    _log_render(path, b, n=3)
    assert generative.cap_error("runway", 1, account_id=a, per_account=10,
                                ceiling=99, dsn=path, env_prefix="RUNWAY") is None
    refusal = generative.cap_error("runway", 1, account_id=a, per_account=10,
                                   ceiling=6, dsn=path, env_prefix="RUNWAY")
    assert refusal is not None and "daily ceiling" in refusal


def test_a_generation_cannot_be_logged_against_someone_elses_shot(two_accounts):
    from src.shot import Shot
    path, a, b = two_accounts
    shot_id = generative.add_shot(
        Shot(subject="a bike", action="idles"), dsn=path, account_id=a)
    with pytest.raises(ValueError):
        generative.record_generation(
            shot_id, "runway", "a prompt", dsn=path, account_id=b)


# --------------------------------------------------------------------------
# the regression test: no unscoped read survives review
# --------------------------------------------------------------------------

# Statements that legitimately touch an owned table without an owner
# predicate. Each needs a reason, and the reason has to be about the
# statement, not about convenience.
UNSCOPED_ALLOWED = {
    # db.own_table's own backfill: the statement that CREATES ownership
    "SET account_id = %s WHERE account_id IS NULL",
    # concept_locations is reached only through an owned concept, and its
    # rows cascade with one -- it has no account_id of its own by design
    "FROM concept_locations",
    "INTO concept_locations",
    "DELETE FROM concept_locations",
    # the global ceiling in generative.used_today(everyone=True). The one
    # query in the codebase that is SUPPOSED to count every account: it is
    # what stops ten pilot users, each inside their own cap, from putting
    # sixty renders on one card.
    "SELECT COUNT(*) FROM generations WHERE tool = %s AND created_at >= %s",
    # assembled in pieces: the owner predicate lives in a different
    # literal from the one that names the table, so the scan cannot see
    # them together. Both are checked by tests of their own --
    # test_a_list_returns_only_your_own and the videos scoping tests.
    "SELECT * FROM videos",
    "ROW_NUMBER()",
    # a channel's rate cap is on what reaches the DESTINATION per day,
    # whoever filed the run -- channels are the installation's
    # (db.SHARED_TABLES), so this count is meant to span every account
    "SELECT COUNT(*) FROM hold_queue WHERE channel = %s AND status = 'posted'",
    # autonomy.init's one-time rename of the personal channel: a migration
    "UPDATE hold_queue SET channel='antihero'",
    # workflows.seed_default's idempotence checks: an installation-level
    # seed asking whether the starter canvas exists at all
    "SELECT id FROM workflows WHERE name = %s",
    "SELECT id FROM workflows LIMIT 1",
}

# Built from the list, not written out beside it: adding a table to
# db.OWNED_TABLES is what puts it under this test. hold_queue and
# workflows were owned in every sense that mattered and on the list in
# none, and this regex used to be the only place the list was repeated.
OWNED_RE = re.compile(
    r"\b(?:FROM|JOIN|UPDATE|INTO)\s+(" + "|".join(db.OWNED_TABLES) + r")\b",
    re.I,
)


def _flatten(node):
    """The text of a string literal, an f-string, or the two concatenated.

    An f-string is a JoinedStr whose pieces are separate Constants, so
    reading only Constants splits `f"INSERT INTO x SELECT {cols} FROM y"`
    into fragments and reports half a statement. Placeholders become
    `{}` -- enough to keep the SQL readable without pretending to know
    what they expand to.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            v.value if isinstance(v, ast.Constant) and isinstance(v.value, str) else "{}"
            for v in node.values
        )
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _flatten(node.left), _flatten(node.right)
        if left is not None and right is not None:
            return left + right
    return None


def _docstrings(tree):
    """Prose is not SQL. shootgen's stage-two docstring says "into shots"."""
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc:
                out.add(doc)
    return out


def _sql_literals(path):
    """Every string in a module that looks like a statement, not prose."""
    tree = ast.parse(pathlib.Path(path).read_text())
    docs = _docstrings(tree)
    # An f-string's pieces are Constants in their own right, so walking
    # everything reports `" FROM locations"` on its own and misses that
    # the whole statement says `INSERT INTO locations_new ... FROM
    # locations`. Read the JoinedStr, skip its parts.
    inside_fstring = {
        id(part)
        for node in ast.walk(tree) if isinstance(node, ast.JoinedStr)
        for part in ast.walk(node) if part is not node
    }
    seen = set()
    for node in ast.walk(tree):
        if id(node) in inside_fstring:
            continue
        text = _flatten(node)
        if text is None or text in docs:
            continue
        if not OWNED_RE.search(text):
            continue
        key = (node.lineno, text)
        if key in seen:
            continue
        seen.add(key)
        yield node.lineno, " ".join(text.split())


def test_no_query_against_an_owned_table_forgets_its_owner():
    """The test that would have caught this whole class of bug.

    `list_concepts` was `SELECT * FROM shoot_concepts ORDER BY id DESC
    LIMIT %s` for as long as there was only one user, and nothing failed,
    because nothing was wrong yet. This fails the moment a new query
    reaches an owned table without saying whose rows it wants.
    """
    offenders = []
    root = pathlib.Path(__file__).resolve().parent.parent
    modules = (sorted((root / "src").glob("*.py"))
               + sorted((root / "app").glob("*.py"))
               + sorted((root / "ops").glob("*.py")))
    for module in modules:
        for lineno, sql in _sql_literals(module):
            if "account_id" in sql:
                continue
            if any(allowed.lower() in sql.lower() for allowed in UNSCOPED_ALLOWED):
                continue
            offenders.append(f"{module.relative_to(root)}:{lineno}  {sql[:90]}")
    assert not offenders, (
        "these statements touch an owned table with no account_id predicate:\n  "
        + "\n  ".join(offenders)
    )


# --------------------------------------------------------------------------
# the tenant is not the brand
# --------------------------------------------------------------------------

def test_the_brand_pill_does_not_empty_the_board(two_accounts, monkeypatch):
    """The bug this closes, found by running the migration against a copy
    of the live database rather than by reading the code.

    `accounts` is doing double duty: zeropage and antihero are two
    brands, and they are also two account rows Mike is a member of.
    auth.current_account reads the brand cookie and returns the matching
    membership -- that is what the pill switches and what colours the UI.
    Scope the DATA by that and clicking ANTIHERO scopes every query to
    account 2, which the backfill gave nothing: an empty board, no
    locations, no cast, on a database with eleven concepts in it.

    So current_account_id returns the tenant (oldest membership) and the
    pill goes on filtering by brand inside it.
    """
    from app import auth

    path, a, b = two_accounts
    with db.connect(path) as conn:
        user_id = conn.execute(
            "SELECT user_id FROM account_members ORDER BY account_id"
        ).fetchone()["user_id"]
        # both concepts to the tenant, the way the backfill leaves them
        conn.execute("UPDATE shoot_concepts SET account_id = %s", (a,))

    monkeypatch.setattr(auth, "current_user", lambda request: {"id": user_id})
    monkeypatch.setenv("DATABASE_URL", path)

    class Request:
        def __init__(self, brand):
            self.cookies = {"brand": brand}

    for brand in ("zeropage", "antihero"):
        scoped_to = auth.current_account_id(Request(brand))
        assert scoped_to == a, f"the {brand} pill switched tenants"
        assert len(preprod.list_concepts(dsn=path, account_id=scoped_to)) == 2


def test_the_brand_pill_does_not_empty_the_dev_console(two_accounts, monkeypatch):
    """The same rule, for the other door (2026-09-02).

    dev_account_id resolved the BRAND, not the tenant, so with the pill
    on ANTIHERO the Dev Studio scoped itself to the account the backfill
    gave nothing: "Draw ungraded concept (0)" against 29 concepts, and
    the board's taste signal reading zero.

    The half that would have cost data rather than a confusing page:
    four dev routes write (fresh grade, new video, metrics, reference
    pick), and a write made under the wrong pill lands on an account the
    board and the judge never read."""
    from app import auth

    path, a, _b = two_accounts
    with db.connect(path) as conn:
        user_id = conn.execute(
            "SELECT user_id FROM account_members ORDER BY account_id"
        ).fetchone()["user_id"]
        conn.execute("UPDATE shoot_concepts SET account_id = %s", (a,))

    monkeypatch.setattr(auth, "current_user", lambda request: {"id": user_id})
    monkeypatch.setenv("DATABASE_URL", path)

    class Request:
        def __init__(self, brand):
            self.cookies = {"brand": brand}

    for brand in ("zeropage", "antihero"):
        assert auth.dev_account_id(Request(brand)) == a, f"the {brand} pill switched tenants"
        # and it agrees with the door /api comes through
        assert auth.dev_account_id(Request(brand)) == auth.current_account_id(Request(brand))


def test_the_dev_console_still_works_with_no_session(two_accounts, monkeypatch):
    """The fallback is the one thing that stays different from
    current_account_id: the engine room has never required a cookie, and
    a 403 there locks Mike out of his own workshop."""
    from app import auth

    path, a, _b = two_accounts
    monkeypatch.setattr(auth, "current_user", lambda request: None)
    monkeypatch.setenv("DATABASE_URL", path)

    class Request:
        cookies: dict = {}

    assert auth.dev_account_id(Request()) == a


def test_a_user_with_no_membership_is_refused_not_defaulted(monkeypatch, pg):
    """Signing in is not the same as having access -- a fresh signup gets
    zero account_members rows on purpose. That has to be a 403, not a
    fall-through to whichever account happens to be first."""
    from fastapi import HTTPException

    from app import auth

    path = pg
    accounts.init(path)
    uid = accounts.create_user("stranger@example.com", dsn=path)

    monkeypatch.setattr(auth, "current_user", lambda request: {"id": uid})
    monkeypatch.setenv("DATABASE_URL", path)

    class Request:
        cookies: dict = {}

    with pytest.raises(HTTPException) as raised:
        auth.current_account_id(Request())
    assert raised.value.status_code == 403


def test_an_entry_point_with_no_session_acts_as_the_bootstrap_account(two_accounts):
    """CLIs, the nightly graph and the MCP surface have no cookie. After
    the backfill "nobody" owns nothing, so defaulting to None would make
    a night's work vanish rather than fail."""
    path, a, _b = two_accounts
    assert accounts.resolve_account(dsn=path) == a
    assert accounts.resolve_account("antihero", dsn=path) != a
    with pytest.raises(ValueError):
        accounts.resolve_account("nosuchbrand", dsn=path)


def test_resolve_account_on_a_fresh_database_is_the_unowned_pool(pg):
    assert accounts.resolve_account(dsn=pg) is None


def test_resolve_account_before_the_table_exists_is_not_a_crash(pg):
    """A database that predates accounts.init() is a fresh install, not an
    error. This raised sqlite3.OperationalError("no such table: accounts")
    until a full-suite run scheduled the mcp_server tests onto a worker
    whose database had never been seeded -- the two-halves runs never put
    them there, so it hid."""
    # db.init_db creates the accounts table itself now (the FK target
    # has to exist), so the table-less state is made, not found
    with db.connect(pg) as conn:
        conn.execute("DROP TABLE accounts CASCADE")
    assert accounts.resolve_account(dsn=pg) is None
    with pytest.raises(ValueError):
        accounts.resolve_account("zeropage", dsn=pg)


# --------------------------------------------------------------------------
# inviting a pilot user
# --------------------------------------------------------------------------

def test_an_invite_gives_them_their_own_account_not_yours(two_accounts):
    """The whole point, and the easy thing to get catastrophically wrong:
    a pilot user needs a workspace, not a membership in Mike's."""
    path, a, _b = two_accounts
    result = accounts.invite("alex@example.com", "alex", dsn=path)

    assert result["created_user"] and result["created_account"]
    assert result["account_id"] not in (a, _b)
    # their board is empty, and Mike's is untouched
    assert preprod.list_concepts(dsn=path, account_id=result["account_id"]) == []
    assert len(preprod.list_concepts(dsn=path, account_id=a)) == 1


def test_inviting_someone_into_an_account_that_owns_rows_is_refused(two_accounts):
    """`--brand zeropage` would not give them a workspace, it would give
    them Mike's board. The error has to say how much."""
    path, _a, _b = two_accounts
    with pytest.raises(ValueError) as raised:
        accounts.invite("alex@example.com", "zeropage", dsn=path)
    assert "owns" in str(raised.value)
    assert "join_existing" in str(raised.value)


def test_sharing_a_workspace_is_possible_but_has_to_be_asked_for(two_accounts):
    path, a, _b = two_accounts
    result = accounts.invite("alex@example.com", "zeropage",
                             join_existing=True, dsn=path)
    assert result["account_id"] == a


def test_the_invited_row_is_unclaimed_so_the_first_sign_in_can_take_it(two_accounts):
    """accounts.claim takes an unclaimed row by email on the first
    Supabase sign-in, and the membership follows the row's new id
    (ON UPDATE CASCADE). That is what makes an invite complete before
    the person has ever visited -- and why there is no secret to send."""
    path, _a, _b = two_accounts
    invited = accounts.invite("alex@example.com", "alex", dsn=path)
    user = accounts.get_user_by_email("alex@example.com", dsn=path)
    assert user["claimed_at"] is None and "password_hash" not in user
    uid, error = accounts.claim("supabase-uuid-alex", "alex@example.com", "Alex", None,
                                dsn=path)
    assert error is None and uid == "supabase-uuid-alex"
    assert accounts.get_user_by_email("alex@example.com", dsn=path)["claimed_at"]
    assert [m["id"] for m in accounts.memberships(uid, dsn=path)] == [invited["account_id"]]


def test_inviting_the_same_person_twice_is_not_an_error(two_accounts):
    path, _a, _b = two_accounts
    first = accounts.invite("alex@example.com", "alex", dsn=path)
    again = accounts.invite("alex@example.com", "alex", dsn=path)
    assert again["user_id"] == first["user_id"]
    assert again["account_id"] == first["account_id"]
    assert not again["created_user"] and not again["created_account"]
    assert len(accounts.memberships(first["user_id"], dsn=path)) == 1


def test_an_invite_needs_a_plausible_email_and_a_slug(two_accounts):
    path, _a, _b = two_accounts
    for bad_email in ("", "   ", "not-an-email"):
        with pytest.raises(ValueError):
            accounts.invite(bad_email, "alex", dsn=path)
    with pytest.raises(ValueError):
        accounts.invite("alex@example.com", "  ", dsn=path)


# --------------------------------------------------------------------------
# the dry run's leaks (docs/PILOT_DRY_RUN.md, 2026-09-02): the tables
# tenancy never listed, the routes that never declared an owner, and the
# job registry that had none
# --------------------------------------------------------------------------

# /api routes that legitimately take no account. Each one has to be about
# the installation, not about anybody's rows, and cheap enough that a
# signed-in stranger reading it costs nothing. Everything else declares
# `Depends(auth.current_account_id)` -- the parameter the handler cannot
# use without declaring -- or this test fails.
ROUTES_WITHOUT_AN_ACCOUNT = {
    # what the shell may render: key presence and store reachability,
    # derived live; nothing owned is read and the answer is the same
    # for every caller. The shell asks before any account resolves.
    ("GET", "/api/capabilities"),
    # prompts/presets.json and prompts/enhance_system.txt, straight off
    # disk -- repo content, the same bytes for everyone
    ("GET", "/api/presets"),
}


def _api_routes():
    from fastapi.routing import APIRoute

    from app import api as api_mod
    return [r for r in api_mod.router.routes if isinstance(r, APIRoute)]


def _declares_account(endpoint) -> bool:
    import inspect

    from fastapi import params

    from app import auth
    return any(
        isinstance(p.default, params.Depends)
        and p.default.dependency is auth.current_account_id
        for p in inspect.signature(endpoint).parameters.values()
    )


def test_every_api_route_declares_whose_rows_it_wants():
    """The test that would have caught all three tables at once.

    The static SQL test audits db.OWNED_TABLES, so a table missing from
    the list is invisible to it; this one audits the routes instead. A
    signed-in user with zero memberships -- the state a Google sign-up
    lands in -- is stopped by current_account_id and by nothing else,
    so a route that does not declare it is a route that serves them
    whatever it serves. The dry run walked /api/holds, /api/workflows
    and /api/jobs exactly that way.
    """
    offenders, stale = [], []
    seen = set()
    for route in _api_routes():
        for method in sorted(route.methods or ()):
            key = (method, route.path)
            seen.add(key)
            if key in ROUTES_WITHOUT_AN_ACCOUNT:
                continue
            if not _declares_account(route.endpoint):
                offenders.append(f"{method:6} {route.path}  ({route.endpoint.__name__})")
    stale = sorted(k for k in ROUTES_WITHOUT_AN_ACCOUNT if k not in seen)
    assert not offenders, (
        "these /api routes take no account -- a signed-in stranger reaches them:\n  "
        + "\n  ".join(offenders))
    assert not stale, f"exempt list names routes that no longer exist: {stale}"


def _init_everything(path):
    """Every init the app lifespan runs, plus the CLI-only ones, so the
    schema under test is the whole schema."""
    from src import (
        evalstore,
        framebank,
        imagesearch,
        inspiration,
        instagram,
        scheduling,
        scout,
        settings,
        winners,
    )
    db.init_db(path)
    preprod.init(path)
    entities.init(path)
    autonomy.init(path)
    winners.init(path)
    inspiration.init(path)
    evalstore.init(path)
    workflows.init(path)
    generative.init(path)
    accounts.init(path)
    settings.init(path)
    scheduling.init(path)
    scout.init(path)
    instagram.init(path)
    imagesearch.init(path)
    framebank.init(path)
    render_assets.init(path)
    account_keys.init(path)


AUTH_SCHEMA = {"users", "accounts", "account_members"}


def test_every_table_is_owned_or_declared_shared(pg):
    """BACKLOG #11's first bullet, as a test: the learning tables are
    global BY DECISION, and writing the decision down is what stops a
    future session reading twenty unscoped tables next to a tenancy
    suite and "finishing the migration". A table on neither list is a
    table nobody decided about."""
    path = pg
    _init_everything(path)
    with db.connect(path) as conn:
        tables = {r["name"] for r in conn.execute(
            "SELECT table_name AS name FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_type = 'BASE TABLE'")}
        undecided = sorted(tables - set(db.OWNED_TABLES) - set(db.SHARED_TABLES))
        assert not undecided, (
            "tables that are neither owned nor declared shared (with a reason) "
            f"in db.SHARED_TABLES: {undecided}")
        both = sorted(set(db.OWNED_TABLES) & set(db.SHARED_TABLES))
        assert not both, f"a table cannot be both owned and shared: {both}"
        gone = sorted(set(db.SHARED_TABLES) - tables)
        assert not gone, f"SHARED_TABLES names tables that do not exist: {gone}"
        for table in db.OWNED_TABLES:
            cols = db.columns(conn, table)
            assert "account_id" in cols, f"{table} is listed as owned but has no owner column"
        for table, reason in db.SHARED_TABLES.items():
            assert reason.strip(), f"{table} is shared with no reason written down"
            if table in AUTH_SCHEMA:
                continue     # account_members.account_id is the grant, not an owner
            cols = db.columns(conn, table)
            assert "account_id" not in cols, (
                f"{table} has an account_id column but is declared shared -- decide")


def test_existing_holds_and_canvases_are_claimed_by_the_bootstrap_account(pg):
    """The two tables the dry run found off the owned list (holds and
    canvases) take the same path as locations above: init before seed,
    rows written unowned, the seed claims them, and a second init
    neither re-claims nor loses anything."""
    autonomy.init(pg)
    workflows.init(pg)
    with db.connect(pg) as conn:
        conn.execute("INSERT INTO hold_queue (created_at, channel) VALUES ('t', 'zeropage')")
        conn.execute("INSERT INTO hold_queue (created_at, channel, status) "
                     "VALUES ('t', 'antihero', 'posted')")
        conn.execute("INSERT INTO workflows (created_at, updated_at, name, graph_json) "
                     "VALUES ('t', 't', 'Midnight Evasion', '{}')")
    assert _one(pg, "SELECT count(*) FROM hold_queue WHERE account_id IS NULL") == 2
    assert _one(pg, "SELECT count(*) FROM workflows WHERE account_id IS NULL") == 1

    accounts.seed("mike@example.com", dsn=pg)
    owner = _one(pg, "SELECT MIN(id) FROM accounts")
    assert _one(pg, "SELECT count(*) FROM hold_queue WHERE account_id = %s", (owner,)) == 2
    assert _one(pg, "SELECT count(*) FROM workflows WHERE account_id = %s", (owner,)) == 1
    assert _one(pg, "SELECT name FROM workflows") == "Midnight Evasion"
    autonomy.init(pg)          # idempotent, and nothing re-claimed or lost
    workflows.init(pg)
    assert _one(pg, "SELECT count(*) FROM hold_queue") == 2


@pytest.fixture
def two_tenants(two_accounts, monkeypatch):
    """two_accounts plus a hold, a canvas and a running job each, the
    app pointed at that database, and a way to make a request as either
    account or as a signed-in user with no membership at all."""
    from fastapi.testclient import TestClient

    import app.main as app_main
    from app import auth, jobs

    path, a, b = two_accounts
    autonomy.init(path)
    workflows.init(path)
    monkeypatch.setenv("DATABASE_URL", path)
    jobs.clear_all_for_tests()

    holds = {owner: autonomy.to_hold("zeropage", f"{tag} run", dsn=path, account_id=owner)
             for owner, tag in ((a, "A"), (b, "B"))}
    canvases = {owner: workflows.create_workflow(f"{tag} canvas", {"nodes": [{"id": 1}]},
                                                 dsn=path, account_id=owner)
                for owner, tag in ((a, "A"), (b, "B"))}
    running = {owner: jobs.create("render", f"{tag}'s private render", account_id=owner)
               for owner, tag in ((a, "A"), (b, "B"))}

    client = TestClient(app_main.app)

    def act_as(account_id):
        # a session for the router-level gate; the tenant is the override
        monkeypatch.setattr(auth, "current_user",
                            lambda request: {"id": 1, "email": "member@example.com"})
        app_main.app.dependency_overrides[auth.current_account_id] = lambda: account_id
        return client

    def nobody():
        """Signed in, zero memberships: the real dependency runs and
        must refuse, because nothing else will."""
        app_main.app.dependency_overrides.pop(auth.current_account_id, None)
        uid = accounts.create_user("stranger@example.com", dsn=path)
        monkeypatch.setattr(auth, "current_user", lambda request: {"id": uid})
        return client

    yield {"path": path, "a": a, "b": b, "holds": holds, "canvases": canvases,
           "jobs": running, "as": act_as, "nobody": nobody}
    jobs.clear_all_for_tests()


def test_a_stranger_cannot_read_or_grade_your_holds(two_tenants):
    """Proven as the pilot in the dry run: hold 38 went held -> rejected."""
    t = two_tenants
    client = t["as"](t["b"])
    listed = client.get("/api/holds").json()["items"]
    assert [h["id"] for h in listed] == [t["holds"][t["b"]]]

    theirs = t["holds"][t["a"]]
    res = client.post(f"/api/holds/{theirs}/resolve", json={"status": "rejected"})
    assert res.status_code == 404
    assert autonomy.get_hold(theirs, dsn=t["path"], account_id=t["a"])["status"] == "held"
    # your own still works, and the grade lands on YOUR agreement number
    mine = t["holds"][t["b"]]
    assert client.post(f"/api/holds/{mine}/resolve",
                       json={"status": "approved"}).status_code == 200
    assert client.get("/api/holds").json()["agreement"]["graded"] == 1
    assert t["as"](t["a"]).get("/api/holds").json()["agreement"]["graded"] == 0


def test_post_now_takes_an_owner_and_never_reaches_the_gate_for_a_stranger(
        two_tenants, monkeypatch):
    """`def holds_post(hold_id)` -- no account of any kind -- was the
    finding that blocks the invite. Someone else's hold is a 404 and
    autopilot.execute is never called."""
    from app import api as api_mod
    t = two_tenants

    def never(*args, **kwargs):
        raise AssertionError("autopilot.execute reached for someone else's hold")
    monkeypatch.setattr(api_mod.autopilot, "execute", never)

    res = t["as"](t["b"]).post(f"/api/holds/{t['holds'][t['a']]}/post")
    assert res.status_code == 404


def test_posting_needs_the_per_run_approval_even_for_the_owner(two_tenants, tmp_path, monkeypatch):
    """The three standing switches are about the installation; the
    per-run yes is ZEROPAGE_POST_OK, in the render tools' SPEND_OK
    shape. Without it a live plan that would post reports so and
    publishes nothing, and no executor is ever entered."""
    from src import autopilot
    monkeypatch.setenv(autopilot.ENABLE_ENV, "1")
    monkeypatch.delenv(autopilot.POST_ENV, raising=False)
    monkeypatch.setattr(autopilot, "KILL_SWITCH_PATH", tmp_path / "off")
    fired = []
    monkeypatch.setattr(autopilot, "EXECUTORS",
                        {"post": lambda a: fired.append(a), "generate": lambda a: fired.append(a)})
    plan = {"actions": [{"kind": "generate", "tool": "veo", "prompt": "p"},
                        {"kind": "post", "platform": "instagram", "caption": "c"}]}
    result = autopilot.execute(plan, approve=True, dry_run=False)
    assert result["mode"] == "post-unapproved"
    assert result["executed"] == 0 and fired == []
    # and the executor itself is a wall, not just the mode
    with pytest.raises(RuntimeError, match=autopilot.POST_ENV):
        autopilot._post_dispatch({"kind": "post", "platform": "instagram"})
    monkeypatch.setenv(autopilot.POST_ENV, "1")
    assert autopilot.execute(plan, approve=True, dry_run=False)["mode"] == "live"
    assert len(fired) == 2


def test_a_stranger_cannot_see_or_destroy_your_canvases(two_tenants):
    """Workflow 3, "Midnight Evasion", is not in the dry run's copy any
    more. A shot's saved graph carries its outputs, so that deleted
    the record of paid renders."""
    t = two_tenants
    client = t["as"](t["b"])
    theirs, mine = t["canvases"][t["a"]], t["canvases"][t["b"]]
    assert [w["id"] for w in client.get("/api/workflows").json()["items"]] == [mine]
    assert client.get(f"/api/workflows/{theirs}").status_code == 404
    assert client.put(f"/api/workflows/{theirs}", json={"name": "overwritten"}).status_code == 404
    assert client.delete(f"/api/workflows/{theirs}").status_code == 404
    assert client.post(f"/api/workflows/{theirs}/run").status_code == 404
    survivor = workflows.get_workflow(theirs, dsn=t["path"], account_id=t["a"])
    assert survivor is not None and survivor["name"] == "A canvas"
    # brand is a label inside the tenant, never a way across it
    assert [w["id"] for w in
            client.get("/api/workflows?brand=zeropage").json()["items"]] == [mine]


def test_a_stranger_cannot_reset_the_canvases_of_your_concept(two_tenants):
    """DELETE /api/concepts/{id}/graph took no account at all."""
    t = two_tenants
    with db.connect(t["path"]) as conn:
        theirs = conn.execute("SELECT id FROM shoot_concepts WHERE account_id = %s",
                              (t["a"],)).fetchone()["id"]
    workflows.save_shot_graph(theirs, 1, {"nodes": [{"id": 1}]}, dsn=t["path"],
                              account_id=t["a"])
    assert t["as"](t["b"]).delete(f"/api/concepts/{theirs}/graph").status_code == 404
    assert workflows.get_shot_graph(theirs, 1, dsn=t["path"], account_id=t["a"]) is not None
    assert t["as"](t["a"]).delete(f"/api/concepts/{theirs}/graph").json()["removed"] == 1


def test_jobs_are_attributed_and_private(two_tenants):
    """The pilot saw a job labelled "Mike's private render" and got 200
    from its cancel. In-memory is fine; unattributed is not."""
    from app import jobs
    t = two_tenants
    client = t["as"](t["b"])
    theirs, mine = t["jobs"][t["a"]]["id"], t["jobs"][t["b"]]["id"]
    assert [j["id"] for j in client.get("/api/jobs").json()["items"]] == [mine]
    assert client.get(f"/api/jobs/{theirs}").status_code == 404
    assert client.post(f"/api/jobs/{theirs}/cancel").status_code == 404
    assert client.delete(f"/api/jobs/{theirs}").status_code == 404
    assert jobs.get(theirs, account_id=t["a"])["status"] == "queued"   # untouched
    # the stream's filter is the same predicate the routes use
    assert jobs.owned_by(jobs.get(theirs, account_id=t["a"]), t["b"]) is False
    assert jobs.owned_by(jobs.get(theirs, account_id=t["a"]), t["a"]) is True
    assert [j["id"] for j in jobs.list_jobs(account_id=t["b"])] == [mine]


def test_signed_in_with_no_membership_is_refused_everywhere(two_tenants):
    """The state a Google sign-up lands in. The dry run's table: /api/assets
    403 (correct) beside /api/holds, /api/workflows, /api/jobs 200."""
    t = two_tenants
    client = t["nobody"]()
    for path in ("/api/holds", "/api/workflows", "/api/jobs", "/api/evals/golden",
                 "/api/evals/runs", "/api/director/landing", "/api/analytics/accounts",
                 f"/api/workflows/{t['canvases'][t['a']]}",
                 f"/api/jobs/{t['jobs'][t['a']]['id']}"):
        assert client.get(path).status_code == 403, path
    theirs = t["holds"][t["a"]]
    assert client.post(f"/api/holds/{theirs}/resolve", json={"status": "rejected"}).status_code == 403
    assert client.post(f"/api/holds/{theirs}/post").status_code == 403
    assert client.delete(f"/api/workflows/{t['canvases'][t['a']]}").status_code == 403
    assert client.post(f"/api/jobs/{t['jobs'][t['a']]['id']}/cancel").status_code == 403
    assert autonomy.get_hold(theirs, dsn=t["path"], account_id=t["a"])["status"] == "held"


# --------------------------------------------------------------------------
# the two numbers
# --------------------------------------------------------------------------

def test_veo_has_the_same_spend_gate_as_every_other_paid_tool(tmp_path, monkeypatch):
    """estimate_cost(6) is $19.20 -- the most expensive tool in the repo
    was the only one with no per-run approval."""
    from src import runway, veo
    assert veo.SPEND_ENV == "VEO_SPEND_OK"
    assert veo.spend_approved.__doc__ and runway.spend_approved.__doc__
    monkeypatch.delenv(veo.SPEND_ENV, raising=False)

    class Untouchable:
        def __getattr__(self, name):
            raise AssertionError("the SDK was reached with no spend approval")

    with pytest.raises(RuntimeError, match="VEO_SPEND_OK"):
        veo.generate_video("x", tmp_path / "c.mp4", client=Untouchable())
    result = veo.generate_candidates("x", tmp_path / "out", n=6,
                                     db_path=tmp_path / "v.db", client=Untouchable())
    assert result["ok"] is False
    assert "VEO_SPEND_OK" in result["error"] and "$19.2" in result["error"]


def test_the_global_caps_are_set_deliberately_in_the_example_env():
    """Every global defaults to its per-account cap, which is right for
    one operator and wrong for two: the first person to render each
    day ends the day for everyone. .env.example carries the decision
    -- (per-account cap x people) -- so a deployment copies a ceiling
    that was chosen, not the one-operator default."""
    from src import higgsfield, midjourney, nano_banana, runway, veo
    text = (pathlib.Path(__file__).resolve().parent.parent / ".env.example").read_text()
    values = dict(re.findall(r"^([A-Z_]+_GLOBAL_DAILY_CAP)=(\d+)", text, re.M))
    per_account = {"RUNWAY": runway.DAILY_CAP, "VEO": veo.DAILY_CAP,
                   "HIGGSFIELD": higgsfield.DAILY_CAP, "MIDJOURNEY": midjourney.DAILY_CAP,
                   "NANO": nano_banana.DAILY_CAP}
    for prefix, cap in per_account.items():
        key = f"{prefix}_GLOBAL_DAILY_CAP"
        assert key in values, f"{key} is not set in .env.example"
        assert int(values[key]) > cap, f"{key} is not above the per-account cap of {cap}"
    assert "people" in text and "x 3" in text     # the arithmetic is written down


# --------------------------------------------------------------------------
# provenance on the shelves (part two): the label is the tenant, and it is
# written at every learning-shelf ingest and read at every retrieval site
# --------------------------------------------------------------------------

def test_slug_of_is_the_tenant_and_never_raises(two_accounts):
    path, a, b = two_accounts
    assert accounts.slug_of(a, dsn=path) == "zeropage"
    assert accounts.slug_of(b, dsn=path) == "antihero"
    assert accounts.slug_of(None, dsn=path) is None
    assert accounts.slug_of(999, dsn=path) is None
    with db.connect(path) as conn:
        conn.execute("DROP TABLE accounts CASCADE")
    assert accounts.slug_of(1, dsn=path) is None


def test_a_denial_is_labelled_with_the_tenant_not_the_brand(two_accounts, monkeypatch):
    """The one site that ever wrote `project` wrote the brand. A second
    user's rows are labelled with Mike's brand name until fix-order item
    5 lands (PILOT_DRY_RUN #9), so keyed by brand a stranger's denial
    would rank FIRST for Mike's next concept."""
    from fastapi.testclient import TestClient

    import app.main as app_main
    from app import api as api_mod
    from app import auth

    path, a, b = two_accounts
    autonomy.init(path)
    monkeypatch.setenv("DATABASE_URL", path)
    records = []

    class _Conn:
        def close(self):
            pass
    monkeypatch.setattr(api_mod.rag, "connect", lambda db_url=None: _Conn())
    monkeypatch.setattr(api_mod.rag, "init_store", lambda c: None)
    monkeypatch.setattr(api_mod.rag, "make_client", lambda: object())
    monkeypatch.setattr(api_mod.rag, "ingest_records",
                        lambda recs, client_, conn: records.extend(recs) or len(recs))
    monkeypatch.setattr(auth, "current_user", lambda request: {"id": 1})
    app_main.app.dependency_overrides[auth.current_account_id] = lambda: b
    with db.connect(path) as conn:
        theirs = conn.execute("SELECT id FROM shoot_concepts WHERE account_id = %s",
                              (b,)).fetchone()["id"]
        conn.execute("UPDATE shoot_concepts SET brand = 'zeropage' WHERE id = %s", (theirs,))
    res = TestClient(app_main.app).post(
        f"/api/concepts/{theirs}/deny", json={"reasons": ["off-tone"], "note": "no"})
    assert res.status_code == 200, res.text
    assert records and records[0]["domain"] == "denials"
    assert records[0]["project"] == "antihero"        # the tenant (account b)
    assert records[0]["project"] != "zeropage"        # not the row's brand


def test_ideation_prefers_the_tenants_own_neighbourhood(two_accounts, monkeypatch):
    """Every automatic retrieval in reference_block passes the caller's
    slug as prefer_project -- never as project, which would be a fence."""
    from src import shootgen
    path, a, _b = two_accounts
    calls = []
    monkeypatch.setattr(shootgen.rag, "retrieve_references",
                        lambda *args, **kw: calls.append(kw) or
                        {"ok": True, "references": []})
    monkeypatch.setattr(shootgen, "build_reference_query", lambda *a, **k: "a query")
    shootgen.reference_block(spark="gearing up ritual", db_path=path, account_id=a)
    assert calls and all(c.get("prefer_project") == "zeropage" for c in calls)
    assert all(c.get("project") is None for c in calls)


# --------------------------------------------------------------------------
# the render path, and the closure that ate the owner
#
# Both found by re-running the dry run's probes against the fix (2026-09-02):
# the three tables were closed and these two were not. Neither is a leak --
# they are the same mistake pointing inward, where the owner is dropped on the
# way to the data layer and the caller's own rows stop existing.
# --------------------------------------------------------------------------

def test_the_render_path_carries_the_owner(two_tenants, monkeypatch):
    """Queue-approve and the Director's generate resolved the concept WITH
    the account and then called generate_for_shot WITHOUT it, so
    preprod.get_concept(account_id=None) found nothing and the render died
    with "no concept N" -- for the owner, on their own row, before any API
    call. Measured on a copy of the live database: concept 149, owned by
    account 1, {'ok': False, 'error': 'no concept 149'}.

    It also meant the per-account cap inside generate_for_shot counted
    against None instead of the caller.
    """
    import time

    from app import jobs
    from src import preprod, runway

    t = two_tenants
    seen = {}

    def fake_generate_for_shot(concept_id, shot_n, **kwargs):
        seen.update(kwargs)
        return {"ok": True, "media_url": "file:///clip.mp4", "generation_id": 1}

    monkeypatch.setattr(runway, "generate_for_shot", fake_generate_for_shot)
    monkeypatch.setattr(runway, "has_key", lambda: True)

    owner = t["a"]
    concept_id = preprod.save_concept(
        {"title": "a take", "logline": "x",
         "shots": [{"n": 1, "ai_prompt": "a prompt"}]},
        "zeropage", dsn=t["path"], account_id=owner)
    preprod.set_picked(concept_id, True, dsn=t["path"], account_id=owner)

    client = t["as"](owner)
    for url in (f"/api/queue/{concept_id}/approve",
                f"/api/concepts/{concept_id}/shots/1/generate"):
        seen.clear()
        res = client.post(url)
        assert res.status_code == 200, (url, res.text)
        job_id = res.json()["job_id"]
        deadline = time.time() + 5
        while time.time() < deadline and jobs.get(job_id, account_id=owner)["status"] in ("queued", "running"):
            time.sleep(0.01)
        done = jobs.get(job_id, account_id=owner)
        assert done["status"] == "done", done.get("error")
        assert seen.get("account_id") == owner, (
            f"{url} called generate_for_shot with account_id="
            f"{seen.get('account_id')!r} -- the owner's own render dies")


def test_no_job_closure_shadows_the_route_owner():
    """`jobs.start` calls `fn(job)` with one argument, so an inner
    `def work(job, account_id=None)` binds None over the route's resolved
    dependency -- silently, because the name is right there in scope.

    That is how POST /api/generate/run saved every concept with
    account_id=NULL, which preprod.init's backfill_owner then handed to the
    bootstrap account at the next startup. Under --reload that is every code
    edit, which is why it never looked broken: Mike's own orphans came back
    to him. A pilot's would come back to him too.

    Static because the failure is invisible at runtime -- the write
    succeeds, it just belongs to nobody.
    """
    import ast
    import pathlib

    offenders = []
    for path in (pathlib.Path("app/api.py"), pathlib.Path("app/main.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for inner in ast.walk(node):
                if inner is node or not isinstance(inner, ast.FunctionDef):
                    continue
                names = [a.arg for a in inner.args.args]
                if "account_id" in names[1:]:
                    offenders.append(f"{path}:{inner.lineno} {inner.name}({', '.join(names)})")
    assert not offenders, (
        "a job function takes account_id as a parameter; jobs.start passes "
        "only the job, so it is always None:\n  " + "\n  ".join(offenders))
