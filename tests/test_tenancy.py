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
    first = preprod.add_location("hallway", photo_count=3, path=path)
    again = preprod.add_location("hallway", photo_count=4, path=path)
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
