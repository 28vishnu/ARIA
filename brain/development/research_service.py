from __future__ import annotations

import logging
import time
from dataclasses import dataclass, asdict
from typing import Any, Iterable

logger = logging.getLogger("aria.research")


@dataclass(frozen=True)
class ResearchSource:
    title: str
    url: str
    snippet: str
    score: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ResearchResult:
    success: bool
    query: str
    sources: tuple[ResearchSource, ...] = ()
    duration_ms: float = 0.0
    error: str | None = None

    @property
    def count(self) -> int:
        return len(self.sources)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "query": self.query,
            "count": self.count,
            "sources": [item.to_dict() for item in self.sources],
            "duration_ms": self.duration_ms,
            "error": self.error,
        }


class RealTimeResearch:
    """Bounded research facade over ARIA's existing SearchTool.

    The service retrieves current public-web sources on demand. It does not
    copy the internet into persistent memory. Persistence, when explicitly
    requested by a caller, remains the responsibility of the knowledge layer.
    """

    def __init__(
        self,
        search_tool: Any,
        *,
        max_results: int = 8,
        search_depth: str = "advanced",
        timeout_seconds: float = 30.0,
    ) -> None:
        if search_tool is None:
            raise ValueError("search_tool is required")

        self.search_tool = search_tool
        self.max_results = max(1, min(int(max_results), 10))
        self.search_depth = str(search_depth or "advanced")
        self.timeout_seconds = max(3.0, float(timeout_seconds))

    async def research(
        self,
        query: str,
        *,
        context: dict[str, Any] | None = None,
    ) -> ResearchResult:
        started = time.monotonic()
        query = str(query or "").strip()

        if not query:
            return ResearchResult(
                success=False,
                query="",
                error="Research query is empty.",
            )

        request_context = dict(context or {})
        request_context.update(
            {
                "requires_web": True,
                "web_search": True,
                "search_depth": self.search_depth,
            }
        )

        original_limit = getattr(
            self.search_tool,
            "max_results",
            None,
        )

        try:
            if original_limit is not None:
                self.search_tool.max_results = self.max_results

            if hasattr(self.search_tool, "execute"):
                response = await self.search_tool.execute(
                    query,
                    context=request_context,
                )
            elif hasattr(self.search_tool, "search"):
                response = await self.search_tool.search(
                    query,
                    context=request_context,
                )
            else:
                raise RuntimeError(
                    "Configured search service has no supported search method."
                )

            if not isinstance(response, dict):
                raise RuntimeError("Search service returned an invalid response.")

            if not response.get("success"):
                return ResearchResult(
                    success=False,
                    query=query,
                    duration_ms=round(
                        (time.monotonic() - started) * 1000,
                        2,
                    ),
                    error=str(
                        response.get("error") or "Web research failed."
                    ),
                )

            sources: list[ResearchSource] = []
            seen_urls: set[str] = set()

            for item in response.get("results") or []:
                if not isinstance(item, dict):
                    continue

                url = str(item.get("url") or "").strip()
                title = str(item.get("title") or "").strip()
                snippet = str(
                    item.get("snippet")
                    or item.get("content")
                    or ""
                ).strip()

                if not url and not title and not snippet:
                    continue

                if url in seen_urls:
                    continue

                seen_urls.add(url)

                score = item.get("score")
                try:
                    score = float(score) if score is not None else None
                except (TypeError, ValueError):
                    score = None

                sources.append(
                    ResearchSource(
                        title=title[:500],
                        url=url[:2000],
                        snippet=snippet[:5000],
                        score=score,
                    )
                )

                if len(sources) >= self.max_results:
                    break

            return ResearchResult(
                success=True,
                query=query,
                sources=tuple(sources),
                duration_ms=round(
                    (time.monotonic() - started) * 1000,
                    2,
                ),
            )

        except Exception as exc:
            logger.exception("Real-time research failed")
            return ResearchResult(
                success=False,
                query=query,
                duration_ms=round(
                    (time.monotonic() - started) * 1000,
                    2,
                ),
                error=f"{type(exc).__name__}: {exc}",
            )
        finally:
            if original_limit is not None:
                try:
                    self.search_tool.max_results = original_limit
                except Exception:
                    pass

    async def research_many(
        self,
        queries: Iterable[str],
        *,
        context: dict[str, Any] | None = None,
    ) -> list[ResearchResult]:
        results: list[ResearchResult] = []
        seen: set[str] = set()

        for query in queries:
            normalized = str(query or "").strip()
            if not normalized or normalized.lower() in seen:
                continue
            seen.add(normalized.lower())
            results.append(
                await self.research(
                    normalized,
                    context=context,
                )
            )

        return results

    def health(self) -> dict[str, Any]:
        available = False
        try:
            available = bool(
                self.search_tool.is_available()
            )
        except Exception:
            available = False

        return {
            "healthy": available,
            "search_available": available,
            "max_results": self.max_results,
            "search_depth": self.search_depth,
        }

    def describe(self) -> dict[str, Any]:
        return {
            "name": "real_time_research",
            "capabilities": [
                "current_web_research",
                "multi_query_research",
                "source_deduplication",
                "source_provenance",
            ],
            "safety": [
                "bounded_results",
                "no_secret_exposure",
                "no_automatic_memory_dump",
                "on_demand_web_retrieval",
            ],
        }


__all__ = [
    "ResearchSource",
    "ResearchResult",
    "RealTimeResearch",
]
