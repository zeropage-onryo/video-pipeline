"""WHO is calling /mcp -- the static token, or a person's own sign-in.

The mount has had exactly one caller since it was written: an agent on
Mike's machine holding `ZEROPAGE_MCP_TOKEN`, acting as the bootstrap
account (`mcp_server._account`). That is correct for a secret only the
operator holds, and wrong the moment anybody else can reach it: a second
person signing in would read the first person's board, which is the one
failure this file exists to prevent.

So there are two doors now, and they are NOT the same door with
different credentials:

- **The static token** is the operator's own key. It is compared with
  `hmac.compare_digest` before the MCP app is entered, and it keeps
  acting as the bootstrap account, exactly as before. Nothing about
  Claude Code, the research node or `ops/` changes.
- **A Supabase access token** is a person. Supabase's OAuth 2.1 server is
  the authorization server (it does the PKCE dance, the consent screen
  and dynamic client registration that the Claude connector needs); this
  app is only the RESOURCE server, which means its whole job is to
  verify the token, refuse anything it cannot verify, and resolve the
  caller to ONE account id.

`account_for_token` is that resolution and it is deliberately the same
rule `auth.current_account_id` uses for the web app -- the tenant is the
user's OLDEST membership (`min(id)`), not the brand cookie, not the
first row alphabetically. Two doors onto one board must not disagree
about whose board it is.

**The audience check is load-bearing.** Supabase mints session tokens
with `aud: "authenticated"` and OAuth tokens FOR a resource, so both are
accepted, but only against a named audience: a token minted for another
resource server must not work here (MCP authorization spec, "Token
Handling"). `resource_url()` is that name, and it is also what the
metadata document publishes, so the two cannot drift.

Nothing here spends money or reads a row: it answers "who" and hands an
account id to `mcp_mount`.
"""
from __future__ import annotations

import os
from typing import Any, Optional

from src import accounts

from . import auth, seo

RESOURCE_ENV = "ZEROPAGE_MCP_RESOURCE"
METADATA_PATH = "/.well-known/oauth-protected-resource"


def resource_url() -> str:
    """This server's canonical URI (RFC 8707 section 2).

    `SITE_URL` + the mount path, which is what a client that reached us
    at `https://zeropage-studio.fly.dev/mcp` will send as `resource`.
    Overridable because a deployment behind a different public hostname
    than `SITE_URL` (a tunnel, a custom domain) would otherwise publish a
    name no token is ever minted for. No trailing slash: the spec asks
    for the un-slashed form.
    """
    override = (os.environ.get(RESOURCE_ENV) or "").strip()
    return (override or f"{seo.site_url()}/mcp").rstrip("/")


def _origin_and_path() -> tuple[str, str]:
    """The resource URI split into `https://host` and `/path`.

    Everything else here is built off THIS rather than off `site_url()`
    directly, which is not a nicety: on Fly, `SITE_URL` is unset and
    defaults to `http://127.0.0.1:8000`, so a metadata document built
    from it would publish a localhost resource to a connector reaching us
    at fly.dev -- a document that discovers nothing, with no error to
    read. One name, one place, whichever env var supplied it.
    """
    parts = resource_url().split("/", 3)
    origin = "/".join(parts[:3])
    return origin, f"/{parts[3]}" if len(parts) > 3 and parts[3] else ""


def metadata_url() -> str:
    """Where the document below is served. RFC 9728 inserts the
    resource's path AFTER the well-known segment, so a server at /mcp
    publishes at /.well-known/oauth-protected-resource/mcp."""
    origin, path = _origin_and_path()
    return f"{origin}{METADATA_PATH}{path}"


def authorization_server() -> str:
    """Supabase's OAuth 2.1 issuer, which is NOT the project URL.

    Probed against the live project rather than assumed (2026-09-25),
    because publishing the wrong one fails in the least readable way
    there is -- the client fetches our document, discovers nothing, and
    reports a generic "no OAuth server":

        {project}/.well-known/oauth-authorization-server        -> 404
        {project}/.well-known/openid-configuration              -> 404
        {project}/auth/v1/.well-known/oauth-authorization-server -> 200
        {project}/.well-known/oauth-authorization-server/auth/v1 -> 200

    The last one is the form a client derives from an issuer WITH a
    path (RFC 8414 inserts the well-known segment before it), so naming
    `/auth/v1` is what makes discovery resolve either way round.
    """
    base = auth.supabase_url()
    return f"{base}/auth/v1" if base else ""


def protected_resource_metadata() -> dict[str, Any]:
    """The RFC 9728 document. Pure, so the exact bytes a connector reads
    are testable without a server -- app/seo.py's rule.

    `scopes_supported` is deliberately absent: the spec tells a client to
    omit the scope parameter when the resource does not publish one, and
    publishing a scope this server does not actually enforce would be a
    claim, not a control.
    """
    return {
        "resource": resource_url(),
        "authorization_servers": [authorization_server()] if authorization_server() else [],
        "bearer_methods_supported": ["header"],
        "resource_documentation": f"{_origin_and_path()[0]}/llms.txt",
    }


def challenge() -> str:
    """The WWW-Authenticate value. A 401 that does not name the metadata
    document is a dead end for a connector: discovery starts here."""
    return f'Bearer resource_metadata="{metadata_url()}"'


def configured() -> bool:
    """Whether the OAuth door can work at all -- there is an
    authorization server to point at. False means the static token is the
    only way in, which is the pre-2026-09-24 posture and a fine one."""
    return bool(auth.supabase_url())


def verify(token: str) -> Optional[dict[str, Any]]:
    """The claims of a token this server will accept, or None.

    Two audiences, checked in order and never skipped: this resource
    (what Supabase's OAuth server mints for a connector) and the ordinary
    session audience (what a `zp_session` sign-in carries, which is what
    makes a token pasted from the app's own console work while the
    connector flow is being wired up).
    """
    for audience in (resource_url(), auth.JWT_AUDIENCE):
        claims = auth.verify_token(token, audience=audience)
        if claims:
            return claims
    return None


def account_for_token(token: str, dsn: Optional[str] = None) -> tuple[Optional[int], str]:
    """`(account_id, reason)` for a bearer token that is not the static one.

    `reason` is the OAuth error code the caller gets back, because the
    three failures are three different things and a connector can only
    act on the difference: `invalid_token` means sign in again,
    `insufficient_scope` (no membership) means somebody has to invite
    you, and no account id ever means "fall back to the operator".
    """
    claims = verify(token)
    if not claims:
        return None, "invalid_token"
    user_id = claims.get("sub")
    if not user_id:
        return None, "invalid_token"
    member_of = accounts.memberships(str(user_id), dsn=dsn)
    if not member_of:
        return None, "no_account"
    return min(int(a["id"]) for a in member_of), "ok"
