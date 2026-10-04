"""
ARIA Phase 1 — Master Autonomous Coding Loop

Step 22 / 28

Purpose
-------
Provide one bounded autonomous software-development loop above the
existing ARIA DevelopmentController.

Architecture:

    Requirement
        ↓
    AutonomousCodingLoop
        ↓
    AutonomousDevelopmentBridge
        ↓
    DevelopmentController
        ↓
    DevelopmentAgent
        ↓
    Requirement Intelligence
        ↓
    Change Planning
        ↓
    Repository Context
        ↓
    Isolated Workspace
        ↓
    Code Generation
        ↓
    Guarded File Writes
        ↓
    Static Validation
        ↓
    Tests
        ↓
    Failure Analysis
        ↓
    Repair
        ↓
    Retest
        ↓
    Final Verification

The DevelopmentAgent already owns the inner repair cycle.

This class provides the outer autonomous control layer so future
ARIA phases can be treated as development jobs instead of requiring
manual orchestration.

Safety
------
- bounded attempts
- no infinite loops
- no direct filesystem writes
- no direct shell execution
- no direct GitHub push
- no direct deployment
- uses the existing DevelopmentController boundary
- preserves failed attempt information
"""

from __future__ import annotations

import asyncio
import logging
import time

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .autonomous_development_bridge import (
    AutonomousDevelopmentBridge,
    AutonomousDevelopmentResult,
)


logger = logging.getLogger(
    "aria.autonomous_coding_loop"
)


# ============================================================================
# RESULT
# ============================================================================


@dataclass
class CodingAttempt:
    """
    One autonomous development attempt.
    """

    attempt: int

    success: bool

    status: str

    elapsed_seconds: float = 0.0

    job_id: Optional[str] = None

    errors: List[str] = field(
        default_factory=list
    )

    result: Any = None

    def to_dict(
        self,
    ) -> Dict[str, Any]:

        return {
            "attempt": self.attempt,
            "success": self.success,
            "status": self.status,
            "elapsed_seconds": (
                self.elapsed_seconds
            ),
            "job_id": self.job_id,
            "errors": list(
                self.errors
            ),
        }


@dataclass
class AutonomousCodingResult:
    """
    Final result of the autonomous coding loop.
    """

    success: bool

    status: str

    requirement: str

    attempts: int

    max_attempts: int

    final_result: Optional[
        AutonomousDevelopmentResult
    ] = None

    attempt_history: List[
        CodingAttempt
    ] = field(
        default_factory=list
    )

    errors: List[str] = field(
        default_factory=list
    )

    elapsed_seconds: float = 0.0

    metadata: Dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(
        self,
    ) -> Dict[str, Any]:

        return {
            "success": self.success,
            "status": self.status,
            "requirement": self.requirement,
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
            "final_result": (
                self.final_result.to_dict()
                if self.final_result is not None
                else None
            ),
            "attempt_history": [
                attempt.to_dict()
                for attempt in self.attempt_history
            ],
            "errors": list(
                self.errors
            ),
            "elapsed_seconds": (
                self.elapsed_seconds
            ),
            "metadata": dict(
                self.metadata
            ),
        }


# ============================================================================
# MASTER LOOP
# ============================================================================


class AutonomousCodingLoop:
    """
    Master autonomous software-development loop.

    This class does not replace DevelopmentAgent.

    DevelopmentAgent remains responsible for the actual coding workflow.

    This class is responsible for:

        - accepting a future-phase development requirement
        - starting development through the bridge
        - evaluating the result
        - determining whether another bounded attempt is useful
        - preserving attempt history
        - stopping on unsafe/permanent failures
        - returning one stable result to the higher orchestration layer
    """

    VERSION = (
        "PHASE1-AUTONOMOUS-CODING-LOOP-20261004"
    )

    DEFAULT_MAX_ATTEMPTS = 3

    MIN_ATTEMPTS = 1

    MAX_ATTEMPTS = 5

    # ------------------------------------------------------------------
    # These statuses normally indicate that retrying the exact same
    # request will not solve the underlying problem.
    # ------------------------------------------------------------------

    NON_RETRYABLE_STATUSES = {
        "invalid_request",
        "requirement_unclear",
        "blocked",
        "impact_blocked",
        "provided_changes_rejected",
        "generated_changes_rejected",
        "acceptance_check_failed",
        "repository_empty",
        "workspace_repository_empty",
        "workspace_verification_failed",
        "cancelled",
    }

    # ------------------------------------------------------------------
    # These indicate a transient/repairable development failure.
    # ------------------------------------------------------------------

    RETRYABLE_STATUS_HINTS = (
        "generation_failed",
        "validation_failed",
        "test_execution_failed",
        "tests_failed",
        "repair_execution_failed",
        "repair_completed_but_final_validation_failed",
        "write_failed",
        "context_build_failed",
        "workspace_creation_failed",
        "repository_inspection_failed",
        "workspace_repository_inspection_failed",
        "planning_failed",
        "impact_analysis_failed",
        "no_changes_generated",
        "timeout",
        "failed",
    )

    def __init__(
        self,
        development_bridge: AutonomousDevelopmentBridge,
        *,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        retry_delay_seconds: float = 0.5,
    ) -> None:

        if development_bridge is None:
            raise ValueError(
                "development_bridge is required."
            )

        if not isinstance(
            development_bridge,
            AutonomousDevelopmentBridge,
        ):
            raise TypeError(
                "development_bridge must be an "
                "AutonomousDevelopmentBridge."
            )

        self.bridge = (
            development_bridge
        )

        self.max_attempts = max(
            self.MIN_ATTEMPTS,
            min(
                self.MAX_ATTEMPTS,
                int(max_attempts),
            ),
        )

        self.retry_delay_seconds = max(
            0.0,
            min(
                10.0,
                float(
                    retry_delay_seconds
                ),
            ),
        )

        self._active = False

        self._cancel_requested = False

        self._current_requirement: Optional[
            str
        ] = None

        self._last_result: Optional[
            AutonomousCodingResult
        ] = None

        self.statistics = {
            "requests": 0,
            "completed": 0,
            "failed": 0,
            "cancelled": 0,
            "retries": 0,
        }

    # ========================================================================
    # STATUS
    # ========================================================================

    @property
    def active(
        self,
    ) -> bool:
        return self._active

    def is_running(
        self,
    ) -> bool:
        return self._active

    def status(
        self,
    ) -> Dict[str, Any]:

        return {
            "component": (
                "AutonomousCodingLoop"
            ),
            "version": self.VERSION,
            "active": self._active,
            "current_requirement": (
                self._current_requirement
            ),
            "max_attempts": (
                self.max_attempts
            ),
            "retry_delay_seconds": (
                self.retry_delay_seconds
            ),
            "statistics": dict(
                self.statistics
            ),
        }

    # ========================================================================
    # CANCELLATION
    # ========================================================================

    def cancel(
        self,
    ) -> Dict[str, Any]:
        """
        Request cancellation.

        The active DevelopmentAgent remains responsible for its own
        workspace safety. This flag prevents the outer loop from
        starting another attempt.
        """

        self._cancel_requested = True

        self.statistics[
            "cancelled"
        ] += 1

        return {
            "cancel_requested": True,
            "active": self._active,
        }

    # ========================================================================
    # MAIN LOOP
    # ========================================================================

    async def run(
        self,
        requirement: str,
        *,
        changes: Optional[
            list[tuple[str, str]]
        ] = None,
        test_paths: Optional[
            list[str]
        ] = None,
        workspace_id: Optional[
            str
        ] = None,
        context: Optional[
            Dict[str, Any]
        ] = None,
        max_attempts: Optional[
            int
        ] = None,
    ) -> AutonomousCodingResult:
        """
        Execute a complete bounded autonomous coding cycle.

        Example:

            result = await loop.run(
                "Build Phase 2 of ARIA."
            )

        The method never creates an unlimited retry loop.
        """

        started = time.monotonic()

        normalized_requirement = (
            str(
                requirement or ""
            ).strip()
        )

        if not normalized_requirement:

            return AutonomousCodingResult(
                success=False,
                status="invalid_request",
                requirement="",
                attempts=0,
                max_attempts=self.max_attempts,
                errors=[
                    "Development requirement is empty."
                ],
            )

        if self._active:

            return AutonomousCodingResult(
                success=False,
                status="already_running",
                requirement=(
                    normalized_requirement
                ),
                attempts=0,
                max_attempts=self.max_attempts,
                errors=[
                    (
                        "Another autonomous coding "
                        "request is already running."
                    )
                ],
            )

        requested_attempts = (
            self.max_attempts
            if max_attempts is None
            else max_attempts
        )

        attempt_limit = max(
            self.MIN_ATTEMPTS,
            min(
                self.MAX_ATTEMPTS,
                int(
                    requested_attempts
                ),
            ),
        )

        self.statistics[
            "requests"
        ] += 1

        self._active = True

        self._cancel_requested = False

        self._current_requirement = (
            normalized_requirement
        )

        history: List[
            CodingAttempt
        ] = []

        final_result: Optional[
            AutonomousDevelopmentResult
        ] = None

        final_status = "failed"

        try:

            for attempt_number in range(
                1,
                attempt_limit + 1,
            ):

                # --------------------------------------------------------
                # Cancellation before a new attempt.
                # --------------------------------------------------------

                if self._cancel_requested:

                    final_status = (
                        "cancelled"
                    )

                    self.statistics[
                        "cancelled"
                    ] += 1

                    break

                logger.info(
                    "[AutonomousCodingLoop] "
                    "Starting attempt %s/%s | requirement=%s",
                    attempt_number,
                    attempt_limit,
                    normalized_requirement[
                        :300
                    ],
                )

                attempt_started = (
                    time.monotonic()
                )

                try:

                    final_result = (
                        await self.bridge.develop(
                            normalized_requirement,
                            changes=changes,
                            test_paths=test_paths,
                            workspace_id=workspace_id,
                            context=context,
                        )
                    )

                    attempt_elapsed = (
                        time.monotonic()
                        - attempt_started
                    )

                    attempt = CodingAttempt(
                        attempt=attempt_number,
                        success=bool(
                            final_result.success
                        ),
                        status=str(
                            final_result.status
                        ),
                        elapsed_seconds=(
                            attempt_elapsed
                        ),
                        job_id=(
                            final_result.job_id
                        ),
                        errors=list(
                            final_result.errors
                        ),
                        result=final_result,
                    )

                    history.append(
                        attempt
                    )

                except asyncio.CancelledError:

                    final_status = (
                        "cancelled"
                    )

                    self._cancel_requested = (
                        True
                    )

                    break

                except Exception as exc:

                    attempt_elapsed = (
                        time.monotonic()
                        - attempt_started
                    )

                    error_text = (
                        self._bounded_error(
                            exc
                        )
                    )

                    attempt = CodingAttempt(
                        attempt=attempt_number,
                        success=False,
                        status="failed",
                        elapsed_seconds=(
                            attempt_elapsed
                        ),
                        errors=[
                            error_text
                        ],
                    )

                    history.append(
                        attempt
                    )

                    final_result = None

                    logger.exception(
                        "[AutonomousCodingLoop] "
                        "Development attempt failed."
                    )

                # --------------------------------------------------------
                # Successful development.
                # --------------------------------------------------------

                if (
                    final_result is not None
                    and final_result.success
                ):

                    final_status = (
                        "completed"
                    )

                    self.statistics[
                        "completed"
                    ] += 1

                    break

                # --------------------------------------------------------
                # Determine the observed status.
                # --------------------------------------------------------

                observed_status = (
                    final_result.status
                    if final_result is not None
                    else "failed"
                )

                # --------------------------------------------------------
                # Permanent/non-retryable failure.
                # --------------------------------------------------------

                if not self.should_retry(
                    observed_status
                ):

                    final_status = (
                        observed_status
                        or "failed"
                    )

                    break

                # --------------------------------------------------------
                # Retry limit reached.
                # --------------------------------------------------------

                if (
                    attempt_number
                    >= attempt_limit
                ):

                    final_status = (
                        observed_status
                        or "retry_limit_reached"
                    )

                    break

                # --------------------------------------------------------
                # Outer retry.
                #
                # DevelopmentAgent already performs its own bounded
                # repair loop. This is a second, higher-level retry only
                # when the complete development job itself failed.
                # --------------------------------------------------------

                self.statistics[
                    "retries"
                ] += 1

                logger.warning(
                    "[AutonomousCodingLoop] "
                    "Attempt %s failed with status=%s. "
                    "Starting bounded outer retry.",
                    attempt_number,
                    observed_status,
                )

                if (
                    self.retry_delay_seconds
                    > 0
                ):

                    await asyncio.sleep(
                        self.retry_delay_seconds
                    )

            # ----------------------------------------------------------------
            # Final state.
            # ----------------------------------------------------------------

            if (
                final_status
                == "completed"
            ):

                success = True

            else:

                success = False

                self.statistics[
                    "failed"
                ] += 1

            elapsed = (
                time.monotonic()
                - started
            )

            result = AutonomousCodingResult(
                success=success,
                status=final_status,
                requirement=(
                    normalized_requirement
                ),
                attempts=len(
                    history
                ),
                max_attempts=attempt_limit,
                final_result=final_result,
                attempt_history=history,
                errors=self._collect_errors(
                    history
                ),
                elapsed_seconds=elapsed,
                metadata={
                    "loop_version": (
                        self.VERSION
                    ),
                    "development_agent_owns_inner_repair": (
                        True
                    ),
                    "outer_retry_count": max(
                        0,
                        len(history) - 1,
                    ),
                    "github_push_performed": (
                        False
                    ),
                    "deployment_performed": (
                        False
                    ),
                },
            )

            self._last_result = result

            return result

        finally:

            self._active = False

            self._current_requirement = (
                None
            )

            self._cancel_requested = (
                False
            )

    # ========================================================================
    # RETRY DECISION
    # ========================================================================

    def should_retry(
        self,
        status: str,
    ) -> bool:
        """
        Determine whether another complete development attempt may
        reasonably help.

        This is deliberately conservative.
        """

        normalized = str(
            status or ""
        ).strip().lower()

        if not normalized:
            return True

        if normalized in (
            self.NON_RETRYABLE_STATUSES
        ):
            return False

        for hint in (
            self.RETRYABLE_STATUS_HINTS
        ):

            if (
                normalized == hint
                or normalized.endswith(
                    hint
                )
                or hint in normalized
            ):
                return True

        # Unknown failures are allowed one bounded retry.
        # The max-attempt limit still prevents infinite execution.
        return True

    # ========================================================================
    # LAST RESULT
    # ========================================================================

    def last_result(
        self,
    ) -> Optional[
        AutonomousCodingResult
    ]:

        return self._last_result

    # ========================================================================
    # HISTORY HELPERS
    # ========================================================================

    @staticmethod
    def _collect_errors(
        history: List[CodingAttempt],
        limit: int = 20,
    ) -> List[str]:

        errors: List[str] = []

        for attempt in history:

            for error in attempt.errors:

                if not error:
                    continue

                error = str(
                    error
                ).strip()

                if not error:
                    continue

                if error in errors:
                    continue

                errors.append(
                    error
                )

                if len(errors) >= limit:
                    return errors

        return errors

    # ========================================================================
    # HEALTH
    # ========================================================================

    def health(
        self,
    ) -> Dict[str, Any]:

        bridge_health = {}

        try:

            bridge_health = (
                self.bridge.health()
            )

        except Exception as exc:

            bridge_health = {
                "healthy": False,
                "error": self._bounded_error(
                    exc
                ),
            }

        bridge_ok = bool(
            bridge_health.get(
                "healthy",
                False,
            )
        )

        return {
            "component": (
                "AutonomousCodingLoop"
            ),
            "healthy": bridge_ok,
            "version": self.VERSION,
            "active": self._active,
            "max_attempts": (
                self.max_attempts
            ),
            "bridge": bridge_health,
            "statistics": dict(
                self.statistics
            ),
        }

    # ========================================================================
    # DESCRIPTION
    # ========================================================================

    def describe(
        self,
    ) -> Dict[str, Any]:

        return {
            "component": (
                "AutonomousCodingLoop"
            ),
            "version": self.VERSION,
            "purpose": (
                "Drive bounded autonomous software "
                "development through ARIA's existing "
                "DevelopmentController."
            ),
            "inner_development_owner": (
                "DevelopmentAgent"
            ),
            "inner_repair_owner": (
                "DevelopmentAgent"
            ),
            "supports": [
                "future phase development",
                "feature implementation",
                "bug fixing",
                "repository changes",
                "bounded retries",
                "development result tracking",
                "failure preservation",
            ],
            "does_not_perform": [
                "direct filesystem writes",
                "direct shell execution",
                "GitHub push",
                "production deployment",
            ],
            "max_attempts": (
                self.max_attempts
            ),
        }

    # ========================================================================
    # ERROR HELPER
    # ========================================================================

    @staticmethod
    def _bounded_error(
        exc: Exception,
        limit: int = 1500,
    ) -> str:

        text = (
            f"{type(exc).__name__}: {exc}"
        ).strip()

        if len(text) > limit:
            return (
                text[: limit - 3]
                + "..."
            )

        return text


__all__ = [
    "CodingAttempt",
    "AutonomousCodingResult",
    "AutonomousCodingLoop",
]