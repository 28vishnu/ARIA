from __future__ import annotations

"""ARIA Phase 1 — Final Autonomous Engineer Orchestrator.

This is the final high-level engineering boundary. It does not replace the
existing development stack; it coordinates it as one autonomous lifecycle.

Lifecycle:
    understand -> inspect -> plan -> graph -> implement -> verify
    -> diagnose -> recover -> retest -> reassess -> accept

GitHub push, deployment, and other privileged actions remain outside this
class and therefore continue to require their existing explicit permission
workflows.
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger("aria")


@dataclass(frozen=True)
class AutonomousEngineeringResult:
    success: bool
    status: str
    requirement: str
    job: Any = None
    phases: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    elapsed_seconds: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        job_value = self.job
        if hasattr(job_value, "to_dict"):
            try:
                job_value = job_value.to_dict()
            except Exception:
                job_value = None
        return {
            "success": self.success,
            "status": self.status,
            "requirement": self.requirement,
            "job": job_value,
            "phases": list(self.phases),
            "errors": list(self.errors),
            "elapsed_seconds": self.elapsed_seconds,
            "metadata": dict(self.metadata),
        }


class AutonomousEngineerOrchestrator:
    """Single autonomous entry point for high-level engineering commands."""

    VERSION = "PHASE1-FINAL-AUTONOMOUS-ENGINEER-20261004"

    PHASES = (
        "understand",
        "inspect",
        "plan",
        "task_graph",
        "implement",
        "verify",
        "diagnose",
        "recover",
        "retest",
        "reassess",
        "accept",
    )

    def __init__(
        self,
        development_controller: Any,
        *,
        timeout_seconds: float = 7200.0,
    ) -> None:
        if development_controller is None:
            raise ValueError("development_controller is required.")
        if not callable(getattr(development_controller, "execute", None)):
            raise TypeError("development_controller must expose execute().")
        self.controller = development_controller
        self.timeout_seconds = max(30.0, min(7200.0, float(timeout_seconds)))
        self._active = False
        self._requests = 0
        self._successful = 0
        self._failed = 0

    @property
    def is_running(self) -> bool:
        return self._active

    def status(self) -> dict[str, Any]:
        controller_status = None
        try:
            method = getattr(self.controller, "status", None)
            if callable(method):
                controller_status = method()
        except Exception as exc:
            controller_status = {"error": str(exc)}
        return {
            "version": self.VERSION,
            "running": self._active,
            "timeout_seconds": self.timeout_seconds,
            "statistics": {
                "requests": self._requests,
                "successful": self._successful,
                "failed": self._failed,
            },
            "phases": list(self.PHASES),
            "controller": controller_status,
        }

    @staticmethod
    def _bounded_error(exc: BaseException) -> str:
        text = f"{type(exc).__name__}: {exc}".strip()
        return text[:2000]

    @staticmethod
    def _job_success(job: Any) -> bool:
        report = getattr(job, "report", None)
        if report is not None and hasattr(report, "success"):
            return bool(report.success)
        return str(getattr(job, "status", "")) == "completed"

    @staticmethod
    def _job_status(job: Any, success: bool) -> str:
        if success:
            return "completed"
        status = str(getattr(job, "status", "failed") or "failed")
        return status

    async def execute(
        self,
        requirement: str,
        *,
        changes: Optional[list[tuple[str, str]]] = None,
        test_paths: Optional[list[str]] = None,
        workspace_id: Optional[str] = None,
        context: Optional[dict[str, Any]] = None,
    ) -> AutonomousEngineeringResult:
        """Run one complete autonomous engineering request."""
        normalized = str(requirement or "").strip()
        if not normalized:
            return AutonomousEngineeringResult(
                success=False,
                status="invalid_request",
                requirement="",
                errors=("Development requirement is empty.",),
            )
        if self._active:
            return AutonomousEngineeringResult(
                success=False,
                status="busy",
                requirement=normalized,
                errors=("Another autonomous engineering job is already running.",),
            )

        self._active = True
        self._requests += 1
        started = time.monotonic()

        try:
            logger.info(
                "[AutonomousEngineer] Starting final autonomous lifecycle | requirement=%r",
                normalized[:500],
            )

            # The DevelopmentController remains the authoritative execution
            # boundary. It invokes all Step 41–49 reasoning, graph, recovery,
            # verification, and acceptance layers already integrated into the
            # DevelopmentAgent.
            job = await self.controller.execute(
                normalized,
                changes=changes,
                test_paths=test_paths,
                workspace_id=workspace_id,
            )

            success = self._job_success(job)
            status = self._job_status(job, success)
            if success:
                self._successful += 1
            else:
                self._failed += 1

            report = getattr(job, "report", None)
            report_metadata = getattr(report, "metadata", {}) if report is not None else {}
            metadata = {
                "orchestrator_version": self.VERSION,
                "context_supplied": isinstance(context, dict),
                "workspace_id": workspace_id,
                "controller_job_id": getattr(job, "job_id", None),
                "engineering_layers": {
                    "reasoning": True,
                    "repository_reasoning": True,
                    "adaptive_plan": True,
                    "task_graph": True,
                    "implementation": True,
                    "verification": True,
                    "root_cause": True,
                    "autonomous_recovery": True,
                    "engineering_judgment": True,
                },
                "report_metadata": dict(report_metadata) if isinstance(report_metadata, dict) else {},
            }

            return AutonomousEngineeringResult(
                success=success,
                status=status,
                requirement=normalized,
                job=job,
                phases=self.PHASES,
                elapsed_seconds=time.monotonic() - started,
                metadata=metadata,
            )

        except Exception as exc:
            self._failed += 1
            logger.exception("[AutonomousEngineer] Autonomous engineering request failed.")
            return AutonomousEngineeringResult(
                success=False,
                status="failed",
                requirement=normalized,
                phases=self.PHASES,
                errors=(self._bounded_error(exc),),
                elapsed_seconds=time.monotonic() - started,
                metadata={"orchestrator_version": self.VERSION},
            )
        finally:
            self._active = False

    async def develop(self, requirement: str, **kwargs: Any) -> AutonomousEngineeringResult:
        """Alias used by high-level integrations and Telegram engineering interfaces."""
        return await self.execute(requirement, **kwargs)
