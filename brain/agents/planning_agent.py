from typing import Dict, Any

from brain.agents.base_agent import BaseAgent, AgentResponse


class PlanningAgent(BaseAgent):
    """
    Handles multi-step goal decomposition, scheduling, and project planning requests.
    """

    name = "planning"

    description = "Task planning, scheduling, and goal decomposition agent."

    version = "1.0.0"

    priority = 95

    async def can_handle(
        self,
        query: str,
        context: Dict[str, Any]
    ) -> float:

        q = query.lower()

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
            "itinerary"
        ]

        if any(word in q for word in keywords):
            return 0.95

        return 0.0

    async def execute(
        self,
        query: str,
        context: Dict[str, Any]
    ) -> AgentResponse:

        messages = [
            {
                "role": "system",
                "content": "You are ARIA's strategic planner. Break down complex goals into logical, actionable steps with clear priorities."
            },
            {
                "role": "user",
                "content": query
            }
        ]

        llm_router = context["app_state"].registry.get("llm_router")

        answer = await llm_router.chat(messages)

        return AgentResponse(
            success=True,
            confidence=1.0,
            agent=self.name,
            data={
                "response": answer
            }
        )
