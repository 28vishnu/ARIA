import os
import json
import re
from datetime import datetime, timezone
from google import genai

class MemoryEngine:
    def __init__(self, mongo_db, api_key: str = None):
        self.db = mongo_db
        self.memory_col = mongo_db["personal_memory"] if mongo_db is not None else None
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.client = genai.Client(api_key=self.api_key) if self.api_key else None

    def _should_extract(self, text: str) -> bool:
        """Determines if a user message contains storable facts while filtering out sensitive IDs."""
        lower = text.lower().strip()
        
        # Security Guardrail: Ignore or block text containing sensitive ID patterns (e.g., Aadhaar)
        aadhaar_pattern = r'\b\d{4}\s?\d{4}\s?\d{4}\b'
        if re.search(aadhaar_pattern, text):
            return False

        triggers = [
            "remember", "i like", "i love", "i prefer", "my name is", 
            "i am", "i live in", "my project", "my birthday", "favorite", "favourite"
        ]
        return any(t in lower for t in triggers) or len(text.split()) > 6

    async def extract_and_store_facts(self, user_text: str):
        """Asynchronously extracts structured facts from user dialogue and persists them."""
        if (
            self.client is None
            or self.memory_col is None
            or not self._should_extract(user_text)
        ):
            return

        prompt = f"""
Analyze this user statement and extract any persistent personal facts, preferences, or project details.
Do NOT extract or store sensitive government IDs (such as Aadhaar, RRN, or MyNumber).
Statement: "{user_text}"

If facts are present, output a JSON list of objects with "category" and "fact". If none, return [].
Example: [{{"category": "preference", "fact": "User prefers dark mode and Python."}}]
"""
        try:
            def _generate():
                return self.client.models.generate_content(
                    model='gemini-2.0-flash',
                    contents=prompt
                )
            
            res = await asyncio_to_thread_safe(_generate)
            raw = res.text.strip()
            cleaned = re.sub(r'```(?:json)?\s*', '', raw)
            cleaned = re.sub(r'\s*```', '', cleaned).strip()
            
            facts = json.loads(cleaned)
            if isinstance(facts, list) and facts:
                for item in facts:
                    fact_text = item.get("fact")
                    category = item.get("category", "general")
                    if fact_text:
                        await self.memory_col.update_one(
                            {"fact": fact_text},
                            {
                                "$set": {
                                    "fact": fact_text,
                                    "category": category,
                                    "updated_at": datetime.now(timezone.utc).isoformat()
                                }
                            },
                            upsert=True
                        )
                print(f"[MemoryEngine]: Successfully stored {len(facts)} fact(s) to long-term memory, Sir.")
        except Exception as e:
            print(f"[MemoryExtraction Warning]: {e}")

    async def get_relevant_memories(self, query: str) -> str:
        """Retrieves permanent memories relevant to the current query."""
        if self.memory_col is None:
            return ""
        try:
            cursor = self.memory_col.find({}).limit(10)
            memories = await cursor.to_list(length=10)
            if not memories:
                return ""
            return "\n".join([f"• [{m.get('category', 'general').upper()}] {m.get('fact')}" for m in memories])
        except Exception as e:
            print(f"[Memory Retrieval Warning]: {e}")
            return ""

async def asyncio_to_thread_safe(func, *args, **kwargs):
    import asyncio
    return await asyncio.to_thread(func, *args, **kwargs)
