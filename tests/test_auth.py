"""
Tests for the real sign-in: sessions, password flows, the OAuth
resolution ladder, and — most importantly — the membership gate. A
brand-new signup must never land inside Mike's real accounts; that
property is pinned here from every direction.

Hermetic: OAuth is tested at _resolve_oauth_user and at the callback
with Authlib + the Discord profile fetch patched; conftest's network
guard catches anything that slips.
"""
import pytest
from fastapi.testclient import TestClient

from app import auth as auth_mod
from app.main import app
from src import accounts, db

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_slate(tmp_path, monkeypatch):
    """Fresh DB with auth tables, fixed session secret, empty rate
    buckets — every test starts signed out."""
    path = tmp_path / "test.db"
    db.init_db(path)
    accounts.init(path)
    monkeypatch.setattr(db, "DB_PATH", path)
    monkeypatch.setenv("SESSION_SECRET", "test-secret-not-for-real-use")
    auth_mod._hits.clear()
    client.cookies.clear()
    return path


def signup(email="new@example.com", password="hunter2hunter2"):
    return client.post("/auth/signup", data={"email": email, "password": password},
                       follow_redirects=False)


def seed_mike(path, password="mikes-password-1"):
    return accounts.seed("mike@example.com",
                         password_hash=auth_mod.hash_password(password),
                         path=path)


# ---------- password signup / login ----------

def test_signup_creates_hashed_user_and_session(clean_slate):
    response = signup()
    assert response.status_code == 303
    assert response.headers["location"] == "/ui/accounts"
    assert auth_mod.SESSION_COOKIE in response.cookies

    user = accounts.get_user_by_email("new@example.com", path=clean_slate)
    assert user["password_hash"] is not None
    assert "hunter2" not in user["password_hash"]          # hashed, not plaintext
    assert user["password_hash"].startswith("$argon2")


def test_login_verifies_the_hash(clean_slate):
    signup()
    client.cookies.clear()
    response = client.post("/auth/login", data={
        "email": "new@example.com", "password": "hunter2hunter2",
    }, follow_redirects=False)
    assert response.status_code == 303
    assert auth_mod.SESSION_COOKIE in response.cookies


@pytest.mark.parametrize("email,password", [
    ("new@example.com", "wrong-password-x"),      # wrong password
    ("nobody@example.com", "hunter2hunter2"),     # unknown email
])
def test_login_failures_get_one_generic_error(clean_slate, email, password):
    signup()
    client.cookies.clear()
    response = client.post("/auth/login", data={"email": email, "password": password},
                           follow_redirects=False)
    assert response.status_code == 303
    assert "invalid%20email%20or%20password" in response.headers["location"]
    assert auth_mod.SESSION_COOKIE not in response.cookies


def test_signup_rejects_short_password(clean_slate):
    response = signup(password="short")
    assert "8" in response.headers["location"]
    assert accounts.get_user_by_email("new@example.com", path=clean_slate) is None


def test_duplicate_email_says_try_the_other_way(clean_slate):
    signup()
    response = signup()
    assert "already%20exists" in response.headers["location"]


def test_logout_clears_the_session(clean_slate):
    signup()
    # session live: /ui sends the (membership-less) user to the picker
    assert client.get("/ui", follow_redirects=False).headers["location"] == "/ui/accounts"
    client.post("/auth/logout", follow_redirects=False)
    assert client.get("/ui", follow_redirects=False).headers["location"] == "/signin"


# ---------- the membership gate ----------

def test_fresh_signup_has_zero_memberships_and_sees_no_access(clean_slate):
    """THE gate: completing sign-up must not open Mike's accounts."""
    signup()
    user = accounts.get_user_by_email("new@example.com", path=clean_slate)
    assert accounts.memberships(user["id"], path=clean_slate) == []

    page = client.get("/ui/accounts")
    assert "No account access yet" in page.text
    assert "Choose an account" not in page.text

    # and /ui bounces them to that state rather than the shell
    response = client.get("/ui", follow_redirects=False)
    assert response.headers["location"] == "/ui/accounts"


def test_seeded_mike_reaches_the_picker_with_both_brands(clean_slate):
    seed_mike(clean_slate)
    client.post("/auth/login", data={
        "email": "mike@example.com", "password": "mikes-password-1",
    }, follow_redirects=False)
    page = client.get("/ui/accounts")
    assert "Choose an account" in page.text
    assert "Zero Page Films" in page.text
    assert "ANTIHERO" in page.text
    assert "Invite a collaborator" in page.text


def test_picking_an_account_lands_in_the_shell(clean_slate):
    seed_mike(clean_slate)
    client.post("/auth/login", data={
        "email": "mike@example.com", "password": "mikes-password-1",
    }, follow_redirects=False)
    response = client.post("/brand/zeropage", data={"next": "/ui"},
                           follow_redirects=False)
    assert response.status_code == 303
    shell = client.get("/ui")
    assert 'data-brand="zeropage"' in shell.text


def test_brand_cookie_cannot_grant_an_account_you_are_not_in(clean_slate):
    """current_account is backed by membership: a forged/stale brand
    cookie can only pick among the accounts you actually belong to."""
    seed_mike(clean_slate)
    zp = accounts.get_user_by_email("mike@example.com", path=clean_slate)
    # a second user who is ONLY a member of antihero
    other = accounts.create_user("collab@example.com",
                                 password_hash=auth_mod.hash_password("collab-pass-1"),
                                 path=clean_slate)
    with db.connect(clean_slate) as conn:
        antihero = conn.execute(
            "SELECT id FROM accounts WHERE slug='antihero'").fetchone()["id"]
    accounts.add_member(antihero, other, path=clean_slate)
    assert zp is not None

    client.post("/auth/login", data={
        "email": "collab@example.com", "password": "collab-pass-1",
    }, follow_redirects=False)
    client.cookies.set("brand", "zeropage")       # forged preference
    shell = client.get("/ui")
    assert 'data-brand="antihero"' in shell.text  # membership wins


# ---------- gating /ui and /api ----------

def test_ui_without_session_redirects_to_signin(clean_slate):
    response = client.get("/ui", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/signin"


def test_signin_page_shows_all_three_methods(clean_slate):
    page = client.get("/signin")
    assert "Continue with Google" in page.text
    assert "Continue with Discord" in page.text
    assert 'action="/auth/login"' in page.text
    assert 'action="/auth/signup"' in page.text
    assert 'type="password"' in page.text


def test_api_without_session_is_401(clean_slate):
    response = client.get("/api/capabilities")
    assert response.status_code == 401


def test_api_with_session_works(clean_slate):
    signup()
    response = client.get("/api/capabilities")
    assert response.status_code == 200


def test_legacy_studio_stays_open(clean_slate):
    from src import entities, preprod
    preprod.init(clean_slate)
    entities.init(clean_slate)
    assert client.get("/studio").status_code == 200


def test_tampered_session_cookie_is_anonymous_not_500(clean_slate):
    client.cookies.set(auth_mod.SESSION_COOKIE, "garbage.token.here")
    response = client.get("/ui", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/signin"


# ---------- rate limiting ----------

def test_login_rate_limit_kicks_in(clean_slate):
    for _ in range(auth_mod.RATE_LIMITS["login"][0]):
        client.post("/auth/login", data={"email": "x@example.com",
                                         "password": "wrong-password"},
                    follow_redirects=False)
    response = client.post("/auth/login", data={"email": "x@example.com",
                                                "password": "wrong-password"},
                           follow_redirects=False)
    assert "too%20many%20attempts" in response.headers["location"]


# ---------- the OAuth resolution ladder ----------

def test_oauth_new_email_creates_user_and_identity_no_memberships(clean_slate):
    user_id, error = auth_mod._resolve_oauth_user(
        "google", "sub-123", "oauth@example.com", "OAuth Person", None)
    assert error is None
    user = accounts.get_user(user_id, path=clean_slate)
    assert user["email"] == "oauth@example.com"
    assert user["password_hash"] is None
    assert accounts.get_identity("google", "sub-123", path=clean_slate)["user_id"] == user_id
    assert accounts.memberships(user_id, path=clean_slate) == []   # the gate again


def test_oauth_existing_identity_signs_in(clean_slate):
    first, _ = auth_mod._resolve_oauth_user("discord", "d-1", "d@example.com", "D", None)
    again, error = auth_mod._resolve_oauth_user("discord", "d-1", "d@example.com", "D", None)
    assert error is None
    assert again == first


def test_oauth_claims_the_seeded_passwordless_user(clean_slate):
    """Mike seeds with email only; his first Google sign-in attaches the
    identity to that user instead of erroring or duplicating."""
    seeded = accounts.seed("mike@example.com", path=clean_slate)  # no password
    user_id, error = auth_mod._resolve_oauth_user(
        "google", "mike-sub", "mike@example.com", "Mike", None)
    assert error is None
    assert user_id == seeded["user_id"]
    assert len(accounts.memberships(user_id, path=clean_slate)) == 2


def test_oauth_email_collision_with_password_user_errors(clean_slate):
    signup(email="both@example.com")
    user_id, error = auth_mod._resolve_oauth_user(
        "google", "g-9", "both@example.com", "B", None)
    assert user_id is None
    assert "already exists" in error


def test_oauth_two_providers_can_link_to_one_user_via_identities(clean_slate):
    """auth_identities being its own table: the seeded user can hold
    google AND discord rows — two rows, one user_id."""
    seeded = accounts.seed("mike@example.com", path=clean_slate)
    google_id, _ = auth_mod._resolve_oauth_user(
        "google", "g-sub", "mike@example.com", None, None)
    assert google_id == seeded["user_id"]
    # second provider on the same (now identified) user is an explicit
    # add_identity — the natural account-linking path
    accounts.add_identity(seeded["user_id"], "discord", "d-sub", path=clean_slate)
    assert accounts.get_identity("discord", "d-sub", path=clean_slate)["user_id"] \
        == seeded["user_id"]


def test_oauth_null_email_is_a_clear_failure(clean_slate):
    user_id, error = auth_mod._resolve_oauth_user("discord", "d-77", None, "X", None)
    assert user_id is None
    assert "verified email" in error
    assert accounts.get_identity("discord", "d-77", path=clean_slate) is None


def test_discord_callback_unverified_email_errors(clean_slate, monkeypatch):
    """End-to-end through the callback with Authlib + profile patched:
    an unverified Discord email must not create a users row."""
    class FakeDiscord:
        async def authorize_access_token(self, request):
            return {"access_token": "tok"}

    class FakeOAuth:
        discord = FakeDiscord()

    monkeypatch.setattr(auth_mod, "_get_oauth", lambda: FakeOAuth())

    async def fake_profile(token):
        return {"id": "d-88", "email": "d88@example.com", "verified": False,
                "username": "d88"}

    monkeypatch.setattr(auth_mod, "fetch_discord_profile", fake_profile)
    response = client.get("/auth/discord/callback?code=x&state=y",
                          follow_redirects=False)
    assert response.status_code == 303
    assert "verified%20email" in response.headers["location"]
    assert accounts.get_user_by_email("d88@example.com", path=clean_slate) is None


def test_discord_callback_verified_email_signs_in(clean_slate, monkeypatch):
    class FakeDiscord:
        async def authorize_access_token(self, request):
            return {"access_token": "tok"}

    class FakeOAuth:
        discord = FakeDiscord()

    monkeypatch.setattr(auth_mod, "_get_oauth", lambda: FakeOAuth())

    async def fake_profile(token):
        return {"id": "d-99", "email": "d99@example.com", "verified": True,
                "username": "d99", "global_name": "D 99", "avatar": None}

    monkeypatch.setattr(auth_mod, "fetch_discord_profile", fake_profile)
    response = client.get("/auth/discord/callback?code=x&state=y",
                          follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/ui/accounts"
    assert auth_mod.SESSION_COOKIE in response.cookies
    user = accounts.get_user_by_email("d99@example.com", path=clean_slate)
    assert user["display_name"] == "D 99"


def test_unconfigured_provider_says_so(clean_slate, monkeypatch):
    for name in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"):
        monkeypatch.delenv(name, raising=False)
    response = client.get("/auth/google/login", follow_redirects=False)
    assert "configured" in response.headers["location"]
