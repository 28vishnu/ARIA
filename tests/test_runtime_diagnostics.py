import asyncio

from core.dependency_injection import ServiceRegistry
from core.health_checker import HealthChecker
from core.runtime_diagnostics import runtime_diagnostics


def test_runtime_diagnostics_contains_measured_process_facts():
    result = runtime_diagnostics()
    assert result["process"]["pid"] > 0
    assert result["process"]["uptime_seconds"] >= 0
    assert result["python"]["version"]
    assert result["memory"]["rss_bytes"] is None or result["memory"]["rss_bytes"] > 0
    assert result["memory"]["rss_mb"] is None or result["memory"]["rss_mb"] > 0


def test_readiness_includes_runtime_diagnostics_without_claiming_external_health():
    registry = ServiceRegistry()
    for name in HealthChecker.REQUIRED_SERVICES:
        registry.register(name, object())
    result = asyncio.run(HealthChecker(registry).check_readiness())
    assert result["ready"] is True
    assert result["runtime_diagnostics"]["process"]["pid"] > 0
    assert any("third-party" in note for note in result["runtime_diagnostics"]["limitations"])
