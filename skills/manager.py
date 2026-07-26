import logging
import time
from typing import List, Dict, Any, Optional
from skills.base import BaseSkill, SkillResponse

logger = logging.getLogger("aria")

class SkillManager:
    def __init__(self):
        self.skills: List[BaseSkill] = []

    def register(self, skill: BaseSkill):
        """Registers an independent skill plugin."""
        self.skills.append(skill)
        logger.info("[SkillManager] Registered skill: %s (v%s)", skill.name, skill.version)

    async def route_and_execute(self, query: str, context: Dict[str, Any]) -> SkillResponse:
        """Evaluates can_run() across all skills, selects the highest-confidence match, and executes it."""
        if not self.skills:
            return SkillResponse(success=False, confidence=0.0, source="manager", error="No skills registered.")

        best_skill: Optional[BaseSkill] = None
        best_confidence = -1.0

        # 1. Evaluate confidence across all registered skills concurrently
        evaluation_tasks = [skill.can_run(query, context) for skill in self.skills]
        import asyncio
        confidences = await asyncio.gather(*evaluation_tasks, return_exceptions=True)

        for skill, conf in zip(self.skills, confidences):
            if isinstance(conf, float) and conf > best_confidence:
                best_confidence = conf
                best_skill = skill

        # Fallback if no skill exceeds confidence threshold
        if not best_skill or best_confidence < 0.3:
            return SkillResponse(success=False, confidence=best_confidence, source="manager", error="No suitable skill found for query.")

        # 2. Execute the winning skill with strict timing logs
        start_time = time.perf_counter()
        success = True
        response: Optional[SkillResponse] = None

        try:
            response = await best_skill.execute(query, context)
            success = response.success
        except Exception as e:
            logger.exception("[SkillManager ERROR] Skill execution failed: %s", best_skill.name)
            response = SkillResponse(success=False, confidence=best_confidence, source=best_skill.name, error=str(e))
            success = False

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.info(
            "[SkillManager] Selected: %s | Confidence: %.2f | Execution Time: %.1f ms | Success: %s",
            best_skill.name, best_confidence, elapsed_ms, success
        )

        return response
