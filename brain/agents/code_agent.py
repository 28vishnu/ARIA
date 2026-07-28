from typing import Dict, Any

from brain.agents.base_agent import BaseAgent, AgentResponse


class CodeAgent(BaseAgent):
    """
    Handles programming-related requests.
    """

    name = "code"

    description = "Programming and software development agent."

    version = "1.0.0"

    priority = 80

    async def can_handle(
        self,
        query: str,
        context: Dict[str, Any]
    ) -> float:

        q = query.lower()

        # Exclude planning/roadmap keywords so PlanningAgent isn't preempted
        exclude_keywords = [
            "roadmap",
            "plan",
            "planning",
            "schedule",
            "strategy",
            "timeline",
            "learning path",
            "30-day",
            "60-day",
            "90-day",
            "itinerary"
        ]

        if any(ex in q for ex in exclude_keywords):
            return 0.0

        keywords = [
            "python",
            "java",
            "c++",
            "c#",
            "javascript",
            "typescript",
            "html",
            "css",
            "sql",
            "code",
            "program",
            "algorithm",
            "bug",
            "debug",
            "function",
            "class",
            "api"
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
                "content": "You are ARIA's software engineering expert."
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
