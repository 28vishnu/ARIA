from abc import ABC, abstractmethod
from typing import Any
from brain.task import Task

class BaseSkill(ABC):
    """Base class for all executable skills."""

    name = "base"

    @abstractmethod
    def execute(self, task: Task) -> Any:
        """Execute a task and return the result."""
        raise NotImplementedError
