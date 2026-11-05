"""Focused Phase 3 security regression tests (no external services)."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import sys
import time

import pytest
from fastapi.testclient import TestClient

import main
from core.logging_config import JSONFormatter

OWNER_ID = "424242"
TOKEN_SECRET = "phase3-test-signing-secret-32-chars"


class FakeSecurityCollection:
    """Minimal async stand-in for the MongoDB app_security collection."""

    def __init__(self, record: dict | None):
        self.record = dict(record or {})

    async def find_one(self, query):
        if not self.record:
            return None
        if query.get("_id") != self.record.get("_id"):
            return None
        return dict(self.record)

    async def update_one(self, query, update, upsert=False):
        for key, value in update.get("$set", {}).items():
            if key.startswith("devices."):
                self.record.setdefault("devices", {})[key.split(".", 1)[1]] = value
            else:
                self.record[key] = value
        return None


def _token(version: int = 1, device: str = "test-device") -> str:
    return main._make_owner_token(OWNER_ID, device, version)


def _expired_token() -> str:
    payload = f"{OWNER_ID}|test-device|{int(time.time()) - 10}|1".encode("utf-8")
    encoded = main._b64url(payload)
    signature = main._b64url(
        hmac.new(TOKEN_SECRET.encode(), encoded.encode("ascii"), hashlib.sha256).digest()
    )
    return f"{encoded}.{signature}"


def _telegram_payload(update_id: int, user_id: int = 424242) -> dict:
    return {
        "update_id": update_id,
        "message": {
            "message_id": 1,
            "chat": {"id": user_id},
            "from": {"id": user_id},
            "text": "hello",
        },
    }


@pytest.fixture(autouse=True)
def _isolate_security_state(monkeypatch):
    main._login_failures.clear()
    main._telegram_update_cache.clear()
    if hasattr(main.app.state, "registry"):
        monkeypatch.delattr(main.app.state, "registry")
    yield
    main._login_failures.clear()
    main._telegram_update_cache.clear()


@pytest.fixture
def owner_env(monkeypatch):
    monkeypatch.setenv("ARIA_OWNER_TELEGRAM_ID", OWNER_ID)
    monkeypatch.setenv("ARIA_OWNER_APP_SECRET", "phase3-initial-password")
    monkeypatch.setenv("ARIA_APP_TOKEN_SECRET", TOKEN_SECRET)
    return monkeypatch


@pytest.fixture
def authorized_client(monkeypatch):
    fake = FakeSecurityCollection({"_id": OWNER_ID, "token_version": 1})
    monkeypatch.setattr(main, "_security_collection", lambda request: fake)
    return TestClient(main.app), fake


def test_health_is_public_and_hardened():
    response = TestClient(main.app).get("/health")
    assert response.status_code == 200
    assert response.json()["live"] is True
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"


def test_readiness_without_registry_returns_503():
    response = TestClient(main.app).get("/ready")
    assert response.status_code == 503
    assert response.json()["ready"] is False
    assert response.json()["status"] == "not_ready"


def test_private_routers_reject_anonymous_requests():
    client = TestClient(main.app)
    for path in (
        "/workspace/overview",
        "/ai/providers/status",
        "/integrations/status",
        "/jarvis/status",
        "/drive/status",
        "/app/notifications",
    ):
        response = client.get(path)
        assert response.status_code == 401, path


def test_login_missing_configuration_fails_closed(monkeypatch):
    for name in (
        "ARIA_OWNER_TELEGRAM_ID",
        "ARIA_OWNER_APP_SECRET",
        "ARIA_APP_TOKEN_SECRET",
    ):
        monkeypatch.delenv(name, raising=False)
    response = TestClient(main.app).post(
        "/app/login",
        json={"telegram_id": OWNER_ID, "secret": "x", "device_id": "test-device"},
    )
    assert response.status_code == 503
    assert response.headers.get("Cache-Control") == "no-store"


def test_login_without_mongodb_returns_503(owner_env):
    response = TestClient(main.app).post(
        "/app/login",
        json={"telegram_id": OWNER_ID, "secret": "phase3-initial-password", "device_id": "test-device"},
    )
    assert response.status_code == 503
    assert "MONGODB_URI" in response.json()["detail"]


def test_invalid_token_returns_401(owner_env):
    response = TestClient(main.app).get(
        "/app/notifications",
        headers={"Authorization": "Bearer not-a-valid-token"},
    )
    assert response.status_code == 401


def test_expired_token_is_rejected(owner_env):
    assert main._decode_owner_token(_expired_token()) is None
    response = TestClient(main.app).get(
        "/app/notifications",
        headers={"Authorization": f"Bearer {_expired_token()}"},
    )
    assert response.status_code == 401


def test_valid_token_decodes(owner_env):
    claims = main._decode_owner_token(_token(version=3))
    assert claims is not None
    assert claims["owner_id"] == OWNER_ID
    assert claims["device_id"] == "test-device"
    assert claims["version"] == 3


def test_revoked_token_version_is_rejected(owner_env, monkeypatch):
    fake = FakeSecurityCollection({"_id": OWNER_ID, "token_version": 2})
    monkeypatch.setattr(main, "_security_collection", lambda request: fake)
    response = TestClient(main.app).get(
        "/app/notifications",
        headers={"Authorization": f"Bearer {_token(version=1)}"},
    )
    assert response.status_code == 401
    assert "revoked" in response.json()["detail"].lower()


def test_valid_owner_session_reaches_protected_route(owner_env, authorized_client):
    client, _ = authorized_client
    response = client.get(
        "/ai/providers/status",
        headers={"Authorization": f"Bearer {_token()}"},
    )
    assert response.status_code == 200
    assert response.json()["providers"]["nvidia_nim"]["strict_no_llm"] is True


def test_password_hash_roundtrip_and_constant_time_check():
    salt, digest = main._password_hash("correct horse battery staple")
    record = {"password_salt": salt, "password_hash": digest}
    assert main._password_matches("correct horse battery staple", record) is True
    assert main._password_matches("wrong password", record) is False
    assert main._password_matches("", {"password_salt": "bad", "password_hash": "bad"}) is False


def test_password_change_invalidates_previous_tokens(owner_env, monkeypatch):
    salt, digest = main._password_hash("old-password")
    fake = FakeSecurityCollection(
        {
            "_id": OWNER_ID,
            "password_salt": salt,
            "password_hash": digest,
            "token_version": 1,
        }
    )
    monkeypatch.setattr(main, "_security_collection", lambda request: fake)
    client = TestClient(main.app)
    headers = {"Authorization": f"Bearer {_token(version=1)}"}

    changed = client.post(
        "/app/change-password",
        headers=headers,
        json={"current_password": "old-password", "new_password": "new-password-123"},
    )
    assert changed.status_code == 200
    assert fake.record["token_version"] == 2

    reused = client.get("/app/notifications", headers=headers)
    assert reused.status_code == 401


def test_password_change_rejects_short_password(owner_env, monkeypatch):
    salt, digest = main._password_hash("old-password")
    fake = FakeSecurityCollection(
        {"_id": OWNER_ID, "password_salt": salt, "password_hash": digest, "token_version": 1}
    )
    monkeypatch.setattr(main, "_security_collection", lambda request: fake)
    response = TestClient(main.app).post(
        "/app/change-password",
        headers={"Authorization": f"Bearer {_token()}"},
        json={"current_password": "old-password", "new_password": "short"},
    )
    assert response.status_code == 400


def test_login_throttle_blocks_after_repeated_failures(owner_env):
    client = TestClient(main.app)
    payload = {"telegram_id": "999999", "secret": "wrong", "device_id": "test-device"}
    for _ in range(main.LOGIN_MAX_FAILURES):
        assert client.post("/app/login", json=payload).status_code == 401
    blocked = client.post("/app/login", json=payload)
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) >= 1


def test_telegram_webhook_requires_owner_configuration(monkeypatch):
    monkeypatch.delenv("ALLOWED_TELEGRAM_USER_ID", raising=False)
    response = TestClient(main.app).post("/telegram-webhook", json=_telegram_payload(1001))
    assert response.status_code == 200
    assert response.json()["status"] == "unauthorized"


def test_telegram_webhook_rejects_unauthorized_user(monkeypatch):
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_ID", OWNER_ID)
    scheduled = []
    monkeypatch.setattr(
        main.background_manager,
        "schedule",
        lambda coro: (scheduled.append(coro), coro.close(), object())[2],
    )
    response = TestClient(main.app).post(
        "/telegram-webhook",
        json=_telegram_payload(1002, user_id=777777),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "unauthorized"
    assert scheduled == []


def test_telegram_webhook_secret_token_enforced(monkeypatch):
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_ID", OWNER_ID)
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "phase3-webhook-secret")
    client = TestClient(main.app)
    payload = _telegram_payload(1003)

    missing = client.post("/telegram-webhook", json=payload)
    assert missing.status_code == 401

    wrong = client.post(
        "/telegram-webhook",
        json=payload,
        headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
    )
    assert wrong.status_code == 401

    accepted = client.post(
        "/telegram-webhook",
        json=_telegram_payload(1004),
        headers={"X-Telegram-Bot-Api-Secret-Token": "phase3-webhook-secret"},
    )
    assert accepted.status_code == 200
    assert accepted.json()["status"] in {"accepted", "temporarily_unavailable"}


def test_chat_error_does_not_leak_exception_details(owner_env, monkeypatch):
    fake = FakeSecurityCollection({"_id": OWNER_ID, "token_version": 1})
    monkeypatch.setattr(main, "_security_collection", lambda request: fake)

    async def _boom(*args, **kwargs):
        raise RuntimeError("super-secret-internal-detail")

    monkeypatch.setattr(main, "process_task", _boom)
    response = TestClient(main.app).post(
        "/chat",
        headers={"Authorization": f"Bearer {_token()}"},
        json={"message": "hello", "session_id": "test"},
    )
    assert response.status_code == 200
    assert "super-secret-internal-detail" not in response.text


def test_global_exception_handler_hides_details():
    response = asyncio.run(
        main.global_exception_handler(None, ValueError("super-secret-internal-detail"))
    )
    assert response.status_code == 500
    assert b"super-secret-internal-detail" not in response.body


def test_log_sanitizer_redacts_known_secret_forms():
    raw = (
        "Authorization: Bearer abc.def.ghi "
        "api_key=plain-secret-value "
        "https://api.telegram.org/bot123456:ABC-DEF/getMe "
        "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    )
    sanitized = main._sanitize_log_text(raw)
    for secret in (
        "abc.def.ghi",
        "plain-secret-value",
        "123456:ABC-DEF",
        "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
    ):
        assert secret not in sanitized
    assert "[REDACTED]" in sanitized


def test_json_log_formatter_redacts_exception_text():
    try:
        raise RuntimeError("Bearer leaked-bearer-token api_key=leaked-key")
    except RuntimeError:
        record = logging.LogRecord(
            name="aria",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="failure",
            args=(),
            exc_info=sys.exc_info(),
        )
    rendered = JSONFormatter().format(record)
    assert "leaked-bearer-token" not in rendered
    assert "leaked-key" not in rendered
    assert json.loads(rendered)["level"] == "ERROR"
