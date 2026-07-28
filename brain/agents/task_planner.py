from brain.agents.task import AgentTask
from brain.agents.task_plan import TaskPlan


class TaskPlanner:
    """
    Converts a user's request into one or more tasks.
    """

    def create_plan(self, query: str) -> TaskPlan:

        plan = TaskPlan()

        separators = [
            " and ",
            ",",
            " then "
        ]

        parts = [query]

        for sep in separators:
            if sep in query.lower():
                parts = [
                    p.strip()
                    for p in query.split(sep)
                    if p.strip()
                ]
                break

        for index, part in enumerate(parts, start=1):

            plan.add(
                AgentTask(
                    id=index,
                    description=part,
                    agent="auto"
                )
            )

        return plan
