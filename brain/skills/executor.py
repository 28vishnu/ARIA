from typing import List, Dict, Any
from brain.plan import ExecutionPlan
from brain.task import Task
from brain.skills.skill_registry import SkillRegistry

class Executor:
    """Executes the tasks defined in an ExecutionPlan by routing them through the SkillRegistry."""
    def __init__(self, skill_registry: SkillRegistry):
        self.registry = skill_registry

    def execute(self, plan: ExecutionPlan) -> List[Dict[str, Any]]:
        """Iterates through all tasks in the execution plan and executes them via skills."""
        results: List[Dict[str, Any]] = []

        for task in plan.tasks:
            result = self.execute_task(task)
            results.append(result)

        return results

    def execute_task(self, task: Task) -> Dict[str, Any]:
        """Dispatches an individual task to the appropriate skill using the SkillRegistry."""
        # Map task name or default to handler category
        skill_name = "chat"
        if "reason" in task.name:
            skill_name = "reasoning"
        elif "document" in task.name or "summary" in task.name or "summarize" in task.name:
            skill_name = "document"
        elif "memory" in task.name:
            skill_name = "memory"
        elif "search" in task.name:
            skill_name = "search"

        skill = self.registry.get(skill_name)
        skill_result = skill.execute(task)

        return {
            "task_id": task.id,
            "task_name": task.name,
            "status": skill_result.get("status", "completed"),
            "output": skill_result.get("output", "")
        }
