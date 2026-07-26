import os
import json
from datetime import datetime, timezone

class LearningEngine:
    def __init__(self, mongo_db):
        self.db = mongo_db
        self.corrections_col = mongo_db["corrections_ledger"] if mongo_db is not None else None

    async def record_correction(self, previous_query: str, wrong_answer: str, user_correction: str):
        """Records user corrections permanently so ARIA adapts and improves over time."""
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
        print(f"[LearningEngine]: Recorded correction for query pattern: '{previous_query}'")

    async def check_correction(self, query: str) -> str:
        """Checks if a user correction exists for the given query pattern."""
        if self.corrections_col is None:
            return None
        
        norm_query = query.lower().strip()
        doc = await self.corrections_col.find_one({"query_pattern": norm_query})
        if doc:
            return doc.get("correction")
        return None
