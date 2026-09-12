"""A model login is separate from the studio session and belongs to one user."""
from fastapi import APIRouter, Depends, HTTPException, Request

from src import personal_models

from . import auth

router = APIRouter(prefix="/model-connections")


def connection_scope(request, account_id):
    user = auth.current_user(request)
    if not user:
        raise HTTPException(401, "Sign in first.")
    return personal_models.scope_id(user["id"], account_id)


def local_browser(request):
    return bool(request.client and request.client.host in ("127.0.0.1", "::1")
                and request.url.hostname in ("localhost", "127.0.0.1", "::1"))


def mutation_header(request):
    # Forces a CORS preflight for browser requests from another origin.
    # SameSite=None studio sessions must not accept cross-site login/logout forms.
    if request.headers.get("x-zpf-model-connection") != "1":
        raise HTTPException(403, "Use the studio's model connection controls.")


def provider_status(scope, provider, request):
    if not personal_models.executable(provider):
        return {"available": False, "connected": False, "models": [],
                "message": f"Install {'Codex' if provider == 'chatgpt' else 'Claude Code'} on the studio server."}
    try:
        if provider == "chatgpt":
            session = personal_models.codex_session(scope)
            result = session.status()
            result["models"] = session.models() if result["connected"] else []
        else:
            result = personal_models.claude_status(scope)
            result["models"] = personal_models.CLAUDE_MODELS if result["connected"] else []
            result["can_sign_in"] = local_browser(request)
            if not result["connected"] and not result["can_sign_in"]:
                result["message"] = (
                    "Claude's personal sign-in opens on the studio computer. "
                    "Connect from localhost on that computer; a hosted website needs a desktop bridge.")
        return result
    except personal_models.ConnectionUnavailable as exc:
        return {"available": True, "connected": False, "models": [], "message": str(exc)}


@router.get("")
def connections(request: Request, account_id: int = Depends(auth.current_account_id)):
    scope = connection_scope(request, account_id)
    return {provider: provider_status(scope, provider, request) for provider in ("chatgpt", "claude")}


@router.get("/{provider}")
def connection_status(provider: str, request: Request,
                      account_id: int = Depends(auth.current_account_id)):
    if provider not in ("chatgpt", "claude"):
        raise HTTPException(404, "Unknown provider.")
    return provider_status(connection_scope(request, account_id), provider, request)


@router.post("/{provider}/signin")
def signin(provider: str, request: Request, account_id: int = Depends(auth.current_account_id)):
    mutation_header(request)
    scope = connection_scope(request, account_id)
    try:
        if provider == "chatgpt":
            return personal_models.codex_session(scope).start_login()
        if provider == "claude":
            if not local_browser(request):
                raise HTTPException(409, "Open the studio on localhost to use Claude Code's native sign-in.")
            return personal_models.claude_login(scope)
        raise HTTPException(404, "Unknown provider.")
    except personal_models.ConnectionUnavailable as exc:
        raise HTTPException(503, str(exc)) from None


@router.post("/{provider}/disconnect")
def disconnect(provider: str, request: Request,
               account_id: int = Depends(auth.current_account_id)):
    mutation_header(request)
    scope = connection_scope(request, account_id)
    try:
        personal_models.disconnect(scope, provider)
        return {"connected": False}
    except personal_models.ConnectionUnavailable as exc:
        raise HTTPException(409, str(exc)) from None
