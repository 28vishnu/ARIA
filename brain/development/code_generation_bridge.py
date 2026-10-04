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
        self.max_tokens = max(1024, min(8192, self.max_tokens))

    @staticmethod
    def _compact_context(context: dict[str, Any]) -> dict[str, Any]:
        """
        Keep code-generation prompts small enough for free/provider limits.

        DevelopmentAgent may prepare a large repository context. A code
        generator does not need every repository file on every request.
        For modifications, keep explicitly requested/changed files first;
        for create-only requests, repository file contents are unnecessary.
        """
        if not isinstance(context, dict):
            return {}

        result = dict(context)
        requirement = result.get("requirement") or {}
        plan = result.get("plan") or {}
        repository = result.get("repository") or {}

        requested = []
        if isinstance(requirement, dict):
            requested.extend(requirement.get("requested_files") or [])
        if isinstance(plan, dict):
            for change in plan.get("changes") or []:
                if isinstance(change, dict) and change.get("path"):
                    requested.append(change["path"])

        requested = list(dict.fromkeys(str(x) for x in requested if x))
        files = repository.get("files") if isinstance(repository, dict) else []
        files = files if isinstance(files, list) else []

        # A create-only request needs no existing source context.
        plan_changes = plan.get("changes") if isinstance(plan, dict) else []
        plan_changes = plan_changes if isinstance(plan_changes, list) else []
        create_only = bool(
            isinstance(requirement, dict)
            and (
                (requirement.get("metadata") or {}).get("create_only")
                or (
                    plan_changes
                    and all(
                        str(change.get("action", change.get("operation", ""))).lower()
                        == "create"
                        for change in plan_changes
                        if isinstance(change, dict)
                    )
                )
            )
        )

        selected = []
        if not create_only:
            by_path = {str(f.get("path")): f for f in files if isinstance(f, dict) and f.get("path")}
            for path in requested:
                item = by_path.get(path)
                if item:
                    selected.append(item)

            # If no explicit target was available, retain a small bounded
            # sample of textual context rather than the entire repository.
            if not selected:
                selected = files[:6]

        compact_repo = {
            "repository_root": repository.get("repository_root", "."),
            "file_count": repository.get("file_count", 0),
            "workspace_file_count": repository.get("workspace_file_count", 0),
            "files": selected,
            "safety": repository.get("safety", {}),
        }
        result["repository"] = compact_repo
        result["_codegen_context_policy"] = {
            "create_only": create_only,
            "requested_files": requested,
            "repository_files_in_prompt": len(selected),
        }
        return result

    async def __call__(
        self,
        prompt: str,
        context: dict[str, Any] | None = None,
    ) -> str | dict[str, Any]:
        safe_context = self._compact_context(context if isinstance(context, dict) else {})

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
            "code generation | task=coding | max_tokens=%s | context_chars=%s",
            self.max_tokens,
            len(json.dumps(safe_context, ensure_ascii=False, default=str)),
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
