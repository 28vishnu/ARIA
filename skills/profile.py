import logging
from typing import Dict, Any, List
from skills.base import BaseSkill, SkillResponse

logger = logging.getLogger("aria")

class ProfileSkill(BaseSkill):
    name = "profile"
    description = "Retrieves user personal profile data, background, education, and professional history."

    async def can_run(self, query: str, context: Dict[str, Any]) -> float:
        """Determines if the query relates to user profile or personal background using precise first-person phrasing."""
        first_person_keywords = [
            "profile", "who am i", "my background", "my education", "my career", 
            "about me", "my skills", "my college", "my university", "my degree", 
            "my phone", "my number", "my work", "my job", "where do i work"
        ]
        lower = query.lower()
        if any(k in lower for k in first_person_keywords):
            return 0.95
        return 0.1

    async def execute(self, query: str, context: Dict[str, Any]) -> SkillResponse:
        """Retrieves user profile data, prioritizing the master user profile and falling back to memory search only if needed."""
        try:
            memory_engine = context.get("memory_engine")
            if not memory_engine and "app_state" in context:
                app_state = context["app_state"]
                if hasattr(app_state, "registry") and app_state.registry.has("memory_engine"):
                    memory_engine = app_state.registry.get("memory_engine")

            profile_data = {}

            if memory_engine:
                # 1. Attempt to fetch the master profile document first
                if hasattr(memory_engine, "get_profile"):
                    profile_data = await memory_engine.get_profile() or {}
                elif hasattr(memory_engine, "get"):
                    profile_data = await memory_engine.get("user_profile") or await memory_engine.get("profile") or {}

                if not isinstance(profile_data, dict):
                    profile_data = {"record": profile_data}

                # 2. If a valid master profile exists, return it immediately without running fallback searches
                if profile_data:
                    logger.info("[ProfileSkill] Returning master profile directly, skipping fallback memory search.")
                    return SkillResponse(
                        success=True,
                        confidence=0.95,
                        source=self.name,
                        data=profile_data
                    )

                # 3. Only reach this point if no master profile document was found; fall back to adaptive memory search
                if hasattr(memory_engine, "get_relevant_memories"):
                    search_query = query
                    generic_triggers = ("profile", "about me", "who am i", "background")
                    if any(t in query.lower() for t in generic_triggers):
                        search_query = f"profile education college university career skills background {query}"

                    logger.info("[ProfileSkill] No master profile found. Querying MemoryEngine with adaptive search: '%s'", search_query)
                    raw_memories = await memory_engine.get_relevant_memories(search_query)
                    
                    normalized_memories: List[Dict[str, Any]] = []
                    if raw_memories:
                        for m in raw_memories:
                            if isinstance(m, dict):
                                k = m.get("key") or m.get("field") or m.get("category") or "Memory"
                                v = m.get("value") or m.get("content") or m.get("text") or m.get("summary")
                                if v is None:
                                    v = repr(m)
                                normalized_memories.append({"key": k, "value": v})
                            elif hasattr(m, "__dict__"):
                                d = m.__dict__
                                k = d.get("key") or d.get("field") or "Memory"
                                v = d.get("value") or d.get("content") or d.get("text") or d.get("summary")
                                if v is None:
                                    v = repr(d)
                                normalized_memories.append({"key": k, "value": v})
                            else:
                                normalized_memories.append({"key": "Detail", "value": repr(m)})

                    if normalized_memories:
                        profile_data["memories"] = normalized_memories

            # 4. Friendly fallback if both profile store and memory search yield nothing
            if not profile_data or (not profile_data.get("memories") and len(profile_data) == 0):
                return SkillResponse(
                    success=True,
                    confidence=0.60,
                    source=self.name,
                    data={
                        "message": "I don't have your profile information stored yet, Sir."
                    }
                )

            return SkillResponse(
                success=True,
                confidence=0.80,
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
