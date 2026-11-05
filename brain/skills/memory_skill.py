from brain.skills.base_skill import BaseSkill
from brain.task import Task
from brain.memory.memory_router import MemoryRouter

class MemorySkill(BaseSkill):
    name = "memory"

    def __init__(self, memory_router: MemoryRouter):
        self.memory_router = memory_router

    def execute(self, task: Task):
        return {
            "status": "completed",
            "output": "Memory operation completed."
        }
