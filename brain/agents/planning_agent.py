from typing import Dict, Any

from brain.agents.base_agent import BaseAgent, AgentResponse


class PlanningAgent(BaseAgent):
    """
    Handles planning, scheduling and task organisation.
    """

    name = "planning"

    description = "Planning and task management agent."

    version = "1.0.0"

    async def can_handle(
        self,
        query: str,
        context: Dict[str, Any]
    ) -> float:

        q = query.lower()

        keywords = [
            "plan",
            "schedule",
            "roadmap",
            "organize",
            "organise",
            "steps",
            "strategy",
            "timeline",
            "project",
            "todo",
            "to-do"
        ]

        if any(word in q for word in keywords):
            return 0.95

        return 0.0

    async def execute(
        self,
        query: str,
        context: Dict[str, Any]
    ) -> AgentResponse:

        llm_router = context["app_state"].registry.get("llm_router")

        messages = [
            {
                "role": "system",
                "content": (
                    "You are ARIA's planning expert. "
                    "Create structured plans, timelines and actionable steps."
                )
            },
            {
                "role": "user",
                "content": query
            }
        ]

        answer = await llm_router.chat(messages)

        return AgentResponse(
            success=True,
            confidence=1.0,
            agent=self.name,
            data={
                "response": answer
            }
        ) 