from brain.skills.base_skill import BaseSkill
from brain.task import Task

class DocumentSkill(BaseSkill):
    name = "document"

    def execute(self, task: Task):
        return {
            "status": "completed",
            "output": "Document loaded."
        }
