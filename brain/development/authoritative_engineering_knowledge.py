from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass, field
from typing import Any, Iterable


logger = logging.getLogger("aria")


@dataclass(frozen=True)
class EngineeringKnowledgeResult:
    """
    Normalized knowledge result consumed by the engineering core.

    Knowledge is advisory unless backed by stronger evidence.
    """

    success: bool
    query: str
    items: tuple[dict[str, Any], ...] = ()
    source: str = ""
    authoritative: bool = False
    error: str | None = None
    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "query": self.query,
            "items": [
                dict(item)
                for item in self.items
            ],
            "source": self.source,
            "authoritative": self.authoritative,
            "error": self.error,
            "metadata": dict(self.metadata),
        }


class AuthoritativeEngineeringKnowledge:
    """
    Knowledge/research bridge for ARIA's engineering core.

    It connects existing knowledge infrastructure to the new
    authoritative engineering session without replacing the
    existing knowledge services.

    Priority:

        current execution evidence
                ↓
        repository facts
                ↓
        user requirements
                ↓
        official documentation
                ↓
        external research
                ↓
        historical experience
                ↓
        inference

    Knowledge never silently overrides current execution evidence.
    """

    DEFAULT_MAX_ITEMS = 20
    DEFAULT_MAX_ITEM_CHARS = 12_000

    def __init__(
        self,
        *,
        knowledge_database: Any | None = None,
        knowledge_graph: Any | None = None,
        knowledge_engine: Any | None = None,
        search_engine: Any | None = None,
        research_engine: Any | None = None,
        memory_engine: Any | None = None,
        session: Any | None = None,
        evidence_recorder: Any | None = None,
        max_items: int = DEFAULT_MAX_ITEMS,
        max_item_chars: int = DEFAULT_MAX_ITEM_CHARS,
    ) -> None:
        self.knowledge_database = (
            knowledge_database
        )
        self.knowledge_graph = (
            knowledge_graph
        )
        self.knowledge_engine = (
            knowledge_engine
        )
        self.search_engine = (
            search_engine
        )
        self.research_engine = (
            research_engine
        )
        self.memory_engine = (
            memory_engine
        )
        self.session = session
        self.evidence_recorder = (
            evidence_recorder
        )

        self.max_items = max(
            1,
            int(max_items),
        )

        self.max_item_chars = max(
            1_000,
            int(max_item_chars),
        )

    # ============================================================
    # Public knowledge API
    # ============================================================

    async def gather(
        self,
        query: str,
        *,
        requirement: Any | None = None,
        repository_context: Any | None = None,
        research: bool = True,
        include_history: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> EngineeringKnowledgeResult:
        """
        Gather engineering knowledge from available sources.

        The method is deliberately best-effort across ARIA's existing
        knowledge implementations because those services evolved
        independently during earlier Phase 1 work.
        """

        normalized_query = str(
            query or ""
        ).strip()

        if not normalized_query:
            return EngineeringKnowledgeResult(
                success=False,
                query="",
                error=(
                    "Knowledge query cannot be empty."
                ),
            )

        collected: list[dict[str, Any]] = []

        source_results = (
            (
                "knowledge_engine",
                self.knowledge_engine,
            ),
            (
                "knowledge_database",
                self.knowledge_database,
            ),
            (
                "knowledge_graph",
                self.knowledge_graph,
            ),
            (
                "search_engine",
                self.search_engine,
            ),
        )

        for source_name, service in source_results:
            if service is None:
                continue

            try:
                values = await self._query_service(
                    service,
                    normalized_query,
                )

                collected.extend(
                    self._normalize_items(
                        values,
                        source=source_name,
                    )
                )

            except Exception as exc:
                logger.warning(
                    "[EngineeringKnowledge] "
                    "Knowledge source failed | "
                    "source=%s | error=%s",
                    source_name,
                    exc,
                )

        if research and self.research_engine is not None:
            try:
                values = await self._query_service(
                    self.research_engine,
                    normalized_query,
                )

                collected.extend(
                    self._normalize_items(
                        values,
                        source="research",
                    )
                )

            except Exception as exc:
                logger.warning(
                    "[EngineeringKnowledge] "
                    "Research source failed | error=%s",
                    exc,
                )

        if include_history and self.memory_engine is not None:
            try:
                values = await self._query_service(
                    self.memory_engine,
                    normalized_query,
                )

                collected.extend(
                    self._normalize_items(
                        values,
                        source="historical_experience",
                    )
                )

            except Exception as exc:
                logger.warning(
                    "[EngineeringKnowledge] "
                    "Historical memory lookup failed | "
                    "error=%s",
                    exc,
                )

        collected = self._deduplicate(
            collected
        )

        collected = collected[
            : self.max_items
        ]

        result = EngineeringKnowledgeResult(
            success=True,
            query=normalized_query,
            items=tuple(collected),
            source="engineering_knowledge_bridge",
            authoritative=False,
            metadata={
                **(
                    metadata
                    or {}
                ),
                "item_count": len(
                    collected
                ),
                "research_enabled": research,
                "history_enabled": include_history,
                "knowledge_is_advisory": True,
            },
        )

        self._record_evidence(
            result
        )

        return result

    async def research(
        self,
        query: str,
        *,
        requirement: Any | None = None,
        repository_context: Any | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> EngineeringKnowledgeResult:
        """
        Explicit research entry point.

        Research remains advisory until verified against stronger
        evidence.
        """

        if self.research_engine is None:
            return EngineeringKnowledgeResult(
                success=False,
                query=str(query or ""),
                error=(
                    "No research engine is connected."
                ),
                metadata={
                    "research_available": False,
                },
            )

        return await self.gather(
            query,
            requirement=requirement,
            repository_context=repository_context,
            research=True,
            include_history=False,
            metadata={
                **(
                    metadata
                    or {}
                ),
                "mode": "research",
            },
        )

    async def retrieve(
        self,
        query: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> EngineeringKnowledgeResult:
        """
        Knowledge retrieval without requiring external research.
        """

        return await self.gather(
            query,
            research=False,
            include_history=True,
            metadata={
                **(
                    metadata
                    or {}
                ),
                "mode": "retrieval",
            },
        )

    # ============================================================
    # Service dispatch
    # ============================================================

    async def _query_service(
        self,
        service: Any,
        query: str,
    ) -> Any:
        """
        Call the first compatible query/retrieve/search method.

        No arbitrary method execution is allowed.
        """

        method_names = (
            "query",
            "retrieve",
            "search",
            "lookup",
            "find",
            "recall",
            "research",
            "ask",
        )

        for method_name in method_names:
            method = getattr(
                service,
                method_name,
                None,
            )

            if not callable(method):
                continue

            attempts = (
                lambda: method(query),
                lambda: method(
                    query=query
                ),
                lambda: method(
                    text=query
                ),
                lambda: method(
                    search_query=query
                ),
            )

            for attempt in attempts:
                try:
                    result = attempt()

                    if inspect.isawaitable(
                        result
                    ):
                        result = await result

                    return result

                except TypeError:
                    continue

        raise RuntimeError(
            "Connected knowledge service does not "
            "expose a supported retrieval interface."
        )

    # ============================================================
    # Normalization
    # ============================================================

    def _normalize_items(
        self,
        values: Any,
        *,
        source: str,
    ) -> list[dict[str, Any]]:
        if values is None:
            return []

        if isinstance(values, dict):
            if isinstance(
                values.get("items"),
                (list, tuple),
            ):
                values = values["items"]

            elif isinstance(
                values.get("results"),
                (list, tuple),
            ):
                values = values["results"]

            elif isinstance(
                values.get("documents"),
                (list, tuple),
            ):
                values = values["documents"]

            else:
                values = [values]

        elif isinstance(
            values,
            (str, bytes),
        ):
            values = [values]

        elif not isinstance(
            values,
            Iterable,
        ):
            values = [values]

        normalized: list[dict[str, Any]] = []

        for item in values:
            normalized_item = (
                self._normalize_item(
                    item,
                    source=source,
                )
            )

            if normalized_item is not None:
                normalized.append(
                    normalized_item
                )

        return normalized

    def _normalize_item(
        self,
        item: Any,
        *,
        source: str,
    ) -> dict[str, Any] | None:
        if item is None:
            return None

        if isinstance(item, dict):
            payload = dict(item)

        else:
            to_dict = getattr(
                item,
                "to_dict",
                None,
            )

            if callable(to_dict):
                try:
                    payload = dict(
                        to_dict()
                    )
                except Exception:
                    payload = {
                        "content": str(item)
                    }
            else:
                payload = {
                    "content": str(item)
                }

        content = (
            payload.get("content")
            or payload.get("text")
            or payload.get("summary")
            or payload.get("description")
            or ""
        )

        content = str(content)

        if len(content) > self.max_item_chars:
            content = (
                content[
                    : self.max_item_chars
                ]
                + "\n[truncated]"
            )

        if not content and not payload:
            return None

        return {
            "source": str(
                payload.get(
                    "source",
                    source,
                )
            ),
            "content": content,
            "title": str(
                payload.get(
                    "title",
                    "",
                )
            ),
            "url": str(
                payload.get(
                    "url",
                    "",
                )
            ),
            "authority": str(
                payload.get(
                    "authority",
                    "advisory",
                )
            ),
            "confidence": payload.get(
                "confidence"
            ),
            "metadata": (
                payload.get(
                    "metadata",
                    {},
                )
                if isinstance(
                    payload.get(
                        "metadata",
                        {},
                    ),
                    dict,
                )
                else {}
            ),
        }

    # ============================================================
    # Deduplication
    # ============================================================

    @staticmethod
    def _deduplicate(
        items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        seen: set[str] = set()
        result: list[dict[str, Any]] = []

        for item in items:
            key = (
                str(
                    item.get(
                        "source",
                        "",
                    )
                )
                + "|"
                + str(
                    item.get(
                        "title",
                        "",
                    )
                )
                + "|"
                + str(
                    item.get(
                        "content",
                        "",
                    )
                )[:1_000]
            )

            if key in seen:
                continue

            seen.add(key)
            result.append(item)

        return result

    # ============================================================
    # Evidence integration
    # ============================================================

    def _record_evidence(
        self,
        result: EngineeringKnowledgeResult,
    ) -> None:
        recorder = (
            self.evidence_recorder
        )

        if recorder is None:
            return

        try:
            recorder.record(
                kind="knowledge",
                summary=(
                    "Engineering knowledge gathered."
                ),
                details=result.to_dict(),
                source=(
                    "authoritative_engineering_knowledge"
                ),
            )

        except Exception:
            logger.exception(
                "[EngineeringKnowledge] "
                "Could not record knowledge evidence."
            )

    # ============================================================
    # Context construction
    # ============================================================

    def build_context(
        self,
        result: EngineeringKnowledgeResult,
    ) -> dict[str, Any]:
        """
        Produce a bounded context object for planning/reasoning.

        This does not claim that retrieved information is true.
        """

        return {
            "query": result.query,
            "items": [
                {
                    "source": item.get(
                        "source",
                        "",
                    ),
                    "title": item.get(
                        "title",
                        "",
                    ),
                    "content": item.get(
                        "content",
                        "",
                    ),
                    "authority": item.get(
                        "authority",
                        "advisory",
                    ),
                    "confidence": item.get(
                        "confidence"
                    ),
                }
                for item in result.items
            ],
            "count": len(
                result.items
            ),
            "knowledge_status": (
                "advisory"
            ),
            "execution_evidence_precedence": True,
        }

    def health(self) -> dict[str, Any]:
        return {
            "healthy": True,
            "knowledge_database": (
                self.knowledge_database
                is not None
            ),
            "knowledge_graph": (
                self.knowledge_graph
                is not None
            ),
            "knowledge_engine": (
                self.knowledge_engine
                is not None
            ),
            "search_engine": (
                self.search_engine
                is not None
            ),
            "research_engine": (
                self.research_engine
                is not None
            ),
            "memory_engine": (
                self.memory_engine
                is not None
            ),
        }