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
        "durable_job_queue",
    )

    def __init__(self, registry: ServiceRegistry):
        self.registry = registry

    async def check_readiness(self) -> dict[str, Any]:
        required = {name: self.registry.has(name) for name in self.REQUIRED_SERVICES}
        optional = {name: self.registry.has(name) for name in self.OPTIONAL_SERVICES}
        missing = [name for name, present in required.items() if not present]
        checks: dict[str, Any] = {
            "registry_available": True,
            "required_services_registered": not missing,
        }
        limitations = []

        # A configured Mongo client must answer a ping; registration alone is not
        # enough to claim the primary persistence dependency is available.
        if self.registry.has("mongo_client"):
            try:
                client = self.registry.get("mongo_client")
                ping = client.admin.command("ping")
                if hasattr(ping, "__await__"):
                    await ping
                checks["mongodb_reachable"] = True
            except Exception:
                checks["mongodb_reachable"] = False
                limitations.append("MongoDB health probe failed; see service logs for details.")
        else:
            checks["mongodb_reachable"] = False
            limitations.append("MongoDB is not configured; persistent memory services may be unavailable.")

        if self.registry.has("scheduler"):
            try:
                scheduler = self.registry.get("scheduler")
                status_method = getattr(scheduler, "status", None)
                if callable(status_method):
                    scheduler_status = status_method()
                    checks["scheduler_running"] = not bool(scheduler_status.get("shutdown", True))
                else:
                    # Lightweight test doubles and compatible schedulers may not
                    # expose status(); registration remains the only available signal.
                    checks["scheduler_running"] = True
            except Exception:
                checks["scheduler_running"] = False
        else:
            checks["scheduler_running"] = False

        if self.registry.has("durable_job_queue"):
            try:
                queue_status = await self.registry.get("durable_job_queue").status()
                checks["durable_job_queue_available"] = bool(queue_status.get("available"))
            except Exception:
                checks["durable_job_queue_available"] = False
        else:
            checks["durable_job_queue_available"] = False

        ready = not missing and checks.get("scheduler_running", False)
        if self.registry.has("mongo_client") and not checks.get("mongodb_reachable", False):
            ready = False
        return {
            "status": "healthy" if ready else "not_ready",
            "ready": ready,
            "required_services": required,
            "optional_services": optional,
            "missing_required_services": missing,
            "checks": checks,
            "durable_jobs": {
                "available": bool(self.registry.has("durable_job_queue") and getattr(self.registry.get("durable_job_queue"), "available", False)),
                "note": "Only jobs submitted through the named durable queue are restart-recoverable; existing in-process scheduler callbacks are not persisted.",
            },
            "limitations": limitations + [
                "Service registration does not prove every external provider is reachable.",
                "Existing in-process scheduler callbacks and Telegram background tasks are not automatically restart-durable.",
            ],
        }
