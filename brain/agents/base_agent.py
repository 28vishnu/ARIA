from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Any


@dataclass
class AgentResponse:
    """
    Standard response returned by every ARIA Agent.
    """

    success: bool
    confidence: float

    agent: str

    data: Dict[str, Any] = field(default_factory=dict)

    error: str | None = None


class BaseAgent(ABC):
    """
    Base class for every ARIA Agent.

    Every specialised agent (Code, Research, Memory, Planner, etc.)
    inherits from this class.
    """

    name = "base"

    description = "Base Agent"

    version = "1.0.0"

    priority = 0

    @abstractmethod
    async def can_handle(
        self,
        query: str,
        context: Dict[str, Any]
    ) -> float:
        """
        Returns a confidence score (0.0 - 1.0)
        indicating whether this agent should handle the request.
        """
        pass

    @abstractmethod
    async def execute(
        self,
        query: str,
        context: Dict[str, Any]
    ) -> AgentResponse:
        """
        Executes the request and returns an AgentResponse.
        """
        pass
