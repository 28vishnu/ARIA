import asyncio
import logging
import os
from typing import Dict, Any

from actions.base import BaseAction, ActionResult
from brain.tools.search_tool import SearchTool

logger = logging.getLogger("aria")


class WebSearchAction(BaseAction):
    """
    Read-only internet search action for ARIA.

    Delegates web-search execution to the shared SearchTool so the
    action layer and ToolManager use the same provider, timeout,
    normalization, and error-handling logic.
    """

    name = "web_search_action"

    description = (
        "Searches the live web for current information and returns "
        "relevant results including titles, URLs, and extracted content."
    )

    permission_level = "safe"
    timeout_seconds = 30

    def __init__(self):
        self.search_tool = SearchTool(
            max_results=10,
            timeout=self.timeout_seconds,
        )

    async def validate(
        self,
        params: Dict[str, Any],
    ) -> bool:
        query = str(params.get("query", "")).strip()

        if not query or len(query) > 1000:
            return False

        try:
            max_results = int(params.get("max_results", 5))
        except (TypeError, ValueError):
            return False

        return 1 <= max_results <= 10

    async def execute(
        self,
        params: Dict[str, Any],
    ) -> ActionResult:
        if not await self.validate(params):
            return ActionResult(
                success=False,
                action_name=self.name,
                error="Invalid web search parameters.",
            )

        query = str(params.get("query", "")).strip()
        max_results = int(params.get("max_results", 5))

        # Reuse the shared search implementation rather than creating
        # a separate provider client for every action invocation.
        self.search_tool.max_results = max_results

        try:
            result = await asyncio.wait_for(
                self.search_tool.execute(
                    query=query,
                    context={
                        "search_depth": params.get(
                            "search_depth",
                            "advanced",
                        ),
                    },
                ),
                timeout=self.timeout_seconds,
            )

        except asyncio.TimeoutError:
            logger.warning(
                "[WebSearchAction] Search timed out. query=%r",
                query,
            )
            return ActionResult(
                success=False,
                action_name=self.name,
                error="Web search timed out.",
            )

        except Exception as exc:
            logger.exception(
                "[WebSearchAction] Search failed."
            )
            return ActionResult(
                success=False,
                action_name=self.name,
                error=f"Web search failed: {type(exc).__name__}.",
            )

        if not result.get("success"):
            return ActionResult(
                success=False,
                action_name=self.name,
                error=result.get(
                    "error",
                    "Web search failed.",
                ),
                data={
                    "query": query,
                    "results": [],
                    "result_count": 0,
                },
            )

        results = result.get("results", [])

        # Preserve the existing downstream contract while also exposing
        # the normalized result structure from SearchTool.
        content_parts = []

        for index, item in enumerate(results, start=1):
            title = str(item.get("title", "")).strip()
            url = str(item.get("url", "")).strip()
            text = str(item.get("snippet", "")).strip()

            content_parts.append(
                f"{index}. {title}\n"
                f"URL: {url}\n"
                f"{text}"
            )

        content = "\n\n".join(content_parts)

        logger.info(
            "[WebSearchAction] Search completed. "
            "query=%r results=%d",
            query,
            len(results),
        )

        return ActionResult(
            success=True,
            action_name=self.name,
            data={
                "content": content,
                "query": query,
                "results": results,
                "result_count": len(results),
                "duration_ms": result.get("duration_ms"),
            },
        )
