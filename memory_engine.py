import os
import re
from datetime import datetime, timezone

class MemoryEngine:
    def __init__(self, mongo_db):
        self.db = mongo_db
        self.memory_col = mongo_db["personal_memory"] if mongo_db is not None else None

    def _should_extract(self, text: str) -> bool:
        """Determines if a user message contains storable facts while respecting privacy rules."""
        aadhaar_pattern = r'\b\d{4}\s?\d{4}\s?\d{4}\b'
        if re.search(aadhaar_pattern, text):
            return False
        return True

    async def deterministic_extract_and_store(self, user_text: str):
        """Captures facts using flexible regex rules (Zero-LLM mode)."""
        if self.memory_col is None or not self._should_extract(user_text):
            return

        lower = user_text.lower().strip()
        fact_to_store = None
        category = "general"

        # Pattern 1: "my favorite X is Y" or "favorite X is Y"
        fav_match = re.search(r'(?:my )?favorite\s+([a-zA-Z0-9\s]+?)\s+is\s+([a-zA-Z0-9\s]+)', lower)
        # Pattern 2: "Y is my favorite X"
        rev_fav_match = re.search(r'([a-zA-Z0-9\s]+?)\s+is\s+my\s+favorite\s+([a-zA-Z0-9\s]+)', lower)
        # Pattern 3: "I prefer X" or "I like X" or "I love X"
        pref_match = re.search(r'i\s+(?:prefer|like|love)\s+([a-zA-Z0-9\s]+)', lower)

        if fav_match:
            subject, value = fav_match.groups()
            fact_to_store = f"Favorite {subject.strip()}: {value.strip()}"
            category = "preference"
        elif rev_fav_match:
            value, subject = rev_fav_match.groups()
            fact_to_store = f"Favorite {subject.strip()}: {value.strip()}"
            category = "preference"
        elif pref_match:
            pref = pref_match.group(1).strip()
            fact_to_store = f"User preference: {pref}"
            category = "preference"
        elif "birthday" in lower or "born on" in lower:
            fact_to_store = f"Personal detail: {user_text}"
            category = "personal"

        if fact_to_store:
            await self.memory_col.update_one(
                {"fact": fact_to_store},
                {"$set": {"fact": fact_to_store, "category": category, "updated_at": datetime.now(timezone.utc).isoformat()}},
                upsert=True
            )
            print(f"[MemoryEngine]: Deterministically stored fact: '{fact_to_store}'")

    async def get_relevant_memories(self, query: str) -> str:
        """Retrieves permanent memories relevant to the query."""
        if self.memory_col is None:
            return ""
        try:
            cursor = self.memory_col.find({}).limit(10)
            memories = await cursor.to_list(length=10)
            if not memories:
                return ""
            return "\n".join([f"• [{m.get('category', 'general').upper()}] {m.get('fact')}" for m in memories])
        except Exception as e:
            print(f"[Memory Retrieval Error]: {e}")
            return ""
