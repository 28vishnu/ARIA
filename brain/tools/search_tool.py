"""Provider-agnostic, bounded web search for ARIA.

Tavily is preferred when configured. If it is unavailable or fails, the tool
uses Wikipedia's public MediaWiki search API as a limited no-key fallback.
The fallback is useful for background/context research; it is not a substitute
for a dedicated real-time news provider.
"""
from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from brain.tools.base_tool import BaseTool

logger = logging.getLogger("aria")

try:
    from tavily import TavilyClient
except ImportError:
    TavilyClient = None


class SearchTool(BaseTool):
    """Search the public web and return normalized structured results."""

    name = "search"
    description = (
        "Search the web for current or factual information and return "
        "structured results with titles, URLs, snippets, and optional content."
    )
    WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"

    def __init__(
        self,
        api_key: Optional[str] = None,
        max_results: int = 5,
        timeout: float = 20.0,
    ) -> None:
        self.api_key = api_key or os.getenv("TAVILY_API_KEY")
        self.max_results = max(1, min(int(max_results), 10))
        self.timeout = max(3.0, float(timeout))
        self._client = None
        self._cache: Dict[str, tuple[float, Dict[str, Any]]] = {}
        try:
            self.current_cache_ttl = max(0, min(int(os.getenv("ARIA_CURRENT_SEARCH_CACHE_TTL", "10")), 300))
        except (TypeError, ValueError):
            self.current_cache_ttl = 10
        try:
            self.cache_ttl = max(0, min(int(os.getenv("ARIA_SEARCH_CACHE_TTL", "60")), 3600))
        except (TypeError, ValueError):
            self.cache_ttl = 60
        if self.api_key and TavilyClient is not None:
            try:
                self._client = TavilyClient(api_key=self.api_key)
            except Exception:
                logger.exception("[SearchTool] Failed to initialize Tavily client")

    def is_available(self) -> bool:
        # The fallback requires no API key. Actual network availability is
        # established by execute(), not by this configuration-level check.
        return self._client is not None or os.getenv("ARIA_DISABLE_WIKIPEDIA_FALLBACK", "0").strip().lower() not in {"1", "true", "yes", "on"}

    async def can_handle(self, query: str, context: Dict[str, Any]) -> float:
        if not query or not query.strip():
            return 0.0
        text = query.lower().strip()
        explicit = ("search the web", "search online", "web search", "look up", "look it up", "find online", "find on the internet", "browse the web", "latest", "current news", "recent news", "today's news", "what happened today")
        current = ("today", "latest", "current", "recent", "this week", "this month", "price", "weather", "stock", "news")
        if any(term in text for term in explicit):
            return 0.98
        if any(term in text for term in current):
            return 0.82
        if context.get("requires_web") or context.get("web_search"):
            return 0.95
        return 0.0

    async def execute(self, query: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        started = time.monotonic()
        context = context or {}
        query = str(query or "").strip()
        if not query:
            return self._error("Search query is empty.", started)

        cache_key = " ".join(query.casefold().split())
        current_query = self._looks_time_sensitive(query) or bool(context.get("requires_freshness"))
        effective_cache_ttl = self.current_cache_ttl if current_query else self.cache_ttl
        cached = self._cache.get(cache_key)
        now = time.monotonic()
        if cached and effective_cache_ttl > 0 and now - cached[0] <= effective_cache_ttl:
            result = copy.deepcopy(cached[1])
            result["cached"] = True
            result["cache_age_seconds"] = round(now - cached[0], 2)
            result["duration_ms"] = round((now - started) * 1000, 2)
            return result
        if cached:
            self._cache.pop(cache_key, None)

        errors: list[str] = []
        if self._client is not None:
            try:
                response = await asyncio.wait_for(asyncio.to_thread(
                    self._client.search,
                    query=query,
                    max_results=self.max_results,
                    search_depth=context.get("search_depth", "advanced"),
                    include_answer=False,
                    include_raw_content=False,
                ), timeout=self.timeout)
                results = self._normalize_results(response)
                if results:
                    result = self._success(query, results, "tavily", started)
                    self._remember(cache_key, result)
                    return result
                errors.append("Tavily returned no usable results")
            except asyncio.TimeoutError:
                errors.append("Tavily search timed out")
                logger.warning("[SearchTool] Tavily search timed out; trying fallback: %s", query)
            except Exception as exc:
                message = str(exc).lower()
                if "429" in message or "rate limit" in message or "too many requests" in message:
                    errors.append("Tavily rate limit reached")
                    logger.warning("[SearchTool] Tavily rate limit reached; trying fallback")
                else:
                    errors.append(f"Tavily failed: {type(exc).__name__}")
                    logger.warning("[SearchTool] Tavily failed (%s); trying fallback", type(exc).__name__)

        fallback_disabled = os.getenv("ARIA_DISABLE_WIKIPEDIA_FALLBACK", "0").strip().lower() in {"1", "true", "yes", "on"}
        if not fallback_disabled:
            try:
                response = await asyncio.wait_for(
                    asyncio.to_thread(self._wikipedia_search, query),
                    timeout=self.timeout,
                )
                results = self._normalize_results(response)
                if results:
                    result = self._success(query, results, "wikipedia", started,
                                           warning="Limited background/context fallback; not a dedicated live-news source.")
                    self._remember(cache_key, result)
                    return result
                errors.append("Wikipedia returned no usable results")
            except asyncio.TimeoutError:
                errors.append("Wikipedia fallback timed out")
            except Exception as exc:
                errors.append(f"Wikipedia fallback failed: {type(exc).__name__}")
                logger.exception("[SearchTool] Wikipedia fallback failed")

        message = "; ".join(errors) or "No search provider is available."
        if current_query and "Wikipedia" in message:
            message += ". Current information could not be verified because the fallback is not a dedicated live-news provider."
        return self._error(message, started)

    def _wikipedia_search(self, query: str) -> Dict[str, Any]:
        params = urlencode({
            "action": "query", "list": "search", "srsearch": query,
            "format": "json", "utf8": 1, "srlimit": self.max_results,
        })
        request = Request(
            f"{self.WIKIPEDIA_API}?{params}",
            headers={"User-Agent": "ARIA-PersonalAssistant/1.0 (public knowledge search)"},
        )
        with urlopen(request, timeout=self.timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        raw = payload.get("query", {}).get("search", []) if isinstance(payload, dict) else []
        results = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title", "")).strip()
            if not title:
                continue
            page_title = title.replace(" ", "_")
            results.append({
                "title": title,
                "url": "https://en.wikipedia.org/wiki/" + page_title,
                "snippet": self._strip_html(str(item.get("snippet", ""))),
            })
        return {"results": results}

    @staticmethod
    def _strip_html(value: str) -> str:
        # MediaWiki search snippets contain simple HTML markup. Remove tags and
        # decode the few common entities without adding a heavy dependency.
        import re
        from html import unescape
        return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]*>", " ", value))).strip()

    def _normalize_results(self, response: Any) -> List[Dict[str, Any]]:
        raw_results = response.get("results") or [] if isinstance(response, dict) else response if isinstance(response, list) else []
        normalized: List[Dict[str, Any]] = []
        seen_urls: set[str] = set()
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            title = str(item.get("title") or "").strip()
            snippet = str(item.get("content") or item.get("snippet") or "").strip()
            if not (url or title or snippet) or (url and url in seen_urls):
                continue
            if url:
                parsed = urlparse(url)
                if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                    continue
                seen_urls.add(url)
            published_date = item.get("published_date") or item.get("publishedDate") or item.get("date")
            normalized_item = {"title": title, "url": url, "snippet": snippet, "score": item.get("score")}
            if published_date:
                normalized_item["published_date"] = str(published_date)[:100]
            normalized.append(normalized_item)
            if len(normalized) >= self.max_results:
                break
        return normalized

    @staticmethod
    def _looks_time_sensitive(query: str) -> bool:
        text = str(query or "").casefold()
        markers = ("today", "latest", "current", "right now", "this week", "breaking", "recent", "news", "stock price", "exchange rate", "weather", "election", "outage")
        return any(marker in text for marker in markers)

    def _remember(self, key: str, result: Dict[str, Any]) -> None:
        if self.cache_ttl <= 0 or not result.get("success"):
            return
        # Bound memory use; keep at most 128 successful query results.
        if len(self._cache) >= 128:
            oldest = min(self._cache, key=lambda item: self._cache[item][0])
            self._cache.pop(oldest, None)
        stored = copy.deepcopy(result)
        stored.pop("cached", None)
        stored.pop("cache_age_seconds", None)
        self._cache[key] = (time.monotonic(), stored)

    def _success(self, query: str, results: List[Dict[str, Any]], provider: str, started: float, warning: str | None = None) -> Dict[str, Any]:
        output = {"success": True, "tool": self.name, "query": query, "results": results[:self.max_results], "count": min(len(results), self.max_results), "provider": provider, "searched_at": datetime.now(timezone.utc).isoformat(), "duration_ms": round((time.monotonic() - started) * 1000, 2)}
        if warning:
            output["warning"] = warning
        return output

    @staticmethod
    def _error(message: str, started: float) -> Dict[str, Any]:
        return {"success": False, "tool": "search", "results": [], "count": 0, "error": message, "duration_ms": round((time.monotonic() - started) * 1000, 2)}


WebSearchTool = SearchTool
