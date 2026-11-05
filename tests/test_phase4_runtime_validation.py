"""Focused Phase 4 runtime, configuration and dependency-handling tests."""
from __future__ import annotations

import asyncio
from pathlib import Path

import main
from brain.development.filesystem_guard import FilesystemGuard
from core.configuration import load_config
from core.dependency_injection import ServiceRegistry
from core.health_checker import HealthChecker

ROOT = Path(__file__).resolve().parents[1]


def test_env_example_declares_google_redirects_and_runtime_keys():
    keys = set()
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            keys.add(line.split("=", 1)[0].strip())

    assert "GOOGLE_OAUTH_REDIRECT_URI" in keys
    assert "GOOGLE_CALENDAR_REDIRECT_URI" in keys
    assert "GOOGLE_DRIVE_REDIRECT_URI" in keys
    assert "LOG_LEVEL" in keys
    assert "ARIA_OWNER_TELEGRAM_ID" in keys
    assert "ARIA_APP_TOKEN_SECRET" in keys


def test_config_prefers_jarvis_names_and_falls_back_to_legacy(monkeypatch):
    monkeypatch.setenv("JARVIS_ENVIRONMENT", "staging")
    monkeypatch.setenv("AR_ENVIRONMENT", "legacy")
    assert load_config().environment == "staging"

    monkeypatch.delenv("JARVIS_ENVIRONMENT")
    assert load_config().environment == "legacy"


def test_sandbox_environment_keeps_windows_system_vars_without_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("SYSTEMROOT", r"C:\Windows")
    monkeypatch.setenv("OPENAI_API_KEY", "should-not-leak")
    monkeypatch.setenv("ARIA_APP_TOKEN_SECRET", "should-not-leak")

    environment = FilesystemGuard(tmp_path).environment()

    assert environment.get("SYSTEMROOT") == r"C:\Windows"
    assert "OPENAI_API_KEY" not in environment
    assert "ARIA_APP_TOKEN_SECRET" not in environment


class _FakeAdmin:
    def __init__(self, *, fail: bool):
        self._fail = fail

    async def command(self, _name):
        if self._fail:
            raise RuntimeError("mongo unavailable")
        return {"ok": 1}


class _FakeMongoClient:
    def __init__(self, *, fail: bool):
        self.admin = _FakeAdmin(fail=fail)


def _registry_with_required_services(client) -> ServiceRegistry:
    registry = ServiceRegistry()
    for name in HealthChecker.REQUIRED_SERVICES:
        registry.register(name, object())
    registry.register("mongo_client", client)
    return registry


def test_readiness_fails_when_configured_mongo_ping_fails():
    registry = _registry_with_required_services(_FakeMongoClient(fail=True))
    result = asyncio.run(HealthChecker(registry).check_readiness())

    assert result["ready"] is False
    assert result["checks"]["mongodb_reachable"] is False
    assert any("MongoDB health probe failed" in note for note in result["limitations"])


def test_readiness_passes_when_configured_mongo_ping_succeeds():
    registry = _registry_with_required_services(_FakeMongoClient(fail=False))
    result = asyncio.run(HealthChecker(registry).check_readiness())

    assert result["ready"] is True
    assert result["checks"]["mongodb_reachable"] is True


def test_unintegrated_dashboard_router_is_not_mounted():
    paths = set(main.app.openapi()["paths"])
    assert "/dashboard/telemetry" not in paths
