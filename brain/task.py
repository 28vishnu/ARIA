from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional


@dataclass
class Task:
    """
    Represents a single executable task within an ExecutionPlan.
    """

    id: str
    name: str
    skill: str

    input: Dict[str, Any] = field(default_factory=dict)

    depends_on: List[str] = field(default_factory=list)

    status: str = "pending"      # pending, running, completed, failed, skipped

    max_retries: int = 2
    retry_count: int = 0

    # -------- Phase 3 additions --------

    priority: int = 1

    output: Optional[Dict[str, Any]] = None

    error: Optional[str] = None

    execution_time_ms: float = 0.0
