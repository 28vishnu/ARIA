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
                agent="research",
                priority=5,
                estimated_seconds=5,
                required_tools=[],
                dependencies=[],
            )

            text = part.lower()# Mathematics
            if any(x in text for x in [
                "calculate",
                "solve",
                "equation",
                "math",
                "+",
                "-",
                "*",
                "/",
            ]):
                task.agent = "math"
                task.priority = 8# Coding
            elif any(x in text for x in [
                "python",
                "code",
                "program",
                "script",
                "bug",
                "debug",
                "api",
            ]):
                task.agent = "coding"
                task.priority = 9
                task.required_tools = ["python"]# Writing
            elif any(x in text for x in [
                "essay",
                "email",
                "letter",
                "article",
                "write",
            ]):
                task.agent = "writing"
                task.priority = 5# Planning
            elif any(x in text for x in [
                "plan",
                "roadmap",
                "schedule",
                "strategy",
            ]):
                task.agent = "planning"
                task.priority = 7# Research
            else:
                task.agent = "research"
                task.priority = 6
                task.required_tools = ["browser"]

            plan.add(task)

        return plan
