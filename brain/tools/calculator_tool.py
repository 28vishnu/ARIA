import ast
from typing import Dict, Any

from brain.tools.base_tool import BaseTool


class CalculatorTool(BaseTool):
    """
    Performs safe mathematical calculations.
    """

    def __init__(self):
        super().__init__("calculator")

    async def can_handle(
        self,
        query: str,
        context: Dict[str, Any]
    ) -> float:

        query = query.lower()

        keywords = [
            "calculate",
            "solve",
            "math",
            "+",
            "-",
            "*",
            "/",
            "%",
            "^"
        ]

        if any(k in query for k in keywords):
            return 0.95

        return 0.0

    async def execute(
        self,
        query: str,
        context: Dict[str, Any]
    ):

        expression = (
            query.lower()
            .replace("calculate", "")
            .replace("solve", "")
            .replace("math", "")
            .strip()
        )

        try:
            result = eval(
                compile(
                    ast.parse(expression, mode="eval"),
                    "<calculator>",
                    "eval"
                ),
                {"__builtins__": {}},
                {}
            )

            return {
                "success": True,
                "result": result
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            } 