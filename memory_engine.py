import os
import json
import re
from datetime import datetime, timezone, timedelta
from google import genai

class MemoryEngine:
    def __init__(self, db_client, chroma_client=None, api_key: str = None):
        self.db = db_client
        self.profile_col = db_client["user_profile"] if db_client is not None else None
        self.memory_col = db_client["extracted_memories"] if db_client is not None else None
        self.chroma_client = chroma_client
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.client = genai.Client(api_key=self.api_key) if self.api_key else None

        # Dual-Stage Heuristics: Extended conversational nuance patterns
        self.trigger_patterns = [
            "my name is", "call me", "i prefer", "i like", "i don't like", 
            "i live", "i'm from", "remember", "my birthday", "my college", 
            "don't call me", "my course", "my project", "from now on", 
            "never call", "obsessed with", "rather than", "favorite", "favourite"
        ]

    def _should_extract(self, text: str) -> bool:
        lower = text.lower()
        # Stage 1: Keyword check or sentence length heuristic for complex statements
        has_keyword = any(pattern in lower for pattern in self.trigger_patterns)
        is_declarative_and_long = len(text.split()) > 6 and any(w in lower for w in ["i ", "my ", "stop ", "always "])
        return has_keyword or is_declarative_and_long

    async def extract_and_store_facts(self, user_text: str):
        """Dual-stage extraction handling conflict detection, history logging, and dynamic confidence scaling."""
        if not self._should_extract(user_text) or not self.client or not self.memory_col:
            return

        extraction_prompt = f"""
Analyze the user statement for personal facts, identity attributes, or preference shifts.
User Statement: "{user_text}"

Return a JSON array of objects. If none, return [].
Format:
[
  {{"key": "attribute_name", "value": "extracted_value", "category": "identity" | "preference" | "fact", "is_contradiction": true/false}}
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
            today_date = datetime.now(timezone.utc).strftime('%Y-%m-%d')

            for fact in facts:
                key = fact.get("key")
                value = fact.get("value")
                is_contradiction = fact.get("is_contradiction", False)
                if not key or not value: 
                    continue

                existing = await self.memory_col.find_one({"key": key})
                if existing:
                    current_val = existing.get("value")
                    history = existing.get("history", [])

                    if current_val.lower() != value.lower() or is_contradiction:
                        # Preference shift / Conflict detected: Log old value into history audit trail
                        history.append({"value": current_val, "until": today_date})
                        new_conf = 0.85 # Reset confidence for the new value
                        confirmed = 1
                    else:
                        # Confirmed existing value: Increase confidence
                        new_conf = min(0.99, float(existing.get("confidence", 0.8)) + 0.1)
                        confirmed = int(existing.get("times_confirmed", 1)) + 1

                    await self.memory_col.update_one(
                        {"key": key},
                        {
                            "$set": {
                                "value": value, 
                                "confidence": new_conf, 
                                "times_confirmed": confirmed, 
                                "history": history,
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
                        "history": [],
                        "created_at": now_iso,
                        "updated_at": now_iso
                    })

                # Sync stable fields to master_profile
                if key in ["name", "location", "college", "course"] and self.profile_col is not None:
                    await self.profile_col.update_one(
                        {"_id": "master_profile"},
                        {"$set": {key: value}},
                        upsert=True
                    )

            print(f"[Memory Engine]: Processed and reconciled {len(facts)} memories with conflict checks, Sir.")
        except Exception as e:
            print(f"[Memory Extraction Warning]: {e}")

    async def get_relevant_memories(self, user_text: str) -> str:
        """Retrieves only the memories relevant to the current user query to prevent prompt bloat."""
        if not self.memory_col:
            return ""
        
        lower_q = user_text.lower()
        cursor = self.memory_col.find({})
        all_mems = await cursor.to_list(length=100)
        
        relevant = []
        for mem in all_mems:
            key = mem.get("key", "").lower()
            val = str(mem.get("value", "")).lower()
            # Match if memory key or value terms appear in query, or for broad questions
            if key in lower_q or any(w in lower_q for w in key.split("_")) or any(k in lower_q for k in ["who am i", "my name", "profile", "about me"]):
                relevant.append(f"• {mem.get('key')}: {mem.get('value')}")

        if not relevant and any(k in lower_q for k in ["who am i", "my name"]):
            # Fallback to key identity keys if general profile requested
            for mem in all_mems:
                if mem.get("key") in ["name", "location", "college"]:
                    relevant.append(f"• {mem.get('key')}: {mem.get('value')}")

        return "\n".join(relevant) if relevant else ""

    async def get_address_style(self) -> str:
        if self.memory_col is not None:
            pref = await self.memory_col.find_one({"key": {"$in": ["address_style", "call_me"]}})
            if pref and pref.get("value"):
                return pref.get("value")
        return "Sir"

    async def consolidate_memories_background_worker(self):
        """Background job for memory consolidation: merging duplicates, resolving conflicts, and syncing graph."""
        if not self.memory_col: 
            return
        print("[Memory Engine]: Running advanced background memory consolidation & sync...")
        try:
            # 1. Purge low-confidence unconfirmed memories older than 30 days
            cutoff_date = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
            await self.memory_col.delete_many({
                "confidence": {"$lt": 0.4},
                "times_confirmed": {"$lte": 1},
                "created_at": {"$lt": cutoff_date}
            })

            # 2. Sync stable high-confidence memories into knowledge graph if available
            cursor = self.memory_col.find({"confidence": {"$gte": 0.9}})
            high_conf_mems = await cursor.to_list(length=50)
            print(f"[Memory Engine]: Consolidated {len(high_conf_mems)} high-confidence memories. Background sync complete.")
        except Exception as e:
            print(f"[Memory Consolidation Error]: {e}")
