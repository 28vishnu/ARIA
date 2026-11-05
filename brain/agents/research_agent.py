from typing import Any, Dict, List

from brain.agents.base_agent import BaseAgent, AgentResponse


class ResearchAgent(BaseAgent):
    """
    Research and knowledge-extraction agent.

    The agent prefers real retrieval evidence. It never presents an LLM answer
    as if it came from a live source, and it never invents citations.
    """

    name = "research"
    aliases = ("research_agent", "web", "web_search")

    description = "Research, web search, and evidence extraction agent."
    version = "2.0.0"
    priority = 60
    timeout_seconds = 45.0
    max_retries = 1

    _TIME_SENSITIVE = (
        "today",
        "latest",
        "current",
        "recent",
        "news",
        "this week",
        "this month",
        "price",
        "weather",
        "stock",
        "election",
        "release",
    )

    async def can_handle(
        self,
        query: str,
        context: Dict[str, Any],
    ) -> float:

        q = str(query or "").lower()

        keywords = [
            "research",
            "explain",
            "history of",
            "overview of",
            "what is",
            "how does",
            "compare",
            "difference between",
            "summarize",
            "find sources",
            "look up",
        ]

        if any(phrase in q for phrase in keywords):
            return 0.90

        return 0.0

    async def execute(
        self,
        query: str,
        context: Dict[str, Any],
    ) -> AgentResponse:

        search_result = await self._search(query, context)
        results = self._results(search_result)

        if results:
            citations = [
                {
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "published_date": item.get("published_date"),
                }
                for item in results
                if item.get("url") or item.get("title")
            ]
            evidence = self._format_evidence(results)
            provider = str(
                search_result.get("provider")
                or "search"
            )

            answer = await self.complete_with_llm(
                context,
                (
                    "You are ARIA's research analyst. Answer only from the "
                    "supplied search evidence. Do not add facts that are not "
                    "in the evidence. Do not invent URLs or publication dates. "
                    "If the evidence is insufficient, explicitly say what is "
                    "missing. Distinguish what the sources state from your own "
                    "inference."
                ),
                (
                    f"User question: {query}\n\n"
                    f"Search evidence (provider: {provider}):\n{evidence}"
                ),
            )

            if not answer:
                answer = (
                    f"Live search results for: {query}\n\n"
                    f"{evidence}\n\n"
                    "No language model was used to synthesize these results."
                )

            return AgentResponse(
                success=True,
                confidence=0.8 if citations else 0.55,
                agent=self.name,
                data={
                    "response": answer,
                    "grounded": True,
                    "provider": provider,
                    "citations": citations,
                    "results": results,
                },
                metadata={
                    "grounded": True,
                    "evidence_count": len(citations),
                },
            )

        # No retrieval evidence. General model knowledge may still help for
        # timeless topics, but it must be labelled and must not claim currency.
        if not self._is_time_sensitive(query):
            answer = await self.complete_with_llm(
                context,
                (
                    "You are ARIA's research analyst. No live search results "
                    "are available. Answer from general knowledge only, never "
                    "claim the information is current, and never invent "
                    "citations or URLs. State clearly that no live sources "
                    "were retrieved."
                ),
                query,
            )
            if answer:
                return AgentResponse(
                    success=True,
                    confidence=0.5,
                    agent=self.name,
                    data={
                        "response": answer,
                        "grounded": False,
                        "citations": [],
                        "results": [],
                        "warning": (
                            "No live sources were retrieved; this answer uses "
                            "general model knowledge only."
                        ),
                    },
                    metadata={"grounded": False, "evidence_count": 0},
                )

        error = (
            "I could not retrieve live sources for this research request, "
            "and no language model is available to answer without them."
        )
        if search_result.get("error"):
            error += f" Search error: {search_result.get('error')}"

        return AgentResponse(
            success=False,
            confidence=0.0,
            agent=self.name,
            data={"results": []},
            error=error,
        )

    async def _search(
        self,
        query: str,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        registry = self._registry(context)
        search_tool = None
        if registry is not None:
            for name in ("search_tool", "web_search", "search"):
                try:
                    if registry.has(name):
                        search_tool = registry.get(name)
                        if search_tool is not None:
                            break
                except Exception:
                    continue

        if search_tool is None:
            return {
                "success": False,
                "error": "No search tool is registered.",
                "results": [],
            }

        try:
            if hasattr(search_tool, "execute"):
                try:
                    result = await search_tool.execute(
                        query=query,
                        context=context,
                    )
                except TypeError:
                    result = await search_tool.execute(query)
            elif hasattr(search_tool, "search"):
                result = await search_tool.search(query)
            else:
                result = None
        except Exception as exc:
            return {
                "success": False,
                "error": f"{type(exc).__name__}: {exc}",
                "results": [],
            }

        return result if isinstance(result, dict) else {
            "success": False,
            "error": "Search tool returned an invalid result.",
            "results": [],
        }

    @staticmethod
    def _results(search_result: Dict[str, Any]) -> List[Dict[str, Any]]:
        if not isinstance(search_result, dict):
            return []
        if search_result.get("success") is False:
            return []
        results = search_result.get("results")
        if not isinstance(results, list):
            return []
        return [item for item in results if isinstance(item, dict)]

    @staticmethod
    def _format_evidence(results: List[Dict[str, Any]]) -> str:
        lines = []
        for index, item in enumerate(results[:8], start=1):
            title = str(item.get("title") or "Untitled source")
            url = str(item.get("url") or "")
            snippet = str(item.get("snippet") or "").strip()
            published = item.get("published_date")
            line = f"[{index}] {title}"
            if url:
                line += f" ({url})"
            if published:
                line += f" published {published}"
            if snippet:
                line += f": {snippet[:500]}"
            lines.append(line)
        return "\n".join(lines)

    def _is_time_sensitive(self, query: str) -> bool:
        text = str(query or "").casefold()
        return any(marker in text for marker in self._TIME_SENSITIVE)
