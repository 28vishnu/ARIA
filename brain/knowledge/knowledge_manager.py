from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
import logging
import asyncio

logger = logging.getLogger("aria")


class KnowledgeManager:

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

        # Kept for non-ordinary/current workflows.
        # Ordinary local knowledge queries NEVER use this.
        self.llm_router = llm_router

        self.event_bus = event_bus

    # =========================================================
    # Local Knowledge Safety
    # =========================================================

    @staticmethod
    def _is_ordinary_knowledge_query(question: str) -> bool:
        """
        Detect normal factual / educational questions.

        These queries are owned by the local knowledge system.
        They must not invoke:
            - personal-memory relevance LLMs
            - external answer-generation LLMs
            - personality LLM synthesis

        Current/live requests are intentionally excluded.
        """
        q = str(question or "").strip().lower()

        if not q:
            return False

        current_markers = (
            "latest",
            "current",
            "today",
            "now",
            "recent",
            "this week",
            "this month",
            "this year",
            "breaking",
            "online",
            "search the web",
            "look up",
            "on the internet",
        )

        if any(marker in q for marker in current_markers):
            return False

        prefixes = (
            "what is ",
            "what are ",
            "what does ",
            "what do ",
            "what was ",
            "what were ",
            "why is ",
            "why are ",
            "why does ",
            "why do ",
            "how does ",
            "how do ",
            "how is ",
            "how are ",
            "explain ",
            "define ",
            "describe ",
            "tell me about ",
            "difference between ",
        )

        return q.startswith(prefixes)

    @staticmethod
    def _is_bad_knowledge_content(content: str) -> bool:
        """
        Reject responses that are clearly system/provider failures.

        This is critical because previously ARIA learned and stored
        messages such as:

            "I'm temporarily unable to reach my language models."

        Those messages are NOT knowledge and must never become future
        knowledge retrieval results.
        """
        text = str(content or "").strip().lower()

        if not text:
            return True

        failure_markers = (
            "temporarily unable to reach my language models",
            "unable to reach my language models",
            "unable to reach the language models",
            "all available llm providers failed",
            "all available llm provider failed",
            "llm providers failed",
            "llm provider failed",
            "language models are unavailable",
            "language model is unavailable",
            "no available llm",
            "no available language model",
            "model providers failed",
            "provider failed",
            "temporarily unavailable",
            "please try again in a few seconds",
            "please try again later",
            "rate limited",
            "rate-limit",
            "service unavailable",
            "internal server error",
        )

        return any(
            marker in text
            for marker in failure_markers
        )

    # =========================================================
    # Built-in Foundational Knowledge
    # =========================================================

    @staticmethod
    def _local_foundational_knowledge(
        question: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Small deterministic knowledge layer for foundational facts.

        This is NOT intended to replace the future large knowledge
        corpus. It guarantees that ARIA has a useful local answer for
        foundational concepts while the larger knowledge ingestion
        system is being built.

        No LLM/API is involved.
        """
        q = str(question or "").strip().lower()

        if not q:
            return None

        # -----------------------------------------------------
        # TCP
        # -----------------------------------------------------

        tcp_patterns = (
            "what does tcp provide",
            "what does tcp provide?",
            "what is tcp",
            "what is tcp?",
            "what does tcp do",
            "what does tcp do?",
            "explain tcp",
            "define tcp",
        )

        if any(
            pattern == q
            for pattern in tcp_patterns
        ):
            return {
                "source": "local_foundational_knowledge",
                "confidence": 0.99,
                "importance": 95,
                "relevance": 1.0,
                "freshness": 1.0,
                "verified": True,
                "evidence_type": "built_in_fact",
                "provenance": "ARIA foundational knowledge",
                "content": (
                    "TCP (Transmission Control Protocol) provides "
                    "reliable, connection-oriented, ordered delivery "
                    "of data between applications over an IP network. "
                    "It provides mechanisms such as sequence numbers, "
                    "acknowledgements, retransmission of lost data, "
                    "flow control, and congestion control. TCP ensures "
                    "that data arrives reliably and in the correct "
                    "order, but it does not itself provide encryption."
                ),
                "local_knowledge": True,
                "external_llm_synthesis": False,
            }

        # -----------------------------------------------------
        # UDP
        # -----------------------------------------------------

        udp_patterns = (
            "what is udp",
            "what is udp?",
            "what does udp provide",
            "what does udp provide?",
            "what does udp do",
            "what does udp do?",
            "explain udp",
            "define udp",
        )

        if any(
            pattern == q
            for pattern in udp_patterns
        ):
            return {
                "source": "local_foundational_knowledge",
                "confidence": 0.99,
                "importance": 95,
                "relevance": 1.0,
                "freshness": 1.0,
                "verified": True,
                "evidence_type": "built_in_fact",
                "provenance": "ARIA foundational knowledge",
                "content": (
                    "UDP (User Datagram Protocol) is a connectionless "
                    "transport-layer protocol that provides a simple, "
                    "low-overhead way to send datagrams. UDP does not "
                    "guarantee delivery, ordering, retransmission, or "
                    "duplicate protection. It is commonly used where "
                    "low latency and application-level control are "
                    "more important than reliable delivery."
                ),
                "local_knowledge": True,
                "external_llm_synthesis": False,
            }

        # -----------------------------------------------------
        # HTTP
        # -----------------------------------------------------

        http_patterns = (
            "what is http",
            "what is http?",
            "what does http provide",
            "what does http do",
            "explain http",
            "define http",
        )

        if any(
            pattern == q
            for pattern in http_patterns
        ):
            return {
                "source": "local_foundational_knowledge",
                "confidence": 0.99,
                "importance": 90,
                "relevance": 1.0,
                "freshness": 1.0,
                "verified": True,
                "evidence_type": "built_in_fact",
                "provenance": "ARIA foundational knowledge",
                "content": (
                    "HTTP (Hypertext Transfer Protocol) is an "
                    "application-layer protocol used for communication "
                    "between clients and servers. It defines how "
                    "requests and responses are exchanged, including "
                    "methods such as GET, POST, PUT, and DELETE and "
                    "status codes such as 200, 404, and 500."
                ),
                "local_knowledge": True,
                "external_llm_synthesis": False,
            }

        # -----------------------------------------------------
        # IP
        # -----------------------------------------------------

        ip_patterns = (
            "what is ip",
            "what is ip?",
            "what is an ip address",
            "what is an ip address?",
            "explain ip",
            "define ip",
        )

        if any(
            pattern == q
            for pattern in ip_patterns
        ):
            return {
                "source": "local_foundational_knowledge",
                "confidence": 0.99,
                "importance": 90,
                "relevance": 1.0,
                "freshness": 1.0,
                "verified": True,
                "evidence_type": "built_in_fact",
                "provenance": "ARIA foundational knowledge",
                "content": (
                    "An IP address is a numerical network-layer "
                    "identifier used to identify a network interface "
                    "and help route packets across an IP network. "
                    "IPv4 uses 32-bit addresses, while IPv6 uses "
                    "128-bit addresses."
                ),
                "local_knowledge": True,
                "external_llm_synthesis": False,
            }

        # -----------------------------------------------------
        # OS
        # -----------------------------------------------------

        os_patterns = (
            "what is an operating system",
            "what is an operating system?",
            "what is os",
            "what is os?",
            "explain operating system",
            "define operating system",
        )

        if any(
            pattern == q
            for pattern in os_patterns
        ):
            return {
                "source": "local_foundational_knowledge",
                "confidence": 0.99,
                "importance": 90,
                "relevance": 1.0,
                "freshness": 1.0,
                "verified": True,
                "evidence_type": "built_in_fact",
                "provenance": "ARIA foundational knowledge",
                "content": (
                    "An operating system (OS) is system software that "
                    "manages computer hardware and provides services "
                    "for application programs. Major responsibilities "
                    "include process management, memory management, "
                    "file management, device management, security, "
                    "and providing interfaces through which programs "
                    "interact with the system."
                ),
                "local_knowledge": True,
                "external_llm_synthesis": False,
            }

        return None

    # =========================================================
    # Evidence Normalization
    # =========================================================

    def _normalize_evidence(
        self,
        item: Dict[str, Any],
        default_source: str = "unknown",
    ) -> Dict[str, Any]:

        if not isinstance(item, dict):
            item = {
                "content": str(item),
            }

        content = str(
            item.get("content", "")
        ).strip()

        source = item.get(
            "source",
            default_source,
        )

        try:
            confidence = float(
                item.get("confidence", 0.5)
            )
        except (TypeError, ValueError):
            confidence = 0.5

        try:
            importance = float(
                item.get("importance", 50)
            )
        except (TypeError, ValueError):
            importance = 50.0

        try:
            freshness = float(
                item.get("freshness", 0.5)
            )
        except (TypeError, ValueError):
            freshness = 0.5

        try:
            relevance = float(
                item.get("relevance", 0.5)
            )
        except (TypeError, ValueError):
            relevance = 0.5

        confidence = max(
            0.0,
            min(confidence, 1.0),
        )

        importance = max(
            0.0,
            min(importance, 100.0),
        )

        freshness = max(
            0.0,
            min(freshness, 1.0),
        )

        relevance = max(
            0.0,
            min(relevance, 1.0),
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
                item.get("verified", False)
            ),
        }

    # =========================================================
    # Unified Search
    # =========================================================

    async def search(
        self,
        query: str,
    ):
        results = []

        if self.document_ai:
            try:
                docs = None

                if hasattr(
                    self.document_ai,
                    "search",
                ):
                    docs = await self.document_ai.search(
                        query
                    )

                elif hasattr(
                    self.document_ai,
                    "retrieve",
                ):
                    docs = await self.document_ai.retrieve(
                        query
                    )

                elif hasattr(
                    self.document_ai,
                    "semantic_search",
                ):
                    docs = await self.document_ai.semantic_search(
                        query
                    )

                elif hasattr(
                    self.document_ai,
                    "find",
                ):
                    docs = await self.document_ai.find(
                        query
                    )

                if docs:
                    results.extend(docs)

            except Exception:
                logger.exception(
                    "[KnowledgeManager] Document search failed"
                )

        if self.knowledge_database:
            try:
                kb = None

                if hasattr(
                    self.knowledge_database,
                    "search",
                ):
                    kb = await self.knowledge_database.search(
                        query
                    )

                elif hasattr(
                    self.knowledge_database,
                    "retrieve",
                ):
                    kb = await self.knowledge_database.retrieve(
                        query
                    )

                if kb:
                    results.extend(kb)

            except Exception:
                logger.exception(
                    "[KnowledgeManager] Knowledge database search failed"
                )

        return results

    # =========================================================
    # Individual Search Methods
    # =========================================================

    async def search_working_memory(
        self,
        question: str,
    ) -> List[Dict[str, Any]]:

        # Working memory is intentionally excluded from ordinary
        # factual questions. Otherwise temporary conversation state
        # can outrank real knowledge.
        if self._is_ordinary_knowledge_query(question):
            logger.info(
                "[KnowledgeManager] Working memory skipped for "
                "ordinary knowledge query."
            )
            return []

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
                        "content": str(snap),
                    }]

            except Exception:
                logger.exception(
                    "[KnowledgeManager] Working memory retrieval failed"
                )

        return []

    async def search_memory(
        self,
        question: str,
    ) -> List[Dict[str, Any]]:

        if self._is_ordinary_knowledge_query(
            question
        ):
            logger.info(
                "[KnowledgeManager] Personal memory retrieval "
                "skipped for ordinary knowledge query."
            )
            return []

        if (
            self.memory_engine
            and hasattr(
                self.memory_engine,
                "get_relevant_memories",
            )
        ):
            mems = await self.memory_engine.get_relevant_memories(
                question
            )

            if mems:
                normalized = []

                for m in mems:

                    if isinstance(m, dict):
                        content = m.get(
                            "content",
                            str(m),
                        )
                    else:
                        content = str(m)

                    if self._is_bad_knowledge_content(
                        content
                    ):
                        continue

                    normalized.append({
                        "source": "memory",
                        "confidence": 0.94,
                        "importance": 80,
                        "content": content,
                    })

                return normalized

        return []

    async def search_database(
        self,
        question: str,
    ) -> List[Dict[str, Any]]:

        if not (
            self.knowledge_database
            and hasattr(
                self.knowledge_database,
                "retrieve",
            )
        ):
            return []

        try:
            kb_res = await self.knowledge_database.retrieve(
                question
            )
        except Exception:
            logger.exception(
                "[KnowledgeManager] Knowledge database retrieval failed"
            )
            return []

        if not kb_res:
            return []

        normalized = []

        for item in kb_res:

            if isinstance(item, dict):

                content = item.get(
                    "content",
                    str(item),
                )

                # Preserve database metadata instead of throwing
                # it away. This is important for semantic retrieval.
                result = {
                    **item,
                    "source": item.get(
                        "source",
                        "knowledge_database",
                    ),
                    "confidence": item.get(
                        "confidence",
                        0.85,
                    ),
                    "importance": item.get(
                        "importance",
                        50,
                    ),
                    "relevance": item.get(
                        "relevance",
                        0.75,
                    ),
                    "freshness": item.get(
                        "freshness",
                        0.7,
                    ),
                    "content": content,
                }

            else:
                result = {
                    "source": "knowledge_database",
                    "confidence": 0.85,
                    "importance": 50,
                    "relevance": 0.75,
                    "freshness": 0.7,
                    "content": str(item),
                }

            if self._is_bad_knowledge_content(
                result.get("content", "")
            ):
                logger.warning(
                    "[KnowledgeManager] Rejected invalid knowledge "
                    "database result."
                )
                continue

            normalized.append(
                result
            )

        return normalized

    async def search_graph(
        self,
        question: str,
    ) -> List[Dict[str, Any]]:

        if not (
            self.knowledge_graph
            and hasattr(
                self.knowledge_graph,
                "search",
            )
        ):
            return []

        try:
            g_res = await self.knowledge_graph.search(
                question
            )
        except Exception:
            logger.exception(
                "[KnowledgeManager] Knowledge graph search failed"
            )
            return []

        if not g_res:
            return []

        normalized = []

        for item in g_res:

            content = (
                item.get("content", str(item))
                if isinstance(item, dict)
                else str(item)
            )

            if self._is_bad_knowledge_content(
                content
            ):
                continue

            normalized.append({
                "source": "knowledge_graph",
                "confidence": 0.81,
                "importance": 60,
                "relevance": 0.75,
                "content": content,
            })

        return normalized

    async def search_world(
        self,
        question: str,
    ) -> List[Dict[str, Any]]:

        if not (
            self.world_model
            and hasattr(
                self.world_model,
                "search",
            )
        ):
            return []

        try:
            w_res = await self.world_model.search(
                question
            )

            if asyncio.iscoroutine(w_res):
                w_res = await w_res

        except Exception:
            logger.exception(
                "[KnowledgeManager] World model search failed"
            )
            return []

        if not w_res:
            return []

        normalized = []

        if isinstance(w_res, dict):

            for k, v in w_res.items():

                if not v:
                    continue

                content = f"{k}: {v}"

                if self._is_bad_knowledge_content(
                    content
                ):
                    continue

                normalized.append({
                    "source": "world_model",
                    "confidence": 0.91,
                    "importance": 70,
                    "relevance": 0.75,
                    "content": content,
                })

        elif isinstance(w_res, list):

            for item in w_res:

                content = (
                    item.get("content", str(item))
                    if isinstance(item, dict)
                    else str(item)
                )

                if self._is_bad_knowledge_content(
                    content
                ):
                    continue

                normalized.append({
                    "source": "world_model",
                    "confidence": 0.91,
                    "importance": 70,
                    "relevance": 0.75,
                    "content": content,
                })

        return normalized

    async def search_documents(
        self,
        session_id: str,
        question: str,
    ) -> List[Dict[str, Any]]:

        if not self.state_manager:
            return []

        try:
            state = self.state_manager.get_state(
                session_id
            )

            if asyncio.iscoroutine(state):
                state = await state

        except Exception:
            logger.exception(
                "[KnowledgeManager] State lookup failed"
            )
            return []

        if not isinstance(state, dict):
            return []

        if (
            state.get("active_document")
            and self.document_ai
            and hasattr(
                self.document_ai,
                "answer_question",
            )
        ):
            try:
                doc_ans = await self.document_ai.answer_question(
                    session_id=session_id,
                    question=question,
                    state=state,
                )

                if doc_ans:

                    content = str(
                        doc_ans
                    ).strip()

                    if self._is_bad_knowledge_content(
                        content
                    ):
                        return []

                    return [{
                        "source": "document",
                        "confidence": 0.95,
                        "importance": 85,
                        "relevance": 0.95,
                        "freshness": 0.8,
                        "content": content,
                    }]

            except Exception:
                logger.exception(
                    "[KnowledgeManager] Document question answering failed"
                )

        return []

    async def search_skills(
        self,
        question: str,
    ) -> List[Dict[str, Any]]:

        if not (
            self.skill_manager
            and hasattr(
                self.skill_manager,
                "route_and_execute",
            )
        ):
            return []

        try:
            skill_res = await self.skill_manager.route_and_execute(
                question,
                {},
            )

            if not skill_res:
                return []

            if not getattr(
                skill_res,
                "success",
                False,
            ):
                return []

            data = getattr(
                skill_res,
                "data",
                {},
            )

            if not isinstance(data, dict):
                data = {
                    "response": str(data)
                }

            msg = (
                data.get("response")
                or data.get("message")
                or data.get("content")
                or str(data)
            )

            if self._is_bad_knowledge_content(
                msg
            ):
                return []

            return [{
                "source": "skill",
                "confidence": 0.80,
                "importance": 50,
                "relevance": 0.70,
                "content": str(msg),
            }]

        except Exception:
            logger.exception(
                "[KnowledgeManager] Skill search failed"
            )
            return []

    # =========================================================
    # Merge Results
    # =========================================================

    async def merge_results(
        self,
        *sources,
    ) -> List[Dict[str, Any]]:

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
                        "content": str(raw_item)
                    }
                )

                content = item.get(
                    "content",
                    "",
                ).strip()

                if not content:
                    continue

                # Never allow system failure text to enter the
                # knowledge graph/index again.
                if self._is_bad_knowledge_content(
                    content
                ):
                    logger.warning(
                        "[KnowledgeManager] Rejected failure text "
                        "from merged knowledge results."
                    )
                    continue

                key = content.lower()

                if key in seen:

                    existing = seen[key]

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

                    if source not in existing_sources:
                        existing_sources.append(
                            source
                        )

                    existing["evidence_count"] = (
                        existing.get(
                            "evidence_count",
                            1,
                        ) + 1
                    )

                    continue

                item["supporting_sources"] = [
                    item.get(
                        "source",
                        "unknown",
                    )
                ]

                item["evidence_count"] = 1

                seen[key] = item
                flattened.append(item)

        return flattened

    # =========================================================
    # Rank Results
    # =========================================================

    async def rank_results(
        self,
        results: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:

        def clamp(
            value,
            minimum=0.0,
            maximum=1.0,
        ):
            try:
                value = float(value)
            except (
                TypeError,
                ValueError,
            ):
                value = minimum

            return max(
                minimum,
                min(
                    value,
                    maximum,
                ),
            )

        def sort_key(item):

            confidence = clamp(
                item.get(
                    "confidence",
                    0.5,
                )
            )

            relevance = clamp(
                item.get(
                    "relevance",
                    0.5,
                )
            )

            freshness = clamp(
                item.get(
                    "freshness",
                    0.5,
                )
            )

            importance = clamp(
                item.get(
                    "importance",
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

            # Built-in/local foundational knowledge gets a small
            # deterministic preference when it is an exact match.
            local_bonus = (
                0.10
                if item.get(
                    "local_knowledge",
                    False,
                )
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

            item["evidence_score"] = round(
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

    # =========================================================
    # Unified Retrieval
    # =========================================================

    async def retrieve(
        self,
        session_id: str,
        question: str,
    ) -> List[Dict[str, Any]]:

        # -----------------------------------------------------
        # Deterministic local knowledge gets first-class priority.
        # -----------------------------------------------------

        local_fact = (
            self._local_foundational_knowledge(
                question
            )
        )

        if local_fact:
            logger.info(
                "[LocalKnowledge] Deterministic foundational "
                "knowledge match found."
            )

            # Still retrieve database knowledge so that once the
            # large corpus is populated, it can coexist with this.
            try:
                knowledge = await self.search_database(
                    question
                )
            except Exception:
                logger.exception(
                    "[KnowledgeManager] Database search failed"
                )
                knowledge = []

            merged = await self.merge_results(
                [local_fact],
                knowledge,
            )

            return await self.rank_results(
                merged
            )

        # -----------------------------------------------------
        # Normal retrieval pipeline
        # -----------------------------------------------------

        try:
            working = await self.search_working_memory(
                question
            )
        except Exception:
            logger.exception(
                "[KnowledgeManager] Working memory search failed"
            )
            working = []

        try:
            memory = await self.search_memory(
                question
            )
        except Exception:
            logger.exception(
                "[KnowledgeManager] Memory search failed"
            )
            memory = []

        try:
            knowledge = await self.search_database(
                question
            )
        except Exception:
            logger.exception(
                "[KnowledgeManager] Database search failed"
            )
            knowledge = []

        try:
            graph = await self.search_graph(
                question
            )
        except Exception:
            logger.exception(
                "[KnowledgeManager] Graph search failed"
            )
            graph = []

        try:
            world = await self.search_world(
                question
            )
        except Exception:
            logger.exception(
                "[KnowledgeManager] World model search failed"
            )
            world = []

        try:
            documents = await self.search_documents(
                session_id,
                question,
            )
        except Exception:
            logger.exception(
                "[KnowledgeManager] Document search failed"
            )
            documents = []

        try:
            skills = await self.search_skills(
                question
            )
        except Exception:
            logger.exception(
                "[KnowledgeManager] Skills search failed"
            )
            skills = []

        merged = await self.merge_results(
            working,
            memory,
            knowledge,
            graph,
            world,
            documents,
            skills,
        )

        return await self.rank_results(
            merged
        )

    # =========================================================
    # Web Decision
    # =========================================================

    async def needs_web(
        self,
        results: List[Dict[str, Any]],
    ) -> bool:

        if not results:
            return True

        # A deterministic/local verified answer means there is
        # no reason to perform a web request.
        if results[0].get(
            "local_knowledge",
            False,
        ):
            return False

        top_conf = results[0].get(
            "confidence",
            0.0,
        )

        if top_conf < 0.40:
            return True

        return False

    async def search_web(
        self,
        question: str,
    ) -> Optional[Dict[str, Any]]:

        if not (
            self.web_search
            and hasattr(
                self.web_search,
                "execute",
            )
        ):
            return None

        try:
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
            )

            if not isinstance(data, dict):
                data = {
                    "result": str(data)
                }

            answer = (
                data.get("result")
                or data.get("content")
                or data.get("answer")
                or str(data)
            )

            answer = str(
                answer
            ).strip()

            if self._is_bad_knowledge_content(
                answer
            ):
                logger.warning(
                    "[KnowledgeManager] Rejected invalid web result."
                )
                return None

            # Web is an allowed fallback for current/unknown
            # information. It is NOT an external answer LLM.
            if self.learning_engine:
                try:
                    await self.learning_engine.learn(
                        text=answer,
                        source="web",
                    )
                except Exception:
                    logger.exception(
                        "[KnowledgeManager] Failed to learn web result"
                    )

            return {
                "source": "web_search",
                "confidence": 0.75,
                "importance": 70,
                "relevance": 0.90,
                "freshness": 1.0,
                "verified": False,
                "content": answer,

                "local_knowledge": False,
                "external_llm_synthesis": False,
            }

        except Exception:
            logger.exception(
                "[KnowledgeManager] Web search failed"
            )
            return None

    # =========================================================
    # Best Answer
    # =========================================================

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

    async def best_answer(
        self,
        question: str,
        results: List[Dict[str, Any]],
    ) -> str:

        if not results:
            return (
                "I couldn't find any relevant information."
            )

        # -----------------------------------------------------
        # HARD LOCAL KNOWLEDGE GATE
        # -----------------------------------------------------
        #
        # Ordinary factual questions NEVER enter LLMRouter.
        # The local evidence itself is the answer.
        # -----------------------------------------------------

        if self._is_ordinary_knowledge_query(
            question
        ):
            logger.info(
                "[LocalKnowledge] Ordinary knowledge query "
                "detected; external LLM synthesis skipped."
            )

            for result in results:

                content = str(
                    result.get(
                        "content",
                        "",
                    )
                ).strip()

                if self._is_bad_knowledge_content(
                    content
                ):
                    continue

                if content:
                    logger.info(
                        "[LocalKnowledge] Returning local evidence "
                        "without LLM synthesis. source=%s",
                        result.get(
                            "source",
                            "unknown",
                        ),
                    )

                    return content

            return (
                "I couldn't find reliable local information "
                "for that question."
            )

        # -----------------------------------------------------
        # High-confidence non-ordinary evidence
        # -----------------------------------------------------

        if (
            len(results) == 1
            or results[0].get(
                "confidence",
                0,
            ) > 0.92
        ):
            content = str(
                results[0].get(
                    "content",
                    "",
                )
            ).strip()

            if not self._is_bad_knowledge_content(
                content
            ):
                return content

        # -----------------------------------------------------
        # Non-ordinary queries may use LLM synthesis.
        #
        # This is deliberately NOT reachable for ordinary
        # factual questions.
        # -----------------------------------------------------

        if (
            self.llm_router
            and hasattr(
                self.llm_router,
                "chat",
            )
        ):

            valid_results = [
                r
                for r in results[:5]
                if not self._is_bad_knowledge_content(
                    r.get(
                        "content",
                        "",
                    )
                )
            ]

            if not valid_results:
                return (
                    "I couldn't find reliable information "
                    "for that request."
                )

            evidence_str = "\n\n".join(
                f"Evidence ({r.get('source')}): "
                f"{r.get('content')}"
                for r in valid_results
            )

            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are ARIA, a helpful AI assistant. "
                        "Synthesize only the provided evidence. "
                        "Do not invent facts."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Question: {question}\n\n"
                        f"{evidence_str}"
                    ),
                },
            ]

            try:
                synth = await self.llm_router.chat(
                    messages
                )

                if synth:
                    synth = str(
                        synth
                    ).strip()

                    if not self._is_bad_knowledge_content(
                        synth
                    ):
                        return synth

            except Exception:
                logger.exception(
                    "[KnowledgeManager] LLM synthesis failed; "
                    "using local evidence."
                )

        return str(
            results[0].get(
                "content",
                "",
            )
        ).strip()

    # =========================================================
    # Remember Answer
    # =========================================================

    async def remember_answer(
        self,
        question: str,
        answer: str,
        source: str,
    ):

        # Never save provider/system failure text as knowledge.
        if self._is_bad_knowledge_content(
            answer
        ):
            logger.warning(
                "[KnowledgeManager] Refusing to store failure "
                "response as knowledge."
            )
            return

        if (
            self.knowledge_database
            and hasattr(
                self.knowledge_database,
                "store",
            )
        ):
            try:
                await self.knowledge_database.store(
                    title=str(
                        question
                    )[:100],
                    content=str(
                        answer
                    ),
                    source=source,
                )
            except Exception:
                logger.exception(
                    "[KnowledgeManager] Failed to store answer"
                )

        if (
            self.learning_engine
            and hasattr(
                self.learning_engine,
                "learn",
            )
        ):
            try:
                await self.learning_engine.learn(
                    text=str(answer),
                    source=source,
                )
            except Exception:
                logger.exception(
                    "[KnowledgeManager] Failed to learn answer"
                )

    # =========================================================
    # Main Answer Pipeline
    # =========================================================

    async def answer(
        self,
        session_id,
        question,
    ):

        question = str(
            question or ""
        ).strip()

        if not question:
            return None

        results = await self.retrieve(
            session_id,
            question,
        )

        # -----------------------------------------------------
        # For ordinary knowledge:
        #
        # 1. local knowledge
        # 2. local database
        # 3. web fallback
        # 4. no external LLM synthesis
        # -----------------------------------------------------

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

                results = await self.rank_results(
                    results
                )

        if not results:
            logger.info(
                "[KnowledgeManager] No knowledge results found."
            )
            return None

        final_answer = await self.best_answer(
            question,
            results,
        )

        if not final_answer:
            return None

        # -----------------------------------------------------
        # Explicit safety check before returning the answer.
        # -----------------------------------------------------

        if self._is_bad_knowledge_content(
            final_answer
        ):
            logger.warning(
                "[KnowledgeManager] Final knowledge answer "
                "was rejected as invalid."
            )
            return None

        return final_answer

    # =========================================================
    # Learn New Knowledge
    # =========================================================

    async def learn(
        self,
        text,
        source="conversation",
    ):

        text = str(
            text or ""
        ).strip()

        if not text:
            return

        # Never teach ARIA that an infrastructure/provider
        # failure is factual knowledge.
        if self._is_bad_knowledge_content(
            text
        ):
            logger.warning(
                "[KnowledgeManager] Rejected invalid learning "
                "payload from source=%s",
                source,
            )
            return

        if (
            self.learning_engine
            and hasattr(
                self.learning_engine,
                "learn",
            )
        ):
            await self.learning_engine.learn(
                text=text,
                source=source,
            )

    # =========================================================
    # Store Structured Fact
    # =========================================================

    async def remember_fact(
        self,
        subject,
        relation,
        value,
    ):

        if (
            self.knowledge_graph
            and hasattr(
                self.knowledge_graph,
                "add_fact",
            )
        ):
            await self.knowledge_graph.add_fact(
                subject,
                relation,
                value,
            )

    # =========================================================
    # Save Knowledge
    # =========================================================

    async def save_knowledge(
        self,
        title,
        content,
        source="conversation",
    ):

        content = str(
            content or ""
        ).strip()

        if not content:
            return

        # Critical protection against storing LLM failure
        # responses into the permanent knowledge database.
        if self._is_bad_knowledge_content(
            content
        ):
            logger.warning(
                "[KnowledgeManager] Refused to save invalid "
                "knowledge content. source=%s",
                source,
            )
            return

        if (
            self.knowledge_database
            and hasattr(
                self.knowledge_database,
                "store",
            )
        ):
            await self.knowledge_database.store(
                title=str(
                    title or ""
                )[:100],
                content=content,
                source=source,
            )