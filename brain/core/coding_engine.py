"""Deterministic coding helper for ARIA (strict no-LLM mode).

This module intentionally does not call an LLM router or remote API. It provides
small, reviewed templates and error explanations. For unsupported tasks it says
so rather than pretending to generate arbitrary production-ready software.
"""
from __future__ import annotations

import re
from typing import Optional, Dict, Any


class CodingEngine:
    """A predictable local coding helper; no model/API calls are made."""

    def __init__(self, llm_router=None):
        # Retain the argument for constructor compatibility; never use it.
        self.llm = None

    @staticmethod
    def _has(text: str, *patterns: str) -> bool:
        return any(re.search(pattern, text, re.I) for pattern in patterns)

    @staticmethod
    def _error_answer(query: str) -> Optional[str]:
        q = query.casefold()
        explanations = [
            (("indexerror", "list index out of range"), "**IndexError** means code tried to access a sequence position that does not exist. Check the sequence length before indexing. Example: `if items and i < len(items): value = items[i]`. Python uses zero-based indexes."),
            (("keyerror",), "**KeyError** means a dictionary does not contain the requested key. Check with `if key in data:`, or use `data.get(key)` when a missing key is an expected case."),
            (("nameerror", "is not defined"), "**NameError** means a name is used before Python can resolve it. Check spelling, capitalization, scope, and whether the variable or function was defined before use."),
            (("modulenotfounderror", "no module named"), "**ModuleNotFoundError** means Python cannot find the requested module in the active environment. Check the package name, selected interpreter/virtual environment, and install only trusted packages in that environment."),
            (("zerodivisionerror", "division by zero"), "**ZeroDivisionError** occurs when a number is divided by zero. Validate the denominator before dividing, for example `if denominator != 0:`."),
            (("typeerror",), "**TypeError** usually means an operation or function received a value of an incompatible type. Inspect the traceback line and the types of the values involved; convert types only when that conversion is semantically correct."),
            (("syntaxerror", "invalid syntax"), "**SyntaxError** means Python could not parse the code. Check the reported line and the line immediately before it for unmatched brackets/quotes, missing colons, commas, or invalid indentation."),
            (("indentationerror", "unexpected indent", "expected an indented block"), "**IndentationError** means indentation does not match Python's block structure. Use consistent spaces (commonly four per level) and indent the body after statements ending in a colon."),
            (("attributeerror",), "**AttributeError** means an object does not have the attribute or method being accessed. Check the object's actual type, spelling, and whether the method belongs to that type."),
        ]
        for needles, answer in explanations:
            if any(n in q for n in needles):
                return answer
        return None

    @staticmethod
    def _code_answer(query: str) -> Optional[str]:
        q = query.casefold()
        if re.search(r"\bpython\\s+list\\b", q) or ("list" in q and "python" in q and "example" in q):
            return ('A Python list is an ordered, mutable collection. It supports duplicate values and zero-based indexing.\n\n'
                    '```python\nfruits = ["apple", "banana", "mango"]\nprint(fruits[0])  # apple\nfruits.append("orange")\nprint(len(fruits))  # 4\n```\n\n'
                    'Reference: https://docs.python.org/3/tutorial/datastructures.html')
        if CodingEngine._has(q, r"binary search") and CodingEngine._has(q, r"python"):
            return ('Binary search works on a **sorted** list and runs in O(log n) time.\n\n'
                    '```python\ndef binary_search(values, target):\n    low, high = 0, len(values) - 1\n    while low <= high:\n        mid = (low + high) // 2\n        if values[mid] == target:\n            return mid\n        if values[mid] < target:\n            low = mid + 1\n        else:\n            high = mid - 1\n    return -1\n\nassert binary_search([1, 3, 5, 7], 5) == 2\nassert binary_search([1, 3, 5, 7], 2) == -1\n```\n\nReference: https://docs.python.org/3/library/bisect.html')
        if CodingEngine._has(q, r"factorial") and CodingEngine._has(q, r"python"):
            return ('This iterative implementation rejects negative inputs and defines 0! = 1.\n\n'
                    '```python\ndef factorial(n):\n    if not isinstance(n, int) or isinstance(n, bool):\n        raise TypeError("n must be an integer")\n    if n < 0:\n        raise ValueError("n must be non-negative")\n    result = 1\n    for value in range(2, n + 1):\n        result *= value\n    return result\n\nassert factorial(0) == 1\nassert factorial(5) == 120\n```')
        if CodingEngine._has(q, r"fibonacci") and CodingEngine._has(q, r"python"):
            return ('This returns the first `n` Fibonacci numbers in O(n) time.\n\n'
                    '```python\ndef fibonacci(n):\n    if not isinstance(n, int) or isinstance(n, bool):\n        raise TypeError("n must be an integer")\n    if n < 0:\n        raise ValueError("n must be non-negative")\n    result = []\n    a, b = 0, 1\n    for _ in range(n):\n        result.append(a)\n        a, b = b, a + b\n    return result\n\nassert fibonacci(7) == [0, 1, 1, 2, 3, 5, 8]\n```')
        if CodingEngine._has(q, r"palindrome") and CodingEngine._has(q, r"python"):
            return ('This version ignores spaces, punctuation and letter case for text input.\n\n'
                    '```python\nimport re\n\ndef is_palindrome(text):\n    normalized = re.sub(r"[^a-z0-9]", "", text.casefold())\n    return normalized == normalized[::-1]\n\nassert is_palindrome("Never odd or even")\nassert not is_palindrome("hello")\n```')
        if CodingEngine._has(q, r"stack and queue", r"difference between.*stack.*queue"):
            return ('A **stack** is last-in, first-out (LIFO); a **queue** is first-in, first-out (FIFO).\n\n'
                    '```python\nstack = []\nstack.append("a")  # push\nitem = stack.pop()  # pop: "a"\n\nfrom collections import deque\nqueue = deque()\nqueue.append("a")  # enqueue\nitem = queue.popleft()  # dequeue: "a"\n```')
        if CodingEngine._has(q, r"sql") and CodingEngine._has(q, r"select", r"query example", r"example"):
            return ('A basic SQL query selects named columns from a table and can filter rows with `WHERE`.\n\n'
                    '```sql\nSELECT name, email\nFROM users\nWHERE active = TRUE\nORDER BY name;\n```\n\n'
                    'Table and column names depend on your database schema.')
        return None

    async def process(self, query: str, context: Optional[str] = None) -> str:
        """Answer only with known templates or clearly relevant supplied context."""
        question = str(query or "").strip()
        if not question:
            return "Please provide a programming question or code snippet."
        error = self._error_answer(question)
        if error:
            return error
        answer = self._code_answer(question)
        if answer:
            return answer
        if context and str(context).strip():
            # Do not treat arbitrary memory as source evidence. Only use context
            # when it explicitly contains documentation/code relevant to the query.
            ctx = str(context).strip()
            q_terms = {w for w in re.findall(r"[a-zA-Z_][a-zA-Z0-9_+#.-]{2,}", question.casefold())}
            c_lower = ctx.casefold()
            if q_terms and sum(term in c_lower for term in q_terms) >= min(2, len(q_terms)):
                return ("Relevant local coding context (verbatim extract; not newly generated code):\n\n"
                        + ctx[:6000])
        return (
            "I’m running in strict no-LLM mode, so I won’t invent code for a task that has no verified local template or relevant documentation. "
            "Import the relevant language documentation or provide the code/error and exact requirements; ARIA can then retrieve evidence and use supported deterministic checks."
        )
