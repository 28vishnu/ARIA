from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

@dataclass
class ActionResult:
    success: bool
    action_name: str
    data: Any = None
    error: Optional[str] = None
    rolled_back: bool = False

class BaseAction(ABC):
    name: str = "base_action"
    description: str = "Base action interface"
    permission_level: str = "confirm"  # "safe", "confirm", "deny"
    timeout_seconds: float = 30.0

    @abstractmethod
    async def validate(self, params: Dict[str, Any]) -> bool:
        """Validates action parameters before execution."""
        pass

    @abstractmethod
    async def execute(self, params: Dict[str, Any]) -> ActionResult:
        """Executes the core action statelessly."""
        pass

    async def rollback(self, params: Dict[str, Any]) -> bool:
        """Optional rollback support if action fails halfway."""
        return False
      
