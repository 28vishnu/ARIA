import re
import ast
import operator
from skills.base import BaseSkill, SkillResponse

ALLOWED_OPERATORS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Pow: operator.pow, ast.USub: operator.neg, ast.UAdd: operator.pos,
}

def _safe_eval(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    elif isinstance(node, ast.BinOp) and type(node.op) in ALLOWED_OPERATORS:
        return ALLOWED_OPERATORS[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
    elif isinstance(node, ast.UnaryOp) and type(node.op) in ALLOWED_OPERATORS:
        return ALLOWED_OPERATORS[type(node.op)](_safe_eval(node.operand))
    raise ValueError("Invalid math syntax")

class CalculatorSkill(BaseSkill):
    name = "calculator"
    description = "Performs safe mathematical calculations."
    version = "1.0.0"
    priority = 20
    requires_llm = False

    async def can_run(self, query: str, context: dict) -> float:
        if bool(re.match(r'^[\d\+\-\*\/\.\(\)\s]+$', query)) and any(op in query for op in ['+', '-', '*', '/']):
            return 0.99
        return 0.0

    async def execute(self, query: str, context: dict) -> SkillResponse:
        try:
            node = ast.parse(query.strip(), mode='eval')
            result = _safe_eval(node.body)
            return SkillResponse(success=True, confidence=0.99, source=self.name, data={"result": result})
        except Exception as e:
            return SkillResponse(success=False, confidence=0.99, source=self.name, error=str(e))
