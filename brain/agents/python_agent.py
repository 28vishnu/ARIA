from typing import Dict, Any

from brain.agents.base_agent import BaseAgent, AgentResponse


class PythonAgent(BaseAgent):
    """
    Executes Python code using the PythonTool.
    """

    name = "python"

    description = "Python execution agent."

    version = "1.0.0"

    priority = 85

    async def can_handle(
        self,
        query: str,
        context: Dict[str, Any]
    ) -> float:

        q = query.lower()

        keywords = [
            "python",
            "run",
            "execute",
            "script",
            "code",
            "print("
        ]

        if any(word in q for word in keywords):
            return 0.95

        return 0.0

    async def execute(
        self,
        query: str,
        context: Dict[str, Any]
    ) -> AgentResponse:

        tool_manager = context["app_state"].registry.get("tool_manager")

        if tool_manager:

            tool = tool_manager.get("python")

            if tool:

                result = await tool.execute(
                    query,
                    context
                )

                if result["success"]:

                    return AgentResponse(
                        success=True,
                        confidence=1.0,
                        agent=self.name,
                        data={
                            "response": result["output"]
                        }
                    )

                return AgentResponse(
                    success=False,
                    confidence=1.0,
                    agent=self.name,
                    data={
                        "response": result["error"]
                    }
                )

        return AgentResponse(
            success=False,
            confidence=0.0,
            agent=self.name,
            data={
                "response": "Python tool unavailable."
            }
        )