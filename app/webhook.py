import hashlib
import hmac
import logging

from fastapi import APIRouter, Request, HTTPException, BackgroundTasks
from app.config import get_settings
from app.reviewer import handle_pr_event

logger = logging.getLogger(__name__)
router = APIRouter()


def verify_signature(payload: bytes, signature: str, secret: str) -> bool:
    expected = "sha256=" + hmac.new(
        secret.encode(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


@router.post("/webhook")
async def github_webhook(request: Request, background_tasks: BackgroundTasks):
    settings = get_settings()
    body = await request.body()

    signature = request.headers.get("X-Hub-Signature-256", "")
    if not verify_signature(body, signature, settings.github_webhook_secret):
        raise HTTPException(status_code=401, detail="Invalid signature")

    event = request.headers.get("X-GitHub-Event", "")
    payload = await request.json()

    if event == "pull_request":
        action = payload.get("action", "")
        if action in ("opened", "synchronize"):
            logger.info(
                "PR #%s %s on %s",
                payload["pull_request"]["number"],
                action,
                payload["repository"]["full_name"],
            )
            background_tasks.add_task(handle_pr_event, payload)
            return {"status": "processing"}

    return {"status": "ignored"}
