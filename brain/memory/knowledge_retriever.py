"""
ARIA Phase 1 — Step 9: Knowledge Retrieval.

Unified, bounded and deterministic knowledge retrieval layer.

Retrieval order:
    1. Durable knowledge database
    2. Semantic/vector knowledge search
    3. Personal memory
    4. Active document context
    5. Conversation context
    6. Knowledge graph

This module returns evidence only.
It never generates an answer and never calls an LLM.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence

logger = logging.getLogger("aria")


class KnowledgeRetriever:
    """
    Unified evidence retrieval for ARIA.

    The retriever deliberately keeps retrieval separate from reasoning and
    answer generation. This allows the reasoning layer to decide how much
    evidence should enter the model context.
    """

    VERSION = "PHASE1-KNOWLEDGE-RETRIEVAL-20261004"

    DEFAULT_LIMIT = 10
    MAX_LIMIT = 50

    def __init__(
        self,
        memory_engine=None,
        document_ai=None,
        state_manager=None,
        knowledge_database=None,
        knowledge_graph=None,
    ):
        self.memory_engine = memory_engine
        self.document_ai = document_ai
        self.state_manager = state_manager
        self.knowledge_database = knowledge_database
        self.knowledge_graph = knowledge_graph

    # =========================================================
    # MAIN RETRIEVAL API
    # =========================================================

    async def retrieve(
        self,
        query: str,
        user_id: str = "",
        session_id: str = "",
        context: Optional[Dict[str, Any]] = None,
        limit: int = DEFAULT_LIMIT,
        include_memory: bool = True,
        include_documents: bool = True,
        include_graph: bool = True,
    ) -> Dict[str, Any]:
        """
        Retrieve bounded evidence from ARIA's knowledge systems.

        No final answer is produced here.
        """

        query = self._normalize_query(query)
        context = context or {}

        limit = self._safe_limit(limit)

        result: Dict[str, Any] = {
            "version": self.VERSION,
            "query": query,
            "personal_memories": [],
            "knowledge": [],
            "document_knowledge": [],
            "conversation_context": [],
            "graph_knowledge": [],
            "active_document": None,
            "has_evidence": False,
            "sources_used": [],
            "retrieval_errors": [],
        }

        if not query:
            return result

        # -----------------------------------------------------
        # 1. DURABLE KNOWLEDGE
        # -----------------------------------------------------

        if self.knowledge_database is not None:
            try:
                knowledge = await self._retrieve_database(
                    query=query,
                    limit=limit,
                )

                result["knowledge"] = self._normalize_results(
                    knowledge,
                    limit=limit,
                )

                if result["knowledge"]:
                    result["sources_used"].append(
                        "knowledge_database"
                    )

            except Exception as exc:
                logger.exception(
                    "[KnowledgeRetriever] "
                    "Knowledge database retrieval failed."
                )

                result["retrieval_errors"].append(
                    {
                        "source": "knowledge_database",
                        "error": str(exc),
                    }
                )

        # -----------------------------------------------------
        # 2. PERSONAL MEMORY
        # -----------------------------------------------------

        if include_memory and self.memory_engine is not None:
            try:
                memories = await self._retrieve_memory(
                    query=query,
                    user_id=user_id,
                    limit=limit,
                )

                result["personal_memories"] = (
                    self._normalize_results(
                        memories,
                        limit=limit,
                    )
                )

                if result["personal_memories"]:
                    result["sources_used"].append(
                        "personal_memory"
                    )

            except Exception as exc:
                logger.exception(
                    "[KnowledgeRetriever] "
                    "Memory retrieval failed."
                )

                result["retrieval_errors"].append(
                    {
                        "source": "personal_memory",
                        "error": str(exc),
                    }
                )

        # -----------------------------------------------------
        # 3. ACTIVE DOCUMENT
        # -----------------------------------------------------

        state = context.get("state")

        if not state and self.state_manager is not None:
            try:
                state = self.state_manager.get_state(
                    session_id
                ) or {}
            except Exception as exc:
                logger.exception(
                    "[KnowledgeRetriever] "
                    "Could not load session state."
                )

                result["retrieval_errors"].append(
                    {
                        "source": "state_manager",
                        "error": str(exc),
                    }
                )

                state = {}

        state = state or {}

        current_document = state.get(
            "current_document"
        )

        if current_document:
            result["active_document"] = (
                current_document
            )

        # -----------------------------------------------------
        # 4. DOCUMENT KNOWLEDGE
        # -----------------------------------------------------

        if (
            include_documents
            and self.document_ai is not None
        ):
            try:
                documents = await self._retrieve_documents(
                    query=query,
                    limit=limit,
                    context=context,
                )

                result["document_knowledge"] = (
                    self._normalize_results(
                        documents,
                        limit=limit,
                    )
                )

                if result["document_knowledge"]:
                    result["sources_used"].append(
                        "document_knowledge"
                    )

            except Exception as exc:
                logger.exception(
                    "[KnowledgeRetriever] "
                    "Document retrieval failed."
                )

                result["retrieval_errors"].append(
                    {
                        "source": "document_knowledge",
                        "error": str(exc),
                    }
                )

        # -----------------------------------------------------
        # 5. CONVERSATION CONTEXT
        # -----------------------------------------------------

        conversation = (
            context.get("conversation_history")
            or context.get("recent_conversation")
            or []
        )

        if conversation:
            result["conversation_context"] = (
                self._bound_conversation(
                    conversation,
                    limit=limit,
                )
            )

            if result["conversation_context"]:
                result["sources_used"].append(
                    "conversation_context"
                )

        # -----------------------------------------------------
        # 6. KNOWLEDGE GRAPH
        # -----------------------------------------------------

        if (
            include_graph
            and self.knowledge_graph is not None
        ):
            try:
                graph_results = (
                    await self._retrieve_graph(
                        query=query,
                        limit=limit,
                    )
                )

                result["graph_knowledge"] = (
                    self._normalize_results(
                        graph_results,
                        limit=limit,
                    )
                )

                if result["graph_knowledge"]:
                    result["sources_used"].append(
                        "knowledge_graph"
                    )

            except Exception as exc:
                logger.exception(
                    "[KnowledgeRetriever] "
                    "Knowledge graph retrieval failed."
                )

                result["retrieval_errors"].append(
                    {
                        "source": "knowledge_graph",
                        "error": str(exc),
                    }
                )

        # -----------------------------------------------------
        # 7. FINAL EVIDENCE FLAG
        # -----------------------------------------------------

        result["has_evidence"] = bool(
            result["knowledge"]
            or result["personal_memories"]
            or result["document_knowledge"]
            or result["conversation_context"]
            or result["graph_knowledge"]
            or result["active_document"]
        )

        logger.info(
            "[KnowledgeRetriever] "
            "Retrieved evidence: "
            "knowledge=%d memory=%d documents=%d "
            "conversation=%d graph=%d",
            len(result["knowledge"]),
            len(result["personal_memories"]),
            len(result["document_knowledge"]),
            len(result["conversation_context"]),
            len(result["graph_knowledge"]),
        )

        return result

    # =========================================================
    # KNOWLEDGE DATABASE
    # =========================================================

    async def _retrieve_database(
        self,
        query: str,
        limit: int,
    ) -> List[Any]:

        database = self.knowledge_database

        # Preferred hybrid/semantic search.
        semantic_search = getattr(
            database,
            "semantic_search",
            None,
        )

        if semantic_search is not None:
            try:
                result = semantic_search(
                    query,
                    limit=limit,
                )

                result = await self._await_if_needed(
                    result
                )

                if result:
                    return self._rank_results(
                        result,
                        limit,
                    )

            except TypeError:
                try:
                    result = semantic_search(
                        query=query,
                        limit=limit,
                    )

                    result = await self._await_if_needed(
                        result
                    )

                    if result:
                        return self._rank_results(
                            result,
                            limit,
                        )

                except Exception:
                    logger.debug(
                        "[KnowledgeRetriever] "
                        "Semantic search signature failed.",
                        exc_info=True,
                    )

            except Exception:
                logger.debug(
                    "[KnowledgeRetriever] "
                    "Semantic search failed.",
                    exc_info=True,
                )

        # Fallback to normal database search.
        search = getattr(
            database,
            "search",
            None,
        )

        if search is None:
            return []

        try:
            result = search(
                query,
                limit=limit,
            )
        except TypeError:
            result = search(
                query=query,
                limit=limit,
            )

        result = await self._await_if_needed(
            result
        )

        return self._rank_results(
            result,
            limit,
        )

    # =========================================================
    # PERSONAL MEMORY
    # =========================================================

    async def _retrieve_memory(
        self,
        query: str,
        user_id: str,
        limit: int,
    ) -> List[Any]:

        engine = self.memory_engine

        # Preferred API.
        method = getattr(
            engine,
            "retrieve_relevant",
            None,
        )

        if method is not None:
            try:
                result = method(
                    user_id=user_id,
                    query=query,
                    limit=limit,
                )

                return await self._await_if_needed(
                    result
                )

            except TypeError:
                pass

        # Common fallback.
        method = getattr(
            engine,
            "get_relevant_memories",
            None,
        )

        if method is not None:
            try:
                result = method(
                    query,
                    limit,
                )
            except TypeError:
                result = method(
                    query=query,
                    limit=limit,
                )

            return await self._await_if_needed(
                result
            )

        # Last compatible fallback.
        method = getattr(
            engine,
            "search",
            None,
        )

        if method is None:
            return []

        try:
            result = method(
                query,
                limit=limit,
            )
        except TypeError:
            result = method(
                query=query,
                limit=limit,
            )

        return await self._await_if_needed(
            result
        )

    # =========================================================
    # DOCUMENT RETRIEVAL
    # =========================================================

    async def _retrieve_documents(
        self,
        query: str,
        limit: int,
        context: Dict[str, Any],
    ) -> List[Any]:

        document_ai = self.document_ai

        # Retrieval-only methods are preferred.
        for method_name in (
            "retrieve",
            "search",
            "search_documents",
            "retrieve_relevant",
            "find_relevant",
        ):

            method = getattr(
                document_ai,
                method_name,
                None,
            )

            if method is None:
                continue

            try:
                result = method(
                    query=query,
                    limit=limit,
                    context=context,
                )

                result = await self._await_if_needed(
                    result
                )

                if result:
                    return result

            except TypeError:
                try:
                    result = method(
                        query,
                        limit,
                    )

                    result = await self._await_if_needed(
                        result
                    )

                    if result:
                        return result

                except Exception:
                    logger.debug(
                        "[KnowledgeRetriever] "
                        "Document method %s failed.",
                        method_name,
                        exc_info=True,
                    )

            except Exception:
                logger.debug(
                    "[KnowledgeRetriever] "
                    "Document method %s failed.",
                    method_name,
                    exc_info=True,
                )

        # Deliberately do NOT call answer_question().
        # Retrieval must return evidence, not generated answers.
        return []

    # =========================================================
    # KNOWLEDGE GRAPH
    # =========================================================

    async def _retrieve_graph(
        self,
        query: str,
        limit: int,
    ) -> List[Any]:

        graph = self.knowledge_graph

        for method_name in (
            "search",
            "query",
            "find_related",
            "related_knowledge",
        ):

            method = getattr(
                graph,
                method_name,
                None,
            )

            if method is None:
                continue

            try:
                result = method(
                    query,
                    limit=limit,
                )

                result = await self._await_if_needed(
                    result
                )

                if result:
                    return result

            except TypeError:
                try:
                    result = method(
                        query=query,
                        limit=limit,
                    )

                    result = await self._await_if_needed(
                        result
                    )

                    if result:
                        return result

                except Exception:
                    logger.debug(
                        "[KnowledgeRetriever] "
                        "Graph method %s failed.",
                        method_name,
                        exc_info=True,
                    )

            except Exception:
                logger.debug(
                    "[KnowledgeRetriever] "
                    "Graph method %s failed.",
                    method_name,
                    exc_info=True,
                )

        return []

    # =========================================================
    # RESULT NORMALIZATION
    # =========================================================

    def _normalize_results(
        self,
        results: Any,
        limit: int,
    ) -> List[Dict[str, Any]]:

        if results is None:
            return []

        if isinstance(
            results,
            dict,
        ):
            # Some APIs return {"results": [...]}.
            for key in (
                "results",
                "items",
                "data",
                "knowledge",
                "memories",
            ):
                if isinstance(
                    results.get(key),
                    (list, tuple),
                ):
                    results = results[key]
                    break
            else:
                results = [results]

        if isinstance(
            results,
            str,
        ):
            results = [results]

        if not isinstance(
            results,
            (list, tuple, set),
        ):
            results = [results]

        normalized: List[Dict[str, Any]] = []

        for item in results:

            if isinstance(
                item,
                dict,
            ):
                record = dict(item)

            else:
                record = {
                    "content": str(item),
                }

            content = (
                record.get("content")
                or record.get("text")
                or record.get("summary")
                or record.get("value")
                or ""
            )

            record["content"] = str(
                content
            ).strip()

            if not record["content"]:
                continue

            record.setdefault(
                "retrieval_score",
                record.get(
                    "score",
                    0.0,
                ),
            )

            normalized.append(
                record
            )

        return self._rank_results(
            normalized,
            limit,
        )

    def _rank_results(
        self,
        results: Any,
        limit: int,
    ) -> List[Any]:

        if results is None:
            return []

        if not isinstance(
            results,
            (list, tuple),
        ):
            results = [results]

        def score(item: Any) -> float:

            if isinstance(
                item,
                dict,
            ):
                for key in (
                    "retrieval_score",
                    "score",
                    "similarity",
                    "relevance",
                    "confidence",
                ):
                    try:
                        value = item.get(
                            key,
                            0.0,
                        )

                        return float(
                            value
                        )
                    except (
                        TypeError,
                        ValueError,
                    ):
                        continue

            return 0.0

        indexed = list(
            enumerate(results)
        )

        indexed.sort(
            key=lambda pair: (
                -score(pair[1]),
                pair[0],
            )
        )

        return [
            item
            for _, item in indexed[:limit]
        ]

    # =========================================================
    # CONVERSATION BOUNDING
    # =========================================================

    @staticmethod
    def _bound_conversation(
        conversation: Iterable[Any],
        limit: int,
    ) -> List[Any]:

        items = list(
            conversation
        )

        # Keep the most recent context while preserving order.
        max_items = min(
            max(
                limit * 2,
                10,
            ),
            40,
        )

        return items[
            -max_items:
        ]

    # =========================================================
    # UTILITIES
    # =========================================================

    @staticmethod
    def _normalize_query(
        query: Any,
    ) -> str:

        text = str(
            query or ""
        )

        text = re.sub(
            r"\s+",
            " ",
            text,
        ).strip()

        return text

    @classmethod
    def _safe_limit(
        cls,
        limit: Any,
    ) -> int:

        try:
            value = int(
                limit
            )
        except (
            TypeError,
            ValueError,
        ):
            value = cls.DEFAULT_LIMIT

        return max(
            1,
            min(
                cls.MAX_LIMIT,
                value,
            ),
        )

    @staticmethod
    async def _await_if_needed(
        value: Any,
    ) -> Any:

        if hasattr(
            value,
            "__await__",
        ):
            return await value

        return value

    # =========================================================
    # COMPACT CONTEXT API
    # =========================================================

    async def retrieve_for_context(
        self,
        query: str,
        user_id: str = "",
        session_id: str = "",
        context: Optional[Dict[str, Any]] = None,
        limit: int = 8,
    ) -> List[Dict[str, Any]]:
        """
        Return only the highest-value evidence records.

        This API is intended for reasoning/context assembly.
        """

        result = await self.retrieve(
            query=query,
            user_id=user_id,
            session_id=session_id,
            context=context,
            limit=limit,
        )

        evidence: List[Dict[str, Any]] = []

        groups = (
            "knowledge",
            "document_knowledge",
            "personal_memories",
            "graph_knowledge",
        )

        for group in groups:

            for item in result.get(
                group,
                [],
            ):

                if not isinstance(
                    item,
                    dict,
                ):
                    item = {
                        "content": str(item)
                    }

                enriched = dict(
                    item
                )

                enriched.setdefault(
                    "evidence_type",
                    group,
                )

                evidence.append(
                    enriched
                )

        evidence.sort(
            key=lambda item: self._item_score(
                item
            ),
            reverse=True,
        )

        return evidence[
            : self._safe_limit(limit)
        ]

    @staticmethod
    def _item_score(
        item: Dict[str, Any],
    ) -> float:

        for key in (
            "retrieval_score",
            "score",
            "similarity",
            "relevance",
            "confidence",
        ):

            try:
                return float(
                    item.get(
                        key,
                        0.0,
                    )
                )
            except (
                TypeError,
                ValueError,
            ):
                continue

        return 0.0

    # =========================================================
    # STATUS
    # =========================================================

    def describe(self) -> Dict[str, Any]:
        return {
            "version": self.VERSION,
            "role": "evidence retrieval",
            "answer_generation": False,
            "llm_calls": False,
            "sources": [
                "knowledge_database",
                "personal_memory",
                "document_knowledge",
                "conversation_context",
                "knowledge_graph",
            ],
            "default_limit": self.DEFAULT_LIMIT,
            "max_limit": self.MAX_LIMIT,
        }


__all__ = [
    "KnowledgeRetriever",
]