import logging
from urllib.parse import urlencode

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.database import get_session
from app.github_client import get_installation
from app.models import Installation, ReviewLog

logger = logging.getLogger(__name__)

router = APIRouter(tags=["web"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
async def landing(request: Request):
    settings = get_settings()
    install_url = f"https://github.com/apps/{settings.github_app_slug}/installations/new"
    return templates.TemplateResponse(
        "landing.html",
        {"request": request, "install_url": install_url},
    )


@router.get("/setup", response_class=HTMLResponse)
async def setup(request: Request, installation_id: int):
    settings = get_settings()

    # Fetch installation info from GitHub and upsert DB record
    try:
        gh_installation = await get_installation(installation_id)
    except Exception:
        logger.exception("Failed to fetch installation %s from GitHub", installation_id)
        raise HTTPException(status_code=404, detail="Installation not found on GitHub")

    owner = gh_installation.get("account", {}).get("login", "unknown")

    session = get_session()
    try:
        installation = (
            session.query(Installation)
            .filter_by(github_installation_id=installation_id)
            .first()
        )
        if not installation:
            installation = Installation(
                github_installation_id=installation_id,
                owner=owner,
                plan="basic",
            )
            session.add(installation)
            session.commit()
            session.refresh(installation)
        else:
            installation.owner = owner
            session.commit()
    finally:
        session.close()

    # Build Dodo checkout URL for Pro upgrade
    dashboard_url = f"{settings.app_url}/dashboard?installation_id={installation_id}"
    pro_checkout_url = ""
    if settings.dodo_checkout_url:
        params = urlencode({
            "metadata[github_installation_id]": str(installation_id),
            "success_url": dashboard_url,
        })
        pro_checkout_url = f"{settings.dodo_checkout_url}?{params}"

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
async def dashboard(request: Request, installation_id: int):
    settings = get_settings()

    session = get_session()
    try:
        installation = (
            session.query(Installation)
            .filter_by(github_installation_id=installation_id)
            .first()
        )
        if not installation:
            raise HTTPException(status_code=404, detail="Installation not found")

        review_count = (
            session.query(ReviewLog)
            .filter_by(installation_id=installation.id)
            .count()
        )
    finally:
        session.close()

    # Build upgrade URL
    dashboard_url = f"{settings.app_url}/dashboard?installation_id={installation_id}"
    upgrade_url = ""
    if settings.dodo_checkout_url and installation.plan != "pro":
        params = urlencode({
            "metadata[github_installation_id]": str(installation_id),
            "success_url": dashboard_url,
        })
        upgrade_url = f"{settings.dodo_checkout_url}?{params}"

    manage_url = f"https://github.com/settings/installations/{installation_id}"

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "installation": installation,
            "review_count": review_count,
            "upgrade_url": upgrade_url,
            "manage_url": manage_url,
        },
    )
