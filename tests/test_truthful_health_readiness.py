import asyncio

from fastapi.testclient import TestClient

import main
from core.dependency_injection import ServiceRegistry
from core.health_checker import HealthChecker


def test_readiness_fails_when_required_services_are_missing():
    registry = ServiceRegistry()
    result = asyncio.run(HealthChecker(registry).check_readiness())

    assert result["status"] == "not_ready"
    assert result["ready"] is False
    assert "planner" in result["missing_required_services"]
    assert result["checks"]["required_services_registered"] is False


def test_readiness_passes_when_all_required_services_are_registered():
    registry = ServiceRegistry()
    for name in HealthChecker.REQUIRED_SERVICES:
        registry.register(name, object())

    result = asyncio.run(HealthChecker(registry).check_readiness())

    assert result["status"] == "healthy"
    assert result["ready"] is True
    assert result["missing_required_services"] == []


def test_liveness_and_readiness_are_separate():
    client = TestClient(main.app)
    previous = getattr(main.app.state, "registry", None)
    had_registry = hasattr(main.app.state, "registry")
    try:
        if had_registry:
            delattr(main.app.state, "registry")

        live = client.get("/health")
        ready = client.get("/ready")

        assert live.status_code == 200
        assert live.json()["live"] is True
        assert live.json()["status"] == "healthy"
        assert ready.status_code == 503
        assert ready.json()["ready"] is False
        assert ready.json()["status"] == "not_ready"
    finally:
        if had_registry:
            main.app.state.registry = previous
