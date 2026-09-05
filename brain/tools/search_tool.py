"""
ARIA Search Tool
----------------
A provider-agnostic web search tool for ARIA.

The tool prefers an explicitly configured search provider and can use
Tavily when TAVILY_API_KEY is available. It returns structured results
without inventing information when the provider is unavailable.
"""

import asyncio
import logging
import os
import time
from typing import Any, Dict, List, Optional

from brain.tools.base_tool import BaseTool

logger = logging.getLogger("aria")

try:
    from tavily import TavilyClient
except ImportError:
    TavilyClient = None


class SearchTool(BaseTool):
    """Search the public web and return structured source results."""

    name = "search"
    description = (
        "Search the web for current or factual information and return "
        "structured results with titles, URLs, snippets, and optional content."
    )

    def __init__(
        self,
        api_key: Optional[str] = None,
        max_results: int = 5,
        timeout: float = 20.0,
    ):
        self.api_key = api_key or os.getenv("TAVILY_API_KEY")
        self.max_results = max(1, min(int(max_results), 10))
        self.timeout = max(3.0, float(timeout))
        self._client = None

        if self.api_key and TavilyClient is not None:
            try:
                self._client = TavilyClient(api_key=self.api_key)
            except Exception:
                logger.exception("[SearchTool] Failed to initialize Tavily client")

    def is_available(self) -> bool:
        return self._client is not None

    async def can_handle(
        self,
        query: str,
        context: Dict[str, Any],
    ) -> float:
        if not query or not query.strip():
            return 0.0

        text = query.lower().strip()

        explicit = (
            "search the web",
            "search online",
            "web search",
            "look up",
            "look it up",
            "find online",
            "find on the internet",
            "browse the web",
            "latest",
            "current news",
            "recent news",
            "today's news",
            "what happened today",
        )

        current = (
            "today",
            "latest",
            "current",
            "recent",
            "this week",
            "this month",
            "price",
            "weather",
            "stock",
            "news",
        )

        if any(term in text for term in explicit):
            return 0.98

        if any(term in text for term in current):
            return 0.82

        if context.get("requires_web") or context.get("web_search"):
            return 0.95

        return 0.0

    async def execute(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        started = time.monotonic()
        context = context or {}

        query = (query or "").strip()
        if not query:
            return self._error("Search query is empty.", started)

        if not self.is_available():
            return self._error(
                "Web search is unavailable. Configure TAVILY_API_KEY "
                "and install the optional Tavily client.",
                started,
            )

        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    self._client.search,
                    query=query,
                    max_results=self.max_results,
                    search_depth=context.get("search_depth", "advanced"),
                    include_answer=False,
                    include_raw_content=False,
                ),
                timeout=self.timeout,
            )

            results = self._normalize_results(response)

            return {
                "success": True,
                "tool": self.name,
                "query": query,
                "results": results,
                "count": len(results),
                "duration_ms": round(
                    (time.monotonic() - started) * 1000, 2
                ),
            }

        except asyncio.TimeoutError:
            logger.warning("[SearchTool] Search timed out: %s", query)
            return self._error("Web search timed out.", started)

        except Exception as exc:
            logger.exception("[SearchTool] Search failed")
            return self._error(
                f"Web search failed: {type(exc).__name__}.",
                started,
            )

    def _normalize_results(self, response: Any) -> List[Dict[str, Any]]:
        raw_results = []

        if isinstance(response, dict):
            raw_results = response.get("results") or []
        elif isinstance(response, list):
            raw_results = response

        normalized: List[Dict[str, Any]] = []

        for item in raw_results[: self.max_results]:
            if not isinstance(item, dict):
                continue

            url = str(item.get("url") or "").strip()
            title = str(item.get("title") or "").strip()
            snippet = str(
                item.get("content")
                or item.get("snippet")
                or ""
            ).strip()

            if not url and not title and not snippet:
                continue

            normalized.append(
                {
                    "title": title,
                    "url": url,
                    "snippet": snippet,
                    "score": item.get("score"),
                }
            )

        return normalized

    @staticmethod
    def _error(message: str, started: float) -> Dict[str, Any]:
        return {
            "success": False,
            "tool": "search",
            "results": [],
            "count": 0,
            "error": message,
            "duration_ms": round(
                (time.monotonic() - started) * 1000, 2
            ),
        }


WebSearchTool = SearchTool
