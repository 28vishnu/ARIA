import logging
from typing import List, Dict, Optional, Any
from datetime import datetime
from uuid import uuid4
import asyncio
import re

try:
    from brain.embeddings import get_embedding
except Exception:
    get_embedding = None

logger = logging.getLogger("aria")


class KnowledgeDatabase:

    # MongoDB's BSON document limit is 16 MiB. Keep knowledge records
    # comfortably below that limit because updates, indexes, and metadata
    # can add overhead. Large source documents belong in the document/vector
    # ingestion pipeline, not in one Mongo knowledge record.
    MAX_CONTENT_CHARS = 1_000_000
    MAX_TITLE_CHARS = 500
    MAX_METADATA_CHARS = 64_000
    MAX_HISTORY_ITEMS = 20
    MAX_HISTORY_CONTENT_CHARS = 2_000
    MAX_EMBEDDING_TEXT_CHARS = 20_000

    def __init__(
        self,
        mongo_collection=None,
        vector_db=None,
    ):

        self.collection = mongo_collection
        self.vector_db = vector_db

    @classmethod
    def _safe_text(cls, value, limit):
        text = str(value or "").strip()
        if len(text) <= limit:
            return text
        logger.warning(
            "[KnowledgeDB] Truncating oversized text from %d to %d characters.",
            len(text),
            limit,
        )
        return text[:limit] + "\n[TRUNCATED BY KNOWLEDGE DATABASE SAFETY LIMIT]"

    @classmethod
    def _compact_value(cls, value, depth=0):
        if depth > 3:
            return cls._safe_text(value, 4000)
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if isinstance(value, str):
            return cls._safe_text(value, 4000)
        if isinstance(value, dict):
            out = {}
            for i, (key, item) in enumerate(value.items()):
                if i >= 40:
                    out["_truncated_items"] = len(value) - 40
                    break
                out[cls._safe_text(key, 200)] = cls._compact_value(item, depth + 1)
            return out
        if isinstance(value, (list, tuple, set)):
            items = list(value)
            out = [cls._compact_value(item, depth + 1) for item in items[:40]]
            if len(items) > 40:
                out.append(f"[TRUNCATED {len(items) - 40} ITEMS]")
            return out
        return cls._safe_text(value, 4000)

    @classmethod
    def _safe_metadata(cls, metadata):
        if not isinstance(metadata, dict):
            return {}
        compact = cls._compact_value(metadata)
        # Metadata itself is bounded independently from content.
        text = str(compact)
        if len(text) <= cls.MAX_METADATA_CHARS:
            return compact
        return {
            "summary": cls._safe_text(
                text,
                cls.MAX_METADATA_CHARS,
            )
        }

    @classmethod
    def _safe_update_data(cls, data):
        if not isinstance(data, dict):
            return {}
        out = {}
        for key, value in data.items():
            if key in {"_id", "history"}:
                continue
            if key == "content":
                out[key] = cls._safe_text(value, cls.MAX_CONTENT_CHARS)
            elif key == "title":
                out[key] = cls._safe_text(value, cls.MAX_TITLE_CHARS)
            elif key == "summary":
                out[key] = cls._safe_text(value, 1000)
            elif key == "metadata":
                out[key] = cls._safe_metadata(value)
            else:
                out[key] = cls._compact_value(value)
        return out

    ############################################################
    # Store Knowledge
    ############################################################

    @staticmethod
    def _is_rejected_learning_payload(title, content) -> bool:
        """Reject infrastructure errors and serialized chat wrappers as facts."""
        text = str(content or "").strip().lower()
        title_text = str(title or "").strip().lower()
        failure_starts = (
            "i'm temporarily unable to reach",
            "i’m temporarily unable to reach",
            "i am temporarily unable to reach",
            "i couldn't reach the language model",
            "i could not reach the language model",
            "all available llm providers failed",
            "language models are unavailable",
            "please try again in a few seconds",
            "service unavailable",
            "internal server error",
        )
        if text.startswith(failure_starts):
            return True
        if text.startswith("query:") and "answer:" in text:
            return True
        if title_text.startswith("query ") and "answer" in title_text and text.startswith("query:"):
            return True
        return False

    async def detect_duplicate(
        self,
        title: str,
        content: str,
    ) -> Optional[Dict[str, Any]]:
        if self.collection is None:
            return None

        # Check exact content match or title match for duplicate detection
        doc = await self.collection.find_one({"content": content})
        if doc:
            return doc

        doc_title = await self.collection.find_one({"title": title})
        if doc_title:
            return doc_title

        return None

    async def store_embedding(
        self,
        knowledge_id: str,
        embedding: list,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        if self.vector_db is None or not embedding:
            return

        meta = metadata or {}
        self.vector_db.add(
            ids=[knowledge_id],
            embeddings=[embedding],
            metadatas=[meta],
        )

    async def store(
        self,
        title,
        content,
        source="conversation",
        metadata=None,
        embedding=None,
    ):
        title = self._safe_text(title, self.MAX_TITLE_CHARS)
        content = self._safe_text(content, self.MAX_CONTENT_CHARS)
        source = self._safe_text(source, 200)
        metadata = self._safe_metadata(metadata)

        # Provider/assistant "success" records are generated outputs, not trusted
        # source material. Keep them out of the factual knowledge brain.
        if source.strip().lower() in {"success", "assistant_response", "llm_response"}:
            logger.warning(
                "[KnowledgeDB] Rejected generated response from source=%s",
                source,
            )
            return None

        if self._is_rejected_learning_payload(title, content):
            logger.warning(
                "[KnowledgeDB] Rejected failure/wrapper payload; it was not stored as knowledge."
            )
            return None

        # A completed Q&A turn can be sent here with source="conversation".
        # It must remain in conversation history instead of becoming a factual
        # record (which can later outrank real source-backed knowledge).
        source_name = source.strip().lower()
        lower_content = content.strip().lower()
        starts_as_question = bool(re.match(
            r"^(?:what(?:'s| is| are| was| were)?|who(?:'s| is| are)?|"
            r"why(?: is| are| does| do)?|how(?: is| are| does| do)?|"
            r"explain|define|describe|difference between)\b",
            lower_content,
        ))
        has_source_trailer = bool(re.search(
            r"\bSources?:\s*https?://|https?://[^\s]+",
            lower_content,
        ))
        if source_name in {"conversation", "chat", "user_conversation"} and (
            (starts_as_question and len(content) > 180)
            or (starts_as_question and has_source_trailer)
        ):
            logger.warning(
                "[KnowledgeDB] Rejected mixed question/answer conversation as factual knowledge."
            )
            return None

        # 2. Duplicate Detection
        existing = await self.detect_duplicate(title, content)
        if existing:
            await self.increase_confidence(existing["_id"])
            return existing

        record = {

            "_id": str(uuid4()),

            "title": title,

            "content": content,

            "summary": content[:250],

            "source": source,

            "metadata": metadata,

            "importance": 50,

            "confidence": 0.60,  # 3. Confidence Learning starting point

            "entities": [],

            "relationships": [],

            "topics": [],

            "history": [],

            "active": True,

            "created_at": datetime.utcnow(),

            "updated_at": datetime.utcnow(),

            "access_count": 0,

            # Retrieval / learning metadata
            "retrieval_count": 0,
            "last_accessed_at": None,

            # Knowledge quality / provenance
            "verification_status": "unverified",
            "source_quality": 0.5,

            # Learning state
            "successful_uses": 0,
            "failed_uses": 0,

        }

        if self.collection is not None:

            await self.collection.update_one(
                {
                    "title": title,
                    "content": content,
                },
                {
                    "$set": record,
                },
                upsert=True,
            )

        # 1. Automatic local embedding storage
        # Generate an embedding automatically when the caller did not provide
        # one. This keeps knowledge ingestion local-first and removes the need
        # for an external embedding API.
        if embedding is None and get_embedding is not None:
            try:
                embedding = await asyncio.to_thread(
                    get_embedding,
                    f"{title}\n{content}"[: self.MAX_EMBEDDING_TEXT_CHARS],
                )
            except Exception:
                logger.exception(
                    "[KnowledgeDB] Local embedding generation failed."
                )
                embedding = None

        if embedding and self.vector_db is not None:
            await self.store_embedding(
                record["_id"],
                embedding,
                metadata={
                    "title": title,
                    "source": source,
                    "importance": record["importance"],
                    "confidence": record["confidence"],
                }
            )

        logger.info(
            "[KnowledgeDB] Stored knowledge: %s",
            title,
        )

        return record

    ############################################################
    # Search
    ############################################################

    async def search(
        self,
        query,
        limit=5,
    ):

        if self.collection is None:
            return []

        try:
            cursor = self.collection.find(
                {
                    "$text": {
                        "$search": query
                    },
                    "active": True,
                }
            ).limit(limit)
            results = await cursor.to_list(limit)
        except Exception:
            # Fallback if text index is not created yet
            cursor = self.collection.find(
                {
                    "content": {"$regex": query, "$options": "i"},
                    "active": True,
                }
            ).limit(limit)
            results = await cursor.to_list(limit)

        return await self.rank_results(results)

    ############################################################
    # Semantic Search
    ############################################################

    async def semantic_search(
        self,
        embedding,
        limit=5,
    ):

        if self.vector_db is None:
            return []

        return self.vector_db.query(
            query_embeddings=[embedding],
            n_results=limit,
        )

    ############################################################
    # Exists
    ############################################################

    async def exists(
        self,
        text,
    ):

        if self.collection is None:
            return False

        doc = await self.collection.find_one(
            {
                "content": text,
                "active": True,
            }
        )

        return doc is not None

    ############################################################
    # Update & Version History
    ############################################################

    async def update(
        self,
        knowledge_id,
        data,
    ):

        if self.collection is None:
            return

        safe_data = self._safe_update_data(data)
        if not safe_data:
            return

        doc = await self.collection.find_one({"_id": knowledge_id})
        if not doc:
            return

        # NEVER append the complete previous Mongo document to history.
        # That pattern caused documents to grow past MongoDB's 16 MiB BSON
        # limit when large knowledge records were merged repeatedly.
        history = doc.get("history", [])
        if not isinstance(history, list):
            history = []

        history_entry = {
            "content": self._safe_text(
                doc.get("content", ""),
                self.MAX_HISTORY_CONTENT_CHARS,
            ),
            "title": self._safe_text(
                doc.get("title", ""),
                self.MAX_TITLE_CHARS,
            ),
            "source": self._safe_text(
                doc.get("source", ""),
                200,
            ),
            "confidence": doc.get("confidence", 0.60),
            "updated_at": datetime.utcnow(),
            "updated_by": "learning_engine",
        }

        history = (history + [history_entry])[-self.MAX_HISTORY_ITEMS:]

        safe_data["updated_at"] = datetime.utcnow()
        safe_data["history"] = history

        await self.collection.update_one(
            {"_id": knowledge_id},
            {"$set": safe_data},
        )

    ############################################################
    # Confidence Learning
    ############################################################

    async def increase_confidence(self, knowledge_id: str):
        if self.collection is None:
            return
        doc = await self.collection.find_one({"_id": knowledge_id})
        if doc:
            new_conf = min(1.0, doc.get("confidence", 0.60) + 0.05)
            await self.update(knowledge_id, {"confidence": new_conf})

    async def decrease_confidence(self, knowledge_id: str):
        if self.collection is None:
            return
        doc = await self.collection.find_one({"_id": knowledge_id})
        if doc:
            new_conf = max(0.0, doc.get("confidence", 0.60) - 0.10)
            await self.update(knowledge_id, {"confidence": new_conf})

    ############################################################
    # Increment Access
    ############################################################

    async def increment_access(
        self,
        knowledge_id,
    ):

        if self.collection is None:
            return

        await self.collection.update_one(
            {
                "_id": knowledge_id
            },
            {
                "$inc": {
                    "access_count": 1
                }
            }
        )

    async def record_usage_result(
        self,
        knowledge_id: str,
        success: bool,
    ):
        """
        Record whether retrieved knowledge contributed
        successfully to an interaction.

        This is a learning signal, not an answer generator.
        """

        if self.collection is None:
            return

        field = (
            "successful_uses"
            if success
            else "failed_uses"
        )

        await self.collection.update_one(
            {"_id": knowledge_id},
            {
                "$inc": {
                    field: 1,
                },
                "$set": {
                    "last_accessed_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow(),
                },
            },
        )

    ############################################################
    # Knowledge Ranking
    ############################################################

    async def rank_results(
        self,
        results: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Rank retrieved knowledge using multiple quality signals.

        This method does NOT generate answers.
        It only determines which knowledge is most useful
        to the reasoning layer.
        """

        def safe_float(value, default=0.0):
            try:
                return float(value)
            except (TypeError, ValueError):
                return default

        def sort_key(item):
            confidence = safe_float(
                item.get("confidence", 0.60),
                0.60,
            )

            importance = safe_float(
                item.get("importance", 50),
                50,
            ) / 100.0

            access_count = safe_float(
                item.get("access_count", 0),
                0,
            )

            successful_uses = safe_float(
                item.get("successful_uses", 0),
                0,
            )

            failed_uses = safe_float(
                item.get("failed_uses", 0),
                0,
            )

            total_uses = successful_uses + failed_uses

            success_rate = (
                successful_uses / total_uses
                if total_uses > 0
                else 0.5
            )

            source_quality = safe_float(
                item.get("source_quality", 0.5),
                0.5,
            )

            verification_status = item.get(
                "verification_status",
                "unverified",
            )

            verification_bonus = {
                "verified": 1.0,
                "partially_verified": 0.7,
                "unverified": 0.4,
                "disputed": 0.1,
            }.get(
                verification_status,
                0.4,
            )

            updated = item.get(
                "updated_at",
                datetime.utcnow(),
            )

            if isinstance(updated, datetime):
                updated_ts = updated.timestamp()
            else:
                updated_ts = 0.0

            # Normalize recency so it has a small influence.
            now_ts = datetime.utcnow().timestamp()

            age_seconds = max(
                0.0,
                now_ts - updated_ts,
            )

            recency_score = 1.0 / (
                1.0 + age_seconds / 86400.0
            )

            return (
                confidence * 0.30
                + importance * 0.15
                + success_rate * 0.15
                + source_quality * 0.15
                + verification_bonus * 0.15
                + recency_score * 0.05
                + min(access_count / 100.0, 1.0) * 0.05
            )

        return sorted(
            results,
            key=sort_key,
            reverse=True,
        )

    ############################################################
    # Related Knowledge & Find Related
    ############################################################

    async def find_related(
        self,
        knowledge_id: str,
    ) -> List[Dict[str, Any]]:
        if self.collection is None:
            return []

        doc = await self.collection.find_one({"_id": knowledge_id})
        if not doc:
            return []

        entities = doc.get("entities", [])
        topics = doc.get("topics", [])

        cursor = self.collection.find(
            {
                "_id": {"$ne": knowledge_id},
                "active": True,
                "$or": [
                    {"entities": {"$in": entities}},
                    {"topics": {"$in": topics}},
                ]
            }
        ).limit(10)

        return await cursor.to_list(10)

    ############################################################
    # Search by Topic
    ############################################################

    async def search_by_topic(
        self,
        topic,
    ):

        if self.collection is None:
            return []

        cursor = self.collection.find(
            {
                "topics": topic,
                "active": True,
            }
        )

        return await cursor.to_list(100)

    ############################################################
    # Search by Entity
    ############################################################

    async def search_by_entity(
        self,
        entity,
    ):

        if self.collection is None:
            return []

        cursor = self.collection.find(
            {
                "entities": entity,
                "active": True,
            }
        )

        return await cursor.to_list(100)

    ############################################################
    # Related Knowledge (Legacy method kept)
    ############################################################

    async def related_knowledge(
        self,
        entity,
    ):

        if self.collection is None:
            return []

        cursor = self.collection.find(
            {
                "active": True,
                "$or": [
                    {
                        "entities": entity
                    },
                    {
                        "topics": entity
                    }
                ]
            }
        )

        return await cursor.to_list(20)

    ############################################################
    # Store Fact
    ############################################################

    async def store_fact(
        self,
        subject,
        fact,
    ):

        return await self.store(
            title=subject,
            content=fact,
            source="fact",
        )

    ############################################################
    # Forgetting / Archiving
    ############################################################

    async def archive(
        self,
        knowledge_id: str,
    ):
        if self.collection is None:
            return
        await self.update(knowledge_id, {"active": False})

    ############################################################
    # Snapshot
    ############################################################

    async def snapshot(self) -> Dict[str, Any]:
        if self.collection is None:
            return {"total_records": 0, "sources": {}, "topics": [], "average_confidence": 0.0}

        total_records = await self.collection.count_documents({"active": True})
        pipeline = [
            {"$match": {"active": True}},
            {"$group": {"_id": "$source", "count": {"$sum": 1}}}
        ]
        source_counts = {}
        async for doc in self.collection.aggregate(pipeline):
            source_counts[doc["_id"]] = doc["count"]

        # Calculate average confidence
        all_docs = await self.collection.find({"active": True}).to_list(1000)
        confidences = [d.get("confidence", 0.60) for d in all_docs]
        avg_conf = sum(confidences) / len(confidences) if confidences else 0.0

        return {
            "total_records": total_records,
            "sources": source_counts,
            "topics": [],
            "average_confidence": avg_conf,
        }

    ############################################################
    # Cleanup
    ############################################################

    async def cleanup(self):
        if self.collection is None:
            return

        # Archive low-confidence records
        await self.collection.update_many(
            {"confidence": {"$lt": 0.15}},
            {"$set": {"active": False}}
        )

    ############################################################
    # Search Pipeline / Unified Retrieval
    ############################################################

    async def retrieve(
        self,
        query: str,
        embedding: Optional[list] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        results = []

        # 1. Text Search
        text_results = await self.search(query, limit=limit)
        results.extend(text_results)

        # 2. Semantic Search
        # Generate the query embedding locally when the caller did not supply
        # one. This keeps retrieval independent of external embedding APIs.
        if embedding is None and get_embedding is not None:
            try:
                embedding = await asyncio.to_thread(
                    get_embedding,
                    query,
                )
            except Exception:
                logger.exception(
                    "[KnowledgeDB] Local query embedding generation failed."
                )
                embedding = None

        if embedding and self.vector_db is not None:
            semantic_res = await self.semantic_search(embedding, limit=limit)
            # Extract IDs from semantic search and fetch from mongo
            ids = []

            if isinstance(semantic_res, dict):
                raw_ids = semantic_res.get("ids")

                if isinstance(raw_ids, list):
                    if raw_ids and isinstance(
                        raw_ids[0],
                        list,
                    ):
                        ids = raw_ids[0]
                    else:
                        ids = raw_ids
            if ids and self.collection is not None:
                cursor = self.collection.find({"_id": {"$in": ids}, "active": True})
                sem_docs = await cursor.to_list(limit)
                results.extend(sem_docs)

        # 3. Topic / Entity Search
        entity_results = await self.search_by_entity(query)
        results.extend(entity_results)
        topic_results = await self.search_by_topic(query)
        results.extend(topic_results)

        # Deduplicate by _id
        seen = set()
        unique_results = []
        for r in results:
            rid = r.get("_id")
            if rid not in seen:
                seen.add(rid)
                unique_results.append(r)

        # Rank and limit
        ranked = await self.rank_results(
            unique_results
        )

        selected = ranked[:limit]

        # Record which knowledge was actually retrieved.
        for item in selected:
            knowledge_id = item.get("_id")

            if knowledge_id:
                try:
                    await self.increment_access(
                        knowledge_id
                    )
                except Exception:
                    logger.exception(
                        "[KnowledgeDB] Failed to update access metadata."
                    )

        return selected