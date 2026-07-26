import os
import json
import re
from google import genai

class MemoryEngine:
    def __init__(self, db_client, api_key: str = None):
        self.db = db_client
        self.profile_col = db_client["user_profile"] if db_client is not None else None
        self.memory_col = db_client["extracted_memories"] if db_client is not None else None
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.client = genai.Client(api_key=self.api_key) if self.api_key else None

    async def extract_and_store_facts(self, user_text: str):
        """Asynchronously extracts permanent facts, identity attributes, and behavioral preferences from user messages."""
        if not self.client or not self.memory_col:
            return

        extraction_prompt = f"""
Analyze the following user statement and extract any permanent facts, identity details, or preferences.
User Statement: "{user_text}"

If any facts or preferences exist, return them as a JSON array of objects. If none, return [].
Format:
[
  {{"type": "identity" | "preference" | "fact", "key": "attribute_name", "value": "extracted_value"}}
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
            for fact in facts:
                if "key" in fact and "value" in fact:
                    await self.memory_col.update_one(
                        {"key": fact["key"]},
                        {"$set": {"type": fact.get("type", "fact"), "value": fact["value"], "confidence": 1.0}},
                        upsert=True
                    )
                    # Sync identity/preferences directly to master profile
                    if fact["key"] in ["name", "address_style", "location"]:
                        await self.profile_col.update_one(
                            {"_id": "master_profile"},
                            {"$set": {fact["key"]: fact["value"]}},
                            upsert=True
                        )
            print(f"[Memory Engine]: Successfully extracted and persisted {len(facts)} facts, Sir.")
        except Exception as e:
            print(f"[Memory Extraction Warning]: {e}")

    async def get_address_style(self) -> str:
        """Retrieves user preference for how they want to be addressed."""
        if self.profile_col is not None:
            prof = await self.profile_col.find_one({"_id": "master_profile"})
            if prof and prof.get("address_style"):
                return prof.get("address_style")
        return "Sir"
