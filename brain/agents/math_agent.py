from typing import Dict, Any

from brain.agents.base_agent import BaseAgent, AgentResponse


class MathAgent(BaseAgent):
    """
    Handles mathematics and numerical reasoning.
    """

    name = "math"

    description = "Mathematics and numerical reasoning agent."

    version = "1.0.0"

    async def can_handle(
        self,
        query: str,
        context: Dict[str, Any]
    ) -> float:

        q = query.lower()

        keywords = [
            "calculate",
            "solve",
            "equation",
            "math",
            "algebra",
            "geometry",
            "integral",
            "derivative",
            "probability",
            "percentage",
            "multiply",
            "divide",
            "addition",
            "subtraction"
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
                    "You are ARIA's mathematics expert. "
                    "Solve problems step by step with clear explanations."
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