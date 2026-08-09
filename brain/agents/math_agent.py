from typing import Dict, Any

from brain.agents.base_agent import BaseAgent, AgentResponse


class MathAgent(BaseAgent):
    """
    Handles mathematical, statistical, and algorithmic calculation requests.

    Deterministic arithmetic must never depend on an LLM.
    """

    name = "math"

    description = "Mathematics, logic, and calculation agent."

    version = "1.1.0"

    priority = 90

    async def can_handle(
        self,
        query: str,
        context: Dict[str, Any]
    ) -> float:

        q = query.lower().strip()

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
            "square root",
        ]

        if any(word in q for word in keywords):
            return 0.95

        if any(
            char in q
            for char in ["+", "-", "*", "/", "^", "=", "×", "÷"]
        ):
            return 0.95

        return 0.0

    async def execute(
        self,
        query: str,
        context: Dict[str, Any]
    ) -> AgentResponse:

        # =========================================================
        # 1. DETERMINISTIC CALCULATOR
        # =========================================================

        try:
            app_state = context.get("app_state")

            if app_state is not None:
                registry = getattr(app_state, "registry", None)

                if registry is not None:
                    tool_manager = registry.get("tool_manager")

                    if tool_manager is not None:
                        calculator = tool_manager.get("calculator")

                        if calculator is not None:
                            result = await calculator.execute(
                                query,
                                context
                            )

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
                                        "response": str(
                                            result["result"]
                                        ),
                                        "deterministic": True,
                                    }
                                )

        except Exception:
            # Do not allow calculator implementation errors
            # to crash the cognitive pipeline.
            pass

        # =========================================================
        # 2. IMPORTANT
        # =========================================================
        #
        # Do NOT silently send deterministic arithmetic to the LLM.
        #
        # If the calculator cannot solve the request, report that
        # the mathematical capability could not process it.
        #
        # Advanced mathematical reasoning can be handled later by
        # the appropriate reasoning/LLM pathway rather than allowing
        # basic arithmetic to become LLM-dependent.
        # =========================================================

        return AgentResponse(
            success=False,
            confidence=0.0,
            agent=self.name,
            data={
                "response": (
                    "I couldn't evaluate that calculation "
                    "with the available calculator."
                ),
                "deterministic": True,
            }
        )