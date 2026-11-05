"""Bounded, non-exec Python-like calculator tool for ARIA.

This is deliberately not a general Python sandbox. It interprets a small AST
allowlist and never calls exec/eval, imports modules, accesses attributes, or
opens files/network connections.
"""
from __future__ import annotations

import ast
import contextlib
import io
import math
import operator
from typing import Any, Dict

from brain.tools.base_tool import BaseTool


class _SafeProgramError(ValueError):
    pass


class _Interpreter:
    MAX_SOURCE_CHARS = 8_000
    MAX_AST_NODES = 300
    MAX_STATEMENTS = 100
    MAX_OUTPUT_CHARS = 8_000
    MAX_COLLECTION_ITEMS = 1_000
    MAX_INTEGER_BITS = 4_096

    BINOPS = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
    }
    UNARYOPS = {ast.UAdd: operator.pos, ast.USub: operator.neg, ast.Not: operator.not_}
    COMPAREOPS = {
        ast.Eq: operator.eq, ast.NotEq: operator.ne,
        ast.Lt: operator.lt, ast.LtE: operator.le,
        ast.Gt: operator.gt, ast.GtE: operator.ge,
    }

    def __init__(self) -> None:
        self.env: Dict[str, Any] = {}
        self.output = io.StringIO()
        self.nodes_seen = 0
        self.statements_seen = 0

    def _check_value(self, value: Any) -> Any:
        if isinstance(value, int) and value.bit_length() > self.MAX_INTEGER_BITS:
            raise _SafeProgramError("Integer result exceeds the safety limit.")
        if isinstance(value, (str, list, tuple)) and len(value) > self.MAX_COLLECTION_ITEMS:
            raise _SafeProgramError("Collection result exceeds the safety limit.")
        if isinstance(value, float) and not math.isfinite(value):
            raise _SafeProgramError("Non-finite numeric results are not allowed.")
        if not isinstance(value, (int, float, bool, str, list, tuple, type(None))):
            raise _SafeProgramError("Unsupported value type.")
        return value

    def _tick(self, node: ast.AST) -> None:
        self.nodes_seen += 1
        if self.nodes_seen > self.MAX_AST_NODES:
            raise _SafeProgramError("Program is too complex (AST node limit reached).")

    def expr(self, node: ast.AST) -> Any:
        self._tick(node)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (str, int, float, bool, type(None))):
                return self._check_value(node.value)
            raise _SafeProgramError("This literal type is not allowed.")
        if isinstance(node, ast.Name):
            if node.id not in self.env:
                raise _SafeProgramError(f"Unknown variable: {node.id}")
            return self.env[node.id]
        if isinstance(node, (ast.List, ast.Tuple)):
            if len(node.elts) > self.MAX_COLLECTION_ITEMS:
                raise _SafeProgramError("Collection is too large.")
            values = [self.expr(item) for item in node.elts]
            return values if isinstance(node, ast.List) else tuple(values)
        if isinstance(node, ast.BinOp) and type(node.op) in self.BINOPS:
            left, right = self.expr(node.left), self.expr(node.right)
            if isinstance(node.op, ast.Pow) and isinstance(right, (int, float)) and abs(right) > 100:
                raise _SafeProgramError("Exponent exceeds the safety limit.")
            if isinstance(node.op, ast.Mult):
                if isinstance(left, (str, list, tuple)) and isinstance(right, int) and abs(right) > self.MAX_COLLECTION_ITEMS:
                    raise _SafeProgramError("Repeated collection is too large.")
                if isinstance(right, (str, list, tuple)) and isinstance(left, int) and abs(left) > self.MAX_COLLECTION_ITEMS:
                    raise _SafeProgramError("Repeated collection is too large.")
            try:
                return self._check_value(self.BINOPS[type(node.op)](left, right))
            except (ArithmeticError, TypeError, ValueError, OverflowError) as exc:
                raise _SafeProgramError(f"Arithmetic error: {exc}") from exc
        if isinstance(node, ast.UnaryOp) and type(node.op) in self.UNARYOPS:
            try:
                return self._check_value(self.UNARYOPS[type(node.op)](self.expr(node.operand)))
            except (TypeError, ValueError) as exc:
                raise _SafeProgramError(f"Unary operation error: {exc}") from exc
        if isinstance(node, ast.Compare) and len(node.ops) == 1 and type(node.ops[0]) in self.COMPAREOPS:
            left, right = self.expr(node.left), self.expr(node.comparators[0])
            try:
                return bool(self.COMPAREOPS[type(node.ops[0])](left, right))
            except TypeError as exc:
                raise _SafeProgramError(f"Comparison error: {exc}") from exc
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            name = node.func.id
            if node.keywords:
                raise _SafeProgramError("Keyword arguments are not supported.")
            args = [self.expr(arg) for arg in node.args]
            funcs = {
                "abs": abs, "min": min, "max": max, "sum": sum,
                "len": len, "round": round, "sorted": sorted,
                "range": self._safe_range,
            }
            if name == "print":
                text = " ".join(str(arg) for arg in args)
                current = self.output.getvalue()
                remaining = self.MAX_OUTPUT_CHARS - len(current)
                if remaining <= 0:
                    raise _SafeProgramError("Output limit reached.")
                self.output.write(text[:remaining] + "\n")
                return None
            if name not in funcs:
                raise _SafeProgramError(f"Function not allowed: {name}")
            try:
                return self._check_value(funcs[name](*args))
            except (TypeError, ValueError, OverflowError) as exc:
                raise _SafeProgramError(f"{name}() failed: {exc}") from exc
        raise _SafeProgramError(f"Unsupported expression: {type(node).__name__}")

    def _safe_range(self, *args: Any) -> range:
        result = range(*args)
        if len(result) > self.MAX_COLLECTION_ITEMS:
            raise _SafeProgramError("range() exceeds the collection limit.")
        return result

    def run(self, source: str) -> str:
        if len(source) > self.MAX_SOURCE_CHARS:
            raise _SafeProgramError("Code is too long.")
        try:
            tree = ast.parse(source, mode="exec")
        except SyntaxError as exc:
            raise _SafeProgramError(f"Syntax error: {exc.msg} (line {exc.lineno})") from exc
        if len(tree.body) > self.MAX_STATEMENTS:
            raise _SafeProgramError("Too many statements.")
        for statement in tree.body:
            self.statements_seen += 1
            self._statement(statement)
        return self.output.getvalue().rstrip()

    def _statement(self, node: ast.stmt) -> None:
        self._tick(node)
        if isinstance(node, ast.Expr):
            self.expr(node.value)
            return
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name.startswith("_") or name in {"print", "exec", "eval", "open", "import"}:
                raise _SafeProgramError("That variable name is not allowed.")
            self.env[name] = self._check_value(self.expr(node.value))
            return
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            if node.target.id.startswith("_"):
                raise _SafeProgramError("Private variable names are not allowed.")
            self.env[node.target.id] = self._check_value(self.expr(node.value))
            return
        if isinstance(node, ast.If):
            branch = node.body if self.expr(node.test) else node.orelse
            for child in branch:
                self._statement(child)
            return
        # Loops, functions, classes, imports, comprehensions, attribute access,
        # subscripting and mutation are intentionally excluded.
        raise _SafeProgramError(f"Statement not allowed: {type(node).__name__}")


class PythonTool(BaseTool):
    """Runs a restricted Python-like expression program without exec/eval."""

    def __init__(self):
        super().__init__("python")

    async def can_handle(self, query: str, context: Dict[str, Any]) -> float:
        q = (query or "").lower()
        return 0.95 if any(word in q for word in ("python", "run", "execute", "script", "code", "print(")) else 0.0

    async def execute(self, query: str, context: Dict[str, Any]) -> Dict[str, Any]:
        # Prefer explicitly supplied code; otherwise preserve the simple legacy prefix cleanup.
        code = (context or {}).get("code")
        if not isinstance(code, str):
            code = str(query or "")
            for prefix in ("execute python", "run python", "execute", "run", "python", "code"):
                if code.lower().startswith(prefix):
                    code = code[len(prefix):].lstrip(" :\n")
                    break
        try:
            output = _Interpreter().run(code)
            return {"success": True, "output": output, "mode": "restricted_interpreter"}
        except _SafeProgramError as exc:
            return {"success": False, "error": str(exc), "mode": "restricted_interpreter"}
        except Exception:
            # Do not leak internal tracebacks or environment details to the caller.
            return {"success": False, "error": "Execution failed safely; simplify the expression and try again.", "mode": "restricted_interpreter"}
