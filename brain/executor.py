import logging
import re
import time
from typing import Dict, Any, Optional, List, Set

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

    IMPORTANT:

    Confirmation-required actions do NOT count as failures.

    Instead execution returns:

        {
            "success": False,
            "paused": True,
            "requires_confirmation": True,
            ...
        }

    CognitiveCore can then store the ExecutionPlan and progress
    inside StateManager and resume execution after confirmation.
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
        Resolve a nested value from a previous task output.

        Example:

            output = {
                "user": {
                    "name": "ARIA"
                }
            }

            field_path = "user.name"

        Returns:

            "ARIA"
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
        """
        Resolve task references inside a string.

        Example:

            "{{1.content}}"

        or:

            "Send this message: {{1.content}}"
        """

        matches = list(
            REFERENCE_PATTERN.finditer(value)
        )

        if not matches:
            return value

        # -----------------------------------------------------
        # Entire string is exactly one reference.
        #
        # Preserve the original value type.
        # -----------------------------------------------------

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

        # -----------------------------------------------------
        # Reference embedded inside normal text.
        # -----------------------------------------------------

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
        """
        Recursively resolve task references inside strings,
        dictionaries, lists and tuples.
        """

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
        """
        Resolve ActionManager either from dependency injection
        or from the application service registry.
        """

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
        """
        Produce one consistent workflow result structure.
        """

        return {
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

            # Paused is not failure, but the objective is not
            # complete yet, so success remains False until the
            # workflow actually finishes.
            "success": (
                not paused
                and len(failed) == 0
                and len(skipped) == 0
            ),
        }

    # =========================================================
    # MAIN EXECUTION
    # =========================================================

    async def execute_plan(
        self,
        plan: ExecutionPlan,
        base_context: Dict[str, Any],
        resume_state: Optional[Dict[str, Any]] = None,
        confirmed_task_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Execute or resume an ExecutionPlan.

        resume_state may contain:

            {
                "task_outputs": {...},
                "completed": [...],
                "failed": [...],
                "skipped": [...]
            }

        confirmed_task_id identifies the task which the user has
        explicitly approved while resuming a paused workflow.
        """

        base_context = base_context or {}
        resume_state = resume_state or {}

        # -----------------------------------------------------
        # RESTORE PREVIOUS WORKFLOW PROGRESS
        # -----------------------------------------------------

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

        # Completed / failed / skipped tasks have already been
        # processed and must not run again.
        executed: Set[str] = set(
            completed
            + failed
            + skipped
        )

        # -----------------------------------------------------
        # NORMALIZE TASK STATE DURING RESUME
        # -----------------------------------------------------

        for task in plan.tasks:

            if task.id in completed:

                task.status = "completed"

                if task.id in task_outputs:
                    task.output = task_outputs[
                        task.id
                    ]

            elif task.id in failed:

                task.status = "failed"

            elif task.id in skipped:

                task.status = "skipped"

            else:

                # A previously suspended confirmation task may
                # still say "awaiting_confirmation".
                #
                # Reset it so execution can reconsider it.
                if (
                    task.status
                    == "awaiting_confirmation"
                ):
                    task.status = "pending"

        # -----------------------------------------------------
        # APPLY USER CONFIRMATION
        # -----------------------------------------------------

        if confirmed_task_id:

            matching_task = next(
                (
                    task
                    for task in plan.tasks
                    if task.id
                    == confirmed_task_id
                ),
                None,
            )

            if matching_task is None:

                logger.error(
                    "[Executor] Confirmed workflow task "
                    "%s does not exist.",
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
                )

            if not matching_task.is_action():

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
                )

            matching_task.confirm()

            logger.info(
                "[Executor] Workflow task %s confirmed.",
                confirmed_task_id,
            )

        # -----------------------------------------------------
        # ACTION MANAGER
        # -----------------------------------------------------

        action_manager = (
            self._resolve_action_manager(
                base_context
            )
        )

        # -----------------------------------------------------
        # EXECUTION LOOP
        # -----------------------------------------------------

        while len(executed) < len(
            plan.tasks
        ):

            ready_tasks = [
                task
                for task in plan.tasks
                if (
                    task.id not in executed

                    and all(
                        dependency
                        in executed

                        for dependency
                        in task.depends_on
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

                    error = (
                        "Unresolvable task dependencies."
                    )

                    task.mark_failed(
                        error
                    )

                    if task.id not in failed:
                        failed.append(
                            task.id
                        )

                    workflow_results[
                        task.id
                    ] = {
                        "type": task.task_type,
                        "target": (
                            task.action_name
                            if task.is_action()
                            else task.skill
                        ),
                        "status": "failed",
                        "error": error,
                    }

                    executed.add(
                        task.id
                    )

                break

            # -------------------------------------------------
            # Priority
            # -------------------------------------------------

            ready_tasks.sort(
                key=lambda task: task.priority,
                reverse=True,
            )

            for task in ready_tasks:

                # ---------------------------------------------
                # FAILED DEPENDENCY
                # ---------------------------------------------

                failed_dependencies = [
                    dependency
                    for dependency
                    in task.depends_on
                    if (
                        dependency in failed
                        or dependency in skipped
                    )
                ]

                if failed_dependencies:

                    reason = (
                        "Skipped because dependency failed: "
                        + ", ".join(
                            failed_dependencies
                        )
                    )

                    task.mark_skipped(
                        reason
                    )

                    workflow_results[
                        task.id
                    ] = {
                        "type": task.task_type,
                        "target": (
                            task.action_name
                            if task.is_action()
                            else task.skill
                        ),
                        "status": "skipped",
                        "error": reason,
                    }

                    if task.id not in skipped:
                        skipped.append(
                            task.id
                        )

                    executed.add(
                        task.id
                    )

                    continue

                # ---------------------------------------------
                # RESOLVE REFERENCES
                # ---------------------------------------------

                try:

                    resolved_input = (
                        self._resolve_value(
                            dict(
                                task.input or {}
                            ),
                            task_outputs,
                        )
                    )

                    resolved_params = (
                        self._resolve_value(
                            dict(
                                task.params or {}
                            ),
                            task_outputs,
                        )
                    )

                except Exception as exc:

                    error = str(exc)

                    logger.warning(
                        "[Executor] Task %s reference "
                        "resolution failed: %s",
                        task.id,
                        error,
                    )

                    task.mark_failed(
                        error
                    )

                    workflow_results[
                        task.id
                    ] = {
                        "type": task.task_type,
                        "target": (
                            task.action_name
                            if task.is_action()
                            else task.skill
                        ),
                        "status": "failed",
                        "error": error,
                    }

                    if task.id not in failed:
                        failed.append(
                            task.id
                        )

                    executed.add(
                        task.id
                    )

                    continue

                # ---------------------------------------------
                # DEPENDENCY CONTEXT
                # ---------------------------------------------

                for dep_id in task.depends_on:

                    if dep_id in task_outputs:

                        resolved_input[
                            f"context_from_{dep_id}"
                        ] = task_outputs[
                            dep_id
                        ]

                # ---------------------------------------------
                # EXECUTE TASK
                # ---------------------------------------------

                task.mark_running()

                start_time = (
                    time.perf_counter()
                )

                try:

                    if task.is_action():

                        result = (
                            await self._execute_action(
                                task=task,
                                params=resolved_params,
                                action_manager=action_manager,
                            )
                        )

                    else:

                        result = (
                            await self._execute_skill(
                                task=task,
                                resolved_input=resolved_input,
                                plan=plan,
                                base_context=base_context,
                            )
                        )

                except Exception as exc:

                    logger.exception(
                        "[Executor] Task %s crashed.",
                        task.id,
                    )

                    result = {
                        "success": False,
                        "paused": False,
                        "requires_confirmation": False,
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

                task.execution_time_ms = (
                    elapsed_ms
                )

                # =============================================
                # WORKFLOW PAUSE
                # =============================================

                if result.get(
                    "requires_confirmation"
                ):

                    task.mark_awaiting_confirmation()

                    confirmation_data = (
                        result.get(
                            "data",
                            {}
                        )
                        or {}
                    )

                    workflow_results[
                        task.id
                    ] = {
                        "type": task.task_type,
                        "target": task.action_name,
                        "status": (
                            "awaiting_confirmation"
                        ),
                        "execution_time_ms": (
                            elapsed_ms
                        ),
                    }

                    logger.info(
                        "[Executor] Workflow paused at "
                        "task %s (%s).",
                        task.id,
                        task.action_name,
                    )

                    # IMPORTANT:
                    # Do NOT mark task executed.
                    # Do NOT mark task failed.
                    # Do NOT execute later tasks.
                    #
                    # CognitiveCore will persist this state.

                    plan.completed_tasks = list(
                        completed
                    )

                    plan.failed_tasks = list(
                        failed
                    )

                    return self._build_result(
                        task_outputs=task_outputs,
                        workflow_results=workflow_results,
                        completed=completed,
                        failed=failed,
                        skipped=skipped,
                        paused=True,
                        requires_confirmation=True,
                        pending_task_id=task.id,
                        pending_action_name=(
                            task.action_name
                        ),
                        pending_action_params=(
                            confirmation_data.get(
                                "params",
                                resolved_params,
                            )
                        ),
                    )

                # =============================================
                # SUCCESS
                # =============================================

                if result.get(
                    "success"
                ):

                    output = result.get(
                        "data",
                        {},
                    )

                    if output is None:
                        output = {}

                    if not isinstance(
                        output,
                        dict,
                    ):
                        output = {
                            "result": output
                        }

                    task.mark_completed(
                        output
                    )

                    task_outputs[
                        task.id
                    ] = output

                    workflow_results[
                        task.id
                    ] = {
                        "type": task.task_type,
                        "target": result.get(
                            "source"
                        ),
                        "status": "completed",
                        "output": output,
                        "execution_time_ms": (
                            elapsed_ms
                        ),
                    }

                    if task.id not in completed:
                        completed.append(
                            task.id
                        )

                    logger.info(
                        "[Executor] Task %s completed "
                        "(%s: %s) in %.1f ms",
                        task.id,
                        task.task_type,
                        result.get(
                            "source"
                        ),
                        elapsed_ms,
                    )

                # =============================================
                # FAILURE
                # =============================================

                else:

                    error = (
                        result.get(
                            "error"
                        )
                        or "Task execution failed."
                    )

                    task.mark_failed(
                        error
                    )

                    workflow_results[
                        task.id
                    ] = {
                        "type": task.task_type,
                        "target": result.get(
                            "source"
                        ),
                        "status": "failed",
                        "error": error,
                        "execution_time_ms": (
                            elapsed_ms
                        ),
                    }

                    if task.id not in failed:
                        failed.append(
                            task.id
                        )

                    logger.warning(
                        "[Executor] Task %s failed: %s",
                        task.id,
                        error,
                    )

                executed.add(
                    task.id
                )

        # =====================================================
        # WORKFLOW COMPLETE
        # =====================================================

        plan.completed_tasks = list(
            completed
        )

        plan.failed_tasks = list(
            failed
        )

        success = (
            len(failed) == 0
            and len(skipped) == 0
        )

        logger.info(
            "[Executor] Workflow finished. "
            "success=%s completed=%s failed=%s skipped=%s",
            success,
            completed,
            failed,
            skipped,
        )

        return self._build_result(
            task_outputs=task_outputs,
            workflow_results=workflow_results,
            completed=completed,
            failed=failed,
            skipped=skipped,
            paused=False,
            requires_confirmation=False,
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
        """
        Execute a skill with verification and retry support.
        """

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

            try:

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

            except Exception as exc:

                logger.exception(
                    "[Executor] Skill %s crashed.",
                    task.skill,
                )

                last_error = str(
                    exc
                )

                res = None

            if (
                res is not None
                and self.verifier.verify(
                    task.id,
                    res,
                )
            ):

                return {
                    "success": True,
                    "paused": False,
                    "requires_confirmation": False,
                    "data": res.data or {},
                    "error": None,
                    "source": task.skill,
                }

            if res is not None:

                last_error = (
                    res.error
                    or "Skill execution failed."
                )

            if not last_error:

                last_error = (
                    "Skill execution failed."
                )

            lowered = (
                str(last_error).lower()
            )

            non_retryable = any(
                phrase in lowered
                for phrase
                in NON_RETRYABLE_PHRASES
            )

            if non_retryable:
                break

            attempt += 1

            task.retry_count = (
                attempt
            )

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
        """
        Execute one registered action.

        Confirmation-sensitive actions return a PAUSE signal
        until CognitiveCore resumes the workflow with the
        corresponding task confirmed.
        """

        if action_manager is None:

            return {
                "success": False,
                "paused": False,
                "requires_confirmation": False,
                "data": {},
                "error": (
                    "Action manager is unavailable."
                ),
                "source": task.action_name,
            }

        actions = getattr(
            action_manager,
            "actions",
            {},
        )

        if task.action_name not in actions:

            return {
                "success": False,
                "paused": False,
                "requires_confirmation": False,
                "data": {},
                "error": (
                    f"Action '{task.action_name}' "
                    "is not registered."
                ),
                "source": task.action_name,
            }

        action = actions[
            task.action_name
        ]

        permission_level = getattr(
            action,
            "permission_level",
            "confirm",
        )

        # Operation-specific permission override.
        if task.action_name == "file_action":
            file_mode = str(
                (params or {}).get("mode", "")
            ).lower().strip()

            if file_mode == "read":
                permission_level = "safe"

            elif file_mode == "write":
                permission_level = "confirm"

        # -----------------------------------------------------
        # CONFIRMATION REQUIRED
        # -----------------------------------------------------

        if (
            permission_level == "confirm"
            and not task.confirmed
        ):

            logger.info(
                "[Executor] Task %s requires confirmation "
                "before action '%s'.",
                task.id,
                task.action_name,
            )

            return {
                "success": False,
                "paused": True,
                "requires_confirmation": True,
                "data": {
                    "action_name": (
                        task.action_name
                    ),
                    "params": dict(
                        params or {}
                    ),
                    "task_id": (
                        task.id
                    ),
                },
                "error": None,
                "source": task.action_name,
            }

        # -----------------------------------------------------
        # EXECUTE CONFIRMED / NON-CONFIRM ACTION
        # -----------------------------------------------------

        action_result = (
            await action_manager.execute_action(
                action_name=task.action_name,
                params=params,
                confirmed=bool(
                    task.confirmed
                ),
            )
        )

        return {
            "success": bool(
                action_result.success
            ),

            "paused": False,

            "requires_confirmation": False,

            "data": (
                action_result.data
                or {}
            ),

            "error": (
                action_result.error
            ),

            "source": (
                task.action_name
            ),
        }
