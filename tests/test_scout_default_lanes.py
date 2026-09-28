"""
The Instagram lane joins ONE account's default research pass (2026-09-28).

The lane reads with the operator's IG_GRAPH_TOKEN and spends Meta's
budget for the whole installation, so it is not a module default: it is
`accounts.scout_instagram`, FALSE for everyone, turned on by hand
(`python -m src.accounts scout-instagram <slug> --on`), and every door
that starts a pass -- the Studio route, the MCP research tool, the CLI --
asks scout.default_lanes(<its account>) for the lanes when none were named.
"""
import pytest

from src import accounts, mcp_server, scout


@pytest.fixture
def tmp_db(pg, monkeypatch):
    accounts.init(pg)
    scout.init(pg)
    monkeypatch.setenv("DATABASE_URL", pg)
    return pg


def two_accounts(pg):
    mine = accounts.upsert_account("zeropage", "Zero Page", dsn=pg)
    theirs = accounts.upsert_account("pilot", "Pilot", dsn=pg)
    return mine, theirs


def test_off_for_everyone_until_turned_on_by_hand(tmp_db):
    mine, theirs = two_accounts(tmp_db)
    assert scout.default_lanes(mine, dsn=tmp_db) == scout.DEFAULT_LANES
    assert "instagram" not in scout.DEFAULT_LANES

    result = accounts.set_scout_instagram("zeropage", True, dsn=tmp_db)
    assert result["changed"] is True and result["account_id"] == mine
    assert scout.default_lanes(mine, dsn=tmp_db) == scout.DEFAULT_LANES + ("instagram",)
    assert scout.default_lanes(theirs, dsn=tmp_db) == scout.DEFAULT_LANES   # mine only
    assert accounts.scout_instagram_accounts(dsn=tmp_db) == [
        {"account_id": mine, "slug": "zeropage"}]

    accounts.set_scout_instagram("zeropage", False, dsn=tmp_db)
    assert scout.default_lanes(mine, dsn=tmp_db) == scout.DEFAULT_LANES


def test_the_flag_fails_closed(tmp_db):
    two_accounts(tmp_db)
    accounts.set_scout_instagram("zeropage", True, dsn=tmp_db)
    assert scout.instagram_default(None, dsn=tmp_db) is False       # the unowned pool
    assert scout.instagram_default("nope", dsn=tmp_db) is False
    assert scout.instagram_default(9999, dsn=tmp_db) is False       # no such account
    assert scout.instagram_default(1, dsn="postgresql://nobody@127.0.0.1:1/none") is False
    with pytest.raises(ValueError):
        accounts.set_scout_instagram("nobody", True, dsn=tmp_db)


def test_it_is_its_own_column(tmp_db):
    """Turning another account flag on must not put Instagram in the pass."""
    mine, _ = two_accounts(tmp_db)
    accounts.set_prompt_edits_teach("zeropage", True, dsn=tmp_db)
    accounts.set_manual_lane_operator("zeropage", True, dsn=tmp_db)
    assert scout.instagram_default(mine, dsn=tmp_db) is False


# ---------- the doors ----------

@pytest.fixture
def captured_lanes(monkeypatch):
    seen = {}

    def fake_scout(brand="zeropage", count=4, *, lanes=scout.DEFAULT_LANES, dsn=None, **k):
        seen["lanes"] = tuple(lanes)
        return {"ok": True, "findings": [], "errors": [], "signals": 0, "bin": []}
    monkeypatch.setattr(scout, "scout", fake_scout)
    return seen


def test_the_mcp_research_default_is_the_callers_own(tmp_db, captured_lanes):
    mine, theirs = two_accounts(tmp_db)
    accounts.set_scout_instagram("zeropage", True, dsn=tmp_db)

    mcp_server.run_research("zeropage", dsn=tmp_db, account_id=mine)
    assert "instagram" in captured_lanes["lanes"]

    mcp_server.run_research("zeropage", dsn=tmp_db, account_id=theirs)
    assert "instagram" not in captured_lanes["lanes"]   # it used to run for everyone


def test_an_explicit_lane_list_is_honoured_either_way(tmp_db, captured_lanes):
    _, theirs = two_accounts(tmp_db)
    mcp_server.run_research("zeropage", lanes=["web", "instagram"], dsn=tmp_db,
                            account_id=theirs)
    assert captured_lanes["lanes"] == ("web", "instagram")


def test_the_mcp_knows_every_lane_the_scout_dispatches():
    """It had drifted: `feeds` as a default, `pinterest` missing."""
    assert mcp_server.LANES == scout.KNOWN_LANES
    assert "pinterest" in mcp_server.LANES
    assert set(scout.DEFAULT_LANES) <= set(scout.KNOWN_LANES)


def test_the_studio_route_asks_for_the_accounts_default(tmp_db, monkeypatch):
    from fastapi.testclient import TestClient

    from app import api as api_mod
    from app import auth
    from app.main import app

    mine, _ = two_accounts(tmp_db)
    accounts.set_scout_instagram("zeropage", True, dsn=tmp_db)
    ran = {}
    monkeypatch.setattr(api_mod, "_gemini_key", lambda account_id: "k")
    stub = {"id": 1, "email": "test@example.com", "display_name": "Test"}
    monkeypatch.setattr(auth, "current_user", lambda request: stub)

    def fake_scout(brand, count, *, lanes=scout.DEFAULT_LANES, **k):
        ran["lanes"] = tuple(lanes)
        return {"ok": True, "findings": [], "errors": [], "bin": []}
    monkeypatch.setattr(scout, "scout", fake_scout)

    def run_now(kind, label, work, account_id=None):
        work({"id": "j"})
        return {"id": "j"}
    monkeypatch.setattr(api_mod.jobs, "start", run_now)
    monkeypatch.setattr(api_mod.jobs, "progress", lambda *a, **k: None)
    app.dependency_overrides[auth.current_account_id] = lambda: mine
    try:
        res = TestClient(app).post("/api/scout/run", json={"brand": "zeropage"})
    finally:
        app.dependency_overrides.pop(auth.current_account_id, None)
    assert res.status_code == 200
    assert "instagram" in ran["lanes"]
