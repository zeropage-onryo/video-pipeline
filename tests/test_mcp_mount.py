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
import pytest

from app import mcp_mount


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
