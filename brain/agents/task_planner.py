from brain.agents.task import AgentTask
from brain.agents.task_plan import TaskPlan


class TaskPlanner:
    """
    Converts a user's request into one or more tasks.
    """

    def create_plan(self, query: str) -> TaskPlan:

        plan = TaskPlan()

        # For now every request is a single task.
        # Later we'll split complex requests automatically.

        plan.add(
            AgentTask(
                id=1,
                description=query,
                agent="auto"
            )
        )

        return plan