import logging
from typing import Dict, Any, List
from skills.base import BaseSkill, SkillResponse

logger = logging.getLogger("aria")

class SkillManager:
    def __init__(self):
        self.skills: List[BaseSkill] = []

    def register(self, skill: BaseSkill):
        """Normalizes and registers a skill into the ecosystem."""
        skill.name = skill.name.strip().lower()
        self.skills.append(skill)
        logger.info("[SkillManager] Registered skill: '%s'", skill.name)

    async def can_handle(self, query: str, context: Dict[str, Any]) -> bool:
        """
        Returns True if any registered skill can handle the query.
        Does not execute the skill.
        """
        for skill in self.skills:
            try:
                confidence = await skill.can_run(query, context)
                if confidence >= 0.3:
                    return True
            except Exception:
                continue

        return False

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
            try:
                return await best_skill.execute(query, context)
            except Exception as e:
                logger.exception("[SkillManager ERROR] Execution failed for routed skill '%s': %s", best_skill.name, e)
                return SkillResponse(success=False, confidence=0.0, source=best_skill.name, error=str(e))

        logger.warning("[SkillManager] No suitable skill found for query with confidence >= 0.3")
        return SkillResponse(
            success=False,
            confidence=0.0,
            source="skill_manager",
            error=f"No suitable skill found for query: '{query}'"
        )

    async def execute_skill(self, skill_name: str, query: str, context: Dict[str, Any]) -> SkillResponse:
        """Directly executes a specific skill requested by the planner safely."""
        normalized_target = skill_name.strip().lower()

        for skill in self.skills:
            if skill.name == normalized_target:
                logger.info("[SkillManager] Directly executing planned skill: '%s'", skill.name)
                try:
                    return await skill.execute(query, context)
                except Exception as e:
                    logger.exception("[SkillManager ERROR] Execution failed for planned skill '%s': %s", skill.name, e)
                    return SkillResponse(
                        success=False,
                        confidence=0.0,
                        source=skill.name,
                        error=str(e)
                    )

        available = [s.name for s in self.skills]
        logger.error("[SkillManager ERROR] Planner requested unsupported skill '%s'. Available skills: %s", skill_name, available)
        return SkillResponse(
            success=False,
            confidence=0.0,
            source="skill_manager",
            error=f"Skill '{skill_name}' not found. Available: {available}"
        )
