import logging
import time
from typing import Dict, Any
from brain.plan import ExecutionPlan
from brain.verifier import Verifier
from skills.manager import SkillManager
from skills.base import SkillResponse

logger = logging.getLogger("aria")

class Executor:
    def __init__(self, skill_manager: SkillManager):
        self.skill_manager = skill_manager
        self.verifier = Verifier()

    async def execute_plan(self, plan: ExecutionPlan, base_context: Dict[str, Any]) -> Dict[str, Any]:
        """Resolves dependencies, runs tasks in order, manages state/outputs, handles retries and verification."""
        task_outputs: Dict[str, Any] = {}
        completed: list = []
        failed: list = []
        
        # Build lookup table for tasks
        tasks_map = {t.id: t for t in plan.tasks}
        executed = set()

        while len(executed) < len(plan.tasks):
            # Find all tasks whose dependencies are fully satisfied
            ready_tasks = [
                t for t in plan.tasks 
                if t.id not in executed and all(dep in executed for dep in t.depends_on)
            ]

            if not ready_tasks:
                # Deadlock or unsatisfied circular dependency
                logger.error("[Executor ERROR] Circular dependency or unresolvable task tree detected.")
                break

            for task in ready_tasks:
                task.status = "running"
                success = False
                res: SkillResponse = SkillResponse(success=False, confidence=0.0, source=task.skill, error="Uninitialized")

                # Resolve dynamic input variables from prior task outputs if any
                resolved_input = dict(task.input)
                for dep_id in task.depends_on:
                    if dep_id in task_outputs:
                        resolved_input[f"context_from_{dep_id}"] = task_outputs[dep_id]

                # Execute with retry policy
                while task.retry_count <= task.max_retries and not success:
                    start_time = time.perf_counter()
                    
                    # Construct task-specific execution context
                    exec_context = dict(base_context)
                    exec_context["task_input"] = resolved_input

                    # Route through SkillManager
                    res = await self.skill_manager.route_and_execute(resolved_input.get("query", plan.goal), exec_context)
                    
                    elapsed_ms = (time.perf_counter() - start_time) * 1000
                    logger.info("[Executor] Task: %s (%s) | Status: %s | Time: %.1f ms", task.id, task.skill, "Completed" if res.success else "Failed", elapsed_ms)

                    # Verify output
                    if self.verifier.verify(task.id, res):
                        success = True
                        break
                    else:
                        task.retry_count += 1
                        logger.warning("[Executor] Retrying task %s (Attempt %d/%d)", task.id, task.retry_count, task.max_retries)

                if success:
                    task.status = "completed"
                    task_outputs[task.id] = res.data
                    completed.append(task.id)
                    executed.add(task.id)
                else:
                    task.status = "failed"
                    failed.append(task.id)
                    executed.add(task.id)
                    # Skip dependent downstream tasks
                    for other_t in plan.tasks:
                        if task.id in other_t.depends_on and other_t.id not in executed:
                            other_t.status = "skipped"
                            executed.add(other_t.id)
                            failed.append(other_t.id)

        return {
            "task_outputs": task_outputs,
            "completed": completed,
            "failed": failed,
            "success": len(failed) == 0
        }
