"""Optional SearXNG metasearch provider for JARVIS.

SearXNG is a self-hosted open-source metasearch engine. It is used only when
``SEARXNG_BASE_URL`` is configured. No key is required, but the instance must
have the JSON output format enabled.

The client is intentionally small: bounded timeout, no retries that could
multiply external requests, and normalization into the same result shape used
by the existing SearchTool.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx

logger = logging.getLogger("aria")


class SearXNGClient:
    VERSION = "1.0.0"

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: float = 15.0,
        max_results: int = 5,
        language: Optional[str] = None,
    ) -> None:
        self.base_url = str(
            base_url if base_url is not None else os.getenv("SEARXNG_BASE_URL", "")
        ).strip().rstrip("/")
        self.timeout = max(3.0, min(float(timeout), 60.0))
        self.max_results = max(1, min(int(max_results), 10))
        self.language = str(
            language
            if language is not None
            else os.getenv("SEARXNG_LANGUAGE", "en")
        ).strip() or "en"
        self.enabled = (
            os.getenv("ARIA_SEARXNG_ENABLED", "1").strip().lower()
            not in {"0", "false", "no", "off"}
            and bool(self.base_url)
        )

    def is_configured(self) -> bool:
        return bool(self.enabled and self._valid_url())

    def _valid_url(self) -> bool:
        try:
            parsed = urlparse(self.base_url)
        except Exception:
            return False
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)

    def _search_url(self) -> str:
        if self.base_url.endswith("/search"):
            return self.base_url
        return self.base_url + "/search"

    async def search(
        self,
        query: str,
        *,
        max_results: Optional[int] = None,
        categories: Optional[str] = None,
        time_range: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        query = str(query or "").strip()
        if not query:
            return self._error("Search query is empty.")

        if not self.is_configured():
            return self._error(
                "SearXNG is not configured. Set SEARXNG_BASE_URL to a "
                "reachable instance with the JSON API enabled."
            )

        limit = max(1, min(int(max_results or self.max_results), 10))
        params = {
            "q": query,
            "format": "json",
            "language": self.language,
            "safesearch": os.getenv("SEARXNG_SAFESEARCH", "1"),
            "categories": categories
            or os.getenv("SEARXNG_CATEGORIES", "general"),
        }
        range_value = time_range or os.getenv("SEARXNG_TIME_RANGE", "").strip()
        if range_value:
            params["time_range"] = range_value

        headers = {
            "Accept": "application/json",
            "User-Agent": "JARVIS/1.0 (SearXNG research client)",
        }

        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                headers=headers,
                follow_redirects=True,
            ) as client:
                response = await client.get(
                    self._search_url(),
                    params=params,
                )

            if response.status_code == 429:
                return self._error(
                    "SearXNG rate limit reached.",
                    status_code=429,
                    retry_after=response.headers.get("Retry-After"),
                )

            response.raise_for_status()
            payload = response.json()

        except httpx.TimeoutException:
            return self._error("SearXNG search timed out.")
        except httpx.HTTPStatusError as exc:
            return self._error(
                f"SearXNG returned HTTP {exc.response.status_code}.",
                status_code=exc.response.status_code,
            )
        except Exception as exc:
            logger.warning(
                "[SearXNG] Search failed: %s",
                type(exc).__name__,
            )
            return self._error(
                f"SearXNG search failed: {type(exc).__name__}.",
            )

        results = self.normalize(payload, limit=limit)
        if not results:
            return self._error("SearXNG returned no usable results.")

        return {
            "success": True,
            "provider": "searxng",
            "query": query,
            "results": results,
            "count": len(results),
            "source": "SearXNG metasearch",
        }

    def normalize(
        self,
        payload: Any,
        *,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        if not isinstance(payload, dict):
            return []

        raw_results = payload.get("results")
        if not isinstance(raw_results, list):
            return []

        limit = max(1, min(int(limit or self.max_results), 10))
        results: List[Dict[str, Any]] = []
        seen: set[str] = set()

        for item in raw_results:
            if not isinstance(item, dict):
                continue

            url = str(item.get("url") or "").strip()
            title = str(item.get("title") or "").strip()
            snippet = str(
                item.get("content")
                or item.get("snippet")
                or item.get("description")
                or ""
            ).strip()

            if not (url or title or snippet):
                continue

            if url:
                try:
                    parsed = urlparse(url)
                except Exception:
                    continue
                if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                    continue
                if url.casefold() in seen:
                    continue
                seen.add(url.casefold())

            normalized = {
                "title": title,
                "url": url,
                "snippet": snippet,
                "engine": str(item.get("engine") or ""),
            }

            score = item.get("score")
            if score is not None:
                try:
                    normalized["score"] = float(score)
                except (TypeError, ValueError):
                    pass

            published = (
                item.get("publishedDate")
                or item.get("published_date")
                or item.get("date")
            )
            if published:
                normalized["published_date"] = str(published)[:100]

            results.append(normalized)
            if len(results) >= limit:
                break

        return results

    def _error(self, message: str, **metadata) -> Dict[str, Any]:
        output = {
            "success": False,
            "provider": "searxng",
            "results": [],
            "count": 0,
            "error": message,
        }
        output.update(metadata)
        return output

    def health(self) -> Dict[str, Any]:
        return {
            "status": "configured" if self.is_configured() else "unconfigured",
            "version": self.VERSION,
            "enabled": self.enabled,
            "base_url_configured": bool(self.base_url),
        }
