import logging
from typing import Dict, Any
from skills.base import BaseSkill, SkillResponse

logger = logging.getLogger("aria")

class ProfileSkill(BaseSkill):
    name = "profile"
    description = "Retrieves user personal profile data, background, education, and professional history."

    async def can_run(self, query: str, context: Dict[str, Any]) -> float:
        """Determines if the query relates to user profile or personal background."""
        keywords = ["profile", "who am i", "my background", "my education", "my career", "about me", "my skills", "college", "university", "degree", "phone", "work", "job"]
        lower = query.lower()
        if any(k in lower for k in keywords):
            return 0.95
        return 0.1

    async def execute(self, query: str, context: Dict[str, Any]) -> SkillResponse:
        """Retrieves user profile data safely via MemoryEngine, utilizing adaptive query matching."""
        try:
            memory_engine = context.get("memory_engine")
            if not memory_engine and "app_state" in context:
                app_state = context["app_state"]
                if hasattr(app_state, "registry") and app_state.registry.has("memory_engine"):
                    memory_engine = app_state.registry.get("memory_engine")

            profile_data = {}
            if memory_engine:
                # 1. Try dedicated profile retrieval methods first
                if hasattr(memory_engine, "get_profile"):
                    profile_data = await memory_engine.get_profile()
                elif hasattr(memory_engine, "get"):
                    profile_data = await memory_engine.get("user_profile") or await memory_engine.get("profile") or {}
                
                # 2. Adaptive query matching against long-term memory if dedicated profile store is empty
                if not profile_data and hasattr(memory_engine, "get_relevant_memories"):
                    search_query = query
                    generic_triggers = ("profile", "about me", "who am i", "background")
                    if any(t in query.lower() for t in generic_triggers):
                        search_query = f"profile education college university career skills background {query}"

                    logger.info("[ProfileSkill] Querying MemoryEngine with adaptive search: '%s'", search_query)
                    memories = await memory_engine.get_relevant_memories(search_query)
                    if memories:
                        profile_data = {"memories": memories}

            if not profile_data:
                return SkillResponse(
                    success=True,
                    confidence=0.6,
                    source=self.name,
                    data={
                        "message": "I don't have your profile information stored yet, Sir."
                    }
                )

            return SkillResponse(
                success=True,
                confidence=0.95,
                source=self.name,
                data=profile_data
            )

        except Exception as e:
            logger.exception("[ProfileSkill ERROR] Failed to retrieve user profile: %s", e)
            return SkillResponse(
                success=False,
                confidence=0.0,
                source=self.name,
                error=str(e)
            )
