"""The Instagram token checks (src/instagram.py), their place in the
nightly preflight, and the operator CLI that installs tokens
(ops/ig_tokens.py). Every Meta answer here is a stub `get`: nothing reaches
the network, and no assertion may find a token value in anything printed."""
from datetime import datetime, timedelta, timezone

import pytest

from ops import ig_tokens
from src import instagram, nightly

NOW = datetime(2026, 9, 26, tzinfo=timezone.utc)
SECRET_TOKEN = "IGQ-very-secret-token-value"


class Resp:
    def __init__(self, body):
        self._body = body

    def json(self):
        return self._body


def stub_get(routes):
    """routes: [(url substring, body)] -- first match answers; calls are kept."""
    calls = []

    def get(url, params=None, timeout=None):
        calls.append((url, dict(params or {})))
        for fragment, body in routes:
            if fragment in url:
                if isinstance(body, Exception):
                    raise body
                return Resp(body)
        raise AssertionError(f"unexpected call to {url}")
    get.calls = calls
    return get


EXPIRED = {"error": {"message": "Error validating access token: Session has expired "
                                "on Friday, 05-Sep-26", "type": "OAuthException",
                     "code": 190, "error_subcode": 463}}


# --------------------------------------------------------------------------
# check_publish_token
# --------------------------------------------------------------------------

def test_a_missing_publishing_token_is_a_warning_that_names_the_fix():
    check = instagram.check_publish_token(get=stub_get([]))
    assert check["state"] == "missing" and check["warning"] is True
    line = instagram.health_line(check)
    assert "IG_ACCESS_TOKEN" in line and "instagram_business_content_publish" in line


def test_an_expired_publishing_token_says_expired_and_never_prints_the_token():
    get = stub_get([("graph.instagram.com", EXPIRED)])
    check = instagram.check_publish_token(SECRET_TOKEN, get=get)
    assert check["state"] == "expired" and check["warning"] and not check["ok"]
    assert SECRET_TOKEN not in instagram.health_line(check)
    assert get.calls[0][0].endswith("/me")          # one read, nothing else


def test_a_valid_publishing_token_reads_its_days_from_the_refresh_store(monkeypatch, tmp_path):
    store = tmp_path / "ig_token.json"
    monkeypatch.setenv("IG_TOKEN_STORE", str(store))
    store.write_text('{"expires_at": "%s"}' % (NOW + timedelta(days=40)).isoformat())
    get = stub_get([("/me", {"user_id": "1789", "username": "zeropagefilms"})])
    check = instagram.check_publish_token(SECRET_TOKEN, get=get, now=NOW)
    assert check["state"] == "valid" and check["days_left"] == 40
    assert check["warning"] is False and "@zeropagefilms" in check["detail"]


def test_a_publishing_token_under_two_weeks_is_expiring_and_loud(monkeypatch, tmp_path):
    store = tmp_path / "ig_token.json"
    monkeypatch.setenv("IG_TOKEN_STORE", str(store))
    store.write_text('{"expires_at": "%s"}' % (NOW + timedelta(days=5)).isoformat())
    get = stub_get([("/me", {"user_id": "1", "username": "z"})])
    check = instagram.check_publish_token(SECRET_TOKEN, get=get, now=NOW)
    assert check["state"] == "expiring" and check["warning"] is True
    assert "refresh" in check["fix"]


def test_an_unreachable_host_is_not_called_an_expired_token():
    get = stub_get([("graph.instagram.com", ConnectionError(f"boom {SECRET_TOKEN}"))])
    check = instagram.check_publish_token(SECRET_TOKEN, get=get)
    assert check["state"] == "unreachable"
    assert SECRET_TOKEN not in check["detail"]


# --------------------------------------------------------------------------
# check_graph_token
# --------------------------------------------------------------------------

def test_a_missing_research_token_is_quiet():
    """The lane is off by default and dark on purpose until the app exists."""
    check = instagram.check_graph_token(get=stub_get([]))
    assert check["state"] == "missing" and check["warning"] is False


def test_the_research_token_inspects_itself_through_debug_token():
    expires = int((NOW + timedelta(days=58)).timestamp())
    get = stub_get([("debug_token", {"data": {
        "is_valid": True, "expires_at": expires,
        "scopes": ["instagram_basic", "pages_show_list"]}})])
    check = instagram.check_graph_token(SECRET_TOKEN, get=get, now=NOW)
    assert check["state"] == "valid" and check["days_left"] == 58
    assert "instagram_basic" in check["scopes"]
    url, params = get.calls[0]
    assert url.startswith("https://graph.facebook.com/") and "debug_token" in url


def test_an_invalid_research_token_is_loud():
    get = stub_get([("debug_token", {"data": {
        "is_valid": False, "error": {"message": "Session has expired"}}})])
    check = instagram.check_graph_token(SECRET_TOKEN, get=get, now=NOW)
    assert check["state"] == "expired" and check["warning"] is True
    assert "IG_GRAPH_TOKEN" in instagram.health_line(check)


# --------------------------------------------------------------------------
# the nightly preflight
# --------------------------------------------------------------------------

def test_preflight_never_stops_the_walk_over_instagram(monkeypatch):
    monkeypatch.setattr(instagram, "token_health", lambda **k: [
        {"name": "IG_ACCESS_TOKEN", "state": "expired", "warning": True,
         "days_left": None, "detail": "Session has expired", "fix": "re-issue"},
        {"name": "IG_GRAPH_TOKEN", "state": "missing", "warning": False,
         "days_left": None, "detail": "not set", "fix": ""}])
    monkeypatch.setattr(nightly, "check_db", lambda dsn=None: {"ok": True, "detail": "ok"})
    monkeypatch.setattr(nightly, "check_gemini",
                        lambda client=None: {"ok": True, "detail": "stub"})
    monkeypatch.setattr(nightly, "check_image_cap", lambda dsn=None, account_id=None: {
        "ok": True, "headroom": 3, "detail": "stub"})
    report = nightly.preflight()
    assert report["stop"] is None
    [warning] = report["instagram"]["warnings"]
    assert warning.startswith("IG_ACCESS_TOKEN: EXPIRED") and "re-issue" in warning
    line = nightly.preflight_line(report)
    assert "IG_ACCESS_TOKEN=expired" in line and line.count("\n") == 0


def test_a_broken_check_is_reported_not_raised(monkeypatch):
    def boom(**k):
        raise ValueError("no")
    monkeypatch.setattr(instagram, "token_health", boom)
    result = nightly.check_instagram()
    assert result["ok"] is False and "failed" in result["warnings"][0]


def test_with_no_tokens_the_preflight_check_makes_no_call():
    """conftest clears the IG env: the check must answer without Meta."""
    result = nightly.check_instagram()
    assert [c["state"] for c in result["checks"]] == ["missing", "missing"]


# --------------------------------------------------------------------------
# ops/ig_tokens.py
# --------------------------------------------------------------------------

def test_set_env_replaces_in_place_appends_new_and_keeps_a_backup(tmp_path):
    env = tmp_path / ".env"
    env.write_text("A=1\nIG_ACCESS_TOKEN=old\n# comment\n")
    backup = ig_tokens.set_env({"IG_ACCESS_TOKEN": "new", "IG_BUSINESS_ID": "42"}, env,
                               now=datetime(2026, 9, 26, 1, 2, 3))
    assert env.read_text() == "A=1\nIG_ACCESS_TOKEN=new\n# comment\nIG_BUSINESS_ID=42\n"
    assert backup.name == ".env.bak.20260926010203"
    assert backup.read_text() == "A=1\nIG_ACCESS_TOKEN=old\n# comment\n"


def test_refresh_writes_env_and_resets_the_store(monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_text(f"IG_ACCESS_TOKEN={SECRET_TOKEN}\n")
    store = tmp_path / "ig_token.json"
    monkeypatch.setenv("IG_TOKEN_STORE", str(store))
    monkeypatch.setenv("IG_ACCESS_TOKEN", SECRET_TOKEN)
    said = []
    code = ig_tokens.cmd_refresh(
        env_path=env, say=said.append, now=NOW,
        refresh=lambda t: {"access_token": "IGQ-fresh", "expires_in": 60 * 86400})
    assert code == 0
    assert "IG_ACCESS_TOKEN=IGQ-fresh" in env.read_text()
    record = instagram._read_token_store()
    assert record["access_token"] is None
    assert record["replaces"] == instagram._fingerprint("IGQ-fresh")
    printed = "\n".join(said)
    assert "60 days" in printed and SECRET_TOKEN not in printed and "IGQ-fresh" not in printed


def test_refresh_of_a_dead_token_writes_nothing_and_names_the_reissue(monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_text("IG_ACCESS_TOKEN=dead\n")
    monkeypatch.setenv("IG_ACCESS_TOKEN", "dead")

    def refuse(token):
        raise RuntimeError("400 Session has expired")
    said = []
    assert ig_tokens.cmd_refresh(env_path=env, refresh=refuse, say=said.append) == 1
    assert env.read_text() == "IG_ACCESS_TOKEN=dead\n"
    assert not list(tmp_path.glob(".env.bak.*"))
    assert any("Generate token" in s for s in said)


def test_research_refuses_the_publishing_app():
    said = []
    assert ig_tokens.cmd_research(app_id=ig_tokens.PUBLISH_APP_ID,
                                  ask=lambda p: pytest.fail("asked for a secret"),
                                  say=said.append) == 1
    assert "ZeroPageFilms" in said[0]


def test_research_exchanges_finds_the_page_and_writes_both_vars(monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_text("IG_USER_ID=1789\n")
    answers = iter(["app-secret", "short-lived"])
    get = stub_get([
        ("oauth/access_token", {"access_token": "EAA-long", "expires_in": 5183999}),
        ("me/accounts", {"data": [
            {"name": "Faceless Photos", "id": "999"},
            {"name": "Mike Massaad", "id": ig_tokens.RESEARCH_PAGE_ID,
             "instagram_business_account": {"id": "17841400000", "username": "zeropagefilms"}},
        ]}),
        ("debug_token", {"data": {"is_valid": True,
                                  "expires_at": int((datetime.now(timezone.utc)
                                                     + timedelta(days=59)).timestamp())}}),
    ])
    seen = {}

    def discovery(handle, limit=6, token=None, user_id=None):
        seen.update(handle=handle, token=token, user_id=user_id)
        return {"ok": True, "followers": 10, "posts": []}
    monkeypatch.setattr(instagram, "business_discovery", discovery)
    monkeypatch.setattr(instagram, "hashtag_id",
                        lambda *a, **k: pytest.fail("research must not spend hashtag budget"))
    said = []
    code = ig_tokens.cmd_research(app_id="555", env_path=env, ask=lambda p: next(answers),
                                  get=get, say=said.append)
    assert code == 0
    text = env.read_text()
    assert "IG_GRAPH_TOKEN=EAA-long" in text and "IG_BUSINESS_ID=17841400000" in text
    assert "IG_USER_ID=1789" in text                      # the publishing id untouched
    exchange = get.calls[0][1]
    assert exchange["grant_type"] == "fb_exchange_token" and exchange["client_id"] == "555"
    assert seen == {"handle": "zeropagefilms", "token": "EAA-long",
                    "user_id": "17841400000"}
    printed = "\n".join(said)
    assert "EAA-long" not in printed and "app-secret" not in printed


def test_research_with_no_linked_page_writes_nothing(tmp_path):
    env = tmp_path / ".env"
    env.write_text("")
    answers = iter(["s", "t"])
    get = stub_get([
        ("oauth/access_token", {"access_token": "EAA-long"}),
        ("me/accounts", {"data": [{"name": "Faceless Photos", "id": "999"}]}),
    ])
    said = []
    assert ig_tokens.cmd_research(app_id="555", env_path=env, ask=lambda p: next(answers),
                                  get=get, say=said.append) == 1
    assert env.read_text() == ""


def test_pick_page_refuses_to_guess_between_two_linked_pages():
    pages = [{"id": "1", "instagram_business_account": {"id": "a"}},
             {"id": "2", "instagram_business_account": {"id": "b"}}]
    assert ig_tokens.pick_page(pages, page_id="3") is None
    assert ig_tokens.pick_page(pages, page_id="2")["id"] == "2"
    assert ig_tokens.pick_page(pages[:1], page_id="3")["id"] == "1"


def test_check_exits_one_when_a_token_needs_a_person():
    said = []
    assert ig_tokens.cmd_check(get=stub_get([]), say=said.append) == 1
    assert said[0].startswith("!!! IG_ACCESS_TOKEN: MISSING")
