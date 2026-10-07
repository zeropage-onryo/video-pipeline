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
import threading
import time
from contextlib import asynccontextmanager
from typing import Callable, Optional

from src import mcp_server

ENABLED_ENV = "ZEROPAGE_MCP"
TOKEN_ENV = "ZEROPAGE_MCP_TOKEN"
HOSTS_ENV = "ZEROPAGE_MCP_HOSTS"
MOUNT_PATH = "/mcp"

# --- the rate limit (2026-10-07, for the directory listing) -----------------
#
# Requests per RATE_WINDOW_S, keyed on WHO is calling once the guard has
# decided that: one bucket per signed-in account, one for the operator's
# static key. A fixed window rather than a token bucket because the
# question it answers is coarse -- "is one caller hammering a server that
# serves everybody" -- and a fixed window is the shape a person can read
# off a 429 (`Retry-After` says when the window turns over).
#
# IN-PROCESS, AND THAT IS A STATED LIMIT: the API is one Fly machine
# (fly.toml: min_machines_running = 1, one shared CPU), so one dict in
# this process IS the whole count. A second machine would mean two
# counters that each allow the full limit; the day that happens this
# moves to a shared store (Postgres is already there), and this comment
# is the reminder. The counts die with a deploy, which is fine: the limit
# protects the process that holds them.
#
# The operator's key is subject to it too, at a higher default, because
# the research agent and ops/ scripts poll `job` in a loop and must not be
# throttled like a stranger -- but an operator key leaked to a stranger
# must not be unlimited either.
RATE_ENV = "ZEROPAGE_MCP_RATE"                  # per account, per window
RATE_OPERATOR_ENV = "ZEROPAGE_MCP_RATE_OPERATOR"  # the static key
RATE_WINDOW_S = 60
DEFAULT_RATE = 120
DEFAULT_RATE_OPERATOR = 1200


def _rate(env: str, default: int) -> int:
    """Read once per request so an operator can tune it without a
    restart being the only way to find out it was set wrongly. 0 or
    garbage means the default, never "unlimited": a typo must not open
    the door."""
    raw = (os.environ.get(env) or "").strip()
    try:
        value = int(raw) if raw else default
    except ValueError:
        return default
    return value if value > 0 else default


class RateLimiter:
    """Fixed-window counter, one window per key, safe across the threads
    uvicorn and the job registry share. `clock` is injected so a test can
    turn the window over without sleeping."""

    def __init__(self, window_s: float = RATE_WINDOW_S,
                 clock: Callable[[], float] = time.monotonic):
        self.window_s = float(window_s)
        self.clock = clock
        self._lock = threading.Lock()
        self._windows: dict = {}        # key -> [window_start, count]

    def allow(self, key, limit: int) -> tuple[bool, int]:
        """(allowed, retry_after_seconds). retry_after is 0 when allowed."""
        now = self.clock()
        with self._lock:
            start, count = self._windows.get(key, (now, 0))
            if now - start >= self.window_s:
                start, count = now, 0
            if count >= limit:
                self._windows[key] = [start, count]
                return False, max(1, int(self.window_s - (now - start)) + 1)
            self._windows[key] = [start, count + 1]
            return True, 0

    def reset(self) -> None:
        with self._lock:
            self._windows.clear()


LIMITER = RateLimiter()

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


# Where a person with no workspace is sent (2026-10-07, Mike's call: one
# web sign-in first, which creates the workspace; the connector never
# creates one). Overridable because the studio's public origin is not
# this one.
SIGNUP_ENV = "ZEROPAGE_SIGNUP_URL"
DEFAULT_SIGNUP_URL = "https://zeropage.studio"


def no_account_detail() -> str:
    url = (os.environ.get(SIGNUP_ENV) or "").strip() or DEFAULT_SIGNUP_URL
    return (f"this sign-in has no workspace yet -- sign in once at {url} "
            "(your workspace is created on the first sign-in), then reconnect")


class Sessions:
    """The session managers of both servers, entered together.

    The app's lifespan (and the tests) enter ONE `run()`; two servers mean
    two managers, so this is the one thing they enter. Each manager can
    be run once per instance, which `run()` keeps true by entering both
    exactly once."""

    def __init__(self, *managers):
        self.managers = [m for m in managers if m is not None]

    @asynccontextmanager
    async def run(self):
        from contextlib import AsyncExitStack

        async with AsyncExitStack() as stack:
            for manager in self.managers:
                await stack.enter_async_context(manager.run())
            yield


def _too_many(retry_after: int, limit: int):
    from starlette.responses import JSONResponse

    # The detail says the window, so an agent that reads it stops rather
    # than retrying the identical call inside the same window.
    return JSONResponse(
        {"error": "rate_limited",
         "detail": f"over {limit} requests in {RATE_WINDOW_S}s -- wait "
                   f"{retry_after}s before calling again"},
        status_code=429,
        headers={"Retry-After": str(retry_after)})


def guarded(app, secret: str, resolve=None, limiter: Optional[RateLimiter] = None,
            listed_app=None):
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

    THE RATE LIMIT SITS AFTER THE IDENTITY CHECK, on purpose: the key is
    who the caller turned out to be, and an unauthenticated request is
    already refused by the cheaper check above it. `limiter` is injected
    the same way `resolve` is (default: the module's one `LIMITER`).

    TWO SERVERS, ROUTED BY DOOR (2026-10-07, Mike's call). The static key
    reaches `app`, the full server; a signed-in person reaches
    `listed_app`, the server built with `mcp_server.LISTED_TOOLS` only --
    no spark bank (a shared table), no web image search, no model-calling
    engine tool. Registration is per server, not per request, so hiding
    tools from one door means a second server, not a filter. With no
    `listed_app` (a test that builds one app) everybody reaches `app`.
    """
    if resolve is None:
        from .mcp_auth import account_for_token as resolve
    if limiter is None:
        limiter = LIMITER

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
            limit = _rate(RATE_OPERATOR_ENV, DEFAULT_RATE_OPERATOR)
            ok, retry_after = limiter.allow(("operator",), limit)
            if not ok:
                response = _too_many(retry_after, limit)
                return await response(scope, receive, send)
            return await app(scope, receive, send)
        account_id, reason = resolve(supplied)
        if reason == "no_account":
            response = _forbidden(no_account_detail())
            return await response(scope, receive, send)
        if account_id is None:
            response = _unauthorized("token not accepted", error="invalid_token")
            return await response(scope, receive, send)
        limit = _rate(RATE_ENV, DEFAULT_RATE)
        ok, retry_after = limiter.allow(("account", int(account_id)), limit)
        if not ok:
            response = _too_many(retry_after, limit)
            return await response(scope, receive, send)
        token = mcp_server.CALLER_ACCOUNT.set(account_id)
        try:
            return await (listed_app or app)(scope, receive, send)
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
        listed = mcp_server.build_server(
            dsn=dsn,
            start_job=start_job,
            job_status=job_status,
            listed=True,
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
        listed_asgi = listed.streamable_http_app(streamable_http_path="/",
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
    return (guarded(asgi, secret, listed_app=listed_asgi),
            Sessions(server.session_manager, listed.session_manager))


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
