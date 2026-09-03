"""
Tests for the real sign-in on Supabase Auth: sessions, the password
doors, the OAuth doors, the claim ladder, and — most importantly — the
membership gate. A brand-new sign-in must never land inside Mike's real
accounts; that property is pinned here from every direction.

Hermetic: `FakeGoTrue` stands in for Supabase's auth server behind the
one seam the module talks to it through (auth.gotrue); it signs real
HS256 tokens with the test secret, so verify_token runs for real.
conftest's network guard catches anything that slips past the seam.
"""
import time

import jwt
import pytest
from fastapi.testclient import TestClient

from app import auth as auth_mod
from app.main import app
from src import accounts, db

client = TestClient(app)

JWT_SECRET = "test-jwt-secret-that-is-at-least-32-bytes-long"


class FakeGoTrue:
    """An in-memory Supabase Auth: users keyed by email, one uuid each,
    a real JWT per sign-in. Answers the three endpoints auth.py uses."""

    def __init__(self):
        self.users: dict[str, dict] = {}     # email -> {uid, password, meta}
        self.codes: dict[str, str] = {}      # auth_code -> email
        self.calls: list = []
        self.confirm_email = False

    def register(self, email, password=None, uid=None, provider="email", **meta):
        uid = uid or f"uid-{email.split('@')[0]}"
        self.users[email] = {"uid": uid, "password": password, "provider": provider,
                             "meta": meta}
        return uid

    def token_for(self, email):
        u = self.users[email]
        return jwt.encode({"sub": u["uid"], "email": email, "aud": "authenticated",
                           "exp": int(time.time()) + 3600,
                           "app_metadata": {"provider": u["provider"]},
                           "user_metadata": u["meta"]}, JWT_SECRET, algorithm="HS256")

    def session(self, email):
        return {"access_token": self.token_for(email), "token_type": "bearer",
                "refresh_token": "r", "user": {"id": self.users[email]["uid"],
                                               "email": email}}

    def __call__(self, method, path, *, json=None, params=None):
        self.calls.append((method, path, json, params))
        if path == "/signup":
            email = json["email"]
            if email in self.users:
                return 422, {"code": 422, "error_code": "user_already_exists",
                             "msg": "User already registered"}
            self.register(email, json["password"])
            if self.confirm_email:
                return 200, {"id": self.users[email]["uid"], "email": email}
            return 200, self.session(email)
        if path == "/token" and params == {"grant_type": "password"}:
            u = self.users.get(json["email"])
            if not u or u["password"] != json["password"]:
                return 400, {"error": "invalid_grant",
                             "error_description": "Invalid login credentials"}
            return 200, self.session(json["email"])
        if path == "/token" and params == {"grant_type": "pkce"}:
            email = self.codes.pop(json["auth_code"], None)
            if not email or not json.get("code_verifier"):
                return 400, {"error": "invalid_grant", "error_description": "bad code"}
            return 200, self.session(email)
        return 404, {}


@pytest.fixture(autouse=True)
def clean_slate(pg, monkeypatch):
    """Fresh schema with the account tables, Supabase 'configured', the
    fake GoTrue behind the seam, a fixed session secret, empty rate
    buckets — every test starts signed out. The routes reach the schema
    through DATABASE_URL."""
    accounts.init(pg)
    monkeypatch.setenv("DATABASE_URL", pg)
    monkeypatch.setenv("SESSION_SECRET", "test-secret-not-for-real-use")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-key")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", JWT_SECRET)
    monkeypatch.delenv("SUPABASE_PROVIDERS", raising=False)
    auth_mod._hits.clear()
    client.cookies.clear()
    return pg


@pytest.fixture
def gotrue(monkeypatch):
    fake = FakeGoTrue()
    monkeypatch.setattr(auth_mod, "gotrue", fake)
    return fake


def signup(email="new@example.com", password="hunter2hunter2"):
    return client.post("/auth/signup", data={"email": email, "password": password},
                       follow_redirects=False)


def login(email, password):
    return client.post("/auth/login", data={"email": email, "password": password},
                       follow_redirects=False)


def seed_mike(path, gotrue, password="mikes-password-1"):
    """Mike is seeded by email (unclaimed); Supabase knows his password."""
    gotrue.register("mike@example.com", password, uid="uid-mike-supabase")
    return accounts.seed("mike@example.com", dsn=path)


# ---------- password doors ----------

def test_signup_makes_a_mirror_row_and_a_session_and_stores_no_password(clean_slate, gotrue):
    response = signup()
    assert response.status_code == 303
    assert response.headers["location"] == "/ui/accounts"
    assert auth_mod.SESSION_COOKIE in response.cookies

    user = accounts.get_user_by_email("new@example.com", dsn=clean_slate)
    assert user["id"] == gotrue.users["new@example.com"]["uid"]   # the Supabase id
    assert user["claimed_at"] is not None
    assert "password_hash" not in user                             # Supabase's, not ours
    assert gotrue.calls[0][1] == "/signup"


def test_login_goes_through_gotrue(clean_slate, gotrue):
    signup()
    client.cookies.clear()
    response = login("new@example.com", "hunter2hunter2")
    assert response.status_code == 303
    assert auth_mod.SESSION_COOKIE in response.cookies
    assert gotrue.calls[-1][3] == {"grant_type": "password"}


@pytest.mark.parametrize("email,password", [
    ("new@example.com", "wrong-password-x"),      # wrong password
    ("nobody@example.com", "hunter2hunter2"),     # unknown email
])
def test_login_failures_get_one_generic_error(clean_slate, gotrue, email, password):
    signup()
    client.cookies.clear()
    response = login(email, password)
    assert response.status_code == 303
    assert "invalid%20email%20or%20password" in response.headers["location"]
    assert auth_mod.SESSION_COOKIE not in response.cookies


def test_signup_rejects_short_password_before_calling_supabase(clean_slate, gotrue):
    response = signup(password="short")
    assert "8" in response.headers["location"]
    assert gotrue.calls == []
    assert accounts.get_user_by_email("new@example.com", dsn=clean_slate) is None


def test_duplicate_email_says_try_the_other_way(clean_slate, gotrue):
    signup()
    response = signup()
    assert "already%20exists" in response.headers["location"]


def test_signup_with_email_confirmation_on_makes_no_session_yet(clean_slate, gotrue):
    gotrue.confirm_email = True
    response = signup()
    assert response.status_code == 303
    assert "check%20your%20email" in response.headers["location"]
    assert auth_mod.SESSION_COOKIE not in response.cookies
    # and no mirror row: the person has not proved the address yet
    assert accounts.get_user_by_email("new@example.com", dsn=clean_slate) is None


def test_logout_clears_the_session(clean_slate, gotrue):
    signup()
    assert client.get("/ui", follow_redirects=False).headers["location"] == "/ui/accounts"
    client.post("/auth/logout", follow_redirects=False)
    assert client.get("/ui", follow_redirects=False).headers["location"] == "/signin"


def test_unconfigured_supabase_says_so(clean_slate, gotrue, monkeypatch):
    monkeypatch.delenv("SUPABASE_URL")
    assert "configured" in signup().headers["location"]
    assert "configured" in login("a@b.co", "x" * 9).headers["location"]
    assert "configured" in client.get("/auth/google/login",
                                      follow_redirects=False).headers["location"]
    assert gotrue.calls == []


# ---------- the membership gate ----------

def test_fresh_signup_has_zero_memberships_and_sees_no_access(clean_slate, gotrue):
    """THE gate: completing sign-up must not open Mike's accounts."""
    signup()
    user = accounts.get_user_by_email("new@example.com", dsn=clean_slate)
    assert accounts.memberships(user["id"], dsn=clean_slate) == []

    page = client.get("/ui/accounts")
    assert "No account access yet" in page.text
    assert "Choose an account" not in page.text
    response = client.get("/ui", follow_redirects=False)
    assert response.headers["location"] == "/ui/accounts"


def test_seeded_mike_reaches_the_picker_with_both_brands(clean_slate, gotrue):
    seed_mike(clean_slate, gotrue)
    login("mike@example.com", "mikes-password-1")
    page = client.get("/ui/accounts")
    assert "Choose an account" in page.text
    assert "Zero Page Films" in page.text
    assert "ANTIHERO" in page.text
    assert "Invite a collaborator" in page.text


def test_the_first_sign_in_claims_the_seeded_row_and_its_memberships(clean_slate, gotrue):
    seeded = seed_mike(clean_slate, gotrue)
    assert accounts.get_user(seeded["user_id"], dsn=clean_slate)["claimed_at"] is None
    login("mike@example.com", "mikes-password-1")
    mike = accounts.get_user_by_email("mike@example.com", dsn=clean_slate)
    assert mike["id"] == "uid-mike-supabase"        # the row's id became Supabase's
    assert mike["claimed_at"] is not None
    assert len(accounts.memberships("uid-mike-supabase", dsn=clean_slate)) == 2
    assert accounts.get_user(seeded["user_id"], dsn=clean_slate) is None   # placeholder gone


def test_picking_an_account_lands_in_the_shell(clean_slate, gotrue):
    seed_mike(clean_slate, gotrue)
    login("mike@example.com", "mikes-password-1")
    response = client.post("/brand/zeropage", data={"next": "/ui"},
                           follow_redirects=False)
    assert response.status_code == 303
    shell = client.get("/ui")
    assert 'data-brand="zeropage"' in shell.text


def test_brand_cookie_cannot_grant_an_account_you_are_not_in(clean_slate, gotrue):
    """current_account is backed by membership: a forged/stale brand
    cookie can only pick among the accounts you actually belong to."""
    seed_mike(clean_slate, gotrue)
    other_uid = gotrue.register("collab@example.com", "collab-pass-1")
    other = accounts.create_user("collab@example.com", user_id=other_uid, claimed=True,
                                 dsn=clean_slate)
    with db.connect(clean_slate) as conn:
        antihero = conn.execute(
            "SELECT id FROM accounts WHERE slug='antihero'").fetchone()["id"]
    accounts.add_member(antihero, other, dsn=clean_slate)

    login("collab@example.com", "collab-pass-1")
    client.cookies.set("brand", "zeropage")       # forged preference
    shell = client.get("/ui")
    assert 'data-brand="antihero"' in shell.text  # membership wins


# ---------- gating /ui and /api ----------

def test_ui_without_session_redirects_to_signin(clean_slate):
    response = client.get("/ui", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/signin"


def test_signin_page_shows_the_providers_supabase_has(clean_slate, monkeypatch):
    """Provider buttons follow SUPABASE_PROVIDERS -- what is switched on
    in the dashboard, which the app cannot read. Email/password is
    always there."""
    monkeypatch.setenv("SUPABASE_PROVIDERS", "google")
    page = client.get("/signin")
    assert "Continue with Google" in page.text
    assert "Continue with Discord" not in page.text
    assert 'action="/auth/login"' in page.text
    assert 'action="/auth/signup"' in page.text
    assert 'type="password"' in page.text


def test_signin_page_shows_both_by_default(clean_slate):
    page = client.get("/signin")
    assert "Continue with Google" in page.text
    assert "Continue with Discord" in page.text


def test_signin_page_hides_oauth_when_supabase_is_not_configured(clean_slate, monkeypatch):
    monkeypatch.delenv("SUPABASE_ANON_KEY")
    page = client.get("/signin")
    assert "Continue with Google" not in page.text
    assert 'action="/auth/login"' in page.text


def test_api_without_session_is_401(clean_slate):
    assert client.get("/api/capabilities").status_code == 401


def test_api_with_session_works(clean_slate, gotrue):
    signup()
    assert client.get("/api/capabilities").status_code == 200


def test_legacy_studio_stays_open(clean_slate):
    from src import autonomy, entities, evalstore, preprod, settings
    preprod.init(clean_slate)
    entities.init(clean_slate)
    autonomy.init(clean_slate)
    evalstore.init(clean_slate)
    settings.init(clean_slate)
    assert client.get("/studio").status_code == 200


def test_tampered_session_cookie_is_anonymous_not_500(clean_slate):
    client.cookies.set(auth_mod.SESSION_COOKIE, "garbage.token.here")
    response = client.get("/ui", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/signin"


def test_a_session_for_a_user_supabase_forgot_is_anonymous(clean_slate, gotrue):
    """A cookie is only as good as the mirror row it names."""
    signup()
    with db.connect(clean_slate) as conn:
        conn.execute("DELETE FROM users")
    assert client.get("/ui", follow_redirects=False).headers["location"] == "/signin"


# ---------- rate limiting ----------

def test_login_rate_limit_kicks_in(clean_slate, gotrue):
    for _ in range(auth_mod.RATE_LIMITS["login"][0]):
        login("x@example.com", "wrong-password")
    response = login("x@example.com", "wrong-password")
    assert "too%20many%20attempts" in response.headers["location"]


# ---------- the token ----------

def test_verify_token_rejects_a_foreign_signature_and_the_wrong_audience(clean_slate):
    good = jwt.encode({"sub": "u", "aud": "authenticated",
                       "exp": int(time.time()) + 60}, JWT_SECRET, algorithm="HS256")
    forged = jwt.encode({"sub": "u", "aud": "authenticated",
                         "exp": int(time.time()) + 60}, "x" * 40, algorithm="HS256")
    anon = jwt.encode({"role": "anon", "aud": "anon",
                       "exp": int(time.time()) + 60}, JWT_SECRET, algorithm="HS256")
    expired = jwt.encode({"sub": "u", "aud": "authenticated",
                          "exp": int(time.time()) - 60}, JWT_SECRET, algorithm="HS256")
    assert auth_mod.verify_token(good)["sub"] == "u"
    assert auth_mod.verify_token(forged) is None
    assert auth_mod.verify_token(anon) is None
    assert auth_mod.verify_token(expired) is None
    assert auth_mod.verify_token("not.a.jwt") is None


def test_a_gotrue_session_whose_token_does_not_verify_is_refused(clean_slate, gotrue):
    """The seam returned 200 but the token is not the project's: no
    cookie, no row."""
    forged = jwt.encode({"sub": "evil", "email": "evil@example.com",
                         "aud": "authenticated", "exp": int(time.time()) + 60},
                        "x" * 40, algorithm="HS256")
    gotrue.register("evil@example.com", "pw")
    gotrue.token_for = lambda email: forged
    response = login("evil@example.com", "pw")
    assert "verified" in response.headers["location"]
    assert auth_mod.SESSION_COOKIE not in response.cookies
    assert accounts.get_user_by_email("evil@example.com", dsn=clean_slate) is None


# ---------- the claim ladder ----------

def test_claim_new_email_makes_a_mirror_row_with_no_memberships(clean_slate):
    uid, error = accounts.claim("sb-123", "oauth@example.com", "OAuth Person", None,
                                dsn=clean_slate)
    assert error is None and uid == "sb-123"
    user = accounts.get_user("sb-123", dsn=clean_slate)
    assert user["email"] == "oauth@example.com" and user["display_name"] == "OAuth Person"
    assert accounts.memberships("sb-123", dsn=clean_slate) == []   # the gate again


def test_claim_existing_id_signs_in_and_keeps_the_profile(clean_slate):
    accounts.claim("sb-1", "d@example.com", "D", None, dsn=clean_slate)
    again, error = accounts.claim("sb-1", "d@example.com", "Renamed", "http://a", dsn=clean_slate)
    assert error is None and again == "sb-1"
    user = accounts.get_user("sb-1", dsn=clean_slate)
    assert user["display_name"] == "D"            # never clobbered
    assert user["avatar_url"] == "http://a"      # filled in when empty


def test_claim_takes_the_seeded_unclaimed_row(clean_slate):
    """Mike seeds with email only; his first sign-in attaches the
    Supabase id to that row instead of erroring or duplicating."""
    seeded = accounts.seed("mike@example.com", dsn=clean_slate)
    uid, error = accounts.claim("mike-sb", "mike@example.com", "Mike", None, dsn=clean_slate)
    assert error is None and uid == "mike-sb"
    assert accounts.get_user(seeded["user_id"], dsn=clean_slate) is None
    assert len(accounts.memberships("mike-sb", dsn=clean_slate)) == 2


def test_claim_refuses_an_email_already_claimed_by_another_id(clean_slate):
    accounts.claim("sb-first", "both@example.com", "B", None, dsn=clean_slate)
    uid, error = accounts.claim("sb-second", "both@example.com", "B", None, dsn=clean_slate)
    assert uid is None and "already exists" in error
    assert accounts.get_user("sb-second", dsn=clean_slate) is None


def test_claim_null_email_is_a_clear_failure(clean_slate):
    uid, error = accounts.claim("sb-77", None, "X", None, dsn=clean_slate)
    assert uid is None and "verified email" in error
    assert accounts.get_user("sb-77", dsn=clean_slate) is None


# ---------- the OAuth doors ----------

def test_oauth_login_redirects_to_supabase_with_pkce(clean_slate, gotrue):
    response = client.get("/auth/google/login", follow_redirects=False)
    assert response.status_code == 303
    location = response.headers["location"]
    assert location.startswith("https://example.supabase.co/auth/v1/authorize?")
    assert "provider=google" in location
    assert "code_challenge_method=s256" in location
    assert "redirect_to=http%3A%2F%2Ftestserver%2Fauth%2Fcallback" in location
    assert gotrue.calls == []                     # the redirect itself costs nothing


def test_callback_exchanges_the_code_and_signs_in(clean_slate, gotrue):
    gotrue.register("d99@example.com", uid="sb-d99", provider="discord",
                    full_name="D 99")
    gotrue.codes["code-1"] = "d99@example.com"
    client.get("/auth/discord/login", follow_redirects=False)   # plants the verifier
    response = client.get("/auth/callback?code=code-1", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/ui/accounts"
    assert auth_mod.SESSION_COOKIE in response.cookies
    user = accounts.get_user_by_email("d99@example.com", dsn=clean_slate)
    assert user["id"] == "sb-d99" and user["display_name"] == "D 99"
    assert gotrue.calls[-1][3] == {"grant_type": "pkce"}


def test_the_old_provider_callback_urls_still_land(clean_slate, gotrue):
    gotrue.register("g@example.com", uid="sb-g")
    gotrue.codes["code-2"] = "g@example.com"
    client.get("/auth/google/login", follow_redirects=False)
    response = client.get("/auth/google/callback?code=code-2", follow_redirects=False)
    assert response.headers["location"] == "/ui/accounts"


def test_callback_without_a_verifier_is_refused(clean_slate, gotrue):
    gotrue.codes["code-3"] = "x@example.com"
    response = client.get("/auth/callback?code=code-3", follow_redirects=False)
    assert "expired" in response.headers["location"]
    assert gotrue.calls == []


def test_callback_relays_supabases_error(clean_slate, gotrue):
    response = client.get("/auth/callback?error=access_denied"
                          "&error_description=Email%20not%20verified",
                          follow_redirects=False)
    assert "Email%20not%20verified" in response.headers["location"]
    assert auth_mod.SESSION_COOKIE not in response.cookies
