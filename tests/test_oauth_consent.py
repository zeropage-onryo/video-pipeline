"""The consent screen Supabase sends people to.

WHY THIS FILE EXISTS. Supabase's OAuth 2.1 server does not render its own
approval screen: it validates the client and redirects to
`/oauth/consent?authorization_id=…` on THIS app, expecting it to show who
is asking and call approve/deny. The route simply did not exist, so every
connector flow -- discovery, dynamic registration, PKCE, all of it
working -- died on a 404 whose body said `{"detail":"Not Found"}` and
nothing else. Found by driving the real Claude connector through the
handshake, not by a test, which is the gap these close.

What is asserted here is only what the SERVER owes: that the page exists
unconditionally, that it carries the two public values the browser needs,
and that it never holds a Supabase token. The approve/deny calls are
supabase-js in the person's own browser (see the route's docstring for
why), so they are deliberately not under test here.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

AUTHORIZED = "/oauth/consent?authorization_id=566cbc46334yp6dumxiaubyxfigvkiuc"


@pytest.fixture
def supabase(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://proj.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "public-anon-key")
    return monkeypatch


def test_the_consent_page_exists(supabase):
    """The regression: this 404'd, and a 404 here reads to the person as
    'the connector is broken' with nothing to act on."""
    assert client.get(AUTHORIZED).status_code == 200


def test_it_does_not_require_a_session_of_its_own(supabase):
    """A connector reaches this page before the person has signed in
    here; the page sends them to /signin itself, carrying the
    authorization_id. A 401/403 would be a dead end."""
    reply = client.get(AUTHORIZED)
    assert reply.status_code == 200
    assert "/signin?next=" in reply.text


def test_it_hands_the_browser_the_two_public_values(supabase):
    """The project URL and the ANON key -- the same pair the sign-in page
    already ships to every visitor. Nothing else is needed, because the
    approval is made by the browser's own Supabase session."""
    body = client.get(AUTHORIZED).text
    assert "https://proj.supabase.co" in body
    assert "public-anon-key" in body


def test_the_server_never_touches_the_authorization(supabase):
    """The decision this route encodes: approving is acting as the user,
    and this app keeps no Supabase token (app/auth.py). If a future edit
    moves approve/deny server-side, it will have to delete this test --
    which is the point of it.
    """
    body = client.get(AUTHORIZED).text
    assert "approveAuthorization" in body and "denyAuthorization" in body
    # the service-role key is the one credential that could approve
    # server-side; it must never reach this page, configured or not.
    assert "service_role" not in body


def test_a_link_with_no_authorization_id_still_renders(supabase):
    """Supabase always sends one, so a request without it is a person
    who bookmarked the page or a truncated link. It must explain itself
    rather than 500 or show an approve button that cannot work."""
    reply = client.get("/oauth/consent")
    assert reply.status_code == 200
    assert "missing its authorization id" in reply.text
