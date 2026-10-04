"""ARIA Phase 1 — Dedicated Code Generation Bridge."""

from __future__ import annotations

import json
import logging
from typing import Any

from .code_generation_router import CodeGenerationRouter

logger = logging.getLogger("aria.development.codegen_bridge")


class LLMCodeGenerationBridge:
    """DevelopmentAgent adapter backed exclusively by CodeGenerationRouter."""

    DEFAULT_MAX_TOKENS = 4096
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
2. Never use absolute paths or '..'.
3. For create/modify, provide complete file content.
4. For delete, content must be empty.
5. Make the smallest safe change that satisfies the requirement.
6. Preserve existing behavior unless explicitly changed.
7. Never invent secrets or credentials.
8. Do not execute commands, deploy, push, or modify production.
9. Do not return Markdown fences or text outside the JSON object.
10. Include appropriate tests.
""".strip()

    def __init__(
        self,
        code_generation_router: CodeGenerationRouter,
        *,
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> None:
        self.code_generation_router = code_generation_router
        try:
            self.temperature = max(0.0, min(1.0, float(temperature)))
        except (TypeError, ValueError):
            self.temperature = self.DEFAULT_TEMPERATURE
        try:
            self.max_tokens = max(1024, min(8192, int(max_tokens)))
        except (TypeError, ValueError):
            self.max_tokens = self.DEFAULT_MAX_TOKENS

    @staticmethod
    def _compact_context(context: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(context, dict):
            return {}
        result = dict(context)
        repository = result.get("repository")
        if isinstance(repository, dict):
            files = repository.get("files")
            if isinstance(files, list):
                repository = dict(repository)
                repository["files"] = files[:8]
                result["repository"] = repository
        return result

    async def __call__(
        self,
        prompt: str,
        context: dict[str, Any] | None = None,
    ) -> str | dict[str, Any]:
        safe_context = self._compact_context(context or {})
        serialized = json.dumps(
            safe_context,
            ensure_ascii=False,
            default=str,
        )
        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "DEVELOPMENT CONTEXT:\n"
                    f"{serialized}\n\n"
                    "DEVELOPMENT REQUEST:\n"
                    f"{prompt}"
                ),
            },
        ]
        logger.info(
            "[Phase1][CodeGenerationBridge] Dedicated router request | context_chars=%d | max_tokens=%d",
            len(serialized),
            self.max_tokens,
        )
        return await self.code_generation_router.chat(
            messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            task="coding",
            context={
                "route": "coding",
                "llm_required": True,
                "development_generation": True,
            },
        )


__all__ = ["LLMCodeGenerationBridge"]
