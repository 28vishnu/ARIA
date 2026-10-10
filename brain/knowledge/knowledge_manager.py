from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
import logging
import asyncio
import os
import re
import sqlite3
from pathlib import Path

from brain.knowledge.answer_composer import AnswerComposer

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
        # Deterministic, non-LLM answer formatting over evidence from all stores.
        self.answer_composer = AnswerComposer()

    # =========================================================
    # Local Knowledge Safety
    # =========================================================

    @staticmethod
    def _is_ordinary_knowledge_query(question: str) -> bool:
        """Recognize stable factual questions that must use local retrieval only."""
        q = re.sub(r"\s+", " ", str(question or "").strip().lower()).replace("’", "'")
        for pattern, replacement in (
            (r"^what's\b", "what is"), (r"^whats\b", "what is"),
            (r"^who's\b", "who is"), (r"^whos\b", "who is"),
            (r"^where's\b", "where is"), (r"^wheres\b", "where is"),
            (r"^when's\b", "when is"), (r"^whens\b", "when is"),
            (r"^how's\b", "how is"), (r"^hows\b", "how is"),
        ):
            q = re.sub(pattern, replacement, q)
        if not q:
            return False
        personal_markers = (
            "my name", "my favorite", "my favourite", "what do you know about me",
            "remember", "memorize", "save this", "store this", "don't forget",
            "do not forget", "forget this", "forget that", "what did i tell you",
            "what did i say", "what have i told you", "my college", "my password",
        )
        if any(marker in q for marker in personal_markers):
            return False
        explicit_online = any(marker in q for marker in (
            "search the web", "search online", "search the internet", "browse online",
            "look up online", "on the internet", "online sources", "live web search",
        ))
        # News is served from the locally ingested RSS corpus by default. Only an
        # explicit request to search online should leave the local-first route.
        if "news" in q and not explicit_online:
            return True
        current_markers = (
            "latest", "current", "currently", "today", "tonight", "tomorrow",
            "right now", "this week", "this month", "this year", "breaking",
            "online", "search the web", "look up", "on the internet", "recent",
        )
        if any(marker in q for marker in current_markers):
            return False
        prefixes = (
            "what is ", "what are ", "what does ", "what do ", "what was ",
            "what were ", "who is ", "who are ", "where is ", "where are ",
            "when is ", "when was ", "why is ", "why are ", "why does ",
            "why do ", "how does ", "how do ", "how is ", "how are ",
            "explain ", "define ", "describe ", "tell me about ",
            "difference between ", "compare ",
        )
        if q.startswith(prefixes):
            return True
        return (" vs " in f" {q} " or " versus " in f" {q} ") and ("?" in q or q.endswith(("tcp", "udp")))

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

        if text.startswith("query:") and "answer:" in text:
            return True

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
        q = re.sub(r"\s+", " ", str(question or "").strip().lower()).replace("’", "'")
        # Normalize common contractions so direct local facts work for natural
        # Telegram phrasing such as "What's TCP and UDP?".
        q = re.sub(r"^what's\b", "what is", q)
        q = re.sub(r"^whats\b", "what is", q)
        q = re.sub(r"^what is the difference between\b", "difference between", q)
        q = q.strip(" \t.,;:!?")

        if not q:
            return None

        # -----------------------------------------------------
        # Compound comparison: TCP and UDP
        # -----------------------------------------------------
        if ("tcp" in q and "udp" in q) and (
            "difference" in q or "compare" in q or "versus" in q
            or re.search(r"\bwhat is tcp and udp\b", q)
            or re.search(r"\btcp and udp\b", q)
        ):
            return {
                "source": "local_foundational_knowledge",
                "title": "TCP vs UDP",
                "confidence": 1.0,
                "importance": 100,
                "relevance": 1.0,
                "freshness": 1.0,
                "verified": True,
                "evidence_type": "built_in_fact",
                "provenance": "ARIA foundational networking knowledge; TCP: RFC 9293; UDP: RFC 768",
                "url": "https://www.rfc-editor.org/rfc/rfc9293",
                "metadata": {"related_sources": [
                    {"title": "Transmission Control Protocol (TCP)", "url": "https://www.rfc-editor.org/rfc/rfc9293"},
                    {"title": "User Datagram Protocol (UDP)", "url": "https://www.rfc-editor.org/rfc/rfc768"},
                ]},
                "content": (
                    "TCP (Transmission Control Protocol) and UDP (User Datagram Protocol) "
                    "are transport-layer protocols used over IP networks.\n\n"
                    "TCP: connection-oriented; establishes a connection before sending data; "
                    "provides reliable, ordered byte-stream delivery using acknowledgements "
                    "and retransmissions; includes flow and congestion control; has more "
                    "protocol overhead. Common uses include web connections, email, and file transfer.\n\n"
                    "UDP: connectionless; sends independent datagrams without establishing a "
                    "connection; does not guarantee delivery, ordering, or retransmission; has "
                    "lower protocol overhead and can suit latency-sensitive traffic. Common uses "
                    "include DNS queries, voice/video calls, live streaming, and many online games.\n\n"
                    "Main difference: TCP prioritizes reliable, ordered delivery, while UDP "
                    "prioritizes lightweight message delivery and leaves reliability, if needed, "
                    "to the application. UDP is not automatically faster in every situation; "
                    "the result depends on the network and application. Neither protocol "
                    "provides encryption by itself."
                ),
                "local_knowledge": True,
                "external_llm_synthesis": False,
            }

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

    # =========================================================
    # Optional Wikipedia / Wikidata SQLite Corpus
    # =========================================================

    @staticmethod
    def _search_open_knowledge_sync(
        question: str,
        db_path: str,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """Search either the current documents schema or legacy open_knowledge schema.

        The importer in brain.knowledge.open_knowledge creates:
          documents(id, source, source_id, title, content, url, language)
          documents_fts(rowid, title, content, source, source_id)
        Older development databases may use open_knowledge/source_url instead.
        This adapter intentionally supports both, without modifying the corpus.
        """
        question = str(question or "").strip()
        path = Path(db_path).expanduser()
        if not question or not path.is_file():
            return []

        tokens = re.findall(r"[\w'-]+", question, flags=re.UNICODE)
        stop_words = {
            "what", "is", "are", "the", "a", "an", "of", "to", "and",
            "or", "in", "on", "for", "using", "only", "aria", "local",
            "knowledge", "database", "stored", "provide", "source", "url",
            "explain", "please", "give", "me", "your", "from", "do", "not",
            "call", "any", "external", "language", "model",
        }
        tokens = [t for t in tokens if len(t) > 1 and t.lower() not in stop_words][:12]
        if not tokens:
            # If the query is an instruction, the caller should resolve its topic
            # first. Do not run a broad empty query against the corpus.
            return []

        limit = max(1, min(int(limit), 20))
        conn = None
        try:
            conn = sqlite3.connect(
                path.resolve().as_uri() + "?mode=ro",
                uri=True,
                timeout=10.0,
            )
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=10000")

            tables = {
                str(row[0])
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
                ).fetchall()
            }

            if "documents" in tables:
                table = "documents"
                url_column = "url"
                fts_table = "documents_fts"
            elif "open_knowledge" in tables:
                table = "open_knowledge"
                url_column = "source_url"
                fts_table = "open_knowledge_fts"
            else:
                logger.warning(
                    "[KnowledgeManager] Open-knowledge DB has no recognized corpus table: %s",
                    path,
                )
                return []

            columns = {
                str(row[1])
                for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
            }
            required = {"id", "source", "source_id", "title", "content", url_column}
            if not required.issubset(columns):
                logger.error(
                    "[KnowledgeManager] Corpus schema mismatch for %s; table=%s columns=%s",
                    path, table, sorted(columns),
                )
                return []

            match_query = " OR ".join(
                '"' + token.replace('"', '""') + '"'
                for token in tokens
            )
            rows = []
            if fts_table in tables:
                try:
                    rows = conn.execute(
                        f"""
                        SELECT d.source, d.source_id, d.title, d.content,
                               d.{url_column} AS url,
                               bm25({fts_table}) AS score
                        FROM {fts_table}
                        JOIN {table} d ON d.id = {fts_table}.rowid
                        WHERE {fts_table} MATCH ?
                        ORDER BY score
                        LIMIT ?
                        """,
                        (match_query, limit),
                    ).fetchall()
                except sqlite3.OperationalError:
                    # An FTS table may exist but be out of sync or unavailable.
                    logger.warning(
                        "[KnowledgeManager] FTS query failed for %s; using LIKE fallback",
                        table,
                    )

            if not rows:
                # Search by informative tokens. OR semantics avoids requiring every
                # token from a natural-language question to occur in the document.
                like_tokens = tokens[:8]
                conditions = " OR ".join(
                    "(title LIKE ? OR content LIKE ?)"
                    for _ in like_tokens
                )
                params = []
                for token in like_tokens:
                    params.extend((f"%{token}%", f"%{token}%"))
                rows = conn.execute(
                    f"""
                    SELECT source, source_id, title, content,
                           {url_column} AS url
                    FROM {table}
                    WHERE {conditions}
                    ORDER BY CASE WHEN lower(title) LIKE lower(?) THEN 0 ELSE 1 END
                    LIMIT ?
                    """,
                    (*params, f"%{tokens[0]}%", limit),
                ).fetchall()

            results: List[Dict[str, Any]] = []
            for row in rows:
                content = str(row["content"] or "").strip()
                title = str(row["title"] or "").strip()
                url = str(row["url"] or "").strip()
                source = str(row["source"] or "open_knowledge").strip().lower()
                if not content or not url:
                    continue
                if KnowledgeManager._is_bad_knowledge_content(content):
                    continue
                results.append({
                    "source": source,
                    "source_id": str(row["source_id"] or ""),
                    "title": title,
                    "content": content[:3500],
                    "url": url,
                    "language": "en",
                    "confidence": 0.90 if source.lower().startswith("news") else 0.88,
                    "importance": 85 if source.lower().startswith("news") else 70,
                    "relevance": 0.95 if source.lower().startswith("news") else 0.88,
                    "freshness": 0.98 if source.lower().startswith("news") else 0.65,
                    "verified": False,
                    "evidence_type": "open_dataset",
                    "provenance": url,
                    "local_knowledge": True,
                    "external_llm_synthesis": False,
                })
            # Prefer readable encyclopedia prose over terse Wikidata entity
            # descriptions for ordinary explanatory questions.
            results.sort(
                key=lambda item: (
                    0 if item.get("source") == "wikipedia" else
                    1 if item.get("source") == "wikidata" else 2,
                    -len(str(item.get("content") or "")),
                )
            )
            return results

        except (sqlite3.Error, OSError, ValueError) as exc:
            logger.exception(
                "[KnowledgeManager] Open-knowledge SQLite search failed: %s",
                exc,
            )
            return []
        finally:
            if conn is not None:
                conn.close()

    async def search_open_knowledge(
        self,
        question: str,
    ) -> List[Dict[str, Any]]:
        """Retrieve local corpus evidence and fill missing topic records.

        Compound questions are handled per topic. If TCP is already cached but
        UDP was missed during a Wikimedia rate limit, ARIA retries only the
        missing topic instead of treating the first partial result as complete.
        """
        db_path = os.environ.get(
            "ARIA_OPEN_KNOWLEDGE_DB",
            "data/aria_open_knowledge.sqlite3",
        )

        try:
            results = await asyncio.to_thread(
                self._search_open_knowledge_sync, question, db_path, 5
            )
        except Exception:
            logger.exception("[KnowledgeManager] Open-knowledge retrieval failed")
            results = []

        if not self._is_ordinary_knowledge_query(question):
            if results:
                logger.info("[LocalKnowledge] Retrieved %d open-corpus result(s)", len(results))
            return results

        normalized_question = re.sub(
            r"\s+", " ", str(question or "").strip()
        ).replace("’", "'")
        for pattern, replacement in (
            (r"^what's\b", "what is"), (r"^whats\b", "what is"),
            (r"^who's\b", "who is"), (r"^whos\b", "who is"),
        ):
            normalized_question = re.sub(
                pattern, replacement, normalized_question, flags=re.IGNORECASE
            )

        topic = re.sub(
            r"^\s*(?:what is the difference between|what is a difference between|"
            r"difference between|compare|what is|what are|what does|what do|"
            r"who is|who are|where is|where are|when is|when was|why is|why are|"
            r"why does|why do|how is|how are|how does|how do|define|explain|"
            r"describe|tell me about)\s+",
            "", normalized_question, flags=re.IGNORECASE,
        ).strip(" \t.,;:!?")
        topic = re.sub(
            r"\s+(?:and give|and provide|provide the source|give the source|with source).*?$",
            "", topic, flags=re.IGNORECASE,
        ).strip(" \t.,;:!?")

        if not topic or len(topic) > 180:
            if results:
                logger.info("[LocalKnowledge] Retrieved %d open-corpus result(s)", len(results))
            return results

        topic_parts = [topic]
        compound = re.fullmatch(
            r"(.+?)\s+(?:and|vs\.?|versus)\s+(.+)", topic, flags=re.IGNORECASE
        )
        if compound:
            topic_parts = [part.strip(" \t.,;:!?") for part in compound.groups()]

        def has_topic_record(topic_part: str, items: List[Dict[str, Any]]) -> bool:
            target = re.sub(r"\W+", " ", topic_part.lower()).strip()
            if not target:
                return True
            for item in items:
                title = re.sub(r"\W+", " ", str(item.get("title") or "").lower()).strip()
                content = str(item.get("content") or "").lower()
                if target == title or target in title:
                    return True
                # Acronyms often appear as aliases in a Wikidata description.
                if re.search(r"\baliases?\s*:\s*[^.]{0,300}\b" + re.escape(topic_part.lower()) + r"\b", content):
                    return True
            return False

        missing_topics = [
            part for part in topic_parts[:3]
            if not has_topic_record(part, results)
        ]
        # Query-time retrieval is strictly local. Dataset acquisition and RSS
        # refresh run through KnowledgeHub on an explicit/scheduled path; never
        # call Wikipedia/Wikidata APIs while answering a user question.
        if missing_topics:
            logger.info(
                "[LocalKnowledge] Missing local topic(s) %s; online API fetch skipped. "
                "Use bulk dataset ingestion or wait for scheduled acquisition.",
                missing_topics,
            )

        # Re-query every component separately. This is essential because FTS
        # AND queries for "TCP and UDP" do not match two separate articles.
        search_terms = topic_parts if len(topic_parts) > 1 else [question, topic_parts[0]]
        gathered: List[Dict[str, Any]] = list(results)
        for search_term in search_terms:
            try:
                part_results = await asyncio.to_thread(
                    self._search_open_knowledge_sync, search_term, db_path, 5
                )
                gathered.extend(part_results or [])
            except Exception:
                logger.exception(
                    "[LocalKnowledge] Corpus search failed for component %r", search_term
                )

        seen_keys = set()
        merged_results: List[Dict[str, Any]] = []
        for item in gathered:
            identity = (
                str(item.get("url") or item.get("source_url") or ""),
                re.sub(r"\W+", " ", str(item.get("content") or "").lower()).strip(),
            )
            if identity in seen_keys:
                continue
            seen_keys.add(identity)
            merged_results.append(item)

        if "news" in str(question or "").lower():
            merged_results.sort(
                key=lambda item: (
                    0 if str(item.get("source") or "").lower().startswith("news") else 1,
                    0 if re.search(r"Published:\s*20\d\d-", str(item.get("content") or "")) else 1,
                    str(item.get("content") or ""),
                )
            )
        else:
            merged_results.sort(
                key=lambda item: (
                    0 if item.get("source") == "wikipedia" else
                    1 if item.get("source") == "wikidata" else 2,
                    -len(str(item.get("content") or "")),
                )
            )
        if merged_results:
            logger.info(
                "[LocalKnowledge] Retrieved %d open-corpus result(s)",
                len(merged_results),
            )
        return merged_results

    async def search_database(
        self,
        question: str,
    ) -> List[Dict[str, Any]]:
        """Merge the existing knowledge database with the optional corpus."""
        normalized: List[Dict[str, Any]] = []

        # Preserve ARIA's existing database retrieval.
        if (
            self.knowledge_database
            and hasattr(self.knowledge_database, "retrieve")
        ):
            try:
                kb_res = await self.knowledge_database.retrieve(question)
            except Exception:
                logger.exception(
                    "[KnowledgeManager] Knowledge database retrieval failed"
                )
                kb_res = []

            if kb_res:
                for item in kb_res:
                    if isinstance(item, dict):
                        content = item.get("content", str(item))
                        result = {
                            **item,
                            "source": item.get(
                                "source", "knowledge_database"
                            ),
                            "confidence": item.get("confidence", 0.85),
                            "importance": item.get("importance", 50),
                            "relevance": item.get("relevance", 0.75),
                            "freshness": item.get("freshness", 0.7),
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

                    source_name = str(result.get("source", "knowledge_database") or "knowledge_database").strip().lower()
                    if self._is_ordinary_knowledge_query(question) and source_name in {
                        "conversation", "memory", "success", "working_memory",
                        "episodic_memory", "chat", "assistant_response",
                    }:
                        logger.info(
                            "[KnowledgeBrain] Ignored unverified %s record for factual query.",
                            source_name,
                        )
                        continue

                    if self._is_bad_knowledge_content(
                        result.get("content", "")
                    ):
                        logger.warning(
                            "[KnowledgeManager] Rejected invalid knowledge "
                            "database result."
                        )
                        continue

                    normalized.append(result)

        # The SQLite corpus is optional and does not replace existing stores.
        # It is read only when ARIA_OPEN_KNOWLEDGE_DB points to an existing DB.
        normalized.extend(
            await self.search_open_knowledge(question)
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
            # WorldModel.search in this repository is synchronous, while some
            # adapters may implement it asynchronously. Call first, then await
            # only when the returned value is awaitable. Awaiting a plain dict
            # caused the recurring "World model search failed" log.
            w_res = self.world_model.search(question)
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

    @staticmethod
    def _get_local_answer_cache(question: str):
        from brain.knowledge.knowledge_hub import get_cached_answer
        return get_cached_answer(question)

    @staticmethod
    def _save_local_answer_cache(question: str, answer: str, evidence):
        from brain.knowledge.knowledge_hub import cache_answer
        return cache_answer(question, answer, evidence)

    # =========================================================
    # Unified Retrieval
    # =========================================================

    async def retrieve(
        self,
        session_id: str,
        question: str,
    ) -> List[Dict[str, Any]]:
        """Retrieve evidence from ARIA's connected knowledge systems.

        The built-in facts, Mongo/knowledge DB, Wikipedia/Wikidata SQLite
        corpus, knowledge graph, world model, documents, skills, and allowed
        working-memory sources are merged and ranked as one evidence set.
        Personal/episodic memory helpers already skip ordinary factual queries.
        """
        # Exact-question cache is local and source-backed. It avoids repeating
        # retrieval/composition for questions ARIA has already answered reliably.
        try:
            cached = None
            if self._is_ordinary_knowledge_query(question):
                cached = await asyncio.to_thread(self._get_local_answer_cache, question)
            if cached and cached.get("answer"):
                logger.info("[KnowledgeBrain] Exact local answer-cache hit; retrieval skipped.")
                return [{
                    "source": "local_answer_cache",
                    "title": "Previously verified local answer",
                    "content": str(cached["answer"]),
                    "url": "",
                    "confidence": 0.99,
                    "importance": 95,
                    "relevance": 1.0,
                    "freshness": 0.95,
                    "verified": True,
                    "evidence_type": "cached_composed_answer",
                    "local_knowledge": True,
                    "cached_answer": True,
                    "cache_sources": cached.get("sources", []),
                    "external_llm_synthesis": False,
                }]
        except Exception:
            logger.exception("[KnowledgeBrain] Local answer cache lookup failed; continuing retrieval.")

        local_fact = self._local_foundational_knowledge(question)
        if local_fact:
            logger.info(
                "[KnowledgeBrain] Found a deterministic foundational fact; "
                "merging it with other knowledge sources."
            )

        async def safe_call(label, coroutine):
            try:
                return await coroutine
            except Exception:
                logger.exception("[KnowledgeBrain] %s retrieval failed", label)
                return []

        if self._is_ordinary_knowledge_query(question):
            # Ordinary facts must not be sourced from episodic chat memory or
            # executable skills. Use the shared factual brain: SQLite corpus,
            # trusted knowledge DB, graph, world model, and explicitly active docs.
            working, memory, knowledge, graph, world, documents, skills = await asyncio.gather(
                asyncio.sleep(0, result=[]),
                asyncio.sleep(0, result=[]),
                safe_call("knowledge database/Wikipedia/Wikidata", self.search_database(question)),
                safe_call("knowledge graph", self.search_graph(question)),
                safe_call("world model", self.search_world(question)),
                # Include only documents explicitly active in this session;
                # never search personal/episodic chat memory for general facts.
                safe_call("active document", self.search_documents(session_id, question)),
                asyncio.sleep(0, result=[]),
            )
        else:
            working, memory, knowledge, graph, world, documents, skills = await asyncio.gather(
                safe_call("working memory", self.search_working_memory(question)),
                safe_call("memory", self.search_memory(question)),
                safe_call("knowledge database/Wikipedia/Wikidata", self.search_database(question)),
                safe_call("knowledge graph", self.search_graph(question)),
                safe_call("world model", self.search_world(question)),
                safe_call("documents", self.search_documents(session_id, question)),
                safe_call("skills", self.search_skills(question)),
            )

        merged = await self.merge_results(
            [local_fact] if local_fact else [],
            working,
            memory,
            knowledge,
            graph,
            world,
            documents,
            skills,
        )
        ranked = await self.rank_results(merged)
        logger.info(
            "[KnowledgeBrain] Unified retrieval completed: %d evidence records; "
            "sources=%s",
            len(ranked),
            sorted({str(item.get('source', 'unknown')) for item in ranked}),
        )
        return ranked

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
    ) -> List[Dict[str, Any]]:
        """Return cited web evidence records without generating an answer.

        Search snippets are evidence only. They are not automatically written
        into the permanent knowledge base because snippets may be incomplete
        and often lack enough context for safe factual learning.
        """
        if not (self.web_search and hasattr(self.web_search, "execute")):
            return []

        try:
            res = await self.web_search.execute({"query": question, "max_results": 5})
            if not res or not getattr(res, "success", False):
                return []

            data = getattr(res, "data", {})
            if not isinstance(data, dict):
                data = {"content": str(data)}

            raw_results = data.get("results")
            evidence: List[Dict[str, Any]] = []
            if isinstance(raw_results, list):
                for item in raw_results[:5]:
                    if not isinstance(item, dict):
                        continue
                    title = str(item.get("title") or "").strip()
                    url = str(item.get("url") or item.get("link") or "").strip()
                    content = str(
                        item.get("snippet") or item.get("content")
                        or item.get("description") or ""
                    ).strip()
                    if not content or self._is_bad_knowledge_content(content):
                        continue
                    if not url.startswith(("https://", "http://")):
                        continue
                    evidence.append({
                        "source": "web_search",
                        "source_id": url,
                        "title": title or url,
                        "url": url,
                        "content": content,
                        "confidence": 0.68,
                        "importance": 60,
                        "relevance": 0.78,
                        "freshness": 0.95,
                        "verified": False,
                        "evidence_type": "web_snippet",
                        "provenance": url,
                        "local_knowledge": False,
                        "external_llm_synthesis": False,
                    })

            # Compatibility fallback for providers that return a single text.
            if not evidence:
                text = str(
                    data.get("result") or data.get("content")
                    or data.get("answer") or ""
                ).strip()
                if text and not self._is_bad_knowledge_content(text):
                    # Parse the stable WebSearchAction format: title, URL, snippet.
                    blocks = re.split(r"\n\s*\n", text)
                    for block in blocks[:5]:
                        match = re.search(r"(?im)^\s*URL:\s*(https?://\S+)\s*$", block)
                        if not match:
                            continue
                        url = match.group(1).rstrip(".,;:!?\"'")
                        title_match = re.match(r"\s*\d+\.\s*(.*?)\s*\n", block)
                        title = title_match.group(1).strip() if title_match else url
                        snippet = re.sub(r"(?im)^\s*(?:\d+\.\s*.*|URL:\s*https?://\S+)\s*$", "", block).strip()
                        if snippet:
                            evidence.append({
                                "source": "web_search", "source_id": url,
                                "title": title, "url": url, "content": snippet,
                                "confidence": 0.65, "importance": 55,
                                "relevance": 0.72, "freshness": 0.9,
                                "verified": False, "evidence_type": "web_snippet",
                                "provenance": url, "local_knowledge": False,
                                "external_llm_synthesis": False,
                            })

            if evidence:
                logger.info(
                    "[KnowledgeBrain] Added %d cited web evidence record(s); "
                    "unverified snippets were not learned automatically.",
                    len(evidence),
                )
            return evidence

        except Exception:
            logger.exception("[KnowledgeBrain] Web evidence search failed")
            return []

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
        """Compose a user-facing answer deterministically, never with an LLM."""
        cached_item = next(
            (item for item in (results or []) if isinstance(item, dict) and item.get("cached_answer")),
            None,
        )
        if cached_item:
            logger.info("[KnowledgeBrain] Returning cached local answer without recomposition.")
            return str(cached_item.get("content") or "")

        valid = [
            item for item in (results or [])
            if isinstance(item, dict)
            and str(item.get("content", "")).strip()
            and not self._is_bad_knowledge_content(item.get("content", ""))
        ]
        if not valid:
            return "I couldn't find reliable information in ARIA's connected knowledge sources."

        answer = self.answer_composer.compose(question, valid)
        if answer and not self._is_bad_knowledge_content(answer):
            logger.info(
                "[KnowledgeBrain] Answer composed locally from %d evidence record(s); "
                "external LLM formatting/synthesis disabled.",
                len(valid),
            )
            try:
                if self._is_ordinary_knowledge_query(question):
                    await asyncio.to_thread(self._save_local_answer_cache, question, answer, valid)
            except Exception:
                logger.exception("[KnowledgeBrain] Could not cache composed local answer.")
            return answer
        return "I found records but could not safely compose a reliable answer from them."

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
        # Strict local-first policy:
        # ordinary knowledge questions are answered only from the local
        # corpus/cache. Do not silently fall back to a live web/API search.
        # Explicit online-search commands are handled by their own route.
        # -----------------------------------------------------

        if not results:
            logger.info(
                "[KnowledgeManager] No local evidence found; returning a clean "
                "local-corpus miss instead of invoking online search or memory fallback."
            )
            return (
                "I don't have reliable information about this topic in ARIA's "
                "local knowledge database yet. No external knowledge API was "
                "called. The topic will be answerable once its dataset or "
                "source-backed article has been imported into the local corpus."
            )

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
