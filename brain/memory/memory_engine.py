import re
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any

logger = logging.getLogger("aria")

SCHEMA_VERSION = 2


class MemoryEngine:

    def __init__(self, mongo_db, llm_router=None):
        self.db = mongo_db
        self.llm_router = llm_router

        self.memory_col = (
            mongo_db["personal_memory"]
            if mongo_db is not None else None
        )
        self.profile_col = (
            mongo_db["user_profile"]
            if mongo_db is not None else None
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
                    "importance": "high",
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
                    "importance": "high",
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
                "importance": "high",
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
                    "importance": "high",
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
                "importance": "medium",
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
                "importance": "medium",
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
                    "importance": "low",
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
                    "importance": "medium",
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

        now = datetime.now(
            timezone.utc
        ).isoformat()

        if memory.get("is_list"):

            stored = []

            for item in value:

                if not self._validate_value(item):
                    continue

                await self.memory_col.update_one(
                    {
                        "key": key,
                        "value": item
                    },
                    {
                        "$set": {
                            "key": key,
                            "value": item,
                            "category": memory["category"],
                            "memory_type": memory["memory_type"],
                            "importance": memory["importance"],
                            "confidence": 1.0,
                            "source": "deterministic",
                            "schema_version": SCHEMA_VERSION,
                            "updated_at": now
                        },
                        "$setOnInsert": {
                            "first_seen": now,
                            "last_used": now
                        }
                    },
                    upsert=True
                )

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

        action = "stored"

        if existing:
            if str(existing.get("value")) != str(value):
                action = "update"

        await self.memory_col.update_one(
            {"key": key},
            {
                "$set": {
                    "key": key,
                    "value": str(value),
                    "category": memory["category"],
                    "memory_type": memory["memory_type"],
                    "importance": memory["importance"],
                    "confidence": 1.0,
                    "source": "deterministic",
                    "schema_version": SCHEMA_VERSION,
                    "updated_at": now
                },
                "$setOnInsert": {
                    "first_seen": now,
                    "last_used": now
                }
            },
            upsert=True
        )

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

        memory = self._extract_memory(
            user_text
        )

        if not memory:
            return {"success": False}

        return await self._store_extracted_memory(
            memory
        )

    # =========================================================
    # MEMORY RETRIEVAL
    # =========================================================

    async def get_relevant_memories(
        self,
        query: str
    ) -> list[dict]:

        if self.memory_col is None:
            return []

        try:

            lower = query.lower().strip()

            filter_query = None

            # Identity
            if re.search(
                r"\b(?:what(?:'s| is) my name|who am i)\b",
                lower
            ):
                filter_query = {
                    "key": "name"
                }

            elif "preferred name" in lower:
                filter_query = {
                    "key": "preferred_name"
                }

            # Birthday
            elif any(
                token in lower
                for token in (
                    "birthday",
                    "date of birth",
                    "dob",
                    "born"
                )
            ):
                filter_query = {
                    "key": "birthday"
                }

            # Study
            elif any(
                token in lower
                for token in (
                    "what do i study",
                    "what am i studying",
                    "field of study"
                )
            ):
                filter_query = {
                    "key": "field_of_study"
                }

            # Likes
            elif any(
                token in lower
                for token in (
                    "what do i like",
                    "things i like",
                    "my likes"
                )
            ):
                filter_query = {
                    "key": "user_likes"
                }

            # Favorites
            else:

                match = re.search(
                    r"(?:what(?:'s| is)|remember|recall)\s+(?:my\s+)?([a-zA-Z0-9\s]+)",
                    lower
                )

                if match:
                    subject = match.group(1).strip()
                    target_key = self._normalize_key(subject)
                    filter_query = {"key": target_key}

                elif any(
                    k in lower
                    for k in (
                        "like",
                        "preference",
                        "favorite",
                        "favourite",
                        "love",
                        "prefer"
                    )
                ):
                    filter_query = {"category": "preference"}

            if filter_query is None:
                return []

            cursor = self.memory_col.find(filter_query).limit(10)
            memories = await cursor.to_list(length=10)

            if not memories:
                return []

            now_iso = datetime.now(timezone.utc).isoformat()
            matched_ids = [m.get("_id") for m in memories if m.get("_id")]

            if matched_ids:
                await self.memory_col.update_many(
                    {"_id": {"$in": matched_ids}},
                    {"$set": {"last_used": now_iso}}
                )

            structured_results = []

            for m in memories:

                key = m.get("key")
                value = m.get("value")

                if not key or not value:
                    continue

                score = 0.98 if filter_query and m.get("key") == filter_query.get("key") else 0.85

                structured_results.append({
                    "key": key,
                    "value": value,
                    "category": m.get("category", "general"),
                    "memory_type": m.get("memory_type", "fact"),
                    "importance": m.get("importance", "medium"),
                    "confidence": m.get("confidence", 1.0),
                    "retrieval_score": score,
                    "updated_at": m.get("updated_at")
                })

            return structured_results

        except Exception:
            logger.exception("[Memory Retrieval Error]")
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
