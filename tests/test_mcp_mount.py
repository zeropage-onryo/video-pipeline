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
import time

import jwt as pyjwt
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


def test_the_403_says_to_sign_in_once_on_the_web(monkeypatch):
    """Mike's call (2026-10-07): the connector never creates a workspace;
    one web sign-in does. The refusal has to say that, with the address,
    rather than 'ask to be invited' (wrong under open sign-up)."""
    monkeypatch.delenv(mcp_mount.SIGNUP_ENV, raising=False)
    assert "https://zeropage.studio" in mcp_mount.no_account_detail()
    assert "invited" not in mcp_mount.no_account_detail()
    monkeypatch.setenv(mcp_mount.SIGNUP_ENV, "https://studio.example.com")
    assert "https://studio.example.com" in mcp_mount.no_account_detail()


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


# --------------------------------------------------------------------------
# THE DIRECTORY LISTING (2026-10-07, docs/tasks/task-directory-listing.md)
#
# A listed connector is reached by strangers. Three things have to be true
# that one operator never needed: a token minted for somebody else's
# resource, or by somebody else's issuer, or yesterday, is refused; one
# caller cannot flood the process that serves everybody; and user A cannot
# read, write or even confirm the existence of user B's rows, through the
# REAL transport, tool by tool.
# --------------------------------------------------------------------------

JWT_SECRET = "test-secret-" * 4
RESOURCE = "https://zeropage-studio.fly.dev/mcp"
ISSUER = "https://proj.supabase.co/auth/v1"


@pytest.fixture
def hs256(site):
    """The HS256 path: the project's shared JWT secret is configured."""
    site.setenv("SUPABASE_JWT_SECRET", JWT_SECRET)
    return site


def _token(secret=JWT_SECRET, alg="HS256", **claims):
    body = {"sub": "user-a", "aud": RESOURCE, "iss": ISSUER,
            "exp": int(time.time()) + 300}
    body.update(claims)
    return pyjwt.encode(body, secret, algorithm=alg)


def test_a_token_for_this_resource_verifies(hs256):
    assert mcp_auth.verify(_token())["sub"] == "user-a"


def test_an_ordinary_session_token_still_verifies(hs256):
    """`aud: authenticated` is what a zp_session sign-in carries; it is
    accepted so a token pasted from the app's own console works."""
    assert mcp_auth.verify(_token(aud="authenticated"))["sub"] == "user-a"


def test_a_token_minted_for_another_resource_is_refused(hs256):
    """MCP authorization spec, Token Handling: a token for some other
    server, signed by the same authorization server, must not work here."""
    assert mcp_auth.verify(_token(aud="https://other.example.com/mcp")) is None


def test_an_expired_token_is_refused(hs256):
    assert mcp_auth.verify(_token(exp=int(time.time()) - 60)) is None


def test_a_token_from_an_unknown_issuer_is_refused(hs256):
    """Right audience, right signature, wrong `iss`: refused. The issuer
    is the one claim that names the project, and the JWKS path trusts
    whatever key that document vouches for."""
    assert mcp_auth.verify(_token(iss="https://evil.example.com/auth/v1")) is None
    # and a token with no issuer at all does not slip through either
    tok = pyjwt.encode({"sub": "u", "aud": RESOURCE, "exp": int(time.time()) + 60},
                       JWT_SECRET, algorithm="HS256")
    assert mcp_auth.verify(tok) is None


def test_a_forged_signature_is_refused(hs256):
    assert mcp_auth.verify(_token(secret="x" * 48)) is None
    assert mcp_auth.verify("not.a.jwt") is None


def test_the_jwks_path_verifies_the_projects_key_and_nobody_elses(site, monkeypatch):
    """No shared secret configured: the token is checked against the
    project's JWKS. The fetch is stood in for at `jwt.PyJWKClient` (the
    network is blocked in tests), answering the project's public key for
    every kid -- so a token signed by another key fails on the signature,
    which is the only way it can fail once the key lookup is stubbed."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    site.delenv("SUPABASE_JWT_SECRET", raising=False)
    project_key = ec.generate_private_key(ec.SECP256R1())
    other_key = ec.generate_private_key(ec.SECP256R1())
    public_pem = project_key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)

    class _Key:
        key = public_pem

    class _Client:
        def __init__(self, url):
            assert url == "https://proj.supabase.co/auth/v1/.well-known/jwks.json"

        def get_signing_key_from_jwt(self, token):
            return _Key()

    monkeypatch.setattr(pyjwt, "PyJWKClient", _Client)

    def pem(k):
        return k.private_bytes(serialization.Encoding.PEM,
                               serialization.PrivateFormat.PKCS8,
                               serialization.NoEncryption())

    assert mcp_auth.verify(_token(secret=pem(project_key), alg="ES256"))["sub"] == "user-a"
    assert mcp_auth.verify(_token(secret=pem(other_key), alg="ES256")) is None
    assert mcp_auth.verify(_token(secret=pem(project_key), alg="ES256",
                                  aud="https://other.example.com/mcp")) is None
    assert mcp_auth.verify(_token(secret=pem(project_key), alg="ES256",
                                  exp=int(time.time()) - 5)) is None


def test_account_for_token_is_the_oldest_membership_or_a_named_refusal(hs256, pg):
    """The resolver end to end on a real schema: an unverifiable token is
    `invalid_token`, a verified stranger is `no_account` (never a
    fall-through to the operator), and a member resolves to min(id) --
    the same rule auth.current_account_id uses."""
    from conftest import seed_two

    from src import accounts

    seeded = seed_two("mike@example.com", dsn=pg)
    uid = seeded["user_id"]
    assert mcp_auth.account_for_token("garbage", dsn=pg) == (None, "invalid_token")
    assert mcp_auth.account_for_token(_token(sub="nobody-yet"), dsn=pg) == (None, "no_account")
    account_id, reason = mcp_auth.account_for_token(_token(sub=uid), dsn=pg)
    assert reason == "ok"
    assert account_id == min(a["id"] for a in accounts.memberships(uid, dsn=pg))


# ---------- the rate limit ----------

def _limited_app(limiter, resolve, secret="static"):
    inner, seen = _capturing()
    return mcp_mount.guarded(inner, secret, resolve=resolve, limiter=limiter), seen


def _status(app, header):
    return _drive(app, header)


def _drive_full(app, header):
    """(status, headers) for one request."""
    sent = []

    async def send(message):
        sent.append(message)

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    asyncio.run(app({"type": "http", "method": "POST", "path": "/",
                     "headers": [(b"authorization", header.encode())]},
                    receive, send))
    start = sent[0]
    return start["status"], {k.decode(): v.decode() for k, v in start.get("headers", [])}


def test_a_caller_over_the_limit_gets_429_with_retry_after(monkeypatch):
    monkeypatch.setenv(mcp_mount.RATE_ENV, "3")
    limiter = mcp_mount.RateLimiter(clock=lambda: 1000.0)
    app, seen = _limited_app(limiter, resolve=lambda t: (4, "ok"))
    for _ in range(3):
        assert _status(app, "Bearer alice") == 200
    status, headers = _drive_full(app, "Bearer alice")
    assert status == 429
    assert int(headers["retry-after"]) >= 1
    # the refused call never reached the server
    assert seen == [4, 4, 4]


def test_another_account_is_unaffected(monkeypatch):
    monkeypatch.setenv(mcp_mount.RATE_ENV, "2")
    limiter = mcp_mount.RateLimiter(clock=lambda: 1000.0)
    people = {"alice": 4, "bob": 9}
    app, seen = _limited_app(limiter, resolve=lambda t: (people[t], "ok"))
    assert [_status(app, "Bearer alice") for _ in range(3)] == [200, 200, 429]
    assert [_status(app, "Bearer bob") for _ in range(2)] == [200, 200]
    assert seen == [4, 4, 9, 9]


def test_the_window_resets(monkeypatch):
    monkeypatch.setenv(mcp_mount.RATE_ENV, "1")
    now = [1000.0]
    limiter = mcp_mount.RateLimiter(clock=lambda: now[0])
    app, _ = _limited_app(limiter, resolve=lambda t: (4, "ok"))
    assert _status(app, "Bearer alice") == 200
    assert _status(app, "Bearer alice") == 429
    now[0] += mcp_mount.RATE_WINDOW_S
    assert _status(app, "Bearer alice") == 200


def test_the_operator_key_has_its_own_higher_bucket(monkeypatch):
    """Subject to the limit too -- a leaked key must not be unlimited --
    but counted apart from any account and at the operator default."""
    monkeypatch.setenv(mcp_mount.RATE_ENV, "1")
    monkeypatch.setenv(mcp_mount.RATE_OPERATOR_ENV, "2")
    limiter = mcp_mount.RateLimiter(clock=lambda: 1000.0)
    app, _ = _limited_app(limiter, resolve=lambda t: (4, "ok"))
    assert _status(app, "Bearer alice") == 200
    assert _status(app, "Bearer alice") == 429
    assert [_status(app, "Bearer static") for _ in range(3)] == [200, 200, 429]


def test_a_bad_limit_setting_falls_back_to_the_default_never_to_unlimited(monkeypatch):
    monkeypatch.setenv(mcp_mount.RATE_ENV, "lots")
    assert mcp_mount._rate(mcp_mount.RATE_ENV, 7) == 7
    monkeypatch.setenv(mcp_mount.RATE_ENV, "0")
    assert mcp_mount._rate(mcp_mount.RATE_ENV, 7) == 7
    monkeypatch.setenv(mcp_mount.RATE_ENV, "42")
    assert mcp_mount._rate(mcp_mount.RATE_ENV, 7) == 42


def test_an_unauthenticated_caller_is_refused_before_any_bucket_is_touched():
    limiter = mcp_mount.RateLimiter(clock=lambda: 1000.0)
    app, _ = _limited_app(limiter, resolve=lambda t: (None, "invalid_token"))
    assert _status(app, "Bearer nonsense") == 401
    assert limiter._windows == {}


# ---------- isolation, tool by tool, through the real transport ----------

def _listed_names(body: str) -> list:
    """Tool names off the SSE reply of one tools/list."""
    import json

    for line in body.splitlines():
        if line.startswith("data:"):
            result = json.loads(line[len("data:"):]).get("result") or {}
            return [t["name"] for t in result.get("tools", [])]
    return []


def _reply(body: str):
    """(is_error, payload) off the SSE reply of one tools/call."""
    import json

    for line in body.splitlines():
        if not line.startswith("data:"):
            continue
        payload = json.loads(line[len("data:"):])
        if "error" in payload:
            return True, payload["error"]
        result = payload.get("result") or {}
        text = next((c["text"] for c in result.get("content") or []
                     if c.get("type") == "text"), "")
        if result.get("isError"):
            return True, text
        try:
            return False, json.loads(text)
        except ValueError:
            return False, text
    return True, body


@pytest.fixture
def two_people(pg, env, monkeypatch):
    """Alice (account a) and Bob (account b), each with one concept and
    one banked spark, behind the REAL mount: the resolver maps a bearer
    token to the account the way account_for_token would after a
    verified sign-in, and every tool runs against the throwaway schema."""
    pytest.importorskip("mcp")
    pytest.importorskip("httpx")
    from app import mcp_auth as auth_module
    from src import accounts, preprod, scout

    preprod.init(pg)
    scout.init(pg)
    seeded = accounts.seed("alice@example.com", dsn=pg)
    a = seeded["accounts"][0]
    # Bob's own workspace, the way seed_two makes a second one (the open
    # sign-up path is a separate test; what matters here is two tenants)
    accounts.create_user("bob@example.com", "Bob", user_id="user-bob",
                         claimed=True, dsn=pg)
    b = accounts.upsert_account("bobs-studio", "Bob", "#000000", dsn=pg)
    accounts.add_member(b, "user-bob", dsn=pg)
    assert a != b
    (a_concept,) = preprod.save_concept_ideas(
        [{"title": "Alice's concept", "hook": "h", "logline": ""}],
        brand="zeropage", dsn=pg, account_id=a)
    (b_concept,) = preprod.save_concept_ideas(
        [{"title": "Bob's concept", "hook": "h", "logline": ""}],
        brand="zeropage", dsn=pg, account_id=b)
    b_finding = scout.record("zeropage", {"spark": "Bob's private direction",
                                          "rationale": "", "evidence": "",
                                          "sources": [], "score": 1.0},
                             lanes="human", dsn=pg)

    monkeypatch.setenv(mcp_mount.TOKEN_ENV, "operator-key")
    monkeypatch.setenv(mcp_mount.HOSTS_ENV, "*")
    people = {"alice": a, "bob": b}
    monkeypatch.setattr(
        auth_module, "account_for_token",
        lambda token, dsn=None: (people[token], "ok") if token in people
        else (None, "invalid_token"))

    jobs = {1: {"id": 1, "status": "done", "label": "bob's job", "account_id": b}}

    def job_status(job_id, account_id=None):
        job = jobs.get(job_id)
        return job if job and job["account_id"] == account_id else None

    app, sessions = mcp_mount.build(dsn=pg, job_status=job_status)
    assert app is not None
    return {"app": app, "sessions": sessions, "a": a, "b": b,
            "a_concept": a_concept, "b_concept": b_concept,
            "b_finding": b_finding}


def _calls(world, calls):
    """Run [(token, tool, args), ...] through the transport in one
    session-manager run; returns [(is_error, payload), ...]."""
    import httpx

    async def go():
        out = []
        async with world["sessions"].run():
            transport = httpx.ASGITransport(app=world["app"])
            async with httpx.AsyncClient(
                    transport=transport,
                    base_url="https://zeropage-studio.fly.dev") as client:
                for n, (token, name, args) in enumerate(calls, 1):
                    reply = await client.post("/", headers={
                        "authorization": f"Bearer {token}",
                        "content-type": "application/json",
                        "accept": "application/json, text/event-stream"},
                        json={"jsonrpc": "2.0", "id": n, "method": "tools/call",
                              "params": {"name": name, "arguments": args}})
                    out.append(_reply(reply.text))
        return out

    return asyncio.run(go())


def test_the_board_and_stats_are_each_persons_own(two_people):
    w = two_people
    (e1, alice), (e2, bob), (e3, a_stats), (e4, b_stats) = _calls(w, [
        ("alice", "board", {}), ("bob", "board", {}),
        ("alice", "stats", {}), ("bob", "stats", {})])
    assert not (e1 or e2 or e3 or e4)
    assert [c["title"] for c in alice["ideas"]] == ["Alice's concept"]
    assert [c["title"] for c in bob["ideas"]] == ["Bob's concept"]
    assert a_stats["board"]["open"] == 1 and b_stats["board"]["open"] == 1


def test_another_persons_concept_is_indistinguishable_from_missing(two_people):
    """`idea`, `pick`, `archive`, `shoot` on Bob's id, as Alice: the same
    "no concept" a nonexistent id gets, never Bob's row, never a crash."""
    w = two_people
    bid = w["b_concept"]
    results = _calls(w, [
        ("alice", "idea", {"idea_id": bid}),
        ("alice", "pick", {"idea_id": bid}),
        ("alice", "archive", {"idea_id": bid, "reason": "seen it"}),
        ("alice", "shoot", {"idea_id": bid}),
        ("bob", "idea", {"idea_id": bid}),
        ("bob", "board", {}),
    ])
    for is_error, payload in results[:4]:
        assert is_error, payload
        assert "Bob" not in str(payload)
        assert f"no idea {bid}" in payload or f"no concept {bid}" in payload or \
            f"no concept with id {bid}" in payload
    is_error, own = results[4]
    assert not is_error and own["title"] == "Bob's concept"
    # and nothing Alice tried changed Bob's row
    _, bob_board = results[5]
    assert bob_board["ideas"][0]["status"] == "open"


def test_search_and_capture_stay_inside_the_callers_account(two_people):
    w = two_people
    (_, hits), (_, made), (_, bob_board), (_, alice_board) = _calls(w, [
        ("alice", "search", {"query": "concept"}),
        ("alice", "capture", {"brand": "zeropage", "title": "Alice's second"}),
        ("bob", "board", {}),
        ("alice", "board", {}),
    ])
    assert [c["title"] for c in hits["ideas"]] == ["Alice's concept"]
    assert made["title"] == "Alice's second"
    assert [c["title"] for c in bob_board["ideas"]] == ["Bob's concept"]
    assert {c["title"] for c in alice_board["ideas"]} == {"Alice's concept", "Alice's second"}


def test_another_persons_job_is_no_job(two_people):
    w = two_people
    (e1, p1), (e2, p2) = _calls(w, [("alice", "job", {"job_id": 1}),
                                    ("bob", "job", {"job_id": 1})])
    assert e1 and "no job 1" in p1
    assert not e2 and p2["label"] == "bob's job"


def test_the_operator_key_still_reads_the_bootstrap_account(two_people):
    """Alice's account is the seeded (oldest) one, which is what the
    static key resolves to -- the pre-OAuth behaviour, unchanged."""
    w = two_people
    (e, board), = _calls(w, [("operator-key", "board", {})])
    assert not e and [c["title"] for c in board["ideas"]] == ["Alice's concept"]


def test_no_tool_reports_a_credit_balance(two_people):
    """Noted rather than asserted away: nothing on this surface answers
    "what can I spend" -- `pick` quotes a draw, `stats` counts the board.
    A balance tool is Phase 3's to decide."""
    import asyncio as _asyncio

    from src import mcp_server

    names = {t.name for t in _asyncio.run(mcp_server.build_server(dsn=":memory:").list_tools())}
    assert not {"balance", "credits", "wallet"} & names


def test_the_spark_bank_is_not_offered_to_a_signed_in_caller(two_people):
    """scout_findings / scout_bin are SHARED tables by design
    (db.SHARED_TABLES), so one person's directions would be listed to
    another. Mike's call (2026-10-07): the bank stays off the listed
    server. A signed-in caller is handed the listed set and `sparks`
    is simply not a tool there; the operator's static key still has it."""
    w = two_people
    (e1, p1), (e2, p2), (e3, p3) = _calls(w, [
        ("alice", "sparks", {}),
        ("alice", "images", {"finding_id": w["b_finding"]}),
        ("operator-key", "sparks", {}),
    ])
    assert e1 and "sparks" in str(p1)
    assert e2 and "images" in str(p2)
    assert "Bob's private direction" not in str(p1) + str(p2)
    assert not e3 and any(r["spark"] == "Bob's private direction" for r in p3["sparks"])


def test_a_signed_in_caller_lists_exactly_the_listed_set(two_people):
    import httpx

    w = two_people

    async def names_for(token):
        async with w["sessions"].run():
            transport = httpx.ASGITransport(app=w["app"])
            async with httpx.AsyncClient(
                    transport=transport,
                    base_url="https://zeropage-studio.fly.dev") as client:
                out = {}
                for tok in token:
                    reply = await client.post("/", headers={
                        "authorization": f"Bearer {tok}",
                        "content-type": "application/json",
                        "accept": "application/json, text/event-stream"},
                        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
                    out[tok] = _listed_names(reply.text)
                return out

    listed = asyncio.run(names_for(["alice", "operator-key"]))
    assert listed["alice"] == list(mcp_server.LISTED_TOOLS)
    assert set(listed["operator-key"]) > set(mcp_server.LISTED_TOOLS)
    assert "sparks" in listed["operator-key"] and "imagine_reference" in listed["operator-key"]


# ---------- what an external caller sees ----------

def test_what_an_external_caller_sees_with_the_engine_off(env, monkeypatch):
    """The exact tool set a signed-in, non-operator caller is offered by
    the mount as deployed (engine off, job registry injected), and that
    every one of them carries the annotations the directory checks."""
    pytest.importorskip("mcp")
    monkeypatch.delenv(mcp_server.ENGINE_ENV, raising=False)
    app, _ = mcp_mount.build(dsn=":memory:", job_status=lambda i, account_id=None: None)
    assert app is not None
    server = mcp_server.build_server(dsn=":memory:", listed=True,
                                     job_status=lambda i, account_id=None: None)
    tools = asyncio.run(server.list_tools())
    names = [t.name for t in tools]
    assert names == ["board", "idea", "search", "capture", "pick", "shoot", "archive",
                     "stats", "job"] == list(mcp_server.LISTED_TOOLS)
    for absent in ("research", "generate", "sparks", "tonight", "add_spark", "images",
                   "reference", "imagine_reference", "images_for"):
        assert absent not in names
    # and the engine flag changes nothing on the listed server
    monkeypatch.setenv(mcp_server.ENGINE_ENV, "1")
    again = mcp_server.build_server(dsn=":memory:", listed=True)
    assert "generate" not in {t.name for t in asyncio.run(again.list_tools())}
    for t in tools:
        assert t.title, t.name
        assert t.annotations is not None
        assert t.annotations.read_only_hint in (True, False)
        assert t.annotations.destructive_hint in (True, False)
        assert t.annotations.idempotent_hint in (True, False)
        assert t.annotations.open_world_hint in (True, False)
        if not t.annotations.read_only_hint:
            # a write says whether it can be undone
            assert t.annotations.destructive_hint is not None
