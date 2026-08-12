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


def _resolve_followup_expression(query: str, context: dict) -> str:
    """
    Resolve a natural-language mathematical follow-up against
    ARIA's previously calculated result.

    This is generic capability logic. It does not contain
    task-specific values or examples.
    """
    if not isinstance(context, dict):
        return _normalize_expression(query)

    last_result = context.get("last_result")

    if last_result is None:
        return _normalize_expression(query)

    text = query.strip().lower()

    number_match = re.search(
        r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)",
        text,
    )

    if not number_match:
        return _normalize_expression(query)

    value = number_match.group(0)

    if re.search(r"\b(add|plus)\b", text):
        return f"({repr(last_result)}) + ({value})"

    if re.search(r"\b(subtract|minus)\b", text):
        return f"({repr(last_result)}) - ({value})"

    if re.search(r"\b(multiply|times)\b", text):
        return f"({repr(last_result)}) * ({value})"

    if re.search(r"\b(divide|divided)\b", text):
        return f"({repr(last_result)}) / ({value})"

    if re.search(r"\b(modulo|remainder)\b", text):
        return f"({repr(last_result)}) % ({value})"

    if re.search(r"\b(power)\b", text):
        return f"({repr(last_result)}) ** ({value})"

    return _normalize_expression(query)


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

        # Generic mathematical follow-up.
        # If ARIA has a previous calculation result, allow calculator
        # operations expressed in natural language to use it.
        last_result = context.get("last_result") if isinstance(context, dict) else None

        if last_result is not None and re.search(
            r"\b(add|plus|subtract|minus|multiply|times|divide|divided|modulo|remainder|power|squared|cubed)\b",
            normalized,
            flags=re.IGNORECASE,
        ):
            return 0.99

        return 0.0

    async def execute(
        self,
        query: str,
        context: dict
    ) -> SkillResponse:

        try:
            expression = _resolve_followup_expression(query, context)

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
