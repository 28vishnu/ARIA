from typing import Dict, Any

from brain.agents.base_agent import BaseAgent, AgentResponse


class MemoryAgent(BaseAgent):
    """
    Handles memory-related requests.
    """

    name = "memory"

    description = "Memory retrieval and storage agent."

    version = "1.0.0"

    async def can_handle(
        self,
        query: str,
        context: Dict[str, Any]
    ) -> float:

        q = query.lower()

        keywords = [
            "remember",
            "recall",
            "memory",
            "forget",
            "saved",
            "store",
            "what did i tell you",
            "do you remember"
        ]

        if any(word in q for word in keywords):
            return 0.95

        return 0.0

    async def execute(
        self,
        query: str,
        context: Dict[str, Any]
    ) -> AgentResponse:

        # Memory operations are already handled elsewhere.
        # This agent simply passes control to the memory system.

        return AgentResponse(
            success=True,
            confidence=1.0,
            agent=self.name,
            data={
                "response": "Memory request has been routed to the memory system."
            }
        ) 