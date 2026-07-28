from typing import Dict, Any

from brain.agents.base_agent import BaseAgent, AgentResponse
from brain.tools.tool_manager import ToolManager


class MathAgent(BaseAgent):
    """
    Handles mathematical, statistical, and algorithmic calculation requests.
    """

    name = "math"

    description = "Mathematics, logic, and calculation agent."

    version = "1.0.0"

    priority = 90

    async def can_handle(
        self,
        query: str,
        context: Dict[str, Any]
    ) -> float:

        q = query.lower()

        keywords = [
            "calculate",
            "solve",
            "math",
            "algebra",
            "calculus",
            "equation",
            "integral",
            "derivative",
            "probability",
            "statistics",
            "sum of",
            "square root"
        ]

        if any(word in q for word in keywords) or any(char in q for char in ["+", "-", "*", "/", "^", "="]):
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
                "content": "You are ARIA's mathematics and logic specialist. Solve the user's problem step-by-step with clear derivations."
            },
            {
                "role": "user",
                "content": query
            }
        ]

        tool_manager = context["app_state"].registry.get("tool_manager")

        if tool_manager:
            tool = tool_manager.get("calculator")

            if tool:
                try:
                    result = await tool.execute(query, context)

                    if (
                        isinstance(result, dict)
                        and result.get("success")
                        and result.get("result") is not None
                    ):
                        return AgentResponse(
                            success=True,
                            confidence=1.0,
                            agent=self.name,
                            data={
                                "response": str(result["result"])
                            }
                        )

                except Exception:
                    pass

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
