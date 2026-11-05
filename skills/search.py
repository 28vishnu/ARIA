"""Read-only search skill backed by ARIA's shared SearchTool."""
from __future__ import annotations

import logging
from typing import Any, Dict

from skills.base import BaseSkill, SkillResponse

logger = logging.getLogger("aria")


class SearchSkill(BaseSkill):
    name = "search"
    description = "Performs live web or knowledge lookups using ARIA's configured search provider."
    version = "1.1.0"
    priority = 20
    requires_llm = False

    async def can_run(self, query: str, context: Dict[str, Any]) -> float:
        cleaned = str(query or "").lower().strip()
        keywords = (
            "search", "find", "look up", "lookup", "google", "bing",
            "latest", "news", "current", "search online", "search the web",
            "browse the web", "what happened today",
        )
        if any(keyword in cleaned for keyword in keywords):
            return 0.90
        if context.get("requires_web") or context.get("web_search"):
            return 0.85
        return 0.0

    async def execute(self, query: str, context: Dict[str, Any]) -> SkillResponse:
        query = str(query or "").strip()
        if not query:
            return SkillResponse(False, 0.0, self.name, error="Search query is empty.")

        app_state = context.get("app_state")
        registry = getattr(app_state, "registry", None) if app_state is not None else None
        search_tool = None
        if registry is not None:
            try:
                search_tool = registry.get("search_tool")
            except (KeyError, LookupError, AttributeError):
                search_tool = None

        # Allow workflow callers to explicitly inject a compatible tool for tests or isolated runs.
        search_tool = search_tool or context.get("search_tool")
        if search_tool is None or not callable(getattr(search_tool, "execute", None)):
            return SkillResponse(
                False, 0.0, self.name,
                error="Search is not configured. The shared SearchTool is unavailable.",
            )

        try:
            result = await search_tool.execute(
                query=query,
                context={
                    "search_depth": context.get("search_depth", "advanced"),
                    "requires_freshness": bool(context.get("requires_freshness")),
                },
            )
        except Exception as exc:
            logger.exception("[SearchSkill] Search execution failed")
            return SkillResponse(False, 0.0, self.name, error=f"Search failed: {type(exc).__name__}.")

        if not isinstance(result, dict) or not result.get("success"):
            error = result.get("error", "Search returned no results.") if isinstance(result, dict) else "Search returned an invalid response."
            return SkillResponse(False, 0.0, self.name, data=result, error=str(error))

        results = result.get("results") or []
        return SkillResponse(
            True, 0.90 if results else 0.45, self.name,
            data={
                "query": query,
                "provider": result.get("provider"),
                "results": results,
                "result_count": len(results),
                "cached": bool(result.get("cached", False)),
                "warning": result.get("warning"),
            },
        )
