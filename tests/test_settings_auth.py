"""
Settings and passwords (2026-10-03, Mike: "Supabase didn't send a code
or allow a new user to create a password ... we need to build out
settings and password change etc").

Two doors onto one write. On the sign-in page: "Create a password"
(POST /auth/signup with a confirm field) and "Forgot your password?"
(POST /auth/forgot -> a recovery code or link -> POST /auth/reset). On
/studio/settings: PATCH /api/me (the name), POST /api/me/password and
POST /api/me/email, each re-proving the person with their current
password or a code mailed by POST /api/me/security/code. Every
password write goes through GoTrue's PUT /user AS THE PERSON with a
session minted for that one call; nothing of Supabase's is stored.

Hermetic behind the same seam as test_auth (FakeGoTrue, extended with
/recover, /verify type=recovery and PUT /user, which checks a real
signed token). conftest's guard catches anything that slips.
"""
import pytest
from fastapi.testclient import TestClient
from test_auth import JWT_SECRET, FakeGoTrue

from app import auth as auth_mod
from app.main import app
from src import accounts

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_slate(pg, monkeypatch):
    accounts.init(pg)
    monkeypatch.setenv("DATABASE_URL", pg)
    monkeypatch.setenv("SESSION_SECRET", "test-secret-not-for-real-use")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-key")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", JWT_SECRET)
    monkeypatch.setenv("ZEROPAGE_OPEN_SIGNUP", "1")
    monkeypatch.delenv("ZEROPAGE_SIGNUP_CREDITS", raising=False)
    monkeypatch.delenv("STUDIO_URL", raising=False)
    auth_mod._hits.clear()
    client.cookies.clear()
    return pg


@pytest.fixture
def gotrue(monkeypatch):
    fake = FakeGoTrue()
    monkeypatch.setattr(auth_mod, "gotrue", fake)
    return fake


def signup(email="new@example.com", password="hunter2hunter2", password2=None):
    data = {"email": email, "password": password}
    if password2 is not None:
        data["password2"] = password2
    return client.post("/auth/signup", data=data, follow_redirects=False)


def login(email, password):
    return client.post("/auth/login", data={"email": email, "password": password},
                       follow_redirects=False)


def puts(gotrue):
    return [c for c in gotrue.calls if c[0] == "PUT" and c[1] == "/user"]


def user(dsn, email="new@example.com"):
    return accounts.get_user_by_email(email, dsn=dsn)


# ---------- the sign-in page: create a password ----------

def test_the_signup_step_is_on_the_page_and_reopens_on_error(clean_slate, gotrue):
    page = client.get("/signin?open=signup")
    assert 'data-open="signup"' in page.text
    assert 'name="password2"' in page.text
    response = signup(password2="something-else")
    assert response.status_code == 303
    assert "don%27t%20match" in response.headers["location"]
    assert "open=signup" in response.headers["location"]
    assert gotrue.calls == []                      # refused before Supabase


def test_a_password_signup_is_remembered_as_having_a_password(clean_slate, gotrue):
    response = signup(password2="hunter2hunter2")
    assert response.status_code == 303
    assert auth_mod.SESSION_COOKIE in response.cookies
    assert user(clean_slate)["password_set_at"] is not None


def test_a_code_signup_has_no_password_until_one_is_set(clean_slate, gotrue):
    gotrue.register("otp@example.com")
    accounts.claim("uid-otp", "otp@example.com", dsn=clean_slate)
    assert user(clean_slate, "otp@example.com")["password_set_at"] is None
    assert accounts.has_password("uid-otp", dsn=clean_slate) is False


def test_an_existing_email_is_sent_to_the_password_door(clean_slate, gotrue):
    gotrue.register("new@example.com", "old-password-1")
    response = signup()
    assert "open=password" in response.headers["location"]
    assert "reset" in response.headers["location"]


def test_a_password_login_stamps_the_password(clean_slate, gotrue):
    gotrue.register("new@example.com", "hunter2hunter2")
    accounts.claim("uid-new", "new@example.com", dsn=clean_slate)
    assert user(clean_slate)["password_set_at"] is None
    assert login("new@example.com", "hunter2hunter2").status_code == 303
    assert user(clean_slate)["password_set_at"] is not None


# ---------- the sign-in page: forgot / reset ----------

def test_forgot_sends_a_recovery_code_with_a_pkce_link_and_lands_on_reset(clean_slate, gotrue):
    gotrue.register("new@example.com", "old-password-1")
    response = client.post("/auth/forgot", data={"email": " New@Example.com "},
                           follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/signin?step=reset&email=new%40example.com"
    method, path, body, params = gotrue.calls[-1]
    assert (method, path) == ("POST", "/recover")
    assert body["email"] == "new@example.com"
    assert body["code_challenge"] and body["code_challenge_method"] == "s256"
    assert params["redirect_to"].endswith("/auth/callback")
    page = client.get(response.headers["location"])
    assert 'action="/auth/reset"' in page.text and 'name="token"' in page.text


def test_forgot_never_says_whether_the_address_exists(clean_slate, gotrue):
    response = client.post("/auth/forgot", data={"email": "nobody@example.com"},
                           follow_redirects=False)
    assert response.headers["location"] == "/signin?step=reset&email=nobody%40example.com"


def test_reset_with_the_code_sets_the_password_and_signs_in(clean_slate, gotrue):
    gotrue.register("new@example.com", "old-password-1", uid="uid-new")
    client.post("/auth/forgot", data={"email": "new@example.com"}, follow_redirects=False)
    response = client.post("/auth/reset", data={
        "email": "new@example.com", "token": "654321",
        "password": "brand-new-pass", "password2": "brand-new-pass"},
        follow_redirects=False)
    assert response.status_code == 303, response.headers.get("location")
    assert auth_mod.SESSION_COOKIE in response.cookies
    assert gotrue.users["new@example.com"]["password"] == "brand-new-pass"
    assert len(puts(gotrue)) == 1
    assert user(clean_slate)["password_set_at"] is not None
    client.cookies.clear()
    assert auth_mod.SESSION_COOKIE in login("new@example.com", "brand-new-pass").cookies


def test_a_wrong_code_changes_nothing_and_stays_on_the_reset_step(clean_slate, gotrue):
    gotrue.register("new@example.com", "old-password-1")
    client.post("/auth/forgot", data={"email": "new@example.com"}, follow_redirects=False)
    response = client.post("/auth/reset", data={
        "email": "new@example.com", "token": "000000",
        "password": "brand-new-pass", "password2": "brand-new-pass"},
        follow_redirects=False)
    assert "step=reset" in response.headers["location"]
    assert "didn%27t+work" in response.headers["location"]
    assert auth_mod.SESSION_COOKIE not in response.cookies
    assert puts(gotrue) == []
    assert gotrue.users["new@example.com"]["password"] == "old-password-1"


def test_a_mismatched_reset_never_reaches_supabase(clean_slate, gotrue):
    gotrue.register("new@example.com", "old-password-1")
    client.post("/auth/forgot", data={"email": "new@example.com"}, follow_redirects=False)
    before = len(gotrue.calls)
    response = client.post("/auth/reset", data={
        "email": "new@example.com", "token": "654321",
        "password": "brand-new-pass", "password2": "other"}, follow_redirects=False)
    assert "match" in response.headers["location"]
    assert len(gotrue.calls) == before


def test_the_recovery_link_lands_on_the_new_password_step_then_sets_it(clean_slate, gotrue):
    """The person clicked the link in the email instead of typing the
    code: the callback must NOT sign them in and skip the password --
    that is what they came for."""
    gotrue.register("new@example.com", "old-password-1", uid="uid-new")
    client.post("/auth/forgot", data={"email": "new@example.com"}, follow_redirects=False)
    landed = client.get("/auth/callback?code=rec-new@example.com", follow_redirects=False)
    assert landed.status_code == 303
    assert landed.headers["location"] == "/signin?step=newpassword&email=new%40example.com"
    assert auth_mod.SESSION_COOKIE not in landed.cookies
    page = client.get(landed.headers["location"])
    assert "Choose a new password" in page.text and 'name="token"' not in page.text
    response = client.post("/auth/reset", data={
        "password": "brand-new-pass", "password2": "brand-new-pass"}, follow_redirects=False)
    assert auth_mod.SESSION_COOKIE in response.cookies
    assert gotrue.users["new@example.com"]["password"] == "brand-new-pass"
    # the parked token is spent: a second post is a stale link
    again = client.post("/auth/reset", data={
        "password": "third-pass-xx", "password2": "third-pass-xx"}, follow_redirects=False)
    assert "expired" in again.headers["location"]


def test_an_ordinary_oauth_return_still_signs_straight_in(clean_slate, gotrue):
    gotrue.register("g@example.com", provider="google", uid="uid-g")
    gotrue.codes["abc"] = "g@example.com"
    client.post("/auth/forgot", data={"email": "g@example.com"}, follow_redirects=False)
    # ...but the person then used Google in the same browser: the
    # recovery flag is consumed and they are signed in, not asked for a
    # password they never wanted
    auth_mod._hits.clear()
    with client as c:
        c.get("/auth/google/login", follow_redirects=False)
        landed = c.get("/auth/callback?code=abc", follow_redirects=False)
    assert landed.status_code == 303
    # the flag from /forgot was still set, so this lands on newpassword;
    # the next OAuth return in a fresh session does not
    client.cookies.clear()
    with client as c:
        c.get("/auth/google/login", follow_redirects=False)
        gotrue.codes["abc2"] = "g@example.com"
        landed = c.get("/auth/callback?code=abc2", follow_redirects=False)
    assert auth_mod.SESSION_COOKIE in landed.cookies


# ---------- the settings API ----------

def signed_in(gotrue, email="new@example.com", password=None, uid=None):
    """A signed-in client with its own workspace (open sign-up)."""
    if password:
        gotrue.register(email, password, uid=uid)
        response = login(email, password)
    else:
        gotrue.register(email, uid=uid)
        gotrue.codes["x"] = email
        with client as c:
            c.get("/auth/google/login", follow_redirects=False)
            response = c.get("/auth/callback?code=x", follow_redirects=False)
    assert auth_mod.SESSION_COOKIE in response.cookies
    return response


def test_rename_yourself(clean_slate, gotrue):
    signed_in(gotrue)
    assert client.get("/api/me").json()["user"]["display_name"] == "new"
    answer = client.patch("/api/me", json={"display_name": "  Maya R  "})
    assert answer.status_code == 200, answer.text
    assert answer.json()["user"]["display_name"] == "Maya R"
    assert client.get("/api/me").json()["user"]["display_name"] == "Maya R"
    # blank clears, and the shell's fallback (the local part) returns
    client.patch("/api/me", json={"display_name": ""})
    assert client.get("/api/me").json()["user"]["display_name"] == "new"
    assert user(clean_slate)["display_name"] is None
    assert client.patch("/api/me", json={}).status_code == 400
    assert client.patch("/api/me", json={"display_name": "x" * 81}).status_code == 400


def test_security_says_whether_a_password_is_known(clean_slate, gotrue):
    signed_in(gotrue)                                  # Google: no password
    card = client.get("/api/me/security").json()
    assert card == {"email": "new@example.com", "has_password": False,
                    "password_set_at": None, "can_change": True, "min_password_len": 8}
    client.cookies.clear()
    auth_mod._hits.clear()
    signed_in(gotrue, "pw@example.com", "hunter2hunter2")
    assert client.get("/api/me/security").json()["has_password"] is True


def test_the_settings_routes_are_behind_the_session(clean_slate, gotrue):
    for method, path in (("GET", "/api/me/security"), ("PATCH", "/api/me"),
                         ("POST", "/api/me/password"), ("POST", "/api/me/email"),
                         ("POST", "/api/me/security/code")):
        assert client.request(method, path, json={}).status_code == 401, path


def test_set_a_first_password_with_an_emailed_code(clean_slate, gotrue):
    signed_in(gotrue, uid="uid-new")                   # Google, no password
    sent = client.post("/api/me/security/code")
    assert sent.status_code == 200, sent.text
    assert sent.json() == {"sent": True, "email": "new@example.com"}
    method, path, body, params = gotrue.calls[-1]
    assert (method, path) == ("POST", "/recover")
    assert "code_challenge" not in body and not params   # the code is the thing
    answer = client.post("/api/me/password", json={
        "password": "my-first-pass", "password2": "my-first-pass", "code": "654321"})
    assert answer.status_code == 200, answer.text
    assert answer.json()["ok"] is True and answer.json()["has_password"] is True
    assert gotrue.users["new@example.com"]["password"] == "my-first-pass"
    assert len(puts(gotrue)) == 1
    # and it works at the door
    client.cookies.clear()
    assert auth_mod.SESSION_COOKIE in login("new@example.com", "my-first-pass").cookies


def test_change_the_password_with_the_current_one(clean_slate, gotrue):
    signed_in(gotrue, "pw@example.com", "hunter2hunter2", uid="uid-pw")
    wrong = client.post("/api/me/password", json={
        "password": "another-pass-1", "current_password": "nope-nope-nope"})
    assert wrong.status_code == 400
    assert wrong.json()["error"]["code"] == "wrong_password"
    assert puts(gotrue) == []
    right = client.post("/api/me/password", json={
        "password": "another-pass-1", "password2": "another-pass-1",
        "current_password": "hunter2hunter2"})
    assert right.status_code == 200, right.text
    assert gotrue.users["pw@example.com"]["password"] == "another-pass-1"
    assert len(puts(gotrue)) == 1


def test_a_password_write_needs_proof_and_a_real_password(clean_slate, gotrue):
    signed_in(gotrue, "pw@example.com", "hunter2hunter2")
    before = len(gotrue.calls)
    no_proof = client.post("/api/me/password", json={"password": "another-pass-1"})
    assert no_proof.status_code == 400
    assert no_proof.json()["error"]["code"] == "proof_required"
    short = client.post("/api/me/password", json={
        "password": "short", "current_password": "hunter2hunter2"})
    assert short.status_code == 400 and short.json()["error"]["code"] == "weak_password"
    mismatch = client.post("/api/me/password", json={
        "password": "another-pass-1", "password2": "another-pass-2",
        "current_password": "hunter2hunter2"})
    assert mismatch.status_code == 400
    assert len(gotrue.calls) == before                 # nothing reached Supabase
    bad_code = client.post("/api/me/password", json={
        "password": "another-pass-1", "code": "111111"})
    assert bad_code.status_code == 400 and bad_code.json()["error"]["code"] == "bad_code"


def test_password_writes_are_rate_limited(clean_slate, gotrue):
    signed_in(gotrue, "pw@example.com", "hunter2hunter2")
    for _ in range(10):
        client.post("/api/me/password", json={"password": "another-pass-1",
                                              "current_password": "wrong-wrong"})
    answer = client.post("/api/me/password", json={"password": "another-pass-1",
                                                   "current_password": "hunter2hunter2"})
    assert answer.status_code == 429


def test_change_the_email_and_the_mirror_follows_at_the_next_sign_in(clean_slate, gotrue):
    signed_in(gotrue, "pw@example.com", "hunter2hunter2", uid="uid-pw")
    same = client.post("/api/me/email", json={"email": "PW@example.com",
                                              "current_password": "hunter2hunter2"})
    assert same.status_code == 400 and same.json()["error"]["code"] == "same_email"
    answer = client.post("/api/me/email", json={"email": "Maya@Example.com",
                                                "current_password": "hunter2hunter2"})
    assert answer.status_code == 200, answer.text
    assert answer.json()["pending"] == "maya@example.com"
    assert puts(gotrue)[-1][2] == {"email": "maya@example.com"}
    # nothing moved yet: Supabase is waiting for the confirmation click
    assert user(clean_slate, "pw@example.com")["id"] == "uid-pw"
    assert client.get("/api/me").json()["user"]["email"] == "pw@example.com"
    # the click, then a sign-in from the new address: same uuid, new email
    gotrue.confirm_email_change("pw@example.com")
    client.cookies.clear()
    auth_mod._hits.clear()
    assert login("maya@example.com", "hunter2hunter2").status_code == 303
    assert user(clean_slate, "maya@example.com")["id"] == "uid-pw"
    assert user(clean_slate, "pw@example.com") is None
    assert client.get("/api/me").json()["user"]["email"] == "maya@example.com"


def test_an_email_another_mirror_row_holds_is_refused(clean_slate, gotrue):
    accounts.create_user("taken@example.com", dsn=clean_slate)   # an invite, say
    signed_in(gotrue, "pw@example.com", "hunter2hunter2")
    answer = client.post("/api/me/email", json={"email": "taken@example.com",
                                                "current_password": "hunter2hunter2"})
    assert answer.status_code == 409
    assert puts(gotrue) == []


def test_claim_never_steals_an_address_held_by_another_row(clean_slate, gotrue):
    """The sync in accounts.claim is for the person's OWN moved identity;
    an address some other mirror row holds (an unclaimed invite) is left
    where it is rather than merged."""
    accounts.create_user("taken@example.com", dsn=clean_slate)
    accounts.claim("uid-a", "a@example.com", dsn=clean_slate)
    uid, error = accounts.claim("uid-a", "taken@example.com", dsn=clean_slate)
    assert (uid, error) == ("uid-a", None)
    assert user(clean_slate, "a@example.com")["id"] == "uid-a"
    assert user(clean_slate, "taken@example.com")["id"] != "uid-a"
