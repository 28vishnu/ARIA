from typing import Dict, Any

from brain.agents.base_agent import BaseAgent, AgentResponse


class WritingAgent(BaseAgent):
    """
    Handles creative writing, drafting, editing, and content generation.
    """

    name = "writing"

    description = "Creative writing, drafting, and editing agent."

    version = "1.0.0"

    priority = 70

    async def can_handle(
        self,
        query: str,
        context: Dict[str, Any]
    ) -> float:

        q = query.lower()

        keywords = [
            "write",
            "draft",
            "compose",
            "essay",
            "email",
            "poem",
            "story",
            "rewrite",
            "proofread",
            "edit",
            "blog post",
            "article"
        ]

        if any(word in q for word in keywords):
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
                "content": "You are ARIA's master creative writer and editor. Craft clear, engaging, and polished content suited to the user's requirements."
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
