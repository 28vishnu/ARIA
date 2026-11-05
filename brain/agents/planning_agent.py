from typing import Dict, Any

from brain.agents.base_agent import BaseAgent, AgentResponse


class PlanningAgent(BaseAgent):
    """
    Handles multi-step goal decomposition, scheduling, and project planning.
    """

    name = "planning"
    aliases = ("planner", "plan")

    description = "Task planning, scheduling, and goal decomposition agent."
    version = "1.1.0"
    priority = 95
    timeout_seconds = 60.0
    max_retries = 1

    async def can_handle(
        self,
        query: str,
        context: Dict[str, Any],
    ) -> float:

        q = str(query or "").lower()

        keywords = [
            "plan",
            "planning",
            "schedule",
            "roadmap",
            "timeline",
            "strategy",
            "learning path",
            "30-day",
            "60-day",
            "90-day",
            "step by step",
            "workflow",
            "strategy for",
            "organize",
            "itinerary",
        ]

        if any(word in q for word in keywords):
            return 0.95

        return 0.0

    async def execute(
        self,
        query: str,
        context: Dict[str, Any],
    ) -> AgentResponse:

        answer = await self.complete_with_llm(
            context,
            (
                "You are ARIA's strategic planner. Break the goal into "
                "ordered, actionable steps with priorities, dependencies, "
                "and a realistic timeline. Do not claim that any step has "
                "already been executed. Ask for missing constraints instead "
                "of inventing them."
            ),
            query,
        )

        if not answer:
            return AgentResponse(
                success=False,
                confidence=0.0,
                agent=self.name,
                data={},
                error=(
                    "The planning agent is unavailable because no language "
                    "model is configured or the model returned no answer."
                ),
            )

        return AgentResponse(
            success=True,
            confidence=0.85,
            agent=self.name,
            data={"response": answer},
        )
