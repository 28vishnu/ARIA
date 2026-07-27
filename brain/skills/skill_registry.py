from typing import Optional
from brain.memory.memory_router import MemoryRouter
from brain.skills.base_skill import BaseSkill
from brain.skills.chat_skill import ChatSkill
from brain.skills.reasoning_skill import ReasoningSkill
from brain.skills.memory_skill import MemorySkill
from brain.skills.document_skill import DocumentSkill
from brain.skills.search_skill import SearchSkill

class SkillRegistry:
    """Manages and provides access to all available skills."""
    def __init__(self, memory_router: MemoryRouter):
        self.skills = {
            "chat": ChatSkill(),
            "reasoning": ReasoningSkill(),
            "memory": MemorySkill(memory_router),
            "document": DocumentSkill(),
            "search": SearchSkill(),
        }

    def get(self, name: str) -> Optional[BaseSkill]:
        """Retrieves a skill by name."""
        return self.skills.get(name)
