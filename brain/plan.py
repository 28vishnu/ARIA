from dataclasses import dataclass, field
from typing import List, Dict, Any
from brain.task import Task


@dataclass
class ExecutionPlan:
    """
    Represents a complete execution workflow produced by the Planner.
    """

    goal: str
    tasks: List[Task] = field(default_factory=list)
    confidence: float = 0.0

    # New fields for Phase 3
    metadata: Dict[str, Any] = field(default_factory=dict)
    completed_tasks: List[str] = field(default_factory=list)
    failed_tasks: List[str] = field(default_factory=list)
