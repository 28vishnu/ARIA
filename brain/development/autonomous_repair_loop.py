from __future__ import annotations

"""
ARIA Phase 1 — Autonomous Error → Repair → Retest Loop.

This module does not replace DevelopmentAgent's repair engine.

DevelopmentAgent remains the authoritative implementation for:

    failure analysis
        ↓
    repair generation/application
        ↓
    targeted retest
        ↓
    bounded repair attempts
        ↓
    final validation

This module provides the orchestration layer needed by the
autonomous brain so that future phases can request:

    "build this"
    "repair this"
    "fix the failing tests"
    "continue until validated"

without directly manipulating the lower-level development
components.

Safety properties:
    - bounded attempts
    - no direct shell execution
    - no direct filesystem writes
    - no GitHub push
    - no deployment
    - DevelopmentController remains the execution boundary
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .development_controller import (
    DevelopmentController,
    DevelopmentJob,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class RepairCycle:
    """
    One high-level autonomous repair cycle.
    """

    cycle: int
    status: str
    job_id: str | None = None
    development_status: str | None = None
    success: bool = False
    failure_detected: bool = False
    repair_attempted: bool = False
    repair_succeeded: bool = False
    retest_passed: bool = False
    errors: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "cycle": self.cycle,
            "status": self.status,
            "job_id": self.job_id,
            "development_status": self.development_status,
            "success": self.success,
            "failure_detected": self.failure_detected,
            "repair_attempted": self.repair_attempted,
            "repair_succeeded": self.repair_succeeded,
            "retest_passed": self.retest_passed,
            "errors": list(self.errors),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class AutonomousRepairResult:
    """
    Final result returned to the autonomous orchestration layer.
    """

    success: bool
    status: str
    requirement: str

    cycles: tuple[RepairCycle, ...] = ()

    final_job_id: str | None = None
    final_development_status: str | None = None

    failure_detected: bool = False
    repair_attempted: bool = False
    repair_succeeded: bool = False
    retest_passed: bool = False

    started_at: str = ""
    completed_at: str = ""

    errors: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "status": self.status,
            "requirement": self.requirement,
            "cycles": [
                cycle.to_dict()
                for cycle in self.cycles
            ],
            "final_job_id": self.final_job_id,
            "final_development_status": (
                self.final_development_status
            ),
            "failure_detected": self.failure_detected,
            "repair_attempted": self.repair_attempted,
            "repair_succeeded": self.repair_succeeded,
            "retest_passed": self.retest_passed,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "errors": list(self.errors),
            "metadata": dict(self.metadata),
        }


class AutonomousRepairLoop:
    """
    Orchestration wrapper around DevelopmentController.

    Important architectural rule:

        AutonomousRepairLoop
                ↓
        DevelopmentController
                ↓
        DevelopmentAgent
                ↓
        FailureAnalyzer
                ↓
        RepairEngine
                ↓
        targeted retest
                ↓
        final validation

    The lower-level DevelopmentAgent already performs bounded
    repair/retest internally. Therefore this class does not
    independently edit files or run commands.

    The optional outer retry exists for cases where the complete
    development job itself fails before reaching the internal
    repair stage.
    """

    NON_RETRYABLE_STATUSES = frozenset(
        {
            "blocked",
            "invalid_requirement",
            "workspace_creation_failed",
            "workspace_verification_failed",
            "generation_failed",
            "generation_invalid",
            "repair_execution_failed",
            "cancelled",
        }
    )

    SUCCESS_STATUSES = frozenset(
        {
            "completed",
            "success",
            "repair_succeeded",
        }
    )

    def __init__(
        self,
        controller: DevelopmentController,
        *,
        max_cycles: int = 2,
    ) -> None:

        if controller is None:
            raise ValueError(
                "controller is required."
            )

        if max_cycles < 1:
            raise ValueError(
                "max_cycles must be at least 1."
            )

        self.controller = controller
        self.max_cycles = min(
            int(max_cycles),
            3,
        )

        self._cancelled = False
        self._running = False

        self._last_result: (
            AutonomousRepairResult | None
        ) = None

    # ==============================================================
    # State
    # ==============================================================

    @property
    def running(self) -> bool:
        return self._running

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def cancel(self) -> None:
        """
        Request cancellation before the next cycle.

        The underlying DevelopmentController remains responsible
        for any already-running development job.
        """

        self._cancelled = True

    def reset(self) -> None:
        """
        Clear transient cancellation state.
        """

        if self._running:
            raise RuntimeError(
                "Cannot reset while repair loop is running."
            )

        self._cancelled = False

    # ==============================================================
    # Helpers
    # ==============================================================

    @staticmethod
    def _report_from_job(
        job: DevelopmentJob,
    ) -> tuple[
        bool,
        bool,
        bool,
        bool,
        str | None,
        list[str],
    ]:
        """
        Extract normalized repair state from a DevelopmentJob.
        """

        report = job.report

        if report is None:
            return (
                False,
                False,
                False,
                False,
                None,
                [],
            )

        failure_detected = (
            report.failure is not None
        )

        repair_attempted = (
            report.repair is not None
        )

        repair_succeeded = bool(
            getattr(
                report.repair,
                "success",
                False,
            )
        )

        retest_passed = bool(
            repair_succeeded
            and report.success
        )

        errors = [
            str(error)
            for error in (
                getattr(
                    report,
                    "errors",
                    (),
                )
                or ()
            )
        ]

        return (
            bool(report.success),
            failure_detected,
            repair_attempted,
            repair_succeeded,
            str(
                getattr(
                    report,
                    "status",
                    None,
                )
            )
            if getattr(
                report,
                "status",
                None,
            )
            else None,
            errors,
        )

    @staticmethod
    def _job_status(
        job: DevelopmentJob,
    ) -> str:
        return str(
            getattr(
                job,
                "status",
                "unknown",
            )
        ).strip().lower()

    def _should_retry(
        self,
        job: DevelopmentJob,
    ) -> bool:

        if self._cancelled:
            return False

        report = job.report

        if report is None:
            return self._job_status(job) not in (
                "blocked",
                "cancelled",
            )

        if report.success:
            return False

        status = str(
            getattr(
                report,
                "status",
                "",
            )
        ).strip().lower()

        if status in self.NON_RETRYABLE_STATUSES:
            return False

        repair = getattr(
            report,
            "repair",
            None,
        )

        # If the lower-level repair engine explicitly exhausted
        # its bounded attempts, another identical repair cycle is
        # unlikely to help.
        if repair is not None:

            stopped_reason = str(
                getattr(
                    repair,
                    "stopped_reason",
                    "",
                )
            ).lower()

            if (
                "max" in stopped_reason
                or "attempt" in stopped_reason
                and "limit" in stopped_reason
            ):
                return False

        return True

    # ==============================================================
    # Main execution
    # ==============================================================

    async def run(
        self,
        requirement: str,
        *,
        changes: list[
            tuple[str, str]
        ] | None = None,
        test_paths: list[str] | None = None,
        workspace_id: str | None = None,
        max_cycles: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AutonomousRepairResult:
        """
        Execute a bounded autonomous repair lifecycle.

        The lifecycle is:

            DevelopmentController
                    ↓
            DevelopmentAgent
                    ↓
            build/validation/tests
                    ↓
            failure analysis
                    ↓
            bounded repair
                    ↓
            targeted retest
                    ↓
            final validation

        If the entire development job fails outside the internal
        repair mechanism, one or more bounded outer cycles may be
        attempted.
        """

        if not isinstance(
            requirement,
            str,
        ):
            raise TypeError(
                "requirement must be a string."
            )

        normalized_requirement = (
            requirement.strip()
        )

        if not normalized_requirement:
            raise ValueError(
                "requirement cannot be empty."
            )

        if self._running:
            raise RuntimeError(
                "Autonomous repair loop is already running."
            )

        cycle_limit = (
            self.max_cycles
            if max_cycles is None
            else min(
                max(
                    1,
                    int(max_cycles),
                ),
                self.max_cycles,
            )
        )

        started_at = _utc_now()

        self._running = True
        self._cancelled = False

        cycles: list[RepairCycle] = []
        errors: list[str] = []

        final_job_id: str | None = None
        final_development_status: str | None = None

        final_success = False
        final_failure_detected = False
        final_repair_attempted = False
        final_repair_succeeded = False
        final_retest_passed = False

        try:

            for cycle_number in range(
                1,
                cycle_limit + 1,
            ):

                if self._cancelled:

                    cycles.append(
                        RepairCycle(
                            cycle=cycle_number,
                            status="cancelled",
                            success=False,
                            errors=(
                                "Repair loop cancelled.",
                            ),
                        )
                    )

                    errors.append(
                        "Repair loop cancelled."
                    )

                    break

                try:

                    job = await self.controller.execute(
                        normalized_requirement,
                        changes=changes,
                        test_paths=test_paths,
                        workspace_id=workspace_id,
                    )

                except Exception as exc:

                    message = str(exc)

                    errors.append(
                        message
                    )

                    cycles.append(
                        RepairCycle(
                            cycle=cycle_number,
                            status="controller_error",
                            success=False,
                            errors=(message,),
                        )
                    )

                    # Controller-level exceptions are only retried
                    # while the bounded cycle budget remains.
                    if (
                        cycle_number
                        >= cycle_limit
                    ):
                        break

                    continue

                final_job_id = str(
                    getattr(
                        job,
                        "job_id",
                        "",
                    )
                ) or None

                (
                    success,
                    failure_detected,
                    repair_attempted,
                    repair_succeeded,
                    development_status,
                    cycle_errors,
                ) = self._report_from_job(job)

                final_development_status = (
                    development_status
                )

                final_success = success
                final_failure_detected = (
                    failure_detected
                )
                final_repair_attempted = (
                    repair_attempted
                )
                final_repair_succeeded = (
                    repair_succeeded
                )
                final_retest_passed = (
                    retest_passed
                )

                if cycle_errors:
                    errors.extend(
                        cycle_errors
                    )

                cycle_status = (
                    "success"
                    if success
                    else (
                        "repair_succeeded"
                        if repair_succeeded
                        else (
                            "repair_attempted"
                            if repair_attempted
                            else (
                                "failure_detected"
                                if failure_detected
                                else "failed"
                            )
                        )
                    )
                )

                cycles.append(
                    RepairCycle(
                        cycle=cycle_number,
                        status=cycle_status,
                        job_id=final_job_id,
                        development_status=(
                            development_status
                        ),
                        success=success,
                        failure_detected=(
                            failure_detected
                        ),
                        repair_attempted=(
                            repair_attempted
                        ),
                        repair_succeeded=(
                            repair_succeeded
                        ),
                        retest_passed=(
                            retest_passed
                        ),
                        errors=tuple(
                            cycle_errors
                        ),
                        metadata={
                            "controller_job_status":
                                self._job_status(job),
                        },
                    )
                )

                if success:
                    break

                if not self._should_retry(job):
                    break

            if self._cancelled:
                status = "cancelled"

            elif final_success:
                status = "repair_cycle_succeeded"

            elif final_repair_succeeded:
                status = (
                    "repair_completed_but_validation_failed"
                )

            elif final_failure_detected:
                status = "repair_exhausted"

            else:
                status = "development_failed"

            completed_at = _utc_now()

            result = AutonomousRepairResult(
                success=final_success,
                status=status,
                requirement=normalized_requirement,
                cycles=tuple(cycles),
                final_job_id=final_job_id,
                final_development_status=(
                    final_development_status
                ),
                failure_detected=(
                    final_failure_detected
                ),
                repair_attempted=(
                    final_repair_attempted
                ),
                repair_succeeded=(
                    final_repair_succeeded
                ),
                retest_passed=(
                    final_retest_passed
                ),
                started_at=started_at,
                completed_at=completed_at,
                errors=tuple(errors),
                metadata=dict(
                    metadata or {}
                ),
            )

            self._last_result = result

            return result

        finally:
            self._running = False

    # ==============================================================
    # Inspection
    # ==============================================================

    def status(self) -> dict[str, Any]:
        result = self._last_result

        return {
            "running": self._running,
            "cancelled": self._cancelled,
            "max_cycles": self.max_cycles,
            "last_result": (
                result.to_dict()
                if result is not None
                else None
            ),
        }

    def health(self) -> dict[str, Any]:
        return {
            "healthy": self.controller is not None,
            "running": self._running,
            "max_cycles": self.max_cycles,
            "last_success": (
                self._last_result.success
                if self._last_result is not None
                else None
            ),
        }

    def describe(self) -> dict[str, Any]:
        return {
            "name": "autonomous_repair_loop",
            "purpose": (
                "Coordinate bounded error analysis, repair, "
                "retest, and final validation."
            ),
            "owner": (
                "brain.development."
                "development_agent"
            ),
            "execution_boundary": (
                "brain.development."
                "development_controller"
            ),
            "max_cycles": self.max_cycles,
            "github_push": False,
            "deployment": False,
            "direct_shell_execution": False,
            "direct_filesystem_writes": False,
        }