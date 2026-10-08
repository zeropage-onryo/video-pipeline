"""The OAuth consent page (app/oauth_consent.py, 2026-10-07).

Supabase's OAuth 2.1 server sends a connector's user to
/oauth/consent?authorization_id=... and waits for the app to answer, as
the person, with GET /oauth/authorizations/{id} and POST .../consent.
These tests drive the real routes with a fake GoTrue behind the one seam
(auth.gotrue) -- the same FakeGoTrue the sign-in tests use, taught the two
authorization endpoints -- and sign real HS256 tokens, so verify_token
runs for real. The network guard in conftest catches anything that slips.

What they pin: the page never answers without a fresh sign-in, any sign-in
door comes back to it holding the token, what the person approves names
the client and the redirect HOST (with the loopback warning), approve and
deny reach Supabase as the person with a CSRF check, the token is spent
once, and nothing redirects anywhere Supabase did not send.
"""
import time

import pytest
from fastapi.testclient import TestClient
from test_auth import JWT_SECRET, FakeGoTrue

from app import auth as auth_mod
from app import oauth_consent
from app.main import app
from src import accounts

client = TestClient(app)

AUTHZ = "8f14e45f-ceea-467f-a0e6-1b2c3d4e5f60"
CLAIMS_CALLBACK = "https://claude.ai/api/mcp/auth_callback"


class ConsentGoTrue(FakeGoTrue):
    """FakeGoTrue plus Supabase's OAuth server's two consent endpoints."""

    def __init__(self):
        super().__init__()
        self.requests = {AUTHZ: {"redirect_uri": CLAIMS_CALLBACK, "scope": "openid email",
                                 "client": {"id": "c1", "name": "Claude",
                                            "uri": "https://claude.ai", "logo_uri": ""}}}
        self.consented: dict[str, str] = {}     # authorization id -> email
        self.decisions: list = []

    def __call__(self, method, path, *, json=None, params=None, token=None):
        prefix = "/oauth/authorizations/"
        if not path.startswith(prefix):
            return super().__call__(method, path, json=json, params=params, token=token)
        self.calls.append((method, path, json, params))
        found = self.user_for_token(token)
        if not found:
            return 401, {"msg": "invalid JWT"}
        email, _ = found
        rest = path[len(prefix):]
        if method == "GET":
            req = self.requests.get(rest)
            if req is None:
                return 404, {"msg": "authorization not found"}
            if self.consented.get(rest) == email:
                return 200, {"redirect_url": f"{req['redirect_uri']}?code=again&state=s"}
            return 200, {"authorization_id": rest, "user": {"id": "u", "email": email}, **req}
        if method == "POST" and rest.endswith("/consent"):
            authz = rest[:-len("/consent")]
            req = self.requests.get(authz)
            if req is None:
                return 404, {"msg": "authorization not found"}
            self.decisions.append((authz, json["action"], email))
            if json["action"] == "approve":
                self.consented[authz] = email
                return 200, {"redirect_url": f"{req['redirect_uri']}?code=c0de&state=s"}
            return 200, {"redirect_url": f"{req['redirect_uri']}?error=access_denied&state=s"}
        return 404, {}


@pytest.fixture(autouse=True)
def clean_slate(pg, monkeypatch):
    accounts.init(pg)
    monkeypatch.setenv("DATABASE_URL", pg)
    monkeypatch.setenv("SESSION_SECRET", "test-secret-not-for-real-use")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-key")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", JWT_SECRET)
    auth_mod._hits.clear()
    client.cookies.clear()
    return pg


@pytest.fixture
def gotrue(monkeypatch):
    fake = ConsentGoTrue()
    fake.register("ana@example.com", "anas-password-1", uid="uid-ana")
    monkeypatch.setattr(auth_mod, "gotrue", fake)
    return fake


def _get(authz=AUTHZ):
    return client.get(f"/oauth/consent?authorization_id={authz}", follow_redirects=False)


def _sign_in():
    return client.post("/auth/login", data={"email": "ana@example.com",
                                            "password": "anas-password-1"},
                       follow_redirects=False)


def _arrive_and_sign_in():
    first = _get()
    assert first.status_code == 303 and first.headers["location"] == "/signin"
    back = _sign_in()
    assert back.status_code == 303
    assert back.headers["location"] == f"/oauth/consent?authorization_id={AUTHZ}"
    return back


def _csrf(html: str) -> str:
    marker = 'name="csrf" value="'
    start = html.index(marker) + len(marker)
    return html[start:html.index('"', start)]


# ---------- arriving ----------

def test_arriving_with_no_sign_in_goes_to_the_sign_in_page_saying_why(gotrue):
    response = _get()
    assert response.status_code == 303 and response.headers["location"] == "/signin"
    page = client.get("/signin")
    assert page.status_code == 200
    assert "Connect an app to Zero Page" in page.text
    # nothing has been asked of Supabase yet: there is no token to ask with
    assert not any(c[1].startswith("/oauth/") for c in gotrue.calls)


def test_a_session_on_this_site_is_not_enough(gotrue):
    """Our own cookie carries no Supabase token, so a person already
    signed in here still signs in for the consent -- and /signin does not
    shortcut them into the studio while a consent is waiting."""
    _sign_in()
    assert _get().headers["location"] == "/signin"
    page = client.get("/signin", follow_redirects=False)
    assert page.status_code == 200 and "Connect an app" in page.text


def test_a_missing_or_malformed_authorization_id_is_a_400_page_not_a_loop(gotrue):
    for bad in ("", "short", "../../etc", "a" * 300, "x%2Fy"):
        response = client.get(f"/oauth/consent?authorization_id={bad}",
                              follow_redirects=False)
        assert response.status_code == 400
        assert "missing its authorization request" in response.text


# ---------- the page ----------

def test_any_sign_in_comes_back_and_the_page_names_the_client_and_redirect_host(gotrue):
    _arrive_and_sign_in()
    page = _get()
    assert page.status_code == 200
    assert "Allow Claude to use your Zero Page Studio?" in page.text
    assert '<span class="host">claude.ai</span>' in page.text
    assert "ana@example.com" in page.text
    assert "openid, email" in page.text
    assert "this computer" not in page.text           # not a loopback redirect
    assert gotrue.calls[-1][:2] == ("GET", f"/oauth/authorizations/{AUTHZ}")


def test_a_loopback_redirect_carries_the_warning(gotrue):
    gotrue.requests[AUTHZ]["redirect_uri"] = "http://localhost:53682/callback"
    _arrive_and_sign_in()
    page = _get()
    assert "this computer" in page.text and '<span class="host">localhost</span>' in page.text


def test_describe_is_what_the_person_approves():
    shown = oauth_consent.describe({
        "redirect_uri": "http://127.0.0.1:9999/cb", "scope": "",
        "client": {"name": "", "uri": "not a url"}, "user": {}})
    assert shown["client_name"] == "An application"
    assert shown["redirect_host"] == "127.0.0.1" and shown["loopback"] is True
    assert shown["scopes"] == [] and shown["email"] == ""


def test_a_person_who_consented_before_goes_straight_back(gotrue):
    gotrue.consented[AUTHZ] = "ana@example.com"
    _arrive_and_sign_in()
    response = _get()
    assert response.status_code == 303
    assert response.headers["location"].startswith(CLAIMS_CALLBACK + "?code=again")


def test_an_expired_authorization_says_so_in_plain_words(gotrue):
    """Supabase forgets an authorization after about ten minutes and says
    "authorization not found" -- which, to the person who just signed in,
    reads like our bug (the 2026-10-08 walk hit it twice). The page says
    it expired and where to start again."""
    gotrue.requests.clear()
    _arrive_and_sign_in()
    page = _get()
    assert page.status_code == 400
    assert "has expired" in page.text and "connect again" in page.text
    assert "authorization not found" not in page.text


def test_a_request_that_expires_before_allow_says_so_too(gotrue):
    _arrive_and_sign_in()
    csrf = _csrf(_get().text)
    gotrue.requests.clear()          # the ten minutes ran out on this page
    response = client.post("/oauth/consent", data={"authorization_id": AUTHZ,
                                                   "decision": "approve", "csrf": csrf},
                           follow_redirects=False)
    assert response.status_code == 400 and "has expired" in response.text
    assert "location" not in response.headers


def test_any_other_refusal_still_shows_supabases_reason(gotrue, monkeypatch):
    _arrive_and_sign_in()
    real = gotrue.__call__

    def refusing(method, path, **kwargs):
        if path.startswith("/oauth/authorizations/"):
            return 400, {"msg": "client is disabled"}
        return real(method, path, **kwargs)

    monkeypatch.setattr(auth_mod, "gotrue", refusing)
    page = _get()
    assert page.status_code == 400 and "client is disabled" in page.text


# ---------- the decision ----------

def test_allow_approves_as_the_person_and_follows_supabases_redirect(gotrue):
    _arrive_and_sign_in()
    csrf = _csrf(_get().text)
    response = client.post("/oauth/consent", data={"authorization_id": AUTHZ,
                                                   "decision": "approve", "csrf": csrf},
                           follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == f"{CLAIMS_CALLBACK}?code=c0de&state=s"
    assert gotrue.decisions == [(AUTHZ, "approve", "ana@example.com")]


def _connections(dsn):
    from src import db
    with db.connect(dsn) as conn:
        return conn.execute("SELECT account_id, user_id, client_name, redirect_host, "
                            "approved_at FROM mcp_connections WHERE account_id IS NOT NULL "
                            "ORDER BY id").fetchall()


def test_allow_records_the_connection_the_page_showed(clean_slate, gotrue, monkeypatch):
    """The studio's "Connected to Claude" line: an approve writes the
    client and the redirect host the person saw, under their tenant."""
    from src import mcp_connections
    mcp_connections.init(clean_slate)
    monkeypatch.delenv("ZEROPAGE_OPEN_SIGNUP", raising=False)   # Ana gets a workspace
    _arrive_and_sign_in()
    csrf = _csrf(_get().text)
    response = client.post("/oauth/consent", data={"authorization_id": AUTHZ,
                                                   "decision": "approve", "csrf": csrf},
                           follow_redirects=False)
    assert response.status_code == 303, response.text[:400]
    (row,) = _connections(clean_slate)
    tenant = min(a["id"] for a in accounts.memberships("uid-ana", dsn=clean_slate))
    assert (row["account_id"], row["user_id"]) == (tenant, "uid-ana")
    assert (row["client_name"], row["redirect_host"]) == ("Claude", "claude.ai")
    assert row["approved_at"] is not None


def test_deny_records_nothing(clean_slate, gotrue, monkeypatch):
    from src import mcp_connections
    mcp_connections.init(clean_slate)
    monkeypatch.delenv("ZEROPAGE_OPEN_SIGNUP", raising=False)   # Ana gets a workspace
    _arrive_and_sign_in()
    csrf = _csrf(_get().text)
    client.post("/oauth/consent", data={"authorization_id": AUTHZ,
                                        "decision": "deny", "csrf": csrf},
                follow_redirects=False)
    assert _connections(clean_slate) == []


def test_a_failed_record_never_stands_between_the_person_and_the_app(gotrue, monkeypatch):
    from src import mcp_connections

    def broken(*args, **kwargs):
        raise RuntimeError("database is down")

    monkeypatch.setattr(mcp_connections, "record_approval", broken)
    _arrive_and_sign_in()
    csrf = _csrf(_get().text)
    response = client.post("/oauth/consent", data={"authorization_id": AUTHZ,
                                                   "decision": "approve", "csrf": csrf},
                           follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == f"{CLAIMS_CALLBACK}?code=c0de&state=s"


def test_deny_denies(gotrue):
    _arrive_and_sign_in()
    csrf = _csrf(_get().text)
    response = client.post("/oauth/consent", data={"authorization_id": AUTHZ,
                                                   "decision": "deny", "csrf": csrf},
                           follow_redirects=False)
    assert "error=access_denied" in response.headers["location"]
    assert gotrue.decisions == [(AUTHZ, "deny", "ana@example.com")]


def test_anything_but_allow_is_a_deny(gotrue):
    _arrive_and_sign_in()
    csrf = _csrf(_get().text)
    client.post("/oauth/consent", data={"authorization_id": AUTHZ,
                                        "decision": "APPROVE!", "csrf": csrf},
                follow_redirects=False)
    assert gotrue.decisions[-1][1] == "deny"


def test_a_wrong_csrf_is_refused_and_nothing_reaches_supabase(gotrue):
    _arrive_and_sign_in()
    _get()
    response = client.post("/oauth/consent", data={"authorization_id": AUTHZ,
                                                   "decision": "approve", "csrf": "forged"},
                           follow_redirects=False)
    assert response.status_code == 403
    assert gotrue.decisions == []


def test_the_token_is_spent_once(gotrue):
    _arrive_and_sign_in()
    csrf = _csrf(_get().text)
    data = {"authorization_id": AUTHZ, "decision": "approve", "csrf": csrf}
    client.post("/oauth/consent", data=data, follow_redirects=False)
    again = client.post("/oauth/consent", data=data, follow_redirects=False)
    assert again.status_code == 303 and again.headers["location"] == "/signin"
    assert len(gotrue.decisions) == 1


def test_a_grant_for_another_authorization_is_not_this_ones(gotrue):
    other = "11111111-2222-3333-4444-555555555555"
    gotrue.requests[other] = dict(gotrue.requests[AUTHZ])
    _arrive_and_sign_in()
    # the parked grant is AUTHZ's: the other request sends the person to sign in again
    assert _get(other).headers["location"] == "/signin"
    response = client.post("/oauth/consent", data={"authorization_id": other,
                                                   "decision": "approve", "csrf": "x"},
                           follow_redirects=False)
    assert response.headers["location"] == "/signin"
    assert gotrue.decisions == []


def test_a_redirect_that_is_not_http_is_never_followed(gotrue):
    gotrue.requests[AUTHZ]["redirect_uri"] = "javascript:alert(1)"
    _arrive_and_sign_in()
    csrf = _csrf(_get().text)
    response = client.post("/oauth/consent", data={"authorization_id": AUTHZ,
                                                   "decision": "approve", "csrf": csrf},
                           follow_redirects=False)
    assert response.status_code == 502
    assert "location" not in response.headers


# ---------- the workspace, and time ----------

def test_signing_in_here_creates_the_workspace(clean_slate, gotrue, monkeypatch):
    """A person whose first contact is the connector gets their workspace
    on this page -- the "one web sign-in first" rule, met on the way."""
    monkeypatch.delenv("ZEROPAGE_OPEN_SIGNUP", raising=False)
    _arrive_and_sign_in()
    assert accounts.memberships("uid-ana", dsn=clean_slate)


def test_a_pending_consent_expires(gotrue, monkeypatch):
    _get()
    later = time.time() + oauth_consent.PENDING_MAX_AGE + 5
    monkeypatch.setattr(oauth_consent.time, "time", lambda: later)
    page = client.get("/signin", follow_redirects=False)
    assert "Connect an app" not in page.text
    back = _sign_in()
    assert back.headers["location"] != f"/oauth/consent?authorization_id={AUTHZ}"


def test_an_expired_token_sends_the_person_to_sign_in_again(gotrue, monkeypatch):
    _arrive_and_sign_in()
    monkeypatch.setattr(auth_mod, "verify_token", lambda token, audience="authenticated": None)
    assert _get().headers["location"] == "/signin"
