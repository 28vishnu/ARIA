from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

@dataclass
class SkillResponse:
    success: bool
    confidence: float
    source: str
    data: Any = None
    error: Optional[str] = None

class BaseSkill(ABC):
    name: str = "base_skill"
    description: str = "Base skill interface"
    version: str = "1.0.0"
    priority: int = 10
    requires_llm: bool = False

    @abstractmethod
    async def can_run(self, query: str, context: Dict[str, Any]) -> float:
        """Returns a confidence score between 0.0 and 1.0 indicating capability to handle the query."""
        pass

    @abstractmethod
    async def execute(self, query: str, context: Dict[str, Any]) -> SkillResponse:
        """Executes the core skill logic statelessly and returns a standard SkillResponse."""
        pass
      
