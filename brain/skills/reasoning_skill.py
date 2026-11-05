from brain.skills.base_skill import BaseSkill
from brain.task import Task

class ReasoningSkill(BaseSkill):
    name = "reasoning"

    def execute(self, task: Task):
        return {
            "status": "completed",
            "output": "Reasoning complete."
        }
