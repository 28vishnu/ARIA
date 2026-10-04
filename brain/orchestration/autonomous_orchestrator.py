"""
ARIA Autonomous Orchestrator
============================

Phase 1 - Step 17

Top-level coordination layer for ARIA.

Pipeline
--------
User request
    ↓
GoalManager
    ↓
PhasePlanner
    ↓
AutonomousExecutionController
    ↓
SelfCorrectionEngine
    ↓
ExperienceEngine
    ↓
ExperienceAdapter
    ↓
Goal completion / failure

Design principles
-----------------
- orchestration only
- no duplicate executor
- no duplicate planner
- bounded cycles
- deterministic control flow
- optional integrations
- safe failure handling
- observable state
- no direct LLM dependency
"""

from __future__ import annotations

import asyncio
import logging

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional


logger = logging.getLogger("aria")


# ============================================================================
# CONSTANTS
# ============================================================================

MAX_ORCHESTRATION_CYCLES = 5
MAX_REPLAN_ATTEMPTS = 3
MAX_HISTORY = 50

ORCHESTRATOR_STATES = {
    "idle",
    "planning",
    "executing",
    "verifying",
    "learning",
    "completed",
    "failed",
    "cancelled",
}


# ============================================================================
# HELPERS
# ============================================================================

def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _text(
    value: Any,
    limit: int = 4000,
) -> str:
    if value is None:
        return ""

    value = str(value).strip()

    if len(value) <= limit:
        return value

    return value[:limit] + "\n[TRUNCATED]"


def _as_dict(
    value: Any,
) -> Dict[str, Any]:
    """
    Convert common ARIA result objects into dictionaries.
    """

    if value is None:
        return {}

    if isinstance(
        value,
        dict,
    ):
        return dict(value)

    method = getattr(
        value,
        "to_dict",
        None,
    )

    if callable(method):

        try:
            result = method()

            if isinstance(
                result,
                dict,
            ):
                return result

        except Exception:
            pass

    result = {}

    for key in (
        "success",
        "status",
        "goal_id",
        "plan_id",
        "error",
        "message",
        "tasks",
        "completed_tasks",
        "failed_tasks",
        "verified",
        "verification",
        "corrections",
        "cycles",
        "duration_ms",
    ):

        if hasattr(
            value,
            key,
        ):
            result[key] = getattr(
                value,
                key,
            )

    return result


# ============================================================================
# RESULT MODEL
# ============================================================================

@dataclass
class OrchestrationResult:
    """
    Final result of one autonomous orchestration run.
    """

    goal_id: str = ""

    request: str = ""

    success: bool = False

    status: str = "failed"

    cycles: int = 0

    replans: int = 0

    plan: Dict[str, Any] = field(
        default_factory=dict
    )

    execution: Dict[str, Any] = field(
        default_factory=dict
    )

    verification: Dict[str, Any] = field(
        default_factory=dict
    )

    learning: Dict[str, Any] = field(
        default_factory=dict
    )

    corrections: List[
        Dict[str, Any]
    ] = field(
        default_factory=list
    )

    error: str = ""

    started_at: datetime = field(
        default_factory=_utc_now
    )

    finished_at: Optional[
        datetime
    ] = None

    def to_dict(self) -> Dict[str, Any]:

        return {
            "goal_id": self.goal_id,
            "request": self.request,
            "success": self.success,
            "status": self.status,
            "cycles": self.cycles,
            "replans": self.replans,
            "plan": dict(self.plan),
            "execution": dict(
                self.execution
            ),
            "verification": dict(
                self.verification
            ),
            "learning": dict(
                self.learning
            ),
            "corrections": list(
                self.corrections
            ),
            "error": self.error,
            "started_at": (
                self.started_at.isoformat()
            ),
            "finished_at": (
                self.finished_at.isoformat()
                if self.finished_at
                else None
            ),
        }


# ============================================================================
# ORCHESTRATOR
# ============================================================================

class AutonomousOrchestrator:
    """
    Coordinates ARIA's autonomous planning/execution lifecycle.

    Components are injected so the orchestrator does not create
    competing versions of the planner or executor.
    """

    def __init__(
        self,
        goal_manager=None,
        phase_planner=None,
        execution_controller=None,
        verification_engine=None,
        experience_engine=None,
        experience_adapter=None,
        self_correction_engine=None,
        max_cycles: int = MAX_ORCHESTRATION_CYCLES,
        max_replans: int = MAX_REPLAN_ATTEMPTS,
    ):
        self.goal_manager = goal_manager

        self.phase_planner = phase_planner

        self.execution_controller = (
            execution_controller
        )

        # Support either the Step 12 name or a direct verification
        # implementation supplied by the caller.
        self.verification_engine = (
            verification_engine
            or self_correction_engine
        )

        self.experience_engine = (
            experience_engine
        )

        self.experience_adapter = (
            experience_adapter
        )

        self.max_cycles = max(
            1,
            min(
                int(max_cycles),
                MAX_ORCHESTRATION_CYCLES,
            ),
        )

        self.max_replans = max(
            0,
            min(
                int(max_replans),
                MAX_REPLAN_ATTEMPTS,
            ),
        )

        self.state = "idle"

        self.current_goal_id = ""

        self.current_request = ""

        self.current_plan = None

        self.current_execution = None

        self.current_verification = None

        self._cancel_requested = False

        self._history: List[
            OrchestrationResult
        ] = []

        self.statistics = {
            "runs": 0,
            "successes": 0,
            "failures": 0,
            "cancelled": 0,
            "replans": 0,
            "corrections": 0,
            "experiences_recorded": 0,
        }

    # ========================================================================
    # STATE
    # ========================================================================

    def _set_state(
        self,
        state: str,
    ) -> None:

        if state not in ORCHESTRATOR_STATES:
            raise ValueError(
                f"Invalid orchestrator state: {state}"
            )

        self.state = state

    def cancel(self) -> None:
        """
        Request cancellation.

        The current executor is also asked to cancel when supported.
        """

        self._cancel_requested = True

        try:

            if self.execution_controller is not None:

                cancel_method = getattr(
                    self.execution_controller,
                    "cancel",
                    None,
                )

                if callable(cancel_method):
                    cancel_method()

        except Exception:

            logger.exception(
                "[AutonomousOrchestrator] "
                "Executor cancellation request failed."
            )

        self.state = "cancelled"

    def status(self) -> Dict[str, Any]:

        return {
            "state": self.state,
            "goal_id": self.current_goal_id,
            "request": self.current_request,
            "has_plan": (
                self.current_plan is not None
            ),
            "has_execution": (
                self.current_execution
                is not None
            ),
            "has_verification": (
                self.current_verification
                is not None
            ),
            "cancel_requested": (
                self._cancel_requested
            ),
        }

    # ========================================================================
    # GOAL
    # ========================================================================

    def _create_goal(
        self,
        request: str,
        goal_id: Optional[str] = None,
        goal_kwargs: Optional[
            Dict[str, Any]
        ] = None,
    ) -> Any:
        """
        Create or retrieve a GoalManager goal.
        """

        if self.goal_manager is None:
            return None

        if goal_id:

            goal = self.goal_manager.get(
                goal_id
            )

            if goal is not None:
                return goal

        kwargs = dict(
            goal_kwargs or {}
        )

        creator = getattr(
            self.goal_manager,
            "from_request",
            None,
        )

        if callable(creator):
            return creator(
                request,
                **kwargs,
            )

        creator = getattr(
            self.goal_manager,
            "create_goal",
            None,
        )

        if callable(creator):
            return creator(
                request=request,
                **kwargs,
            )

        return None

    # ========================================================================
    # PLANNING
    # ========================================================================

    async def _build_plan(
        self,
        request: str,
        goal: Any,
        context: Optional[
            Dict[str, Any]
        ] = None,
    ) -> Any:
        """
        Use the existing PhasePlanner.
        """

        if self.phase_planner is None:
            raise RuntimeError(
                "PhasePlanner is not configured."
            )

        planner = self.phase_planner

        # Preferred API.
        for method_name in (
            "create_plan",
            "plan",
            "build_plan",
            "decompose",
        ):

            method = getattr(
                planner,
                method_name,
                None,
            )

            if not callable(method):
                continue

            attempts = [
                {
                    "request": request,
                    "goal": goal,
                    "context": context or {},
                },
                {
                    "request": request,
                    "context": context or {},
                },
                {
                    "goal": goal,
                    "context": context or {},
                },
                {
                    "request": request,
                },
            ]

            for kwargs in attempts:

                try:

                    result = method(
                        **kwargs
                    )

                    if hasattr(
                        result,
                        "__await__",
                    ):
                        result = await result

                    if result is not None:
                        return result

                except TypeError:
                    continue

        raise RuntimeError(
            "PhasePlanner does not expose a supported planning API."
        )

    # ========================================================================
    # EXECUTION
    # ========================================================================

    async def _execute_plan(
        self,
        plan: Any,
        goal: Any,
        context: Optional[
            Dict[str, Any]
        ] = None,
    ) -> Any:
        """
        Use the existing AutonomousExecutionController.
        """

        if self.execution_controller is None:
            raise RuntimeError(
                "AutonomousExecutionController "
                "is not configured."
            )

        controller = (
            self.execution_controller
        )

        # Preferred controller API.
        method = getattr(
            controller,
            "execute",
            None,
        )

        if callable(method):

            attempts = [
                {
                    "plan": plan,
                    "goal": goal,
                    "context": context or {},
                },
                {
                    "plan": plan,
                    "context": context or {},
                },
                {
                    "plan": plan,
                },
            ]

            for kwargs in attempts:

                try:

                    result = method(
                        **kwargs
                    )

                    if hasattr(
                        result,
                        "__await__",
                    ):
                        result = await result

                    return result

                except TypeError:
                    continue

        raise RuntimeError(
            "AutonomousExecutionController "
            "does not expose a supported execute API."
        )

    # ========================================================================
    # VERIFICATION
    # ========================================================================

    async def _verify(
        self,
        plan: Any,
        execution: Any,
        goal: Any,
    ) -> Dict[str, Any]:
        """
        Run available verification/self-correction logic.

        Verification failures do not immediately mean the entire
        orchestration failed; the result determines whether replanning
        is appropriate.
        """

        if self.verification_engine is None:

            return {
                "verified": True,
                "status": "not_configured",
                "issues": [],
                "corrections": [],
            }

        verifier = (
            self.verification_engine
        )

        for method_name in (
            "verify",
            "verify_plan",
            "check",
        ):

            method = getattr(
                verifier,
                method_name,
                None,
            )

            if not callable(method):
                continue

            attempts = [
                {
                    "plan": plan,
                    "execution_result": execution,
                    "goal": goal,
                },
                {
                    "plan": plan,
                    "execution": execution,
                },
                {
                    "plan": plan,
                },
            ]

            for kwargs in attempts:

                try:

                    result = method(
                        **kwargs
                    )

                    if hasattr(
                        result,
                        "__await__",
                    ):
                        result = await result

                    result = _as_dict(
                        result
                    )

                    if not result:
                        result = {
                            "verified": True,
                            "status": "passed",
                            "issues": [],
                            "corrections": [],
                        }

                    # Normalize common result naming.
                    if (
                        "verified"
                        not in result
                    ):

                        status = str(
                            result.get(
                                "status",
                                "",
                            )
                        ).lower()

                        result[
                            "verified"
                        ] = status not in {
                            "failed",
                            "invalid",
                            "rejected",
                        }

                    return result

                except TypeError:
                    continue

                except Exception:

                    logger.exception(
                        "[AutonomousOrchestrator] "
                        "Verification failed."
                    )

                    return {
                        "verified": False,
                        "status": "error",
                        "issues": [
                            "Verification engine raised an exception."
                        ],
                        "corrections": [],
                    }

        return {
            "verified": True,
            "status": "not_supported",
            "issues": [],
            "corrections": [],
        }

    # ========================================================================
    # LEARNING
    # ========================================================================

    async def _record_experience(
        self,
        execution: Any,
        plan: Any,
        goal: Any,
        verification: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Record the outcome in ExperienceEngine when available.
        """

        if self.experience_engine is None:
            return {
                "recorded": False
            }

        try:

            record = getattr(
                self.experience_engine,
                "record",
                None,
            )

            if not callable(record):

                return {
                    "recorded": False,
                    "reason": (
                        "ExperienceEngine has no record method."
                    ),
                }

            corrections = verification.get(
                "corrections",
                [],
            )

            correction_text = ""

            if corrections:
                correction_text = _text(
                    corrections,
                    3000,
                )

            outcome = await record(
                execution=execution,
                plan=plan,
                goal=goal,
                verification=verification,
                correction=correction_text,
            )

            self.statistics[
                "experiences_recorded"
            ] += 1

            return {
                "recorded": True,
                "experience": _as_dict(
                    outcome
                ),
            }

        except Exception:

            logger.exception(
                "[AutonomousOrchestrator] "
                "Experience recording failed."
            )

            return {
                "recorded": False,
                "error": (
                    "Experience recording failed."
                ),
            }

    # ========================================================================
    # ADAPTATION
    # ========================================================================

    async def _adaptation_hints(
        self,
        plan: Any,
        goal: Any,
    ) -> Dict[str, Any]:
        """
        Obtain experience-driven planning hints.
        """

        if self.experience_adapter is None:
            return {}

        task_type = ""

        action_name = ""

        # Attempt to infer from plan/task information.
        plan_dict = _as_dict(
            plan
        )

        task_type = _text(
            plan_dict.get(
                "task_type",
                "",
            ),
            100,
        )

        action_name = _text(
            plan_dict.get(
                "action_name",
                "",
            ),
            300,
        )

        try:

            method = getattr(
                self.experience_adapter,
                "planning_hints",
                None,
            )

            if callable(method):

                result = method(
                    task_type=task_type,
                    action_name=action_name,
                )

                if hasattr(
                    result,
                    "__await__",
                ):
                    result = await result

                return _as_dict(
                    result
                )

        except Exception:

            logger.exception(
                "[AutonomousOrchestrator] "
                "Experience adaptation failed."
            )

        return {}

    # ========================================================================
    # REPLAN DECISION
    # ========================================================================

    def _should_replan(
        self,
        verification: Dict[str, Any],
        replans: int,
    ) -> bool:
        """
        Decide whether another planning cycle is justified.
        """

        if replans >= self.max_replans:
            return False

        if self._cancel_requested:
            return False

        verified = bool(
            verification.get(
                "verified",
                True,
            )
        )

        if verified:
            return False

        status = str(
            verification.get(
                "status",
                "",
            )
        ).lower()

        if status in {
            "cancelled",
            "fatal",
            "terminal",
        }:
            return False

        issues = verification.get(
            "issues",
            [],
        )

        corrections = verification.get(
            "corrections",
            [],
        )

        return bool(
            issues
            or corrections
            or status
            in {
                "failed",
                "invalid",
                "rejected",
                "error",
            }
        )

    # ========================================================================
    # MAIN RUN
    # ========================================================================

    async def run(
        self,
        request: str,
        *,
        goal_id: Optional[
            str
        ] = None,
        context: Optional[
            Dict[str, Any]
        ] = None,
        goal_kwargs: Optional[
            Dict[str, Any]
        ] = None,
    ) -> OrchestrationResult:
        """
        Execute one bounded autonomous orchestration run.
        """

        request = _text(
            request,
            4000,
        )

        if not request:
            raise ValueError(
                "Request cannot be empty."
            )

        started_at = _utc_now()

        result = OrchestrationResult(
            request=request,
            started_at=started_at,
        )

        self.statistics[
            "runs"
        ] += 1

        self.current_request = request

        self._cancel_requested = False

        self.current_plan = None

        self.current_execution = None

        self.current_verification = None

        try:

            # --------------------------------------------------------
            # GOAL
            # --------------------------------------------------------

            goal = self._create_goal(
                request=request,
                goal_id=goal_id,
                goal_kwargs=goal_kwargs,
            )

            if goal is not None:

                result.goal_id = _text(
                    getattr(
                        goal,
                        "goal_id",
                        "",
                    ),
                    200,
                )

                self.current_goal_id = (
                    result.goal_id
                )

                try:

                    activate = getattr(
                        self.goal_manager,
                        "activate",
                        None,
                    )

                    if callable(activate):
                        activate(
                            result.goal_id
                        )

                except Exception:

                    logger.exception(
                        "[AutonomousOrchestrator] "
                        "Goal activation failed."
                    )

            # --------------------------------------------------------
            # MAIN CYCLE
            # --------------------------------------------------------

            replans = 0

            for cycle in range(
                1,
                self.max_cycles + 1,
            ):

                result.cycles = cycle

                if self._cancel_requested:

                    result.status = (
                        "cancelled"
                    )

                    result.error = (
                        "Orchestration was cancelled."
                    )

                    self.statistics[
                        "cancelled"
                    ] += 1

                    break

                # ----------------------------------------------------
                # ADAPTATION
                # ----------------------------------------------------

                adaptation = (
                    await self._adaptation_hints(
                        self.current_plan,
                        goal,
                    )
                )

                # ----------------------------------------------------
                # PLANNING
                # ----------------------------------------------------

                self._set_state(
                    "planning"
                )

                planning_context = dict(
                    context or {}
                )

                if adaptation:
                    planning_context[
                        "experience_hints"
                    ] = adaptation

                if goal is not None:
                    planning_context[
                        "goal_context"
                    ] = {
                        "goal_id": result.goal_id,
                        "objective": getattr(
                            goal,
                            "objective",
                            request,
                        ),
                        "intent": getattr(
                            goal,
                            "intent",
                            "general",
                        ),
                        "constraints": list(
                            getattr(
                                goal,
                                "constraints",
                                [],
                            )
                        ),
                    }

                plan = await self._build_plan(
                    request=request,
                    goal=goal,
                    context=planning_context,
                )

                self.current_plan = plan

                result.plan = _as_dict(
                    plan
                )

                # ----------------------------------------------------
                # EXECUTION
                # ----------------------------------------------------

                self._set_state(
                    "executing"
                )

                execution = await self._execute_plan(
                    plan=plan,
                    goal=goal,
                    context=planning_context,
                )

                self.current_execution = (
                    execution
                )

                result.execution = _as_dict(
                    execution
                )

                # ----------------------------------------------------
                # VERIFICATION
                # ----------------------------------------------------

                self._set_state(
                    "verifying"
                )

                verification = await self._verify(
                    plan=plan,
                    execution=execution,
                    goal=goal,
                )

                self.current_verification = (
                    verification
                )

                result.verification = dict(
                    verification
                )

                corrections = verification.get(
                    "corrections",
                    [],
                )

                if isinstance(
                    corrections,
                    list,
                ):
                    result.corrections.extend(
                        [
                            _as_dict(
                                correction
                            )
                            for correction in corrections
                        ]
                    )

                    self.statistics[
                        "corrections"
                    ] += len(
                        corrections
                    )

                # ----------------------------------------------------
                # LEARNING
                # ----------------------------------------------------

                self._set_state(
                    "learning"
                )

                learning = (
                    await self._record_experience(
                        execution=execution,
                        plan=plan,
                        goal=goal,
                        verification=verification,
                    )
                )

                result.learning = learning

                # ----------------------------------------------------
                # SUCCESS
                # ----------------------------------------------------

                if bool(
                    verification.get(
                        "verified",
                        False,
                    )
                ):

                    result.success = True

                    result.status = (
                        "completed"
                    )

                    self._set_state(
                        "completed"
                    )

                    if goal is not None:

                        try:

                            complete = getattr(
                                self.goal_manager,
                                "complete",
                                None,
                            )

                            if callable(complete):
                                complete(
                                    result.goal_id
                                )

                        except Exception:

                            logger.exception(
                                "[AutonomousOrchestrator] "
                                "Goal completion update failed."
                            )

                    break

                # ----------------------------------------------------
                # REPLAN
                # ----------------------------------------------------

                if self._should_replan(
                    verification,
                    replans,
                ):

                    replans += 1

                    result.replans = (
                        replans
                    )

                    self.statistics[
                        "replans"
                    ] += 1

                    continue

                # No safe replan available.
                result.success = False

                result.status = "failed"

                result.error = _text(
                    verification.get(
                        "error",
                        "Verification failed.",
                    ),
                    3000,
                )

                break

            # --------------------------------------------------------
            # MAX CYCLES
            # --------------------------------------------------------

            if (
                result.status
                not in {
                    "completed",
                    "cancelled",
                }
                and result.cycles
                >= self.max_cycles
            ):

                result.status = (
                    "failed"
                )

                if not result.error:
                    result.error = (
                        "Maximum orchestration "
                        "cycles reached."
                    )

            if result.success:

                self.statistics[
                    "successes"
                ] += 1

            else:

                self.statistics[
                    "failures"
                ] += 1

                if (
                    goal is not None
                    and result.status
                    == "failed"
                ):

                    try:

                        fail = getattr(
                            self.goal_manager,
                            "fail",
                            None,
                        )

                        if callable(fail):
                            fail(
                                result.goal_id,
                                result.error,
                            )

                    except Exception:

                        logger.exception(
                            "[AutonomousOrchestrator] "
                            "Goal failure update failed."
                        )

        except asyncio.CancelledError:

            self._set_state(
                "cancelled"
            )

            result.status = (
                "cancelled"
            )

            result.error = (
                "Orchestration task cancelled."
            )

            self.statistics[
                "cancelled"
            ] += 1

            raise

        except Exception as exc:

            logger.exception(
                "[AutonomousOrchestrator] "
                "Orchestration failed."
            )

            result.success = False

            result.status = (
                "failed"
            )

            result.error = _text(
                exc,
                3000,
            )

            self._set_state(
                "failed"
            )

            self.statistics[
                "failures"
            ] += 1

            if (
                goal is not None
                and result.goal_id
            ):

                try:

                    fail = getattr(
                        self.goal_manager,
                        "fail",
                        None,
                    )

                    if callable(fail):
                        fail(
                            result.goal_id,
                            result.error,
                        )

                except Exception:

                    logger.exception(
                        "[AutonomousOrchestrator] "
                        "Failed to update goal after exception."
                    )

        finally:

            result.finished_at = (
                _utc_now()
            )

            if (
                result.status
                == "completed"
            ):
                self.state = (
                    "completed"
                )

            elif (
                result.status
                == "cancelled"
            ):
                self.state = (
                    "cancelled"
                )

            else:
                self.state = (
                    "failed"
                )

            self._history.append(
                result
            )

            if (
                len(self._history)
                > MAX_HISTORY
            ):
                self._history = (
                    self._history[
                        -MAX_HISTORY:
                    ]
                )

        return result

    # ========================================================================
    # HISTORY
    # ========================================================================

    def history(
        self,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        limit = max(
            1,
            min(
                int(limit),
                MAX_HISTORY,
            ),
        )

        return [
            result.to_dict()
            for result in reversed(
                self._history[-limit:]
            )
        ]

    # ========================================================================
    # HEALTH
    # ========================================================================

    def health(self) -> Dict[str, Any]:

        return {
            "component": (
                "autonomous_orchestrator"
            ),
            "status": "healthy",
            "state": self.state,
            "goal_manager": (
                self.goal_manager is not None
            ),
            "phase_planner": (
                self.phase_planner is not None
            ),
            "execution_controller": (
                self.execution_controller
                is not None
            ),
            "verification_engine": (
                self.verification_engine
                is not None
            ),
            "experience_engine": (
                self.experience_engine
                is not None
            ),
            "experience_adapter": (
                self.experience_adapter
                is not None
            ),
            "statistics": dict(
                self.statistics
            ),
        }

    def describe(self) -> Dict[str, Any]:

        return {
            "component": (
                "AutonomousOrchestrator"
            ),
            "purpose": (
                "Coordinate goals, planning, "
                "execution, verification and learning."
            ),
            "llm_required": False,
            "max_cycles": self.max_cycles,
            "max_replans": self.max_replans,
            "pipeline": [
                "GoalManager",
                "PhasePlanner",
                "AutonomousExecutionController",
                "SelfCorrectionEngine",
                "ExperienceEngine",
                "ExperienceAdapter",
            ],
            "features": [
                "bounded autonomous cycles",
                "goal lifecycle coordination",
                "planning",
                "execution",
                "verification",
                "self-correction",
                "experience recording",
                "experience-driven replanning",
                "cancellation",
                "history",
                "health monitoring",
            ],
        }