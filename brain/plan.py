from dataclasses import dataclass, field
from typing import List
from brain.task import Task

@dataclass
class ExecutionPlan:
    goal: str
    tasks: List[Task] = field(default_factory=list)
    confidence: float = 0.0
