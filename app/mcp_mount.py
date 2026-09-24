"""
Mounting the MCP server on the web app.

WHY IT LIVES IN app/ AND NOT src/. `src/mcp_server.py` is the tool
surface and knows nothing about HTTP. Two things it needs are the web
process's own: the job registry in `app/jobs.py` (a thread registry
belonging to this process) and the transport. They are handed to it as
callables rather than imported by it, because `src/` never imports
`app/` -- the same injection `scene_chain` uses for the two app-layer
capabilities it needs.

THE POSTURE. Mounting is off unless ZEROPAGE_MCP=1, and a mount with no
ZEROPAGE_MCP_TOKEN is REFUSED rather than served open. That refusal is
the whole point of this module: the reason to mount MCP at all is to
reach it from off the machine, which in practice means a tunnel, which
means the endpoint is on the public internet the moment it works. An
"I'll add auth later" default here writes to the board, banks sparks
and -- with the engine flag -- spends model credit, for anyone who
finds the URL. So it fails loudly and stays unmounted.

The token is compared with `hmac.compare_digest`, not `==`, and the
check happens before the MCP app is ever entered, so an unauthenticated
caller cannot open a session or enumerate the tool list.
"""
from __future__ import annotations

import hmac
import os
import sys
from contextlib import asynccontextmanager
from typing import Optional

from src import mcp_server

ENABLED_ENV = "ZEROPAGE_MCP"
TOKEN_ENV = "ZEROPAGE_MCP_TOKEN"
HOSTS_ENV = "ZEROPAGE_MCP_HOSTS"
MOUNT_PATH = "/mcp"

# The SDK refuses any request whose Host header it does not recognise --
# DNS-rebinding protection, which defends a localhost server against a
# malicious page in the operator's own browser. Behind a tunnel the Host
# is the tunnel's hostname, so the default list 421s every real call
# with "Invalid Host header", which reads like a broken server rather
# than a setting. Hence ZEROPAGE_MCP_HOSTS.
DEFAULT_HOSTS = ("127.0.0.1", "127.0.0.1:8000", "localhost", "localhost:8000")


def allowed_hosts() -> list[str]:
    """Hosts this endpoint answers to. `*` disables the check, which is
    the right setting behind a quick tunnel whose hostname changes on
    every restart: the attack rebinding protection exists to stop is a
    browser reaching a localhost server, and a browser cannot supply the
    bearer token that `guarded` demands before the MCP app is entered.
    A NAMED tunnel has a stable hostname -- list it instead.
    """
    extra = [h.strip() for h in os.environ.get(HOSTS_ENV, "").split(",") if h.strip()]
    return extra if "*" in extra else list(DEFAULT_HOSTS) + extra


def enabled() -> bool:
    return os.environ.get(ENABLED_ENV) == "1"


def token() -> str:
    return os.environ.get(TOKEN_ENV, "")


def _unauthorized(detail: str, error: str = "unauthorized"):
    from starlette.responses import JSONResponse

    from . import mcp_auth

    # The challenge names the metadata document when there is an
    # authorization server to discover; a bare "Bearer" otherwise, which
    # is the honest answer on a deployment with no Supabase configured.
    challenge = mcp_auth.challenge() if mcp_auth.configured() else "Bearer"
    return JSONResponse({"error": error, "detail": detail},
                        status_code=401,
                        headers={"WWW-Authenticate": challenge})


def _forbidden(detail: str):
    from starlette.responses import JSONResponse

    return JSONResponse({"error": "no_account", "detail": detail}, status_code=403)


def guarded(app, secret: str, resolve=None):
    """Wrap an ASGI app so every request names a caller.

    A plain ASGI wrapper rather than middleware on the parent app: the
    check must not apply to /ui or /api (which have their own cookie
    session), and it must apply to every method and path under the
    mount, including the ones the transport adds itself.

    TWO DOORS, and which one a caller came through decides whose board
    they read (see app/mcp_auth.py):

    - The static token -- the operator's own key, compared with
      `hmac.compare_digest` rather than `==`, before the MCP app is ever
      entered, so an unauthenticated caller cannot open a session or
      enumerate the tool list. It acts as the bootstrap account, exactly
      as it did before OAuth existed.
    - Anything else is offered to `resolve`, which verifies it as a
      Supabase access token and answers with the caller's OWN account
      id. That id is put on `mcp_server.CALLER_ACCOUNT` for the length of
      this request and reset in a `finally` -- a leaked value here is
      one caller reading another's board, so it is never left set.

    `resolve` is injected (defaulting to `mcp_auth.account_for_token`)
    for the reason the whole mount is injected: this module is the seam
    where app-layer capability meets `src/`, and a test that has to mint
    a real Supabase JWT to exercise the guard is a test nobody writes.
    """
    if resolve is None:
        from .mcp_auth import account_for_token as resolve

    from src import mcp_server

    async def wrapper(scope, receive, send):
        if scope["type"] != "http":
            return await app(scope, receive, send)
        header = ""
        for key, value in scope.get("headers") or []:
            if key == b"authorization":
                header = value.decode("latin-1")
                break
        prefix = "Bearer "
        supplied = header[len(prefix):] if header.startswith(prefix) else ""
        if not supplied:
            response = _unauthorized("send Authorization: Bearer <token>")
            return await response(scope, receive, send)
        if hmac.compare_digest(supplied, secret):
            # The operator's own key: no caller is named, so
            # mcp_server._account falls through to the bootstrap account.
            return await app(scope, receive, send)
        account_id, reason = resolve(supplied)
        if reason == "no_account":
            response = _forbidden(
                "this sign-in has no account yet -- ask to be invited")
            return await response(scope, receive, send)
        if account_id is None:
            response = _unauthorized("token not accepted", error="invalid_token")
            return await response(scope, receive, send)
        token = mcp_server.CALLER_ACCOUNT.set(account_id)
        try:
            return await app(scope, receive, send)
        finally:
            mcp_server.CALLER_ACCOUNT.reset(token)

    return wrapper


def build(dsn=None, start_job=None, job_status=None):
    """The (asgi_app, session_manager) pair, or (None, None) when MCP is
    off or misconfigured.

    Never raises: a bad MCP config must not stop the web app from
    starting, which is the rule every other optional capability in this
    project follows. It does print, because a capability that silently
    does not exist is the failure mode that hid the dead launchd job for
    eleven nights.
    """
    if not enabled():
        return None, None

    secret = token()
    if not secret:
        print(
            f"note: {ENABLED_ENV}=1 but {TOKEN_ENV} is unset -- refusing to "
            f"mount {MOUNT_PATH} rather than serve it open. Generate one with "
            "python -c \"import secrets; print(secrets.token_urlsafe(32))\"",
            file=sys.stderr,
        )
        return None, None

    try:
        server = mcp_server.build_server(
            dsn=dsn,
            start_job=start_job,
            job_status=job_status,
        )
        # streamable_http_path="/" because the parent app owns the mount
        # prefix; leaving the SDK default would serve this at /mcp/mcp.
        # stateless_http because there is no shared state between calls
        # to keep -- every tool reads the database fresh, and a stateful
        # session would only add something to lose on a --reload.
        from mcp.server.transport_security import TransportSecuritySettings

        hosts = allowed_hosts()
        security = TransportSecuritySettings(
            enable_dns_rebinding_protection="*" not in os.environ.get(HOSTS_ENV, ""),
            allowed_hosts=hosts,
            allowed_origins=hosts,
        )
        asgi = server.streamable_http_app(streamable_http_path="/",
                                          stateless_http=True,
                                          transport_security=security)
    except ImportError as exc:
        print(f"note: {ENABLED_ENV}=1 but the mcp package is missing ({exc}) "
              f"-- {MOUNT_PATH} not mounted. `pip install -r requirements.txt`.",
              file=sys.stderr)
        return None, None
    except Exception as exc:  # surfaced, never silent
        print(f"note: could not build the MCP server ({type(exc).__name__}: "
              f"{exc}) -- {MOUNT_PATH} not mounted.", file=sys.stderr)
        return None, None

    engine = "on" if mcp_server.engine_enabled() else "off"
    hosts = os.environ.get(HOSTS_ENV, "").strip() or ",".join(DEFAULT_HOSTS)
    print(f"MCP mounted at {MOUNT_PATH} (bearer auth, engine tools {engine}, "
          f"hosts {hosts})", file=sys.stderr)
    return guarded(asgi, secret), server.session_manager


@asynccontextmanager
async def session_lifespan(manager: Optional[object]):
    """Run the transport's session manager for the life of the app.

    The streamable-HTTP app is not self-starting: its session manager
    has to be entered by whoever hosts it, and a mount without this
    answers every request with a 500 that says nothing useful. Nothing
    to run when MCP is off, so this degrades to a no-op rather than
    making the parent lifespan conditional.
    """
    if manager is None:
        yield
        return
    async with manager.run():
        yield
