from __future__ import annotations

"""Read-only Phase 1 autonomous-engineering readiness gateway.

This module is intentionally outside the executable engineering lifecycle.
It may inspect repository structure, static contracts, runtime health, and
stage wiring. It must never start engineering or perform mutations.

Forbidden operations from this gateway:
- develop / execute / run / resume
- filesystem writes or deletes
- git commits / pushes
- deployment / rollback
"""

import ast
import inspect
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("aria.phase1_readiness_gateway")


class Phase1ReadinessGateway:
    """Safe, deterministic, read-only readiness inspection."""

    VERSION = "ARIA-PHASE1-READINESS-GATEWAY-20261005.2"

    REQUIRED_ORCHESTRATOR_STAGES = (
        "requirement_engine",
        "knowledge_engine",
        "implementation_engine",
        "verification_engine",
        "diagnosis_engine",
        "recovery_engine",
        "acceptance_engine",
    )

    REQUIRED_ORCHESTRATOR_METHODS = (
        "develop",
        "resume",
        "status",
        "health",
    )

    REQUIRED_FINAL_ENGINEER_METHODS = (
        "develop",
        "resume",
        "status",
        "health",
    )

    REQUIRED_ADAPTER_METHODS = (
        "develop",
        "resume",
        "status",
        "engineering_status",
        "health",
    )

    MUTATING_NAMES = (
        "write",
        "unlink",
        "remove",
        "rename",
        "replace",
        "mkdir",
        "rmdir",
        "commit",
        "push",
        "deploy",
        "rollback",
        "execute",
        "develop",
        "run",
        "resume",
    )

    def __init__(
        self,
        runtime: Any = None,
        repository_root: str | Path | None = None,
    ) -> None:
        self.runtime = runtime
        self.repository_root = self._resolve_repository_root(repository_root)

    def inspect(self, *, session_id: str | None = None) -> dict[str, Any]:
        """Inspect Phase 1 without entering its executable lifecycle."""
        static = self._static_validation()
        runtime = self._runtime_validation(session_id=session_id)
        safety = self._safety_contract()

        checks = {
            "repository": bool(static.get("success")),
            "authoritative_runtime": bool(runtime.get("success")),
            "safety_boundaries": bool(safety.get("success")),
        }
        ready = all(checks.values())

        return {
            "success": ready,
            "ready": ready,
            "status": "ready" if ready else "not_ready",
            "message": (
                "Phase 1 autonomous engineering lifecycle is ready for execution."
                if ready
                else "Phase 1 autonomous engineering lifecycle is not ready for execution."
            ),
            "gateway": self.VERSION,
            "read_only": True,
            "execution_started": False,
            "execution_invoked": False,
            "mutations_performed": False,
            "checks": checks,
            "repository": static,
            "runtime": runtime,
            "safety": safety,
        }

    def _static_validation(self) -> dict[str, Any]:
        root = self.repository_root
        if not root.exists() or not root.is_dir():
            return {
                "success": False,
                "status": "repository_missing",
                "repository_root": str(root),
                "error": "Repository root does not exist or is not a directory.",
            }

        try:
            from brain.integration.phase1_jarvis_validator import Phase1JarvisValidator

            report = Phase1JarvisValidator(root).validate()
            payload = report.to_dict()

            findings = payload.get("findings", [])
            failures = [
                item for item in findings
                if isinstance(item, dict) and item.get("passed") is False
            ]

            return {
                "success": bool(payload.get("success")) and not failures,
                "status": payload.get("status", "unknown"),
                "repository_root": str(root),
                "total_checks": payload.get("total_checks", 0),
                "passed_checks": payload.get("passed_checks", 0),
                "failed_checks": payload.get("failed_checks", 0),
                "warning_checks": payload.get("warning_checks", 0),
                "missing_capabilities": payload.get("missing_capabilities", []),
                "architecture_chain": payload.get("architecture_chain", []),
                "findings": findings,
            }
        except Exception as exc:
            logger.exception("[Phase1][Readiness] Static validation failed")
            return {
                "success": False,
                "status": "static_validation_error",
                "repository_root": str(root),
                "error": str(exc),
            }

    def _runtime_validation(self, *, session_id: str | None) -> dict[str, Any]:
        runtime = self.runtime
        if runtime is None:
            return {
                "success": False,
                "status": "runtime_missing",
                "error": "Canonical Phase 1 runtime is not connected.",
            }

        adapter_methods = self._method_presence(runtime, self.REQUIRED_ADAPTER_METHODS)
        adapter_status = self._read_status(runtime, session_id)

        final_engineer = getattr(runtime, "final_engineer", None)
        final_methods = self._method_presence(
            final_engineer,
            self.REQUIRED_FINAL_ENGINEER_METHODS,
        )
        final_health = self._read_health(final_engineer)

        orchestrator = getattr(final_engineer, "orchestrator", None)
        orchestrator_methods = self._method_presence(
            orchestrator,
            self.REQUIRED_ORCHESTRATOR_METHODS,
        )
        orchestrator_health = self._read_health(orchestrator)

        stage_requirements = {
            name: bool(orchestrator_health.get(name, False))
            for name in self.REQUIRED_ORCHESTRATOR_STAGES
        }

        stage_object_presence = {
            name: getattr(orchestrator, name, None) is not None
            for name in self.REQUIRED_ORCHESTRATOR_STAGES
        } if orchestrator is not None else {
            name: False for name in self.REQUIRED_ORCHESTRATOR_STAGES
        }

        health_ok = bool(final_health.get("healthy")) and bool(
            orchestrator_health.get("healthy")
        )
        adapter_ok = all(adapter_methods.values()) and bool(adapter_status)
        final_ok = final_engineer is not None and all(final_methods.values())
        orchestrator_ok = orchestrator is not None and all(
            orchestrator_methods.values()
        )
        stages_ok = all(stage_requirements.values()) and all(
            stage_object_presence.values()
        )

        success = adapter_ok and final_ok and orchestrator_ok and stages_ok and health_ok

        return {
            "success": success,
            "status": "connected" if success else "runtime_not_ready",
            "adapter_status": adapter_status,
            "adapter_methods": adapter_methods,
            "final_engineer_health": final_health,
            "final_engineer_methods": final_methods,
            "orchestrator_health": orchestrator_health,
            "orchestrator_methods": orchestrator_methods,
            "stage_requirements": stage_requirements,
            "stage_object_presence": stage_object_presence,
            "authoritative_orchestrator_connected": orchestrator is not None,
            "final_engineer_connected": final_engineer is not None,
            "execution_method_invoked": False,
        }

    def _safety_contract(self) -> dict[str, Any]:
        runtime = self.runtime
        final_engineer = getattr(runtime, "final_engineer", None) if runtime is not None else None
        health = self._read_health(final_engineer)

        gateway_methods = {
            name: callable(getattr(self, name, None))
            for name in ("inspect", "_static_validation", "_runtime_validation")
        }
        source_contract = self._source_safety_check()

        github_authorized = health.get("github_push_requires_authorization") is True
        deployment_authorized = health.get("deployment_requires_authorization") is True
        production_direct_write = health.get("production_direct_write") is False

        return {
            "success": (
                github_authorized
                and deployment_authorized
                and production_direct_write
                and all(gateway_methods.values())
                and source_contract["success"]
            ),
            "github_push_requires_authorization": github_authorized,
            "deployment_requires_authorization": deployment_authorized,
            "production_direct_write_disabled": production_direct_write,
            "implementation_not_started": True,
            "mutations_performed": False,
            "gateway_method_contract": gateway_methods,
            "source_contract": source_contract,
        }

    def _source_safety_check(self) -> dict[str, Any]:
        """Statically verify this gateway contains no executable mutating call sites."""
        try:
            source = Path(__file__).read_text(encoding="utf-8")
            tree = ast.parse(source)
            forbidden_calls: list[str] = []

            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                name = None
                if isinstance(func, ast.Name):
                    name = func.id
                elif isinstance(func, ast.Attribute):
                    name = func.attr
                if name in self.MUTATING_NAMES:
                    forbidden_calls.append(name)

            # ``inspect`` and validator calls are safe; only forbidden call
            # names matter here. The class methods themselves may be named
            # with words such as ``_runtime_validation`` without triggering.
            return {
                "success": not forbidden_calls,
                "forbidden_calls": sorted(set(forbidden_calls)),
            }
        except Exception as exc:
            return {
                "success": False,
                "forbidden_calls": [],
                "error": str(exc),
            }

    @staticmethod
    def _method_presence(target: Any, names: tuple[str, ...]) -> dict[str, bool]:
        return {
            name: callable(getattr(target, name, None)) if target is not None else False
            for name in names
        }

    @staticmethod
    def _read_status(target: Any, session_id: str | None) -> dict[str, Any]:
        if target is None:
            return {}

        for name in ("engineering_status", "status"):
            method = getattr(target, name, None)
            if not callable(method):
                continue
            try:
                value = method(session_id=session_id)
            except TypeError:
                try:
                    value = method(session_id) if session_id else method()
                except TypeError:
                    value = method()
            except Exception as exc:
                return {"healthy": False, "status": "inspection_error", "error": str(exc)}

            if inspect.isawaitable(value):
                return {
                    "healthy": False,
                    "status": "async_status_unsupported",
                    "error": f"Read-only status method {name} returned an awaitable.",
                }
            if isinstance(value, dict):
                return dict(value)
            return {"value": str(value)}

        return {}

    @staticmethod
    def _read_health(target: Any) -> dict[str, Any]:
        if target is None:
            return {}
        method = getattr(target, "health", None)
        if not callable(method):
            return {}
        try:
            value = method()
            if inspect.isawaitable(value):
                return {
                    "healthy": False,
                    "status": "async_health_unsupported",
                    "error": "Read-only health method returned an awaitable.",
                }
            if isinstance(value, dict):
                return dict(value)
            return {"value": str(value)}
        except Exception as exc:
            return {"healthy": False, "status": "inspection_error", "error": str(exc)}

    @staticmethod
    def _resolve_repository_root(explicit: str | Path | None) -> Path:
        if explicit:
            return Path(explicit).resolve()

        candidates = (
            Path.cwd().resolve(),
            Path("/app").resolve(),
            Path("/workspace").resolve(),
        )
        for candidate in candidates:
            if (candidate / "brain").is_dir() and (candidate / "core").is_dir():
                return candidate

        return Path.cwd().resolve()


__all__ = ["Phase1ReadinessGateway"]
