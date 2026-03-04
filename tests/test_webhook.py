import hashlib
import hmac
import json
from unittest.mock import patch, AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

WEBHOOK_SECRET = "test_secret"


def _sign(payload: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def _pr_payload(action: str = "opened") -> dict:
    return {
        "action": action,
        "installation": {"id": 12345},
        "repository": {
            "full_name": "owner/repo",
            "name": "repo",
            "owner": {"login": "owner"},
        },
        "pull_request": {"number": 1},
    }


@pytest.fixture(autouse=True)
def mock_settings():
    with patch("app.webhook.get_settings") as mock:
        settings = mock.return_value
        settings.github_webhook_secret = WEBHOOK_SECRET
        yield settings


class TestSignatureVerification:
    def test_valid_signature_accepted(self):
        payload = json.dumps(_pr_payload()).encode()
        sig = _sign(payload, WEBHOOK_SECRET)

        with patch("app.webhook.handle_pr_event", new_callable=AsyncMock):
            resp = client.post(
                "/webhook",
                content=payload,
                headers={
                    "X-Hub-Signature-256": sig,
                    "X-GitHub-Event": "pull_request",
                    "Content-Type": "application/json",
                },
            )
        assert resp.status_code == 200

    def test_invalid_signature_rejected(self):
        payload = json.dumps(_pr_payload()).encode()

        resp = client.post(
            "/webhook",
            content=payload,
            headers={
                "X-Hub-Signature-256": "sha256=bad",
                "X-GitHub-Event": "pull_request",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 401

    def test_missing_signature_rejected(self):
        payload = json.dumps(_pr_payload()).encode()

        resp = client.post(
            "/webhook",
            content=payload,
            headers={
                "X-GitHub-Event": "pull_request",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 401


class TestEventRouting:
    def test_pr_opened_triggers_review(self):
        payload_dict = _pr_payload("opened")
        payload = json.dumps(payload_dict).encode()
        sig = _sign(payload, WEBHOOK_SECRET)

        with patch("app.webhook.handle_pr_event", new_callable=AsyncMock) as mock_handle:
            resp = client.post(
                "/webhook",
                content=payload,
                headers={
                    "X-Hub-Signature-256": sig,
                    "X-GitHub-Event": "pull_request",
                    "Content-Type": "application/json",
                },
            )
            assert resp.status_code == 200
            assert resp.json()["status"] == "processing"

    def test_pr_synchronize_triggers_review(self):
        payload_dict = _pr_payload("synchronize")
        payload = json.dumps(payload_dict).encode()
        sig = _sign(payload, WEBHOOK_SECRET)

        with patch("app.webhook.handle_pr_event", new_callable=AsyncMock):
            resp = client.post(
                "/webhook",
                content=payload,
                headers={
                    "X-Hub-Signature-256": sig,
                    "X-GitHub-Event": "pull_request",
                    "Content-Type": "application/json",
                },
            )
            assert resp.status_code == 200
            assert resp.json()["status"] == "processing"

    def test_pr_closed_is_ignored(self):
        payload_dict = _pr_payload("closed")
        payload = json.dumps(payload_dict).encode()
        sig = _sign(payload, WEBHOOK_SECRET)

        resp = client.post(
            "/webhook",
            content=payload,
            headers={
                "X-Hub-Signature-256": sig,
                "X-GitHub-Event": "pull_request",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ignored"

    def test_non_pr_event_is_ignored(self):
        payload = json.dumps({"action": "created"}).encode()
        sig = _sign(payload, WEBHOOK_SECRET)

        resp = client.post(
            "/webhook",
            content=payload,
            headers={
                "X-Hub-Signature-256": sig,
                "X-GitHub-Event": "push",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ignored"
