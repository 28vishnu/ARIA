from typing import Dict, Any

from brain.agents.base_agent import BaseAgent, AgentResponse


class ResearchAgent(BaseAgent):
    """
    Handles research and knowledge-based questions.
    """

    name = "research"

    description = "Research and factual knowledge agent."

    version = "1.0.0"

    async def can_handle(
        self,
        query: str,
        context: Dict[str, Any]
    ) -> float:

        q = query.lower()

        keywords = [
            "what",
            "why",
            "how",
            "explain",
            "research",
            "history",
            "compare",
            "difference",
            "meaning",
            "define",
            "information"
        ]

        if any(word in q for word in keywords):
            return 0.90

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
                    "You are ARIA's research expert. "
                    "Give accurate, detailed and well-structured answers."
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