import secrets
import logging
import httpx

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import RedirectResponse
from urllib.parse import urlencode
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

from app.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"

# read:user  → basic profile info
# read:org   → see org memberships (required for /user/installations on org accounts)
OAUTH_SCOPE = "read:user read:org"

SESSION_COOKIE = "autopr_session"
SESSION_MAX_AGE = 60 * 60 * 8  # 8 hours


# ── Helpers ───────────────────────────────────────────────────────────────────

def _serializer() -> URLSafeTimedSerializer:
    settings = get_settings()
    return URLSafeTimedSerializer(settings.session_secret_key, salt="autopr-session")


def get_session_data(request: Request) -> dict | None:
    """
    Decode and return the session dict from the signed cookie.
    Returns None if the cookie is missing, expired, or tampered with.
    """
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        return None
    try:
        return _serializer().loads(raw, max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None


def _set_session_cookie(response: RedirectResponse, data: dict) -> None:
    signed = _serializer().dumps(data)
    response.set_cookie(
        key=SESSION_COOKIE,
        value=signed,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=True,
    )


def _clear_session_cookie(response: RedirectResponse) -> None:
    response.delete_cookie(SESSION_COOKIE)


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/login")
async def oauth_login(request: Request, next: str = "/"):
    """
    Kick off the GitHub OAuth flow.
    `next` is the URL to redirect to after successful login.
    """
    settings = get_settings()
    if not settings.github_client_id:
        raise HTTPException(
            status_code=500,
            detail="GITHUB_CLIENT_ID is not configured. Add it to your .env file.",
        )

    state = secrets.token_urlsafe(16)

    state_serializer = URLSafeTimedSerializer(settings.session_secret_key, salt="oauth-state")
    state_cookie_value = state_serializer.dumps({"state": state, "next": next})

    params = urlencode({
        "client_id": settings.github_client_id,
        "redirect_uri": f"{settings.app_url}/auth/callback",
        "scope": OAUTH_SCOPE,
        "state": state,
    })
    github_url = f"{GITHUB_AUTHORIZE_URL}?{params}"

    response = RedirectResponse(github_url, status_code=302)
    response.set_cookie(
        "oauth_state",
        state_cookie_value,
        max_age=300,
        httponly=True,
        samesite="lax",
    )
    return response


@router.get("/callback")
async def oauth_callback(
    request: Request,
    code: str = "",
    state: str = "",
    error: str = "",
    installation_id: int = None,   # GitHub sends this when coming from a fresh install
    setup_action: str = "",        # GitHub sends "install" or "update"
):
    """
    GitHub redirects here after the user authorises the app.

    Two entry points land here:
      1. Normal login via /auth/login  → `next` comes from the signed state cookie
      2. Fresh install (checkbox enabled) → GitHub appends `installation_id`
         and `setup_action=install` to the URL automatically

    For case 2 we redirect to /setup so the new user can choose their plan.
    For case 1 we redirect to wherever `next` pointed (usually "/").
    """
    settings = get_settings()

    if error:
        logger.warning("OAuth denied by user: %s", error)
        return RedirectResponse("/?oauth_error=denied", status_code=302)

    if not code:
        raise HTTPException(status_code=400, detail="Missing code parameter")

    # ── Determine where to redirect after login ───────────────────────────────
    # Priority: fresh install > state cookie next value > fallback "/"

    if installation_id and setup_action == "install":
        # Brand-new installation — send user to plan selection
        next_url = f"/setup?installation_id={installation_id}"
        logger.info("Fresh install detected for installation_id=%s", installation_id)
    elif state:
        # Normal login flow — verify CSRF state and read `next` from cookie
        raw_state_cookie = request.cookies.get("oauth_state", "")
        state_serializer = URLSafeTimedSerializer(settings.session_secret_key, salt="oauth-state")
        try:
            state_data = state_serializer.loads(raw_state_cookie, max_age=300)
        except (BadSignature, SignatureExpired):
            raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")

        if state_data.get("state") != state:
            raise HTTPException(status_code=400, detail="State mismatch — possible CSRF attempt")

        next_url = state_data.get("next", "/")
    else:
        next_url = "/"

    # ── Exchange code for access token ────────────────────────────────────────
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            GITHUB_TOKEN_URL,
            headers={"Accept": "application/json"},
            data={
                "client_id": settings.github_client_id,
                "client_secret": settings.github_client_secret,
                "code": code,
                "redirect_uri": f"{settings.app_url}/auth/callback",
            },
        )
        token_resp.raise_for_status()
        token_data = token_resp.json()

    access_token = token_data.get("access_token")
    if not access_token:
        logger.error("GitHub token exchange failed: %s", token_data)
        raise HTTPException(status_code=502, detail="Failed to obtain access token from GitHub")

    granted_scopes = token_data.get("scope", "")
    logger.info("OAuth token granted scopes: %s", granted_scopes)

    # ── Fetch user info ───────────────────────────────────────────────────────
    async with httpx.AsyncClient() as client:
        user_resp = await client.get(
            GITHUB_USER_URL,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github+json",
            },
        )
        user_resp.raise_for_status()
        user_data = user_resp.json()

    session = {
        "access_token": access_token,
        "user_login": user_data.get("login"),
        "user_avatar": user_data.get("avatar_url"),
        "user_name": user_data.get("name") or user_data.get("login"),
        "scopes": granted_scopes,
    }

    response = RedirectResponse(next_url, status_code=302)
    response.delete_cookie("oauth_state")
    _set_session_cookie(response, session)
    logger.info("OAuth login successful for user: %s → %s", session["user_login"], next_url)
    return response


@router.get("/logout")
async def oauth_logout():
    """Clear the session cookie and redirect to landing page."""
    response = RedirectResponse("/", status_code=302)
    _clear_session_cookie(response)
    return response
