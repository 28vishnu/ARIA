import os
import re
import logging
from datetime import datetime, timezone

logger = logging.getLogger("aria")

class MemoryEngine:
    def __init__(self, mongo_db):
        self.db = mongo_db
        self.memory_col = mongo_db["personal_memory"] if mongo_db is not None else None

    async def initialize_indexes(self):
        """Creates indexes on startup to ensure high-performance retrieval as memories scale."""
        if self.memory_col is not None:
            try:
                await self.memory_col.create_index("key", unique=True)
                await self.memory_col.create_index("category")
                await self.memory_col.create_index("updated_at")
                logger.info("[MemoryEngine] Successfully initialized MongoDB indexes.")
            except Exception as e:
                logger.warning("[MemoryEngine] Index creation note: %s", e)

    def _should_extract(self, text: str) -> bool:
        """Filters non-fact statements and strict privacy identifiers (Aadhaar, RRN, MyNumber, PAN)."""
        aadhaar_pattern = r'\b\d{4}\s?\d{4}\s?\d{4}\b'
        pan_pattern = r'[A-Z]{5}[0-9]{4}[A-Z]{1}'
        if re.search(aadhaar_pattern, text) or re.search(pan_pattern, text):
            return False

        lower = text.lower().strip()
        skip_phrases = ["hi", "hello", "hey", "thanks", "thank you", "good morning", "good evening", "bye"]
        if lower in skip_phrases or any(lower.startswith(p) for p in ["what's", "what is", "how ", "where ", "who "]):
            if not any(k in lower for k in ["my name", "my favorite", "i prefer"]):
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

    async def deterministic_extract_and_store(self, user_text: str):
        """Extracts structured memories deterministically with validation, timestamps, and importance levels."""
        if self.memory_col is None or not self._should_extract(user_text):
            return

        lower = user_text.lower().strip()
        key, value, category, importance = None, None, "preference", "medium"
        is_list_accumulate = False

        fav_match = re.search(r'(?:my )?favorite\s+([a-zA-Z0-9\s]+?)\s+is\s+([a-zA-Z0-9\s]+)', lower)
        rev_fav_match = re.search(r'([a-zA-Z0-9\s]+?)\s+is\s+my\s+favorite\s+([a-zA-Z0-9\s]+)', lower)
        pref_match = re.search(r'i\s+(?:prefer|like|love)\s+([a-zA-Z0-9\s]+)', lower)

        if fav_match:
            subj, val = fav_match.groups()
            key = f"favorite_{self._normalize(subj)}"
            value = self._normalize(val)
            category = "preference"
            importance = "medium"
        elif rev_fav_match:
            val, subj = rev_fav_match.groups()
            key = f"favorite_{self._normalize(subj)}"
            value = self._normalize(val)
            category = "preference"
            importance = "medium"
        elif pref_match:
            key = "user_likes"
            value = self._normalize(pref_match.group(1))
            category = "preference"
            importance = "low"
            is_list_accumulate = True
        elif "birthday" in lower or "born on" in lower:
            key = "birthday"
            value = user_text
            category = "personal"
            importance = "high"
        elif "my name is" in lower or "i am" in lower:
            name_match = re.search(r'(?:my name is|i am)\s+([a-zA-Z\s]+)', lower)
            if name_match:
                key = "name"
                value = self._normalize(name_match.group(1))
                category = "personal"
                importance = "high"

        if key and value and self._validate_value(value):
            now_iso = datetime.now(timezone.utc).isoformat()
            
            if is_list_accumulate:
                await self.memory_col.update_one(
                    {"key": key},
                    {
                        "$addToSet": {"values": value},
                        "$set": {
                            "category": category, 
                            "importance": importance,
                            "schema_version": 1,
                            "updated_at": now_iso
                        },
                        "$setOnInsert": {
                            "confidence": 1.0, 
                            "source": "regex",
                            "first_seen": now_iso
                        }
                    },
                    upsert=True
                )
            else:
                await self.memory_col.update_one(
                    {"key": key},
                    {
                        "$set": {
                            "key": key,
                            "value": value,
                            "category": category,
                            "importance": importance,
                            "confidence": 1.0,
                            "source": "regex",
                            "schema_version": 1,
                            "updated_at": now_iso
                        },
                        "$setOnInsert": {
                            "first_seen": now_iso
                        }
                    },
                    upsert=True
                )

            logger.info("[MemoryEngine] Extracted: %s | Value: %s | Importance: %s", key, value, importance)

    async def get_relevant_memories(self, query: str) -> list[dict]:
        """Query-aware structured memory retrieval returning raw structured objects for downstream formatters."""
        if self.memory_col is None:
            return []
        try:
            lower_q = query.lower()
            filter_query = {}

            if "like" in lower_q or "preference" in lower_q or "favorite" in lower_q:
                filter_query = {"category": "preference"}
            elif "birthday" in lower_q or "born" in lower_q:
                filter_query = {"key": "birthday"}
            elif "name" in lower_q or "profile" in lower_q:
                filter_query = {"key": "name"}

            cursor = self.memory_col.find(filter_query).limit(10)
            memories = await cursor.to_list(length=10)
            
            if not memories and filter_query:
                cursor = self.memory_col.find({}).limit(10)
                memories = await cursor.to_list(length=10)

            if not memories:
                return []

            structured_results = []
            for m in memories:
                structured_results.append({
                    "key": m.get("key"),
                    "value": m.get("value") or m.get("values"),
                    "category": m.get("category", "general"),
                    "importance": m.get("importance", "medium"),
                    "confidence": m.get("confidence", 1.0),
                    "updated_at": m.get("updated_at")
                })

            return structured_results
        except Exception:
            logger.exception("[Memory Retrieval Error]")
            return []
