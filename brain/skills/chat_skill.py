from brain.skills.base_skill import BaseSkill
from brain.task import Task

class ChatSkill(BaseSkill):
    name = "chat"

    def execute(self, task: Task):
        return {
            "status": "completed",
            "output": "Chat response generated."
        }
