import ast
import pytest

from brain.core.coding_engine import CodingEngine


@pytest.mark.asyncio
async def test_prime_number_template_is_selected_without_llm():
    answer = await CodingEngine().process(
        "Write a Python function to check whether a number is prime. Include tests."
    )
    assert "def is_prime(n):" in answer
    assert "assert is_prime(97)" in answer
    assert "assert not is_prime(100)" in answer
    code = answer.split("```python\n", 1)[1].split("\n```", 1)[0]
    ast.parse(code)
    namespace = {}
    exec(compile(code, "<prime-template>", "exec"), namespace)
    assert namespace["is_prime"](2) is True
    assert namespace["is_prime"](97) is True
    assert namespace["is_prime"](91) is False
    assert namespace["is_prime"](1) is False
