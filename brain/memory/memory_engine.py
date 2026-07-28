import os
import re
import logging
from datetime import datetime, timezone

logger = logging.getLogger("aria")
SCHEMA_VERSION = 1

class MemoryEngine:
    def __init__(self, mongo_db):
        self.db = mongo_db
        self.memory_col = mongo_db["personal_memory"] if mongo_db is not None else None
        self.profile_col = mongo_db["user_profile"] if mongo_db is not None else None

    async def initialize_indexes(self):
        """Creates composite and unique indexes safely without conflicting with multi-item preferences."""
        if self.memory_col is not None:
            try:
                # Unique compound index to allow multiple values per key (like user_likes) while preventing exact duplicates
                await self.memory_col.create_index([("key", 1), ("value", 1)], unique=True, sparse=True)
                # Unique single-field index for singular keys (like birthday)
                await self.memory_col.create_index("key", unique=True, partialFilterExpression={"value": {"$type": "string"}})
                await self.memory_col.create_index("category")
                await self.memory_col.create_index("memory_type")
                await self.memory_col.create_index("updated_at")
                logger.info("[MemoryEngine] Successfully initialized composite and singular MongoDB indexes.")
            except Exception as e:
                logger.warning("[MemoryEngine] Index creation note: %s", e)

    async def get_profile(self) -> dict:
        """Retrieve the master user profile from MongoDB."""
        if self.profile_col is None:
            logger.warning("[MemoryEngine] user_profile collection not configured.")
            return {}

        try:
            profile = await self.profile_col.find_one({})

            if not profile:
                logger.info("[MemoryEngine] No profile document found.")
                return {}

            profile.pop("_id", None)

            logger.info(
                "[MemoryEngine] Loaded user profile with fields: %s",
                list(profile.keys())
            )

            return profile

        except Exception:
            logger.exception("[MemoryEngine] Failed to load user profile.")
            return {}

    def _should_extract(self, text: str) -> bool:
        """Filters out non-fact statements and strict privacy identifiers (Aadhaar, RRN, MyNumber, PAN)."""
        aadhaar_pattern = r'\b\d{4}\s?\d{4}\s?\d{4}\b'
        pan_pattern = r'[A-Z]{5}[0-9]{4}[A-Z]{1}'
        if re.search(aadhaar_pattern, text) or re.search(pan_pattern, text):
            return False

        lower = text.lower().strip()
        skip_phrases = ["hi", "hello", "hey", "thanks", "thank you", "good morning", "good evening", "bye"]
        if lower in skip_phrases or any(lower.startswith(p) for p in ["what's", "what is", "how ", "where ", "who "]):
            if not any(k in lower for k in ["my favorite", "my favourite", "i prefer", "i like"]):
                return False

        if bool(re.match(r'^[\d\+\-\*\/\.\(\)\s]+$', text)):
            return False

        return True

    def _normalize(self, value: str) -> str:
        """Normalizes extracted text values by stripping punctuation and collapsing whitespace."""
        cleaned = value.lower().strip()
        cleaned = re.sub(r'[^\w\s]', '', cleaned)
        cleaned = re.sub(r'\s+', ' ', cleaned)
        return cleaned

    def _validate_value(self, value: str) -> bool:
        """Rejects meaningless values like 'it', 'that', 'something', or empty strings."""
        invalid_tokens = {"it", "that", "something", "this", "everything", "nothing", ""}
        cleaned = self._normalize(value)
        if len(cleaned) < 2 or cleaned in invalid_tokens:
            return False
        return True

    def _parse_preference_items(self, text_segment: str) -> list[str]:
        """Splits coordinated lists like 'football and cricket' or 'football, cricket, chess' into distinct items."""
        normalized = re.sub(r'\band\b', ',', text_segment)
        raw_items = [self._normalize(item) for item in normalized.split(',')]
        return [item for item in raw_items if self._validate_value(item)]

    def _normalize_key(self, subject: str) -> str:
        """Creates a standardized storage key from a subject string safely avoiding duplicate prefixes."""
        cleaned = self._normalize(subject)
        cleaned = cleaned.replace("favourite", "favorite").strip()
        cleaned = re.sub(r"^favorite\s+", "", cleaned).strip()
        return f"favorite_{cleaned.replace(' ', '_')}"

    async def deterministic_extract_and_store(self, user_text: str):
        """Extracts structured memories deterministically with duplicate protection via composite keys."""
        if self.memory_col is None or not self._should_extract(user_text):
            return

        lower = user_text.lower().strip()
        key, value, category, memory_type, importance = None, None, "preference", "preference", "medium"
        is_list_accumulate = False
        extracted_items = []

        fav_match = re.search(r'(?:my )?favou?rite\s+([a-zA-Z0-9\s]+?)\s+is\s+([a-zA-Z0-9\s]+)', lower)
        rev_fav_match = re.search(r'([a-zA-Z0-9\s]+?)\s+is\s+my\s+favou?rite\s+([a-zA-Z0-9\s]+)', lower)
        pref_match = re.search(r'i\s+(?:prefer|like|love)\s+([a-zA-Z0-9\s,and]+)', lower)

        if fav_match:
            subj, val = fav_match.groups()
            key = self._normalize_key(subj)
            value = self._normalize(val)
            category = "preference"
            memory_type = "preference"
            importance = "medium"
        elif rev_fav_match:
            val, subj = rev_fav_match.groups()
            key = self._normalize_key(subj)
            value = self._normalize(val)
            category = "preference"
            memory_type = "preference"
            importance = "medium"
        elif pref_match:
            key = "user_likes"
            extracted_items = self._parse_preference_items(pref_match.group(1))
            category = "preference"
            memory_type = "preference"
            importance = "low"
            is_list_accumulate = True
        elif "birthday" in lower:
            match = re.search(r"birthday\s+is\s+(.+)", lower)
            if match:
                key = "birthday"
                value = match.group(1).strip()
                category = "personal"
                memory_type = "fact"
                importance = "high"

        now_iso = datetime.now(timezone.utc).isoformat()

        if is_list_accumulate and extracted_items:
            for item in extracted_items:
                try:
                    await self.memory_col.update_one(
                        {"key": key, "value": item},
                        {
                            "$set": {
                                "key": key,
                                "value": item,
                                "category": category,
                                "memory_type": memory_type,
                                "importance": importance,
                                "confidence": 1.0,
                                "source": "regex",
                                "schema_version": SCHEMA_VERSION,
                                "updated_at": now_iso
                            },
                            "$setOnInsert": {
                                "first_seen": now_iso,
                                "last_used": now_iso
                            }
                        },
                        upsert=True
                    )
                    logger.info("[MemoryEngine] Stored list item — Key: %s | Value: %s", key, item)
                except Exception:
                    pass

        elif key and value and self._validate_value(value):
            await self.memory_col.update_one(
                {"key": key},
                {
                    "$set": {
                        "key": key,
                        "value": value,
                        "category": category,
                        "memory_type": memory_type,
                        "importance": importance,
                        "confidence": 1.0,
                        "source": "regex",
                        "schema_version": SCHEMA_VERSION,
                        "updated_at": now_iso
                    },
                    "$setOnInsert": {
                        "first_seen": now_iso,
                        "last_used": now_iso
                    }
                },
                upsert=True
            )
            logger.info("[MemoryEngine] Stored singular memory — Key: %s | Value: %s", key, value)

    async def get_relevant_memories(self, query: str) -> list[dict]:
        """Query-aware retrieval with exact key targeting for preferences and birthdays."""
        if self.memory_col is None:
            return []
        try:
            lower_q = query.lower()
            filter_query = None

            if any(k in lower_q for k in ["birthday", "born", "dob", "date of birth"]):
                filter_query = {"key": "birthday"}
            else:
                match = re.search(r'(?:what\'s|what is|recall|remember)\s+(?:my\s+)?([a-zA-Z0-9\s]+)', lower_q)
                if match:
                    subject = match.group(1).strip()
                    target_key = self._normalize_key(subject)
                    filter_query = {"key": target_key}
                else:
                    if any(k in lower_q for k in ["like", "preference", "favorite", "favourite", "love", "prefer"]):
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

    async def process_and_store(self, user_text: str) -> dict:
        """Wrapper method for storing memories and returning structured result status."""
        if self.memory_col is None or not self._should_extract(user_text):
            return {"success": False}

        lower = user_text.lower().strip()
        key, value, category, memory_type, importance = None, None, "preference", "preference", "medium"
        is_list_accumulate = False
        extracted_items = []

        fav_match = re.search(r'(?:my )?favou?rite\s+([a-zA-Z0-9\s]+?)\s+is\s+([a-zA-Z0-9\s]+)', lower)
        rev_fav_match = re.search(r'([a-zA-Z0-9\s]+?)\s+is\s+my\s+favou?rite\s+([a-zA-Z0-9\s]+)', lower)
        pref_match = re.search(r'i\s+(?:prefer|like|love)\s+([a-zA-Z0-9\s,and]+)', lower)

        action_type = "stored"

        if fav_match:
            subj, val = fav_match.groups()
            key = self._normalize_key(subj)
            value = self._normalize(val)
            category = "preference"
            memory_type = "preference"
            importance = "medium"
        elif rev_fav_match:
            val, subj = rev_fav_match.groups()
            key = self._normalize_key(subj)
            value = self._normalize(val)
            category = "preference"
            memory_type = "preference"
            importance = "medium"
        elif pref_match:
            key = "user_likes"
            extracted_items = self._parse_preference_items(pref_match.group(1))
            category = "preference"
            memory_type = "preference"
            importance = "low"
            is_list_accumulate = True
        elif "birthday" in lower:
            match = re.search(r"birthday\s+is\s+(.+)", lower)
            if match:
                key = "birthday"
                value = match.group(1).strip()
                category = "personal"
                memory_type = "fact"
                importance = "high"

        now_iso = datetime.now(timezone.utc).isoformat()

        if key:
            existing = await self.memory_col.find_one({"key": key})
            if existing and existing.get("value") != value:
                action_type = "update"

        if is_list_accumulate and extracted_items:
            for item in extracted_items:
                try:
                    await self.memory_col.update_one(
                        {"key": key, "value": item},
                        {
                            "$set": {
                                "key": key,
                                "value": item,
                                "category": category,
                                "memory_type": memory_type,
                                "importance": importance,
                                "confidence": 1.0,
                                "source": "regex",
                                "schema_version": SCHEMA_VERSION,
                                "updated_at": now_iso
                            },
                            "$setOnInsert": {
                                "first_seen": now_iso,
                                "last_used": now_iso
                            }
                        },
                        upsert=True
                    )
                except Exception:
                    pass
            return {"success": True, "key": key, "value": ", ".join(extracted_items), "action": action_type}

        elif key and value and self._validate_value(value):
            await self.memory_col.update_one(
                {"key": key},
                {
                    "$set": {
                        "key": key,
                        "value": value,
                        "category": category,
                        "memory_type": memory_type,
                        "importance": importance,
                        "confidence": 1.0,
                        "source": "regex",
                        "schema_version": SCHEMA_VERSION,
                        "updated_at": now_iso
                    },
                    "$setOnInsert": {
                        "first_seen": now_iso,
                        "last_used": now_iso
                    }
                },
                upsert=True
            )
            return {"success": True, "key": key, "value": value, "action": action_type}

        return {"success": False}

    async def retrieve(self, query: str) -> list[dict]:
        """Wrapper method for retrieving relevant memories."""
        return await self.get_relevant_memories(query)

    async def delete_memory(self, query_or_key: str) -> bool:
        """Deletes a memory by parsing subject keys or falling back to regex matching."""
        if self.memory_col is None:
            return False

        try:
            cleaned = query_or_key.lower().strip()
            cleaned = re.sub(r"^(forget|delete|clear|remove)\s+", "", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"\bmy\b", "", cleaned, flags=re.IGNORECASE).strip()

            target_key = self._normalize_key(cleaned) if cleaned else ""

            if target_key:
                res = await self.memory_col.delete_one({"key": target_key})
                if res.deleted_count > 0:
                    return True

            res_direct = await self.memory_col.delete_one({"key": query_or_key})
            if res_direct.deleted_count > 0:
                return True

            res_regex = await self.memory_col.delete_one({"key": {"$regex": cleaned, "$options": "i"}})
            if res_regex.deleted_count > 0:
                return True

            return False
        except Exception:
            logger.exception("[MemoryEngine Delete Error]")
            return False