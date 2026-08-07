from dataclasses import dataclass, field
from typing import Dict, Any, List


@dataclass
class AgentTask:
    """
    Represents a single task executed by one specialist agent.
    """

    id: int

    description: str

    agent: str

    context: Dict[str, Any] = field(default_factory=dict)

    completed: bool = False

    result: Any = None

    # ---------- Phase 2D ----------

    priority: int = 5

    estimated_seconds: int = 5

    required_tools: List[str] = field(default_factory=list)

    dependencies: List[int] = field(default_factory=list)

    retry_limit: int = 2

    timeout: int = 60

    status: str = "pending"
