from typing import Dict, Any

from brain.agents.base_agent import BaseAgent, AgentResponse


class WritingAgent(BaseAgent):
    """
    Handles writing, rewriting and content generation.
    """

    name = "writing"

    description = "Writing and content creation agent."

    version = "1.0.0"

    async def can_handle(
        self,
        query: str,
        context: Dict[str, Any]
    ) -> float:

        q = query.lower()

        keywords = [
            "write",
            "rewrite",
            "essay",
            "email",
            "letter",
            "story",
            "blog",
            "article",
            "grammar",
            "correct",
            "summarize",
            "summary"
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
                    "You are ARIA's professional writing expert. "
                    "Produce clear, well-structured and polished writing."
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