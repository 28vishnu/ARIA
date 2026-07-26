import os
import re
import logging
from datetime import datetime, timezone

logger = logging.getLogger("aria")

class MemoryEngine:
    def __init__(self, mongo_db):
        self.db = mongo_db
        self.memory_col = mongo_db["personal_memory"] if mongo_db is not None else None

    def _should_extract(self, text: str) -> bool:
        """Skips non-fact statements (greetings, math, simple queries) and filters sensitive IDs."""
        lower = text.lower().strip()
        
        # Security Guardrail: Never extract sensitive IDs
        aadhaar_pattern = r'\b\d{4}\s?\d{4}\s?\d{4}\b'
        if re.search(aadhaar_pattern, text):
            return False

        # Skip non-storable conversational utterances
        skip_phrases = ["hi", "hello", "hey", "thanks", "thank you", "good morning", "good evening", "bye"]
        if lower in skip_phrases or any(lower.startswith(p) for p in ["what's", "what is", "how ", "where ", "who "]):
            if not any(k in lower for k in ["my name", "my favorite", "i prefer"]):
                return False

        # Skip basic math expressions
        if bool(re.match(r'^[\d\+\-\*\/\.\(\)\s]+$', text)):
            return False

        return True

    def _normalize(self, value: str) -> str:
        """Normalizes extracted text values by stripping punctuation and collapsing whitespace."""
        cleaned = value.lower().strip()
        cleaned = re.sub(r'[^\w\s]', '', cleaned)
        cleaned = re.sub(r'\s+', ' ', cleaned)
        return cleaned

    async def deterministic_extract_and_store(self, user_text: str):
        """Extracts structured key-value memories deterministically with overwrite/accumulate rules."""
        if self.memory_col is None or not self._should_extract(user_text):
            return

        lower = user_text.lower().strip()
        key, value, category = None, None, "preference"
        is_list_accumulate = False

        # Pattern 1: Favorite subject/thing
        fav_match = re.search(r'(?:my )?favorite\s+([a-zA-Z0-9\s]+?)\s+is\s+([a-zA-Z0-9\s]+)', lower)
        rev_fav_match = re.search(r'([a-zA-Z0-9\s]+?)\s+is\s+my\s+favorite\s+([a-zA-Z0-9\s]+)', lower)
        
        # Pattern 2: Preferences (Likes/Loves/Prefers) -> Accumulate into lists
        pref_match = re.search(r'i\s+(?:prefer|like|love)\s+([a-zA-Z0-9\s]+)', lower)

        if fav_match:
            subj, val = fav_match.groups()
            key = f"favorite_{self._normalize(subj)}"
            value = self._normalize(val)
            category = "preference"
        elif rev_fav_match:
            val, subj = rev_fav_match.groups()
            key = f"favorite_{self._normalize(subj)}"
            value = self._normalize(val)
            category = "preference"
        elif pref_match:
            key = "user_likes"
            value = self._normalize(pref_match.group(1))
            category = "preference"
            is_list_accumulate = True
        elif "birthday" in lower or "born on" in lower:
            key = "birthday"
            value = user_text
            category = "personal"

        if key and value:
            now_iso = datetime.now(timezone.utc).isoformat()
            
            if is_list_accumulate:
                # Accumulate values into an array without duplicating
                await self.memory_col.update_one(
                    {"key": key},
                    {
                        "$addToSet": {"values": value},
                        "$set": {"category": category, "updated_at": now_iso},
                        "$setOnInsert": {"confidence": 1.0, "source": "regex"}
                    },
                    upsert=True
                )
            else:
                # Singular facts overwrite the previous value
                await self.memory_col.update_one(
                    {"key": key},
                    {
                        "$set": {
                            "key": key,
                            "value": value,
                            "category": category,
                            "confidence": 1.0,
                            "source": "regex",
                            "updated_at": now_iso
                        }
                    },
                    upsert=True
                )

            logger.info("[MemoryEngine] Extracted: %s | Value: %s | Source: regex", key, value)

    async def get_relevant_memories(self, query: str) -> str:
        """Query-aware structured memory retrieval filtering by category or keyword."""
        if self.memory_col is None:
            return ""
        try:
            lower_q = query.lower()
            filter_query = {}

            # Query-aware category/key mapping
            if "like" in lower_q or "preference" in lower_q or "favorite" in lower_q:
                filter_query = {"category": "preference"}
            elif "birthday" in lower_q or "born" in lower_q:
                filter_query = {"key": "birthday"}
            elif "personal" in lower_q:
                filter_query = {"category": "personal"}

            cursor = self.memory_col.find(filter_query).limit(10)
            memories = await cursor.to_list(length=10)
            
            if not memories and filter_query:
                # Fallback to broader search if specific category yielded nothing
                cursor = self.memory_col.find({}).limit(10)
                memories = await cursor.to_list(length=10)

            if not memories:
                return ""

            formatted_memories = []
            for m in memories:
                if "values" in m:
                    formatted_memories.append(f"• [{m.get('category', 'general').upper()}] {m.get('key')}: {', '.join(m['values'])}")
                else:
                    formatted_memories.append(f"• [{m.get('category', 'general').upper()}] {m.get('key')}: {m.get('value')}")

            return "\n".join(formatted_memories)
        except Exception as e:
            logger.exception("[Memory Retrieval Error]")
            return ""
