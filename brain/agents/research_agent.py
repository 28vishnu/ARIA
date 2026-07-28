from typing import Dict, Any

from brain.agents.base_agent import BaseAgent, AgentResponse


class ResearchAgent(BaseAgent):
    """
    Handles research, deep explanations, and information retrieval requests.
    """

    name = "research"

    description = "Research and knowledge extraction agent."

    version = "1.0.0"

    priority = 60

    async def can_handle(
        self,
        query: str,
        context: Dict[str, Any]
    ) -> float:

        q = query.lower()

        keywords = [
            "research",
            "explain",
            "history of",
            "overview of",
            "what is",
            "how does",
            "compare",
            "difference between",
            "summarize"
        ]

        if any(phrase in q for phrase in keywords):
            return 0.90

        return 0.0

    async def execute(
        self,
        query: str,
        context: Dict[str, Any]
    ) -> AgentResponse:

        messages = [
            {
                "role": "system",
                "content": "You are ARIA's senior research analyst. Provide deep, accurate, and well-structured insights."
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
