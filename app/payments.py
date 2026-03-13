import hashlib
import hmac
import logging
from datetime import datetime

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

    # DEBUG: log full payload so we can inspect field names in Render logs
    logger.info("Dodo webhook received | event_type=%s | full payload=%s", event_type, payload)

    data = payload.get("data", {})

    if event_type == "subscription.active":
        # Primary trigger — subscription confirmed and paid
        await _handle_subscription_active(data)

    elif event_type in ("subscription.updated", "subscription.renewed"):
        # renewed = billing cycle succeeded, expiry extended
        # updated = general status/metadata change
        await _handle_subscription_updated(data)

    elif event_type == "subscription.cancelled":
        await _handle_subscription_cancelled(data)

    elif event_type == "payment.succeeded":
        # Fallback — activates Pro if subscription.active was missed or delayed
        await _handle_payment_succeeded(data)

    else:
        logger.warning("Dodo webhook: unhandled event_type=%s", event_type)

    return {"status": "ok"}


async def _handle_subscription_active(data: dict):
    """
    Fires when a subscription becomes active (payment confirmed).
    This is the primary event for granting Pro access.
    """
    logger.info("_handle_subscription_active | data=%s", data)
    db = get_session()
    try:
        metadata = data.get("metadata", {})
        logger.info("metadata=%s", metadata)

        installation_id = metadata.get("github_installation_id")
        logger.info("parsed installation_id=%s", installation_id)

        if not installation_id:
            logger.warning("No installation_id in metadata — plan will NOT be activated")
            return

        installation = (
            db.query(Installation)
            .filter_by(github_installation_id=int(installation_id))
            .first()
        )
        if not installation:
            logger.warning("Installation %s not found in DB", installation_id)
            return

        expires_at = _parse_expiry(data)

        # Upsert — safe to call multiple times, won't create duplicate rows
        sub = (
            db.query(Subscription)
            .filter_by(dodo_payment_id=data.get("id"))
            .first()
        )
        if not sub:
            sub = Subscription(
                installation_id=installation.id,
                dodo_payment_id=data.get("id"),
                status="active",
                plan="pro",
                expires_at=expires_at,
            )
            db.add(sub)
        else:
            sub.status = "active"
            sub.plan = "pro"
            if expires_at:
                sub.expires_at = expires_at

        installation.plan = "pro"
        db.commit()
        logger.info("✅ Pro activated for installation_id=%s owner=%s", installation_id, installation.owner)

    finally:
        db.close()


async def _handle_subscription_updated(data: dict):
    logger.info("_handle_subscription_updated/renewed | data=%s", data)
    db = get_session()
    try:
        sub = (
            db.query(Subscription)
            .filter_by(dodo_payment_id=data.get("id"))
            .first()
        )
        if not sub:
            logger.warning("No subscription found for dodo_payment_id=%s", data.get("id"))
            return

        sub.status = data.get("status", sub.status)

        # On renewal, push expires_at forward so the expiry banner resets
        expires_at = _parse_expiry(data)
        if expires_at:
            sub.expires_at = expires_at
            logger.info("Expiry updated to %s for dodo_payment_id=%s", expires_at, data.get("id"))

        db.commit()
        logger.info("Subscription updated | dodo_payment_id=%s status=%s", data.get("id"), sub.status)
    finally:
        db.close()


async def _handle_subscription_cancelled(data: dict):
    logger.info("_handle_subscription_cancelled | data=%s", data)
    db = get_session()
    try:
        sub = (
            db.query(Subscription)
            .filter_by(dodo_payment_id=data.get("id"))
            .first()
        )
        if not sub:
            logger.warning("No subscription found to cancel for dodo_payment_id=%s", data.get("id"))
            return

        sub.status = "cancelled"
        sub.plan = "basic"

        installation = (
            db.query(Installation)
            .filter_by(id=sub.installation_id)
            .first()
        )
        if installation:
            installation.plan = "basic"

        db.commit()
        logger.info("Subscription cancelled for dodo_payment_id=%s", data.get("id"))
    finally:
        db.close()


async def _handle_payment_succeeded(data: dict):
    """
    Fallback — activates Pro if subscription.active was missed or delayed.
    Safe to call multiple times — skips if installation is already Pro.
    """
    logger.info("_handle_payment_succeeded | data=%s", data)
    db = get_session()
    try:
        metadata = data.get("metadata", {})
        installation_id = metadata.get("github_installation_id")

        if not installation_id:
            logger.info("payment.succeeded: no installation_id in metadata — skipping")
            return

        installation = (
            db.query(Installation)
            .filter_by(github_installation_id=int(installation_id))
            .first()
        )
        if not installation:
            logger.warning("payment.succeeded: installation %s not in DB", installation_id)
            return

        # Already Pro — subscription.active already handled it
        if installation.plan == "pro":
            logger.info("payment.succeeded: installation %s already Pro — skipping", installation_id)
            return

        # Activate Pro as fallback
        installation.plan = "pro"

        existing_sub = (
            db.query(Subscription)
            .filter_by(installation_id=installation.id, status="active")
            .first()
        )
        if not existing_sub:
            sub = Subscription(
                installation_id=installation.id,
                dodo_payment_id=data.get("id"),
                status="active",
                plan="pro",
                expires_at=_parse_expiry(data),
            )
            db.add(sub)

        db.commit()
        logger.info("✅ Pro activated via payment.succeeded fallback for installation_id=%s", installation_id)

    finally:
        db.close()


def _parse_expiry(data: dict) -> datetime | None:
    """Extract and parse expiry date from Dodo webhook data."""
    raw = (
        data.get("current_period_end")
        or data.get("expires_at")
        or data.get("next_billing_date")
    )
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        logger.warning("Could not parse expiry date: %s", raw)
        return None


def get_installation_plan(github_installation_id: int) -> str:
    db = get_session()
    try:
        installation = (
            db.query(Installation)
            .filter_by(github_installation_id=github_installation_id)
            .first()
        )
        return installation.plan if installation else "basic"
    finally:
        db.close()
