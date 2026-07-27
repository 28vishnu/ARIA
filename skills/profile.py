import logging
from typing import Dict, Any
from skills.base import BaseSkill, SkillResponse

logger = logging.getLogger("aria")

class ProfileSkill(BaseSkill):
    name = "profile"
    description = "Retrieves user personal profile data, background, education, and professional history."

    async def can_run(self, query: str, context: Dict[str, Any]) -> float:
        """Determines if the query relates to user profile or personal background."""
        keywords = ["profile", "who am i", "my background", "my education", "my career", "about me", "my skills", "aadhar", "aadhaar", "id number"]
        lower = query.lower()
        if any(k in lower for k in keywords):
            return 0.95
        return 0.1

    async def execute(self, query: str, context: Dict[str, Any]) -> SkillResponse:
        """Retrieves user profile data safely via MemoryEngine, gracefully handling empty record sets."""
        try:
            memory_engine = context.get("memory_engine")
            if not memory_engine and "app_state" in context:
                app_state = context["app_state"]
                if hasattr(app_state, "registry") and app_state.registry.has("memory_engine"):
                    memory_engine = app_state.registry.get("memory_engine")

            logger.info(
                "[ProfileSkill] Using MemoryEngine implementation: %s",
                type(memory_engine).__name__ if memory_engine else "None"
            )

            profile_data = {}
            if memory_engine:
                if hasattr(memory_engine, "get_profile"):
                    profile_data = await memory_engine.get_profile()
                elif hasattr(memory_engine, "get"):
                    profile_data = await memory_engine.get("user_profile") or await memory_engine.get("profile") or {}
                elif hasattr(memory_engine, "search"):
                    res = await memory_engine.search("profile")
                    profile_data = res if isinstance(res, dict) else {"results": res}

            logger.info(
                "[ProfileSkill] Retrieved profile data type/keys: %s",
                list(profile_data.keys()) if isinstance(profile_data, dict) else type(profile_data).__name__
            )

            # Gracefully handle missing profile records without triggering a hard system error
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
