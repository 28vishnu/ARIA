from typing import Dict, Any

from brain.agents.base_agent import BaseAgent, AgentResponse


class CodeAgent(BaseAgent):
    """
    Handles programming-related requests.

    The agent provides software-engineering guidance. It does not execute
    untrusted code; code execution belongs to the dedicated Python tool.
    """

    name = "code"
    aliases = ("coding", "programming")

    description = "Programming and software development agent."
    version = "1.1.0"
    priority = 80
    timeout_seconds = 60.0
    max_retries = 1

    async def can_handle(
        self,
        query: str,
        context: Dict[str, Any],
    ) -> float:

        q = str(query or "").lower()

        # Exclude planning/roadmap keywords so PlanningAgent isn't preempted.
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
            "itinerary",
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
            "api",
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
                "You are ARIA's senior software engineer. Give correct, "
                "runnable, concise code and explain trade-offs. If you are "
                "unsure about an API or version, say so instead of guessing. "
                "Never claim code was executed or tested unless the user "
                "provided the result."
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
                    "The coding agent is unavailable because no language "
                    "model is configured or the model returned no answer."
                ),
            )

        return AgentResponse(
            success=True,
            confidence=0.85,
            agent=self.name,
            data={"response": answer},
        )
