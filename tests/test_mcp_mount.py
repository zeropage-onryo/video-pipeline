"""The /mcp mount actually builds.

WHY THIS FILE EXISTS. `mcp_mount.build` catches every exception on
purpose -- a bad MCP config must not stop the web app from starting --
so a signature drift between it and `mcp_server.build_server` fails
SILENTLY: the app boots, /mcp 404s, and the only trace is one line on
stderr. That is exactly what happened when build_server's first
parameter was renamed `path` -> `dsn` (2026-09-18, the Guide's build)
and this caller was not updated: the deployed endpoint answered 404 for
every caller and the tests, which only ever exercised build_server
directly, stayed green.

So the assertion worth making is the one nothing else makes: with the
env set the way a real deployment sets it, build() returns an app
rather than the pair of Nones it returns for every failure.
"""
import asyncio

import pytest

from app import mcp_auth, mcp_mount
from src import mcp_server


@pytest.fixture
def env(monkeypatch):
    monkeypatch.delenv(mcp_mount.HOSTS_ENV, raising=False)
    monkeypatch.setenv(mcp_mount.ENABLED_ENV, "1")
    monkeypatch.setenv(mcp_mount.TOKEN_ENV, "test-token")
    return monkeypatch


def test_off_unless_enabled(monkeypatch):
    monkeypatch.delenv(mcp_mount.ENABLED_ENV, raising=False)
    assert mcp_mount.build() == (None, None)


def test_refused_without_a_token(monkeypatch):
    monkeypatch.setenv(mcp_mount.ENABLED_ENV, "1")
    monkeypatch.delenv(mcp_mount.TOKEN_ENV, raising=False)
    assert mcp_mount.build() == (None, None)


def test_builds_when_configured(env, tmp_path):
    """The regression: a bad keyword here returns (None, None) quietly."""
    pytest.importorskip("mcp")
    app, sessions = mcp_mount.build(dsn=str(tmp_path / "board.db"))
    assert app is not None and sessions is not None


def test_allowed_hosts_take_the_deployment_hostname(env):
    env.setenv(mcp_mount.HOSTS_ENV, "zeropage-studio.fly.dev")
    assert "zeropage-studio.fly.dev" in mcp_mount.allowed_hosts()
    env.setenv(mcp_mount.HOSTS_ENV, "*")
    assert mcp_mount.allowed_hosts() == ["*"]


@pytest.mark.parametrize("header, status", [
    (None, 401),
    ("Bearer wrong", 401),
    ("Bearer right", 200),
])
def test_guarded_checks_the_bearer_token(header, status):
    import asyncio

    async def inner(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    wrapped = mcp_mount.guarded(inner, "right")
    headers = [(b"authorization", header.encode())] if header else []
    sent = []

    async def send(message):
        sent.append(message)

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    asyncio.run(wrapped({"type": "http", "headers": headers, "method": "POST",
                         "path": "/mcp/"}, receive, send))
    assert sent[0]["status"] == status


# --------------------------------------------------------------------------
# THE OAUTH DOOR (2026-09-24)
#
# The mount had one caller for its whole life: an agent holding the static
# token, acting as the bootstrap account. Letting a second person in is the
# change these tests exist for, and the failure they are written against is
# not "OAuth is broken" -- it is "OAuth works and the caller reads Mike's
# board", which looks exactly like success from the connector's side.
# --------------------------------------------------------------------------
@pytest.fixture
def site(monkeypatch):
    monkeypatch.setenv("SITE_URL", "https://zeropage-studio.fly.dev")
    monkeypatch.setenv("SUPABASE_URL", "https://proj.supabase.co")
    monkeypatch.delenv(mcp_auth.RESOURCE_ENV, raising=False)
    return monkeypatch


def test_metadata_names_this_server_and_its_authorization_server(site):
    doc = mcp_auth.protected_resource_metadata()
    assert doc["resource"] == "https://zeropage-studio.fly.dev/mcp"
    # Supabase's issuer is /auth/v1, not the project root: the root 404s
    # on every discovery path, which a client reports as "no OAuth server"
    # rather than as a wrong URL.
    assert doc["authorization_servers"] == ["https://proj.supabase.co/auth/v1"]
    # A scope this server does not enforce would be a claim, not a control.
    assert "scopes_supported" not in doc


def test_metadata_lives_under_the_resource_path(site):
    """RFC 9728 puts the resource's path AFTER the well-known segment."""
    assert mcp_auth.metadata_url() == (
        "https://zeropage-studio.fly.dev/.well-known/oauth-protected-resource/mcp")
    assert mcp_auth.metadata_url() in mcp_auth.challenge()


def test_challenge_degrades_when_there_is_no_authorization_server(site):
    site.delenv("SUPABASE_URL", raising=False)
    assert mcp_auth.configured() is False


def test_resource_can_be_overridden_for_another_public_hostname(site):
    site.setenv(mcp_auth.RESOURCE_ENV, "https://tunnel.example.com/mcp/")
    assert mcp_auth.protected_resource_metadata()["resource"] == \
        "https://tunnel.example.com/mcp"


def _drive(app, header=None):
    """Run one HTTP request through an ASGI app and return (status, seen)."""
    sent = []
    headers = [(b"authorization", header.encode())] if header else []

    async def send(message):
        sent.append(message)

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    asyncio.run(app({"type": "http", "headers": headers, "method": "POST",
                     "path": "/"}, receive, send))
    return sent[0]["status"]


def _capturing():
    """An inner app that records who the transport says is calling."""
    seen = []

    async def inner(scope, receive, send):
        seen.append(mcp_server.CALLER_ACCOUNT.get())
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    return inner, seen


def test_the_static_token_still_acts_as_the_operator():
    """No caller named -> _account falls through to the bootstrap account,
    which is the pre-OAuth behaviour every CLI and agent depends on."""
    inner, seen = _capturing()
    app = mcp_mount.guarded(inner, "static", resolve=lambda t: (None, "invalid_token"))
    assert _drive(app, "Bearer static") == 200
    assert seen == [None]


def test_a_signed_in_caller_acts_as_their_own_account():
    inner, seen = _capturing()
    app = mcp_mount.guarded(inner, "static", resolve=lambda t: (7, "ok"))
    assert _drive(app, "Bearer someones-jwt") == 200
    assert seen == [7]
    # and the value does not outlive the request -- a leak here is one
    # caller reading the next caller's board.
    assert mcp_server.CALLER_ACCOUNT.get() is None


def test_a_sign_in_with_no_membership_is_403_not_somebody_elses_board():
    inner, seen = _capturing()
    app = mcp_mount.guarded(inner, "static", resolve=lambda t: (None, "no_account"))
    assert _drive(app, "Bearer valid-but-unaffiliated") == 403
    assert seen == []


def test_an_unverifiable_token_is_401_and_never_reaches_the_server():
    inner, seen = _capturing()
    app = mcp_mount.guarded(inner, "static", resolve=lambda t: (None, "invalid_token"))
    assert _drive(app, "Bearer nonsense") == 401
    assert seen == []


def test_two_callers_through_the_real_transport_read_two_boards(env, monkeypatch):
    """The end-to-end one, and the only one that would have caught a
    context that does not propagate: two tool calls through the REAL
    streamable-HTTP app, each reporting the account the tool resolved.

    `list_ideas` is stood in for rather than reaching Postgres -- what is
    under test is whose id arrives, not what the board says. The resolver
    is stood in for at `mcp_auth.account_for_token`, which is where
    `guarded` reaches for it, so the wiring under test is the real one.
    """
    pytest.importorskip("mcp")
    httpx = pytest.importorskip("httpx")
    from app import mcp_auth as auth_module

    monkeypatch.setenv(mcp_mount.TOKEN_ENV, "operator-key")
    monkeypatch.setenv(mcp_mount.HOSTS_ENV, "*")
    monkeypatch.setattr(mcp_server.accounts, "resolve_account",
                        lambda **kw: 1, raising=False)
    monkeypatch.setattr(
        mcp_server, "list_ideas",
        lambda *a, dsn=None, account_id=None, **kw:
            {"acting_as": mcp_server._account(account_id, dsn)})
    people = {"alice": 4, "bob": 9}
    monkeypatch.setattr(
        auth_module, "account_for_token",
        lambda token, dsn=None: (people[token], "ok") if token in people
        else (None, "invalid_token"))

    app, sessions = mcp_mount.build(dsn=":memory:")
    assert app is not None

    async def run_calls():
        # ONE session manager for the whole test: it is an async context
        # that refuses to be entered twice, the same way the app enters it
        # once in its lifespan.
        out = {}
        async with sessions.run():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                    transport=transport,
                    base_url="https://zeropage-studio.fly.dev") as client:
                for token in ("alice", "bob", "operator-key", "nonsense"):
                    reply = await client.post("/", headers={
                        "authorization": f"Bearer {token}",
                        "content-type": "application/json",
                        "accept": "application/json, text/event-stream"},
                        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                              "params": {"name": "board", "arguments": {}}})
                    out[token] = _acting_as(reply.text)
        return out

    acting_as = asyncio.run(run_calls())

    assert acting_as["alice"] == 4
    assert acting_as["bob"] == 9
    # the operator's own key still reads the bootstrap account
    assert acting_as["operator-key"] == 1
    # and an unverifiable token never reaches a tool at all
    assert acting_as["nonsense"] is None


def _acting_as(body: str):
    """The account a tool call resolved, read back off the SSE reply, or
    None when the call never reached a tool."""
    import json

    for line in body.splitlines():
        if not line.startswith("data:"):
            continue
        payload = json.loads(line[len("data:"):])
        result = payload.get("result") or {}
        for item in result.get("content") or []:
            if item.get("type") == "text":
                return json.loads(item["text"]).get("acting_as")
    return None


def test_the_document_is_built_off_the_resource_not_off_site_url(monkeypatch):
    """The Fly case: SITE_URL is unset there (it drives the landing
    page's canonical tags, and the public site is the Vercel app), so a
    document built from it would publish a localhost resource to a
    connector reaching us at fly.dev -- discovery that fails silently."""
    monkeypatch.delenv("SITE_URL", raising=False)
    monkeypatch.setenv(mcp_auth.RESOURCE_ENV, "https://zeropage-studio.fly.dev/mcp")
    doc = mcp_auth.protected_resource_metadata()
    assert doc["resource"] == "https://zeropage-studio.fly.dev/mcp"
    assert "127.0.0.1" not in mcp_auth.metadata_url()
    assert "127.0.0.1" not in doc["resource_documentation"]
