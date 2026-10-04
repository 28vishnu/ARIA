from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Sequence

from brain.plan import ExecutionPlan
from brain.task import Task
from brain.planning.phase_planner import PhaseDefinition, PhasePlanner

logger = logging.getLogger("aria.phase_task_execution")


@dataclass
class TaskExecutionRecord:
    task_id: str
    name: str
    status: str
    requirement: str
    job_id: Optional[str] = None
    error: Optional[str] = None
    output: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PhaseExecutionResult:
    success: bool
    goal: str
    plan_status: str
    plan: Optional[ExecutionPlan] = None
    records: List[TaskExecutionRecord] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        plan_dict = None
        if self.plan is not None:
            plan_dict = {
                "goal": self.plan.goal,
                "status": self.plan.status,
                "confidence": self.plan.confidence,
                "completed_tasks": list(self.plan.completed_tasks),
                "failed_tasks": list(self.plan.failed_tasks),
                "skipped_tasks": list(self.plan.skipped_tasks),
                "task_outputs": dict(self.plan.task_outputs),
                "metadata": dict(self.plan.metadata),
                "tasks": [
                    {
                        "id": task.id,
                        "name": task.name,
                        "skill": task.skill,
                        "depends_on": list(task.depends_on),
                        "priority": task.priority,
                        "status": task.status,
                        "error": task.error,
                    }
                    for task in self.plan.tasks
                ],
            }

        return {
            "success": self.success,
            "goal": self.goal,
            "plan_status": self.plan_status,
            "plan": plan_dict,
            "records": [record.to_dict() for record in self.records],
            "error": self.error,
        }


class PhaseTaskExecutionEngine:
    """
    Converts a large engineering phase into a dependency-aware task graph
    and executes one engineering task at a time through DevelopmentController.

    The engine deliberately executes sequentially because the development
    controller protects one repository/workspace from concurrent mutation.
    """

    VERSION = "PHASE1-PHASE-TASK-EXECUTION-20261004"

    def __init__(
        self,
        phase_planner: PhasePlanner,
        development_controller: Any,
        *,
        max_tasks: int = 32,
        stop_on_failure: bool = True,
    ) -> None:
        if phase_planner is None:
            raise ValueError("phase_planner is required.")
        if development_controller is None:
            raise ValueError("development_controller is required.")

        self.phase_planner = phase_planner
        self.development_controller = development_controller
        self.max_tasks = max(1, min(int(max_tasks), 32))
        self.stop_on_failure = bool(stop_on_failure)

        self._active = False
        self._last_result: Optional[PhaseExecutionResult] = None

    async def plan(
        self,
        goal: str,
        *,
        context: Optional[Dict[str, Any]] = None,
        explicit_phases: Optional[Sequence[Dict[str, Any] | PhaseDefinition]] = None,
    ) -> ExecutionPlan:
        """Create and validate a dependency graph without executing it."""
        plan = await self.phase_planner.create_plan(
            goal=goal,
            context=context or {},
            explicit_phases=explicit_phases,
        )

        if len(plan.tasks) > self.max_tasks:
            plan.tasks = plan.tasks[: self.max_tasks]
            plan.metadata["task_limit_applied"] = True

        if not plan.validate_dependencies():
            plan.status = "failed"
            plan.error = "Generated task graph failed dependency validation."
            return plan

        plan.metadata.update({
            "execution_engine": self.VERSION,
            "execution_started": False,
            "task_graph_valid": True,
        })
        return plan

    @staticmethod
    def _task_requirement(
        goal: str,
        task: Task,
        dependency_outputs: Dict[str, Any],
    ) -> str:
        dependency_summary = ""
        if dependency_outputs:
            dependency_summary = (
                "\nCompleted dependency context:\n"
                + str(dependency_outputs)[:12000]
            )

        return (
            "You are executing one task inside a larger autonomous engineering phase.\n\n"
            f"Overall phase requirement:\n{goal}\n\n"
            f"Current task:\n{task.name}\n\n"
            f"Task skill/category: {task.skill}\n"
            f"Task type: {task.task_type}\n"
            f"Task input: {task.input}\n"
            f"Dependencies: {task.depends_on}\n"
            f"{dependency_summary}\n\n"
            "Implement and validate this task within ARIA's existing development workflow. "
            "Do not push to GitHub or deploy production as part of this task."
        )

    async def execute(
        self,
        goal: str,
        *,
        context: Optional[Dict[str, Any]] = None,
        explicit_phases: Optional[Sequence[Dict[str, Any] | PhaseDefinition]] = None,
        workspace_id: Optional[str] = None,
    ) -> PhaseExecutionResult:
        """Plan a phase and execute its ready tasks sequentially."""
        if self._active:
            raise RuntimeError("Another phase execution is already running.")

        normalized_goal = str(goal or "").strip()
        if not normalized_goal:
            raise ValueError("goal cannot be empty.")

        self._active = True
        records: List[TaskExecutionRecord] = []
        plan: Optional[ExecutionPlan] = None

        try:
            plan = await self.plan(
                normalized_goal,
                context=context,
                explicit_phases=explicit_phases,
            )

            if plan.status == "failed":
                result = PhaseExecutionResult(
                    success=False,
                    goal=normalized_goal,
                    plan_status=plan.status,
                    plan=plan,
                    records=records,
                    error=plan.error,
                )
                self._last_result = result
                return result

            plan.mark_running()
            plan.metadata["execution_started"] = True

            while not plan.is_complete():
                ready = [
                    task
                    for task in plan.tasks
                    if task.is_ready(plan.completed_tasks)
                ]

                ready.sort(
                    key=lambda task: (-int(task.priority), task.id)
                )

                if not ready:
                    unresolved = [
                        task.id
                        for task in plan.tasks
                        if task.status == "pending"
                    ]
                    plan.mark_failed(
                        "No runnable task remained; dependency graph is blocked: "
                        + ", ".join(unresolved)
                    )
                    break

                task = ready[0]

                if task.requires_confirmation and not task.confirmed:
                    task.mark_awaiting_confirmation()
                    plan.mark_awaiting_confirmation(task.id)
                    records.append(
                        TaskExecutionRecord(
                            task_id=task.id,
                            name=task.name,
                            status="awaiting_confirmation",
                            requirement="",
                            error="Task requires explicit confirmation.",
                        )
                    )
                    break

                task.mark_running()
                dependency_outputs = {
                    dep: plan.task_outputs.get(dep, {})
                    for dep in task.depends_on
                }
                requirement = self._task_requirement(
                    normalized_goal,
                    task,
                    dependency_outputs,
                )

                try:
                    job = await self.development_controller.execute(
                        requirement,
                        test_paths=task.input.get("test_paths") if isinstance(task.input, dict) else None,
                        workspace_id=workspace_id,
                    )

                    job_dict = job.to_dict() if hasattr(job, "to_dict") else {"value": str(job)}
                    success = str(job_dict.get("status", "")).lower() == "completed"
                    report = job_dict.get("report") or {}
                    if isinstance(report, dict) and "success" in report:
                        success = success and bool(report.get("success"))

                    if success:
                        task.mark_completed(job_dict)
                        plan.record_completed_task(task.id, job_dict)
                        records.append(
                            TaskExecutionRecord(
                                task_id=task.id,
                                name=task.name,
                                status="completed",
                                requirement=requirement,
                                job_id=job_dict.get("job_id"),
                                output=job_dict,
                            )
                        )
                    else:
                        error = (
                            str(job_dict.get("error"))
                            if job_dict.get("error")
                            else "Development task did not complete successfully."
                        )
                        task.mark_failed(error)
                        plan.record_failed_task(task.id)
                        records.append(
                            TaskExecutionRecord(
                                task_id=task.id,
                                name=task.name,
                                status="failed",
                                requirement=requirement,
                                job_id=job_dict.get("job_id"),
                                error=error,
                                output=job_dict,
                            )
                        )
                        if self.stop_on_failure:
                            plan.mark_failed(error)
                            break

                except Exception as exc:
                    error = str(exc)[:4000]
                    task.mark_failed(error)
                    plan.record_failed_task(task.id)
                    records.append(
                        TaskExecutionRecord(
                            task_id=task.id,
                            name=task.name,
                            status="failed",
                            requirement=requirement,
                            error=error,
                        )
                    )
                    logger.exception(
                        "[PhaseTaskExecution] Task failed | task=%s",
                        task.id,
                    )
                    if self.stop_on_failure:
                        plan.mark_failed(error)
                        break

            if plan.status == "awaiting_confirmation":
                success = False
            elif plan.has_failures():
                if plan.status != "failed":
                    plan.mark_failed("One or more phase tasks failed.")
                success = False
            elif plan.is_complete():
                plan.mark_completed()
                success = True
            else:
                success = False

            result = PhaseExecutionResult(
                success=success,
                goal=normalized_goal,
                plan_status=plan.status,
                plan=plan,
                records=records,
                error=plan.error,
            )
            self._last_result = result
            return result

        finally:
            self._active = False

    async def resume(
        self,
        *,
        confirm_task_id: Optional[str] = None,
        workspace_id: Optional[str] = None,
    ) -> PhaseExecutionResult:
        """Resume a paused plan after confirmation."""
        if self._last_result is None or self._last_result.plan is None:
            raise RuntimeError("No paused phase execution exists.")

        plan = self._last_result.plan
        if plan.status != "awaiting_confirmation":
            raise RuntimeError("The last phase execution is not awaiting confirmation.")

        task_id = confirm_task_id or plan.awaiting_task_id
        if not task_id:
            raise ValueError("confirm_task_id is required.")

        task = plan.get_task(task_id)
        if task is None:
            raise ValueError(f"Unknown task: {task_id}")

        task.confirm()
        plan.clear_confirmation()

        # Reconstruct the original goal/context from plan metadata.
        return await self._continue_plan(
            plan,
            workspace_id=workspace_id,
        )

    async def _continue_plan(
        self,
        plan: ExecutionPlan,
        *,
        workspace_id: Optional[str] = None,
    ) -> PhaseExecutionResult:
        """Continue an already-created plan."""
        if self._active:
            raise RuntimeError("Another phase execution is already running.")

        self._active = True
        records: List[TaskExecutionRecord] = []
        try:
            goal = plan.goal
            while not plan.is_complete():
                ready = [task for task in plan.tasks if task.is_ready(plan.completed_tasks)]
                ready.sort(key=lambda task: (-int(task.priority), task.id))
                if not ready:
                    plan.mark_failed("No runnable task remained while resuming phase execution.")
                    break

                task = ready[0]
                if task.requires_confirmation and not task.confirmed:
                    plan.mark_awaiting_confirmation(task.id)
                    break

                task.mark_running()
                dependency_outputs = {dep: plan.task_outputs.get(dep, {}) for dep in task.depends_on}
                requirement = self._task_requirement(goal, task, dependency_outputs)
                try:
                    job = await self.development_controller.execute(
                        requirement,
                        test_paths=task.input.get("test_paths") if isinstance(task.input, dict) else None,
                        workspace_id=workspace_id,
                    )
                    job_dict = job.to_dict() if hasattr(job, "to_dict") else {"value": str(job)}
                    success = str(job_dict.get("status", "")).lower() == "completed"
                    report = job_dict.get("report") or {}
                    if isinstance(report, dict) and "success" in report:
                        success = success and bool(report.get("success"))
                    if success:
                        task.mark_completed(job_dict)
                        plan.record_completed_task(task.id, job_dict)
                        records.append(TaskExecutionRecord(task.id, task.name, "completed", requirement, job_dict.get("job_id"), output=job_dict))
                    else:
                        error = str(job_dict.get("error") or "Development task failed.")
                        task.mark_failed(error)
                        plan.record_failed_task(task.id)
                        records.append(TaskExecutionRecord(task.id, task.name, "failed", requirement, job_dict.get("job_id"), error=error, output=job_dict))
                        if self.stop_on_failure:
                            plan.mark_failed(error)
                            break
                except Exception as exc:
                    error = str(exc)[:4000]
                    task.mark_failed(error)
                    plan.record_failed_task(task.id)
                    records.append(TaskExecutionRecord(task.id, task.name, "failed", requirement, error=error))
                    if self.stop_on_failure:
                        plan.mark_failed(error)
                        break

            if plan.status == "awaiting_confirmation":
                success = False
            elif plan.has_failures():
                if plan.status != "failed":
                    plan.mark_failed("One or more phase tasks failed.")
                success = False
            elif plan.is_complete():
                plan.mark_completed()
                success = True
            else:
                success = False

            result = PhaseExecutionResult(
                success=success,
                goal=plan.goal,
                plan_status=plan.status,
                plan=plan,
                records=records,
                error=plan.error,
            )
            self._last_result = result
            return result
        finally:
            self._active = False

    def status(self) -> Dict[str, Any]:
        return {
            "active": self._active,
            "version": self.VERSION,
            "max_tasks": self.max_tasks,
            "stop_on_failure": self.stop_on_failure,
            "last_result": self._last_result.to_dict() if self._last_result else None,
        }

    def health(self) -> Dict[str, Any]:
        return {
            "healthy": self.phase_planner is not None and self.development_controller is not None,
            "active": self._active,
            "version": self.VERSION,
        }

    def describe(self) -> Dict[str, Any]:
        return {
            "name": "phase_task_execution",
            "capabilities": [
                "phase_decomposition",
                "dependency_graph",
                "sequential_task_execution",
                "task_result_propagation",
                "pause_for_confirmation",
                "resume_after_confirmation",
            ],
            "safety": [
                "single_development_job_at_a_time",
                "stop_on_failure",
                "no_github_push",
                "no_production_deployment",
            ],
        }


__all__ = [
    "TaskExecutionRecord",
    "PhaseExecutionResult",
    "PhaseTaskExecutionEngine",
]
