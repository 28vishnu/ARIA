"""
ARIA Phase 1 — Step 11: Autonomous Execution Controller.

Provides the autonomous control loop around ARIA's canonical Executor.

Architecture:

    Goal
      ↓
    PhasePlanner
      ↓
    ExecutionPlan
      ↓
    AutonomousExecutionController
      ↓
    Canonical Executor
      ↓
    Verification / Replanning
      ↓
    Completed result

This module does NOT replace brain.executor.Executor.

Responsibilities:
- accept an already-created ExecutionPlan;
- execute it through the canonical Executor;
- monitor completion/failure;
- request dynamic replanning when supported;
- enforce bounded autonomous cycles;
- prevent infinite execution loops;
- preserve execution context;
- expose execution state;
- remain safe when optional components are unavailable.

The controller never invents tools or bypasses the canonical executor.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from brain.plan import ExecutionPlan

logger = logging.getLogger("aria")


@dataclass
class AutonomousExecutionResult:
    """Machine-readable result of an autonomous workflow."""

    success: bool
    status: str
    cycles: int = 0

    completed_tasks: List[str] = field(
        default_factory=list
    )

    failed_tasks: List[str] = field(
        default_factory=list
    )

    skipped_tasks: List[str] = field(
        default_factory=list
    )

    task_outputs: Dict[str, Any] = field(
        default_factory=dict
    )

    error: Optional[str] = None

    elapsed_seconds: float = 0.0

    replans: int = 0

    metadata: Dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "status": self.status,
            "cycles": self.cycles,
            "completed_tasks": list(
                self.completed_tasks
            ),
            "failed_tasks": list(
                self.failed_tasks
            ),
            "skipped_tasks": list(
                self.skipped_tasks
            ),
            "task_outputs": dict(
                self.task_outputs
            ),
            "error": self.error,
            "elapsed_seconds": self.elapsed_seconds,
            "replans": self.replans,
            "metadata": dict(
                self.metadata
            ),
        }


class AutonomousExecutionController:
    """
    Bounded autonomous workflow controller.

    The controller intentionally keeps autonomy bounded:

    - maximum execution cycles;
    - maximum replans;
    - optional workflow timeout;
    - no execution if the plan is invalid;
    - no hidden tool execution;
    - no infinite retry/replan loop.
    """

    VERSION = (
        "PHASE1-AUTONOMOUS-EXECUTION-20261004"
    )

    DEFAULT_MAX_CYCLES = 3
    DEFAULT_MAX_REPLANS = 2
    DEFAULT_TIMEOUT_SECONDS = 600.0

    def __init__(
        self,
        executor,
        planner=None,
        verifier=None,
        max_cycles: int = DEFAULT_MAX_CYCLES,
        max_replans: int = DEFAULT_MAX_REPLANS,
        timeout_seconds: float = (
            DEFAULT_TIMEOUT_SECONDS
        ),
    ) -> None:

        if executor is None:
            raise ValueError(
                "executor is required"
            )

        self.executor = executor
        self.planner = (
            planner
            or getattr(
                executor,
                "planner",
                None,
            )
        )

        self.verifier = (
            verifier
            or getattr(
                executor,
                "verifier",
                None,
            )
        )

        self.max_cycles = max(
            1,
            min(
                20,
                int(max_cycles),
            ),
        )

        self.max_replans = max(
            0,
            min(
                10,
                int(max_replans),
            ),
        )

        self.timeout_seconds = max(
            1.0,
            min(
                7200.0,
                float(timeout_seconds),
            ),
        )

        self.active_workflows: Dict[
            str,
            Dict[str, Any],
        ] = {}

        self.statistics = {
            "workflows": 0,
            "successful": 0,
            "failed": 0,
            "cancelled": 0,
            "timeouts": 0,
            "cycles": 0,
            "replans": 0,
        }

    # =========================================================
    # MAIN AUTONOMOUS API
    # =========================================================

    async def run(
        self,
        plan: ExecutionPlan,
        context: Optional[
            Dict[str, Any]
        ] = None,
        workflow_id: Optional[str] = None,
    ) -> AutonomousExecutionResult:
        """
        Execute an ExecutionPlan autonomously through the canonical
        ARIA Executor.

        A failed workflow may be dynamically replanned when the canonical
        planner exposes dynamic_replan().
        """

        started = time.monotonic()

        context = dict(
            context or {}
        )

        workflow_id = (
            str(workflow_id)
            if workflow_id
            else self._workflow_id(
                plan
            )
        )

        if not isinstance(
            plan,
            ExecutionPlan,
        ):
            return self._failure(
                status="rejected",
                error=(
                    "run() requires an "
                    "ExecutionPlan."
                ),
                started=started,
            )

        validation_error = (
            self._validate_plan(
                plan
            )
        )

        if validation_error:
            return self._failure(
                status="rejected",
                error=validation_error,
                started=started,
            )

        self.statistics[
            "workflows"
        ] += 1

        self.active_workflows[
            workflow_id
        ] = {
            "status": "running",
            "started": started,
            "cycles": 0,
            "replans": 0,
            "goal": plan.goal,
        }

        current_plan = plan
        cycle = 0
        replans = 0

        try:

            while cycle < self.max_cycles:

                cycle += 1

                self.statistics[
                    "cycles"
                ] += 1

                self.active_workflows[
                    workflow_id
                ]["cycles"] = cycle

                elapsed = (
                    time.monotonic()
                    - started
                )

                if (
                    elapsed
                    >= self.timeout_seconds
                ):
                    self.statistics[
                        "timeouts"
                    ] += 1

                    self._mark_timeout(
                        current_plan
                    )

                    return self._failure(
                        status="timeout",
                        error=(
                            "Autonomous execution "
                            "timeout reached."
                        ),
                        started=started,
                        plan=current_plan,
                        cycles=cycle,
                        replans=replans,
                    )

                logger.info(
                    "[AutonomousExecution] "
                    "Starting cycle %d for workflow %s.",
                    cycle,
                    workflow_id,
                )

                execution_context = dict(
                    context
                )

                execution_context[
                    "autonomous_execution"
                ] = True

                execution_context[
                    "workflow_id"
                ] = workflow_id

                execution_context[
                    "cycle"
                ] = cycle

                execution_context[
                    "replan_count"
                ] = replans

                remaining_timeout = max(
                    1.0,
                    self.timeout_seconds
                    - (
                        time.monotonic()
                        - started
                    ),
                )

                try:

                    execution_result = (
                        await asyncio.wait_for(
                            self.executor.execute_plan(
                                current_plan,
                                context=execution_context,
                            ),
                            timeout=remaining_timeout,
                        )
                    )

                except asyncio.TimeoutError:

                    self.statistics[
                        "timeouts"
                    ] += 1

                    self._mark_timeout(
                        current_plan
                    )

                    return self._failure(
                        status="timeout",
                        error=(
                            "Executor exceeded "
                            "the autonomous "
                            "execution timeout."
                        ),
                        started=started,
                        plan=current_plan,
                        cycles=cycle,
                        replans=replans,
                    )

                except asyncio.CancelledError:

                    self.statistics[
                        "cancelled"
                    ] += 1

                    self._mark_cancelled(
                        current_plan
                    )

                    return self._failure(
                        status="cancelled",
                        error=(
                            "Autonomous execution "
                            "was cancelled."
                        ),
                        started=started,
                        plan=current_plan,
                        cycles=cycle,
                        replans=replans,
                    )

                except Exception as exc:

                    logger.exception(
                        "[AutonomousExecution] "
                        "Executor failed."
                    )

                    if (
                        replans
                        < self.max_replans
                    ):
                        replanned = (
                            await self._try_replan(
                                current_plan,
                                context=execution_context,
                                failure_reason=str(
                                    exc
                                ),
                            )
                        )

                        if replanned is not None:

                            current_plan = (
                                replanned
                            )

                            replans += 1

                            self.statistics[
                                "replans"
                            ] += 1

                            self.active_workflows[
                                workflow_id
                            ]["replans"] = replans

                            continue

                    self.statistics[
                        "failed"
                    ] += 1

                    return self._failure(
                        status="failed",
                        error=str(exc),
                        started=started,
                        plan=current_plan,
                        cycles=cycle,
                        replans=replans,
                    )

                success = (
                    self._execution_success(
                        execution_result,
                        current_plan,
                    )
                )

                # ---------------------------------------------
                # Verification
                # ---------------------------------------------

                verification = (
                    await self._verify(
                        current_plan,
                        execution_result,
                        execution_context,
                    )
                )

                verified = (
                    verification.get(
                        "verified",
                        True,
                    )
                )

                if success and verified:

                    current_plan.status = (
                        "completed"
                    )

                    self.statistics[
                        "successful"
                    ] += 1

                    self.active_workflows[
                        workflow_id
                    ]["status"] = (
                        "completed"
                    )

                    return self._success(
                        execution_result=(
                            execution_result
                        ),
                        plan=current_plan,
                        started=started,
                        cycles=cycle,
                        replans=replans,
                        verification=verification,
                    )

                # ---------------------------------------------
                # Failure / Replanning
                # ---------------------------------------------

                failure_reason = (
                    verification.get(
                        "reason"
                    )
                    or self._failure_reason(
                        execution_result,
                        current_plan,
                    )
                )

                if (
                    replans
                    < self.max_replans
                ):

                    replanned = (
                        await self._try_replan(
                            current_plan,
                            context=execution_context,
                            failure_reason=(
                                failure_reason
                                or "Execution failed."
                            ),
                        )
                    )

                    if replanned is not None:

                        current_plan = (
                            replanned
                        )

                        replans += 1

                        self.statistics[
                            "replans"
                        ] += 1

                        self.active_workflows[
                            workflow_id
                        ]["replans"] = replans

                        continue

                self.statistics[
                    "failed"
                ] += 1

                current_plan.status = (
                    "failed"
                )

                return self._failure(
                    status="failed",
                    error=(
                        failure_reason
                        or "Autonomous execution failed."
                    ),
                    started=started,
                    plan=current_plan,
                    execution_result=(
                        execution_result
                    ),
                    cycles=cycle,
                    replans=replans,
                    verification=verification,
                )

            # -------------------------------------------------
            # Cycle limit
            # -------------------------------------------------

            self.statistics[
                "failed"
            ] += 1

            return self._failure(
                status="cycle_limit",
                error=(
                    "Maximum autonomous "
                    "execution cycles reached."
                ),
                started=started,
                plan=current_plan,
                cycles=cycle,
                replans=replans,
            )

        finally:

            self.active_workflows.pop(
                workflow_id,
                None,
            )

    # =========================================================
    # VERIFICATION
    # =========================================================

    async def _verify(
        self,
        plan: ExecutionPlan,
        execution_result: Any,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Ask the existing verifier for a result when available.

        If no compatible verifier API exists, the canonical executor's
        result remains authoritative.
        """

        verifier = self.verifier

        if verifier is None:
            return {
                "verified": True,
                "source": "executor",
            }

        methods = (
            "verify_plan",
            "verify",
            "validate",
        )

        for method_name in methods:

            method = getattr(
                verifier,
                method_name,
                None,
            )

            if not callable(method):
                continue

            attempts = (
                (
                    plan,
                    execution_result,
                    context,
                ),
                (
                    plan,
                    execution_result,
                ),
                (
                    plan,
                ),
            )

            for args in attempts:

                try:

                    result = method(
                        *args
                    )

                    if hasattr(
                        result,
                        "__await__",
                    ):
                        result = await result

                    return self._normalize_verification(
                        result
                    )

                except TypeError:
                    continue

                except Exception:
                    logger.exception(
                        "[AutonomousExecution] "
                        "Verification failed."
                    )

                    return {
                        "verified": False,
                        "reason": (
                            "Verification "
                            "raised an exception."
                        ),
                    }

        return {
            "verified": True,
            "source": "executor",
        }

    @staticmethod
    def _normalize_verification(
        result: Any,
    ) -> Dict[str, Any]:

        if isinstance(
            result,
            bool,
        ):
            return {
                "verified": result
            }

        if isinstance(
            result,
            dict,
        ):
            output = dict(
                result
            )

            if "verified" not in output:

                if "success" in output:
                    output[
                        "verified"
                    ] = bool(
                        output[
                            "success"
                        ]
                    )
                else:
                    output[
                        "verified"
                    ] = True

            return output

        success = getattr(
            result,
            "success",
            None,
        )

        if success is not None:
            return {
                "verified": bool(
                    success
                ),
                "result": result,
            }

        return {
            "verified": True,
            "result": result,
        }

    # =========================================================
    # DYNAMIC REPLANNING
    # =========================================================

    async def _try_replan(
        self,
        plan: ExecutionPlan,
        context: Dict[str, Any],
        failure_reason: str,
    ) -> Optional[ExecutionPlan]:

        planner = self.planner

        if planner is None:
            return None

        method = getattr(
            planner,
            "dynamic_replan",
            None,
        )

        if not callable(method):
            return None

        failed_tasks = list(
            getattr(
                plan,
                "failed_tasks",
                [],
            )
            or []
        )

        completed_tasks = list(
            getattr(
                plan,
                "completed_tasks",
                [],
            )
            or []
        )

        failed_task = None

        if failed_tasks:
            failed_task = (
                plan.get_task(
                    failed_tasks[-1]
                )
            )

        try:

            result = method(
                goal=plan.goal,
                context=dict(
                    context
                ),
                failed_task=failed_task,
                failure_reason=failure_reason,
                previous_plan=plan,
            )

            if hasattr(
                result,
                "__await__",
            ):
                result = await result

            if isinstance(
                result,
                ExecutionPlan,
            ):
                return result

        except Exception:
            logger.exception(
                "[AutonomousExecution] "
                "Dynamic replanning failed."
            )

        return None

    # =========================================================
    # PLAN VALIDATION
    # =========================================================

    @staticmethod
    def _validate_plan(
        plan: ExecutionPlan,
    ) -> Optional[str]:

        if not plan.goal.strip():
            return (
                "Execution plan has no goal."
            )

        if not plan.tasks:
            return (
                "Execution plan contains no tasks."
            )

        task_ids = {
            task.id
            for task in plan.tasks
        }

        if len(task_ids) != len(
            plan.tasks
        ):
            return (
                "Execution plan contains "
                "duplicate task IDs."
            )

        for task in plan.tasks:

            for dependency in (
                task.depends_on
            ):

                if dependency not in task_ids:
                    return (
                        "Task "
                        f"{task.id} depends on "
                        f"unknown task "
                        f"{dependency}."
                    )

                if dependency == task.id:
                    return (
                        "Task "
                        f"{task.id} depends on itself."
                    )

        return None

    # =========================================================
    # SUCCESS / FAILURE
    # =========================================================

    @staticmethod
    def _execution_success(
        execution_result: Any,
        plan: ExecutionPlan,
    ) -> bool:

        if (
            getattr(
                plan,
                "status",
                "",
            )
            == "completed"
        ):
            return True

        if isinstance(
            execution_result,
            dict,
        ):
            if "success" in execution_result:
                return bool(
                    execution_result[
                        "success"
                    ]
                )

            status = str(
                execution_result.get(
                    "status",
                    "",
                )
            ).casefold()

            if status in {
                "completed",
                "success",
                "successful",
            }:
                return True

        return not bool(
            getattr(
                plan,
                "failed_tasks",
                [],
            )
        ) and getattr(
            plan,
            "is_complete",
            lambda: False,
        )()

    @staticmethod
    def _failure_reason(
        execution_result: Any,
        plan: ExecutionPlan,
    ) -> str:

        if isinstance(
            execution_result,
            dict,
        ):

            error = execution_result.get(
                "error"
            )

            if error:
                return str(
                    error
                )

        error = getattr(
            plan,
            "error",
            None,
        )

        if error:
            return str(
                error
            )

        failed_tasks = getattr(
            plan,
            "failed_tasks",
            [],
        )

        if failed_tasks:
            return (
                "Failed tasks: "
                + ", ".join(
                    map(
                        str,
                        failed_tasks,
                    )
                )
            )

        return (
            "Execution did not "
            "complete successfully."
        )

    # =========================================================
    # RESULT BUILDERS
    # =========================================================

    def _success(
        self,
        execution_result: Any,
        plan: ExecutionPlan,
        started: float,
        cycles: int,
        replans: int,
        verification: Dict[str, Any],
    ) -> AutonomousExecutionResult:

        elapsed = max(
            0.0,
            time.monotonic()
            - started,
        )

        return AutonomousExecutionResult(
            success=True,
            status="completed",
            cycles=cycles,
            completed_tasks=list(
                getattr(
                    plan,
                    "completed_tasks",
                    [],
                )
                or []
            ),
            failed_tasks=list(
                getattr(
                    plan,
                    "failed_tasks",
                    [],
                )
                or []
            ),
            skipped_tasks=list(
                getattr(
                    plan,
                    "skipped_tasks",
                    [],
                )
                or []
            ),
            task_outputs=dict(
                getattr(
                    plan,
                    "task_outputs",
                    {},
                )
                or {}
            ),
            elapsed_seconds=round(
                elapsed,
                3,
            ),
            replans=replans,
            metadata={
                "version": self.VERSION,
                "verification": verification,
                "executor_result": (
                    execution_result
                ),
            },
        )

    def _failure(
        self,
        status: str,
        error: str,
        started: float,
        plan: Optional[
            ExecutionPlan
        ] = None,
        execution_result: Any = None,
        cycles: int = 0,
        replans: int = 0,
        verification: Optional[
            Dict[str, Any]
        ] = None,
    ) -> AutonomousExecutionResult:

        elapsed = max(
            0.0,
            time.monotonic()
            - started,
        )

        return AutonomousExecutionResult(
            success=False,
            status=status,
            cycles=cycles,
            completed_tasks=list(
                getattr(
                    plan,
                    "completed_tasks",
                    [],
                )
                or []
            ),
            failed_tasks=list(
                getattr(
                    plan,
                    "failed_tasks",
                    [],
                )
                or []
            ),
            skipped_tasks=list(
                getattr(
                    plan,
                    "skipped_tasks",
                    [],
                )
                or []
            ),
            task_outputs=dict(
                getattr(
                    plan,
                    "task_outputs",
                    {},
                )
                or {}
            ),
            error=str(
                error
            ),
            elapsed_seconds=round(
                elapsed,
                3,
            ),
            replans=replans,
            metadata={
                "version": self.VERSION,
                "verification": (
                    verification
                    or {}
                ),
                "executor_result": (
                    execution_result
                ),
            },
        )

    # =========================================================
    # WORKFLOW CONTROL
    # =========================================================

    @staticmethod
    def _mark_timeout(
        plan: ExecutionPlan,
    ) -> None:

        try:
            plan.mark_failed(
                "Autonomous execution timeout."
            )
        except Exception:
            plan.status = "failed"
            plan.error = (
                "Autonomous execution timeout."
            )

    @staticmethod
    def _mark_cancelled(
        plan: ExecutionPlan,
    ) -> None:

        try:
            plan.mark_cancelled()
        except Exception:
            plan.status = "cancelled"

    @staticmethod
    def _workflow_id(
        plan: ExecutionPlan,
    ) -> str:

        return (
            f"aria-workflow-"
            f"{abs(hash(plan.goal))}-"
            f"{int(time.time() * 1000)}"
        )

    def cancel(
        self,
        workflow_id: str,
    ) -> bool:
        """
        Request cancellation through the canonical Executor.
        """

        workflow_id = str(
            workflow_id
        ).strip()

        cancel = getattr(
            self.executor,
            "cancel_workflow",
            None,
        )

        if not callable(cancel):
            return False

        try:
            cancel(
                workflow_id
            )

            self.statistics[
                "cancelled"
            ] += 1

            return True

        except Exception:
            logger.exception(
                "[AutonomousExecution] "
                "Cancellation failed."
            )

            return False

    def status(
        self,
        workflow_id: str,
    ) -> Optional[
        Dict[str, Any]
    ]:

        state = self.active_workflows.get(
            str(
                workflow_id
            ).strip()
        )

        if state is None:
            return None

        return dict(
            state
        )

    def health(
        self,
    ) -> Dict[str, Any]:

        return {
            "version": self.VERSION,
            "healthy": self.executor is not None,
            "executor_available": (
                self.executor is not None
            ),
            "planner_available": (
                self.planner is not None
            ),
            "verifier_available": (
                self.verifier is not None
            ),
            "active_workflows": len(
                self.active_workflows
            ),
            "max_cycles": self.max_cycles,
            "max_replans": self.max_replans,
            "timeout_seconds": (
                self.timeout_seconds
            ),
            "statistics": dict(
                self.statistics
            ),
        }

    def describe(
        self,
    ) -> Dict[str, Any]:

        return {
            "version": self.VERSION,
            "role": (
                "bounded autonomous "
                "execution controller"
            ),
            "uses_canonical_executor": True,
            "features": [
                "bounded autonomy",
                "execution monitoring",
                "verification",
                "dynamic replanning",
                "workflow timeout",
                "cycle limits",
                "replan limits",
                "cancellation",
                "execution state",
            ],
            "safety_limits": {
                "max_cycles": self.max_cycles,
                "max_replans": self.max_replans,
                "timeout_seconds": (
                    self.timeout_seconds
                ),
            },
        }


__all__ = [
    "AutonomousExecutionController",
    "AutonomousExecutionResult",
]