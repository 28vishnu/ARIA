from typing import List, Dict, Any
from brain.plan import ExecutionPlan
from brain.task import Task
from brain.skills.skill_registry import SkillRegistry

class Executor:
    """Executes tasks purely by routing them through the SkillRegistry."""
    def __init__(self, skill_registry: SkillRegistry):
        self.registry = skill_registry

    def execute(self, plan: ExecutionPlan) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for task in plan.tasks:
            result = self.execute_task(task)
            results.append(result)
        return results

    def execute_task(self, task: Task) -> Dict[str, Any]:
        skill = self.registry.get(task.skill)
        if not skill:
            skill = self.registry.get("chat")
        
        skill_result = skill.execute(task)

        return {
            "task_id": task.id,
            "task_name": task.name,
            "skill_used": task.skill,
            "status": skill_result.get("status", "completed"),
            "output": skill_result.get("output", "")
        }
