import re
import ast
import operator

from skills.base import BaseSkill, SkillResponse


ALLOWED_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _safe_eval(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value

    if isinstance(node, ast.BinOp) and type(node.op) in ALLOWED_OPERATORS:
        return ALLOWED_OPERATORS[type(node.op)](
            _safe_eval(node.left),
            _safe_eval(node.right)
        )

    if isinstance(node, ast.UnaryOp) and type(node.op) in ALLOWED_OPERATORS:
        return ALLOWED_OPERATORS[type(node.op)](
            _safe_eval(node.operand)
        )

    raise ValueError("Invalid math syntax")


def _normalize_expression(query: str) -> str:
    expression = query.strip()

    # Human-friendly operators → Python operators
    expression = (
        expression
        .replace("×", "*")
        .replace("÷", "/")
        .replace("−", "-")
        .replace("–", "-")
        .replace("—", "-")
        .replace("^", "**")
    )

    # Remove common natural-language prefixes.
    expression = re.sub(
        r"^\s*(calculate|compute|solve|evaluate|what\s+is|find)\s+",
        "",
        expression,
        flags=re.IGNORECASE,
    )

    # Remove trailing question mark.
    expression = expression.rstrip(" ?.")

    return expression.strip()


class CalculatorSkill(BaseSkill):
    name = "calculator"
    description = "Performs safe mathematical calculations."
    version = "1.0.0"
    priority = 20
    requires_llm = False

    async def can_run(self, query: str, context: dict) -> float:
        normalized = (
            query
            .lower()
            .replace("×", "*")
            .replace("÷", "/")
            .replace("−", "-")
        )

        math_words = [
            "calculate",
            "compute",
            "solve",
            "evaluate",
            "what is",
            "find",
        ]

        if any(word in normalized for word in math_words):
            return 0.99

        if re.fullmatch(
            r"[\d\s\+\-\*\/\^\(\)\.]+",
            normalized
        ):
            return 0.99

        return 0.0

    async def execute(
        self,
        query: str,
        context: dict
    ) -> SkillResponse:

        try:
            expression = _normalize_expression(query)

            node = ast.parse(expression, mode="eval")

            result = _safe_eval(node.body)

            return SkillResponse(
                success=True,
                confidence=0.99,
                source=self.name,
                data={
                    "result": result
                }
            )

        except Exception as e:
            return SkillResponse(
                success=False,
                confidence=0.99,
                source=self.name,
                error=str(e)
            )