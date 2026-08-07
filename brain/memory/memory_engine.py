import re
import logging
import traceback
from datetime import datetime, timezone
from typing import Optional, Dict, Any

logger = logging.getLogger("aria")

SCHEMA_VERSION = 3
MEMORY_SCHEMA_VERSION = 4

MEMORY_TYPES = {
    "personal",
    "preference",
    "goal",
    "project",
    "decision",
    "document",
    "fact",
    "schedule",
    "relationship",
    "skill",
    "event",
    "contact"
}

IMPORTANCE = {
    "low": 0.25,
    "medium": 0.5,
    "high": 0.75,
    "critical": 1.0
}


class MemoryEngine:

    def __init__(self, mongo_db, llm_router=None, working_memory=None):
        self.db = mongo_db
        self.llm_router = llm_router
        self.working_memory = working_memory if working_memory is not None else None

        self.memory_col = (
            mongo_db["personal_memory"]
            if mongo_db is not None else None
        )
        self.profile_col = (
            mongo_db["user_profile"]
            if mongo_db is not None else None
        )

    async def prefetch(self, route, session_id):
        """
        Prepare only the memory needed for this route.
        """
        return

    def _update_semantic_memory(
        self,
        memory,
    ):
        """
        Mirror important memories into the semantic graph.
        """

        if not self.working_memory:
            return

        semantic = self.working_memory.semantic()

        semantic.add_node(
            node_id=memory.get("key"),
            node_type=memory.get("category", "general"),
            value=str(memory.get("value")),
            metadata={
                "importance": memory.get("importance"),
                "confidence": memory.get("confidence"),
            },
        )

        logger.info(
            "[SemanticMemory] Mirrored memory '%s' into graph.",
            memory.get("key", "unknown"),
        )

    # =========================================================
    # DATABASE INITIALISATION
    # =========================================================

    async def initialize_indexes(self):
        if self.memory_col is None:
            return

        try:
            await self.memory_col.create_index("key")
            await self.memory_col.create_index("category")
            await self.memory_col.create_index("memory_type")
            await self.memory_col.create_index("updated_at")

            await self.memory_col.create_index(
                [("key", 1), ("value", 1)]
            )

            logger.info(
                "[MemoryEngine] MongoDB indexes initialized."
            )

        except Exception as exc:
            logger.warning(
                "[MemoryEngine] Index creation note: %s",
                exc
            )

    # =========================================================
    # PROFILE
    # =========================================================

    async def get_profile(self) -> dict:

        if self.profile_col is None:
            return {}

        try:
            profile = await self.profile_col.find_one({})

            if not profile:
                return {}

            profile.pop("_id", None)

            return profile

        except Exception:
            logger.exception(
                "[MemoryEngine] Failed to load profile."
            )
            return {}

    # =========================================================
    # NORMALISATION
    # =========================================================

    def _normalize(self, value: str) -> str:

        value = value.strip()

        value = re.sub(
            r"\s+",
            " ",
            value
        )

        return value.strip(" .,!?")

    def _normalize_key(self, subject: str) -> str:

        subject = subject.lower().strip()

        subject = subject.replace(
            "favourite",
            "favorite"
        )

        subject = re.sub(
            r"^favorite\s+",
            "",
            subject
        )

        subject = re.sub(
            r"[^a-z0-9\s_]",
            "",
            subject
        )

        subject = re.sub(
            r"\s+",
            "_",
            subject
        )

        return f"favorite_{subject}"

    def _validate_value(self, value: str) -> bool:

        if not value:
            return False

        cleaned = value.strip().lower()

        invalid = {
            "",
            "it",
            "that",
            "this",
            "something",
            "nothing",
            "everything"
        }

        return (
            len(cleaned) >= 2
            and cleaned not in invalid
        )

    # =========================================================
    # SHOULD MEMORY BE USED?
    # =========================================================

    def should_use_memory(self, query: str, intent: Optional[Any] = None) -> bool:
        """
        Determines whether memory retrieval is necessary for the given query and intent.
        Skips memory lookup for general knowledge, factual inquiries, historical facts, etc.
        """
        if not query:
            return False

        q = query.lower().strip()

        # If intent is clearly research, coding, web search, or general factual asking about external entities
        intent_name = getattr(intent, "name", "").lower() if intent else ""
        if intent_name in ("research", "coding", "web search", "tool"):
            return False

        # General factual prefixes that indicate external/world questions rather than personal history/preferences
        factual_starters = (
            "who founded",
            "who is",
            "who was",
            "what is",
            "what was",
            "where is",
            "where was",
            "when was",
            "how does",
            "how do",
            "explain",
            "compare",
            "calculate"
        )

        if q.startswith(factual_starters):
            return False

        return True

    # =========================================================
    # SHOULD THIS MESSAGE BE STORED?
    # =========================================================

    def _should_extract(self, text: str) -> bool:

        if not text:
            return False

        # Aadhaar
        if re.search(
            r"\b\d{4}\s?\d{4}\s?\d{4}\b",
            text
        ):
            return False

        # PAN
        if re.search(
            r"\b[A-Z]{5}[0-9]{4}[A-Z]\b",
            text.upper()
        ):
            return False

        lower = text.lower().strip()

        greetings = {
            "hi",
            "hello",
            "hey",
            "thanks",
            "thank you",
            "good morning",
            "good evening",
            "bye"
        }

        if lower in greetings:
            return False

        # Questions normally should not become memories.
        question_prefixes = (
            "what ",
            "what's ",
            "what is ",
            "who ",
            "where ",
            "when ",
            "why ",
            "how ",
            "do i ",
            "did i ",
            "can i "
        )

        if lower.startswith(question_prefixes):
            return False

        if re.fullmatch(
            r"[\d+\-*/.()\s]+",
            text
        ):
            return False

        return True

    # =========================================================
    # CENTRAL MEMORY EXTRACTOR
    # =========================================================

    def _extract_memory(
        self,
        text: str
    ) -> Optional[Dict[str, Any]]:

        original = text.strip()
        lower = original.lower().strip()

        # -----------------------------------------------------
        # 1. NAME
        # -----------------------------------------------------

        name_patterns = [
            r"\bmy name is\s+([a-zA-Z][a-zA-Z .'-]{1,80})",
            r"\bi am called\s+([a-zA-Z][a-zA-Z .'-]{1,80})",
            r"\bi'm called\s+([a-zA-Z][a-zA-Z .'-]{1,80})"
        ]

        for pattern in name_patterns:

            match = re.search(
                pattern,
                original,
                re.IGNORECASE
            )

            if match:

                value = self._clean_clause(
                    match.group(1)
                )

                return {
                    "key": "name",
                    "value": value,
                    "category": "identity",
                    "memory_type": "fact",
                    "importance": 0.75,
                    "is_list": False
                }

        # -----------------------------------------------------
        # 2. PREFERRED NAME
        # -----------------------------------------------------

        preferred_name_patterns = [
            r"\bcall me\s+([a-zA-Z][a-zA-Z .'-]{1,50})",
            r"\bi prefer to be called\s+([a-zA-Z][a-zA-Z .'-]{1,50})",
            r"\bpreferred name is\s+([a-zA-Z][a-zA-Z .'-]{1,50})"
        ]

        for pattern in preferred_name_patterns:

            match = re.search(
                pattern,
                original,
                re.IGNORECASE
            )

            if match:

                value = self._clean_clause(
                    match.group(1)
                )

                return {
                    "key": "preferred_name",
                    "value": value,
                    "category": "identity",
                    "memory_type": "preference",
                    "importance": 0.75,
                    "is_list": False
                }

        # -----------------------------------------------------
        # 3. ADDRESSING PREFERENCE
        # -----------------------------------------------------

        if re.search(
            r"\b(?:don't|do not)\s+call me\s+(?:by|with)\s+my name\b",
            lower
        ):

            return {
                "key": "address_by_name",
                "value": "false",
                "category": "interaction_preference",
                "memory_type": "preference",
                "importance": 0.75,
                "is_list": False
            }

        # -----------------------------------------------------
        # 4. BIRTHDAY
        # -----------------------------------------------------

        birthday_patterns = [
            r"\bmy birthday is\s+(.+)",
            r"\bmy date of birth is\s+(.+)",
            r"\bi was born on\s+(.+)"
        ]

        for pattern in birthday_patterns:

            match = re.search(
                pattern,
                original,
                re.IGNORECASE
            )

            if match:

                value = self._clean_clause(
                    match.group(1)
                )

                return {
                    "key": "birthday",
                    "value": value,
                    "category": "personal",
                    "memory_type": "fact",
                    "importance": 0.75,
                    "is_list": False
                }

        # -----------------------------------------------------
        # 5. FAVORITES
        # -----------------------------------------------------

        fav_match = re.search(
            r"\bmy favou?rite\s+"
            r"([a-zA-Z0-9 ]+?)\s+is\s+"
            r"([^,.!?]+)",
            original,
            re.IGNORECASE
        )

        if fav_match:

            subject = fav_match.group(1)

            value = self._clean_clause(
                fav_match.group(2)
            )

            return {
                "key": self._normalize_key(subject),
                "value": value,
                "category": "preference",
                "memory_type": "preference",
                "importance": 0.5,
                "is_list": False
            }

        # -----------------------------------------------------
        # 6. STUDY / EDUCATION
        # -----------------------------------------------------

        study_match = re.search(
            r"\bi (?:study|am studying)\s+([^,.!?]+)",
            original,
            re.IGNORECASE
        )

        if study_match:

            value = self._clean_clause(
                study_match.group(1)
            )

            return {
                "key": "field_of_study",
                "value": value,
                "category": "education",
                "memory_type": "fact",
                "importance": 0.5,
                "is_list": False
            }

        # -----------------------------------------------------
        # 7. GENERAL LIKES
        # -----------------------------------------------------

        like_match = re.search(
            r"\bi\s+(?:like|love)\s+([^.!?]+)",
            original,
            re.IGNORECASE
        )

        if like_match:

            segment = self._clean_clause(
                like_match.group(1)
            )

            items = self._parse_preference_items(
                segment
            )

            if items:

                return {
                    "key": "user_likes",
                    "value": items,
                    "category": "preference",
                    "memory_type": "preference",
                    "importance": 0.25,
                    "is_list": True
                }

        # -----------------------------------------------------
        # 8. GENERAL "I PREFER"
        # -----------------------------------------------------

        prefer_match = re.search(
            r"\bi prefer\s+([^.!?]+)",
            original,
            re.IGNORECASE
        )

        if prefer_match:

            segment = self._clean_clause(
                prefer_match.group(1)
            )

            # Don't store complex behavioural statements as user_likes.
            if not re.search(
                r"\b(?:but|don't|do not|call me|called)\b",
                segment,
                re.IGNORECASE
            ):

                return {
                    "key": "general_preference",
                    "value": segment,
                    "category": "interaction_preference",
                    "memory_type": "preference",
                    "importance": 0.5,
                    "is_list": False
                }

        return None

    # =========================================================
    # CLAUSE CLEANING
    # =========================================================

    def _clean_clause(
        self,
        value: str
    ) -> str:

        value = value.strip()

        # Stop extraction when a new clause begins.
        value = re.split(
            r"\s+(?:but|and\s+i|because|although|however)\s+",
            value,
            maxsplit=1,
            flags=re.IGNORECASE
        )[0]

        return self._normalize(value)

    # =========================================================
    # LIST PREFERENCES
    # =========================================================

    def _parse_preference_items(
        self,
        segment: str
    ) -> list[str]:

        segment = re.sub(
            r"\band\b",
            ",",
            segment,
            flags=re.IGNORECASE
        )

        items = []

        for raw in segment.split(","):

            item = self._normalize(raw)

            if self._validate_value(item):
                items.append(item)

        return items

    # =========================================================
    # MEMORY RECORD BUILDER
    # =========================================================

    def _build_memory_record(
        self,
        memory: Dict[str, Any]
    ):
        now = datetime.now(
            timezone.utc
        ).isoformat()

        imp = memory.get("importance", 0.5)
        if isinstance(imp, str):
            imp = {
                "low": 0.25,
                "medium": 0.5,
                "high": 0.75,
                "critical": 1.0,
            }.get(imp.lower(), 0.5)
        try:
            imp = float(imp)
        except (TypeError, ValueError):
            imp = 0.5

        return {

            "key": memory["key"],

            "value": memory["value"],

            "summary": memory.get(
                "summary",
                str(memory["value"])
            ),

            "category": memory.get(
                "category",
                "general"
            ),

            "memory_type": memory.get(
                "memory_type",
                "fact"
            ),

            "importance": imp,

            "confidence": memory.get(
                "confidence",
                1.0
            ),

            "source": memory.get(
                "source",
                "conversation"
            ),

            "entities": memory.get(
                "entities",
                []
            ),

            "relationships": memory.get(
                "relationships",
                []
            ),

            "topics": memory.get(
                "topics",
                []
            ),

            "aliases": memory.get(
                "aliases",
                []
            ),

            "tags": memory.get(
                "tags",
                []
            ),

            "embedding_id": memory.get(
                "embedding_id"
            ),

            "document_id": memory.get(
                "document_id"
            ),

            "created_at": now,

            "updated_at": now,

            "last_accessed": now,

            "access_count": 0,

            "schema_version": MEMORY_SCHEMA_VERSION
        }

    # =========================================================
    # STORE MEMORY
    # =========================================================

    async def _store_extracted_memory(
        self,
        memory: Dict[str, Any]
    ) -> dict:

        if self.memory_col is None:
            return {"success": False}

        key = memory["key"]
        value = memory["value"]

        imp_val = memory.get("importance", 0.5)
        if isinstance(imp_val, str):
            is_perm = imp_val in ("high", "critical")
        else:
            try:
                is_perm = float(imp_val) >= 0.75
            except (TypeError, ValueError):
                is_perm = False
        memory["is_permanent"] = is_perm

        if memory.get("is_list"):

            stored = []

            for item in value:

                if not self._validate_value(item):
                    continue

                item_memory = dict(memory)
                item_memory["value"] = item
                record = self._build_memory_record(item_memory)

                existing = await self.memory_col.find_one(
                    {
                        "key": key,
                        "value": item
                    }
                )

                if existing and existing.get("value") == item:
                    stored.append(item)
                    continue

                version = 1
                history = []

                if existing:
                    version = existing.get("version", 1) + 1
                    history = existing.get("history", [])
                    history.append({
                        "value": existing.get("value"),
                        "updated_at": existing.get("updated_at")
                    })
                    record["created_at"] = existing.get("created_at", record["created_at"])
                    record["access_count"] = existing.get("access_count", 0)

                record["version"] = version
                record["history"] = history
                record["is_permanent"] = memory["is_permanent"]

                await self.memory_col.update_one(
                    {
                        "key": key,
                        "value": item
                    },
                    {
                        "$set": record,
                        "$setOnInsert": {
                            "expires_at": None
                        }
                    },
                    upsert=True
                )

                self._update_semantic_memory(item_memory)

                stored.append(item)

            return {
                "success": bool(stored),
                "key": key,
                "value": ", ".join(stored),
                "action": "stored"
            }

        if not self._validate_value(str(value)):
            return {"success": False}

        existing = await self.memory_col.find_one(
            {"key": key}
        )

        if existing and str(existing.get("value")) == str(value):
            return {
                "success": True,
                "action": "already_exists",
                "key": key,
                "value": str(value),
            }

        record = self._build_memory_record(memory)

        action = "stored"
        version = 1
        history = []

        if existing:
            if str(existing.get("value")) != str(value):
                action = "update"
            version = existing.get("version", 1) + 1
            history = existing.get("history", [])
            history.append({
                "value": existing.get("value"),
                "updated_at": existing.get("updated_at")
            })
            record["created_at"] = existing.get("created_at", record["created_at"])
            record["access_count"] = existing.get("access_count", 0)

        record["version"] = version
        record["history"] = history
        record["is_permanent"] = memory["is_permanent"]

        await self.memory_col.update_one(
            {"key": key},
            {
                "$set": record,
                "$setOnInsert": {
                    "expires_at": None
                }
            },
            upsert=True
        )

        self._update_semantic_memory(memory)

        logger.info(
            "[MemoryEngine] Stored memory — Key: %s | Value: %s",
            key,
            value
        )

        return {
            "success": True,
            "key": key,
            "value": str(value),
            "action": action
        }

    # =========================================================
    # PUBLIC STORE METHODS
    # =========================================================

    async def deterministic_extract_and_store(
        self,
        user_text: str
    ):

        if (
            self.memory_col is None
            or not self._should_extract(user_text)
        ):
            return

        memory = self._extract_memory(
            user_text
        )

        if memory:
            await self._store_extracted_memory(
                memory
            )

    async def process_and_store(
        self,
        user_text: str
    ) -> dict:

        if (
            self.memory_col is None
            or not self._should_extract(user_text)
        ):
            return {"success": False}

        # ---------------------------------------------------------
        # LEVEL 1 — FAST DETERMINISTIC MEMORY
        # ---------------------------------------------------------

        memory = self._extract_memory(
            user_text
        )

        if memory:
            res = await self._store_extracted_memory(
                memory
            )
            if res.get("success"):
                if hasattr(self, "learning_engine") and self.learning_engine:
                    await self.learning_engine.learn_from_memory(memory)
            return res

        # ---------------------------------------------------------
        # LEVEL 2 — INTELLIGENT LLM MEMORY UNDERSTANDING
        # ---------------------------------------------------------

        if (
            self.llm_router is not None
            and hasattr(self.llm_router, "extract_memories")
        ):
            try:

                memories = await self.llm_router.extract_memories(
                    user_text
                )

                if memories:

                    stored_results = []

                    for extracted in memories:

                        memory_data = {
                            "key": extracted.get("key"),
                            "value": extracted.get("value"),
                            "category": extracted.get(
                                "category",
                                "general"
                            ),
                            "memory_type": extracted.get(
                                "memory_type",
                                "fact"
                            ),
                            "importance": extracted.get(
                                "importance",
                                0.5
                            ),
                            "is_list": False
                        }

                        if (
                            not memory_data["key"]
                            or not memory_data["value"]
                        ):
                            continue

                        result = await self._store_extracted_memory(
                            memory_data
                        )

                        if result.get("success"):
                            stored_results.append(result)
                            if hasattr(self, "learning_engine") and self.learning_engine:
                                await self.learning_engine.learn_from_memory(memory_data)

                    if stored_results:

                        logger.info(
                            "[MemoryEngine] Intelligent memory stored %d memories.",
                            len(stored_results)
                        )

                        return {
                            "success": True,
                            "action": "intelligent_store",
                            "memories": stored_results
                        }

            except Exception:
                logger.exception(
                    "[MemoryEngine] Intelligent memory extraction failed."
                )

        return {"success": False}

    # =========================================================
    # MEMORY RETRIEVAL
    # =========================================================

    def _calculate_score(
        self,
        memory,
        semantic_score
    ):

        importance = memory.get(
            "importance",
            0.5
        )

        # Convert string importance to numeric value
        if isinstance(importance, str):
            importance = {
                "low": 0.25,
                "medium": 0.5,
                "high": 0.75,
                "critical": 1.0,
            }.get(importance.lower(), 0.5)

        try:
            importance = float(importance)
        except (TypeError, ValueError):
            importance = 0.5

        confidence = memory.get(
            "confidence",
            1
        )

        accesses = memory.get(
            "access_count",
            0
        )

        # Cap the influence of access_count to prevent domination
        capped_accesses = min(accesses, 10)

        return (

            semantic_score

            +

            importance * 0.15

            +

            confidence * 5

            +

            capped_accesses * 0.08

        )

    async def get_relevant_memories(
        self,
        query: str,
        limit: int = 10
    ) -> list[dict]:
        """
        Retrieve memories relevant to natural-language queries.

        Retrieval strategy:
        1. Exact high-confidence memory patterns.
        2. Keyword scoring across stored personal memories.
        3. LLM-assisted semantic ranking when available.
        """

        if self.memory_col is None:
            return []

        try:
            lower = query.lower().strip()

            # =====================================================
            # LEVEL 1 — EXACT / HIGH-CONFIDENCE LOOKUPS
            # =====================================================

            filter_query = None

            if re.search(
                r"\b(?:what(?:'s| is) my name|who am i|do you know my name|tell me my name|remember my name|what's my name again|say my name)\b",
                lower
            ):
                filter_query = {"key": "name"}

            elif "preferred name" in lower:
                filter_query = {"key": "preferred_name"}

            elif any(
                token in lower
                for token in (
                    "birthday",
                    "date of birth",
                    "dob",
                    "when was i born"
                )
            ):
                filter_query = {"key": "birthday"}

            elif any(
                token in lower
                for token in (
                    "what do i study",
                    "what am i studying",
                    "field of study"
                )
            ):
                filter_query = {"key": "field_of_study"}

            elif any(
                token in lower
                for token in (
                    "what do i like",
                    "things i like",
                    "my likes"
                )
            ):
                filter_query = {"key": "user_likes"}

            # =====================================================
            # EXACT FAVORITE LOOKUP
            # =====================================================

            if filter_query is None:

                favorite_match = re.search(
                    r"(?:what(?:'s| is)|remember|recall)\s+"
                    r"(?:my\s+)?(?:favorite|favourite)\s+"
                    r"([a-zA-Z0-9\s]+)",
                    lower
                )

                if favorite_match:
                    subject = favorite_match.group(1).strip()

                    filter_query = {
                        "key": self._normalize_key(subject)
                    }

            # =====================================================
            # RETURN EXACT RESULTS IMMEDIATELY
            # =====================================================

            if filter_query is not None:

                cursor = self.memory_col.find(
                    filter_query
                ).limit(limit)

                memories = await cursor.to_list(
                    length=limit
                )

                if memories:

                    now_iso = datetime.now(
                        timezone.utc
                    ).isoformat()

                    matched_ids = [
                        m["_id"]
                        for m in memories
                        if m.get("_id")
                    ]

                    if matched_ids:
                        await self.memory_col.update_many(
                            {
                                "_id": {
                                    "$in": matched_ids
                                }
                            },
                            {
                                "$inc": {
                                    "access_count": 1
                                },
                                "$set": {
                                    "last_accessed": now_iso
                                }
                            }
                        )

                    return [
                        {
                            "key": m.get("key"),
                            "value": m.get("value"),
                            "category": m.get(
                                "category",
                                "general"
                            ),
                            "memory_type": m.get(
                                "memory_type",
                                "fact"
                            ),
                            "importance": m.get(
                                "importance",
                                0.5
                            ),
                            "confidence": m.get(
                                "confidence",
                                1.0
                            ),
                            "retrieval_score": 1.0,
                            "updated_at": m.get(
                                "updated_at"
                            )
                        }
                        for m in memories
                        if m.get("key") and m.get("value")
                    ]

            # =====================================================
            # LEVEL 2 — LOAD PERSONAL MEMORIES
            # =====================================================

            cursor = self.memory_col.find({
                "category": {
                    "$nin": [
                        "document",
                        "document_chunk"
                    ]
                }
            })

            all_memories = await cursor.to_list(
                length=200
            )

            if not all_memories:
                return []

            # =====================================================
            # QUERY NORMALISATION
            # =====================================================

            stop_words = {
                "what",
                "whats",
                "what's",
                "where",
                "when",
                "why",
                "how",
                "who",
                "which",
                "did",
                "does",
                "do",
                "am",
                "is",
                "are",
                "was",
                "were",
                "the",
                "a",
                "an",
                "my",
                "me",
                "i",
                "you",
                "your",
                "about",
                "know",
                "remember",
                "recall",
                "tell",
                "please"
            }

            query_words = {
                word
                for word in re.findall(
                    r"[a-zA-Z0-9]+",
                    lower
                )
                if len(word) > 1
                and word not in stop_words
            }

            # =====================================================
            # SEMANTIC ALIASES
            # =====================================================

            aliases = {
                "plan": {
                    "plan",
                    "planned",
                    "planning",
                    "goal",
                    "future",
                    "postgraduate",
                    "masters",
                    "master",
                    "education",
                    "study"
                },

                "future": {
                    "future",
                    "plan",
                    "planned",
                    "planning",
                    "goal",
                    "career",
                    "postgraduate"
                },

                "btech": {
                    "btech",
                    "degree",
                    "undergraduate",
                    "postgraduate",
                    "masters",
                    "education"
                },

                "master": {
                    "master",
                    "masters",
                    "postgraduate",
                    "degree",
                    "study"
                },

                "masters": {
                    "master",
                    "masters",
                    "postgraduate",
                    "degree",
                    "study"
                },

                "study": {
                    "study",
                    "education",
                    "degree",
                    "university",
                    "college",
                    "postgraduate"
                },

                "italy": {
                    "italy",
                    "europe",
                    "european"
                },

                "education": {
                    "education",
                    "study",
                    "degree",
                    "university",
                    "college"
                },

                "career": {
                    "career",
                    "job",
                    "work",
                    "future",
                    "goal",
                    "plan"
                },

                "preference": {
                    "preference",
                    "prefer",
                    "favorite",
                    "favourite",
                    "love",
                    "prefer"
                }
            }

            expanded_query_words = set(
                query_words
            )

            for word in list(query_words):

                if word in aliases:
                    expanded_query_words.update(
                        aliases[word]
                    )

            # =====================================================
            # SCORE STORED MEMORIES
            # =====================================================

            scored = []

            for memory in all_memories:

                key = str(
                    memory.get(
                        "key",
                        ""
                    )
                ).lower()

                value = str(
                    memory.get(
                        "value",
                        ""
                    )
                ).lower()

                category = str(
                    memory.get(
                        "category",
                        ""
                    )
                ).lower()

                memory_type = str(
                    memory.get(
                        "memory_type",
                        ""
                    )
                ).lower()

                searchable = (
                    key.replace("_", " ")
                    + " "
                    + value
                    + " "
                    + category
                    + " "
                    + memory_type
                )

                memory_words = set(
                    re.findall(
                        r"[a-zA-Z0-9]+",
                        searchable
                    )
                )

                semantic_score = 0.0

                # Direct word overlap
                direct_matches = (
                    query_words
                    & memory_words
                )

                semantic_score += len(
                    direct_matches
                ) * 3.0

                # Expanded semantic overlap
                semantic_matches = (
                    expanded_query_words
                    & memory_words
                )

                semantic_score += len(
                    semantic_matches
                ) * 1.5

                # Key matches are especially important
                key_words = set(
                    re.findall(
                        r"[a-zA-Z0-9]+",
                        key.replace("_", " ")
                    )
                )

                key_matches = (
                    expanded_query_words
                    & key_words
                )

                semantic_score += len(
                    key_matches
                ) * 2.5

                score = self._calculate_score(memory, semantic_score)

                if semantic_score > 0:

                    scored.append(
                        (
                            score,
                            memory
                        )
                    )

            scored.sort(
                key=lambda item: item[0],
                reverse=True
            )

            # =====================================================
            # LEVEL 3 — LLM SEMANTIC MEMORY SELECTION
            # =====================================================

            if (
                self.llm_router is not None
                and hasattr(
                    self.llm_router,
                    "select_relevant_memories"
                )
            ):

                try:

                    candidates = [
                        {
                            "key": m.get("key"),
                            "value": m.get("value"),
                            "category": m.get(
                                "category",
                                "general"
                            )
                        }
                        for m in all_memories
                        if m.get("key")
                        and m.get("value")
                    ]

                    selected_keys = (
                        await self.llm_router.select_relevant_memories(
                            query,
                            candidates
                        )
                    )

                    if selected_keys:

                        selected_key_set = set(
                            selected_keys
                        )

                        llm_selected = [
                            m
                            for m in all_memories
                            if m.get("key")
                            in selected_key_set
                        ]

                        # Merge LLM results with keyword results.
                        existing_keys = {
                            m.get("key")
                            for _, m in scored
                        }

                        for memory in llm_selected:

                            if (
                                memory.get("key")
                                not in existing_keys
                            ):
                                scored.append(
                                    (
                                        self._calculate_score(memory, 2.0),
                                        memory
                                    )
                                )

                except Exception:

                    logger.exception(
                        "[MemoryEngine] Semantic memory selection failed."
                    )

            # =====================================================
            # FINAL RESULTS
            # =====================================================

            if not scored:
                return []

            scored.sort(
                key=lambda item: item[0],
                reverse=True
            )

            final_memories = []
            seen_keys = set()

            for score, memory in scored:

                key = memory.get("key")
                value = memory.get("value")

                if not key or not value:
                    continue

                if key in seen_keys:
                    continue

                seen_keys.add(key)

                final_memories.append({
                    "key": key,
                    "value": value,
                    "category": memory.get(
                        "category",
                        "general"
                    ),
                    "memory_type": memory.get(
                        "memory_type",
                        "fact"
                    ),
                    "importance": memory.get(
                        "importance",
                        0.5
                    ),
                    "confidence": memory.get(
                        "confidence",
                        1.0
                    ),
                    "retrieval_score": round(
                        float(score),
                        3
                    ),
                    "updated_at": memory.get(
                        "updated_at"
                    )
                })

                if len(final_memories) >= limit:
                    break

            # Update access_count and last_accessed only for the top utilized/returned memory or cap updates
            returned_keys = [
                m["key"]
                for m in final_memories[:1]  # Increment access count only for the top matching memory to prevent over-inflation
            ]

            if returned_keys:

                await self.memory_col.update_many(
                    {
                        "key": {
                            "$in": returned_keys
                        }
                    },
                    {
                        "$inc": {
                            "access_count": 1
                        },
                        "$set": {
                            "last_accessed": datetime.now(
                                timezone.utc
                            ).isoformat()
                        }
                    }
                )

            logger.info(
                "[MemoryEngine] Retrieved %d relevant memories for query: %s",
                len(final_memories),
                query
            )

            return final_memories

        except Exception:

            logger.exception("[Memory Retrieval Error]")

            traceback.print_exc()

            return []

    async def retrieve(self, query: str) -> list[dict]:

        return await self.get_relevant_memories(query)

    # =========================================================
    # DELETE MEMORY
    # =========================================================

    async def delete_memory(
        self,
        query_or_key: str
    ) -> bool:

        if self.memory_col is None:
            return False

        try:

            cleaned = query_or_key.lower().strip()

            cleaned = re.sub(
                r"^(forget|delete|clear|remove)\s+",
                "",
                cleaned,
                flags=re.IGNORECASE
            )

            cleaned = re.sub(
                r"\bmy\b",
                "",
                cleaned,
                flags=re.IGNORECASE
            ).strip()

            target_key = (
                self._normalize_key(cleaned)
                if cleaned else ""
            )

            if target_key:
                res = await self.memory_col.delete_one(
                    {"key": target_key}
                )
                if res.deleted_count > 0:
                    return True

            res_direct = await self.memory_col.delete_one(
                {"key": query_or_key}
            )

            if res_direct.deleted_count > 0:
                return True

            res_regex = await self.memory_col.delete_one(
                {"key": {"$regex": cleaned, "$options": "i"}}
            )

            if res_regex.deleted_count > 0:
                return True

            return False

        except Exception:
            logger.exception("[MemoryEngine Delete Error]")
            return False

    # =========================================================
    # ADDITIONAL ROUTER METHODS
    # =========================================================

    async def store_chat(self, chat):
        return await self.process_and_store(chat)

    async def store_profile(self, profile):
        if self.profile_col is None:
            return

        await self.profile_col.update_one(
            {},
            {
                "$set": profile
            },
            upsert=True
        )

    async def update_memory(
        self,
        memory_id,
        data
    ):
        if self.memory_col is None:
            return False

        await self.memory_col.update_one(
            {
                "_id": memory_id
            },
            {
                "$set": data
            }
        )

        return True

    async def memory_exists(
        self,
        query
    ):
        if self.memory_col is None:
            return False

        memory = await self.memory_col.find_one(
            {
                "$or": [
                    {"key": query},
                    {"value": query}
                ]
            }
        )

        return memory is not None
