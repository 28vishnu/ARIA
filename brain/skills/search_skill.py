from brain.skills.base_skill import BaseSkill
from brain.task import Task

class SearchSkill(BaseSkill):
    name = "search"

    def execute(self, task: Task):
        return {
            "status": "completed",
            "output": "Search completed."
        }
