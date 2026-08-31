"""
Tenancy -- every owned row carries the account that owns it.

Stage one: the schema and its migration. The ownership *predicates* get
their own tests as the reads and writes land; what is proved here is
that an existing database can grow the column without losing anything,
which is the part that only gets one chance to be right.

The migration is the sharp edge. `locations.name` was globally UNIQUE,
so no second account could ever own a place called "Garage", and a
UNIQUE lives in the table definition where SQLite cannot ALTER it away.
The rebuild that fixes it sits next to a foreign key -- concept_locations
references locations -- and two plausible ways of writing it silently
destroy data:

* rename the old table aside, and SQLite (>= 3.25) rewrites
  concept_locations to reference `locations_old`, which is then dropped;
* drop the referenced table with foreign keys on, and ON DELETE CASCADE
  takes every concept_locations row with it.

Neither shows up in `PRAGMA foreign_key_check` on a database whose
concept_locations happens to be empty -- which is exactly the state of
the live one -- so these tests seed a row first. Both failures were
observed for real before the current implementation.
"""
import ast
import pathlib
import re
import sqlite3

import pytest

from src import accounts, db, entities, generative, preprod

# The pre-tenancy shape, copied from the schema as it stood at a8fe240.
# Written out rather than imported so that a later edit to preprod.SCHEMA
# cannot quietly make this test stop testing the migration.
PRE_TENANCY = """
CREATE TABLE locations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT    NOT NULL,
    name        TEXT    NOT NULL UNIQUE,
    photo_count INTEGER,
    description_json TEXT,
    notes       TEXT
);
CREATE TABLE shoot_concepts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT    NOT NULL,
    brand       TEXT    NOT NULL,
    title       TEXT    NOT NULL,
    shots_json  TEXT    NOT NULL,
    shot_done   INTEGER NOT NULL DEFAULT 0,
    use_pov     INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE concept_locations (
    concept_id  INTEGER NOT NULL REFERENCES shoot_concepts(id) ON DELETE CASCADE,
    location_id INTEGER NOT NULL REFERENCES locations(id) ON DELETE CASCADE,
    UNIQUE (concept_id, location_id)
);
"""


@pytest.fixture
def legacy_db(tmp_path):
    """A populated database in the shape that predates tenancy."""
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    conn.executescript(PRE_TENANCY)
    conn.execute("INSERT INTO locations (created_at, name) VALUES ('t', 'Garage')")
    conn.execute("INSERT INTO locations (created_at, name) VALUES ('t', 'Alley')")
    conn.execute(
        "INSERT INTO shoot_concepts (created_at, brand, title, shots_json) "
        "VALUES ('t', 'zeropage', 'A concept', '[]')"
    )
    conn.execute("INSERT INTO concept_locations (concept_id, location_id) VALUES (1, 1)")
    conn.execute("INSERT INTO concept_locations (concept_id, location_id) VALUES (1, 2)")
    conn.commit()
    conn.close()
    return path


@pytest.fixture
def migrated(legacy_db):
    preprod.init(legacy_db)
    accounts.seed("mike@example.com", path=legacy_db)
    preprod.init(legacy_db)     # idempotence is part of the contract
    return legacy_db


def _sql(path, name):
    with db.connect(path) as conn:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name = ?", (name,)
        ).fetchone()
    return " ".join(row["sql"].split()) if row else None


def _one(path, query, args=()):
    with db.connect(path) as conn:
        return conn.execute(query, args).fetchone()[0]


# --------------------------------------------------------------------------
# the column
# --------------------------------------------------------------------------

def test_every_owned_table_grows_an_account_id(tmp_path):
    path = tmp_path / "fresh.db"
    db.init_db(path)
    preprod.init(path)
    entities.init(path)
    generative.init(path)
    with db.connect(path) as conn:
        for table in db.OWNED_TABLES:
            cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
            assert "account_id" in cols, f"{table} has no owner"


def test_existing_rows_are_claimed_by_the_bootstrap_account(migrated):
    owner = _one(migrated, "SELECT MIN(id) FROM accounts")
    for table in ("locations", "shoot_concepts"):
        unowned = _one(migrated, f"SELECT count(*) FROM {table} WHERE account_id IS NULL")
        assert unowned == 0, f"{table} left rows with no owner"
        assert _one(
            migrated, f"SELECT count(*) FROM {table} WHERE account_id = ?", (owner,)
        ) > 0


def test_init_before_seed_leaves_rows_unowned_rather_than_guessing(legacy_db):
    """There is no account yet, so there is no honest owner to write."""
    preprod.init(legacy_db)
    assert _one(legacy_db, "SELECT count(*) FROM locations WHERE account_id IS NULL") == 2


def test_seeding_afterwards_claims_them(legacy_db):
    preprod.init(legacy_db)
    accounts.seed("mike@example.com", path=legacy_db)
    assert _one(legacy_db, "SELECT count(*) FROM locations WHERE account_id IS NULL") == 0


# --------------------------------------------------------------------------
# the locations rebuild -- the part that can eat data
# --------------------------------------------------------------------------

def test_the_join_table_survives_the_rebuild(migrated):
    """Both destructive implementations left this at 0."""
    assert _one(migrated, "SELECT count(*) FROM concept_locations") == 2


def test_the_join_table_still_points_at_locations(migrated):
    sql = _sql(migrated, "concept_locations")
    assert "locations_old" not in sql
    assert "REFERENCES locations(id)" in sql


def test_no_table_references_a_table_that_does_not_exist(migrated):
    """`PRAGMA foreign_key_check` says nothing about a REFERENCES clause
    naming a missing table, so check the schema text itself."""
    import re
    with db.connect(migrated) as conn:
        names = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        for table, sql in conn.execute(
                "SELECT name, sql FROM sqlite_master WHERE type = 'table'"):
            for ref in re.findall(r'REFERENCES\s+"?(\w+)"?', sql or ""):
                assert ref in names, f"{table} references missing {ref}"


def test_the_cascade_still_fires(migrated):
    with db.connect(migrated) as conn:
        conn.execute("DELETE FROM locations WHERE name = 'Alley'")
    assert _one(migrated, "SELECT count(*) FROM concept_locations") == 1


def test_rows_and_integrity_survive(migrated):
    assert _one(migrated, "SELECT count(*) FROM locations") == 2
    with db.connect(migrated) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_no_scratch_tables_are_left_behind(migrated):
    with db.connect(migrated) as conn:
        leftovers = [r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND (name LIKE '%_new' OR name LIKE '%_old')")]
    assert leftovers == []


# --------------------------------------------------------------------------
# what the rebuild was for
# --------------------------------------------------------------------------

def test_two_accounts_can_each_own_a_garage(migrated):
    other = _one(migrated, "SELECT id FROM accounts WHERE slug = 'antihero'")
    with db.connect(migrated) as conn:
        conn.execute(
            "INSERT INTO locations (created_at, name, account_id) VALUES ('t', 'Garage', ?)",
            (other,),
        )
    assert _one(migrated, "SELECT count(*) FROM locations WHERE name = 'Garage'") == 2


def test_one_account_still_cannot_own_two_garages(migrated):
    owner = _one(migrated, "SELECT account_id FROM locations WHERE name = 'Garage'")
    with pytest.raises(sqlite3.IntegrityError):
        with db.connect(migrated) as conn:
            conn.execute(
                "INSERT INTO locations (created_at, name, account_id) "
                "VALUES ('t', 'Garage', ?)",
                (owner,),
            )


def test_ownerless_rows_still_collide_the_way_they_used_to(tmp_path):
    """The NULL-safe half of the index. SQLite treats NULLs as distinct
    inside a UNIQUE, so without the COALESCE two unowned rows named
    'hallway' would both exist and add_location's upsert would start
    duplicating instead of updating."""
    path = tmp_path / "fresh.db"
    db.init_db(path)
    preprod.init(path)
    with db.connect(path) as conn:
        conn.execute("INSERT INTO locations (created_at, name) VALUES ('t', 'hallway')")
    with pytest.raises(sqlite3.IntegrityError):
        with db.connect(path) as conn:
            conn.execute("INSERT INTO locations (created_at, name) VALUES ('t', 'hallway')")


def test_add_location_still_upserts_by_name(tmp_path):
    path = tmp_path / "fresh.db"
    db.init_db(path)
    preprod.init(path)
    first = preprod.add_location("hallway", photo_count=3, path=path, account_id=None)
    again = preprod.add_location("hallway", photo_count=4, path=path, account_id=None)
    assert first == again
    assert _one(path, "SELECT count(*) FROM locations") == 1
    assert _one(path, "SELECT photo_count FROM locations WHERE id = ?", (first,)) == 4


# --------------------------------------------------------------------------
# the repair, for databases the first implementation already broke
# --------------------------------------------------------------------------

def test_a_join_table_pointing_at_locations_old_is_healed(legacy_db):
    """Reproduces the damage the first rebuild caused, then proves init
    fixes it. Without the repair, every save of a concept against a
    location dies with `no such table: main.locations_old`."""
    conn = sqlite3.connect(legacy_db)
    conn.executescript("""
        PRAGMA foreign_keys = OFF;
        CREATE TABLE cl_broken (
            concept_id  INTEGER NOT NULL REFERENCES shoot_concepts(id) ON DELETE CASCADE,
            location_id INTEGER NOT NULL REFERENCES "locations_old"(id) ON DELETE CASCADE,
            UNIQUE (concept_id, location_id)
        );
        INSERT INTO cl_broken SELECT * FROM concept_locations;
        DROP TABLE concept_locations;
        ALTER TABLE cl_broken RENAME TO concept_locations;
    """)
    conn.commit()
    conn.close()
    assert "locations_old" in _sql(legacy_db, "concept_locations")

    preprod.init(legacy_db)

    sql = _sql(legacy_db, "concept_locations")
    assert "locations_old" not in sql
    assert _one(legacy_db, "SELECT count(*) FROM concept_locations") == 2


# --------------------------------------------------------------------------
# reads -- one account cannot see another's rows
# --------------------------------------------------------------------------

@pytest.fixture
def two_accounts(tmp_path):
    """Two accounts, one concept, one location and one character each."""
    path = tmp_path / "shared.db"
    db.init_db(path)
    preprod.init(path)
    entities.init(path)
    generative.init(path)
    accounts.seed("mike@example.com", path=path)
    with db.connect(path) as conn:
        a = conn.execute("SELECT id FROM accounts WHERE slug='zeropage'").fetchone()["id"]
        b = conn.execute("SELECT id FROM accounts WHERE slug='antihero'").fetchone()["id"]
        for owner, tag in ((a, "A"), (b, "B")):
            conn.execute(
                "INSERT INTO shoot_concepts (created_at, brand, title, shots_json, "
                "account_id) VALUES ('t', 'zeropage', ?, '[]', ?)", (f"{tag} concept", owner))
            conn.execute(
                "INSERT INTO locations (created_at, name, account_id) VALUES ('t', ?, ?)",
                (f"{tag} place", owner))
            conn.execute(
                "INSERT INTO characters (name, created_at, account_id) VALUES (?, 't', ?)",
                (f"{tag} person", owner))
    return path, a, b


def test_a_list_returns_only_your_own(two_accounts):
    path, a, b = two_accounts
    assert [c["title"] for c in preprod.list_concepts(path=path, account_id=a)] == ["A concept"]
    assert [c["title"] for c in preprod.list_concepts(path=path, account_id=b)] == ["B concept"]


def test_fetching_someone_elses_concept_by_id_is_indistinguishable_from_missing(two_accounts):
    """Ids are sequential integers. If "not yours" answered differently
    from "no such row", counting from 1 would map the whole table."""
    path, a, b = two_accounts
    theirs = preprod.list_concepts(path=path, account_id=b)[0]["id"]
    assert preprod.get_concept(theirs, path=path, account_id=a) is None
    assert preprod.get_concept(999_999, path=path, account_id=a) is None
    assert preprod.get_concept(theirs, path=path, account_id=b) is not None


def test_locations_and_cast_are_scoped_too(two_accounts):
    path, a, b = two_accounts
    assert [x["name"] for x in preprod.list_locations(path=path, account_id=a)] == ["A place"]
    assert [x["name"] for x in entities.list_characters(path=path, account_id=b)] == ["B person"]
    theirs = entities.list_characters(path=path, account_id=b)[0]["id"]
    assert entities.get_character(theirs, path=path, account_id=a) is None


def test_counts_do_not_leak_how_much_work_the_other_account_has_done(two_accounts):
    path, a, b = two_accounts
    assert preprod.summary(path=path, account_id=a) == {"locations": 1, "shoot_concepts": 1}
    assert entities.summary(path=path, account_id=b) == {"characters": 1, "props": 0}


def test_the_unowned_pool_is_its_own_scope(two_accounts):
    """account_id=None addresses rows that predate tenancy. It must not
    be a skeleton key onto everybody's."""
    path, a, b = two_accounts
    assert preprod.list_concepts(path=path, account_id=None) == []


# --------------------------------------------------------------------------
# writes -- ownership is stamped on create and checked on mutate
# --------------------------------------------------------------------------

def test_a_new_concept_is_stamped_with_its_creator(two_accounts):
    path, a, b = two_accounts
    new_id = preprod.save_concept(
        {"title": "Mine", "shots": []}, brand="zeropage", path=path, account_id=a)
    assert preprod.get_concept(new_id, path=path, account_id=a)["title"] == "Mine"
    assert preprod.get_concept(new_id, path=path, account_id=b) is None


def test_you_cannot_mutate_someone_elses_concept(two_accounts):
    """set_picked already raised "no concept N" on a rowcount of 0, and
    with the owner in the WHERE clause that now covers "not yours" too --
    which is the right error, because it is the same one a genuinely
    missing id gives. The mutation must not land either way."""
    path, a, b = two_accounts
    theirs = preprod.list_concepts(path=path, account_id=b)[0]["id"]
    with pytest.raises(ValueError):
        preprod.set_picked(theirs, True, path=path, account_id=a)
    assert preprod.get_concept(theirs, path=path, account_id=b)["picked_at"] is None

    preprod.set_picked(theirs, True, path=path, account_id=b)
    assert preprod.get_concept(theirs, path=path, account_id=b)["picked_at"] is not None


def test_you_cannot_delete_someone_elses_concept(two_accounts):
    path, a, b = two_accounts
    theirs = preprod.list_concepts(path=path, account_id=b)[0]["id"]
    preprod.delete_concept(theirs, path=path, account_id=a)
    assert preprod.get_concept(theirs, path=path, account_id=b) is not None


def test_clearing_the_slate_clears_only_your_own(two_accounts):
    """This one used to be `DELETE FROM shoot_concepts` with no argument."""
    path, a, b = two_accounts
    removed = preprod.delete_all_concepts(path=path, account_id=a)
    assert removed == 1
    assert preprod.list_concepts(path=path, account_id=a) == []
    assert len(preprod.list_concepts(path=path, account_id=b)) == 1


def test_a_concept_cannot_be_pinned_to_someone_elses_location(two_accounts):
    """location_ids arrives from a request. Without the ownership check
    a guessed integer links your concept to a stranger's room -- and the
    concept card would then render its name."""
    path, a, b = two_accounts
    theirs = preprod.list_locations(path=path, account_id=b)[0]["id"]
    mine = preprod.save_concept(
        {"title": "Borrowed", "shots": []}, brand="zeropage",
        location_ids=[theirs], path=path, account_id=a)
    assert preprod.get_concept(mine, path=path, account_id=a)["locations"] == []


def test_cast_and_props_are_stamped_and_checked(two_accounts):
    path, a, b = two_accounts
    cid = entities.add_character("Rider", path=path, account_id=a)
    assert entities.get_character(cid, path=path, account_id=b) is None
    entities.delete_character(cid, path=path, account_id=b)
    assert entities.get_character(cid, path=path, account_id=a) is not None


# --------------------------------------------------------------------------
# caps -- your renders are not billed to their day, and neither is the card
# --------------------------------------------------------------------------

def _log_render(path, account_id, tool="runway", n=1):
    from src.shot import Shot
    shot_id = generative.add_shot(
        Shot(subject="a bike", action="idles"), path=path, account_id=account_id)
    for _ in range(n):
        generative.record_generation(
            shot_id, tool, "a prompt", path=path, account_id=account_id)


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
        path=path, env_prefix="RUNWAY")
    assert refusal is not None and "daily cap" in refusal


def test_the_global_ceiling_catches_what_per_account_caps_cannot(two_accounts):
    """Two accounts, each comfortably inside its own cap, together over
    the ceiling. Per-account limits alone are ten pilot users times six
    renders on one card, every one of them within their rights."""
    path, a, b = two_accounts
    _log_render(path, a, n=3)
    _log_render(path, b, n=3)
    assert generative.cap_error("runway", 1, account_id=a, per_account=10,
                                ceiling=99, path=path, env_prefix="RUNWAY") is None
    refusal = generative.cap_error("runway", 1, account_id=a, per_account=10,
                                   ceiling=6, path=path, env_prefix="RUNWAY")
    assert refusal is not None and "daily ceiling" in refusal


def test_a_generation_cannot_be_logged_against_someone_elses_shot(two_accounts):
    from src.shot import Shot
    path, a, b = two_accounts
    shot_id = generative.add_shot(
        Shot(subject="a bike", action="idles"), path=path, account_id=a)
    with pytest.raises(ValueError):
        generative.record_generation(
            shot_id, "runway", "a prompt", path=path, account_id=b)


# --------------------------------------------------------------------------
# the regression test: no unscoped read survives review
# --------------------------------------------------------------------------

# Statements that legitimately touch an owned table without an owner
# predicate. Each needs a reason, and the reason has to be about the
# statement, not about convenience.
UNSCOPED_ALLOWED = {
    # migrations run before ownership exists, and operate on the whole table
    "INSERT INTO locations_new",
    "SELECT sql FROM sqlite_master",
    "PRAGMA table_info",
    # db.own_table's own backfill: the statement that CREATES ownership
    "SET account_id = ? WHERE account_id IS NULL",
    # the FK-repair copy, a pure join-table rebuild
    "INSERT INTO concept_locations_new",
    # concept_locations is reached only through an owned concept, and its
    # rows cascade with one -- it has no account_id of its own by design
    "FROM concept_locations",
    "INTO concept_locations",
    "DELETE FROM concept_locations",
    # the global ceiling in generative.used_today(everyone=True). The one
    # query in the codebase that is SUPPOSED to count every account: it is
    # what stops ten pilot users, each inside their own cap, from putting
    # sixty renders on one card.
    "SELECT COUNT(*) FROM generations WHERE tool = ? AND created_at >= ?",
    # assembled in pieces: the owner predicate lives in a different
    # literal from the one that names the table, so the scan cannot see
    # them together. Both are checked by tests of their own --
    # test_a_list_returns_only_your_own and the videos scoping tests.
    "SELECT * FROM videos",
    "ROW_NUMBER()",
}

OWNED_RE = re.compile(
    r"\b(?:FROM|JOIN|UPDATE|INTO)\s+(shoot_concepts|locations|characters|props|"
    r"generations|videos|scene_briefs|shots)\b",
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
    LIMIT ?` for as long as there was only one user, and nothing failed,
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
        conn.execute("UPDATE shoot_concepts SET account_id = ?", (a,))

    monkeypatch.setattr(auth, "current_user", lambda request: {"id": user_id})
    monkeypatch.setattr(auth.db, "DB_PATH", path)

    class Request:
        def __init__(self, brand):
            self.cookies = {"brand": brand}

    for brand in ("zeropage", "antihero"):
        scoped_to = auth.current_account_id(Request(brand))
        assert scoped_to == a, f"the {brand} pill switched tenants"
        assert len(preprod.list_concepts(path=path, account_id=scoped_to)) == 2


def test_a_user_with_no_membership_is_refused_not_defaulted(monkeypatch, tmp_path):
    """Signing in is not the same as having access -- a fresh signup gets
    zero account_members rows on purpose. That has to be a 403, not a
    fall-through to whichever account happens to be first."""
    from fastapi import HTTPException

    from app import auth

    path = tmp_path / "empty.db"
    db.init_db(path)
    accounts.init(path)
    uid = accounts.create_user("stranger@example.com", path=path)

    monkeypatch.setattr(auth, "current_user", lambda request: {"id": uid})
    monkeypatch.setattr(auth.db, "DB_PATH", path)

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
    assert accounts.resolve_account(path=path) == a
    assert accounts.resolve_account("antihero", path=path) != a
    with pytest.raises(ValueError):
        accounts.resolve_account("nosuchbrand", path=path)


def test_resolve_account_on_a_fresh_database_is_the_unowned_pool(tmp_path):
    path = tmp_path / "fresh.db"
    db.init_db(path)
    assert accounts.resolve_account(path=path) is None
