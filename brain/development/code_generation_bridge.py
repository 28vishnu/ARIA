"""
ARIA Phase 1 — LLM Code Generation Bridge

Connects the existing LLMRouter to DevelopmentAgent.

This bridge only requests structured code-generation data.
It does not write files, execute commands, deploy, or push code.
Those responsibilities remain behind DevelopmentAgent's safety
and isolated-workspace controls.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from brain.llm.llm_router import LLMRouter

logger = logging.getLogger("aria")


class LLMCodeGenerationBridge:
    """Adapter from DevelopmentAgent's CodeGenerator to LLMRouter."""

    DEFAULT_MAX_TOKENS = 16384
    DEFAULT_TEMPERATURE = 0.15

    SYSTEM_PROMPT = """
You are ARIA's isolated software-development code generator.

Transform the supplied development requirement into safe,
repository-relative code changes for ARIA's DevelopmentAgent.

Return exactly ONE valid JSON object and NOTHING ELSE.

Required schema:
{
  "summary": "short description",
  "reasoning": "technical reasoning",
  "changes": [
    {
      "path": "relative/path",
      "operation": "create|modify|delete",
      "content": "complete file content"
    }
  ],
  "tests": ["test path or test description"]
}

Rules:
1. Paths must be repository-relative.
2. Never use absolute paths.
3. Never use '..' path traversal.
4. For create/modify, provide complete file content.
5. For delete, content must be an empty string.
6. Make the smallest safe change that satisfies the requirement.
7. Preserve existing behavior unless explicitly changed.
8. Never invent secrets, API keys, passwords, tokens, credentials,
   environment values, or private data.
9. Do not execute commands.
10. Do not deploy.
11. Do not push to GitHub.
12. Do not modify production directly.
13. Do not return Markdown fences.
14. Do not put explanatory text outside the JSON object.
15. When modifying a file, use the repository context supplied by
    DevelopmentAgent and return the COMPLETE resulting file.
16. Prefer precise changes over broad refactoring.
17. Include appropriate tests for the requested change.
""".strip()

    def __init__(
        self,
        llm_router: LLMRouter,
        *,
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> None:
        self.llm_router = llm_router

        try:
            self.temperature = float(temperature)
        except (TypeError, ValueError):
            self.temperature = self.DEFAULT_TEMPERATURE

        try:
            self.max_tokens = int(max_tokens)
        except (TypeError, ValueError):
            self.max_tokens = self.DEFAULT_MAX_TOKENS

        self.temperature = max(0.0, min(1.0, self.temperature))
        self.max_tokens = max(4096, min(65536, self.max_tokens))

    async def __call__(
        self,
        prompt: str,
        context: dict[str, Any] | None = None,
    ) -> str | dict[str, Any]:
        safe_context = context if isinstance(context, dict) else {}

        messages = [
            {
                "role": "system",
                "content": self.SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": (
                    "DEVELOPMENT CONTEXT:\n"
                    f"{json.dumps(safe_context, ensure_ascii=False, default=str)}\n\n"
                    "DEVELOPMENT REQUEST:\n"
                    f"{prompt}"
                ),
            },
        ]

        logger.info(
            "[Phase1][CodeGenerationBridge] Requesting structured "
            "code generation | task=coding | max_tokens=%s",
            self.max_tokens,
        )

        response = await self.llm_router.chat(
            messages=messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            task="coding",
            context={
                "route": "coding",
                "llm_required": True,
                "development_generation": True,
            },
        )

        if response is None:
            raise RuntimeError(
                "LLMRouter returned no response for code generation."
            )

        if isinstance(response, (str, dict)):
            return response

        return str(response)


__all__ = ["LLMCodeGenerationBridge"]
