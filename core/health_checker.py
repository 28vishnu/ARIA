"""Truthful readiness checks for the ARIA service registry.

A registered object is not proof that the dependency is operational. This checker
reports missing core services as not-ready and does not claim to perform network
health checks for services whose APIs are not probed here.
"""
from __future__ import annotations

from typing import Any

from core.dependency_injection import ServiceRegistry


class HealthChecker:
    # These services are needed for the primary request path. Optional integrations
    # are reported but do not prevent readiness by themselves.
    REQUIRED_SERVICES = (
        "memory_engine",
        "planner",
        "cognitive_core",
        "action_manager",
        "scheduler",
    )
    OPTIONAL_SERVICES = (
        "document_intelligence",
        "conversation_manager",
        "http_client",
        "skill_manager",
        "plugin_manager",
    )

    def __init__(self, registry: ServiceRegistry):
        self.registry = registry

    async def check_readiness(self) -> dict[str, Any]:
        required = {name: self.registry.has(name) for name in self.REQUIRED_SERVICES}
        optional = {name: self.registry.has(name) for name in self.OPTIONAL_SERVICES}
        missing = [name for name, present in required.items() if not present]
        ready = not missing
        return {
            "status": "healthy" if ready else "not_ready",
            "ready": ready,
            "required_services": required,
            "optional_services": optional,
            "missing_required_services": missing,
            "checks": {
                "registry_available": True,
                "required_services_registered": ready,
            },
            "limitations": [
                "Registration checks do not prove external databases or providers are reachable.",
                "Background jobs are currently held in process memory and are not restart-durable.",
            ],
        }
