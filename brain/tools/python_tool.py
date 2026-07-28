import io
import contextlib
from typing import Dict, Any

from brain.tools.base_tool import BaseTool


class PythonTool(BaseTool):
    """
    Executes simple Python code safely.
    """

    def __init__(self):
        super().__init__("python")

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
    ):

        code = (
            query.replace("run", "")
                 .replace("execute", "")
                 .replace("python", "")
                 .replace("code", "")
                 .strip()
        )

        output = io.StringIO()

        try:

            with contextlib.redirect_stdout(output):
                exec(
                    code,
                    {
                        "__builtins__": {
                            "print": print,
                            "range": range,
                            "len": len,
                            "sum": sum,
                            "min": min,
                            "max": max,
                            "abs": abs
                        }
                    },
                    {}
                )

            return {
                "success": True,
                "output": output.getvalue().strip()
            }

        except Exception as e:

            return {
                "success": False,
                "error": str(e)
            } 