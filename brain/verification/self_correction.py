"""
ARIA Phase 1 — Step 12: Verification & Self-Correction.

Provides bounded post-execution verification and correction signals.

Responsibilities:
- verify ExecutionPlan completion;
- inspect failed tasks and outputs;
- detect incomplete/empty results;
- compare expected task state with actual state;
- produce structured correction recommendations;
- remain deterministic and side-effect free;
- integrate with Step 11 AutonomousExecutionController.

This module does NOT:
- execute tools;
- modify files;
- call an LLM;
- retry tasks directly;
- perform unlimited self-correction.

Correction decisions are returned to the execution/planning layer.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

from brain.plan import ExecutionPlan

logger = logging.getLogger("aria")


@dataclass(frozen=True)
class VerificationIssue:
    """One detected execution or result-quality issue."""

    code: str
    message: str
    severity: str = "warning"
    task_id: Optional[str] = None
    recoverable: bool = True
    evidence: Dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
            "task_id": self.task_id,
            "recoverable": self.recoverable,
            "evidence": dict(
                self.evidence
            ),
        }


@dataclass(frozen=True)
class CorrectionAction:
    """Recommended correction action."""

    action: str
    reason: str
    task_id: Optional[str] = None
    priority: int = 1
    input: Dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "reason": self.reason,
            "task_id": self.task_id,
            "priority": self.priority,
            "input": dict(
                self.input
            ),
        }


@dataclass
class VerificationResult:
    """Complete verification result."""

    verified: bool

    status: str

    confidence: float = 0.0

    issues: List[
        VerificationIssue
    ] = field(
        default_factory=list
    )

    corrections: List[
        CorrectionAction
    ] = field(
        default_factory=list
    )

    completed_tasks: List[str] = field(
        default_factory=list
    )

    failed_tasks: List[str] = field(
        default_factory=list
    )

    metadata: Dict[str, Any] = field(
        default_factory=dict
    )

    @property
    def recoverable(self) -> bool:
        return any(
            issue.recoverable
            for issue in self.issues
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verified": self.verified,
            "status": self.status,
            "confidence": self.confidence,
            "issues": [
                issue.to_dict()
                for issue in self.issues
            ],
            "corrections": [
                action.to_dict()
                for action in self.corrections
            ],
            "completed_tasks": list(
                self.completed_tasks
            ),
            "failed_tasks": list(
                self.failed_tasks
            ),
            "recoverable": self.recoverable,
            "metadata": dict(
                self.metadata
            ),
        }


class SelfCorrectionEngine:
    """
    Bounded verification and self-correction engine.

    The engine observes execution state and produces correction advice.
    It never performs the correction itself.

    Architecture:

        ExecutionPlan
             ↓
        Verify Structure
             ↓
        Verify Tasks
             ↓
        Verify Outputs
             ↓
        Detect Issues
             ↓
        Generate Correction Actions
             ↓
        Autonomous Controller / Planner
    """

    VERSION = (
        "PHASE1-SELF-CORRECTION-20261004"
    )

    MAX_ISSUES = 32
    MAX_CORRECTIONS = 16

    def __init__(
        self,
        max_issues: int = MAX_ISSUES,
        max_corrections: int = MAX_CORRECTIONS,
    ) -> None:

        self.max_issues = max(
            1,
            min(
                100,
                int(max_issues),
            ),
        )

        self.max_corrections = max(
            1,
            min(
                50,
                int(max_corrections),
            ),
        )

        self.statistics = {
            "verifications": 0,
            "verified": 0,
            "failed": 0,
            "issues": 0,
            "corrections": 0,
        }

    # =========================================================
    # PUBLIC VERIFICATION API
    # =========================================================

    async def verify_plan(
        self,
        plan: ExecutionPlan,
        execution_result: Any = None,
        context: Optional[
            Dict[str, Any]
        ] = None,
    ) -> Dict[str, Any]:
        """
        Verify a completed or partially completed ExecutionPlan.

        Returns a dictionary for direct compatibility with
        AutonomousExecutionController._verify().
        """

        result = self.verify(
            plan=plan,
            execution_result=execution_result,
            context=context,
        )

        return result.to_dict()

    def verify(
        self,
        plan: ExecutionPlan,
        execution_result: Any = None,
        context: Optional[
            Dict[str, Any]
        ] = None,
    ) -> VerificationResult:

        self.statistics[
            "verifications"
        ] += 1

        context = dict(
            context or {}
        )

        if not isinstance(
            plan,
            ExecutionPlan,
        ):
            self.statistics[
                "failed"
            ] += 1

            return VerificationResult(
                verified=False,
                status="invalid_plan",
                confidence=0.0,
                issues=[
                    VerificationIssue(
                        code="invalid_plan",
                        message=(
                            "Verification requires "
                            "an ExecutionPlan."
                        ),
                        severity="critical",
                        recoverable=False,
                    )
                ],
            )

        issues: List[
            VerificationIssue
        ] = []

        completed = self._completed_tasks(
            plan
        )

        failed = self._failed_tasks(
            plan
        )

        issues.extend(
            self._verify_structure(
                plan
            )
        )

        issues.extend(
            self._verify_task_state(
                plan
            )
        )

        issues.extend(
            self._verify_dependencies(
                plan
            )
        )

        issues.extend(
            self._verify_outputs(
                plan,
                execution_result,
            )
        )

        issues.extend(
            self._verify_executor_result(
                execution_result
            )
        )

        issues.extend(
            self._verify_context(
                plan,
                context,
            )
        )

        issues = self._deduplicate_issues(
            issues
        )[
            : self.max_issues
        ]

        corrections = (
            self._generate_corrections(
                plan,
                issues,
            )
        )[
            : self.max_corrections
        ]

        verified = not any(
            issue.severity
            in {
                "critical",
                "error",
            }
            for issue in issues
        )

        # A warning alone does not fail verification.
        if verified and not issues:
            status = "verified"
            confidence = 0.95

        elif verified:
            status = "verified_with_warnings"
            confidence = 0.80

        elif corrections:
            status = "correction_required"
            confidence = 0.35

        else:
            status = "verification_failed"
            confidence = 0.10

        if verified:
            self.statistics[
                "verified"
            ] += 1
        else:
            self.statistics[
                "failed"
            ] += 1

        self.statistics[
            "issues"
        ] += len(issues)

        self.statistics[
            "corrections"
        ] += len(corrections)

        return VerificationResult(
            verified=verified,
            status=status,
            confidence=confidence,
            issues=issues,
            corrections=corrections,
            completed_tasks=completed,
            failed_tasks=failed,
            metadata={
                "version": self.VERSION,
                "issue_count": len(
                    issues
                ),
                "correction_count": len(
                    corrections
                ),
                "execution_status": (
                    getattr(
                        plan,
                        "status",
                        None,
                    )
                ),
            },
        )

    # =========================================================
    # STRUCTURAL VERIFICATION
    # =========================================================

    def _verify_structure(
        self,
        plan: ExecutionPlan,
    ) -> List[
        VerificationIssue
    ]:

        issues: List[
            VerificationIssue
        ] = []

        if not plan.goal.strip():
            issues.append(
                VerificationIssue(
                    code="missing_goal",
                    message=(
                        "Execution plan has "
                        "no goal."
                    ),
                    severity="critical",
                    recoverable=False,
                )
            )

        if not plan.tasks:
            issues.append(
                VerificationIssue(
                    code="empty_plan",
                    message=(
                        "Execution plan "
                        "contains no tasks."
                    ),
                    severity="critical",
                    recoverable=False,
                )
            )

            return issues

        task_ids = [
            task.id
            for task in plan.tasks
        ]

        seen: Set[str] = set()

        for task_id in task_ids:

            if not task_id:
                issues.append(
                    VerificationIssue(
                        code="empty_task_id",
                        message=(
                            "A task has an "
                            "empty ID."
                        ),
                        severity="critical",
                        recoverable=False,
                    )
                )
                continue

            if task_id in seen:
                issues.append(
                    VerificationIssue(
                        code="duplicate_task_id",
                        message=(
                            f"Duplicate task "
                            f"ID: {task_id}."
                        ),
                        severity="critical",
                        task_id=task_id,
                        recoverable=False,
                    )
                )

            seen.add(
                task_id
            )

        return issues

    # =========================================================
    # TASK STATE VERIFICATION
    # =========================================================

    def _verify_task_state(
        self,
        plan: ExecutionPlan,
    ) -> List[
        VerificationIssue
    ]:

        issues: List[
            VerificationIssue
        ] = []

        for task in plan.tasks:

            status = str(
                getattr(
                    task,
                    "status",
                    "",
                )
                or ""
            ).casefold()

            if status in {
                "failed",
                "error",
                "failure",
            }:

                issues.append(
                    VerificationIssue(
                        code="task_failed",
                        message=(
                            f"Task {task.id} "
                            "failed."
                        ),
                        severity="error",
                        task_id=task.id,
                        recoverable=True,
                        evidence={
                            "status": status,
                            "error": getattr(
                                task,
                                "error",
                                None,
                            ),
                        },
                    )
                )

            elif status in {
                "cancelled",
                "canceled",
            }:

                issues.append(
                    VerificationIssue(
                        code="task_cancelled",
                        message=(
                            f"Task {task.id} "
                            "was cancelled."
                        ),
                        severity="error",
                        task_id=task.id,
                        recoverable=True,
                    )
                )

            elif status in {
                "pending",
                "queued",
                "waiting",
                "running",
            }:

                issues.append(
                    VerificationIssue(
                        code="task_incomplete",
                        message=(
                            f"Task {task.id} "
                            "did not reach a "
                            "terminal state."
                        ),
                        severity="error",
                        task_id=task.id,
                        recoverable=True,
                        evidence={
                            "status": status
                        },
                    )
                )

        return issues

    # =========================================================
    # DEPENDENCY VERIFICATION
    # =========================================================

    def _verify_dependencies(
        self,
        plan: ExecutionPlan,
    ) -> List[
        VerificationIssue
    ]:

        issues: List[
            VerificationIssue
        ] = []

        task_map = {
            task.id: task
            for task in plan.tasks
        }

        for task in plan.tasks:

            for dependency in (
                task.depends_on
            ):

                if dependency not in task_map:

                    issues.append(
                        VerificationIssue(
                            code=(
                                "missing_dependency"
                            ),
                            message=(
                                f"Task {task.id} "
                                f"depends on missing "
                                f"task {dependency}."
                            ),
                            severity="critical",
                            task_id=task.id,
                            recoverable=False,
                            evidence={
                                "dependency": (
                                    dependency
                                )
                            },
                        )
                    )

                    continue

                dependency_task = (
                    task_map[
                        dependency
                    ]
                )

                dependency_status = str(
                    getattr(
                        dependency_task,
                        "status",
                        "",
                    )
                    or ""
                ).casefold()

                if dependency_status in {
                    "failed",
                    "error",
                    "failure",
                    "cancelled",
                    "canceled",
                }:

                    task_status = str(
                        getattr(
                            task,
                            "status",
                            "",
                        )
                        or ""
                    ).casefold()

                    if task_status in {
                        "completed",
                        "success",
                        "successful",
                    }:

                        issues.append(
                            VerificationIssue(
                                code=(
                                    "invalid_dependency_completion"
                                ),
                                message=(
                                    f"Task {task.id} "
                                    "completed even "
                                    "though a dependency "
                                    "failed."
                                ),
                                severity="error",
                                task_id=task.id,
                                recoverable=True,
                            )
                        )

        cycle = self._find_cycle(
            plan
        )

        if cycle:

            issues.append(
                VerificationIssue(
                    code="dependency_cycle",
                    message=(
                        "Execution plan contains "
                        "a dependency cycle."
                    ),
                    severity="critical",
                    recoverable=False,
                    evidence={
                        "cycle": cycle
                    },
                )
            )

        return issues

    def _find_cycle(
        self,
        plan: ExecutionPlan,
    ) -> List[str]:

        task_map = {
            task.id: task
            for task in plan.tasks
        }

        visiting: Set[str] = set()
        visited: Set[str] = set()
        stack: List[str] = []

        def visit(
            task_id: str,
        ) -> Optional[
            List[str]
        ]:

            if task_id in visiting:

                try:
                    start = stack.index(
                        task_id
                    )
                    return (
                        stack[
                            start:
                        ]
                        + [task_id]
                    )
                except ValueError:
                    return [
                        task_id
                    ]

            if task_id in visited:
                return None

            visiting.add(
                task_id
            )
            stack.append(
                task_id
            )

            task = task_map.get(
                task_id
            )

            if task is not None:

                for dependency in (
                    task.depends_on
                ):

                    if dependency not in task_map:
                        continue

                    cycle = visit(
                        dependency
                    )

                    if cycle:
                        return cycle

            stack.pop()
            visiting.remove(
                task_id
            )
            visited.add(
                task_id
            )

            return None

        for task_id in task_map:

            cycle = visit(
                task_id
            )

            if cycle:
                return cycle

        return []

    # =========================================================
    # OUTPUT VERIFICATION
    # =========================================================

    def _verify_outputs(
        self,
        plan: ExecutionPlan,
        execution_result: Any,
    ) -> List[
        VerificationIssue
    ]:

        issues: List[
            VerificationIssue
        ] = []

        outputs = getattr(
            plan,
            "task_outputs",
            {},
        ) or {}

        if not isinstance(
            outputs,
            dict,
        ):
            outputs = {}

        for task in plan.tasks:

            status = str(
                getattr(
                    task,
                    "status",
                    "",
                )
                or ""
            ).casefold()

            if status not in {
                "completed",
                "success",
                "successful",
            }:
                continue

            if task.id not in outputs:
                issues.append(
                    VerificationIssue(
                        code="missing_output",
                        message=(
                            f"Task {task.id} "
                            "is marked completed "
                            "but has no recorded "
                            "output."
                        ),
                        severity="warning",
                        task_id=task.id,
                        recoverable=True,
                    )
                )
                continue

            output = outputs.get(
                task.id
            )

            if output is None:
                issues.append(
                    VerificationIssue(
                        code="null_output",
                        message=(
                            f"Task {task.id} "
                            "returned no output."
                        ),
                        severity="warning",
                        task_id=task.id,
                        recoverable=True,
                    )
                )

            elif isinstance(
                output,
                str,
            ) and not output.strip():

                issues.append(
                    VerificationIssue(
                        code="empty_output",
                        message=(
                            f"Task {task.id} "
                            "returned an empty "
                            "output."
                        ),
                        severity="warning",
                        task_id=task.id,
                        recoverable=True,
                    )
                )

        # Inspect common executor result structures.
        if isinstance(
            execution_result,
            dict,
        ):

            result_error = (
                execution_result.get(
                    "error"
                )
            )

            if result_error:
                issues.append(
                    VerificationIssue(
                        code="executor_error",
                        message=str(
                            result_error
                        ),
                        severity="error",
                        recoverable=True,
                    )
                )

        return issues

    # =========================================================
    # EXECUTOR RESULT VERIFICATION
    # =========================================================

    def _verify_executor_result(
        self,
        execution_result: Any,
    ) -> List[
        VerificationIssue
    ]:

        if execution_result is None:
            return []

        issues: List[
            VerificationIssue
        ] = []

        if isinstance(
            execution_result,
            dict,
        ):

            status = str(
                execution_result.get(
                    "status",
                    "",
                )
                or ""
            ).casefold()

            success = (
                execution_result.get(
                    "success"
                )
            )

            if success is False:
                issues.append(
                    VerificationIssue(
                        code="executor_reported_failure",
                        message=(
                            "Executor reported "
                            "unsuccessful execution."
                        ),
                        severity="error",
                        recoverable=True,
                        evidence={
                            "status": status
                        },
                    )
                )

            elif status in {
                "failed",
                "error",
                "failure",
                "cancelled",
                "canceled",
            }:

                issues.append(
                    VerificationIssue(
                        code="executor_terminal_failure",
                        message=(
                            f"Executor ended "
                            f"with status "
                            f"{status}."
                        ),
                        severity="error",
                        recoverable=True,
                    )
                )

        return issues

    # =========================================================
    # CONTEXT VERIFICATION
    # =========================================================

    def _verify_context(
        self,
        plan: ExecutionPlan,
        context: Dict[str, Any],
    ) -> List[
        VerificationIssue
    ]:

        issues: List[
            VerificationIssue
        ] = []

        if not isinstance(
            context,
            dict,
        ):
            return issues

        expected_goal = context.get(
            "expected_goal"
        )

        if (
            expected_goal
            and str(
                expected_goal
            ).strip().casefold()
            != plan.goal.strip().casefold()
        ):

            issues.append(
                VerificationIssue(
                    code="goal_mismatch",
                    message=(
                        "Execution goal does "
                        "not match the expected "
                        "goal."
                    ),
                    severity="error",
                    recoverable=True,
                    evidence={
                        "expected": expected_goal,
                        "actual": plan.goal,
                    },
                )
            )

        return issues

    # =========================================================
    # CORRECTION GENERATION
    # =========================================================

    def _generate_corrections(
        self,
        plan: ExecutionPlan,
        issues: Sequence[
            VerificationIssue
        ],
    ) -> List[
        CorrectionAction
    ]:

        corrections: List[
            CorrectionAction
        ] = []

        for issue in issues:

            if not issue.recoverable:
                continue

            if issue.code == "task_failed":

                corrections.append(
                    CorrectionAction(
                        action="retry_task",
                        reason=issue.message,
                        task_id=issue.task_id,
                        priority=10,
                        input={
                            "failed_task": (
                                issue.task_id
                            ),
                            "bounded_retry": True,
                        },
                    )
                )

            elif issue.code in {
                "task_cancelled",
                "task_incomplete",
            }:

                corrections.append(
                    CorrectionAction(
                        action="resume_task",
                        reason=issue.message,
                        task_id=issue.task_id,
                        priority=9,
                    )
                )

            elif issue.code in {
                "missing_output",
                "null_output",
                "empty_output",
            }:

                corrections.append(
                    CorrectionAction(
                        action="reexecute_task",
                        reason=issue.message,
                        task_id=issue.task_id,
                        priority=8,
                    )
                )

            elif issue.code in {
                "executor_error",
                "executor_reported_failure",
                "executor_terminal_failure",
            }:

                corrections.append(
                    CorrectionAction(
                        action="replan",
                        reason=issue.message,
                        priority=10,
                        input={
                            "scope": "failed_branch"
                        },
                    )
                )

            elif issue.code == "goal_mismatch":

                corrections.append(
                    CorrectionAction(
                        action="replan",
                        reason=issue.message,
                        priority=10,
                        input={
                            "scope": "goal_alignment"
                        },
                    )
                )

            elif issue.code == (
                "invalid_dependency_completion"
            ):

                corrections.append(
                    CorrectionAction(
                        action="replan",
                        reason=issue.message,
                        task_id=issue.task_id,
                        priority=10,
                    )
                )

        return self._deduplicate_corrections(
            corrections
        )

    # =========================================================
    # NORMALIZATION
    # =========================================================

    @staticmethod
    def _completed_tasks(
        plan: ExecutionPlan,
    ) -> List[str]:

        completed = getattr(
            plan,
            "completed_tasks",
            [],
        ) or []

        return list(
            dict.fromkeys(
                str(item)
                for item in completed
            )
        )

    @staticmethod
    def _failed_tasks(
        plan: ExecutionPlan,
    ) -> List[str]:

        failed = getattr(
            plan,
            "failed_tasks",
            [],
        ) or []

        return list(
            dict.fromkeys(
                str(item)
                for item in failed
            )
        )

    @staticmethod
    def _deduplicate_issues(
        issues: Iterable[
            VerificationIssue
        ],
    ) -> List[
        VerificationIssue
    ]:

        result: List[
            VerificationIssue
        ] = []

        seen = set()

        for issue in issues:

            key = (
                issue.code,
                issue.task_id,
                issue.message,
            )

            if key in seen:
                continue

            seen.add(
                key
            )

            result.append(
                issue
            )

        return result

    @staticmethod
    def _deduplicate_corrections(
        corrections: Iterable[
            CorrectionAction
        ],
    ) -> List[
        CorrectionAction
    ]:

        result: List[
            CorrectionAction
        ] = []

        seen = set()

        for correction in corrections:

            key = (
                correction.action,
                correction.task_id,
            )

            if key in seen:
                continue

            seen.add(
                key
            )

            result.append(
                correction
            )

        result.sort(
            key=lambda item: (
                -item.priority,
                item.action,
                item.task_id or "",
            )
        )

        return result

    # =========================================================
    # STATUS / HEALTH
    # =========================================================

    def health(
        self,
    ) -> Dict[str, Any]:

        return {
            "version": self.VERSION,
            "healthy": True,
            "max_issues": self.max_issues,
            "max_corrections": (
                self.max_corrections
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
                "verification and "
                "self-correction analysis"
            ),
            "execution": False,
            "llm_calls": False,
            "side_effects": False,
            "features": [
                "plan verification",
                "task-state verification",
                "dependency verification",
                "cycle detection",
                "output verification",
                "executor-result verification",
                "goal verification",
                "correction recommendations",
                "bounded issue collection",
                "bounded correction collection",
            ],
        }


__all__ = [
    "CorrectionAction",
    "SelfCorrectionEngine",
    "VerificationIssue",
    "VerificationResult",
]