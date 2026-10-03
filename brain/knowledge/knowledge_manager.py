from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
import logging
import asyncio

logger = logging.getLogger("aria")


class KnowledgeManager:
    """
    ARIA's canonical local-first knowledge orchestration layer.

    Architecture:

        CognitiveCore
              |
              v
        KnowledgeManager
              |
        +-----+------------------+
        |     |      |     |     |
        v     v      v     v     v
       DB   Memory  Graph World Documents
        |
        v
    ChromaDB + local embeddings

    Web search is used only when local knowledge is unavailable or weak.

    External LLM synthesis is intentionally NOT used for ordinary
    knowledge retrieval. A future local Qwen model will become the
    answer-generation layer. External LLM APIs remain a final fallback.
    """

    def __init__(
        self,
        document_ai,
        memory_engine,
        state_manager,
        knowledge_database=None,
        knowledge_graph=None,
        learning_engine=None,
        world_model=None,
        memory_router=None,
        skill_manager=None,
        web_search=None,
        llm_router=None,
        event_bus=None,
    ):
        self.document_ai = document_ai
        self.memory_engine = memory_engine
        self.state_manager = state_manager

        self.knowledge_database = knowledge_database
        self.knowledge_graph = knowledge_graph
        self.learning_engine = learning_engine

        self.world_model = world_model
        self.memory_router = memory_router
        self.skill_manager = skill_manager
        self.web_search = web_search

        # Kept for future last-resort fallback.
        # Normal local knowledge answers must NOT depend on it.
        self.llm_router = llm_router

        self.event_bus = event_bus

        logger.info(
            "[KnowledgeManager] Initialized local-first knowledge manager."
        )

    # ===========================================================
    # Utility Helpers
    # ===========================================================

    @staticmethod
    def _as_list(value: Any) -> List[Any]:
        """
        Normalize arbitrary search output into a list.
        """

        if value is None:
            return []

        if isinstance(value, list):
            return value

        if isinstance(value, tuple):
            return list(value)

        if isinstance(value, set):
            return list(value)

        return [value]

    @staticmethod
    def _safe_float(
        value: Any,
        default: float,
    ) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _clamp(
        value: float,
        minimum: float = 0.0,
        maximum: float = 1.0,
    ) -> float:
        return max(
            minimum,
            min(float(value), maximum),
        )

    @staticmethod
    def _content_from_item(item: Any) -> str:
        """
        Extract textual content from a knowledge result.
        """

        if isinstance(item, dict):
            value = (
                item.get("content")
                or item.get("text")
                or item.get("answer")
                or item.get("description")
                or item.get("value")
                or ""
            )
        else:
            value = item

        return str(value or "").strip()

    # ===========================================================
    # Evidence Normalization
    # ===========================================================

    def _normalize_evidence(
        self,
        item: Dict[str, Any],
        default_source: str = "unknown",
    ) -> Dict[str, Any]:
        """
        Normalize every knowledge result into a common evidence format.
        """

        if not isinstance(item, dict):
            item = {
                "content": str(item),
            }

        content = self._content_from_item(item)

        source = item.get(
            "source",
            default_source,
        )

        try:
            confidence = float(
                item.get(
                    "confidence",
                    0.5,
                )
            )
        except (TypeError, ValueError):
            confidence = 0.5

        try:
            importance = float(
                item.get(
                    "importance",
                    50,
                )
            )
        except (TypeError, ValueError):
            importance = 50.0

        try:
            freshness = float(
                item.get(
                    "freshness",
                    0.5,
                )
            )
        except (TypeError, ValueError):
            freshness = 0.5

        try:
            relevance = float(
                item.get(
                    "relevance",
                    0.5,
                )
            )
        except (TypeError, ValueError):
            relevance = 0.5

        confidence = self._clamp(
            confidence
        )

        importance = max(
            0.0,
            min(
                importance,
                100.0,
            ),
        )

        freshness = self._clamp(
            freshness
        )

        relevance = self._clamp(
            relevance
        )

        return {
            **item,

            "content": content,

            "source": source,

            "confidence": confidence,

            "importance": importance,

            "evidence_type": item.get(
                "evidence_type",
                "retrieved",
            ),

            "provenance": item.get(
                "provenance",
                source,
            ),

            "freshness": freshness,

            "relevance": relevance,

            "verified": bool(
                item.get(
                    "verified",
                    False,
                )
            ),
        }

    # ===========================================================
    # Unified Search Entrypoint
    # ===========================================================

    async def search(
        self,
        query: str,
    ):
        """
        Search the local knowledge layer.

        This method intentionally does NOT perform web search and does
        NOT call an external LLM.

        Priority:

            1. Documents
            2. Local KnowledgeDatabase
        """

        results = []

        if self.document_ai:
            try:

                docs = None

                if hasattr(
                    self.document_ai,
                    "search",
                ):
                    docs = self.document_ai.search(
                        query
                    )

                elif hasattr(
                    self.document_ai,
                    "retrieve",
                ):
                    docs = self.document_ai.retrieve(
                        query
                    )

                elif hasattr(
                    self.document_ai,
                    "semantic_search",
                ):
                    docs = self.document_ai.semantic_search(
                        query
                    )

                elif hasattr(
                    self.document_ai,
                    "find",
                ):
                    docs = self.document_ai.find(
                        query
                    )

                if asyncio.iscoroutine(docs):
                    docs = await docs

                if docs:
                    results.extend(
                        self._as_list(docs)
                    )

            except Exception:
                logger.exception(
                    "[KnowledgeManager] Document search failed."
                )

        if self.knowledge_database:

            try:

                kb = None

                if hasattr(
                    self.knowledge_database,
                    "search",
                ):
                    kb = self.knowledge_database.search(
                        query
                    )

                elif hasattr(
                    self.knowledge_database,
                    "retrieve",
                ):
                    kb = self.knowledge_database.retrieve(
                        query
                    )

                if asyncio.iscoroutine(kb):
                    kb = await kb

                if kb:
                    results.extend(
                        self._as_list(kb)
                    )

            except Exception:
                logger.exception(
                    "[KnowledgeManager] Knowledge database search failed."
                )

        return results

    # ===========================================================
    # Working Memory
    # ===========================================================

    async def search_working_memory(
        self,
        question: str,
    ) -> List[Dict[str, Any]]:

        if (
            self.memory_router
            and hasattr(
                self.memory_router,
                "snapshot",
            )
        ):

            try:

                snap = self.memory_router.snapshot()

                if asyncio.iscoroutine(snap):
                    snap = await snap

                if snap:
                    return [{
                        "source": "working_memory",
                        "confidence": 0.98,
                        "importance": 90,
                        "relevance": 0.95,
                        "content": str(snap),
                    }]

            except Exception:
                logger.exception(
                    "[KnowledgeManager] Working memory search failed."
                )

        return []

    # ===========================================================
    # Personal Memory
    # ===========================================================

    async def search_memory(
        self,
        question: str,
    ) -> List[Dict[str, Any]]:

        if (
            self.memory_engine
            and hasattr(
                self.memory_engine,
                "get_relevant_memories",
            )
        ):

            try:

                mems = (
                    await self.memory_engine.get_relevant_memories(
                        question
                    )
                )

                if mems:

                    normalized = []

                    for m in self._as_list(mems):

                        content = (
                            self._content_from_item(m)
                        )

                        if not content:
                            continue

                        confidence = (
                            m.get(
                                "confidence",
                                0.94,
                            )
                            if isinstance(
                                m,
                                dict,
                            )
                            else 0.94
                        )

                        importance = (
                            m.get(
                                "importance",
                                80,
                            )
                            if isinstance(
                                m,
                                dict,
                            )
                            else 80
                        )

                        normalized.append({
                            "source": "memory",
                            "confidence": self._safe_float(
                                confidence,
                                0.94,
                            ),
                            "importance": self._safe_float(
                                importance,
                                80,
                            ),
                            "relevance": 0.90,
                            "content": content,
                        })

                    return normalized

            except Exception:
                logger.exception(
                    "[KnowledgeManager] Personal memory search failed."
                )

        return []

    # ===========================================================
    # LOCAL KNOWLEDGE DATABASE
    # ===========================================================

    async def search_database(
        self,
        question: str,
    ) -> List[Dict[str, Any]]:
        """
        Search ARIA's local knowledge database.

        This is the PRIMARY general-knowledge source.

        KnowledgeDatabase is expected to use:

            local embedding
                +
            ChromaDB
                +
            MongoDB metadata
        """

        if not self.knowledge_database:
            logger.warning(
                "[KnowledgeManager] Knowledge database unavailable."
            )
            return []

        try:

            kb_res = None

            if hasattr(
                self.knowledge_database,
                "retrieve",
            ):
                kb_res = (
                    await self.knowledge_database.retrieve(
                        question
                    )
                )

            elif hasattr(
                self.knowledge_database,
                "search",
            ):
                kb_res = (
                    self.knowledge_database.search(
                        question
                    )
                )

                if asyncio.iscoroutine(
                    kb_res
                ):
                    kb_res = await kb_res

            elif hasattr(
                self.knowledge_database,
                "semantic_search",
            ):
                kb_res = (
                    self.knowledge_database.semantic_search(
                        question
                    )
                )

                if asyncio.iscoroutine(
                    kb_res
                ):
                    kb_res = await kb_res

            if not kb_res:
                logger.info(
                    "[KnowledgeManager] No local knowledge found for: %s",
                    question,
                )
                return []

            normalized = []

            for item in self._as_list(
                kb_res
            ):

                content = (
                    self._content_from_item(
                        item
                    )
                )

                if not content:
                    continue

                if isinstance(
                    item,
                    dict,
                ):
                    confidence = item.get(
                        "confidence",
                        item.get(
                            "score",
                            0.85,
                        ),
                    )

                    importance = item.get(
                        "importance",
                        50,
                    )

                    relevance = item.get(
                        "relevance",
                        item.get(
                            "similarity",
                            0.85,
                        ),
                    )

                    freshness = item.get(
                        "freshness",
                        0.8,
                    )

                    verified = item.get(
                        "verified",
                        False,
                    )

                else:
                    confidence = 0.85
                    importance = 50
                    relevance = 0.85
                    freshness = 0.8
                    verified = False

                normalized.append({
                    "source": "knowledge_database",
                    "confidence": self._safe_float(
                        confidence,
                        0.85,
                    ),
                    "importance": self._safe_float(
                        importance,
                        50,
                    ),
                    "relevance": self._safe_float(
                        relevance,
                        0.85,
                    ),
                    "freshness": self._safe_float(
                        freshness,
                        0.8,
                    ),
                    "verified": bool(
                        verified
                    ),
                    "content": content,
                })

            logger.info(
                "[KnowledgeManager] Local knowledge retrieved: %d result(s)",
                len(normalized),
            )

            return normalized

        except Exception:
            logger.exception(
                "[KnowledgeManager] Local knowledge database retrieval failed."
            )
            return []

    # ===========================================================
    # Knowledge Graph
    # ===========================================================

    async def search_graph(
        self,
        question: str,
    ) -> List[Dict[str, Any]]:

        if (
            not self.knowledge_graph
            or not hasattr(
                self.knowledge_graph,
                "search",
            )
        ):
            return []

        try:

            g_res = (
                await self.knowledge_graph.search(
                    question
                )
            )

            if not g_res:
                return []

            normalized = []

            for item in self._as_list(
                g_res
            ):

                content = (
                    self._content_from_item(
                        item
                    )
                )

                if not content:
                    continue

                if isinstance(
                    item,
                    dict,
                ):
                    confidence = item.get(
                        "confidence",
                        0.81,
                    )

                    importance = item.get(
                        "importance",
                        60,
                    )

                    relevance = item.get(
                        "relevance",
                        0.80,
                    )

                else:
                    confidence = 0.81
                    importance = 60
                    relevance = 0.80

                normalized.append({
                    "source": "knowledge_graph",
                    "confidence": self._safe_float(
                        confidence,
                        0.81,
                    ),
                    "importance": self._safe_float(
                        importance,
                        60,
                    ),
                    "relevance": self._safe_float(
                        relevance,
                        0.80,
                    ),
                    "content": content,
                })

            return normalized

        except Exception:
            logger.exception(
                "[KnowledgeManager] Knowledge graph search failed."
            )
            return []

    # ===========================================================
    # World Model
    # ===========================================================

    async def search_world(
        self,
        question: str,
    ) -> List[Dict[str, Any]]:

        if (
            not self.world_model
            or not hasattr(
                self.world_model,
                "search",
            )
        ):
            return []

        try:

            w_res = (
                self.world_model.search(
                    question
                )
            )

            if asyncio.iscoroutine(
                w_res
            ):
                w_res = await w_res

            if not w_res:
                return []

            normalized = []

            if isinstance(
                w_res,
                dict,
            ):

                for k, v in w_res.items():

                    if not v:
                        continue

                    normalized.append({
                        "source": "world_model",
                        "confidence": 0.91,
                        "importance": 70,
                        "relevance": 0.80,
                        "content": f"{k}: {v}",
                    })

            else:

                for item in self._as_list(
                    w_res
                ):

                    content = (
                        self._content_from_item(
                            item
                        )
                    )

                    if content:
                        normalized.append({
                            "source": "world_model",
                            "confidence": 0.91,
                            "importance": 70,
                            "relevance": 0.80,
                            "content": content,
                        })

            return normalized

        except Exception:
            logger.exception(
                "[KnowledgeManager] World model search failed."
            )
            return []

    # ===========================================================
    # Documents
    # ===========================================================

    async def search_documents(
        self,
        session_id: str,
        question: str,
    ) -> List[Dict[str, Any]]:

        if (
            not self.state_manager
            or not self.document_ai
        ):
            return []

        try:

            state = (
                self.state_manager.get_state(
                    session_id
                )
            )

            if asyncio.iscoroutine(
                state
            ):
                state = await state

            if not isinstance(
                state,
                dict,
            ):
                state = {}

            active_document = state.get(
                "active_document"
            )

            if not active_document:
                return []

            if not hasattr(
                self.document_ai,
                "answer_question",
            ):
                return []

            doc_ans = (
                await self.document_ai.answer_question(
                    session_id=session_id,
                    question=question,
                    state=state,
                )
            )

            if doc_ans:

                return [{
                    "source": "document",
                    "confidence": 0.95,
                    "importance": 85,
                    "relevance": 0.98,
                    "verified": True,
                    "content": str(
                        doc_ans
                    ),
                }]

        except Exception:
            logger.exception(
                "[KnowledgeManager] Document question failed."
            )

        return []

    # ===========================================================
    # Skills
    # ===========================================================

    async def search_skills(
        self,
        question: str,
    ) -> List[Dict[str, Any]]:

        if (
            not self.skill_manager
            or not hasattr(
                self.skill_manager,
                "route_and_execute",
            )
        ):
            return []

        try:

            skill_res = (
                await self.skill_manager.route_and_execute(
                    question,
                    {},
                )
            )

            if (
                skill_res
                and getattr(
                    skill_res,
                    "success",
                    False,
                )
            ):

                data = getattr(
                    skill_res,
                    "data",
                    {},
                ) or {}

                msg = (
                    data.get(
                        "response"
                    )
                    or data.get(
                        "message"
                    )
                    or str(data)
                )

                if msg:

                    return [{
                        "source": "skill",
                        "confidence": 0.80,
                        "importance": 50,
                        "relevance": 0.75,
                        "content": str(
                            msg
                        ),
                    }]

        except Exception:
            logger.exception(
                "[KnowledgeManager] Skill search failed."
            )

        return []

    # ===========================================================
    # Merge Results
    # ===========================================================

    async def merge_results(
        self,
        *sources,
    ) -> List[Dict[str, Any]]:
        """
        Merge all local evidence.

        Exact duplicate text is merged while preserving supporting
        source information.
        """

        flattened = []
        seen = {}

        for source_list in sources:

            if not source_list:
                continue

            if not isinstance(
                source_list,
                list,
            ):
                source_list = [
                    source_list
                ]

            for raw_item in source_list:

                item = self._normalize_evidence(
                    raw_item
                    if isinstance(
                        raw_item,
                        dict,
                    )
                    else {
                        "content": str(
                            raw_item
                        )
                    }
                )

                content = item.get(
                    "content",
                    "",
                ).strip()

                if not content:
                    continue

                key = content.lower()

                if key in seen:

                    existing = seen[
                        key
                    ]

                    existing_sources = (
                        existing.setdefault(
                            "supporting_sources",
                            [],
                        )
                    )

                    source = item.get(
                        "source",
                        "unknown",
                    )

                    if source not in (
                        existing_sources
                    ):
                        existing_sources.append(
                            source
                        )

                    existing[
                        "evidence_count"
                    ] = (
                        existing.get(
                            "evidence_count",
                            1,
                        )
                        + 1
                    )

                    continue

                item[
                    "supporting_sources"
                ] = [
                    item.get(
                        "source",
                        "unknown",
                    )
                ]

                item[
                    "evidence_count"
                ] = 1

                seen[
                    key
                ] = item

                flattened.append(
                    item
                )

        return flattened

    # ===========================================================
    # Ranking
    # ===========================================================

    async def rank_results(
        self,
        results: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Rank evidence using confidence, relevance, freshness,
        importance, verification and independent support.
        """

        def sort_key(item):

            confidence = self._clamp(
                item.get(
                    "confidence",
                    0.5,
                )
            )

            relevance = self._clamp(
                item.get(
                    "relevance",
                    0.5,
                )
            )

            freshness = self._clamp(
                item.get(
                    "freshness",
                    0.5,
                )
            )

            importance = self._clamp(
                self._safe_float(
                    item.get(
                        "importance",
                        50,
                    ),
                    50,
                ) / 100.0
            )

            evidence_count = min(
                int(
                    item.get(
                        "evidence_count",
                        1,
                    )
                ),
                5,
            ) / 5.0

            verified = (
                1.0
                if item.get(
                    "verified",
                    False,
                )
                else 0.0
            )

            # Local knowledge gets a modest source-quality
            # preference without making source alone determine
            # the result.
            source = item.get(
                "source",
                "unknown",
            )

            local_bonus = (
                0.05
                if source
                in {
                    "knowledge_database",
                    "document",
                    "knowledge_graph",
                    "memory",
                    "working_memory",
                }
                else 0.0
            )

            score = (
                confidence * 0.30
                + relevance * 0.30
                + freshness * 0.10
                + importance * 0.10
                + evidence_count * 0.10
                + verified * 0.10
                + local_bonus
            )

            return score

        for item in results:

            item[
                "evidence_score"
            ] = round(
                sort_key(item),
                4,
            )

        return sorted(
            results,
            key=lambda item: item.get(
                "evidence_score",
                0.0,
            ),
            reverse=True,
        )

    # ===========================================================
    # Main Local Retrieval Pipeline
    # ===========================================================

    async def retrieve(
        self,
        session_id: str,
        question: str,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve local knowledge.

        The knowledge database is the primary general-knowledge source.

        Other local systems provide supporting context.

        Web search is intentionally NOT performed here.
        """

        logger.info(
            "[KnowledgeManager] Local retrieval started: %s",
            question,
        )

        # -------------------------------------------------------
        # Run independent local sources concurrently.
        # -------------------------------------------------------

        tasks = [
            self.search_working_memory(
                question
            ),
            self.search_memory(
                question
            ),
            self.search_database(
                question
            ),
            self.search_graph(
                question
            ),
            self.search_world(
                question
            ),
            self.search_documents(
                session_id,
                question,
            ),
            self.search_skills(
                question
            ),
        ]

        (
            working,
            memory,
            knowledge,
            graph,
            world,
            documents,
            skills,
        ) = await asyncio.gather(
            *tasks,
            return_exceptions=True,
        )

        # -------------------------------------------------------
        # Convert failed tasks to empty lists.
        # -------------------------------------------------------

        source_names = [
            "working_memory",
            "memory",
            "knowledge_database",
            "knowledge_graph",
            "world_model",
            "documents",
            "skills",
        ]

        raw_sources = [
            working,
            memory,
            knowledge,
            graph,
            world,
            documents,
            skills,
        ]

        cleaned_sources = []

        for name, result in zip(
            source_names,
            raw_sources,
        ):

            if isinstance(
                result,
                Exception,
            ):
                logger.exception(
                    "[KnowledgeManager] %s retrieval failed.",
                    name,
                    exc_info=result,
                )
                cleaned_sources.append([])
            else:
                cleaned_sources.append(
                    result
                )

        merged = await self.merge_results(
            *cleaned_sources
        )

        ranked = await self.rank_results(
            merged
        )

        logger.info(
            "[KnowledgeManager] Local retrieval complete: %d result(s).",
            len(ranked),
        )

        if ranked:

            top = ranked[0]

            logger.info(
                "[KnowledgeManager] Top local source=%s confidence=%.3f relevance=%.3f score=%.3f",
                top.get(
                    "source",
                    "unknown",
                ),
                top.get(
                    "confidence",
                    0.0,
                ),
                top.get(
                    "relevance",
                    0.0,
                ),
                top.get(
                    "evidence_score",
                    0.0,
                ),
            )

        return ranked

    # ===========================================================
    # Web Decision
    # ===========================================================

    async def needs_web(
        self,
        results: List[Dict[str, Any]],
    ) -> bool:
        """
        Decide whether current local knowledge is insufficient.

        Web is a fallback, not the primary knowledge source.
        """

        if not results:
            logger.info(
                "[KnowledgeManager] No local evidence -> web fallback allowed."
            )
            return True

        top = results[0]

        confidence = self._safe_float(
            top.get(
                "confidence",
                0.0,
            ),
            0.0,
        )

        relevance = self._safe_float(
            top.get(
                "relevance",
                0.0,
            ),
            0.0,
        )

        evidence_score = self._safe_float(
            top.get(
                "evidence_score",
                0.0,
            ),
            0.0,
        )

        # Strong local evidence means no web call.
        if (
            confidence >= 0.60
            and relevance >= 0.55
            and evidence_score >= 0.55
        ):
            logger.info(
                "[KnowledgeManager] Local evidence sufficient -> no web search."
            )
            return False

        logger.info(
            "[KnowledgeManager] Local evidence weak -> web fallback allowed."
        )

        return True

    # ===========================================================
    # Web Search
    # ===========================================================

    async def search_web(
        self,
        question: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Web is a fallback for missing/weak local knowledge.

        Successful web knowledge can be learned into the local
        knowledge system for future use.
        """

        if (
            not self.web_search
            or not hasattr(
                self.web_search,
                "execute",
            )
        ):
            logger.info(
                "[KnowledgeManager] Web search unavailable."
            )
            return None

        try:

            logger.info(
                "[KnowledgeManager] Executing web fallback: %s",
                question,
            )

            res = await self.web_search.execute({
                "query": question
            })

            if not res:
                return None

            if not getattr(
                res,
                "success",
                False,
            ):
                return None

            data = getattr(
                res,
                "data",
                {},
            ) or {}

            answer = (
                data.get(
                    "result"
                )
                or data.get(
                    "content"
                )
                or data.get(
                    "answer"
                )
                or str(data)
            )

            answer = str(
                answer or ""
            ).strip()

            if not answer:
                return None

            web_result = {
                "source": "web_search",
                "confidence": 0.75,
                "importance": 70,
                "relevance": 0.90,
                "freshness": 1.0,
                "verified": False,
                "content": answer,
            }

            # ---------------------------------------------------
            # Learn successful web information into local memory.
            # ---------------------------------------------------

            if self.learning_engine:

                try:

                    await self.learning_engine.learn(
                        text=answer,
                        source="web",
                    )

                except Exception:
                    logger.exception(
                        "[KnowledgeManager] Failed to learn web result."
                    )

            return web_result

        except Exception:
            logger.exception(
                "[KnowledgeManager] Web fallback failed."
            )
            return None

    # ===========================================================
    # Source Explanation
    # ===========================================================

    async def explain_sources(
        self,
        results: List[Dict[str, Any]],
    ) -> List[str]:

        return list(
            dict.fromkeys(
                item.get(
                    "source",
                    "unknown",
                )
                for item in results
            )
        )

    # ===========================================================
    # Local Answer Selection
    # ===========================================================

    async def best_answer(
        self,
        question: str,
        results: List[Dict[str, Any]],
    ) -> str:
        """
        Select the strongest locally retrieved answer.

        IMPORTANT:
        This method intentionally does NOT call LLMRouter.

        If multiple results exist, the highest-ranked evidence is returned.
        Later, a local Qwen model will synthesize multiple pieces of evidence.

        External APIs therefore remain outside the normal knowledge path.
        """

        if not results:
            return ""

        top = results[0]

        answer = str(
            top.get(
                "content",
                "",
            )
            or ""
        ).strip()

        if not answer:
            return ""

        logger.info(
            "[KnowledgeManager] Answer selected locally from source=%s",
            top.get(
                "source",
                "unknown",
            ),
        )

        return answer

    # ===========================================================
    # Last-Resort External LLM
    # ===========================================================

    async def external_llm_fallback(
        self,
        question: str,
        results: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[str]:
        """
        LAST-RESORT external LLM fallback.

        This method is deliberately separate from best_answer().

        It should only be called when:
            - local knowledge failed,
            - web fallback failed,
            - and a final external answer is genuinely required.

        Normal knowledge questions must NOT call this method.
        """

        if (
            not self.llm_router
            or not hasattr(
                self.llm_router,
                "chat",
            )
        ):
            return None

        evidence = results or []

        evidence_text = "\n\n".join(
            (
                f"Source: {item.get('source', 'unknown')}\n"
                f"{item.get('content', '')}"
            )
            for item in evidence[:5]
            if item.get("content")
        )

        messages = [
            {
                "role": "system",
                "content": (
                    "You are ARIA. Answer accurately and concisely. "
                    "Use supplied evidence when available. "
                    "Do not invent facts."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Question: {question}\n\n"
                    f"Available evidence:\n{evidence_text}"
                ),
            },
        ]

        try:

            logger.warning(
                "[KnowledgeManager] Using external LLM as LAST-RESORT fallback."
            )

            response = await self.llm_router.chat(
                messages
            )

            if (
                isinstance(
                    response,
                    str,
                )
                and response.strip()
            ):
                return response.strip()

        except Exception:
            logger.exception(
                "[KnowledgeManager] External LLM fallback failed."
            )

        return None

    # ===========================================================
    # Main Answer Pipeline
    # ===========================================================

    async def answer(
        self,
        session_id,
        question,
    ):
        """
        Main local-first answer pipeline.

        Flow:

            Local knowledge
                  |
                  | sufficient?
                  v
                answer

            otherwise
                  |
                  v
              Web search
                  |
                  v
                answer

            otherwise
                  |
                  v
          return None

        The external LLM is intentionally NOT called here.

        CognitiveCore can decide later whether an external fallback
        is appropriate.
        """

        question = str(
            question or ""
        ).strip()

        if not question:
            return None

        logger.info(
            "[KnowledgeManager] Answer pipeline started."
        )

        # -------------------------------------------------------
        # 1. LOCAL KNOWLEDGE
        # -------------------------------------------------------

        results = await self.retrieve(
            session_id,
            question,
        )

        # -------------------------------------------------------
        # 2. LOCAL ANSWER
        # -------------------------------------------------------

        if results:

            if not await self.needs_web(
                results
            ):

                final_answer = (
                    await self.best_answer(
                        question,
                        results,
                    )
                )

                if final_answer:
                    return final_answer

        # -------------------------------------------------------
        # 3. WEB FALLBACK
        # -------------------------------------------------------

        if await self.needs_web(
            results
        ):

            web_res = await self.search_web(
                question
            )

            if web_res:

                results.insert(
                    0,
                    web_res,
                )

                final_answer = (
                    await self.best_answer(
                        question,
                        results,
                    )
                )

                if final_answer:
                    return final_answer

        # -------------------------------------------------------
        # 4. NO ANSWER
        # -------------------------------------------------------

        logger.info(
            "[KnowledgeManager] No local/web knowledge answer available."
        )

        return None

    # ===========================================================
    # Learn New Knowledge
    # ===========================================================

    async def learn(
        self,
        text,
        source="conversation",
    ):
        """
        Pass newly learned information into the learning engine.

        This is intentionally separate from personal memory.
        """

        text = str(
            text or ""
        ).strip()

        if not text:
            return False

        if self.learning_engine:

            try:

                await self.learning_engine.learn(
                    text=text,
                    source=source,
                )

                logger.info(
                    "[KnowledgeManager] Learned knowledge from source=%s",
                    source,
                )

                return True

            except Exception:
                logger.exception(
                    "[KnowledgeManager] Knowledge learning failed."
                )

        return False

    # ===========================================================
    # Store Structured Fact
    # ===========================================================

    async def remember_fact(
        self,
        subject,
        relation,
        value,
    ):
        """
        Store a structured fact in the knowledge graph.
        """

        if not self.knowledge_graph:
            return False

        if not hasattr(
            self.knowledge_graph,
            "add_fact",
        ):
            return False

        try:

            result = await self.knowledge_graph.add_fact(
                subject,
                relation,
                value,
            )

            logger.info(
                "[KnowledgeManager] Stored structured fact: %s %s %s",
                subject,
                relation,
                value,
            )

            return result if result is not None else True

        except Exception:
            logger.exception(
                "[KnowledgeManager] Failed to store structured fact."
            )

        return False

    # ===========================================================
    # Save Knowledge
    # ===========================================================

    async def save_knowledge(
        self,
        title,
        content,
        source="conversation",
    ):
        """
        Store general knowledge in the local KnowledgeDatabase.

        KnowledgeDatabase is responsible for creating the local
        embedding and storing it in the dedicated Chroma collection.
        """

        title = str(
            title or ""
        ).strip()

        content = str(
            content or ""
        ).strip()

        if not content:
            return False

        if not self.knowledge_database:
            logger.warning(
                "[KnowledgeManager] Cannot save knowledge: database unavailable."
            )
            return False

        if not hasattr(
            self.knowledge_database,
            "store",
        ):
            logger.warning(
                "[KnowledgeManager] KnowledgeDatabase has no store() method."
            )
            return False

        try:

            result = await self.knowledge_database.store(
                title=title or content[:50],
                content=content,
                source=source,
            )

            logger.info(
                "[KnowledgeManager] Saved knowledge locally: %s",
                title or content[:50],
            )

            return result if result is not None else True

        except Exception:
            logger.exception(
                "[KnowledgeManager] Failed to save knowledge locally."
            )

        return False

    # ===========================================================
    # Remember Answer
    # ===========================================================

    async def remember_answer(
        self,
        question: str,
        answer: str,
        source: str,
    ):
        """
        Store a generated/retrieved answer in the local knowledge database.

        The local KnowledgeDatabase handles embeddings.
        """

        question = str(
            question or ""
        ).strip()

        answer = str(
            answer or ""
        ).strip()

        if not answer:
            return False

        stored = False

        if (
            self.knowledge_database
            and hasattr(
                self.knowledge_database,
                "store",
            )
        ):

            try:

                result = (
                    await self.knowledge_database.store(
                        title=question[:50]
                        if question
                        else "Knowledge",
                        content=answer,
                        source=source,
                    )
                )

                stored = (
                    result
                    if isinstance(
                        result,
                        bool,
                    )
                    else True
                )

            except Exception:
                logger.exception(
                    "[KnowledgeManager] Failed to store answer in knowledge database."
                )

        if self.learning_engine:

            try:

                await self.learning_engine.learn(
                    text=answer,
                    source=source,
                )

            except Exception:
                logger.exception(
                    "[KnowledgeManager] Failed to send answer to learning engine."
                )

        return stored

    # ===========================================================
    # Explicit Knowledge Ingestion
    # ===========================================================

    async def ingest(
        self,
        title: str,
        content: str,
        source: str = "conversation",
        subject: Optional[str] = None,
        relation: Optional[str] = None,
        value: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Explicitly ingest knowledge into ARIA.

        General knowledge:
            -> KnowledgeDatabase

        Structured fact:
            -> KnowledgeGraph

        LearningEngine is updated as well.

        This method will become the main entrypoint for future
        Wikipedia, Wikidata, dataset and document ingestion.
        """

        title = str(
            title or ""
        ).strip()

        content = str(
            content or ""
        ).strip()

        source = str(
            source or "conversation"
        ).strip()

        result = {
            "success": False,
            "knowledge_database": False,
            "knowledge_graph": False,
            "learning_engine": False,
            "source": source,
            "timestamp": datetime.now(
                timezone.utc
            ).isoformat(),
        }

        if not content:
            result[
                "error"
            ] = "Empty knowledge content."

            return result

        # -------------------------------------------------------
        # General knowledge
        # -------------------------------------------------------

        saved = await self.save_knowledge(
            title=title or content[:50],
            content=content,
            source=source,
        )

        result[
            "knowledge_database"
        ] = bool(saved)

        # -------------------------------------------------------
        # Structured fact
        # -------------------------------------------------------

        if (
            subject
            and relation
            and value
        ):

            graph_saved = (
                await self.remember_fact(
                    subject,
                    relation,
                    value,
                )
            )

            result[
                "knowledge_graph"
            ] = bool(graph_saved)

        # -------------------------------------------------------
        # Learning engine
        # -------------------------------------------------------

        learned = await self.learn(
            text=content,
            source=source,
        )

        result[
            "learning_engine"
        ] = bool(learned)

        result[
            "success"
        ] = bool(
            result["knowledge_database"]
            or result["knowledge_graph"]
            or result["learning_engine"]
        )

        logger.info(
            "[KnowledgeManager] Knowledge ingestion complete: success=%s source=%s",
            result["success"],
            source,
        )

        return result