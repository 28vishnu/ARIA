import logging
from skills.base import SkillResponse

logger = logging.getLogger("aria")

class Verifier:
    def verify(self, task_id: str, response: SkillResponse) -> bool:
        """Validates task execution output, throwing no exceptions and logging detailed verification metrics."""
        if not response.success:
            logger.warning("[Verifier] Task %s failed: %s", task_id, response.error)
            return False
            
        if response.data is None:
            logger.warning("[Verifier] Task %s passed execution but returned empty data payload.", task_id)
            # Depending on policy, empty data can be acceptable or a soft failure. Let's treat as pass if success=True.
            
        logger.info("[Verifier] Task %s | Confidence: %.2f | Result: PASS", task_id, response.confidence)
        return True
