"""
ARIA Phase 1 — Autonomous Development Bridge

Step 21 / 28

Connects ARIA's high-level Phase 1 orchestration system to the
existing real development subsystem.

Architecture:

    Phase1System
        ↓
    AutonomousDevelopmentBridge
        ↓
    DevelopmentController
        ↓
    DevelopmentAgent
        ↓
    Requirement Intelligence
        ↓
    Repository Inspection
        ↓
    Workspace
        ↓
    Code Generation
        ↓
    Guarded File Writes
        ↓
    Build / Validation / Tests
        ↓
    Failure Analysis
        ↓
    Repair
        ↓
    Retest
        ↓
    DevelopmentReport

This bridge deliberately does NOT:
    - push to GitHub;
    - deploy;
    - bypass filesystem protection;
    - bypass the existing DevelopmentAgent;
    - directly modify production files;
    - create an unlimited retry loop.

GitHub and deployment remain explicit, permissioned operations.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Sequence


logger = logging.getLogger("aria.autonomous_development")


# =====================================================================
# RESULT
# =====================================================================


@dataclass
class AutonomousDevelopmentResult:
    """
    Stable result returned by the development bridge.
    """

    success: bool

    status: str

    requirement: str

    job_id: Optional[str] = None

    development_report: Any = None

    errors: list[str] = field(
        default_factory=list
    )

    elapsed_seconds: float = 0.0

    metadata: Dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self) -> Dict[str, Any]:
        report = self.development_report

        if hasattr(report, "to_dict"):
            try:
                report = report.to_dict()
            except Exception:
                report = None

        return {
            "success": self.success,
            "status": self.status,
            "requirement": self.requirement,
            "job_id": self.job_id,
            "development_report": report,
            "errors": list(self.errors),
            "elapsed_seconds": self.elapsed_seconds,
            "metadata": dict(self.metadata),
        }


# =====================================================================
# BRIDGE
# =====================================================================


class AutonomousDevelopmentBridge:
    """
    Controlled bridge between Phase 1 orchestration and ARIA's
    existing DevelopmentController.

    The bridge is intentionally small.

    The DevelopmentController remains responsible for:
        requirement processing
        repository inspection
        workspace creation
        code generation
        guarded writes
        validation
        testing
        repair
        final development result

    This class only provides the higher-level autonomous interface.
    """

    VERSION = (
        "PHASE1-AUTONOMOUS-DEVELOPMENT-BRIDGE-20261004"
    )

    DEFAULT_TIMEOUT_SECONDS = 1800.0

    DEVELOPMENT_KEYWORDS = {
        "build",
        "develop",
        "development",
        "implement",
        "implementation",
        "code",
        "coding",
        "create",
        "modify",
        "change",
        "fix",
        "repair",
        "refactor",
        "feature",
        "function",
        "module",
        "phase",
        "subsystem",
        "api",
        "endpoint",
        "database",
        "integration",
        "test",
        "bug",
        "error",
        "project",
        "repository",
        "repo",
    }

    NON_DEVELOPMENT_KEYWORDS = {
        "weather",
        "time",
        "remind",
        "reminder",
        "music",
        "movie",
        "search",
        "news",
        "translate",
    }

    def __init__(
        self,
        development_controller: Any,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:

        if development_controller is None:
            raise ValueError(
                "development_controller is required."
            )

        if not hasattr(
            development_controller,
            "execute",
        ):
            raise TypeError(
                "development_controller must expose "
                "execute()."
            )

        self.controller = (
            development_controller
        )

        self.timeout_seconds = max(
            30.0,
            min(
                7200.0,
                float(timeout_seconds),
            ),
        )

        self.statistics = {
            "requests": 0,
            "successful": 0,
            "failed": 0,
            "timeouts": 0,
        }

        self._active = False

    # =================================================================
    # REQUEST CLASSIFICATION
    # =================================================================

    @classmethod
    def is_development_request(
        cls,
        request: str,
    ) -> bool:
        """
        Determine whether a request is intended to modify/build
        software.

        This is intentionally conservative.

        Explicit development language is preferred over vague
        interpretation.
        """

        text = str(
            request or ""
        ).strip().lower()

        if not text:
            return False

        # Strong explicit signals.
        explicit_patterns = (
            "build phase",
            "implement",
            "write code",
            "create a file",
            "create files",
            "modify the code",
            "fix the code",
            "fix this bug",
            "develop",
            "refactor",
            "add a feature",
            "make changes to aria",
            "change aria",
            "continue development",
            "complete phase",
        )

        if any(
            pattern in text
            for pattern in explicit_patterns
        ):
            return True

        words = {
            word.strip(
                ".,!?;:()[]{}"
            )
            for word in text.split()
        }

        development_hits = len(
            words.intersection(
                cls.DEVELOPMENT_KEYWORDS
            )
        )

        non_development_hits = len(
            words.intersection(
                cls.NON_DEVELOPMENT_KEYWORDS
            )
        )

        return (
            development_hits >= 2
            and development_hits
            > non_development_hits
        )

    # =================================================================
    # STATUS
    # =================================================================

    def is_running(self) -> bool:
        return bool(
            self._active
        )

    def status(self) -> Dict[str, Any]:

        controller_status = None

        try:

            status_method = getattr(
                self.controller,
                "status",
                None,
            )

            if callable(status_method):
                controller_status = (
                    status_method()
                )

        except Exception as exc:

            controller_status = {
                "error": str(exc),
            }

        return {
            "version": self.VERSION,
            "running": self._active,
            "timeout_seconds": (
                self.timeout_seconds
            ),
            "statistics": dict(
                self.statistics
            ),
            "controller": controller_status,
        }

    # =================================================================
    # EXECUTION
    # =================================================================

    async def develop(
        self,
        requirement: str,
        *,
        changes: Optional[
            list[tuple[str, str]]
        ] = None,
        test_paths: Optional[
            list[str]
        ] = None,
        workspace_id: Optional[str] = None,
        context: Optional[
            Dict[str, Any]
        ] = None,
    ) -> AutonomousDevelopmentResult:
        """
        Execute a complete development request through the existing
        DevelopmentController.
        """

        started = time.monotonic()

        normalized_requirement = (
            str(
                requirement or ""
            ).strip()
        )

        if not normalized_requirement:

            return AutonomousDevelopmentResult(
                success=False,
                status="invalid_request",
                requirement="",
                errors=[
                    "Development requirement is empty."
                ],
            )

        self.statistics[
            "requests"
        ] += 1

        self._active = True

        try:

            logger.info(
                "[AutonomousDevelopment] "
                "Starting development request: %s",
                normalized_requirement[:300],
            )

            # ---------------------------------------------------------
            # Pass only safe, explicit development information to the
            # existing DevelopmentController.
            #
            # The controller/development-agent remains the authority
            # for filesystem operations.
            # ---------------------------------------------------------

            job = await asyncio.wait_for(
                self.controller.execute(
                    normalized_requirement,
                    changes=changes,
                    test_paths=test_paths,
                    workspace_id=workspace_id,
                ),
                timeout=self.timeout_seconds,
            )

            elapsed = (
                time.monotonic()
                - started
            )

            success = bool(
                getattr(
                    job,
                    "status",
                    "",
                )
                == "completed"
            )

            report = getattr(
                job,
                "report",
                None,
            )

            if report is not None:
                success = bool(
                    getattr(
                        report,
                        "success",
                        success,
                    )
                )

            if success:

                self.statistics[
                    "successful"
                ] += 1

                status = "completed"

            else:

                self.statistics[
                    "failed"
                ] += 1

                status = str(
                    getattr(
                        job,
                        "status",
                        "failed",
                    )
                )

            job_id = getattr(
                job,
                "job_id",
                None,
            )

            return AutonomousDevelopmentResult(
                success=success,
                status=status,
                requirement=(
                    normalized_requirement
                ),
                job_id=(
                    str(job_id)
                    if job_id is not None
                    else None
                ),
                development_report=report,
                elapsed_seconds=elapsed,
                metadata={
                    "bridge_version": self.VERSION,
                    "context_supplied": (
                        isinstance(
                            context,
                            dict,
                        )
                    ),
                    "workspace_id": (
                        workspace_id
                    ),
                },
            )

        except asyncio.TimeoutError:

            self.statistics[
                "timeouts"
            ] += 1

            elapsed = (
                time.monotonic()
                - started
            )

            logger.error(
                "[AutonomousDevelopment] "
                "Development timeout."
            )

            return AutonomousDevelopmentResult(
                success=False,
                status="timeout",
                requirement=(
                    normalized_requirement
                ),
                errors=[
                    (
                        "Development request exceeded "
                        f"{self.timeout_seconds:.0f} "
                        "seconds."
                    )
                ],
                elapsed_seconds=elapsed,
                metadata={
                    "bridge_version": self.VERSION,
                },
            )

        except asyncio.CancelledError:

            elapsed = (
                time.monotonic()
                - started
            )

            logger.warning(
                "[AutonomousDevelopment] "
                "Development request cancelled."
            )

            return AutonomousDevelopmentResult(
                success=False,
                status="cancelled",
                requirement=(
                    normalized_requirement
                ),
                errors=[
                    "Development request cancelled."
                ],
                elapsed_seconds=elapsed,
                metadata={
                    "bridge_version": self.VERSION,
                },
            )

        except Exception as exc:

            self.statistics[
                "failed"
            ] += 1

            elapsed = (
                time.monotonic()
                - started
            )

            logger.exception(
                "[AutonomousDevelopment] "
                "Development request failed."
            )

            return AutonomousDevelopmentResult(
                success=False,
                status="failed",
                requirement=(
                    normalized_requirement
                ),
                errors=[
                    self._bounded_error(
                        exc
                    )
                ],
                elapsed_seconds=elapsed,
                metadata={
                    "bridge_version": self.VERSION,
                    "error_type": (
                        type(exc).__name__
                    ),
                },
            )

        finally:

            self._active = False

    # =================================================================
    # SYNCHRONOUS HELPER
    # =================================================================

    def develop_sync(
        self,
        requirement: str,
        *,
        changes: Optional[
            list[tuple[str, str]]
        ] = None,
        test_paths: Optional[
            list[str]
        ] = None,
        workspace_id: Optional[str] = None,
        context: Optional[
            Dict[str, Any]
        ] = None,
    ) -> AutonomousDevelopmentResult:
        """
        Convenience wrapper for synchronous callers.

        If already running inside an asyncio event loop, callers should
        use develop() directly.
        """

        try:
            asyncio.get_running_loop()

        except RuntimeError:

            return asyncio.run(
                self.develop(
                    requirement,
                    changes=changes,
                    test_paths=test_paths,
                    workspace_id=workspace_id,
                    context=context,
                )
            )

        raise RuntimeError(
            "develop_sync() cannot be called from "
            "an active asyncio event loop. "
            "Use await develop()."
        )

    # =================================================================
    # HISTORY / CONTROLLER ACCESS
    # =================================================================

    def history(self) -> Any:

        method = getattr(
            self.controller,
            "history",
            None,
        )

        if callable(method):
            return method()

        return []

    def last_job(self) -> Any:

        method = getattr(
            self.controller,
            "last_job",
            None,
        )

        if callable(method):
            return method()

        return None

    # =================================================================
    # HELPERS
    # =================================================================

    @staticmethod
    def _bounded_error(
        exc: Exception,
        limit: int = 1000,
    ) -> str:

        text = (
            f"{type(exc).__name__}: {exc}"
        ).strip()

        if len(text) > limit:
            text = (
                text[:limit - 3]
                + "..."
            )

        return text

    # =================================================================
    # HEALTH
    # =================================================================

    def health(self) -> Dict[str, Any]:

        controller_available = (
            self.controller is not None
            and callable(
                getattr(
                    self.controller,
                    "execute",
                    None,
                )
            )
        )

        return {
            "healthy": (
                controller_available
            ),
            "version": self.VERSION,
            "running": self._active,
            "controller_available": (
                controller_available
            ),
            "statistics": dict(
                self.statistics
            ),
        }


__all__ = [
    "AutonomousDevelopmentBridge",
    "AutonomousDevelopmentResult",
]