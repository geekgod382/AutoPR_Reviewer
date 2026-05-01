import hashlib
import hmac
import base64
import logging
from datetime import datetime

from fastapi import APIRouter, Request, HTTPException
from app.config import get_settings
from app.database import get_session
from app.models import Installation, Subscription

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/payments", tags=["payments"])


def verify_dodo_signature(payload: bytes, headers: dict, secret: str) -> bool:
    """
    Dodo uses the Standard Webhooks spec:
    - Headers: webhook-id, webhook-timestamp, webhook-signature
    - Signed message: "{webhook-id}.{webhook-timestamp}.{raw body}"
    - Secret is base64-encoded, must be decoded before use
    - Signature header format: "v1,<base64_signature>"
    """
    try:
        webhook_id = headers.get("webhook-id", "")
        webhook_timestamp = headers.get("webhook-timestamp", "")
        webhook_signature = headers.get("webhook-signature", "")

        if not webhook_id or not webhook_timestamp or not webhook_signature:
            logger.warning("Missing Standard Webhooks headers")
            return False

        # Message to sign
        signed_content = f"{webhook_id}.{webhook_timestamp}.{payload.decode('utf-8')}"

        # Secret may be prefixed with "whsec_" — strip it, then base64-decode
        raw_secret = secret
        if raw_secret.startswith("whsec_"):
            raw_secret = raw_secret[len("whsec_") :]
        secret_bytes = base64.b64decode(raw_secret)

        # Compute expected signature
        expected = base64.b64encode(
            hmac.new(
                secret_bytes, signed_content.encode("utf-8"), hashlib.sha256
            ).digest()
        ).decode("utf-8")

        # Signature header can contain multiple sigs: "v1,sig1 v1,sig2"
        for sig_entry in webhook_signature.split(" "):
            parts = sig_entry.split(",", 1)
            if len(parts) == 2 and parts[1] == expected:
                return True

        return False

    except Exception as e:
        logger.warning("Signature verification error: %s", e)
        return False


@router.post("/webhook")
async def dodo_webhook(request: Request):
    settings = get_settings()
    body = await request.body()

    if settings.dodo_webhook_secret:
        if not verify_dodo_signature(
            body, dict(request.headers), settings.dodo_webhook_secret
        ):
            logger.warning("Dodo webhook: invalid signature — rejecting")
            raise HTTPException(status_code=401, detail="Invalid signature")

    payload = await request.json()
    event_type = payload.get("type", "")

    # DEBUG: log full payload so we can verify field names in Render logs
    logger.info(
        "Dodo webhook received | event_type=%s | full payload=%s", event_type, payload
    )

    data = payload.get("data", {})

    if event_type == "subscription.active":
        await _handle_subscription_active(data)

    elif event_type in ("subscription.updated", "subscription.renewed"):
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
    logger.info("_handle_subscription_active | data=%s", data)
    db = get_session()
    try:
        metadata = data.get("metadata", {})
        logger.info("metadata=%s", metadata)

        installation_id = metadata.get("github_installation_id")
        logger.info("parsed installation_id=%s", installation_id)

        if not installation_id:
            logger.warning(
                "No installation_id in metadata — plan will NOT be activated"
            )
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
            .filter_by(dodo_payment_id=data.get("subscription_id"))
            .first()
        )
        if not sub:
            sub = Subscription(
                installation_id=installation.id,
                dodo_payment_id=data.get("subscription_id"),
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
        logger.info(
            "✅ Pro activated for installation_id=%s owner=%s",
            installation_id,
            installation.owner,
        )

    finally:
        db.close()


async def _handle_subscription_updated(data: dict):
    logger.info("_handle_subscription_updated/renewed | data=%s", data)
    db = get_session()
    try:
        sub = (
            db.query(Subscription)
            .filter_by(dodo_payment_id=data.get("subscription_id"))
            .first()
        )
        if not sub:
            logger.warning(
                "No subscription found for subscription_id=%s",
                data.get("subscription_id"),
            )
            return

        sub.status = data.get("status", sub.status)

        expires_at = _parse_expiry(data)
        if expires_at:
            sub.expires_at = expires_at
            logger.info("Expiry updated to %s", expires_at)

        db.commit()
        logger.info(
            "Subscription updated | subscription_id=%s status=%s",
            data.get("subscription_id"),
            sub.status,
        )
    finally:
        db.close()


async def _handle_subscription_cancelled(data: dict):
    logger.info("_handle_subscription_cancelled | data=%s", data)
    db = get_session()
    try:
        sub = (
            db.query(Subscription)
            .filter_by(dodo_payment_id=data.get("subscription_id"))
            .first()
        )
        if not sub:
            logger.warning(
                "No subscription found to cancel for subscription_id=%s",
                data.get("subscription_id"),
            )
            return

        sub.status = "cancelled"
        sub.plan = "basic"

        installation = db.query(Installation).filter_by(id=sub.installation_id).first()
        if installation:
            installation.plan = "basic"

        db.commit()
        logger.info(
            "Subscription cancelled for subscription_id=%s", data.get("subscription_id")
        )
    finally:
        db.close()


async def _handle_payment_succeeded(data: dict):
    """
    Fallback — activates Pro if subscription.active was missed or delayed.
    Safe to call multiple times — skips if already Pro.
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
            logger.warning(
                "payment.succeeded: installation %s not in DB", installation_id
            )
            return

        if installation.plan == "pro":
            logger.info("payment.succeeded: already Pro — skipping")
            return

        installation.plan = "pro"

        existing_sub = (
            db.query(Subscription)
            .filter_by(installation_id=installation.id, status="active")
            .first()
        )
        if not existing_sub:
            sub = Subscription(
                installation_id=installation.id,
                dodo_payment_id=data.get("payment_id"),
                status="active",
                plan="pro",
                expires_at=_parse_expiry(data),
            )
            db.add(sub)

        db.commit()
        logger.info(
            "✅ Pro activated via payment.succeeded fallback for installation_id=%s",
            installation_id,
        )

    finally:
        db.close()


def _parse_expiry(data: dict) -> datetime | None:
    """
    Extract expiry date from Dodo webhook data.
    Confirmed field name from Dodo docs/sample payload: next_billing_date
    """
    raw = (
        data.get("next_billing_date")  # confirmed Dodo field
        or data.get("current_period_end")
        or data.get("expires_at")
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
