import logging
import re
import time
from typing import Dict, Any

from brain.plan import ExecutionPlan
from brain.verifier import Verifier
from skills.manager import SkillManager
from skills.base import SkillResponse

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


class Executor:
    """
    Phase-3 hybrid executor.

    Executes:
    - skills through SkillManager
    - actions through ActionManager

    Supports:
    - task dependencies
    - output references
    - failure propagation
    - retries
    - execution timing
    """

    def __init__(
        self,
        skill_manager: SkillManager,
        action_manager=None,
    ):
        self.skill_manager = skill_manager
        self.action_manager = action_manager
        self.verifier = Verifier()

    # =========================================================
    # RESULT REFERENCE RESOLUTION
    # =========================================================

    def _extract_value(
        self,
        output: Any,
        field_path: str,
    ) -> Any:
        """
        Resolve nested fields.

        Example:

        output = {
            "user": {
                "name": "ARIA"
            }
        }

        field_path = "user.name"

        -> "ARIA"
        """

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

        # If the entire value is one reference,
        # preserve the original value type.
        if (
            len(matches) == 1
            and matches[0].span()
            == (0, len(value))
        ):

            task_id = matches[0].group(1)
            field = matches[0].group(2)

            output = task_outputs.get(task_id)

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

        # Otherwise interpolate references into text.
        def replace_reference(match):

            task_id = match.group(1)
            field = match.group(2)

            output = task_outputs.get(task_id)

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

        return value

    # =========================================================
    # MAIN EXECUTION
    # =========================================================

    async def execute_plan(
        self,
        plan: ExecutionPlan,
        base_context: Dict[str, Any],
    ) -> Dict[str, Any]:

        task_outputs: Dict[str, Any] = {}

        completed = []
        failed = []
        skipped = []

        workflow_results: Dict[str, Any] = {}

        executed = set()

        # -----------------------------------------------------
        # Resolve ActionManager from context if it wasn't
        # injected directly.
        # -----------------------------------------------------

        action_manager = self.action_manager

        if action_manager is None:

            app_state = base_context.get(
                "app_state"
            )

            if (
                app_state
                and app_state.registry.has(
                    "action_manager"
                )
            ):
                action_manager = app_state.registry.get(
                    "action_manager"
                )

        # -----------------------------------------------------
        # EXECUTION LOOP
        # -----------------------------------------------------

        while len(executed) < len(plan.tasks):

            ready_tasks = [
                task
                for task in plan.tasks
                if (
                    task.id not in executed
                    and all(
                        dep in executed
                        for dep in task.depends_on
                    )
                )
            ]

            if not ready_tasks:

                logger.error(
                    "[Executor] Unresolvable dependency tree."
                )

                remaining = [
                    task
                    for task in plan.tasks
                    if task.id not in executed
                ]

                for task in remaining:

                    task.mark_failed(
                        "Unresolvable task dependencies."
                    )

                    failed.append(task.id)
                    executed.add(task.id)

                break

            # Priority: higher priority first.
            ready_tasks.sort(
                key=lambda task: task.priority,
                reverse=True,
            )

            for task in ready_tasks:

                # ---------------------------------------------
                # FAILED DEPENDENCY
                # ---------------------------------------------

                failed_dependencies = [
                    dep
                    for dep in task.depends_on
                    if dep in failed or dep in skipped
                ]

                if failed_dependencies:

                    reason = (
                        "Skipped because dependency failed: "
                        + ", ".join(
                            failed_dependencies
                        )
                    )

                    task.mark_skipped(reason)

                    workflow_results[task.id] = {
                        "type": task.task_type,
                        "target": (
                            task.action_name
                            if task.is_action()
                            else task.skill
                        ),
                        "status": "skipped",
                        "error": reason,
                    }

                    skipped.append(task.id)
                    executed.add(task.id)

                    continue

                # ---------------------------------------------
                # RESOLVE INPUT REFERENCES
                # ---------------------------------------------

                try:

                    resolved_input = self._resolve_value(
                        dict(task.input),
                        task_outputs,
                    )

                    resolved_params = self._resolve_value(
                        dict(task.params),
                        task_outputs,
                    )

                except Exception as exc:

                    error = str(exc)

                    logger.warning(
                        "[Executor] Task %s reference "
                        "resolution failed: %s",
                        task.id,
                        error,
                    )

                    task.mark_failed(error)

                    workflow_results[task.id] = {
                        "type": task.task_type,
                        "status": "failed",
                        "error": error,
                    }

                    failed.append(task.id)
                    executed.add(task.id)

                    continue

                # Existing dependency context support.
                for dep_id in task.depends_on:

                    if dep_id in task_outputs:

                        resolved_input[
                            f"context_from_{dep_id}"
                        ] = task_outputs[dep_id]

                # ---------------------------------------------
                # EXECUTE
                # ---------------------------------------------

                task.mark_running()

                start_time = time.perf_counter()

                try:

                    if task.is_action():

                        result = await self._execute_action(
                            task=task,
                            params=resolved_params,
                            action_manager=action_manager,
                        )

                    else:

                        result = await self._execute_skill(
                            task=task,
                            resolved_input=resolved_input,
                            plan=plan,
                            base_context=base_context,
                        )

                except Exception as exc:

                    logger.exception(
                        "[Executor] Task %s crashed.",
                        task.id,
                    )

                    result = {
                        "success": False,
                        "data": {},
                        "error": str(exc),
                        "source": (
                            task.action_name
                            if task.is_action()
                            else task.skill
                        ),
                    }

                elapsed_ms = (
                    time.perf_counter()
                    - start_time
                ) * 1000

                task.execution_time_ms = elapsed_ms

                # ---------------------------------------------
                # RESULT
                # ---------------------------------------------

                if result["success"]:

                    output = result.get(
                        "data",
                        {},
                    )

                    if output is None:
                        output = {}

                    if not isinstance(output, dict):
                        output = {
                            "result": output
                        }

                    task.mark_completed(output)

                    task_outputs[task.id] = output

                    workflow_results[task.id] = {
                        "type": task.task_type,
                        "target": result.get(
                            "source"
                        ),
                        "status": "completed",
                        "output": output,
                        "execution_time_ms": elapsed_ms,
                    }

                    completed.append(task.id)

                    logger.info(
                        "[Executor] Task %s completed "
                        "(%s: %s) in %.1f ms",
                        task.id,
                        task.task_type,
                        result.get("source"),
                        elapsed_ms,
                    )

                else:

                    error = (
                        result.get("error")
                        or "Task execution failed."
                    )

                    task.mark_failed(error)

                    workflow_results[task.id] = {
                        "type": task.task_type,
                        "target": result.get(
                            "source"
                        ),
                        "status": "failed",
                        "error": error,
                        "execution_time_ms": elapsed_ms,
                    }

                    failed.append(task.id)

                    logger.warning(
                        "[Executor] Task %s failed: %s",
                        task.id,
                        error,
                    )

                executed.add(task.id)

        # -----------------------------------------------------
        # PLAN STATE
        # -----------------------------------------------------

        plan.completed_tasks = list(
            completed
        )

        plan.failed_tasks = list(
            failed
        )

        return {
            "task_outputs": task_outputs,
            "workflow_results": workflow_results,
            "completed": completed,
            "failed": failed,
            "skipped": skipped,
            "success": (
                len(failed) == 0
                and len(skipped) == 0
            ),
        }

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
        max_attempts = (
            task.max_retries + 1
        )

        last_error = None

        while attempt < max_attempts:

            exec_context = dict(
                base_context
            )

            exec_context[
                "task_input"
            ] = resolved_input

            res: SkillResponse = (
                await self.skill_manager.execute_skill(
                    task.skill,
                    resolved_input.get(
                        "query",
                        plan.goal,
                    ),
                    exec_context,
                )
            )

            if self.verifier.verify(
                task.id,
                res,
            ):

                return {
                    "success": True,
                    "data": res.data or {},
                    "error": None,
                    "source": task.skill,
                }

            last_error = (
                res.error
                or "Skill execution failed."
            )

            lowered = last_error.lower()

            non_retryable = any(
                phrase in lowered
                for phrase
                in NON_RETRYABLE_PHRASES
            )

            if non_retryable:
                break

            attempt += 1
            task.retry_count = attempt

            if attempt < max_attempts:

                logger.warning(
                    "[Executor] Retrying skill task "
                    "%s (%d/%d)",
                    task.id,
                    attempt + 1,
                    max_attempts,
                )

        return {
            "success": False,
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
                "data": {},
                "error": (
                    "Action manager is unavailable."
                ),
                "source": task.action_name,
            }

        if (
            task.action_name
            not in action_manager.actions
        ):

            return {
                "success": False,
                "data": {},
                "error": (
                    f"Action '{task.action_name}' "
                    "is not registered."
                ),
                "source": task.action_name,
            }

        action = action_manager.actions[
            task.action_name
        ]

        permission_level = getattr(
            action,
            "permission_level",
            "confirm",
        )

        # -----------------------------------------------------
        # Confirmation-sensitive actions
        #
        # Multi-step confirmation will be handled by
        # CognitiveCore. Executor must not silently bypass it.
        # -----------------------------------------------------

        if (
            permission_level == "confirm"
            and not task.confirmed
        ):

            task.mark_awaiting_confirmation()

            return {
                "success": False,
                "data": {
                    "requires_confirmation": True,
                    "action_name": task.action_name,
                    "params": params,
                    "task_id": task.id,
                },
                "error": "Action requires confirmation.",
                "source": task.action_name,
            }

        action_result = (
            await action_manager.execute_action(
                action_name=task.action_name,
                params=params,
                confirmed=task.confirmed,
            )
        )

        return {
            "success": bool(
                action_result.success
            ),
            "data": (
                action_result.data
                or {}
            ),
            "error": action_result.error,
            "source": task.action_name,
        }