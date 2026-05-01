import logging
from datetime import datetime, timezone
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.database import get_session
from app.github_client import get_installation
from app.models import Installation, ReviewLog, Subscription
from app.oauth import get_session_data

logger = logging.getLogger(__name__)

router = APIRouter(tags=["web"])
templates = Jinja2Templates(directory="app/templates")

GITHUB_USER_INSTALLATIONS_URL = "https://api.github.com/user/installations"


def _build_checkout_url(base_url: str, installation_id: int, success_url: str) -> str:
    """
    Build a Dodo static checkout URL with metadata.
    Dodo passes query params prefixed with `metadata_` into the subscription metadata.
    e.g. ?metadata_github_installation_id=123 → data.metadata.github_installation_id = "123"
    """
    params = urlencode(
        {
            "metadata_github_installation_id": str(installation_id),
            "redirect_url": success_url,
        }
    )
    return f"{base_url}&{params}"


@router.get("/", response_class=HTMLResponse)
async def landing(request: Request):
    settings = get_settings()
    install_url = (
        f"https://github.com/apps/{settings.github_app_slug}/installations/new"
    )
    session = get_session_data(request)

    user_plan = "basic"
    user_pro_installation_id = None

    if session and session.get("user_login"):
        db = get_session()
        try:
            installations = (
                db.query(Installation).filter_by(owner=session["user_login"]).all()
            )
            for inst in installations:
                if inst.plan == "pro":
                    user_plan = "pro"
                    user_pro_installation_id = inst.github_installation_id
                    break
        finally:
            db.close()

    return templates.TemplateResponse(
        "landing.html",
        {
            "request": request,
            "install_url": install_url,
            "user": session,
            "user_plan": user_plan,
            "user_pro_installation_id": user_pro_installation_id,
            "oauth_enabled": bool(settings.github_client_id),
        },
    )


@router.get("/api/installations", response_class=JSONResponse)
async def list_installations(request: Request):
    settings = get_settings()

    if not settings.github_client_id:
        db = get_session()
        try:
            installations = db.query(Installation).all()
            return [
                {
                    "installation_id": inst.github_installation_id,
                    "owner": inst.owner,
                    "plan": inst.plan,
                    "created_at": (
                        inst.created_at.isoformat() if inst.created_at else None
                    ),
                }
                for inst in installations
            ]
        finally:
            db.close()

    session_data = get_session_data(request)
    if not session_data:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated. Please log in with GitHub first.",
        )

    access_token = session_data["access_token"]
    github_installation_ids: set[int] = set()
    page = 1
    async with httpx.AsyncClient() as client:
        while True:
            resp = await client.get(
                GITHUB_USER_INSTALLATIONS_URL,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/vnd.github+json",
                },
                params={"per_page": 100, "page": page},
            )
            if resp.status_code == 401:
                raise HTTPException(
                    status_code=401,
                    detail="GitHub token expired or revoked. Please log in again.",
                )
            resp.raise_for_status()
            data = resp.json()
            batch = data.get("installations", [])
            if not batch:
                break
            for inst in batch:
                github_installation_ids.add(inst["id"])
            if len(batch) < 100:
                break
            page += 1

    if not github_installation_ids:
        return []

    db = get_session()
    try:
        installations = (
            db.query(Installation)
            .filter(Installation.github_installation_id.in_(github_installation_ids))
            .all()
        )
        return [
            {
                "installation_id": inst.github_installation_id,
                "owner": inst.owner,
                "plan": inst.plan,
                "created_at": inst.created_at.isoformat() if inst.created_at else None,
            }
            for inst in installations
        ]
    finally:
        db.close()


@router.get("/setup", response_class=HTMLResponse)
async def setup(request: Request, installation_id: int):
    settings = get_settings()

    try:
        gh_installation = await get_installation(installation_id)
    except Exception:
        logger.exception("Failed to fetch installation %s from GitHub", installation_id)
        raise HTTPException(status_code=404, detail="Installation not found on GitHub")

    owner = gh_installation.get("account", {}).get("login", "unknown")

    db = get_session()
    try:
        installation = (
            db.query(Installation)
            .filter_by(github_installation_id=installation_id)
            .first()
        )
        if not installation:
            installation = Installation(
                github_installation_id=installation_id,
                owner=owner,
                plan="basic",
            )
            db.add(installation)
            db.commit()
            db.refresh(installation)
        else:
            installation.owner = owner
            db.commit()
    finally:
        db.close()

    dashboard_url = f"{settings.app_url}/dashboard?installation_id={installation_id}"
    pro_checkout_url = ""
    if settings.dodo_checkout_url:
        pro_checkout_url = _build_checkout_url(
            settings.dodo_checkout_url,
            installation_id,
            f"{dashboard_url}&flash=pro_activated",
        )

    return templates.TemplateResponse(
        "setup.html",
        {
            "request": request,
            "installation_id": installation_id,
            "owner": owner,
            "dashboard_url": dashboard_url,
            "pro_checkout_url": pro_checkout_url,
        },
    )


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, installation_id: int, flash: str = ""):
    settings = get_settings()

    db = get_session()
    try:
        installation = (
            db.query(Installation)
            .filter_by(github_installation_id=installation_id)
            .first()
        )
        if not installation:
            raise HTTPException(status_code=404, detail="Installation not found")

        review_count = (
            db.query(ReviewLog).filter_by(installation_id=installation.id).count()
        )

        active_sub = (
            db.query(Subscription)
            .filter_by(installation_id=installation.id, status="active")
            .order_by(Subscription.created_at.desc())
            .first()
        )
    finally:
        db.close()

    expiry_days = None
    if active_sub and active_sub.expires_at:
        now = datetime.now(timezone.utc)
        expires = active_sub.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        delta = (expires - now).days
        if 0 <= delta <= 7:
            expiry_days = delta

    dashboard_url = f"{settings.app_url}/dashboard?installation_id={installation_id}"
    upgrade_url = None
    cancel_url = None

    if installation.plan != "pro":
        if settings.dodo_checkout_url:
            upgrade_url = _build_checkout_url(
                settings.dodo_checkout_url,
                installation_id,
                f"{dashboard_url}&flash=pro_activated",
            )
    else:
        cancel_url = f"/cancel-subscription?installation_id={installation_id}"

    manage_url = f"https://github.com/settings/installations/{installation_id}"

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "installation": installation,
            "review_count": review_count,
            "upgrade_url": upgrade_url,
            "cancel_url": cancel_url,
            "manage_url": manage_url,
            "flash": flash,
            "expiry_days": expiry_days,
        },
    )


@router.get("/cancel-subscription")
async def cancel_subscription(installation_id: int):
    db = get_session()

    installation = (
        db.query(Installation).filter_by(github_installation_id=installation_id).first()
    )
    if installation:
        installation.plan = "basic"
        db.commit()

    db.close()

    return RedirectResponse(
        f"/dashboard?installation_id={installation_id}&flash=cancelled",
        status_code=303,
    )
