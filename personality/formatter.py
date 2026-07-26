import logging
from typing import Any

logger = logging.getLogger("aria")

class ResponseFormatter:
    @staticmethod
    to_markdown(raw_text: str) -> str:
        """Formats raw content into clean Markdown without altering underlying facts."""
        return raw_text.strip()

    @staticmethod
    to_bullet_list(items: list[str]) -> str:
        """Formats a list of strings into clean markdown bullet points."""
        if not items:
            return ""
        return "\n".join([f"• {item}" for item in items])

    @staticmethod
    to_code_block(code: str, language: str = "python") -> str:
        """Wraps code snippets safely."""
        return f"```{language}\n{code}\n```"
