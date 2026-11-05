import os
import re
from datetime import datetime, timezone

class LearningEngine:
    def __init__(self, mongo_db):
        self.db = mongo_db
        self.corrections_col = mongo_db["corrections_ledger"] if mongo_db is not None else None
        self.memory_col = mongo_db["personal_memory"] if mongo_db is not None else None

    async def record_correction(self, previous_query: str, wrong_answer: str, user_correction: str):
        if self.corrections_col is None:
            return
        correction_doc = {
            "query_pattern": previous_query.lower().strip(),
            "wrong_answer": wrong_answer,
            "correction": user_correction,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        await self.corrections_col.update_one(
            {"query_pattern": correction_doc["query_pattern"]},
            {"$set": correction_doc},
            upsert=True
        )
        print(f"[LearningEngine]: Recorded correction for pattern: '{previous_query}'")

    async def check_correction(self, query: str) -> str:
        if self.corrections_col is None:
            return None
        doc = await self.corrections_col.find_one({"query_pattern": query.lower().strip()})
        return doc.get("correction") if doc else None

    async def deterministic_extract_and_store(self, user_text: str):
        """Extracts facts using regex rules instead of depending on LLM quotas."""
        if self.memory_col is None:
            return

        lower = user_text.lower().strip()
        fact_to_store = None
        category = "general"

        # Rule 1: Favorite color/thing
        fav_match = re.search(r'(?:my )?favorite\s+([a-zA-Z0-9\s]+?)\s+is\s+([a-zA-Z0-9\s]+)', lower)
        if fav_match:
            subject, value = fav_match.groups()
            fact_to_store = f"Favorite {subject.strip()}: {value.strip()}"
            category = "preference"

        # Rule 2: Birthday
        elif "birthday" in lower or "born on" in lower:
            fact_to_store = f"Birthday/Birth detail: {user_text}"
            category = "personal"

        # Rule 3: Direct "I like / I love" preference statements
        elif lower.startswith("i like ") or lower.startswith("i love "):
            fact_to_store = f"User preference: {user_text}"
            category = "preference"

        if fact_to_store:
            await self.memory_col.update_one(
                {"fact": fact_to_store},
                {"$set": {"fact": fact_to_store, "category": category, "updated_at": datetime.now(timezone.utc).isoformat()}},
                upsert=True
            )
            print(f"[Zero-LLM MemoryEngine]: Extracted and stored fact: '{fact_to_store}'")
