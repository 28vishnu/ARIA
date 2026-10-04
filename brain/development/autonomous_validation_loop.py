"""
ARIA Phase 1 — Autonomous Validation Loop

Step 23 / 28

Purpose
-------
Provide a stable validation boundary around ARIA's existing development
validation infrastructure.

Flow:

    AutonomousCodingLoop
            ↓
    AutonomousValidationLoop
            ↓
    DevelopmentController / DevelopmentAgent
            ↓
    Workspace
            ↓
    Build
            ↓
    Static validation
            ↓
    Tests
            ↓
    Runtime validation
            ↓
    ValidationResult

Important:
-----------
This module does not replace ARIA's existing:
    - sandbox
    - build manager
    - test runner
    - validator
    - development agent

It discovers and calls the available controller validation APIs safely.

No GitHub push or deployment is performed here.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional


logger = logging.getLogger(
    "aria.autonomous_validation"
)


# ============================================================================
# RESULT MODELS
# ============================================================================


@dataclass
class ValidationCheck:
    """
    One validation check.
    """

    name: str

    passed: bool

    status: str = ""

    output: str = ""

    error: str = ""

    duration_seconds: float = 0.0

    metadata: Dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(
        self,
    ) -> Dict[str, Any]:

        return {
            "name": self.name,
            "passed": self.passed,
            "status": self.status,
            "output": self.output,
            "error": self.error,
            "duration_seconds": (
                self.duration_seconds
            ),
            "metadata": dict(
                self.metadata
            ),
        }


@dataclass
class AutonomousValidationResult:
    """
    Final validation result.
    """

    success: bool

    status: str

    workspace_id: Optional[str] = None

    checks: List[
        ValidationCheck
    ] = field(
        default_factory=list
    )

    errors: List[str] = field(
        default_factory=list
    )

    warnings: List[str] = field(
        default_factory=list
    )

    duration_seconds: float = 0.0

    metadata: Dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(
        self,
    ) -> Dict[str, Any]:

        return {
            "success": self.success,
            "status": self.status,
            "workspace_id": (
                self.workspace_id
            ),
            "checks": [
                check.to_dict()
                for check in self.checks
            ],
            "errors": list(
                self.errors
            ),
            "warnings": list(
                self.warnings
            ),
            "duration_seconds": (
                self.duration_seconds
            ),
            "metadata": dict(
                self.metadata
            ),
        }


# ============================================================================
# VALIDATION LOOP
# ============================================================================


class AutonomousValidationLoop:
    """
    Stable validation boundary for autonomous development.

    The controller remains the authority for actual code execution.

    This layer:
        - invokes supported validation APIs
        - normalizes results
        - records failures
        - provides a single validation result
        - never executes arbitrary shell commands itself
    """

    VERSION = (
        "PHASE1-AUTONOMOUS-VALIDATION-20261004"
    )

    MAX_CHECKS = 20

    DEFAULT_TIMEOUT_SECONDS = 600.0

    # Common method names used by existing ARIA development systems.
    BUILD_METHODS = (
        "build",
        "run_build",
        "build_project",
        "validate_build",
        "run_build_check",
    )

    TEST_METHODS = (
        "test",
        "run_tests",
        "execute_tests",
        "test_project",
        "validate_tests",
    )

    VALIDATION_METHODS = (
        "validate",
        "validate_project",
        "run_validation",
        "validate_workspace",
        "verify",
    )

    STATIC_METHODS = (
        "static_check",
        "static_validate",
        "lint",
        "run_lint",
        "type_check",
        "run_type_check",
    )

    def __init__(
        self,
        development_controller: Any,
        *,
        timeout_seconds: float = (
            DEFAULT_TIMEOUT_SECONDS
        ),
        require_tests: bool = False,
    ) -> None:

        if development_controller is None:
            raise ValueError(
                "development_controller is required."
            )

        self.controller = (
            development_controller
        )

        self.timeout_seconds = max(
            30.0,
            min(
                3600.0,
                float(
                    timeout_seconds
                ),
            ),
        )

        self.require_tests = bool(
            require_tests
        )

        self._active = False

        self.statistics = {
            "validation_runs": 0,
            "successful": 0,
            "failed": 0,
            "timeouts": 0,
        }

    # ========================================================================
    # STATUS
    # ========================================================================

    def status(
        self,
    ) -> Dict[str, Any]:

        return {
            "component": (
                "AutonomousValidationLoop"
            ),
            "version": self.VERSION,
            "active": self._active,
            "timeout_seconds": (
                self.timeout_seconds
            ),
            "require_tests": (
                self.require_tests
            ),
            "statistics": dict(
                self.statistics
            ),
        }

    def health(
        self,
    ) -> Dict[str, Any]:

        return {
            "component": (
                "AutonomousValidationLoop"
            ),
            "healthy": (
                self.controller is not None
            ),
            "version": self.VERSION,
            "active": self._active,
            "statistics": dict(
                self.statistics
            ),
        }

    # ========================================================================
    # MAIN VALIDATION
    # ========================================================================

    async def validate(
        self,
        *,
        workspace_id: Optional[str] = None,
        test_paths: Optional[
            List[str]
        ] = None,
        requirement: Optional[str] = None,
        context: Optional[
            Dict[str, Any]
        ] = None,
    ) -> AutonomousValidationResult:
        """
        Run the available validation stages.

        The stages are intentionally capability-driven.

        If the existing controller exposes a build/test/validation
        method, it is used.

        If a particular method does not exist, that stage is skipped
        rather than incorrectly pretending it passed.
        """

        started = time.monotonic()

        self.statistics[
            "validation_runs"
        ] += 1

        self._active = True

        checks: List[
            ValidationCheck
        ] = []

        errors: List[str] = []

        warnings: List[str] = []

        try:

            # ------------------------------------------------------------
            # 1. Explicit controller validation
            # ------------------------------------------------------------

            validation_check = (
                await self._run_first_available(
                    stage="validation",
                    method_names=(
                        self.VALIDATION_METHODS
                    ),
                    workspace_id=workspace_id,
                    test_paths=test_paths,
                    requirement=requirement,
                    context=context,
                )
            )

            if validation_check is not None:

                checks.append(
                    validation_check
                )

                if not validation_check.passed:

                    errors.append(
                        self._bounded(
                            validation_check.error
                            or validation_check.output
                            or (
                                "Validation stage "
                                "failed."
                            )
                        )
                    )

            # ------------------------------------------------------------
            # 2. Build
            # ------------------------------------------------------------

            build_check = (
                await self._run_first_available(
                    stage="build",
                    method_names=(
                        self.BUILD_METHODS
                    ),
                    workspace_id=workspace_id,
                    test_paths=test_paths,
                    requirement=requirement,
                    context=context,
                )
            )

            if build_check is not None:

                checks.append(
                    build_check
                )

                if not build_check.passed:

                    errors.append(
                        self._bounded(
                            build_check.error
                            or build_check.output
                            or "Build failed."
                        )
                    )

            # ------------------------------------------------------------
            # 3. Static checks
            # ------------------------------------------------------------

            static_check = (
                await self._run_first_available(
                    stage="static",
                    method_names=(
                        self.STATIC_METHODS
                    ),
                    workspace_id=workspace_id,
                    test_paths=test_paths,
                    requirement=requirement,
                    context=context,
                )
            )

            if static_check is not None:

                checks.append(
                    static_check
                )

                if not static_check.passed:

                    errors.append(
                        self._bounded(
                            static_check.error
                            or static_check.output
                            or (
                                "Static validation "
                                "failed."
                            )
                        )
                    )

            # ------------------------------------------------------------
            # 4. Tests
            # ------------------------------------------------------------

            test_check = (
                await self._run_first_available(
                    stage="tests",
                    method_names=(
                        self.TEST_METHODS
                    ),
                    workspace_id=workspace_id,
                    test_paths=test_paths,
                    requirement=requirement,
                    context=context,
                )
            )

            if test_check is not None:

                checks.append(
                    test_check
                )

                if not test_check.passed:

                    errors.append(
                        self._bounded(
                            test_check.error
                            or test_check.output
                            or "Tests failed."
                        )
                    )

            elif self.require_tests:

                errors.append(
                    "No test runner is available."
                )

                warnings.append(
                    (
                        "The controller does not expose "
                        "a recognized test API."
                    )
                )

            else:

                warnings.append(
                    (
                        "No explicit test API was "
                        "exposed by the controller."
                    )
                )

            # ------------------------------------------------------------
            # 5. No supported validation API
            # ------------------------------------------------------------

            if not checks:

                errors.append(
                    (
                        "No supported validation API "
                        "was exposed by the "
                        "DevelopmentController."
                    )
                )

                status = (
                    "validation_unavailable"
                )

                success = False

            else:

                failed_checks = [
                    check
                    for check in checks
                    if not check.passed
                ]

                if failed_checks:

                    status = (
                        "validation_failed"
                    )

                    success = False

                else:

                    status = (
                        "validated"
                    )

                    success = True

            duration = (
                time.monotonic()
                - started
            )

            if success:

                self.statistics[
                    "successful"
                ] += 1

            else:

                self.statistics[
                    "failed"
                ] += 1

            return AutonomousValidationResult(
                success=success,
                status=status,
                workspace_id=workspace_id,
                checks=checks[
                    : self.MAX_CHECKS
                ],
                errors=self._unique(
                    errors
                ),
                warnings=self._unique(
                    warnings
                ),
                duration_seconds=duration,
                metadata={
                    "version": self.VERSION,
                    "requirement_supplied": bool(
                        requirement
                    ),
                    "tests_required": (
                        self.require_tests
                    ),
                },
            )

        except asyncio.TimeoutError:

            self.statistics[
                "timeouts"
            ] += 1

            duration = (
                time.monotonic()
                - started
            )

            return AutonomousValidationResult(
                success=False,
                status="timeout",
                workspace_id=workspace_id,
                checks=checks,
                errors=[
                    (
                        "Validation exceeded "
                        f"{self.timeout_seconds:.0f} "
                        "seconds."
                    )
                ],
                warnings=warnings,
                duration_seconds=duration,
                metadata={
                    "version": self.VERSION,
                },
            )

        except asyncio.CancelledError:

            duration = (
                time.monotonic()
                - started
            )

            return AutonomousValidationResult(
                success=False,
                status="cancelled",
                workspace_id=workspace_id,
                checks=checks,
                errors=[
                    "Validation was cancelled."
                ],
                duration_seconds=duration,
                metadata={
                    "version": self.VERSION,
                },
            )

        except Exception as exc:

            self.statistics[
                "failed"
            ] += 1

            duration = (
                time.monotonic()
                - started
            )

            logger.exception(
                "[AutonomousValidationLoop] "
                "Validation failed."
            )

            return AutonomousValidationResult(
                success=False,
                status="validation_error",
                workspace_id=workspace_id,
                checks=checks,
                errors=[
                    self._bounded_error(
                        exc
                    )
                ],
                warnings=warnings,
                duration_seconds=duration,
                metadata={
                    "version": self.VERSION,
                    "error_type": (
                        type(exc).__name__
                    ),
                },
            )

        finally:

            self._active = False

    # ========================================================================
    # RUN FIRST AVAILABLE API
    # ========================================================================

    async def _run_first_available(
        self,
        *,
        stage: str,
        method_names: Iterable[str],
        workspace_id: Optional[str],
        test_paths: Optional[
            List[str]
        ],
        requirement: Optional[str],
        context: Optional[
            Dict[str, Any]
        ],
    ) -> Optional[
        ValidationCheck
    ]:
        """
        Find and call the first supported controller API for a stage.
        """

        method = None

        method_name = None

        for candidate in method_names:

            candidate_method = getattr(
                self.controller,
                candidate,
                None,
            )

            if callable(
                candidate_method
            ):

                method = (
                    candidate_method
                )

                method_name = candidate

                break

        if method is None:

            return None

        started = time.monotonic()

        try:

            result = await asyncio.wait_for(
                self._call_method(
                    method,
                    workspace_id=workspace_id,
                    test_paths=test_paths,
                    requirement=requirement,
                    context=context,
                ),
                timeout=self.timeout_seconds,
            )

            duration = (
                time.monotonic()
                - started
            )

            return self._normalize_check(
                stage=stage,
                method_name=method_name,
                result=result,
                duration=duration,
            )

        except asyncio.TimeoutError:

            return ValidationCheck(
                name=stage,
                passed=False,
                status="timeout",
                error=(
                    f"{stage} stage timed out."
                ),
                duration_seconds=(
                    time.monotonic()
                    - started
                ),
                metadata={
                    "method": method_name
                },
            )

        except Exception as exc:

            logger.exception(
                "[AutonomousValidationLoop] "
                "%s stage failed.",
                stage,
            )

            return ValidationCheck(
                name=stage,
                passed=False,
                status="error",
                error=self._bounded_error(
                    exc
                ),
                duration_seconds=(
                    time.monotonic()
                    - started
                ),
                metadata={
                    "method": method_name
                },
            )

    # ========================================================================
    # CALL ADAPTER
    # ========================================================================

    async def _call_method(
        self,
        method: Any,
        *,
        workspace_id: Optional[str],
        test_paths: Optional[
            List[str]
        ],
        requirement: Optional[str],
        context: Optional[
            Dict[str, Any]
        ],
    ) -> Any:
        """
        Adapt arguments to the existing controller API.

        This avoids assuming one exact signature.
        """

        kwargs = {
            "workspace_id": workspace_id,
            "test_paths": test_paths,
            "requirement": requirement,
            "context": context,
        }

        # Remove None values.
        kwargs = {
            key: value
            for key, value in kwargs.items()
            if value is not None
        }

        try:

            signature = inspect.signature(
                method
            )

            parameters = (
                signature.parameters
            )

            accepts_kwargs = any(
                parameter.kind
                == inspect.Parameter.VAR_KEYWORD
                for parameter
                in parameters.values()
            )

            if not accepts_kwargs:

                kwargs = {
                    key: value
                    for key, value in kwargs.items()
                    if key in parameters
                }

            result = method(
                **kwargs
            )

        except (
            TypeError,
            ValueError,
        ):

            # Some decorated/bound methods may not expose a usable
            # signature. Fall back to the simplest invocation.
            result = method()

        if inspect.isawaitable(
            result
        ):

            return await result

        return result

    # ========================================================================
    # RESULT NORMALIZATION
    # ========================================================================

    def _normalize_check(
        self,
        *,
        stage: str,
        method_name: Optional[str],
        result: Any,
        duration: float,
    ) -> ValidationCheck:
        """
        Convert arbitrary existing validation return types into one
        stable ValidationCheck.
        """

        if result is None:

            return ValidationCheck(
                name=stage,
                passed=True,
                status="completed",
                output=(
                    f"{stage} completed."
                ),
                duration_seconds=duration,
                metadata={
                    "method": method_name,
                    "result_type": "None",
                },
            )

        if isinstance(
            result,
            bool,
        ):

            return ValidationCheck(
                name=stage,
                passed=result,
                status=(
                    "passed"
                    if result
                    else "failed"
                ),
                output=(
                    f"{stage} returned "
                    f"{result}."
                ),
                error=(
                    ""
                    if result
                    else f"{stage} returned False."
                ),
                duration_seconds=duration,
                metadata={
                    "method": method_name,
                    "result_type": "bool",
                },
            )

        # Dataclass / object style.
        success = self._extract_success(
            result
        )

        status = self._extract_text(
            result,
            (
                "status",
                "state",
                "result",
            ),
        )

        output = self._extract_text(
            result,
            (
                "output",
                "stdout",
                "message",
                "summary",
                "details",
            ),
        )

        error = self._extract_text(
            result,
            (
                "error",
                "stderr",
                "failure",
                "reason",
            ),
        )

        # Dictionary style.
        if isinstance(
            result,
            dict,
        ):

            if "success" in result:

                success = bool(
                    result.get(
                        "success"
                    )
                )

            elif "passed" in result:

                success = bool(
                    result.get(
                        "passed"
                    )
                )

            if not status:

                status = self._safe_string(
                    result.get(
                        "status"
                    )
                )

            if not output:

                output = self._safe_string(
                    result.get(
                        "output"
                    )
                    or result.get(
                        "message"
                    )
                    or result.get(
                        "summary"
                    )
                )

            if not error:

                error = self._safe_string(
                    result.get(
                        "error"
                    )
                    or result.get(
                        "stderr"
                    )
                    or result.get(
                        "failure"
                    )
                )

        if success is None:

            # A returned result without an explicit success flag
            # is treated as successful only when it does not expose
            # an obvious failure status/error.
            failure_tokens = (
                "fail",
                "error",
                "invalid",
                "timeout",
                "blocked",
                "exception",
            )

            normalized_status = (
                status.lower()
                if status
                else ""
            )

            normalized_error = (
                error.lower()
                if error
                else ""
            )

            if any(
                token in normalized_status
                for token in failure_tokens
            ):
                success = False

            elif error:

                success = False

            else:

                success = True

        if not status:

            status = (
                "passed"
                if success
                else "failed"
            )

        return ValidationCheck(
            name=stage,
            passed=bool(
                success
            ),
            status=status,
            output=self._bounded(
                output
            ),
            error=self._bounded(
                error
            ),
            duration_seconds=duration,
            metadata={
                "method": method_name,
                "result_type": (
                    type(result).__name__
                ),
            },
        )

    # ========================================================================
    # EXTRACTORS
    # ========================================================================

    @staticmethod
    def _extract_success(
        result: Any,
    ) -> Optional[bool]:

        if isinstance(
            result,
            dict,
        ):

            if "success" in result:
                return bool(
                    result["success"]
                )

            if "passed" in result:
                return bool(
                    result["passed"]
                )

            return None

        for name in (
            "success",
            "passed",
            "ok",
            "valid",
        ):

            if hasattr(
                result,
                name,
            ):

                value = getattr(
                    result,
                    name,
                )

                if value is not None:
                    return bool(
                        value
                    )

        return None

    @staticmethod
    def _extract_text(
        result: Any,
        names: Iterable[str],
    ) -> str:

        if isinstance(
            result,
            dict,
        ):

            for name in names:

                value = result.get(
                    name
                )

                if value is not None:

                    return str(
                        value
                    ).strip()

            return ""

        for name in names:

            if hasattr(
                result,
                name,
            ):

                value = getattr(
                    result,
                    name,
                )

                if value is not None:

                    return str(
                        value
                    ).strip()

        return ""

    # ========================================================================
    # UTILITIES
    # ========================================================================

    @staticmethod
    def _safe_string(
        value: Any,
    ) -> str:

        if value is None:
            return ""

        return str(
            value
        ).strip()

    @staticmethod
    def _bounded(
        value: Any,
        limit: int = 3000,
    ) -> str:

        text = (
            str(
                value or ""
            )
            .strip()
        )

        if len(text) <= limit:
            return text

        return (
            text[: limit - 3]
            + "..."
        )

    @classmethod
    def _bounded_error(
        cls,
        exc: Exception,
    ) -> str:

        return cls._bounded(
            (
                f"{type(exc).__name__}: "
                f"{exc}"
            ),
            2000,
        )

    @staticmethod
    def _unique(
        values: Iterable[str],
    ) -> List[str]:

        result: List[str] = []

        for value in values:

            value = str(
                value or ""
            ).strip()

            if not value:
                continue

            if value in result:
                continue

            result.append(
                value
            )

        return result


__all__ = [
    "ValidationCheck",
    "AutonomousValidationResult",
    "AutonomousValidationLoop",
]