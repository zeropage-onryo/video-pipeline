"""Who has connected Claude (src/mcp_connections.py) and the route the
account menus' Connect to Claude panel reads (GET /api/mcp/connection).

What they pin: an approval names its client, a use stamps every client
the person connected and writes a client-less row when none was
approved, and the route answers for the caller's OWN account and person
only -- a second account, and a second member of the same account, both
read `connected: false`.
"""
import pytest
from fastapi.testclient import TestClient
from test_auth import JWT_SECRET, FakeGoTrue

from app import auth as auth_mod
from app.main import app
from src import accounts, db, mcp_connections

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_slate(pg, monkeypatch, account_scope):
    # this file IS about whose rows a route reads: the real tenant
    # dependency, not conftest's stand-in None
    app.dependency_overrides.pop(auth_mod.current_account_id, None)
    accounts.init(pg)
    mcp_connections.init(pg)
    monkeypatch.setenv("DATABASE_URL", pg)
    monkeypatch.setenv("SESSION_SECRET", "test-secret-not-for-real-use")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-key")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", JWT_SECRET)
    auth_mod._hits.clear()
    client.cookies.clear()
    return pg


@pytest.fixture
def people(clean_slate, monkeypatch):
    """Mike (two accounts, the oldest is his tenant), Ana in her own
    account, and Cleo, a second member of Mike's account."""
    fake = FakeGoTrue()
    monkeypatch.setattr(auth_mod, "gotrue", fake)
    out = {}
    for name in ("mike", "ana", "cleo"):
        uid = fake.register(f"{name}@example.com", f"{name}s-password-1", uid=f"uid-{name}")
        accounts.create_user(f"{name}@example.com", user_id=uid, claimed=True, dsn=clean_slate)
        out[name] = uid
    mikes = accounts.upsert_account("zeropage", "Zero Page", "#e4002b", dsn=clean_slate)
    second = accounts.upsert_account("antihero", "ANTIHERO", "#d64550", dsn=clean_slate)
    anas = accounts.upsert_account("anas-studio", "Ana", "#000000", dsn=clean_slate)
    accounts.add_member(mikes, out["mike"], dsn=clean_slate)
    accounts.add_member(second, out["mike"], dsn=clean_slate)
    accounts.add_member(anas, out["ana"], dsn=clean_slate)
    accounts.add_member(mikes, out["cleo"], dsn=clean_slate)
    out.update(mikes=mikes, second=second, anas=anas)
    return out


def _as(name):
    client.cookies.clear()
    response = client.post("/auth/login", data={"email": f"{name}@example.com",
                                                "password": f"{name}s-password-1"},
                           follow_redirects=False)
    assert response.status_code == 303
    return client.get("/api/mcp/connection")


# ---------- the module ----------

def test_nothing_recorded_is_not_connected(clean_slate):
    assert mcp_connections.status(1, "uid-x", dsn=clean_slate) == {
        "connected": False, "approved_at": None, "last_used_at": None, "client_name": None}


def test_an_approval_names_the_client_and_a_second_one_moves_it(people, clean_slate):
    mcp_connections.record_approval(people["mikes"], people["mike"], "Claude", "claude.ai",
                                    dsn=clean_slate)
    first = mcp_connections.status(people["mikes"], people["mike"], dsn=clean_slate)
    assert first["connected"] and first["client_name"] == "Claude"
    assert first["approved_at"] is not None and first["last_used_at"] is None
    mcp_connections.record_approval(people["mikes"], people["mike"], "Claude", "claude.ai",
                                    dsn=clean_slate)
    with db.connect(clean_slate) as conn:
        rows = conn.execute("SELECT client_name, redirect_host FROM mcp_connections "
                            "WHERE account_id = %s", (people["mikes"],)).fetchall()
    assert [(r["client_name"], r["redirect_host"]) for r in rows] == [("Claude", "claude.ai")]


def test_a_use_with_no_approval_on_file_is_still_a_connection(people, clean_slate):
    """A connection made before this table existed (Mike's own, walked
    2026-10-08) shows as connected the first time it is used."""
    mcp_connections.touch(people["mikes"], people["mike"], dsn=clean_slate)
    mcp_connections.touch(people["mikes"], people["mike"], dsn=clean_slate)
    got = mcp_connections.status(people["mikes"], people["mike"], dsn=clean_slate)
    assert got["connected"] and got["last_used_at"] is not None
    assert got["approved_at"] is None and got["client_name"] is None
    with db.connect(clean_slate) as conn:
        assert conn.execute("SELECT count(*) AS n FROM mcp_connections "
                            "WHERE account_id = %s", (people["mikes"],)).fetchone()["n"] == 1


def test_a_use_stamps_every_client_the_person_approved(people, clean_slate):
    for name in ("Claude", "Claude Code"):
        mcp_connections.record_approval(people["mikes"], people["mike"], name, "x",
                                        dsn=clean_slate)
    mcp_connections.touch(people["mikes"], people["mike"], dsn=clean_slate)
    with db.connect(clean_slate) as conn:
        rows = conn.execute("SELECT client_name, last_used_at FROM mcp_connections "
                            "WHERE account_id = %s ORDER BY id", (people["mikes"],)).fetchall()
    assert [r["client_name"] for r in rows] == ["Claude", "Claude Code"]
    assert all(r["last_used_at"] is not None for r in rows)


# ---------- the route ----------

def test_the_route_answers_for_the_callers_own_account_only(people, clean_slate):
    mcp_connections.record_approval(people["mikes"], people["mike"], "Claude", "claude.ai",
                                    dsn=clean_slate)
    mike = _as("mike").json()
    assert mike["connected"] is True and mike["client_name"] == "Claude"
    # another account, and another member of Mike's own account
    assert _as("ana").json()["connected"] is False
    assert _as("cleo").json()["connected"] is False


def test_the_route_reads_the_tenant_not_the_brand(people, clean_slate):
    """MCP calls resolve to the oldest membership; switching the brand
    pill to the second account must not make the connection disappear."""
    mcp_connections.record_approval(people["mikes"], people["mike"], "Claude", "claude.ai",
                                    dsn=clean_slate)
    _as("mike")
    client.post("/brand/antihero", data={"next": "/studio"}, follow_redirects=False)
    assert client.get("/api/mcp/connection").json()["connected"] is True


def test_the_route_needs_a_session(clean_slate):
    assert client.get("/api/mcp/connection").status_code == 401
