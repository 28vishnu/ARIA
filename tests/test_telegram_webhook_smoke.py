"""Offline smoke tests for ARIA's public HTTP and Telegram webhook contracts.

These tests never contact Telegram or schedule real message processing.
"""
from fastapi.testclient import TestClient

import main


def test_root_reports_aria_service_identity():
    response = TestClient(main.app).get("/")
    assert response.status_code == 200
    payload = response.json()
    assert payload["system"] == "ARIA AI Operating Platform"
    assert payload["status"] == "operational"


def test_health_endpoint_is_available_without_registry():
    client = TestClient(main.app)
    previous = getattr(main.app.state, "registry", None)
    had_registry = hasattr(main.app.state, "registry")
    try:
        if had_registry:
            delattr(main.app.state, "registry")
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"
    finally:
        if had_registry:
            main.app.state.registry = previous


def test_webhook_rejects_invalid_json():
    response = TestClient(main.app).post(
        "/telegram-webhook",
        content="{not-json",
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "invalid_payload"


def test_webhook_ignores_update_without_chat_or_user():
    update_id = 987654321001
    response = TestClient(main.app).post(
        "/telegram-webhook",
        json={"update_id": update_id},
    )
    assert response.status_code == 200
    assert response.json() == {"status": "ignored", "update_id": update_id}


def test_webhook_requires_configured_owner_for_user_message(monkeypatch):
    monkeypatch.delenv("ALLOWED_TELEGRAM_USER_ID", raising=False)
    update_id = 987654321002
    response = TestClient(main.app).post(
        "/telegram-webhook",
        json={
            "update_id": update_id,
            "message": {
                "chat": {"id": 111},
                "from": {"id": 222},
                "text": "hello",
            },
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "unauthorized"
