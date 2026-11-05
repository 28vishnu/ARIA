from abc import ABC, abstractmethod
from typing import Any, Dict


class BaseTool(ABC):
    """
    Base class for all ARIA tools.
    Every tool must inherit from this class.
    """

    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    async def can_handle(
        self,
        query: str,
        context: Dict[str, Any]
    ) -> float:
        """
        Returns a confidence score (0.0 - 1.0)
        indicating whether this tool should handle the query.
        """
        pass

    @abstractmethod
    async def execute(
        self,
        query: str,
        context: Dict[str, Any]
    ) -> Any:
        """
        Executes the tool and returns the result.
        """
        pass 