import hashlib
import hmac
import logging

from fastapi import APIRouter, Request, HTTPException
from app.config import get_settings
from app.database import get_session
from app.models import Installation, Subscription

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/payments", tags=["payments"])


def verify_dodo_signature(payload: bytes, signature: str, secret: str) -> bool:
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


@router.post("/webhook")
async def dodo_webhook(request: Request):
    settings = get_settings()
    body = await request.body()

    signature = request.headers.get("X-Dodo-Signature", "")
    if settings.dodo_webhook_secret and not verify_dodo_signature(
        body, signature, settings.dodo_webhook_secret
    ):
        raise HTTPException(status_code=401, detail="Invalid signature")

    payload = await request.json()
    event_type = payload.get("type", "")

    if event_type == "subscription.created":
        await _handle_subscription_created(payload.get("data", {}))
    elif event_type == "subscription.updated":
        await _handle_subscription_updated(payload.get("data", {}))
    elif event_type == "subscription.cancelled":
        await _handle_subscription_cancelled(payload.get("data", {}))

    return {"status": "ok"}


async def _handle_subscription_created(data: dict):
    session = get_session()
    try:
        metadata = data.get("metadata", {})
        installation_id = metadata.get("github_installation_id")
        if not installation_id:
            logger.warning("No installation_id in subscription metadata")
            return

        installation = (
            session.query(Installation)
            .filter_by(github_installation_id=int(installation_id))
            .first()
        )
        if not installation:
            logger.warning("Installation %s not found", installation_id)
            return

        sub = Subscription(
            installation_id=installation.id,
            dodo_payment_id=data.get("id"),
            status="active",
            plan="pro",
        )
        session.add(sub)
        installation.plan = "pro"
        session.commit()
        logger.info("Pro subscription activated for installation %s", installation_id)
    finally:
        session.close()


async def _handle_subscription_updated(data: dict):
    session = get_session()
    try:
        sub = (
            session.query(Subscription)
            .filter_by(dodo_payment_id=data.get("id"))
            .first()
        )
        if sub:
            sub.status = data.get("status", sub.status)
            session.commit()
    finally:
        session.close()


async def _handle_subscription_cancelled(data: dict):
    session = get_session()
    try:
        sub = (
            session.query(Subscription)
            .filter_by(dodo_payment_id=data.get("id"))
            .first()
        )
        if sub:
            sub.status = "cancelled"
            sub.plan = "basic"
            installation = (
                session.query(Installation)
                .filter_by(id=sub.installation_id)
                .first()
            )
            if installation:
                installation.plan = "basic"
            session.commit()
            logger.info("Subscription cancelled for dodo_payment_id %s", data.get("id"))
    finally:
        session.close()


def get_installation_plan(github_installation_id: int) -> str:
    session = get_session()
    try:
        installation = (
            session.query(Installation)
            .filter_by(github_installation_id=github_installation_id)
            .first()
        )
        if installation:
            return installation.plan
        return "basic"
    finally:
        session.close()
