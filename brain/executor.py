import logging
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
    "unavailable"
]

class Executor:
    def __init__(self, skill_manager: SkillManager):
        self.skill_manager = skill_manager
        self.verifier = Verifier()

    async def execute_plan(self, plan: ExecutionPlan, base_context: Dict[str, Any]) -> Dict[str, Any]:
        task_outputs: Dict[str, Any] = {}

        completed: list[str] = []
        failed: list[str] = []

        workflow_results: Dict[str, Any] = {}

        executed = set()

        while len(executed) < len(plan.tasks):
            ready_tasks = [
                t for t in plan.tasks 
                if t.id not in executed and all(dep in executed for dep in t.depends_on)
            ]

            if not ready_tasks:
                logger.error("[Executor ERROR] Unresolvable task dependency tree.")
                break

            for task in ready_tasks:
                task.status = "running"
                success = False
                res: SkillResponse = SkillResponse(success=False, confidence=0.0, source=task.skill, error="Uninitialized")

                resolved_input = dict(task.input)
                for dep_id in task.depends_on:
                    if dep_id in task_outputs:
                        resolved_input[f"context_from_{dep_id}"] = task_outputs[dep_id]

                attempt = 0
                max_attempts = task.max_retries + 1

                while attempt < max_attempts and not success:
                    start_time = time.perf_counter()

                    exec_context = dict(base_context)
                    exec_context["task_input"] = resolved_input

                    res = await self.skill_manager.execute_skill(
                        task.skill,
                        resolved_input.get("query", plan.goal),
                        exec_context
                    )

                    elapsed_ms = (time.perf_counter() - start_time) * 1000
                    logger.info("[Executor] Task: %s (Skill: %s) | Status: %s | Time: %.1f ms", task.id, task.skill, "Completed" if res.success else "Failed", elapsed_ms)

                    # Check if failure is deterministic/non-retryable (e.g. missing data)
                    err_lower = (res.error or "").lower()
                    is_non_retryable = any(phrase in err_lower for phrase in NON_RETRYABLE_PHRASES)

                    if self.verifier.verify(task.id, res):
                        success = True
                        break
                    elif is_non_retryable:
                        logger.warning("[Executor] Task %s encountered non-retryable result: '%s'. Aborting retries.", task.id, res.error)
                        break
                    else:
                        attempt += 1
                        task.retry_count = attempt
                        if attempt < max_attempts:
                            logger.warning("[Executor] Retrying task %s (Attempt %d/%d)", task.id, attempt + 1, max_attempts)

                if success:
                    task.status = "completed"

                    task.output = res.data

                    task_outputs[task.id] = res.data

                    workflow_results[task.id] = {
                        "skill": task.skill,
                        "status": "completed",
                        "output": res.data
                    }

                    completed.append(task.id)
                    executed.add(task.id)
                else:
                    task.status = "failed"

                    task.error = res.error

                    workflow_results[task.id] = {
                        "skill": task.skill,
                        "status": "failed",
                        "error": res.error
                    }

                    failed.append(task.id)
                    executed.add(task.id)
                    for other_t in plan.tasks:
                        if task.id in other_t.depends_on and other_t.id not in executed:
                            other_t.status = "skipped"
                            executed.add(other_t.id)
                            failed.append(other_t.id)

        return {
            "task_outputs": task_outputs,
            "workflow_results": workflow_results,
            "completed": completed,
            "failed": failed,
            "success": len(failed) == 0
        }
