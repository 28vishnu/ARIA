import pytest
from brain.tools.python_tool import PythonTool

@pytest.mark.asyncio
async def test_arithmetic_and_print_work():
    result = await PythonTool().execute("python print(2 + 3 * 4)", {})
    assert result["success"] is True
    assert result["output"] == "14"

@pytest.mark.asyncio
async def test_variables_and_basic_if_work():
    result = await PythonTool().execute("python x = 4\nif x > 2:\n    print(x)", {})
    assert result["success"] is True
    assert result["output"] == "4"

@pytest.mark.asyncio
@pytest.mark.parametrize("code", [
    "import os",
    "print(open('/etc/passwd').read())",
    "print((1).__class__)",
    "while True: pass",
    "print(__import__('os'))",
])
async def test_dangerous_or_unbounded_syntax_is_rejected(code):
    result = await PythonTool().execute(code, {"code": code})
    assert result["success"] is False
    assert result["error"]

@pytest.mark.asyncio
async def test_source_size_limit():
    code = "print('x')\n" * 900
    result = await PythonTool().execute(code, {"code": code})
    assert result["success"] is False
    assert "long" in result["error"].lower() or "statements" in result["error"].lower()
