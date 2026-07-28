import logging
from typing import Dict, Any, Optional
from brain.memory.memory_engine import MemoryEngine

logger = logging.getLogger("aria")

class MemoryConversationManager:
    """
    Manages conversational memory interactions cleanly through MemoryEngine abstraction,
    producing natural, JARVIS-style responses without direct database or regex duplication.
    """

    def __init__(self, memory_engine: MemoryEngine):
        self.memory_engine = memory_engine

    async def handle(self, query: str, context: Dict[str, Any]) -> str:
        """
        Interprets memory-related intents routed via the DecisionEngine and MemoryEngine,
        returning polished conversational responses.
        """
        intent = context.get("intent")
        intent_name = intent.name if intent else "memory"

        lower_q = query.lower().strip()

        # 1. Handle Deletion / Forget
        if intent_name == "memory_delete" or lower_q.startswith(("forget", "delete", "clear", "remove")):
            return await self._handle_forget(query)

        # 2. Handle Store / Update
        if intent_name in ("memory_store", "memory_update"):
            result = await self.memory_engine.process_and_store(query)
            if result and result.get("success"):
                key = result.get("key", "").replace("favorite_", "").replace("_", " ")
                value = result.get("value", "")
                action_type = result.get("action", "stored")

                if action_type == "update":
                    return f"I've updated that, Sir. I'll remember that your {key} is {value}."
                return f"Understood, Sir. I'll remember that your {key} is {value}."
            return "Understood, Sir. I've updated my records accordingly."

        # 3. Handle Recall
        memories = await self.memory_engine.retrieve(query)
        if memories:
            mem = memories[0]
            key = mem.get("key", "").replace("favorite_", "").replace("_", " ")
            value = mem.get("value", "")
            if key and value:
                return f"Your {key} is {value}, Sir."
            return f"I found this in my records, Sir: {value}"

        # 4. Unknown / No memory found
        key_guess = self._guess_key_from_query(lower_q)
        if key_guess:
            return f"I don't remember your {key_guess} yet, Sir."

        return "I couldn't find a matching record in my memory banks, Sir."

    async def _handle_forget(self, query: str) -> str:
        """Handles deletion or clearing of specific memories by delegating parsing to MemoryEngine."""
        try:
            success = await self.memory_engine.delete_memory(query)
            if success:
                return "Done, Sir. I've removed that from my records."

            return "I couldn't find any recorded memory matching that description, Sir."
        except Exception:
            logger.exception("[MemoryConversationManager] Failed to delete memory.")
            return "I encountered an error while trying to update my memory, Sir."

    def _guess_key_from_query(self, query: str) -> Optional[str]:
        """Guesses the subject from a failed recall query."""
        import re
        match = re.search(r'(?:what\'s|what is|recall|remember)\s+(?:my\s+)?([a-zA-Z0-9\s]+)', query)
        if match:
            cleaned = match.group(1).replace("favorite", "").replace("favourite", "").strip()
            if cleaned:
                return cleaned
        return None
