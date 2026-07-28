from dataclasses import dataclass, field
from typing import List

from brain.agents.task import AgentTask


@dataclass
class TaskPlan:
    """
    Represents a collection of tasks required
    to solve a user's request.
    """

    tasks: List[AgentTask] = field(default_factory=list)

    def add(self, task: AgentTask):
        self.tasks.append(task)

    def __iter__(self):
        return iter(self.tasks)

    def __len__(self):
        return len(self.tasks)

    @property
    def completed(self):
        return all(task.completed for task in self.tasks)