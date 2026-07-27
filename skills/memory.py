import logging
from typing import Dict, Any
from skills.base import BaseSkill, SkillResponse

logger = logging.getLogger("aria")

class MemorySkill(BaseSkill):
    name = "memory"
    description = "Searches, recalls, or stores long-term personal facts, past conversations, preferences, and memories."

    async def can_run(self, query: str, context: Dict[str, Any]) -> float:
        """Determines if the query relates to memory recall or past facts with strict thresholding."""
        keywords = ["remember", "recall", "what did", "my memory", "history", "did I", "saved", "memory"]
        lower = query.lower()
        if any(k in lower for k in keywords):
            return 0.90
        # Prevent casual greetings or unrelated queries from biasing toward memory
        return 0.05

    async def execute(self, query: str, context: Dict[str, Any]) -> SkillResponse:
        """Retrieves or searches long-term memories using ARIA's MemoryEngine API."""
        try:
            # 1. Resolve memory engine from context or service registry
            memory_engine = context.get("memory_engine")
            if not memory_engine and "app_state" in context:
                app_state = context["app_state"]
                if hasattr(app_state, "registry") and app_state.registry.has("memory_engine"):
                    memory_engine = app_state.registry.get("memory_engine")

            if not memory_engine:
                logger.error("[MemorySkill ERROR] Memory engine not found in context or registry.")
                return SkillResponse(
                    success=False,
                    confidence=0.0,
                    source=self.name,
                    error="Memory engine offline."
                )

            logger.info("[MemorySkill] Executing memory query: '%s'", query)

            # 2. Extract task input if passed by executor
            task_input = context.get("task_input", {})
            search_query = task_input.get("query", query)

            # 3. Perform memory retrieval via MemoryEngine API matching exact method signatures
            memories = []
            if hasattr(memory_engine, "get_relevant_memories"):
                memories = await memory_engine.get_relevant_memories(search_query)
            elif hasattr(memory_engine, "search_memories"):
                memories = await memory_engine.search_memories(search_query)
            elif hasattr(memory_engine, "search"):
                memories = await memory_engine.search(search_query)
            elif hasattr(memory_engine, "get_recent"):
                memories = await memory_engine.get_recent()
            else:
                return SkillResponse(
                    success=False,
                    confidence=0.0,
                    source=self.name,
                    error="Memory engine does not expose a supported retrieval API."
                )

            # Accurate signal handling for empty result sets
            if not memories:
                return SkillResponse(
                    success=True,
                    confidence=0.6,
                    source=self.name,
                    data={
                        "memories": [],
                        "query": search_query,
                        "message": "No relevant memories found."
                    }
                )

            return SkillResponse(
                success=True,
                confidence=0.95,
                source=self.name,
                data={"memories": memories, "query": search_query}
            )

        except Exception as e:
            logger.exception("[MemorySkill ERROR] Failed to execute memory skill: %s", e)
            return SkillResponse(
                success=False,
                confidence=0.0,
                source=self.name,
                error=f"Memory engine error: {str(e)}"
            )
