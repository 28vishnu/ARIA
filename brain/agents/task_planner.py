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

            task = AgentTask(
                id=index,
                description=part,
                agent="research"
            )

            text = part.lower()

            if any(x in text for x in [
                "calculate",
                "solve",
                "+",
                "-",
                "*",
                "/",
                "=",
                "equation",
                "math"
            ]):
                task.agent = "math"

            elif any(x in text for x in [
                "python",
                "code",
                "program",
                "script",
                "function"
            ]):
                task.agent = "python"

            elif any(x in text for x in [
                "write",
                "email",
                "essay",
                "article",
                "letter"
            ]):
                task.agent = "writing"

            elif any(x in text for x in [
                "plan",
                "schedule",
                "roadmap"
            ]):
                task.agent = "planning"

            plan.add(task)

        return plan
