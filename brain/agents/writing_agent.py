from typing import Dict, Any

from brain.agents.base_agent import BaseAgent, AgentResponse


class WritingAgent(BaseAgent):
    """
    Handles creative writing, drafting, editing, and content generation.
    """

    name = "writing"
    aliases = ("writer", "editor")

    description = "Creative writing, drafting, and editing agent."
    version = "1.1.0"
    priority = 70
    timeout_seconds = 60.0
    max_retries = 1

    async def can_handle(
        self,
        query: str,
        context: Dict[str, Any],
    ) -> float:

        q = str(query or "").lower()

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
            "article",
        ]

        if any(word in q for word in keywords):
            return 0.90

        return 0.0

    async def execute(
        self,
        query: str,
        context: Dict[str, Any],
    ) -> AgentResponse:

        answer = await self.complete_with_llm(
            context,
            (
                "You are ARIA's senior writer and editor. Produce clear, "
                "well-structured content that follows the user's audience, "
                "tone, and length requirements. Do not invent facts, quotes, "
                "or sources. If a factual claim needs verification, mark it."
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
                    "The writing agent is unavailable because no language "
                    "model is configured or the model returned no answer."
                ),
            )

        return AgentResponse(
            success=True,
            confidence=0.85,
            agent=self.name,
            data={"response": answer},
        )
