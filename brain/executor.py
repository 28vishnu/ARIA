import logging
import re
import time
import asyncio
from typing import Dict, Any, Optional, List, Set
from dataclasses import dataclass

from brain.plan import ExecutionPlan
from brain.verifier import Verifier
from brain.optimizer import PlanOptimizer
from skills.manager import SkillManager
from skills.base import SkillResponse
from brain.events.event import Event
from brain.events import event_types

logger = logging.getLogger("aria")


NON_RETRYABLE_PHRASES = [
    "no profile information available",
    "no relevant memories found",
    "not found",
    "unavailable",
    "permission",
    "validation failed",
    "blocked",
]


REFERENCE_PATTERN = re.compile(
    r"\{\{\s*([A-Za-z0-9_-]+)\.([A-Za-z0-9_.-]+)\s*\}\}"
)


@dataclass
class IntentDecision:
    intent: str
    confidence: float




class Executor:
    """
    ARIA Phase-3 hybrid workflow executor.

    Executes:
    - skills through SkillManager
    - actions through ActionManager

    Supports:
    - task dependencies
    - task output references
    - skill retries
    - execution timing
    - failure propagation
    - action confirmation
    - workflow suspension
    - workflow resumption
    - preservation of completed task outputs
    - parallel execution via asyncio.gather
    - event publication via EventBus
    - workflow and task timeouts
    - safety cancellation and rollback support
    - rollback manager
    - task queue
    - workflow persistence via MongoDB
    - resource locking via asyncio.Lock
    - workflow visualization
    - extended metrics and statistics
    - automated recovery on startup
    - background execution
    - executor snapshot
    """

    def __init__(
        self,
        planner,
        event_bus,
        skill_manager=None,
        action_manager=None,
        mongodb=None,
        agent_manager=None,
        agent_coordinator=None,
    ):
        self.planner = planner
        self.event_bus = event_bus

        self.skill_manager = skill_manager
        self.action_manager = action_manager
        self.agent_manager = agent_manager
        self.agent_coordinator = agent_coordinator

        self.mongodb = mongodb
        if mongodb is not None:
            self.collection = mongodb["workflow_state"]
        else:
            self.collection = None

        self.verifier = Verifier()
        self.optimizer = PlanOptimizer()

        self.paused_workflows = {}
        self.execution_history = []
        self.max_execution_history = 1000

        self.task_queue = asyncio.Queue()
        self._resource_locks = {}

        self.statistics = {
            "workflows": 0,
            "tasks": 0,
            "completed": 0,
            "failed": 0,
            "paused": 0,
            "average_time": 0.0,
            "success_rate": 1.0,
            "average_task_time": 0.0,
            "longest_workflow": 0.0,
            "parallel_tasks": 0,
            "rollback_count": 0,
            "timeouts": 0,
            "cancelled": 0,
        }
        self._active_workflows: Set[str] = set()
        self.execution_log = []

    # =========================================================
    # RESOURCE LOCKING
    # =========================================================

    def _get_resource_lock(self, resource_name: str) -> asyncio.Lock:
        if resource_name not in self._resource_locks:
            self._resource_locks[resource_name] = asyncio.Lock()
        return self._resource_locks[resource_name]

    # =========================================================
    # CANCELLATION & ROLLBACK MANAGER
    # =========================================================

    def cancel_workflow(self, workflow_id: str):
        """
        Safely stop a running workflow.
        """
        if workflow_id in self._active_workflows:
            self._active_workflows.remove(workflow_id)
            self.statistics["cancelled"] += 1
            logger.info("[Executor] Workflow %s marked for cancellation.", workflow_id)

    async def rollback_workflow(self, plan: ExecutionPlan, completed_task_ids: List[str]):
        """
        Rollback completed tasks in reverse order if they define a rollback action.
        """
        logger.info("[Executor] Initiating rollback for workflow: %s", plan.goal)
        self.statistics["rollback_count"] += 1

        # Map task IDs back to task objects
        task_map = {t.id: t for t in plan.tasks}
        for task_id in reversed(completed_task_ids):
            task = task_map.get(task_id)
            if task and hasattr(task, "rollback_action") and task.rollback_action:
                try:
                    logger.info("[Executor] Rolling back task %s using action %s", task.id, task.rollback_action)
                    # Execute rollback action if action manager available
                    action_mgr = self._resolve_action_manager({})
                    if action_mgr and task.rollback_action in getattr(action_mgr, "actions", {}):
                        await action_mgr.execute_action(task.rollback_action, task.input, confirmed=True)
                except Exception:
                    logger.exception("[Executor] Rollback failed for task %s", task.id)

    # =========================================================
    # WORKFLOW PERSISTENCE & RECOVERY
    # =========================================================

    async def _persist_workflow_state(self, workflow_id: str, state_data: Dict[str, Any]):
        if self.collection is not None:
            try:
                state_data["_id"] = workflow_id
                await self.collection.replace_one({"_id": workflow_id}, state_data, upsert=True)
            except Exception:
                logger.exception("[Executor] Failed to persist workflow %s", workflow_id)

    async def recover_workflows(self):
        """
        Load paused/active workflows from MongoDB on startup and resume automatically.
        """
        if self.collection is not None:
            try:
                cursor = self.collection.find({"status": "paused"})
                async for doc in cursor:
                    wf_id = doc.get("_id")
                    if wf_id:
                        self.paused_workflows[wf_id] = doc
                        logger.info("[Executor] Recovered paused workflow: %s", wf_id)
            except Exception:
                logger.exception("[Executor] Failed to recover workflows from database.")

    # =========================================================
    # WORKFLOW VISUALIZATION
    # =========================================================

    def workflow_graph(self, plan: ExecutionPlan) -> str:
        """
        Return a textual flowchart representation of the workflow.
        """
        lines = []
        for task in plan.tasks:
            deps = ", ".join(task.depends_on) if task.depends_on else "None"
            lines.append(f"Task [{task.id}] ({task.name}) -> depends on: [{deps}]")
        return "\n └── ▼ \n".join(lines)

    # =========================================================
    # SNAPSHOT
    # =========================================================

    def snapshot(self) -> Dict[str, Any]:
        """
        Return executor statistics, history, queue state, and active/paused workflows.
        """
        return {
            "running": list(self._active_workflows),
            "paused": list(self.paused_workflows.keys()),
            "queue_size": self.task_queue.qsize(),
            "history": self.execution_history[-20:],  # last 20 entries
            "statistics": self.statistics,
        }

    # =========================================================
    # RESULT REFERENCE RESOLUTION
    # =========================================================

    def _extract_value(
        self,
        output: Any,
        field_path: str,
    ) -> Any:
        current = output
        for part in field_path.split("."):
            if isinstance(current, dict):
                if part not in current:
                    return None
                current = current[part]
            else:
                return None
        return current

    def _resolve_string(
        self,
        value: str,
        task_outputs: Dict[str, Any],
    ) -> Any:
        matches = list(
            REFERENCE_PATTERN.finditer(value)
        )
        if not matches:
            return value

        if (
            len(matches) == 1
            and matches[0].span() == (0, len(value))
        ):
            task_id = matches[0].group(1)
            field = matches[0].group(2)
            output = task_outputs.get(task_id)
            if output is None:
                raise ValueError(
                    f"Task output '{task_id}' is unavailable."
                )
            resolved = self._extract_value(
                output,
                field,
            )
            if resolved is None:
                raise ValueError(
                    f"Unable to resolve task reference "
                    f"'{{{{{task_id}.{field}}}}}'."
                )
            return resolved

        def replace_reference(match):
            task_id = match.group(1)
            field = match.group(2)
            output = task_outputs.get(task_id)
            if output is None:
                raise ValueError(
                    f"Task output '{task_id}' is unavailable."
                )
            resolved = self._extract_value(
                output,
                field,
            )
            if resolved is None:
                raise ValueError(
                    f"Unable to resolve task reference "
                    f"'{{{{{task_id}.{field}}}}}'."
                )
            return str(resolved)

        return REFERENCE_PATTERN.sub(
            replace_reference,
            value,
        )

    def _resolve_value(
        self,
        value: Any,
        task_outputs: Dict[str, Any],
    ) -> Any:
        if isinstance(value, str):
            return self._resolve_string(
                value,
                task_outputs,
            )
        if isinstance(value, dict):
            return {
                key: self._resolve_value(
                    item,
                    task_outputs,
                )
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [
                self._resolve_value(
                    item,
                    task_outputs,
                )
                for item in value
            ]
        if isinstance(value, tuple):
            return tuple(
                self._resolve_value(
                    item,
                    task_outputs,
                )
                for item in value
            )
        return value

    # =========================================================
    # ACTION MANAGER RESOLUTION
    # =========================================================

    def _resolve_action_manager(
        self,
        base_context: Dict[str, Any],
    ):
        if self.action_manager is not None:
            return self.action_manager

        app_state = (
            base_context or {}
        ).get(
            "app_state"
        )
        if not app_state:
            return None

        registry = getattr(
            app_state,
            "registry",
            None,
        )
        if registry is None:
            return None

        try:
            if registry.has(
                "action_manager"
            ):
                return registry.get(
                    "action_manager"
                )
        except Exception:
            logger.exception(
                "[Executor] Failed resolving ActionManager "
                "from service registry."
            )
        return None

    # =========================================================
    # WORKFLOW RESULT
    # =========================================================

    def _build_result(
        self,
        *,
        task_outputs: Dict[str, Any],
        workflow_results: Dict[str, Any],
        completed: List[str],
        failed: List[str],
        skipped: List[str],
        paused: bool = False,
        requires_confirmation: bool = False,
        pending_task_id: Optional[str] = None,
        pending_action_name: Optional[str] = None,
        pending_action_params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        result = {
            "task_outputs": dict(
                task_outputs
            ),
            "workflow_results": dict(
                workflow_results
            ),
            "completed": list(
                completed
            ),
            "failed": list(
                failed
            ),
            "skipped": list(
                skipped
            ),
            "paused": bool(
                paused
            ),
            "requires_confirmation": bool(
                requires_confirmation
            ),
            "pending_task_id": (
                pending_task_id
            ),
            "pending_action_name": (
                pending_action_name
            ),
            "pending_action_params": dict(
                pending_action_params or {}
            ),
            "success": (
                not paused
                and len(failed) == 0
                and len(skipped) == 0
            ),
        }
        self.execution_log.append(result)
        if len(self.execution_log) > 100:
            self.execution_log.pop(0)
        return result

    # =========================================================
    # BACKGROUND EXECUTION SUPPORT
    # =========================================================

    def execute_background(self, plan: ExecutionPlan, base_context: Dict[str, Any]):
        """
        Execute workflow in the background without awaiting result directly.
        """
        asyncio.create_task(self.execute_plan(plan, base_context))
        logger.info("[Executor] Dispatched background workflow for goal: %s", plan.goal)

    # =========================================================
    # REPLAN & PROGRESS TRACKING
    # =========================================================

    async def replan_if_needed(
        self,
        plan: ExecutionPlan,
        failed_tasks: List[str],
        completed: List[str],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Trigger dynamic replanning via planner if tasks have failed.
        """
        if failed_tasks and self.planner and hasattr(self.planner, "dynamic_replan"):
            logger.info("[Executor] Triggering dynamic replan due to failed tasks.")
            new_plan = await self.planner.dynamic_replan(
                plan.goal,
                completed,
                failed_tasks,
                context,
            )
            if new_plan:
                return await self.execute_plan(new_plan, context)
        return {}

    async def update_progress(self, plan: ExecutionPlan, completed: List[str], running: List[str], start_time: float) -> Dict[str, Any]:
        """
        Update and calculate percentage completion, running status, remaining tasks, and ETA.
        """
        total_tasks = len(plan.tasks) if plan and plan.tasks else 1
        completed_count = len(completed)
        percent = (completed_count / total_tasks) * 100.0

        elapsed = time.time() - start_time
        avg_time_per_task = elapsed / max(1, completed_count)
        remaining_count = total_tasks - completed_count
        eta = remaining_count * avg_time_per_task

        progress_info = {
            "percent_completed": round(percent, 2),
            "running": running,
            "remaining": remaining_count,
            "eta_seconds": round(eta, 2),
        }
        return progress_info

    # =========================================================
    # TASK & PLAN EXECUTION HELPERS
    # =========================================================

    async def execute_task(self, task, context=None):
        agent = task.get("agent")
        task_name = task.get("task")

        try:
            if self.agent_manager:
                results = await self.agent_manager.execute_agents(
                    [
                        {
                            "agent": agent,
                            "task": task_name
                        }
                    ],
                    context=context
                )
            else:
                results = []

            return {
                "success": True,
                "result": results
            }

        except Exception as e:

            return {
                "success": False,
                "error": str(e)
            }

    async def execute_plan(
        self,
        plan,
        context,
    ):

        results = []

        while True:

            step = self.planner.next_step(plan)

            if step is None:
                break

            for retry in range(3):

                try:

                    result = await self.execute(
                        step,
                        context,
                    )

                    break

                except Exception:

                    if retry == 2:
                        raise

            step["status"] = "completed"

            step["result"] = result

            results.append(result)

        plan.completed = True

        return results

    # =========================================================
    # MAIN EXECUTION (FULL PIPELINE)
    # =========================================================

    async def _execute_full_plan_object(
        self,
        plan: ExecutionPlan,
        base_context: Dict[str, Any],
        resume_state: Optional[Dict[str, Any]] = None,
        confirmed_task_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if isinstance(plan, ExecutionPlan):
            plan = self.optimizer.optimize(plan)

        base_context = base_context or {}
        resume_state = resume_state or {}

        decision = base_context.get("decision")
        if (
            decision
            and decision.use_multi_agent
            and self.agent_coordinator
        ):
            try:
                logger.info(
                    "[Executor] Executing multi-agent workflow: %s",
                    decision.selected_agents if decision else [],
                )
                return await self.agent_coordinator.coordinate(
                    decision=decision,
                    query=base_context.get("query", plan.goal),
                    context=base_context,
                )
            except Exception:
                logger.exception(
                    "[Executor] Coordinator failed"
                )

        workflow_id = getattr(plan, "id", f"wf_{int(time.time())}")
        self._active_workflows.add(workflow_id)
        self.statistics["workflows"] += 1

        start_time_all = time.time()

        if self.event_bus:
            await self.event_bus.publish(
                Event(
                    type=event_types.WORKFLOW_STARTED,
                    source="executor",
                    data={"workflow_id": workflow_id, "goal": plan.goal},
                )
            )

        task_outputs: Dict[str, Any] = dict(
            resume_state.get(
                "task_outputs",
                {}
            )
            or {}
        )

        completed: List[str] = list(
            resume_state.get(
                "completed",
                []
            )
            or []
        )

        failed: List[str] = list(
            resume_state.get(
                "failed",
                []
            )
            or []
        )

        skipped: List[str] = list(
            resume_state.get(
                "skipped",
                []
            )
            or []
        )

        workflow_results: Dict[str, Any] = dict(
            resume_state.get(
                "workflow_results",
                {}
            )
            or {}
        )

        executed: Set[str] = set(
            completed
            + failed
            + skipped
        )

        for task in plan.tasks:
            if task.id in completed:
                task.status = "completed"
                if task.id in task_outputs:
                    task.output = task_outputs[task.id]
            elif task.id in failed:
                task.status = "failed"
            elif task.id in skipped:
                task.status = "skipped"
            else:
                if task.status == "awaiting_confirmation":
                    task.status = "pending"

        if confirmed_task_id:
            matching_task = next(
                (
                    task
                    for task in plan.tasks
                    if task.id == confirmed_task_id
                ),
                None,
            )
            if matching_task is None:
                logger.error(
                    "[Executor] Confirmed workflow task %s does not exist.",
                    confirmed_task_id,
                )
                return self._build_result(
                    task_outputs=task_outputs,
                    workflow_results=workflow_results,
                    completed=completed,
                    failed=[*failed, confirmed_task_id],
                    skipped=skipped,
                )
            if not matching_task.is_action():
                logger.error(
                    "[Executor] Confirmation supplied for non-action task %s.",
                    confirmed_task_id,
                )
                return self._build_result(
                    task_outputs=task_outputs,
                    workflow_results=workflow_results,
                    completed=completed,
                    failed=[*failed, confirmed_task_id],
                    skipped=skipped,
                )
            matching_task.confirm()
            if self.event_bus:
                await self.event_bus.publish(
                    Event(
                        type=event_types.WORKFLOW_RESUMED,
                        source="executor",
                        data={"workflow_id": workflow_id, "confirmed_task_id": confirmed_task_id},
                    )
                )

        action_manager = self._resolve_action_manager(base_context)
        workflow_timeout = base_context.get("workflow_timeout", 300)  # default 5 mins

        try:
            while len(executed) < len(plan.tasks):
                if workflow_id not in self._active_workflows:
                    logger.info("[Executor] Workflow %s cancelled.", workflow_id)
                    break

                if time.time() - start_time_all > workflow_timeout:
                    logger.warning("[Executor] Workflow %s timed out.", workflow_id)
                    self.statistics["timeouts"] += 1
                    if self.event_bus:
                        await self.event_bus.publish(
                            Event(
                                type=event_types.WORKFLOW_PAUSED,
                                source="executor",
                                data={"workflow_id": workflow_id, "reason": "timeout"},
                            )
                        )
                    break

                ready_tasks = [
                    task
                    for task in plan.tasks
                    if (
                        task.id not in executed
                        and all(
                            dependency in executed
                            for dependency in task.depends_on
                        )
                    )
                ]

                if not ready_tasks:
                    logger.error("[Executor] Unresolvable dependency tree.")
                    remaining = [
                        task for task in plan.tasks if task.id not in executed
                    ]
                    for task in remaining:
                        error = "Unresolvable task dependencies."
                        task.mark_failed(error)
                        if task.id not in failed:
                            failed.append(task.id)
                        workflow_results[task.id] = {
                            "type": task.task_type,
                            "target": task.action_name if task.is_action() else task.skill,
                            "status": "failed",
                            "error": error,
                        }
                        executed.add(task.id)
                    break

                ready_tasks.sort(key=lambda task: task.priority, reverse=True)

                parallel_batch = []
                for task in ready_tasks:
                    has_peer_dependency = any(dep in [t.id for t in ready_tasks] for dep in task.depends_on)
                    if not has_peer_dependency:
                        parallel_batch.append(task)

                if not parallel_batch:
                    parallel_batch = [ready_tasks[0]]

                if len(parallel_batch) > 1:
                    self.statistics["parallel_tasks"] += len(parallel_batch)

                async def execute_single_task(task):
                    failed_dependencies = [
                        dependency
                        for dependency in task.depends_on
                        if (dependency in failed or dependency in skipped)
                    ]
                    if failed_dependencies:
                        reason = "Skipped because dependency failed: " + ", ".join(failed_dependencies)
                        task.mark_skipped(reason)
                        workflow_results[task.id] = {
                            "type": task.task_type,
                            "target": task.action_name if task.is_action() else task.skill,
                            "status": "skipped",
                            "error": reason,
                        }
                        if task.id not in skipped:
                            skipped.append(task.id)
                        executed.add(task.id)
                        if self.event_bus:
                            await self.event_bus.publish(
                                Event(
                                    type=event_types.TASK_SKIPPED,
                                    source="executor",
                                    data={"task_id": task.id, "reason": reason},
                                )
                            )
                        return "skipped"

                    try:
                        resolved_input = self._resolve_value(
                            dict(task.input or {}),
                            task_outputs,
                        )
                        resolved_params = self._resolve_value(
                            dict(task.params or {}),
                            task_outputs,
                        )
                    except Exception as exc:
                        error = str(exc)
                        task.mark_failed(error)
                        workflow_results[task.id] = {
                            "type": task.task_type,
                            "target": task.action_name if task.is_action() else task.skill,
                            "status": "failed",
                            "error": error,
                        }
                        if task.id not in failed:
                            failed.append(task.id)
                        executed.add(task.id)
                        if self.event_bus:
                            await self.event_bus.publish(
                                Event(
                                    type=event_types.TASK_FAILED,
                                    source="executor",
                                    data={"task_id": task.id, "error": error},
                                )
                            )
                        return "failed"

                    for dep_id in task.depends_on:
                        if dep_id in task_outputs:
                            resolved_input[f"context_from_{dep_id}"] = task_outputs[dep_id]

                    task.mark_running()
                    self.statistics["tasks"] += 1
                    if self.event_bus:
                        await self.event_bus.publish(
                            Event(
                                type=event_types.TASK_STARTED,
                                source="executor",
                                data={"task_id": task.id, "name": task.name},
                            )
                        )

                    task_start = time.time()
                    start_time = time.perf_counter()
                    task_timeout = getattr(task, "timeout", 30)

                    # Acquire resource lock if specified in task
                    resource_name = getattr(task, "resource", None)
                    lock = self._get_resource_lock(resource_name) if resource_name else None

                    try:
                        if lock:
                            await lock.acquire()

                        if task.is_action():
                            result = await asyncio.wait_for(
                                self._execute_action(
                                    task=task,
                                    params=resolved_params,
                                    action_manager=action_manager,
                                ),
                                timeout=task_timeout,
                            )
                        else:
                            result = await asyncio.wait_for(
                                self._execute_skill(
                                    task=task,
                                    resolved_input=resolved_input,
                                    plan=plan,
                                    base_context=base_context,
                                ),
                                timeout=task_timeout,
                            )
                    except asyncio.TimeoutError:
                        self.statistics["timeouts"] += 1
                        result = {
                            "success": False,
                            "paused": False,
                            "requires_confirmation": False,
                            "data": {},
                            "error": f"Task timed out after {task_timeout} seconds.",
                            "source": task.action_name if task.is_action() else task.skill,
                        }
                        if self.event_bus:
                            await self.event_bus.publish(
                                Event(
                                    type=event_types.TASK_TIMEOUT,
                                    source="executor",
                                    data={"task_id": task.id, "timeout": task_timeout},
                                )
                            )
                    except Exception as exc:
                        result = {
                            "success": False,
                            "paused": False,
                            "requires_confirmation": False,
                            "data": {},
                            "error": str(exc),
                            "source": task.action_name if task.is_action() else task.skill,
                        }
                    finally:
                        if lock and lock.locked():
                            lock.release()

                    elapsed_ms = (time.perf_counter() - start_time) * 1000
                    task.execution_time_ms = elapsed_ms
                    self.statistics["average_task_time"] = (self.statistics["average_task_time"] + elapsed_ms) / 2

                    if result.get("requires_confirmation"):
                        task.mark_awaiting_confirmation()
                        workflow_results[task.id] = {
                            "type": task.task_type,
                            "target": task.action_name,
                            "status": "awaiting_confirmation",
                            "execution_time_ms": elapsed_ms,
                        }
                        self.paused_workflows[workflow_id] = {
                            "plan": plan,
                            "task_outputs": task_outputs,
                            "completed": completed,
                            "failed": failed,
                            "skipped": skipped,
                            "workflow_results": workflow_results,
                            "status": "paused",
                        }
                        await self._persist_workflow_state(workflow_id, self.paused_workflows[workflow_id])

                        if self.event_bus:
                            await self.event_bus.publish(
                                Event(
                                    type=event_types.WORKFLOW_PAUSED,
                                    source="executor",
                                    data={"workflow_id": workflow_id, "task_id": task.id},
                                )
                            )
                        self.statistics["paused"] += 1
                        return "paused"

                    if result.get("success"):
                        output = result.get("data", {}) or {}
                        if not isinstance(output, dict):
                            output = {"result": output}
                        task.mark_completed(output)
                        task_outputs[task.id] = output
                        workflow_results[task.id] = {
                            "type": task.task_type,
                            "target": result.get("source"),
                            "status": "completed",
                            "output": output,
                            "execution_time_ms": elapsed_ms,
                        }
                        if task.id not in completed:
                            completed.append(task.id)
                        self.statistics["completed"] += 1
                        if self.event_bus:
                            await self.event_bus.publish(
                                Event(
                                    type=event_types.TASK_COMPLETED,
                                    source="executor",
                                    data={"task_id": task.id, "result": output},
                                )
                            )
                    else:
                        error = result.get("error") or "Task execution failed."
                        task.mark_failed(error)
                        workflow_results[task.id] = {
                            "type": task.task_type,
                            "target": result.get("source"),
                            "status": "failed",
                            "error": error,
                            "execution_time_ms": elapsed_ms,
                        }
                        if task.id not in failed:
                            failed.append(task.id)
                        self.statistics["failed"] += 1
                        if self.event_bus:
                            await self.event_bus.publish(
                                Event(
                                    type=event_types.TASK_FAILED,
                                    source="executor",
                                    data={"task_id": task.id, "error": error},
                                )
                            )

                        # Rollback completed tasks on failure
                        await self.rollback_workflow(plan, completed)

                        # Failure Recovery via Planner & Replanning
                        if failed:
                            replan_res = await self.replan_if_needed(plan, failed, completed, base_context)
                            if replan_res:
                                return replan_res

                    task_end = time.time()

                    execution_report = {
                        "workflow": workflow_id,
                        "task_id": task.id,
                        "task_name": task.name,
                        "status": task.status,
                        "started_at": task_start,
                        "finished_at": task_end,
                        "duration": round(task_end - task_start, 3),
                        "output": task_outputs.get(task.id),
                        "success": task.status == "completed",
                    }
                    self.execution_history.append(execution_report)

                    if len(self.execution_history) > self.max_execution_history:
                        self.execution_history.pop(0)

                    if hasattr(self, "world_model"):
                        await self.world_model.record_execution(execution_report)

                    if self.event_bus:
                        await self.event_bus.publish(
                            Event(
                                type=event_types.TASK_FINISHED,
                                source="executor",
                                data=execution_report,
                            )
                        )

                    executed.add(task.id)
                    return "done"

                results_batch = await asyncio.gather(*(execute_single_task(t) for t in parallel_batch))
                if "paused" in results_batch:
                    plan.completed_tasks = list(completed)
                    plan.failed_tasks = list(failed)
                    return self._build_result(
                        task_outputs=task_outputs,
                        workflow_results=workflow_results,
                        completed=completed,
                        failed=failed,
                        skipped=skipped,
                        paused=True,
                        requires_confirmation=True,
                    )

        finally:
            if workflow_id in self._active_workflows:
                self._active_workflows.remove(workflow_id)

        plan.completed_tasks = list(completed)
        plan.failed_tasks = list(failed)
        success = (len(failed) == 0 and len(skipped) == 0)

        elapsed_all_ms = (time.time() - start_time_all) * 1000
        self.statistics["average_time"] = (self.statistics["average_time"] + elapsed_all_ms) / 2
        if elapsed_all_ms > self.statistics["longest_workflow"]:
            self.statistics["longest_workflow"] = elapsed_all_ms

        total_workflows = self.statistics["workflows"]
        total_failed = self.statistics["failed"]
        self.statistics["success_rate"] = max(0.0, (total_workflows - total_failed) / max(1, total_workflows))

        res_built = self._build_result(
            task_outputs=task_outputs,
            workflow_results=workflow_results,
            completed=completed,
            failed=failed,
            skipped=skipped,
            paused=False,
            requires_confirmation=False,
        )

        self.execution_history.append({
            "workflow_id": workflow_id,
            "goal": plan.goal,
            "success": success,
            "duration_ms": elapsed_all_ms,
            "timestamp": time.time(),
        })

        if self.event_bus:
            event_name = event_types.WORKFLOW_COMPLETED if success else event_types.WORKFLOW_FAILED
            await self.event_bus.publish(
                Event(
                    type=event_name,
                    source="executor",
                    data={"workflow_id": workflow_id, "success": success},
                )
            )

        return res_built

    # =========================================================
    # SKILL EXECUTION
    # =========================================================

    async def _execute_skill(
        self,
        task,
        resolved_input,
        plan,
        base_context,
    ) -> Dict[str, Any]:
        attempt = 0
        max_attempts = task.max_retries + 1
        last_error = None

        while attempt < max_attempts:
            exec_context = dict(base_context)
            exec_context["task_input"] = resolved_input

            try:
                res: SkillResponse = await self.skill_manager.execute_skill(
                    task.skill,
                    resolved_input.get("query", plan.goal),
                    exec_context,
                )
            except Exception as exc:
                logger.exception("[Executor] Skill %s crashed.", task.skill)
                last_error = str(exc)
                res = None

            if res is not None and self.verifier.verify(task.id, res):
                return {
                    "success": True,
                    "paused": False,
                    "requires_confirmation": False,
                    "data": res.data or {},
                    "error": None,
                    "source": task.skill,
                }

            if res is not None:
                last_error = res.error or "Skill execution failed."
            if not last_error:
                last_error = "Skill execution failed."

            lowered = str(last_error).lower()
            non_retryable = any(phrase in lowered for phrase in NON_RETRYABLE_PHRASES)
            if non_retryable:
                break

            attempt += 1
            task.retry_count = attempt
            if attempt < max_attempts:
                logger.warning(
                    "[Executor] Retrying skill task %s (%d/%d)",
                    task.id,
                    attempt + 1,
                    max_attempts,
                )
                if self.event_bus:
                    await self.event_bus.publish(
                        Event(
                            type=event_types.TASK_RETRY,
                            source="executor",
                            data={"task_id": task.id, "attempt": attempt + 1},
                        )
                    )

        return {
            "success": False,
            "paused": False,
            "requires_confirmation": False,
            "data": {},
            "error": last_error,
            "source": task.skill,
        }

    # =========================================================
    # ACTION EXECUTION
    # =========================================================

    async def _execute_action(
        self,
        task,
        params,
        action_manager,
    ) -> Dict[str, Any]:
        if action_manager is None:
            return {
                "success": False,
                "paused": False,
                "requires_confirmation": False,
                "data": {},
                "error": "Action manager is unavailable.",
                "source": task.action_name,
            }

        actions = getattr(action_manager, "actions", {})
        if task.action_name not in actions:
            return {
                "success": False,
                "paused": False,
                "requires_confirmation": False,
                "data": {},
                "error": f"Action '{task.action_name}' is not registered.",
                "source": task.action_name,
            }

        action = actions[task.action_name]
        permission_level = getattr(action, "permission_level", "confirm")

        if task.action_name == "file_action":
            file_mode = str((params or {}).get("mode", "")).lower().strip()
            if file_mode == "read":
                permission_level = "safe"
            elif file_mode == "write":
                permission_level = "confirm"

        if permission_level == "confirm" and not task.confirmed:
            logger.info(
                "[Executor] Task %s requires confirmation before action '%s'.",
                task.id,
                task.action_name,
            )
            return {
                "success": False,
                "paused": True,
                "requires_confirmation": True,
                "data": {
                    "action_name": task.action_name,
                    "params": dict(params or {}),
                    "task_id": task.id,
                },
                "error": None,
                "source": task.action_name,
            }

        action_result = await action_manager.execute_action(
            action_name=task.action_name,
            params=params,
            confirmed=bool(task.confirmed),
        )

        return {
            "success": bool(action_result.success),
            "paused": False,
            "requires_confirmation": False,
            "data": action_result.data or {},
            "error": action_result.error,
            "source": task.action_name,
        }

    def last_execution(self):
        if not self.execution_log:
            return None
        return self.execution_log[-1]

    def clear_log(self):
        self.execution_log.clear()
