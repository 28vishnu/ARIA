import os
import json
import re
from datetime import datetime, timezone
from google import genai

class MemoryEngine:
    def __init__(self, db_client, api_key: str = None):
        self.db = db_client
        self.profile_col = db_client["user_profile"] if db_client is not None else None
        self.memory_col = db_client["extracted_memories"] if db_client is not None else None
        self.chats_col = db_client["chat_history"] if db_client is not None else None
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.client = genai.Client(api_key=self.api_key) if self.api_key else None

        # Lightweight trigger patterns to avoid unnecessary LLM calls
        self.trigger_patterns = [
            "my name is", "call me", "i prefer", "i like", "i don't like", 
            "i live", "i'm from", "remember", "my birthday", "my college", 
            "don't call me", "my course", "my project"
        ]

    def _should_extract(self, text: str) -> bool:
        lower = text.lower()
        return any(pattern in lower for pattern in self.trigger_patterns)

    async def extract_and_store_facts(self, user_text: str):
        """Filters message with lightweight keywords before invoking Gemini memory extraction."""
        if not self._should_extract(user_text) or not self.client or not self.memory_col:
            return

        extraction_prompt = f"""
Analyze the user statement and extract any lasting personal facts, identity attributes, or preferences.
User Statement: "{user_text}"

Return a JSON array of objects. If none, return [].
Format:
[
  {{"key": "attribute_name", "value": "extracted_value", "category": "identity" | "preference" | "fact"}}
]
"""
        try:
            response = self.client.models.generate_content(
                model='gemini-2.0-flash',
                contents=extraction_prompt
            )
            raw = response.text.strip()
            cleaned = re.sub(r'```(?:json)?\s*', '', raw)
            cleaned = re.sub(r'\s*```', '', cleaned).strip()
            
            facts = json.loads(cleaned)
            now_iso = datetime.now(timezone.utc).isoformat()

            for fact in facts:
                key = fact.get("key")
                value = fact.get("value")
                if not key or not value: 
                    continue

                # Check if memory already exists to update confidence and confirmation count
                existing = await self.memory_col.find_one({"key": key})
                if existing:
                    new_conf = min(0.99, float(existing.get("confidence", 0.8)) + 0.1)
                    confirmed = int(existing.get("times_confirmed", 1)) + 1
                    await self.memory_col.update_one(
                        {"key": key},
                        {
                            "$set": {
                                "value": value, 
                                "confidence": new_conf, 
                                "times_confirmed": confirmed, 
                                "updated_at": now_iso
                            }
                        }
                    )
                else:
                    await self.memory_col.insert_one({
                        "key": key,
                        "value": value,
                        "category": fact.get("category", "fact"),
                        "confidence": 0.85,
                        "source": "conversation",
                        "times_confirmed": 1,
                        "created_at": now_iso,
                        "updated_at": now_iso
                    })

                # Sync stable fields separately to master_profile
                if key in ["name", "location", "college", "course"] and self.profile_col is not None:
                    await self.profile_col.update_one(
                        {"_id": "master_profile"},
                        {"$set": {key: value}},
                        upsert=True
                    )

            print(f"[Memory Engine]: Processed {len(facts)} memory updates securely, Sir.")
        except Exception as e:
            print(f"[Memory Extraction Warning]: {e}")

    async def get_address_style(self) -> str:
        """Retrieves user preference for how they want to be addressed."""
        if self.memory_col is not None:
            pref = await self.memory_col.find_one({"key": {"$in": ["address_style", "call_me"]}})
            if pref and pref.get("value"):
                return pref.get("value")
        if self.profile_col is not None:
            prof = await self.profile_col.find_one({"_id": "master_profile"})
            if prof and prof.get("address_style"):
                return prof.get("address_style")
        return "Sir"

    async def consolidate_memories_background_worker(self):
        """Periodic background job to review recent conversations, consolidate memories, and purge stale facts."""
        if not self.memory_col: 
            return
        print("[Memory Engine]: Running background memory consolidation task...")
        try:
            # Purge low-confidence unconfirmed memories older than 30 days
            cutoff_date = (datetime.now(timezone.utc) - __import__('datetime').timedelta(days=30)).isoformat()
            await self.memory_col.delete_many({
                "confidence": {"$lt": 0.5},
                "times_confirmed": {"$lte": 1},
                "created_at": {"$lt": cutoff_date}
            })
            print("[Memory Engine]: Background memory consolidation complete.")
        except Exception as e:
            print(f"[Memory Consolidation Error]: {e}")
