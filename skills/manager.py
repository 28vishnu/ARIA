import logging
from typing import Dict, Any, List
from skills.base import BaseSkill, SkillResponse

logger = logging.getLogger("aria")

class SkillManager:
    def __init__(self):
        self.skills: List[BaseSkill] = []

    def register(self, skill: BaseSkill):
        self.skills.append(skill)
        logger.info("[SkillManager] Registered skill: '%s'", skill.name)

    async def route_and_execute(self, query: str, context: Dict[str, Any]) -> SkillResponse:
        """Evaluates all registered skills by confidence and executes the best match."""
        best_skill = None
        highest_confidence = 0.0

        for skill in self.skills:
            try:
                confidence = await skill.can_run(query, context)
                if confidence > highest_confidence:
                    highest_confidence = confidence
                    best_skill = skill
            except Exception as e:
                logger.exception("[SkillManager ERROR] Error evaluating skill '%s': %s", skill.name, e)

        if best_skill and highest_confidence >= 0.3:
            logger.info("[SkillManager] Routing query to skill '%s' (Confidence: %.2f)", best_skill.name, highest_confidence)
            return await best_skill.execute(query, context)

        logger.warning("[SkillManager] No suitable skill found for query with confidence >= 0.3")
        return SkillResponse(
            success=False,
            confidence=0.0,
            source="skill_manager",
            error=f"No suitable skill found for query: '{query}'"
        )

    async def execute_skill(self, skill_name: str, query: str, context: Dict[str, Any]) -> SkillResponse:
        """Directly executes a specific skill requested by the planner, avoiding redundant re-routing."""
        normalized_target = skill_name.lower().strip()
        
        for skill in self.skills:
            if skill.name.lower().strip() == normalized_target:
                logger.info("[SkillManager] Directly executing planned skill: '%s'", skill.name)
                return await skill.execute(query, context)

        logger.error("[SkillManager ERROR] Requested skill '%s' not found in registry.", skill_name)
        return SkillResponse(
            success=False,
            confidence=0.0,
            source="skill_manager",
            error=f"Skill '{skill_name}' not found."
        )
