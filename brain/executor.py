import asyncio
import copy
import logging
import re
import time
from dataclasses import dataclass
from typing import Dict, Any, Optional, List, Set, Tuple

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
    ARIA Phase-11 canonical workflow executor.

    Execution ownership:
        CognitiveCore -> Planner -> Executor

    The Executor is responsible for executing an already-created plan.
    It does not reinterpret the user's intent and does not create a second
    orchestration system.

    Supports:
      - skills through SkillManager
      - actions through ActionManager
      - optional ToolManager for centralized tool execution
      - optional AgentCoordinator for explicit multi-agent workflows
      - task dependencies
      - task output references
      - bounded skill retries
      - task/workflow timeouts
      - action confirmation
      - workflow suspension/resumption
      - cancellation
      - resource locking
      - rollback hooks
      - event publication
      - workflow persistence/recovery
      - execution history/statistics
      - background execution
    """

    EXECUTOR_VERSION = "11.5"
    MAX_HISTORY = 1000
    MAX_EXECUTION_LOG = 100
    DEFAULT_WORKFLOW_TIMEOUT = 300.0
    DEFAULT_TASK_TIMEOUT = 30.0
    MAX_TASK_TIMEOUT = 600.0

    def __init__(
        self,
        planner,
        event_bus,
        skill_manager=None,
        action_manager=None,
        mongodb=None,
        agent_manager=None,
        agent_coordinator=None,
        tool_manager=None,
    ):
        self.planner = planner
        self.event_bus = event_bus

        self.skill_manager = skill_manager
        self.action_manager = action_manager
        self.agent_manager = agent_manager
        self.agent_coordinator = agent_coordinator
        self.tool_manager = tool_manager

        self.mongodb = mongodb
        if mongodb is not None:
            self.collection = mongodb["workflow_state"]
        else:
            self.collection = None

        self.verifier = Verifier()
        self.optimizer = PlanOptimizer()

        self.paused_workflows: Dict[str, Dict[str, Any]] = {}
        self.execution_history: List[Dict[str, Any]] = []
        self.max_execution_history = self.MAX_HISTORY

        self.task_queue = asyncio.Queue()
        self._resource_locks: Dict[str, asyncio.Lock] = {}
        self._workflow_tasks: Dict[str, asyncio.Task] = {}

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
        self.execution_log: List[Dict[str, Any]] = []
        self._cancel_requested: Set[str] = set()

    # =========================================================
    # GENERIC HELPERS
    # =========================================================

    @staticmethod
    def _safe_dict(value: Any) -> Dict[str, Any]:
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _safe_list(value: Any) -> List[Any]:
        return value if isinstance(value, list) else []

    @staticmethod
    def _task_target(task) -> str:
        if getattr(task, "is_action", lambda: False)():
            return str(getattr(task, "action_name", "") or "")
        return str(getattr(task, "skill", "") or "")

    @staticmethod
    def _result_success(result: Any) -> bool:
        if isinstance(result, dict):
            return bool(result.get("success", False))
        return bool(getattr(result, "success", False))

    @staticmethod
    def _result_data(result: Any) -> Any:
        if isinstance(result, dict):
            return result.get("data")
        return getattr(result, "data", None)

    @staticmethod
    def _result_error(result: Any) -> Optional[str]:
        if isinstance(result, dict):
            error = result.get("error")
        else:
            error = getattr(result, "error", None)

        return str(error) if error else None

    @staticmethod
    def _decision_value(decision: Any, key: str, default=None):
        if decision is None:
            return default

        if isinstance(decision, dict):
            return decision.get(key, default)

        return getattr(decision, key, default)

    def _record_execution_log(self, entry: Dict[str, Any]):
        self.execution_log.append(copy.deepcopy(entry))

        if len(self.execution_log) > self.MAX_EXECUTION_LOG:
            del self.execution_log[:-self.MAX_EXECUTION_LOG]

    def _record_history(self, entry: Dict[str, Any]):
        self.execution_history.append(copy.deepcopy(entry))

        if len(self.execution_history) > self.max_execution_history:
            del self.execution_history[:-self.max_execution_history]

    # =========================================================
    # RESOURCE LOCKING
    # =========================================================

    def _get_resource_lock(self, resource_name: str) -> asyncio.Lock:
        resource_name = str(resource_name or "").strip()

        if resource_name not in self._resource_locks:
            self._resource_locks[resource_name] = asyncio.Lock()

        return self._resource_locks[resource_name]

    # =========================================================
    # CANCELLATION & ROLLBACK
    # =========================================================

    def cancel_workflow(self, workflow_id: str):
        """
        Request cancellation of an active workflow.

        The request is cooperative so the current task can release resource
        locks and execute its cleanup path.
        """
        workflow_id = str(workflow_id or "").strip()

        if workflow_id in self._active_workflows:
            self._cancel_requested.add(workflow_id)
            self.statistics["cancelled"] += 1

            logger.info(
                "[Executor] Cancellation requested for workflow %s.",
                workflow_id,
            )

            workflow_task = self._workflow_tasks.get(workflow_id)

            if workflow_task and not workflow_task.done():
                workflow_task.cancel()

    async def rollback_workflow(
        self,
        plan: ExecutionPlan,
        completed_task_ids: List[str],
        base_context: Optional[Dict[str, Any]] = None,
    ):
        """
        Roll back completed tasks in reverse order when a task explicitly
        provides a rollback action.

        Rollback is opt-in and never inferred from arbitrary task names.
        """
        logger.info(
            "[Executor] Initiating rollback for workflow: %s",
            getattr(plan, "goal", ""),
        )

        self.statistics["rollback_count"] += 1

        task_map = {
            str(getattr(task, "id", "")): task
            for task in getattr(plan, "tasks", []) or []
        }

        action_manager = self._resolve_action_manager(
            base_context or {}
        )

        for task_id in reversed(completed_task_ids):
            task = task_map.get(str(task_id))

            if task is None:
                continue

            rollback_action = getattr(
                task,
                "rollback_action",
                None,
            )

            if not rollback_action or action_manager is None:
                continue

            try:
                actions = getattr(
                    action_manager,
                    "actions",
                    {},
                )

                if rollback_action not in actions:
                    logger.warning(
                        "[Executor] Rollback action %s is not registered.",
                        rollback_action,
                    )
                    continue

                logger.info(
                    "[Executor] Rolling back task %s using action %s.",
                    task.id,
                    rollback_action,
                )

                await action_manager.execute_action(
                    action_name=rollback_action,
                    params=dict(getattr(task, "input", {}) or {}),
                    confirmed=True,
                )

            except Exception:
                logger.exception(
                    "[Executor] Rollback failed for task %s.",
                    task_id,
                )

    # =========================================================
    # WORKFLOW PERSISTENCE & RECOVERY
    # =========================================================

    async def _persist_workflow_state(
        self,
        workflow_id: str,
        state_data: Dict[str, Any],
    ):
        if self.collection is None:
            return

        try:
            payload = copy.deepcopy(state_data)
            payload["_id"] = workflow_id

            await self.collection.replace_one(
                {"_id": workflow_id},
                payload,
                upsert=True,
            )

        except Exception:
            logger.exception(
                "[Executor] Failed to persist workflow %s.",
                workflow_id,
            )

    async def recover_workflows(self):
        """
        Load paused workflows from MongoDB.

        Recovery restores resumable state into paused_workflows. It does not
        silently execute arbitrary persisted actions on startup.
        """
        if self.collection is None:
            return

        try:
            cursor = self.collection.find(
                {"status": {"$in": ["paused", "awaiting_confirmation"]}}
            )

            async for doc in cursor:
                workflow_id = doc.get("_id")

                if workflow_id:
                    self.paused_workflows[str(workflow_id)] = doc

                    logger.info(
                        "[Executor] Recovered paused workflow: %s",
                        workflow_id,
                    )

        except Exception:
            logger.exception(
                "[Executor] Failed to recover workflows from database."
            )

    # =========================================================
    # WORKFLOW VISUALIZATION
    # =========================================================

    def workflow_graph(self, plan: ExecutionPlan) -> str:
        lines = []

        for task in getattr(plan, "tasks", []) or []:
            dependencies = getattr(
                task,
                "depends_on",
                [],
            ) or []

            deps = ", ".join(
                str(item) for item in dependencies
            ) or "None"

            lines.append(
                f"Task [{task.id}] ({task.name}) -> "
                f"depends on: [{deps}]"
            )

        return "\n └── ▼ \n".join(lines)

    # =========================================================
    # SNAPSHOT
    # =========================================================

    def snapshot(self) -> Dict[str, Any]:
        return {
            "version": self.EXECUTOR_VERSION,
            "running": list(self._active_workflows),
            "paused": list(self.paused_workflows.keys()),
            "queue_size": self.task_queue.qsize(),
            "history": copy.deepcopy(
                self.execution_history[-20:]
            ),
            "statistics": copy.deepcopy(self.statistics),
            "tool_manager": self.tool_manager is not None,
            "agent_coordinator": self.agent_coordinator is not None,
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

        for part in str(field_path).split("."):
            if isinstance(current, dict):
                if part not in current:
                    return None

                current = current[part]

            elif isinstance(current, (list, tuple)):
                try:
                    current = current[int(part)]
                except (ValueError, IndexError):
                    return None

            else:
                if hasattr(current, part):
                    current = getattr(current, part)
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

            if task_id not in task_outputs:
                raise ValueError(
                    f"Task output '{task_id}' is unavailable."
                )

            resolved = self._extract_value(
                task_outputs[task_id],
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

            if task_id not in task_outputs:
                raise ValueError(
                    f"Task output '{task_id}' is unavailable."
                )

            resolved = self._extract_value(
                task_outputs[task_id],
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

        app_state = self._safe_dict(
            base_context
        ).get("app_state")

        if app_state is None:
            return None

        registry = getattr(
            app_state,
            "registry",
            None,
        )

        if registry is None:
            return None

        try:
            if registry.has("action_manager"):
                return registry.get("action_manager")

        except Exception:
            logger.exception(
                "[Executor] Failed resolving ActionManager "
                "from service registry."
            )

        return None

    def _resolve_tool_manager(
        self,
        base_context: Dict[str, Any],
    ):
        if self.tool_manager is not None:
            return self.tool_manager

        app_state = self._safe_dict(
            base_context
        ).get("app_state")

        registry = getattr(
            app_state,
            "registry",
            None,
        ) if app_state is not None else None

        if registry is None:
            return None

        try:
            if registry.has("tool_manager"):
                return registry.get("tool_manager")

        except Exception:
            logger.exception(
                "[Executor] Failed resolving ToolManager "
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
        workflow_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        result = {
            "success": (
                not paused
                and not failed
                and not skipped
            ),
            "task_outputs": copy.deepcopy(task_outputs),
            "workflow_results": copy.deepcopy(workflow_results),
            "completed": list(completed),
            "failed": list(failed),
            "skipped": list(skipped),
            "paused": bool(paused),
            "requires_confirmation": bool(
                requires_confirmation
            ),
            "pending_task_id": pending_task_id,
            "pending_action_name": pending_action_name,
            "pending_action_params": copy.deepcopy(
                pending_action_params or {}
            ),
            "workflow_id": workflow_id,
            "executor_version": self.EXECUTOR_VERSION,
        }

        self._record_execution_log(result)

        return result

    # =========================================================
    # BACKGROUND EXECUTION
    # =========================================================

    def execute_background(
        self,
        plan: ExecutionPlan,
        base_context: Optional[Dict[str, Any]],
    ):
        """
        Start a workflow in the background and retain the asyncio Task so
        cancellation/shutdown can manage it.
        """
        context = dict(base_context or {})
        workflow_id = str(
            getattr(
                plan,
                "id",
                f"wf_{int(time.time() * 1000)}",
            )
        )

        task = asyncio.create_task(
            self.execute_plan(
                plan,
                context,
            )
        )

        self._workflow_tasks[workflow_id] = task

        def _cleanup(_task):
            self._workflow_tasks.pop(
                workflow_id,
                None,
            )

        task.add_done_callback(_cleanup)

        logger.info(
            "[Executor] Dispatched background workflow %s for goal: %s",
            workflow_id,
            getattr(plan, "goal", ""),
        )

        return task

    # =========================================================
    # REPLAN & PROGRESS
    # =========================================================

    async def replan_if_needed(
        self,
        plan: ExecutionPlan,
        failed_tasks: List[str],
        completed: List[str],
        context: Dict[str, Any],
        failed_task=None,
        failure_reason: str = "",
    ) -> Dict[str, Any]:
        """
        Trigger dynamic replanning using the Planner's canonical API.

        The old implementation passed positional arguments in the wrong
        order. This version uses named arguments so Planner.dynamic_replan()
        receives the intended workflow context.
        """
        if not failed_tasks:
            return {}

        if not self.planner:
            return {}

        dynamic_replan = getattr(
            self.planner,
            "dynamic_replan",
            None,
        )

        if not callable(dynamic_replan):
            return {}

        try:
            logger.info(
                "[Executor] Triggering dynamic replan due to failed tasks."
            )

            replan_context = dict(context or {})
            replan_context["completed_tasks"] = list(completed)
            replan_context["failed_tasks"] = list(failed_tasks)

            new_plan = await dynamic_replan(
                goal=getattr(plan, "goal", ""),
                context=replan_context,
                failed_task=failed_task,
                failure_reason=failure_reason,
                previous_plan=plan,
            )

            if new_plan is None:
                return {}

            return await self.execute_plan(
                new_plan,
                replan_context,
            )

        except Exception:
            logger.exception(
                "[Executor] Dynamic replan failed."
            )
            return {}

    async def update_progress(
        self,
        plan: ExecutionPlan,
        completed: List[str],
        running: List[str],
        start_time: float,
    ) -> Dict[str, Any]:
        total_tasks = max(
            1,
            len(getattr(plan, "tasks", []) or []),
        )

        completed_count = len(completed)
        percent = (
            completed_count / total_tasks
        ) * 100.0

        elapsed = max(
            0.0,
            time.time() - start_time,
        )

        avg_time_per_task = (
            elapsed / max(1, completed_count)
        )

        remaining_count = max(
            0,
            total_tasks - completed_count,
        )

        return {
            "percent_completed": round(
                percent,
                2,
            ),
            "running": list(running),
            "remaining": remaining_count,
            "eta_seconds": round(
                remaining_count * avg_time_per_task,
                2,
            ),
        }

    # =========================================================
    # LEGACY TASK EXECUTION
    # =========================================================

    async def execute_task(
        self,
        task,
        context=None,
    ):
        """
        Compatibility gateway for older agent-style task dictionaries.

        Canonical ExecutionPlan tasks are handled by _execute_full_plan_object.
        """
        task = self._safe_dict(task)

        agent = task.get("agent")
        task_name = task.get("task")

        if not agent:
            return {
                "success": False,
                "error": "Agent is not specified.",
            }

        try:
            if self.agent_manager is None:
                return {
                    "success": False,
                    "error": "Agent manager is unavailable.",
                }

            results = await self.agent_manager.execute_agents(
                [
                    {
                        "agent": agent,
                        "task": task_name,
                    }
                ],
                context=context,
            )

            return {
                "success": True,
                "result": results,
            }

        except Exception as exc:
            logger.exception(
                "[Executor] Agent task failed."
            )

            return {
                "success": False,
                "error": str(exc),
            }

    async def execute(self, task, context=None):
        """
        Canonical compatibility gateway for legacy callers.
        """
        return await self.execute_task(
            task,
            context,
        )

    # =========================================================
    # MAIN EXECUTION GATEWAY
    # =========================================================

    async def execute_plan(
        self,
        plan,
        context=None,
        resume_state=None,
        confirmed_task_id=None,
    ):
        context = dict(context or {})
        resume_state = dict(resume_state or {})

        if isinstance(plan, ExecutionPlan):
            return await self._execute_full_plan_object(
                plan=plan,
                base_context=context,
                resume_state=resume_state,
                confirmed_task_id=confirmed_task_id,
            )

        # -----------------------------------------------------
        # Legacy planner compatibility
        # -----------------------------------------------------

        if self.planner is None:
            return {
                "success": False,
                "error": "Planner is unavailable.",
                "results": [],
            }

        results = []

        while True:
            next_step = getattr(
                self.planner,
                "next_step",
                None,
            )

            if not callable(next_step):
                break

            step = next_step(plan)

            if step is None:
                break

            result = None
            last_error = None

            for attempt in range(3):
                try:
                    result = await self.execute(
                        step,
                        context,
                    )

                    if result.get("success", False):
                        break

                except Exception as exc:
                    last_error = exc
                    logger.exception(
                        "[Executor] Planner step failed."
                    )

                if attempt < 2:
                    await asyncio.sleep(0.25)

            if result is None:
                result = {
                    "success": False,
                    "error": str(
                        last_error
                        or "Task execution failed."
                    ),
                }

            if isinstance(step, dict):
                step["status"] = (
                    "completed"
                    if result.get("success")
                    else "failed"
                )
                step["result"] = result

            results.append(result)

            if not result.get("success"):
                break

        if hasattr(plan, "completed"):
            plan.completed = all(
                bool(result.get("success", False))
                for result in results
            )

        return results

    # =========================================================
    # FULL EXECUTION PIPELINE
    # =========================================================

    async def _execute_full_plan_object(
        self,
        plan: ExecutionPlan,
        base_context: Dict[str, Any],
        resume_state: Optional[Dict[str, Any]] = None,
        confirmed_task_id: Optional[str] = None,
    ) -> Dict[str, Any]:

        # -----------------------------------------------------
        # PLAN VALIDATION
        # -----------------------------------------------------

        if hasattr(plan, "validate_dependencies"):
            try:
                valid = bool(
                    plan.validate_dependencies()
                )
            except Exception:
                logger.exception(
                    "[Executor] Plan validation raised an exception."
                )
                valid = False

            if not valid:
                logger.error(
                    "[Executor] Invalid execution plan rejected."
                )

                try:
                    plan.mark_failed(
                        "Invalid execution plan dependencies."
                    )
                except Exception:
                    pass

                return self._build_result(
                    task_outputs={},
                    workflow_results={},
                    completed=[],
                    failed=[],
                    skipped=[],
                )

        # Optimization must remain non-destructive where possible.
        try:
            optimized_plan = self.optimizer.optimize(plan)
            if optimized_plan is not None:
                plan = optimized_plan
        except Exception:
            logger.exception(
                "[Executor] Plan optimization failed; "
                "continuing with original plan."
            )

        base_context = dict(base_context or {})
        resume_state = dict(resume_state or {})

        # -----------------------------------------------------
        # EXPLICIT MULTI-AGENT OWNERSHIP
        # -----------------------------------------------------
        #
        # CognitiveCore is normally the orchestration owner. Executor only
        # enters coordinator mode when the decision explicitly requests it.
        # This prevents accidental agent execution on ordinary plans.
        #
        decision = base_context.get("decision")

        use_multi_agent = bool(
            self._decision_value(
                decision,
                "use_multi_agent",
                False,
            )
        )

        if (
            use_multi_agent
            and self.agent_coordinator is not None
        ):
            try:
                selected_agents = self._decision_value(
                    decision,
                    "selected_agents",
                    [],
                )

                logger.info(
                    "[Executor] Executing explicitly requested "
                    "multi-agent workflow: %s",
                    selected_agents or [],
                )

                return await self.agent_coordinator.coordinate(
                    decision=decision,
                    query=base_context.get(
                        "query",
                        getattr(plan, "goal", ""),
                    ),
                    context=base_context,
                )

            except Exception:
                logger.exception(
                    "[Executor] Agent coordinator failed; "
                    "falling back to task execution."
                )

        # -----------------------------------------------------
        # WORKFLOW STATE
        # -----------------------------------------------------

        workflow_id = str(
            getattr(
                plan,
                "id",
                f"wf_{int(time.time() * 1000)}",
            )
        )

        self._active_workflows.add(workflow_id)
        self._cancel_requested.discard(workflow_id)

        self.statistics["workflows"] += 1

        start_time_all = time.time()

        if self.event_bus:
            try:
                await self.event_bus.publish(
                    Event(
                        type=event_types.WORKFLOW_STARTED,
                        source="executor",
                        data={
                            "workflow_id": workflow_id,
                            "goal": getattr(
                                plan,
                                "goal",
                                "",
                            ),
                        },
                    )
                )
            except Exception:
                logger.exception(
                    "[Executor] Failed publishing workflow start event."
                )

        task_outputs: Dict[str, Any] = copy.deepcopy(
            resume_state.get(
                "task_outputs",
                {},
            )
            or {}
        )

        completed: List[str] = [
            str(item)
            for item in (
                resume_state.get(
                    "completed",
                    [],
                )
                or []
            )
        ]

        failed: List[str] = [
            str(item)
            for item in (
                resume_state.get(
                    "failed",
                    [],
                )
                or []
            )
        ]

        skipped: List[str] = [
            str(item)
            for item in (
                resume_state.get(
                    "skipped",
                    [],
                )
                or []
            )
        ]

        workflow_results: Dict[str, Any] = copy.deepcopy(
            resume_state.get(
                "workflow_results",
                {},
            )
            or {}
        )

        executed: Set[str] = set(
            completed
            + failed
            + skipped
        )

        tasks = list(
            getattr(plan, "tasks", []) or []
        )

        task_map = {
            str(getattr(task, "id", "")): task
            for task in tasks
        }

        # Restore persisted task state.
        for task in tasks:
            task_id = str(
                getattr(task, "id", "")
            )

            if task_id in completed:
                task.status = "completed"

                if task_id in task_outputs:
                    task.output = task_outputs[task_id]

            elif task_id in failed:
                task.status = "failed"

            elif task_id in skipped:
                task.status = "skipped"

            elif getattr(
                task,
                "status",
                None,
            ) == "awaiting_confirmation":
                task.status = "pending"

        # -----------------------------------------------------
        # CONFIRMATION RESUME
        # -----------------------------------------------------

        if confirmed_task_id is not None:
            confirmed_task_id = str(
                confirmed_task_id
            )

            matching_task = task_map.get(
                confirmed_task_id
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
                    failed=[
                        *failed,
                        confirmed_task_id,
                    ],
                    skipped=skipped,
                    workflow_id=workflow_id,
                )

            is_action = getattr(
                matching_task,
                "is_action",
                lambda: False,
            )()

            if not is_action:
                logger.error(
                    "[Executor] Confirmation supplied for "
                    "non-action task %s.",
                    confirmed_task_id,
                )

                return self._build_result(
                    task_outputs=task_outputs,
                    workflow_results=workflow_results,
                    completed=completed,
                    failed=[
                        *failed,
                        confirmed_task_id,
                    ],
                    skipped=skipped,
                    workflow_id=workflow_id,
                )

            try:
                matching_task.confirm()
            except Exception:
                matching_task.confirmed = True
                matching_task.status = "pending"

            if self.event_bus:
                try:
                    await self.event_bus.publish(
                        Event(
                            type=event_types.WORKFLOW_RESUMED,
                            source="executor",
                            data={
                                "workflow_id": workflow_id,
                                "confirmed_task_id": confirmed_task_id,
                            },
                        )
                    )
                except Exception:
                    logger.exception(
                        "[Executor] Failed publishing resume event."
                    )

        action_manager = self._resolve_action_manager(
            base_context
        )

        tool_manager = self._resolve_tool_manager(
            base_context
        )

        workflow_timeout = self._safe_timeout(
            base_context.get(
                "workflow_timeout",
                self.DEFAULT_WORKFLOW_TIMEOUT,
            ),
            self.DEFAULT_WORKFLOW_TIMEOUT,
            self.DEFAULT_WORKFLOW_TIMEOUT * 4,
        )

        paused_result = None

        try:
            while len(executed) < len(tasks):

                if workflow_id in self._cancel_requested:
                    logger.info(
                        "[Executor] Workflow %s cancelled.",
                        workflow_id,
                    )

                    if self.event_bus:
                        try:
                            await self.event_bus.publish(
                                Event(
                                    type=event_types.WORKFLOW_PAUSED,
                                    source="executor",
                                    data={
                                        "workflow_id": workflow_id,
                                        "reason": "cancelled",
                                    },
                                )
                            )
                        except Exception:
                            logger.exception(
                                "[Executor] Failed publishing cancellation event."
                            )

                    paused_result = self._build_result(
                        task_outputs=task_outputs,
                        workflow_results=workflow_results,
                        completed=completed,
                        failed=failed,
                        skipped=skipped,
                        paused=True,
                        workflow_id=workflow_id,
                    )
                    break

                if (
                    time.time() - start_time_all
                    > workflow_timeout
                ):
                    logger.warning(
                        "[Executor] Workflow %s timed out.",
                        workflow_id,
                    )

                    self.statistics["timeouts"] += 1

                    paused_result = self._build_result(
                        task_outputs=task_outputs,
                        workflow_results=workflow_results,
                        completed=completed,
                        failed=failed,
                        skipped=skipped,
                        paused=True,
                        workflow_id=workflow_id,
                    )

                    if self.event_bus:
                        try:
                            await self.event_bus.publish(
                                Event(
                                    type=event_types.WORKFLOW_PAUSED,
                                    source="executor",
                                    data={
                                        "workflow_id": workflow_id,
                                        "reason": "timeout",
                                    },
                                )
                            )
                        except Exception:
                            logger.exception(
                                "[Executor] Failed publishing timeout event."
                            )

                    break

                ready_tasks = [
                    task
                    for task in tasks
                    if (
                        str(getattr(task, "id", ""))
                        not in executed
                        and getattr(
                            task,
                            "is_ready",
                            lambda _completed: False,
                        )(completed)
                    )
                ]

                if not ready_tasks:
                    awaiting_confirmation_tasks = [
                        task
                        for task in tasks
                        if (
                            str(getattr(task, "id", ""))
                            not in executed
                            and getattr(
                                task,
                                "status",
                                None,
                            )
                            == "awaiting_confirmation"
                        )
                    ]

                    if awaiting_confirmation_tasks:
                        pending_task = (
                            awaiting_confirmation_tasks[0]
                        )

                        plan.status = (
                            "awaiting_confirmation"
                        )

                        plan.completed_tasks = list(
                            completed
                        )
                        plan.failed_tasks = list(
                            failed
                        )
                        plan.skipped_tasks = list(
                            skipped
                        )

                        paused_result = self._build_result(
                            task_outputs=task_outputs,
                            workflow_results=workflow_results,
                            completed=completed,
                            failed=failed,
                            skipped=skipped,
                            paused=True,
                            requires_confirmation=True,
                            pending_task_id=str(
                                getattr(
                                    pending_task,
                                    "id",
                                    "",
                                )
                            ),
                            pending_action_name=getattr(
                                pending_task,
                                "action_name",
                                None,
                            ),
                            pending_action_params=copy.deepcopy(
                                getattr(
                                    pending_task,
                                    "params",
                                    {},
                                )
                                or {}
                            ),
                            workflow_id=workflow_id,
                        )

                        self.statistics["paused"] += 1

                        await self._persist_workflow_state(
                            workflow_id,
                            {
                                "status": "awaiting_confirmation",
                                "goal": getattr(
                                    plan,
                                    "goal",
                                    "",
                                ),
                                **paused_result,
                            },
                        )

                        break

                    # No task can proceed and no confirmation is pending.
                    remaining = [
                        task
                        for task in tasks
                        if str(getattr(task, "id", ""))
                        not in executed
                    ]

                    if remaining:
                        logger.error(
                            "[Executor] Unresolvable dependency tree."
                        )

                        error = (
                            "Unresolvable task dependencies."
                        )

                        for task in remaining:
                            task.mark_failed(error)

                            task_id = str(
                                getattr(
                                    task,
                                    "id",
                                    "",
                                )
                            )

                            if task_id not in failed:
                                failed.append(task_id)

                            workflow_results[task_id] = {
                                "type": getattr(
                                    task,
                                    "task_type",
                                    "",
                                ),
                                "target": self._task_target(task),
                                "status": "failed",
                                "error": error,
                            }

                            executed.add(task_id)

                    break

                # Highest priority first. Stable order is preserved for ties.
                ready_tasks.sort(
                    key=lambda task: self._safe_int(
                        getattr(
                            task,
                            "priority",
                            1,
                        ),
                        1,
                    ),
                    reverse=True,
                )

                ready_ids = {
                    str(getattr(task, "id", ""))
                    for task in ready_tasks
                }

                # Tasks whose dependencies are also ready should not run in
                # the same batch. Independent ready tasks may run together.
                parallel_batch = []

                for task in ready_tasks:
                    dependencies = [
                        str(dep)
                        for dep in (
                            getattr(
                                task,
                                "depends_on",
                                [],
                            )
                            or []
                        )
                    ]

                    if not any(
                        dependency in ready_ids
                        for dependency in dependencies
                    ):
                        parallel_batch.append(task)

                if not parallel_batch:
                    parallel_batch = [
                        ready_tasks[0]
                    ]

                if len(parallel_batch) > 1:
                    self.statistics["parallel_tasks"] += len(
                        parallel_batch
                    )

                async def execute_single_task(task):
                    task_id = str(
                        getattr(task, "id", "")
                    )

                    failed_dependencies = [
                        str(dependency)
                        for dependency in (
                            getattr(
                                task,
                                "depends_on",
                                [],
                            )
                            or []
                        )
                        if (
                            str(dependency) in failed
                            or str(dependency) in skipped
                        )
                    ]

                    if failed_dependencies:
                        reason = (
                            "Skipped because dependency failed: "
                            + ", ".join(
                                failed_dependencies
                            )
                        )

                        task.mark_skipped(reason)

                        workflow_results[task_id] = {
                            "type": getattr(
                                task,
                                "task_type",
                                "",
                            ),
                            "target": self._task_target(task),
                            "status": "skipped",
                            "error": reason,
                        }

                        if task_id not in skipped:
                            skipped.append(task_id)

                        executed.add(task_id)

                        await self._publish_event(
                            event_types.TASK_SKIPPED,
                            {
                                "task_id": task_id,
                                "reason": reason,
                            },
                        )

                        return "skipped"

                    try:
                        resolved_input = self._resolve_value(
                            copy.deepcopy(
                                getattr(
                                    task,
                                    "input",
                                    {},
                                )
                                or {}
                            ),
                            task_outputs,
                        )

                        resolved_params = self._resolve_value(
                            copy.deepcopy(
                                getattr(
                                    task,
                                    "params",
                                    {},
                                )
                                or {}
                            ),
                            task_outputs,
                        )

                    except Exception as exc:
                        error = str(exc)

                        task.mark_failed(error)

                        workflow_results[task_id] = {
                            "type": getattr(
                                task,
                                "task_type",
                                "",
                            ),
                            "target": self._task_target(task),
                            "status": "failed",
                            "error": error,
                        }

                        if task_id not in failed:
                            failed.append(task_id)

                        executed.add(task_id)

                        await self._publish_event(
                            event_types.TASK_FAILED,
                            {
                                "task_id": task_id,
                                "error": error,
                            },
                        )

                        return "failed"

                    # Preserve explicit dependency outputs in the execution
                    # context without mutating the Task's original input.
                    for dependency in (
                        getattr(
                            task,
                            "depends_on",
                            [],
                        )
                        or []
                    ):
                        dependency = str(dependency)

                        if dependency in task_outputs:
                            resolved_input[
                                f"context_from_{dependency}"
                            ] = copy.deepcopy(
                                task_outputs[dependency]
                            )

                    task.mark_running()

                    self.statistics["tasks"] += 1

                    await self._publish_event(
                        event_types.TASK_STARTED,
                        {
                            "task_id": task_id,
                            "name": getattr(
                                task,
                                "name",
                                f"Task {task_id}",
                            ),
                        },
                    )

                    task_start = time.time()
                    perf_start = time.perf_counter()

                    task_timeout = self._safe_timeout(
                        getattr(
                            task,
                            "timeout",
                            self.DEFAULT_TASK_TIMEOUT,
                        ),
                        self.DEFAULT_TASK_TIMEOUT,
                        self.MAX_TASK_TIMEOUT,
                    )

                    resource_name = getattr(
                        task,
                        "resource",
                        None,
                    )

                    lock = (
                        self._get_resource_lock(
                            resource_name
                        )
                        if resource_name
                        else None
                    )

                    result = None

                    try:
                        if lock:
                            await lock.acquire()

                        if getattr(
                            task,
                            "is_action",
                            lambda: False,
                        )():
                            result = await asyncio.wait_for(
                                self._execute_action(
                                    task=task,
                                    params=resolved_params,
                                    action_manager=action_manager,
                                    tool_manager=tool_manager,
                                    base_context=base_context,
                                ),
                                timeout=task_timeout,
                            )

                        elif getattr(
                            task,
                            "task_type",
                            "skill",
                        ) == "tool":
                            result = await asyncio.wait_for(
                                self._execute_tool(
                                    task=task,
                                    params=resolved_params,
                                    resolved_input=resolved_input,
                                    tool_manager=tool_manager,
                                    base_context=base_context,
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
                            "error": (
                                f"Task timed out after "
                                f"{task_timeout} seconds."
                            ),
                            "source": self._task_target(task),
                        }

                        await self._publish_event(
                            event_types.TASK_TIMEOUT,
                            {
                                "task_id": task_id,
                                "timeout": task_timeout,
                            },
                        )

                    except asyncio.CancelledError:
                        result = {
                            "success": False,
                            "paused": True,
                            "requires_confirmation": False,
                            "data": {},
                            "error": "Task cancelled.",
                            "source": self._task_target(task),
                        }

                    except Exception as exc:
                        result = {
                            "success": False,
                            "paused": False,
                            "requires_confirmation": False,
                            "data": {},
                            "error": str(exc),
                            "source": self._task_target(task),
                        }

                    finally:
                        if lock and lock.locked():
                            lock.release()

                    elapsed_ms = (
                        time.perf_counter() - perf_start
                    ) * 1000.0

                    task.execution_time_ms = elapsed_ms

                    previous_average = float(
                        self.statistics.get(
                            "average_task_time",
                            0.0,
                        )
                    )

                    completed_sample_count = max(
                        1,
                        self.statistics.get(
                            "tasks",
                            1,
                        ),
                    )

                    self.statistics["average_task_time"] = (
                        (
                            previous_average
                            * max(
                                0,
                                completed_sample_count - 1,
                            )
                        )
                        + elapsed_ms
                    ) / completed_sample_count

                    if result.get(
                        "requires_confirmation",
                        False,
                    ):
                        task.mark_awaiting_confirmation()

                        confirmation_data = (
                            result.get(
                                "data",
                                {},
                            )
                            or {}
                        )

                        pending_task_id = (
                            confirmation_data.get(
                                "task_id"
                            )
                            or task_id
                        )

                        pending_action_name = (
                            confirmation_data.get(
                                "action_name"
                            )
                            or getattr(
                                task,
                                "action_name",
                                None,
                            )
                        )

                        pending_action_params = (
                            confirmation_data.get(
                                "params"
                            )
                            or resolved_params
                            or {}
                        )

                        workflow_results[task_id] = {
                            "type": getattr(
                                task,
                                "task_type",
                                "",
                            ),
                            "target": pending_action_name,
                            "status": (
                                "awaiting_confirmation"
                            ),
                            "execution_time_ms": elapsed_ms,
                        }

                        logger.info(
                            "[Executor] Workflow paused for confirmation. "
                            "task_id=%s action=%s",
                            pending_task_id,
                            pending_action_name,
                        )

                        return self._build_result(
                            task_outputs=task_outputs,
                            workflow_results=workflow_results,
                            completed=completed,
                            failed=failed,
                            skipped=skipped,
                            paused=True,
                            requires_confirmation=True,
                            pending_task_id=str(
                                pending_task_id
                            ),
                            pending_action_name=(
                                pending_action_name
                            ),
                            pending_action_params=(
                                pending_action_params
                            ),
                            workflow_id=workflow_id,
                        )

                    if self._result_success(result):
                        output = self._result_data(
                            result
                        )

                        if output is None:
                            output = {}

                        if not isinstance(output, dict):
                            output = {
                                "result": output
                            }

                        task.mark_completed(output)

                        task_outputs[task_id] = copy.deepcopy(
                            output
                        )

                        workflow_results[task_id] = {
                            "type": getattr(
                                task,
                                "task_type",
                                "",
                            ),
                            "target": result.get(
                                "source"
                            )
                            if isinstance(
                                result,
                                dict,
                            )
                            else self._task_target(task),
                            "status": "completed",
                            "output": copy.deepcopy(
                                output
                            ),
                            "execution_time_ms": elapsed_ms,
                        }

                        if task_id not in completed:
                            completed.append(task_id)

                        self.statistics["completed"] += 1

                        await self._publish_event(
                            event_types.TASK_COMPLETED,
                            {
                                "task_id": task_id,
                                "result": output,
                            },
                        )

                    else:
                        error = (
                            self._result_error(result)
                            or "Task execution failed."
                        )

                        task.mark_failed(error)

                        workflow_results[task_id] = {
                            "type": getattr(
                                task,
                                "task_type",
                                "",
                            ),
                            "target": result.get(
                                "source"
                            )
                            if isinstance(
                                result,
                                dict,
                            )
                            else self._task_target(task),
                            "status": "failed",
                            "error": error,
                            "execution_time_ms": elapsed_ms,
                        }

                        if task_id not in failed:
                            failed.append(task_id)

                        self.statistics["failed"] += 1

                        await self._publish_event(
                            event_types.TASK_FAILED,
                            {
                                "task_id": task_id,
                                "error": error,
                            },
                        )

                        if base_context.get(
                            "transactional",
                            False,
                        ):
                            await self.rollback_workflow(
                                plan,
                                completed,
                                base_context,
                            )

                        # Replanning is opt-in. CognitiveCore/Planner may
                        # request it explicitly through context.
                        if (
                            base_context.get(
                                "allow_dynamic_replan",
                                False,
                            )
                            and failed
                        ):
                            replan_result = (
                                await self.replan_if_needed(
                                    plan=plan,
                                    failed_tasks=failed,
                                    completed=completed,
                                    context=base_context,
                                    failed_task=task,
                                    failure_reason=error,
                                )
                            )

                            if replan_result:
                                return replan_result

                    task_end = time.time()

                    execution_report = {
                        "workflow": workflow_id,
                        "task_id": task_id,
                        "task_name": getattr(
                            task,
                            "name",
                            f"Task {task_id}",
                        ),
                        "status": getattr(
                            task,
                            "status",
                            None,
                        ),
                        "started_at": task_start,
                        "finished_at": task_end,
                        "duration": round(
                            task_end - task_start,
                            3,
                        ),
                        "output": copy.deepcopy(
                            task_outputs.get(task_id)
                        ),
                        "success": (
                            getattr(
                                task,
                                "status",
                                None,
                            )
                            == "completed"
                        ),
                    }

                    self._record_history(
                        execution_report
                    )

                    world_model = base_context.get(
                        "world_model"
                    ) or getattr(
                        self,
                        "world_model",
                        None,
                    )

                    if world_model is not None:
                        try:
                            await world_model.record_execution(
                                execution_report
                            )
                        except Exception:
                            logger.exception(
                                "[Executor] World model execution "
                                "record failed."
                            )

                    await self._publish_event(
                        event_types.TASK_FINISHED,
                        execution_report,
                    )

                    executed.add(task_id)

                    await self._persist_workflow_state(
                        workflow_id,
                        {
                            "status": "running",
                            "goal": getattr(
                                plan,
                                "goal",
                                "",
                            ),
                            "task_outputs": task_outputs,
                            "workflow_results": workflow_results,
                            "completed": completed,
                            "failed": failed,
                            "skipped": skipped,
                        },
                    )

                    return "done"

                batch_results = await asyncio.gather(
                    *(
                        execute_single_task(task)
                        for task in parallel_batch
                    ),
                    return_exceptions=False,
                )

                # A confirmation pause is a workflow-level state, so stop
                # immediately after the batch.
                confirmation_result = next(
                    (
                        item
                        for item in batch_results
                        if isinstance(item, dict)
                        and item.get(
                            "requires_confirmation",
                            False,
                        )
                    ),
                    None,
                )

                if confirmation_result:
                    plan.completed_tasks = list(completed)
                    plan.failed_tasks = list(failed)
                    plan.skipped_tasks = list(skipped)
                    plan.status = "awaiting_confirmation"

                    self.statistics["paused"] += 1

                    await self._persist_workflow_state(
                        workflow_id,
                        {
                            "status": "awaiting_confirmation",
                            "goal": getattr(
                                plan,
                                "goal",
                                "",
                            ),
                            **confirmation_result,
                        },
                    )

                    return confirmation_result

                progress = await self.update_progress(
                    plan,
                    completed,
                    [
                        str(
                            getattr(
                                task,
                                "id",
                                "",
                            )
                        )
                        for task in parallel_batch
                    ],
                    start_time_all,
                )

                logger.info(
                    "[Executor] Progress: %.2f%% | Remaining: %d",
                    progress["percent_completed"],
                    progress["remaining"],
                )

            if paused_result is not None:
                plan.completed_tasks = list(completed)
                plan.failed_tasks = list(failed)
                plan.skipped_tasks = list(skipped)

                return paused_result

        except asyncio.CancelledError:
            logger.info(
                "[Executor] Workflow %s cancelled by asyncio.",
                workflow_id,
            )

            self._cancel_requested.add(workflow_id)

            return self._build_result(
                task_outputs=task_outputs,
                workflow_results=workflow_results,
                completed=completed,
                failed=failed,
                skipped=skipped,
                paused=True,
                workflow_id=workflow_id,
            )

        finally:
            self._active_workflows.discard(
                workflow_id
            )

            self._cancel_requested.discard(
                workflow_id
            )

        # -----------------------------------------------------
        # FINALIZE WORKFLOW
        # -----------------------------------------------------

        plan.completed_tasks = list(completed)
        plan.failed_tasks = list(failed)
        plan.skipped_tasks = list(skipped)

        success = (
            not failed
            and not skipped
            and len(completed) == len(tasks)
        )

        if success:
            try:
                plan.mark_completed()
            except Exception:
                plan.status = "completed"

        else:
            try:
                plan.mark_failed(
                    "One or more tasks failed or were skipped."
                )
            except Exception:
                plan.status = "failed"

        elapsed_all_ms = (
            time.time() - start_time_all
        ) * 1000.0

        previous_average = float(
            self.statistics.get(
                "average_time",
                0.0,
            )
        )

        workflow_count = max(
            1,
            self.statistics.get(
                "workflows",
                1,
            ),
        )

        self.statistics["average_time"] = (
            (
                previous_average
                * max(
                    0,
                    workflow_count - 1,
                )
            )
            + elapsed_all_ms
        ) / workflow_count

        self.statistics["longest_workflow"] = max(
            float(
                self.statistics.get(
                    "longest_workflow",
                    0.0,
                )
            ),
            elapsed_all_ms,
        )

        total_workflows = max(
            1,
            self.statistics.get(
                "workflows",
                1,
            ),
        )

        successful_workflows = max(
            0,
            total_workflows
            - self.statistics.get(
                "failed",
                0,
            ),
        )

        self.statistics["success_rate"] = max(
            0.0,
            min(
                1.0,
                successful_workflows
                / total_workflows,
            ),
        )

        final_result = self._build_result(
            task_outputs=task_outputs,
            workflow_results=workflow_results,
            completed=completed,
            failed=failed,
            skipped=skipped,
            paused=False,
            requires_confirmation=False,
            workflow_id=workflow_id,
        )

        self._record_history(
            {
                "workflow_id": workflow_id,
                "goal": getattr(
                    plan,
                    "goal",
                    "",
                ),
                "success": success,
                "duration_ms": elapsed_all_ms,
                "timestamp": time.time(),
            }
        )

        await self._persist_workflow_state(
            workflow_id,
            {
                "status": (
                    "completed"
                    if success
                    else "failed"
                ),
                "goal": getattr(
                    plan,
                    "goal",
                    "",
                ),
                **final_result,
            },
        )

        event_name = (
            event_types.WORKFLOW_COMPLETED
            if success
            else event_types.WORKFLOW_FAILED
        )

        await self._publish_event(
            event_name,
            {
                "workflow_id": workflow_id,
                "success": success,
            },
        )

        return final_result

    # =========================================================
    # TIMEOUT / EVENTS
    # =========================================================

    @staticmethod
    def _safe_timeout(
        value: Any,
        default: float,
        maximum: float,
    ) -> float:
        try:
            value = float(value)
        except (TypeError, ValueError):
            value = default

        if value <= 0:
            value = default

        return min(
            value,
            maximum,
        )

    async def _publish_event(
        self,
        event_type,
        data: Dict[str, Any],
    ):
        if self.event_bus is None:
            return

        try:
            await self.event_bus.publish(
                Event(
                    type=event_type,
                    source="executor",
                    data=copy.deepcopy(data),
                )
            )
        except Exception:
            logger.exception(
                "[Executor] Event publication failed: %s",
                event_type,
            )

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
        if self.skill_manager is None:
            return {
                "success": False,
                "paused": False,
                "requires_confirmation": False,
                "data": {},
                "error": "Skill manager is unavailable.",
                "source": getattr(
                    task,
                    "skill",
                    "",
                ),
            }

        attempt = 0
        max_retries = max(
            0,
            self._safe_int(
                getattr(
                    task,
                    "max_retries",
                    0,
                ),
                0,
            ),
        )
        max_attempts = max_retries + 1

        last_error = None

        while attempt < max_attempts:
            exec_context = dict(
                base_context or {}
            )
            exec_context["task_input"] = copy.deepcopy(
                resolved_input
            )
            exec_context["task_id"] = str(
                getattr(
                    task,
                    "id",
                    "",
                )
            )
            exec_context["workflow_goal"] = getattr(
                plan,
                "goal",
                "",
            )

            try:
                response: SkillResponse = (
                    await self.skill_manager.execute_skill(
                        getattr(
                            task,
                            "skill",
                            "",
                        ),
                        resolved_input.get(
                            "query",
                            getattr(
                                plan,
                                "goal",
                                "",
                            ),
                        ),
                        exec_context,
                    )
                )

            except asyncio.CancelledError:
                raise

            except Exception as exc:
                logger.exception(
                    "[Executor] Skill %s crashed.",
                    getattr(
                        task,
                        "skill",
                        "",
                    ),
                )

                response = None
                last_error = str(exc)

            if (
                response is not None
                and self.verifier.verify(
                    getattr(
                        task,
                        "id",
                        "",
                    ),
                    response,
                )
            ):
                return {
                    "success": True,
                    "paused": False,
                    "requires_confirmation": False,
                    "data": getattr(
                        response,
                        "data",
                        {},
                    )
                    or {},
                    "error": None,
                    "source": getattr(
                        task,
                        "skill",
                        "",
                    ),
                }

            if response is not None:
                last_error = (
                    getattr(
                        response,
                        "error",
                        None,
                    )
                    or "Skill execution failed."
                )

            if not last_error:
                last_error = "Skill execution failed."

            lowered = str(
                last_error
            ).lower()

            if any(
                phrase in lowered
                for phrase in NON_RETRYABLE_PHRASES
            ):
                break

            attempt += 1

            try:
                task.retry_count = attempt
            except Exception:
                pass

            if attempt < max_attempts:
                logger.warning(
                    "[Executor] Retrying skill task %s (%d/%d)",
                    getattr(
                        task,
                        "id",
                        "",
                    ),
                    attempt,
                    max_attempts,
                )

                await self._publish_event(
                    event_types.TASK_RETRY,
                    {
                        "task_id": getattr(
                            task,
                            "id",
                            "",
                        ),
                        "attempt": attempt,
                        "max_attempts": max_attempts,
                    },
                )

                await asyncio.sleep(
                    min(
                        0.25 * attempt,
                        2.0,
                    )
                )

        return {
            "success": False,
            "paused": False,
            "requires_confirmation": False,
            "data": {},
            "error": str(
                last_error
                or "Skill execution failed."
            ),
            "source": getattr(
                task,
                "skill",
                "",
            ),
        }

    # =========================================================
    # TOOL EXECUTION
    # =========================================================

    async def _execute_tool(
        self,
        task,
        params,
        resolved_input,
        tool_manager,
        base_context,
    ) -> Dict[str, Any]:
        if tool_manager is None:
            return {
                "success": False,
                "paused": False,
                "requires_confirmation": False,
                "data": {},
                "error": "Tool manager is unavailable.",
                "source": getattr(
                    task,
                    "skill",
                    "",
                )
                or getattr(
                    task,
                    "action_name",
                    "",
                ),
            }

        tool_name = (
            getattr(
                task,
                "action_name",
                None,
            )
            or getattr(
                task,
                "skill",
                None,
            )
            or params.get(
                "tool",
                "",
            )
        )

        tool_name = str(
            tool_name or ""
        ).strip()

        if not tool_name:
            return {
                "success": False,
                "paused": False,
                "requires_confirmation": False,
                "data": {},
                "error": "Tool name is missing.",
                "source": "",
            }

        # ToolManager implementations differ across Phase-9/Phase-11
        # revisions, so prefer the canonical execute() contract while
        # retaining a narrow compatibility fallback.
        try:
            execute_method = getattr(
                tool_manager,
                "execute",
                None,
            )

            if not callable(execute_method):
                return {
                    "success": False,
                    "paused": False,
                    "requires_confirmation": False,
                    "data": {},
                    "error": "Tool manager has no execute method.",
                    "source": tool_name,
                }

            payload = dict(
                params or {}
            )

            if resolved_input:
                payload.setdefault(
                    "input",
                    copy.deepcopy(
                        resolved_input
                    ),
                )

            try:
                tool_result = await execute_method(
                    tool_name,
                    payload,
                )
            except TypeError:
                tool_result = await execute_method(
                    tool_name=tool_name,
                    params=payload,
                    context=base_context,
                )

            if isinstance(tool_result, dict):
                success = bool(
                    tool_result.get(
                        "success",
                        False,
                    )
                )
                data = tool_result.get(
                    "data",
                    tool_result.get(
                        "result",
                        {},
                    ),
                )
                error = tool_result.get(
                    "error"
                )

            else:
                success = bool(
                    getattr(
                        tool_result,
                        "success",
                        False,
                    )
                )
                data = getattr(
                    tool_result,
                    "data",
                    None,
                )
                error = getattr(
                    tool_result,
                    "error",
                    None,
                )

            return {
                "success": success,
                "paused": False,
                "requires_confirmation": False,
                "data": data or {},
                "error": str(error) if error else None,
                "source": tool_name,
            }

        except asyncio.CancelledError:
            raise

        except Exception as exc:
            logger.exception(
                "[Executor] Tool %s failed.",
                tool_name,
            )

            return {
                "success": False,
                "paused": False,
                "requires_confirmation": False,
                "data": {},
                "error": str(exc),
                "source": tool_name,
            }

    # =========================================================
    # ACTION EXECUTION
    # =========================================================

    async def _execute_action(
        self,
        task,
        params,
        action_manager,
        tool_manager=None,
        base_context=None,
    ) -> Dict[str, Any]:
        if action_manager is None:
            return {
                "success": False,
                "paused": False,
                "requires_confirmation": False,
                "data": {},
                "error": "Action manager is unavailable.",
                "source": getattr(
                    task,
                    "action_name",
                    "",
                ),
            }

        actions = getattr(
            action_manager,
            "actions",
            {},
        )

        action_name = str(
            getattr(
                task,
                "action_name",
                "",
            )
            or ""
        ).strip()

        if action_name not in actions:
            return {
                "success": False,
                "paused": False,
                "requires_confirmation": False,
                "data": {},
                "error": (
                    f"Action '{action_name}' "
                    "is not registered."
                ),
                "source": action_name,
            }

        action = actions[action_name]

        permission_level = str(
            getattr(
                action,
                "permission_level",
                "confirm",
            )
            or "confirm"
        ).lower().strip()

        # File reads are safe; writes retain confirmation.
        if action_name == "file_action":
            file_mode = str(
                (params or {}).get(
                    "mode",
                    "",
                )
            ).lower().strip()

            if file_mode == "read":
                permission_level = "safe"

            elif file_mode == "write":
                permission_level = "confirm"

        confirmation_required = (
            bool(
                getattr(
                    task,
                    "requires_confirmation",
                    False,
                )
            )
            or permission_level in {
                "confirm",
                "confirmation",
                "approval",
                "high",
                "dangerous",
            }
        )

        confirmed = bool(
            getattr(
                task,
                "confirmed",
                False,
            )
        )

        if (
            confirmation_required
            and not confirmed
        ):
            logger.info(
                "[Executor] Task %s requires confirmation "
                "before action '%s'.",
                getattr(
                    task,
                    "id",
                    "",
                ),
                action_name,
            )

            return {
                "success": False,
                "paused": True,
                "requires_confirmation": True,
                "data": {
                    "action_name": action_name,
                    "params": copy.deepcopy(
                        params or {}
                    ),
                    "task_id": str(
                        getattr(
                            task,
                            "id",
                            "",
                        )
                    ),
                },
                "error": None,
                "source": action_name,
            }

        try:
            action_result = await action_manager.execute_action(
                action_name=action_name,
                params=params,
                confirmed=confirmed,
            )

        except asyncio.CancelledError:
            raise

        except Exception as exc:
            logger.exception(
                "[Executor] Action %s failed.",
                action_name,
            )

            return {
                "success": False,
                "paused": False,
                "requires_confirmation": False,
                "data": {},
                "error": str(exc),
                "source": action_name,
            }

        return {
            "success": bool(
                getattr(
                    action_result,
                    "success",
                    False,
                )
            ),
            "paused": False,
            "requires_confirmation": False,
            "data": getattr(
                action_result,
                "data",
                {},
            )
            or {},
            "error": getattr(
                action_result,
                "error",
                None,
            ),
            "source": action_name,
        }

    # =========================================================
    # HEALTH
    # =========================================================

    def health(self) -> Dict[str, Any]:
        return {
            "status": "healthy",
            "version": self.EXECUTOR_VERSION,
            "skill_manager": self.skill_manager is not None,
            "action_manager": self.action_manager is not None,
            "tool_manager": self.tool_manager is not None,
            "planner": self.planner is not None,
            "event_bus": self.event_bus is not None,
            "agent_manager": self.agent_manager is not None,
            "agent_coordinator": self.agent_coordinator is not None,
            "active_workflows": len(
                self._active_workflows
            ),
            "paused_workflows": len(
                self.paused_workflows
            ),
            "background_workflows": len(
                self._workflow_tasks
            ),
            "queue_size": self.task_queue.qsize(),
            "statistics": copy.deepcopy(
                self.statistics
            ),
        }

    def last_execution(self):
        if not self.execution_log:
            return None

        return copy.deepcopy(
            self.execution_log[-1]
        )

    def clear_log(self):
        self.execution_log.clear()
