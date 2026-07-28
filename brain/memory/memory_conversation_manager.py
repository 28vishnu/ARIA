import logging
from typing import Dict, Any, Optional
from memory_engine import MemoryEngine

logger = logging.getLogger("aria")

class MemoryConversationManager:
    """
    Manages conversational memory interactions, translating intents and queries
    into structured database operations and natural, JARVIS-style responses.
    """

    def __init__(self, memory_engine: MemoryEngine):
        self.memory_engine = memory_engine

    async def handle(self, query: str, context: Dict[str, Any]) -> str:
        """
        Determines the memory action (Store, Recall, Update, Forget, Unknown)
        based on the query and context, executes it against MemoryEngine,
        and returns a natural, conversational response.
        """
        lower_q = query.lower().strip()

        # 1. Forget / Delete Action
        if lower_q.startswith(("forget", "delete", "clear")):
            return await self._handle_forget(lower_q)

        # 2. Store / Update Action (e.g. "My favourite color is blue" or "My favourite color is now black")
        if any(p in lower_q for p in ["is", "prefer", "like", "love"]):
            # Check if it's an update or store (deterministic_extract_and_store handles upserts)
            await self.memory_engine.deterministic_extract_and_store(query)
            
            # Extract key/value for the natural response
            key, value = self._extract_key_value(query)
            if key and value:
                display_key = key.replace("favorite_", "").replace("_", " ")
                return f"Understood, Sir. I've noted that your {display_key} is {value}."
            return "Understood, Sir. I've updated my records accordingly."

        # 3. Recall Action (e.g. "What's my favourite colour?")
        memories = await self.memory_engine.get_relevant_memories(query)
        if memories:
            mem = memories[0]
            key = mem.get("key", "").replace("favorite_", "").replace("_", " ")
            value = mem.get("value", "")
            if key and value:
                return f"Your {key} is {value}, Sir."
            return f"I found this in my records, Sir: {value}"

        # 4. Unknown / No memory exists
        key_guess = self._guess_key_from_query(lower_q)
        if key_guess:
            return f"I don't remember your {key_guess} yet, Sir."
        
        return "I couldn't find a matching record in my memory banks, Sir."

    async def _handle_forget(self, query: str) -> str:
        """Handles deletion or clearing of specific memories."""
        if self.memory_engine.memory_col is None:
            return "Memory database is currently offline, Sir."

        try:
            # Extract what to forget (e.g., "forget my favourite colour")
            target = query.replace("forget", "").replace("delete", "").replace("my", "").strip()
            target_key = f"favorite_{target}" if not target.startswith("favorite_") else target
            
            result = await self.memory_engine.memory_col.delete_one({"key": target_key})
            if result.deleted_count > 0:
                display_target = target.replace("favorite_", "").replace("_", " ")
                return f"Done, Sir. I've forgotten your {display_target}."
            
            # Try matching broad query
            result_broad = await self.memory_engine.memory_col.delete_one({"key": {"$regex": target, "$options": "i"}})
            if result_broad.deleted_count > 0:
                return f"Done, Sir. I've removed that from my records."

            return f"I couldn't find any recorded memory matching '{target}', Sir."
        except Exception:
            logger.exception("[MemoryConversationManager] Failed to delete memory.")
            return "I encountered an error while trying to update my memory, Sir."

    def _extract_key_value(self, query: str):
        """Helper to extract key and value for response formatting."""
        import re
        lower = query.lower()
        fav_match = re.search(r'(?:my )?favou?rite\s+([a-zA-Z0-9\s]+?)\s+is\s+([a-zA-Z0-9\s]+)', lower)
        if fav_match:
            subj, val = fav_match.groups()
            return f"favorite_{subj.strip()}", val.strip()
        return None, None

    def _guess_key_from_query(self, query: str) -> Optional[str]:
        """Guesses the subject from a failed recall query."""
        import re
        match = re.search(r'(?:what\'s|what is|recall|remember)\s+(?:my\s+)?([a-zA-Z0-9\s]+)', query)
        if match:
            cleaned = match.group(1).replace("favorite", "").replace("favourite", "").strip()
            if cleaned:
                return cleaned
        return None
