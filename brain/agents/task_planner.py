from brain.agents.task import AgentTask
from brain.agents.task_plan import TaskPlan
from typing import Any, Dict, List, Optional


class TaskPlanner:
    """
    Converts a user's request into one or more tasks.
    """

    def create_plan(
        self,
        query: str,
        decision: Optional[Any] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> TaskPlan:
        """
        Convert a user's request into an ordered TaskPlan.

        The planner prefers explicit decisions from the cognitive
        layer and falls back to lightweight keyword routing for
        legacy callers.
        """

        plan = TaskPlan()

        context = (
            context
            if isinstance(context, dict)
            else {}
        )

        query = str(
            query or ""
        ).strip()

        if not query:
            return plan

        # -----------------------------------------------------
        # Canonical decision state
        # -----------------------------------------------------

        selected_skills = list(
            getattr(
                decision,
                "selected_skills",
                [],
            )
            or []
        )

        selected_tools = list(
            getattr(
                decision,
                "selected_tools",
                [],
            )
            or []
        )

        # -----------------------------------------------------
        # Split independent tasks
        # -----------------------------------------------------

        separators = [
            " and ",
            ",",
            " then ",
        ]

        parts = [query]

        for separator in separators:
            if separator in query.lower():

                candidate_parts = [
                    part.strip()
                    for part in query.split(
                        separator
                    )
                    if part.strip()
                ]

                if candidate_parts:
                    parts = candidate_parts

                break

        # -----------------------------------------------------
        # Create tasks
        # -----------------------------------------------------

        for index, part in enumerate(
            parts,
            start=1,
        ):

            text = part.lower()

            agent = self._select_agent(
                text=text,
                selected_skills=selected_skills,
                index=index,
            )

            priority = self._priority_for_agent(
                agent
            )

            required_tools = []

            if agent == "coding":
                required_tools = ["python"]

            elif agent == "research":
                required_tools = ["browser"]

            # Explicit tools from the cognitive decision.
            if selected_tools:
                required_tools = list(
                    dict.fromkeys(
                        required_tools
                        + selected_tools
                    )
                )

            task = AgentTask(
                id=index,
                description=part,
                agent=agent,
                priority=priority,
                estimated_seconds=5,
                required_tools=required_tools,
                dependencies=(
                    [index - 1]
                    if index > 1
                    else []
                ),
            )

            plan.add(task)

        return plan

    def _select_agent(
        self,
        text: str,
        selected_skills: List[str],
        index: int,
    ) -> str:
        """
        Select the specialist responsible for a task.

        Explicit cognitive decisions have priority over
        keyword-based fallback routing.
        """

        # If the decision selected one or more skills,
        # use the corresponding skill for the first task.
        if selected_skills:

            if index <= len(
                selected_skills
            ):
                return selected_skills[
                    index - 1
                ]

            return selected_skills[0]

        # -----------------------------------------------------
        # Legacy keyword fallback
        # -----------------------------------------------------

        if any(
            x in text
            for x in [
                "calculate",
                "solve",
                "equation",
                "math",
                "+",
                "-",
                "*",
                "/",
            ]
        ):
            return "math"

        if any(
            x in text
            for x in [
                "python",
                "code",
                "program",
                "script",
                "bug",
                "debug",
                "api",
            ]
        ):
            return "coding"

        if any(
            x in text
            for x in [
                "essay",
                "email",
                "letter",
                "article",
                "write",
            ]
        ):
            return "writing"

        if any(
            x in text
            for x in [
                "plan",
                "roadmap",
                "schedule",
                "strategy",
            ]
        ):
            return "planning"

        return "research"

    def _priority_for_agent(
        self,
        agent: str,
    ) -> int:
        """
        Return the default execution priority for a specialist.
        """

        priorities = {
            "coding": 9,
            "math": 8,
            "planning": 7,
            "research": 6,
            "writing": 5,
            "memory": 6,
            "document": 7,
            "reasoning": 8,
        }

        return priorities.get(
            agent,
            5,
        )
