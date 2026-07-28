from dataclasses import dataclass, field
from typing import Dict, Any


@dataclass
class AgentTask:
    """
    Represents a single task that will be executed by one agent.
    """

    id: int

    description: str

    agent: str

    context: Dict[str, Any] = field(default_factory=dict)

    completed: bool = False

    result: Any = None