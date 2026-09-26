"""
Open sign-up and the one-door email code (2026-09-24, Mike: "do what
these professional sites already do" -- InVideo, LTX Studio).

Two behaviours, pinned here:

- The first sign-in through ANY door (email code, password, OAuth)
  gives a person with no membership their OWN empty workspace and
  lands them in it, instead of the no-access page. Never an existing
  account, never twice, never for someone who already belongs somewhere
  (Mike, an invited pilot). ZEROPAGE_OPEN_SIGNUP=0 restores the gate.
- Email is a one-time code: /auth/email sends it (create_user: true, so
  one form serves new and returning people), /auth/verify signs in.
"""
import pytest

import app.auth as auth_mod
from src import accounts, ledger
from tests import test_auth
from tests.test_auth import FakeGoTrue, client, seed_mike

# test_auth's autouse fixture (fresh schema, Supabase configured, signed
# out), re-exported by assignment so pytest finds it here too
clean_slate = test_auth.clean_slate


class CodeGoTrue(FakeGoTrue):
    """FakeGoTrue plus GoTrue's two passwordless endpoints."""

    def __init__(self):
        super().__init__()
        self.sent: dict[str, str] = {}      # email -> code

    def __call__(self, method, path, *, json=None, params=None):
        if path == "/otp":
            self.calls.append((method, path, json, params))
            email = json["email"]
            if email not in self.users:
                if not json.get("create_user"):
                    return 422, {"msg": "Signups not allowed for otp"}
                self.register(email)
            self.sent[email] = "123456"
            return 200, {}
        if path == "/verify":
            self.calls.append((method, path, json, params))
            email = json["email"]
            if json.get("type") != "email" or self.sent.get(email) != json["token"]:
                return 403, {"error_code": "otp_expired",
                             "msg": "Token has expired or is invalid"}
            del self.sent[email]
            return 200, self.session(email)
        return super().__call__(method, path, json=json, params=params)


@pytest.fixture
def gotrue(monkeypatch):
    fake = CodeGoTrue()
    monkeypatch.setattr(auth_mod, "gotrue", fake)
    return fake


@pytest.fixture
def open_door(monkeypatch):
    monkeypatch.setenv("ZEROPAGE_OPEN_SIGNUP", "1")
    monkeypatch.delenv("ZEROPAGE_SIGNUP_CREDITS", raising=False)
    monkeypatch.delenv("STUDIO_URL", raising=False)


def code_sign_in(email="new@example.com", code="123456"):
    sent = client.post("/auth/email", data={"email": email}, follow_redirects=False)
    assert sent.status_code == 303
    return client.post("/auth/verify", data={"email": email, "token": code},
                       follow_redirects=False)


# ---------- the email code door ----------

def test_the_email_door_sends_a_code_and_lands_on_the_code_step(clean_slate, gotrue):
    response = client.post("/auth/email", data={"email": " New@Example.com "},
                           follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/signin?step=code")
    assert "new%40example.com" in response.headers["location"]
    method, path, body, params = gotrue.calls[-1]
    assert path == "/otp"
    assert body["email"] == "new@example.com"
    assert body["create_user"] is True            # one form, new or returning
    assert body["code_challenge_method"] == "s256"   # the link fallback is PKCE
    assert params["redirect_to"].endswith("/auth/callback")


def test_the_code_step_page_asks_for_the_code(clean_slate):
    page = client.get("/signin?step=code&email=new%40example.com")
    assert "Check your email" in page.text
    assert 'action="/auth/verify"' in page.text
    assert "new@example.com" in page.text


def test_a_right_code_signs_in(clean_slate, gotrue):
    response = code_sign_in()
    assert response.status_code == 303
    user = accounts.get_user_by_email("new@example.com", dsn=clean_slate)
    assert user is not None
    assert client.get("/api/capabilities").status_code in (200, 403)  # a session exists


def test_a_wrong_code_goes_back_to_the_code_step_without_a_session(clean_slate, gotrue):
    response = code_sign_in(code="000000")
    assert "step=code" in response.headers["location"]
    assert "didn" in response.headers["location"]
    assert client.get("/api/capabilities").status_code == 401


def test_a_malformed_code_never_reaches_supabase(clean_slate, gotrue):
    client.post("/auth/email", data={"email": "new@example.com"}, follow_redirects=False)
    before = len(gotrue.calls)
    response = client.post("/auth/verify", data={"email": "new@example.com", "token": "12"},
                           follow_redirects=False)
    assert "step=code" in response.headers["location"]
    assert len(gotrue.calls) == before


def test_a_bad_email_never_reaches_supabase(clean_slate, gotrue):
    response = client.post("/auth/email", data={"email": "not-an-email"},
                           follow_redirects=False)
    assert "error=" in response.headers["location"]
    assert gotrue.calls == []


def test_code_requests_are_rate_limited(clean_slate, gotrue):
    for _ in range(5):
        client.post("/auth/email", data={"email": "new@example.com"}, follow_redirects=False)
    response = client.post("/auth/email", data={"email": "new@example.com"},
                           follow_redirects=False)
    assert "too%20many" in response.headers["location"]


def test_the_start_page_is_one_door(clean_slate):
    page = client.get("/signin")
    assert "Welcome to Zero Page" in page.text
    assert 'action="/auth/email"' in page.text      # the default email door
    assert 'action="/auth/login"' in page.text      # the password fallback
    assert 'action="/auth/signup"' not in page.text  # no second form to choose
    signup_page = client.get("/signin?mode=signup")
    assert "Sign up and start creating" in signup_page.text
    assert 'action="/auth/email"' in signup_page.text


def test_the_legal_line_points_at_the_public_site(clean_slate, monkeypatch):
    monkeypatch.setenv("STUDIO_URL", "https://zpf-web.vercel.app/studio")
    page = client.get("/signin")
    assert 'href="https://zpf-web.vercel.app/terms"' in page.text
    monkeypatch.delenv("STUDIO_URL")
    assert "/terms" not in client.get("/signin").text


# ---------- open sign-up: the workspace ----------

def test_first_sign_in_gets_its_own_workspace(clean_slate, gotrue, open_door):
    code_sign_in("maya.r+zpf@example.com")
    user = accounts.get_user_by_email("maya.r+zpf@example.com", dsn=clean_slate)
    member_of = accounts.memberships(user["id"], dsn=clean_slate)
    assert len(member_of) == 1
    account = member_of[0]
    assert account["slug"] == "maya-r-zpf"
    assert account["display_name"] == "maya.r+zpf's studio"
    assert account["role"] == "owner"
    # every flag fails closed on a stranger's account
    assert not account["credit_exempt"]
    assert not account["manual_lane_operator"]
    assert not account["prompt_edits_teach"]
    assert account["plan"] is None
    # and they are in, not on the gate page
    assert "No account access yet" not in client.get("/ui/accounts").text


def test_the_password_door_provisions_too(clean_slate, gotrue, open_door):
    client.post("/auth/signup", data={"email": "pw@example.com", "password": "hunter2hunter2"},
                follow_redirects=False)
    user = accounts.get_user_by_email("pw@example.com", dsn=clean_slate)
    assert len(accounts.memberships(user["id"], dsn=clean_slate)) == 1


def test_signing_in_again_does_not_make_a_second_workspace(clean_slate, gotrue, open_door):
    code_sign_in()
    client.cookies.clear()
    code_sign_in()
    user = accounts.get_user_by_email("new@example.com", dsn=clean_slate)
    assert len(accounts.memberships(user["id"], dsn=clean_slate)) == 1
    assert accounts.provision_personal(user["id"], "new@example.com", dsn=clean_slate) is None


def test_mike_is_never_given_a_new_workspace(clean_slate, gotrue, open_door):
    seed_mike(clean_slate, gotrue)
    client.post("/auth/login", data={"email": "mike@example.com",
                                     "password": "mikes-password-1"},
                follow_redirects=False)
    slugs = sorted(a["slug"] for a in accounts.memberships("uid-mike-supabase", dsn=clean_slate))
    assert slugs == ["antihero", "zeropage"]


def test_an_invited_pilot_lands_in_their_invite_not_a_new_one(clean_slate, gotrue, open_door):
    accounts.invite("pilot@example.com", "pilot-co", dsn=clean_slate)
    code_sign_in("pilot@example.com")
    user = accounts.get_user_by_email("pilot@example.com", dsn=clean_slate)
    assert [a["slug"] for a in accounts.memberships(user["id"], dsn=clean_slate)] == ["pilot-co"]


def test_a_taken_or_reserved_slug_is_never_joined(clean_slate, gotrue, open_door):
    accounts.seed("mike@example.com", dsn=clean_slate)      # owns zeropage / antihero
    accounts.upsert_account("maya", "Someone else", dsn=clean_slate)
    code_sign_in("zeropage@example.com")
    code_sign_in_user = accounts.get_user_by_email("zeropage@example.com", dsn=clean_slate)
    mine = accounts.memberships(code_sign_in_user["id"], dsn=clean_slate)
    assert [a["slug"] for a in mine] == ["studio-zeropage"]
    client.cookies.clear()
    code_sign_in("maya@example.com")
    maya = accounts.get_user_by_email("maya@example.com", dsn=clean_slate)
    assert [a["slug"] for a in accounts.memberships(maya["id"], dsn=clean_slate)] == ["maya-2"]


def test_the_switch_off_keeps_the_invite_only_gate(clean_slate, gotrue, monkeypatch):
    monkeypatch.setenv("ZEROPAGE_OPEN_SIGNUP", "0")
    code_sign_in()
    user = accounts.get_user_by_email("new@example.com", dsn=clean_slate)
    assert accounts.memberships(user["id"], dsn=clean_slate) == []
    assert "No account access yet" in client.get("/ui/accounts").text


def test_open_signup_reads_on_unless_explicitly_off(monkeypatch):
    monkeypatch.delenv("ZEROPAGE_OPEN_SIGNUP", raising=False)
    assert accounts.open_signup() is True
    for off in ("0", "false", "OFF", "no"):
        monkeypatch.setenv("ZEROPAGE_OPEN_SIGNUP", off)
        assert accounts.open_signup() is False


def test_someone_stuck_behind_the_old_gate_gets_a_workspace_on_return(
        clean_slate, gotrue, monkeypatch):
    monkeypatch.setenv("ZEROPAGE_OPEN_SIGNUP", "0")
    code_sign_in()                                   # signed in under the old gate
    user = accounts.get_user_by_email("new@example.com", dsn=clean_slate)
    assert accounts.memberships(user["id"], dsn=clean_slate) == []
    monkeypatch.setenv("ZEROPAGE_OPEN_SIGNUP", "1")
    client.get("/signin", follow_redirects=False)    # comes back through the door
    assert len(accounts.memberships(user["id"], dsn=clean_slate)) == 1


def test_a_failed_workspace_never_fails_the_sign_in(clean_slate, gotrue, open_door, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("database hiccup")
    monkeypatch.setattr(accounts, "provision_personal", boom)
    response = code_sign_in()
    assert response.status_code == 303
    assert "error" not in response.headers["location"]


# ---------- the welcome grant ----------

def test_no_welcome_credits_unless_configured(clean_slate, gotrue, open_door):
    ledger.init(clean_slate)
    code_sign_in()
    user = accounts.get_user_by_email("new@example.com", dsn=clean_slate)
    account_id = accounts.memberships(user["id"], dsn=clean_slate)[0]["id"]
    assert ledger.available(account_id, dsn=clean_slate) == 0


def test_welcome_credits_are_granted_once(clean_slate, gotrue, open_door, monkeypatch):
    ledger.init(clean_slate)
    monkeypatch.setenv("ZEROPAGE_SIGNUP_CREDITS", "200")
    code_sign_in()
    user = accounts.get_user_by_email("new@example.com", dsn=clean_slate)
    account_id = accounts.memberships(user["id"], dsn=clean_slate)[0]["id"]
    assert ledger.available(account_id, dsn=clean_slate) == 200
    accounts.grant_signup_credits(account_id, dsn=clean_slate)   # a retry
    assert ledger.available(account_id, dsn=clean_slate) == 200


def test_a_new_person_is_handed_straight_to_the_studio(clean_slate, gotrue, open_door,
                                                       monkeypatch):
    """The point of provisioning inside _finish: the studio handoff runs
    after it, so a first sign-in lands in the React studio, not on the
    no-access page -- InVideo's 'log in and you are in'."""
    monkeypatch.setenv("STUDIO_URL", "https://studio.example")
    response = code_sign_in()
    assert response.headers["location"].startswith("https://studio.example/auth/handoff")
    monkeypatch.setenv("ZEROPAGE_OPEN_SIGNUP", "0")
    client.cookies.clear()
    response = code_sign_in("other@example.com")
    assert response.headers["location"] == "/ui/accounts"


def test_the_free_credit_row_shows_only_when_a_grant_is_configured(clean_slate, open_door,
                                                                   monkeypatch):
    assert "free credits" not in client.get("/signin").text
    monkeypatch.setenv("ZEROPAGE_SIGNUP_CREDITS", "150")
    assert "get 150 free credits" in client.get("/signin").text
    monkeypatch.setenv("ZEROPAGE_OPEN_SIGNUP", "0")         # no sign-up, no promise
    assert "free credits" not in client.get("/signin").text


def test_an_error_reopens_the_step_it_came_from(clean_slate, gotrue):
    response = client.post("/auth/login", data={"email": "x@example.com", "password": "nope"},
                           follow_redirects=False)
    assert "open=password" in response.headers["location"]
    page = client.get(response.headers["location"])
    assert 'data-open="password"' in page.text


def test_the_showcase_keeps_only_real_sources(clean_slate, monkeypatch):
    monkeypatch.setenv("SIGNIN_SHOWCASE", '[{"label": "Runway", "video": "https://cdn.example/a.mp4"},'
                       '{"label": "bad", "video": "javascript:alert(1)"},'
                       '{"label": "Veo", "image": "/refs/x.jpg"}]')
    page = client.get("/signin").text
    assert "https://cdn.example/a.mp4" in page and "/refs/x.jpg" in page
    assert "javascript:" not in page
    monkeypatch.setenv("SIGNIN_SHOWCASE", "not json")
    assert client.get("/signin").status_code == 200
