"""
Real sign-in for the /ui shell, on Supabase Auth (2026-09-03, step 6 of
docs/tasks/task-postgres-migration.md, Mike's call).

Supabase's GoTrue does the identity work -- Google, Discord and
email+password, the passwords, the verified-email rule, account linking
-- and this module does the two things that are ours:

  1. get a person from GoTrue to a verified identity, and
  2. decide which of OUR accounts they may enter (accounts.py's
     membership gate -- signing in is not the same as having access).

Server-side, two HTTP calls, no client library: the OAuth doors redirect
to `{SUPABASE_URL}/auth/v1/authorize` (PKCE, the verifier kept in the
starlette session cookie); Supabase sends the person back to
`/auth/callback?code=...`; the code is exchanged at `/auth/v1/token`
and the returned access token -- a JWT signed by the project -- is
verified with PyJWT (HS256 on SUPABASE_JWT_SECRET, or the project's
JWKS when no secret is configured). Email+password is the same
`/auth/v1/token` with grant_type=password; sign-up is `/auth/v1/signup`.

Session = one signed, httpOnly cookie (itsdangerous URLSafeTimedSerializer)
carrying the Supabase user id, expiry-checked on every request -- the
same cookie as before, so current_user / current_account_id and every
route behind them are untouched. We verify the JWT ONCE at sign-in and
never act as the user against Supabase afterwards, so no refresh token
is stored. Logout clears the cookie (this device only).

Identity resolution after any successful GoTrue sign-in is
accounts.claim: existing mirror row -> sign in; unclaimed row with this
email (an invite, the seeded bootstrap user) -> claim it; claimed by a
different id -> refuse; new -> new mirror row, zero memberships (the
gate).

Config (env): SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_JWT_SECRET
(optional when the project uses asymmetric signing keys),
SUPABASE_PROVIDERS (comma list, default "google,discord" -- what the
sign-in page offers; enabling them is done in the Supabase dashboard),
SESSION_SECRET. Google/Discord client ids live in the dashboard now.
"""
import base64
import hashlib
import os
import secrets as _secrets
import sys
import time
from collections import defaultdict, deque
from typing import Any, Optional
from urllib.parse import quote, urlencode

import httpx
from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, URLSafeTimedSerializer

from src import accounts, db

router = APIRouter(prefix="/auth")

SESSION_COOKIE = "zp_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 30          # 30 days
MIN_PASSWORD_LEN = 8
PKCE_SESSION_KEY = "sb_pkce_verifier"
JWT_AUDIENCE = "authenticated"
DEFAULT_PROVIDERS = ("google", "discord")


def _session_secret() -> str:
    secret = os.environ.get("SESSION_SECRET")
    if not secret:
        secret = _secrets.token_urlsafe(32)
        os.environ["SESSION_SECRET"] = secret     # stable within this process
        print("note: SESSION_SECRET not set -- generated an ephemeral one; "
              "sessions will not survive a restart", file=sys.stderr)
    return secret


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(_session_secret(), salt="zp-session")


def issue_session(response, user_id: str, request: Request) -> None:
    token = _serializer().dumps({"uid": str(user_id)})
    response.set_cookie(
        SESSION_COOKIE, token,
        max_age=SESSION_MAX_AGE, httponly=True, samesite="lax",
        secure=request.url.scheme == "https",
    )


def clear_session(response) -> None:
    response.delete_cookie(SESSION_COOKIE)


# --------------------------------------------------------------------------
# dependencies
# --------------------------------------------------------------------------

def current_user(request: Request) -> Optional[dict[str, Any]]:
    """The signed-in user (the mirror row), or None. Signature + age
    checked; a stale or tampered cookie is simply an anonymous request,
    never a 500."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    try:
        data = _serializer().loads(token, max_age=SESSION_MAX_AGE)
    except BadSignature:
        return None
    uid = data.get("uid")
    return accounts.get_user(str(uid)) if uid else None


def current_account(request: Request,
                    user: Optional[dict] = None) -> Optional[dict[str, Any]]:
    """
    The active account, backed by real membership instead of a
    client-trusted cookie value: the brand cookie still expresses the
    *preference*, but only a slug the user is actually a member of can
    win; otherwise their first membership; None when they have none.
    """
    if user is None:
        user = current_user(request)
    if user is None:
        return None
    member_of = accounts.memberships(user["id"])
    if not member_of:
        return None
    preferred = request.cookies.get("brand")
    for account in member_of:
        if account["slug"] == preferred:
            return account
    return member_of[0]


def current_account_id(request: Request) -> int:
    """The account this request acts as, as a FastAPI dependency.

    Signing in is not the same as having access: a fresh user gets a
    users row and zero account_members rows on purpose (see
    accounts.py), and that state renders the membership gate. So a
    signed-in user with no membership is a 403 here, not a crash and not
    a silent fall-through to somebody else's data.

    Routes take this rather than reaching for current_account
    themselves, because a route that forgets is a route that leaks --
    this way the account id is a parameter the handler cannot use
    without declaring.

    **Deliberately NOT current_account.** They answer different
    questions, and conflating them empties Mike's board. current_account
    resolves the BRAND: it reads the brand cookie and returns the
    membership whose slug matches, which is what the brand pill switches
    and what the UI colours itself from. This returns the TENANT: the
    user's oldest membership, whichever brand they are currently looking
    at.

    That distinction is load-bearing because Mike's two accounts --
    zeropage and antihero -- are two brands of one operator sharing one
    asset bank, one board and one cast list. Scope the data by
    current_account and clicking the ANTIHERO pill scopes every query to
    account 2, which owns nothing: an empty board, no locations, no
    cast. Verified against a copy of the live database, which has all 11
    concepts under account 1.

    So: `account_id` is who owns the row, `brand` is the label on it, and
    the pill still filters by brand the way it always did -- the filter
    just happens inside the tenant now instead of being the only thing
    separating anybody from anybody.

    (The impure part, worth naming: `accounts` is serving as both tenant
    and brand table, and "oldest membership" is what picks the tenant out
    of the two. That holds for one operator with two brands and for a
    pilot user with one account. It stops holding the day one person
    legitimately belongs to two DIFFERENT operators, and that is when
    accounts has to split into tenants and brands for real.)
    """
    user = current_user(request)
    if user is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="sign in first")
    member_of = accounts.memberships(user["id"])
    if not member_of:
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="no account access")
    return min(int(a["id"]) for a in member_of)


def dev_account_id(request: Request) -> int:
    """The dev console's account: the signed-in user's TENANT when there
    is a session, otherwise the bootstrap account.

    Same tenant rule as current_account_id, and for the same reason
    (2026-09-02). This used to call `current_account`, which resolves
    the BRAND from the cookie -- so with the pill on ANTIHERO the whole
    dev console scoped itself to account 2, which owns nothing: "Draw
    ungraded concept (0)" on a database holding 29 of them, and the
    board's taste signal reading zero. That is the exact failure
    test_the_brand_pill_does_not_empty_the_board closed for /api, left
    open here because this function predates it.

    Worse than the empty page: four dev routes WRITE (a fresh grade, a
    new video, metrics, a reference pick). Every one of those made
    while the pill was on the other brand stamped account_id = 2, where
    the board, the Queue and the judge -- all of which read the tenant
    -- can never see it again. Nothing had landed there yet when this
    was found, which was luck, not design.

    What stays deliberately different from current_account_id is the
    FALLBACK. The dev console (`dev` router, DEV_TOOLS only) is the
    single operator's engine room -- never mounted on a public
    deployment, never part of a pilot -- and it has never required a
    session. Making it 403 would lock Mike out of his own workshop to
    protect it from a second user who by definition cannot reach it. So
    it degrades to the bootstrap account, and it degrades *visibly and
    in one named place* rather than by letting `account_id` default to
    None somewhere deep in the data layer. /api gets no fallback.

    The brand pill still does what it always did: it filters by brand
    (a column on the row) inside the tenant, and colours the UI.
    """
    user = current_user(request)
    if user is not None:
        member_of = accounts.memberships(user["id"])
        if member_of:
            return min(int(a["id"]) for a in member_of)
    with db.connect() as conn:
        bootstrap = db.bootstrap_account_id(conn)
    if bootstrap is None:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=503,
            detail="no accounts exist yet -- run `python -m src.accounts seed <email>`",
        )
    return bootstrap


def require_user_ui(request: Request):
    """Gate for HTML routes: no session -> the sign-in screen."""
    user = current_user(request)
    if user is None:
        raise _redirect("/signin")
    return user


def require_user_api(request: Request):
    """Gate for /api/*: no session -> 401 JSON, matching shared.js's
    error shape so the shell surfaces it as a stateline."""
    user = current_user(request)
    if user is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="sign in first")
    return user


def _redirect(url: str) -> Exception:
    """An exception that IS a redirect, so dependencies can bail out of
    HTML routes cleanly."""
    from fastapi import HTTPException
    return HTTPException(status_code=307, headers={"Location": url})


# --------------------------------------------------------------------------
# rate limiting -- in-process sliding window; the brute-force brake the
# password endpoints keep even though GoTrue has its own, so a flood
# never reaches Supabase's quota in the first place
# --------------------------------------------------------------------------

_hits: dict[tuple, deque] = defaultdict(deque)
RATE_LIMITS = {"login": (10, 60.0), "signup": (5, 60.0)}   # (max, window s)


def _rate_limited(request: Request, bucket: str) -> bool:
    limit, window = RATE_LIMITS[bucket]
    key = (bucket, request.client.host if request.client else "?")
    now = time.monotonic()
    window_hits = _hits[key]
    while window_hits and now - window_hits[0] > window:
        window_hits.popleft()
    if len(window_hits) >= limit:
        return True
    window_hits.append(now)
    return False


# --------------------------------------------------------------------------
# Supabase: configuration, the HTTP seam, the JWT
# --------------------------------------------------------------------------

def supabase_url() -> str:
    return (os.environ.get("SUPABASE_URL") or "").rstrip("/")


def configured() -> bool:
    """Whether sign-in can work at all: the project URL and its anon key.
    Live key presence, the /api/capabilities rule."""
    return bool(supabase_url() and os.environ.get("SUPABASE_ANON_KEY"))


def providers_available() -> dict[str, bool]:
    """Which OAuth buttons the sign-in page renders. A provider is
    switched on in the Supabase dashboard, which the app cannot read, so
    SUPABASE_PROVIDERS says which ones are; nothing renders when Supabase
    itself is not configured."""
    raw = os.environ.get("SUPABASE_PROVIDERS")
    enabled = {p.strip().lower() for p in raw.split(",")} if raw is not None \
        else set(DEFAULT_PROVIDERS)
    return {p: configured() and p in enabled for p in DEFAULT_PROVIDERS}


def gotrue(method: str, path: str, *, json: Optional[dict] = None,
           params: Optional[dict] = None) -> tuple[int, dict]:
    """ONE call to GoTrue. The seam the tests patch -- every HTTP
    request this module makes to Supabase goes through here, so a test
    that stubs it can be sure nothing reaches the network (conftest's
    guard catches anything that slips). Returns (status, body)."""
    anon = os.environ.get("SUPABASE_ANON_KEY") or ""
    with httpx.Client(timeout=10) as client:
        response = client.request(
            method, f"{supabase_url()}/auth/v1{path}", json=json, params=params,
            headers={"apikey": anon, "Authorization": f"Bearer {anon}",
                     "Content-Type": "application/json"})
    try:
        body = response.json()
    except ValueError:
        body = {}
    return response.status_code, body if isinstance(body, dict) else {}


def verify_token(token: str) -> Optional[dict]:
    """The claims of a Supabase access token, or None when it does not
    verify. HS256 on SUPABASE_JWT_SECRET when one is configured; the
    project's JWKS otherwise (newer projects sign asymmetrically).
    Audience "authenticated" -- an anon or service token is not a
    person."""
    import jwt
    try:
        secret = os.environ.get("SUPABASE_JWT_SECRET")
        if secret:
            return jwt.decode(token, secret, algorithms=["HS256"],
                              audience=JWT_AUDIENCE)
        key = jwt.PyJWKClient(f"{supabase_url()}/auth/v1/.well-known/jwks.json") \
            .get_signing_key_from_jwt(token)
        return jwt.decode(token, key.key, algorithms=["ES256", "RS256"],
                          audience=JWT_AUDIENCE)
    except Exception:
        return None


def _error_text(body: dict, fallback: str) -> str:
    """GoTrue's error shapes vary by version and endpoint: {msg}, {message},
    {error_description}, {error}. Read whichever is there."""
    for key in ("msg", "message", "error_description", "error"):
        value = body.get(key)
        if value and isinstance(value, str):
            return value
    return fallback


def _signin_error(message: str, mode: str = "signin") -> RedirectResponse:
    return RedirectResponse(
        f"/signin?error={quote(message)}&mode={mode}", status_code=303)


def _not_configured() -> RedirectResponse:
    return _signin_error("sign-in isn't configured yet "
                         "(SUPABASE_URL / SUPABASE_ANON_KEY)")


def _finish(request: Request, session: dict) -> RedirectResponse:
    """A GoTrue session (the token response) -> a verified identity ->
    accounts.claim -> our cookie. Every door ends here."""
    claims = verify_token(session.get("access_token") or "")
    if not claims or not claims.get("sub"):
        return _signin_error("sign-in could not be verified -- try again")
    meta = claims.get("user_metadata") or {}
    user_id, error = accounts.claim(
        claims["sub"], claims.get("email"),
        meta.get("full_name") or meta.get("name") or meta.get("user_name"),
        meta.get("avatar_url") or meta.get("picture"))
    if error:
        return _signin_error(error)
    response = RedirectResponse("/ui/accounts", status_code=303)
    issue_session(response, user_id, request)
    return response


# --------------------------------------------------------------------------
# email + password
# --------------------------------------------------------------------------

@router.post("/signup")
async def signup(request: Request, email: str = Form(...),
                 password: str = Form(...)):
    if _rate_limited(request, "signup"):
        return _signin_error("too many attempts -- wait a minute", "signup")
    if not configured():
        return _not_configured()
    email = email.strip().lower()
    if "@" not in email or "." not in email.split("@")[-1]:
        return _signin_error("enter a real email address", "signup")
    if len(password) < MIN_PASSWORD_LEN:
        return _signin_error(
            f"password needs at least {MIN_PASSWORD_LEN} characters", "signup")

    status, body = gotrue("POST", "/signup", json={"email": email, "password": password})
    if status >= 400:
        text = _error_text(body, "sign-up failed")
        if "already" in text.lower() or body.get("error_code") == "user_already_exists":
            return _signin_error(
                "an account with this email already exists -- try signing in "
                "the other way", "signin")
        return _signin_error(text, "signup")
    if not body.get("access_token"):
        # confirmation email on: Supabase made the user, no session yet
        return RedirectResponse(
            f"/signin?error={quote('check your email to confirm the address, then sign in')}"
            f"&mode=signin&email={quote(email)}", status_code=303)
    return _finish(request, body)


@router.post("/login")
async def login(request: Request, email: str = Form(...),
                password: str = Form(...)):
    if _rate_limited(request, "login"):
        return _signin_error("too many attempts -- wait a minute")
    if not configured():
        return _not_configured()
    status, body = gotrue("POST", "/token", params={"grant_type": "password"},
                          json={"email": email.strip().lower(), "password": password})
    # One generic error for every failure mode -- never reveal whether
    # the email exists or the password was wrong.
    if status >= 400 or not body.get("access_token"):
        return _signin_error("invalid email or password")
    return _finish(request, body)


@router.post("/logout")
async def logout():
    response = RedirectResponse("/signin", status_code=303)
    clear_session(response)
    return response


# --------------------------------------------------------------------------
# OAuth through Supabase (PKCE)
# --------------------------------------------------------------------------

def _pkce_pair() -> tuple[str, str]:
    verifier = _secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def _oauth_login(request: Request, provider: str):
    if not providers_available().get(provider):
        return _signin_error(f"{provider.title()} sign-in isn't configured yet "
                             "(SUPABASE_URL / SUPABASE_PROVIDERS)")
    verifier, challenge = _pkce_pair()
    request.session[PKCE_SESSION_KEY] = verifier
    query = urlencode({
        "provider": provider,
        "redirect_to": str(request.url_for("auth_callback")),
        "code_challenge": challenge,
        "code_challenge_method": "s256",
    })
    return RedirectResponse(f"{supabase_url()}/auth/v1/authorize?{query}",
                            status_code=303)


@router.get("/google/login")
async def google_login(request: Request):
    return _oauth_login(request, "google")


@router.get("/discord/login")
async def discord_login(request: Request):
    return _oauth_login(request, "discord")


@router.get("/callback", name="auth_callback")
async def auth_callback(request: Request, code: Optional[str] = None,
                        error: Optional[str] = None,
                        error_description: Optional[str] = None):
    """Where Supabase sends the person back. One callback for every
    provider: which one they used is in the token's app_metadata, and
    accounts.claim does not care."""
    if error or not code:
        return _signin_error(error_description or error
                             or "sign-in was cancelled or failed -- try again")
    verifier = request.session.pop(PKCE_SESSION_KEY, None)
    if not verifier:
        return _signin_error("sign-in session expired -- try again")
    status, body = gotrue("POST", "/token", params={"grant_type": "pkce"},
                          json={"auth_code": code, "code_verifier": verifier})
    if status >= 400 or not body.get("access_token"):
        return _signin_error(_error_text(body, "sign-in was cancelled or failed -- try again"))
    return _finish(request, body)


# The URLs the rollout checklist registered before Supabase: kept as
# aliases so an old bookmark or dashboard entry still lands.
@router.get("/google/callback")
async def google_callback(request: Request, code: Optional[str] = None,
                          error: Optional[str] = None,
                          error_description: Optional[str] = None):
    return await auth_callback(request, code, error, error_description)


@router.get("/discord/callback")
async def discord_callback(request: Request, code: Optional[str] = None,
                           error: Optional[str] = None,
                           error_description: Optional[str] = None):
    return await auth_callback(request, code, error, error_description)
