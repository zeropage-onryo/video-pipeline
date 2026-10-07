"""The OAuth consent page -- what Supabase's OAuth 2.1 server sends a person
to when an MCP client (Claude) asks to act on their studio (2026-10-07,
docs/directory/OAUTH_TEST.md Finding 3).

WHY IT IS OURS TO SERVE. Supabase is the authorization server: it validates
the client, PKCE and the redirect, issues the code and the tokens. It does
NOT draw the consent screen. Its /oauth/authorize redirects the person to
`<Site URL><Authorization Path>?authorization_id=<id>` and waits for the
app to answer, AS THE PERSON, either

    GET  /auth/v1/oauth/authorizations/{id}           -> the details, or a
                                                         redirect_url when
                                                         they consented before
    POST /auth/v1/oauth/authorizations/{id}/consent   {"action": "approve"|"deny"}
                                                      -> {"redirect_url": ...}

(read off supabase-js's `_getAuthorizationDetails` / `_approveAuthorization`
/ `_denyAuthorization`, 2026-10-07). Until this page existed the connector
could not be connected from claude.ai at all: the flow ended on a 404.

WHERE THE PERSON'S TOKEN COMES FROM. Both calls need the person's own
Supabase access token, and this app keeps none -- the zp_session cookie
carries only the verified user id (app/auth.py's docstring says why). So
the page sends the person through the ordinary sign-in, whichever door
they like, and `resume` -- called from `auth._finish`, which every door
ends in -- parks THAT sign-in's access token in the starlette session for
this one step, beside a CSRF value, keyed to the authorization id. The
POST spends it and drops it. The same pattern as the password reset
(`RESET_TOKEN_SESSION_KEY`): a token minted for one write, never stored
past it. Signing in here also runs `_provision`, so a person whose first
contact with the studio is the connector gets their workspace on this
page, which is the "one web sign-in first" Mike chose for first contact.

WHAT IT SHOWS. The client's name, the HOST of the redirect URI in bold
(the connector checklist's "display the redirect URI's hostname clearly",
with the spec's extra warning when it is a loopback address -- any local
process can claim one), the scopes, and who is signing in. Nothing here
spends money or reads the board.
"""
from __future__ import annotations

import hmac
import re
import secrets as _secrets
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote, urlsplit

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from . import auth

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

CONSENT_PATH = "/oauth/consent"
PENDING_KEY = "oauth_consent_pending"   # an authorization id waiting on a sign-in
GRANT_KEY = "oauth_consent_grant"       # {"id", "token", "csrf"} for one decision

# Supabase's authorization ids are UUIDs today; accept a little more than
# that, never anything that could break out of a URL path segment.
_ID = re.compile(r"^[A-Za-z0-9_-]{8,128}$")
LOOPBACK = {"localhost", "127.0.0.1", "::1"}
# How long a consent waits on a sign-in. Supabase's own authorization
# request expires in minutes; past this the pending id is forgotten, so a
# person who walked away is not shown "Connect an app" on their next visit.
PENDING_MAX_AGE = 15 * 60


def _valid_id(authorization_id: str) -> bool:
    return bool(_ID.match(authorization_id or ""))


def pending(request: Request) -> Optional[str]:
    """The authorization id a sign-in on this browser is FOR, if any --
    what /signin reads to say why the person is there and to skip its
    already-signed-in shortcut (the consent needs a fresh Supabase
    session even when our own cookie is good)."""
    value = request.session.get(PENDING_KEY)
    if not isinstance(value, dict) or not _valid_id(value.get("id") or ""):
        return None
    if time.time() - float(value.get("at") or 0) > PENDING_MAX_AGE:
        request.session.pop(PENDING_KEY, None)
        return None
    return value["id"]


def resume(request: Request, session: dict) -> Optional[RedirectResponse]:
    """Called from auth._finish with the GoTrue session a sign-in just
    produced. When a consent was waiting, keep that sign-in's access token
    for the decision and go back to the page; otherwise None and the
    sign-in finishes as it always has."""
    authorization_id = pending(request)
    request.session.pop(PENDING_KEY, None)
    if authorization_id is None:
        return None
    token = session.get("access_token") or ""
    if not token:
        return None
    request.session[GRANT_KEY] = {"id": authorization_id, "token": token,
                                  "csrf": _secrets.token_urlsafe(24)}
    return RedirectResponse(f"{CONSENT_PATH}?authorization_id={quote(authorization_id)}",
                            status_code=303)


def _grant(request: Request, authorization_id: str) -> Optional[dict]:
    """The parked grant for THIS authorization id, while its token still
    verifies (Supabase access tokens last about an hour)."""
    grant = request.session.get(GRANT_KEY)
    if not isinstance(grant, dict) or grant.get("id") != authorization_id:
        return None
    if not auth.verify_token(grant.get("token") or ""):
        request.session.pop(GRANT_KEY, None)
        return None
    return grant


def _to_signin(request: Request, authorization_id: str) -> RedirectResponse:
    request.session[PENDING_KEY] = {"id": authorization_id, "at": time.time()}
    request.session.pop(GRANT_KEY, None)
    return RedirectResponse("/signin", status_code=303)


def _page(request: Request, status: int = 200, **context: Any) -> HTMLResponse:
    return templates.TemplateResponse(request, "oauth_consent.html", context,
                                      status_code=status)


def _problem(request: Request, message: str, status: int = 400) -> HTMLResponse:
    return _page(request, status, problem=message)


def _safe_redirect(url: Any) -> Optional[str]:
    """Supabase's redirect_url, followed only when it is an absolute
    http(s) URL -- the authorization server validated the client's
    redirect URI, this just refuses to 303 to a javascript: or a path."""
    if not isinstance(url, str):
        return None
    parts = urlsplit(url)
    return url if parts.scheme in ("https", "http") and parts.netloc else None


def _host(uri: Any) -> str:
    try:
        parts = urlsplit(uri or "")
    except ValueError:
        return ""
    return (parts.hostname or "").lower()


def describe(details: dict) -> dict:
    """The details Supabase returned, as the page draws them. Pure, so the
    exact words a person approves are testable without a server."""
    client = details.get("client") or {}
    redirect_host = _host(details.get("redirect_uri"))
    scopes = [s for s in str(details.get("scope") or "").split() if s]
    return {
        "client_name": str(client.get("name") or "An application"),
        "client_host": _host(client.get("uri")),
        "redirect_host": redirect_host or "(no redirect address)",
        "loopback": redirect_host in LOOPBACK,
        "scopes": scopes,
        "email": str((details.get("user") or {}).get("email") or ""),
    }


@router.get(CONSENT_PATH)
def consent_page(request: Request, authorization_id: str = ""):
    if not _valid_id(authorization_id):
        return _problem(request, "This link is missing its authorization request. "
                                 "Start the connection again from the app you came from.")
    if not auth.configured():
        return _problem(request, "Sign-in isn't configured on this server.", 503)
    if auth._rate_limited(request, "consent"):
        return _problem(request, "Too many attempts -- wait a minute and try again.", 429)
    grant = _grant(request, authorization_id)
    if grant is None:
        return _to_signin(request, authorization_id)

    status, body = auth.gotrue("GET", f"/oauth/authorizations/{quote(authorization_id)}",
                               token=grant["token"])
    if status == 401:
        return _to_signin(request, authorization_id)
    if status >= 400:
        request.session.pop(GRANT_KEY, None)
        return _problem(request, auth._error_text(
            body, "This authorization request has expired or was already used. "
                  "Start the connection again from the app you came from."))
    if "authorization_id" not in body:
        # consented before: Supabase hands back the client's redirect directly
        request.session.pop(GRANT_KEY, None)
        target = _safe_redirect(body.get("redirect_url"))
        if target:
            return RedirectResponse(target, status_code=303)
        return _problem(request, "The authorization server gave no way back to the app.", 502)
    return _page(request, authorization_id=authorization_id, csrf=grant["csrf"],
                 **describe(body))


@router.post(CONSENT_PATH)
def consent_decision(request: Request, authorization_id: str = Form(""),
                     decision: str = Form(""), csrf: str = Form("")):
    if not _valid_id(authorization_id):
        return _problem(request, "This form is missing its authorization request.")
    if auth._rate_limited(request, "consent"):
        return _problem(request, "Too many attempts -- wait a minute and try again.", 429)
    grant = _grant(request, authorization_id)
    if grant is None:
        # the token expired, or this browser never signed in for it: start over
        return _to_signin(request, authorization_id)
    if not hmac.compare_digest(str(csrf), str(grant.get("csrf") or "")):
        return _problem(request, "This form has expired. Go back and try again.", 403)
    action = "approve" if decision == "approve" else "deny"
    status, body = auth.gotrue(
        "POST", f"/oauth/authorizations/{quote(authorization_id)}/consent",
        json={"action": action}, token=grant["token"])
    # one decision per sign-in: the token is dropped whatever the answer
    request.session.pop(GRANT_KEY, None)
    if status >= 400:
        return _problem(request, auth._error_text(
            body, "The authorization server refused that answer. "
                  "Start the connection again from the app you came from."))
    target = _safe_redirect(body.get("redirect_url"))
    if not target:
        return _problem(request, "The authorization server gave no way back to the app.", 502)
    return RedirectResponse(target, status_code=303)
