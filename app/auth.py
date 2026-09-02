"""
Real sign-in for the /ui shell: Google OAuth, Discord OAuth, and
email/password. Three doors into one `users` table; membership in
`account_members` -- not the fact of being signed in -- is what opens
Mike's two real accounts (see require gate notes below).

Session = one signed, httpOnly cookie (itsdangerous URLSafeTimedSerializer)
carrying the user id, expiry-checked on every request -- consistent with
how the app already treats the `brand` cookie, no server-side session
table for v1. Logout clears the cookie (this device only).

Identity resolution on an OAuth callback, in order:
  1. (provider, subject) identity exists        -> sign that user in.
  2. email matches a user with NO password and
     NO identities (the seeded bootstrap user)  -> attach the identity.
  3. email matches any other user               -> "already exists, sign
     in the way you first signed up" (never silently merged).
  4. brand-new email                            -> new user + identity,
     zero memberships (the gate).

Secrets (client ids/secrets, the signing key) come from env only.
Without a SESSION_SECRET an ephemeral key is generated with a loud
stderr note -- dev keeps working, sessions just don't survive restarts.
"""
import os
import secrets as _secrets
import sys
import time
from collections import defaultdict, deque
from typing import Any, Optional
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, URLSafeTimedSerializer

from src import accounts, db

router = APIRouter(prefix="/auth")

SESSION_COOKIE = "zp_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 30          # 30 days
MIN_PASSWORD_LEN = 8

DISCORD_AUTHORIZE = "https://discord.com/oauth2/authorize"
DISCORD_TOKEN = "https://discord.com/api/oauth2/token"
DISCORD_ME = "https://discord.com/api/users/@me"
GOOGLE_DISCOVERY = "https://accounts.google.com/.well-known/openid-configuration"


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


def issue_session(response, user_id: int, request: Request) -> None:
    token = _serializer().dumps({"user_id": user_id})
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
    """The signed-in user, or None. Signature + age checked; a stale or
    tampered cookie is simply an anonymous request, never a 500."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    try:
        data = _serializer().loads(token, max_age=SESSION_MAX_AGE)
    except BadSignature:
        return None
    return accounts.get_user(int(data["user_id"]), path=db.DB_PATH)


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
    member_of = accounts.memberships(user["id"], path=db.DB_PATH)
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
    member_of = accounts.memberships(user["id"], path=db.DB_PATH)
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
        member_of = accounts.memberships(user["id"], path=db.DB_PATH)
        if member_of:
            return min(int(a["id"]) for a in member_of)
    with db.connect(db.DB_PATH) as conn:
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
# password endpoints need, without a new dependency
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
# password hashing (argon2)
# --------------------------------------------------------------------------

def hash_password(password: str) -> str:
    from argon2 import PasswordHasher
    return PasswordHasher().hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    from argon2 import PasswordHasher
    from argon2.exceptions import VerificationError
    try:
        return PasswordHasher().verify(password_hash, password)
    except VerificationError:
        return False


# --------------------------------------------------------------------------
# email + password routes
# --------------------------------------------------------------------------

def _signin_error(message: str, mode: str = "signin") -> RedirectResponse:
    return RedirectResponse(
        f"/signin?error={quote(message)}&mode={mode}", status_code=303)


@router.post("/signup")
async def signup(request: Request, email: str = Form(...),
                 password: str = Form(...)):
    if _rate_limited(request, "signup"):
        return _signin_error("too many attempts -- wait a minute", "signup")
    email = email.strip().lower()
    if "@" not in email or "." not in email.split("@")[-1]:
        return _signin_error("enter a real email address", "signup")
    if len(password) < MIN_PASSWORD_LEN:
        return _signin_error(
            f"password needs at least {MIN_PASSWORD_LEN} characters", "signup")
    if accounts.get_user_by_email(email, path=db.DB_PATH):
        return _signin_error(
            "an account with this email already exists -- try signing in "
            "the other way", "signin")

    user_id = accounts.create_user(email, password_hash=hash_password(password),
                                   path=db.DB_PATH)
    response = RedirectResponse("/ui/accounts", status_code=303)
    issue_session(response, user_id, request)
    return response


@router.post("/login")
async def login(request: Request, email: str = Form(...),
                password: str = Form(...)):
    if _rate_limited(request, "login"):
        return _signin_error("too many attempts -- wait a minute")
    user = accounts.get_user_by_email(email, path=db.DB_PATH)
    # One generic error for every failure mode -- never reveal whether
    # the email exists or the password was wrong.
    if not user or not user["password_hash"] \
            or not verify_password(user["password_hash"], password):
        return _signin_error("invalid email or password")

    response = RedirectResponse("/ui/accounts", status_code=303)
    issue_session(response, user["id"], request)
    return response


@router.post("/logout")
async def logout():
    response = RedirectResponse("/signin", status_code=303)
    clear_session(response)
    return response


# --------------------------------------------------------------------------
# OAuth -- Authlib clients. Google is OIDC (discovery + JWKS-verified id
# token); Discord is plain OAuth2 (no OIDC): the trust boundary is the
# authenticated /users/@me call over the token Discord itself issued.
# --------------------------------------------------------------------------

_oauth = None


def _get_oauth():
    global _oauth
    if _oauth is None:
        from authlib.integrations.starlette_client import OAuth
        _oauth = OAuth()
        _oauth.register(
            name="google",
            client_id=os.environ.get("GOOGLE_CLIENT_ID"),
            client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
            server_metadata_url=GOOGLE_DISCOVERY,
            client_kwargs={"scope": "openid email profile"},
        )
        _oauth.register(
            name="discord",
            client_id=os.environ.get("DISCORD_CLIENT_ID"),
            client_secret=os.environ.get("DISCORD_CLIENT_SECRET"),
            authorize_url=DISCORD_AUTHORIZE,
            access_token_url=DISCORD_TOKEN,
            client_kwargs={"scope": "identify email"},
        )
    return _oauth


def _provider_configured(provider: str) -> bool:
    prefix = provider.upper()
    return bool(os.environ.get(f"{prefix}_CLIENT_ID")
                and os.environ.get(f"{prefix}_CLIENT_SECRET"))


def _resolve_oauth_user(provider: str, subject: str, email: Optional[str],
                        display_name: Optional[str],
                        avatar_url: Optional[str]) -> tuple:
    """The identity-resolution ladder from the module docstring.
    Returns (user_id, error) -- exactly one is set."""
    identity = accounts.get_identity(provider, subject, path=db.DB_PATH)
    if identity:
        accounts.update_profile(identity["user_id"], display_name, avatar_url,
                                path=db.DB_PATH)
        return identity["user_id"], None

    if not email:
        return None, (f"{provider} did not return a verified email for this "
                      "account -- verify your email there and try again")
    user = accounts.get_user_by_email(email, path=db.DB_PATH)
    if user:
        with db.connect(db.DB_PATH) as conn:
            has_identities = conn.execute(
                "SELECT 1 FROM auth_identities WHERE user_id = ?",
                (user["id"],)).fetchone()
        if user["password_hash"] is None and not has_identities:
            # the seeded bootstrap user: first provider sign-in claims it
            accounts.add_identity(user["id"], provider, subject, path=db.DB_PATH)
            accounts.update_profile(user["id"], display_name, avatar_url,
                                    path=db.DB_PATH)
            return user["id"], None
        return None, ("an account with this email already exists -- sign in "
                      "the way you first signed up")

    user_id = accounts.create_user(email, display_name=display_name,
                                   avatar_url=avatar_url, path=db.DB_PATH)
    accounts.add_identity(user_id, provider, subject, path=db.DB_PATH)
    return user_id, None


@router.get("/google/login")
async def google_login(request: Request):
    if not _provider_configured("google"):
        return _signin_error("Google sign-in isn't configured yet "
                             "(GOOGLE_CLIENT_ID/SECRET)")
    redirect_uri = str(request.url_for("google_callback"))
    return await _get_oauth().google.authorize_redirect(request, redirect_uri)


@router.get("/google/callback")
async def google_callback(request: Request):
    try:
        token = await _get_oauth().google.authorize_access_token(request)
    except Exception:
        return _signin_error("Google sign-in was cancelled or failed -- try again")
    # authorize_access_token verifies the ID token against Google's JWKS
    # (state param included) -- the claims below are authenticated.
    claims = token.get("userinfo") or {}
    return _finish_oauth(request, "google", claims.get("sub"),
                         claims.get("email"), claims.get("name"),
                         claims.get("picture"))


@router.get("/discord/login")
async def discord_login(request: Request):
    if not _provider_configured("discord"):
        return _signin_error("Discord sign-in isn't configured yet "
                             "(DISCORD_CLIENT_ID/SECRET)")
    redirect_uri = str(request.url_for("discord_callback"))
    return await _get_oauth().discord.authorize_redirect(request, redirect_uri)


@router.get("/discord/callback")
async def discord_callback(request: Request):
    try:
        token = await _get_oauth().discord.authorize_access_token(request)
    except Exception:
        return _signin_error("Discord sign-in was cancelled or failed -- try again")
    # Discord doesn't put the profile in the token response -- it comes
    # from the authenticated /users/@me call, which IS the trust boundary.
    profile = await fetch_discord_profile(token["access_token"])
    if profile is None:
        return _signin_error("could not read your Discord profile -- try again")
    avatar = None
    if profile.get("avatar"):
        avatar = (f"https://cdn.discordapp.com/avatars/{profile['id']}/"
                  f"{profile['avatar']}.png")
    # Discord's email can be null (e.g. unverified) -- resolve treats
    # that as a clear failure, never a NULL users.email row.
    email = profile.get("email") if profile.get("verified") else None
    return _finish_oauth(request, "discord", profile.get("id"), email,
                         profile.get("global_name") or profile.get("username"),
                         avatar)


async def fetch_discord_profile(access_token: str) -> Optional[dict]:
    """Separate + async so tests patch it and no test ever hits Discord."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                DISCORD_ME, headers={"Authorization": f"Bearer {access_token}"})
            response.raise_for_status()
            return response.json()
    except Exception:
        return None


def _finish_oauth(request: Request, provider: str, subject, email,
                  display_name, avatar_url):
    if not subject:
        return _signin_error(f"{provider} returned no account id -- try again")
    user_id, error = _resolve_oauth_user(provider, str(subject), email,
                                         display_name, avatar_url)
    if error:
        return _signin_error(error)
    response = RedirectResponse("/ui/accounts", status_code=303)
    issue_session(response, user_id, request)
    return response
