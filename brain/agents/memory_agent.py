from typing import Dict, Any

from brain.agents.base_agent import BaseAgent, AgentResponse


class MemoryAgent(BaseAgent):
    """
    Handles operations requiring retrieval, updating, or querying stored personal context and long-term memory.
    """

    name = "memory"

    description = "Personal context and long-term memory operations agent."

    version = "1.0.0"

    priority = 100

    async def can_handle(
        self,
        query: str,
        context: Dict[str, Any]
    ) -> float:

        q = query.lower()

        keywords = [
            "remember",
            "what is my",
            "do you recall",
            "my preferences",
            "save this",
            "store this",
            "my background",
            "my name",
            "forget"
        ]

        if any(phrase in q for phrase in keywords):
            return 0.98

        return 0.0

    async def execute(
        self,
        query: str,
        context: Dict[str, Any]
    ) -> AgentResponse:

        messages = [
            {
                "role": "system",
                "content": "You are ARIA's memory specialist. Help manage, retrieve, and summarize stored user context accurately."
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
