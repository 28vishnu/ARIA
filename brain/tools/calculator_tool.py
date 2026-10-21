"""Safe deterministic calculator tool used by ARIA's ToolManager."""
from __future__ import annotations

import ast
import math
import operator
import re
from typing import Any, Dict

from brain.tools.base_tool import BaseTool


_BINARY_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPERATORS = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_MAX_ABS_NUMBER = 10**100
_MAX_POWER = 1000


def normalize_expression(query: str) -> str:
    """Extract a numeric expression from common natural-language requests."""
    expression = str(query or "").strip()
    expression = (expression.replace("×", "*").replace("✕", "*")
                  .replace("·", "*").replace("÷", "/")
                  .replace("−", "-").replace("–", "-")
                  .replace("—", "-").replace("^", "**"))
    expression = re.sub(
        r"^\s*(?:please\s+)?(?:calculate|compute|solve|evaluate|work\s+out|what\s+is|find)\s+",
        "", expression, flags=re.IGNORECASE,
    )
    expression = re.sub(r"\s*[?!.]+\s*$", "", expression).strip()
    expression = re.sub(
        r"\s+(?:and\s+)?(?:show|give|tell\s+me)\s+(?:me\s+)?(?:the\s+)?(?:result|answer|solution)(?:\s+please)?\s*$",
        "", expression, flags=re.IGNORECASE,
    ).strip()
    return expression


def _safe_eval(node: ast.AST) -> int | float:
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        value = node.value
        if abs(value) > _MAX_ABS_NUMBER:
            raise ValueError("Number is outside the supported range")
        return value
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATORS:
        left = _safe_eval(node.left)
        right = _safe_eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > _MAX_POWER:
            raise ValueError("Exponent is outside the supported range")
        result = _BINARY_OPERATORS[type(node.op)](left, right)
        if isinstance(result, complex) or not math.isfinite(float(result)):
            raise ValueError("Result is outside the supported numeric range")
        if abs(result) > _MAX_ABS_NUMBER:
            raise ValueError("Result is outside the supported range")
        return result
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPERATORS:
        return _UNARY_OPERATORS[type(node.op)](_safe_eval(node.operand))
    raise ValueError("Only numeric arithmetic expressions are allowed")


class CalculatorTool(BaseTool):
    """Performs safe arithmetic without eval() or arbitrary code execution."""

    def __init__(self):
        super().__init__("calculator")

    async def can_handle(self, query: str, context: Dict[str, Any]) -> float:
        text = str(query or "").strip().lower()
        normalized = normalize_expression(text)
        if re.search(r"\d\s*(?:[+*/%×÷^]|\-\s*\d)\s*\d", text):
            return 0.99
        if re.search(r"\b(?:calculate|compute|solve|evaluate|work out)\b", text) and re.search(r"\d", text):
            return 0.99
        if normalized and re.fullmatch(r"[\d\s+*/%().-]+", normalized):
            return 0.95
        return 0.0

    async def execute(self, query: str, context: Dict[str, Any]) -> Dict[str, Any]:
        expression = normalize_expression(query)
        try:
            if not expression or not re.fullmatch(r"[\d\s+*/%().-]+", expression):
                raise ValueError("Please provide a numeric arithmetic expression")
            tree = ast.parse(expression, mode="eval")
            result = _safe_eval(tree.body)
            return {"success": True, "result": result, "expression": expression, "tool": self.name}
        except (SyntaxError, ValueError, TypeError, ZeroDivisionError, OverflowError) as exc:
            return {"success": False, "error": str(exc) or "Invalid arithmetic expression", "expression": expression, "tool": self.name}
