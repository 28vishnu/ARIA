from dataclasses import dataclass, field
from typing import List


@dataclass
class PlanStep:
    id: int
    title: str
    description: str
    tool: str | None = None
    completed: bool = False


@dataclass
class ExecutionPlan:
    goal: str
    steps: List[PlanStep] = field(default_factory=list)

    def add_step(self, title, description, tool=None):
        self.steps.append(
            PlanStep(
                id=len(self.steps) + 1,
                title=title,
                description=description,
                tool=tool,
            )
        )
