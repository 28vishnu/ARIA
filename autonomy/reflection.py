import logging
from typing import List
from autonomy.models import ReflectionRecord

logger = logging.getLogger("aria")

class ReflectionEngine:
    def __init__(self):
        self.reflections: List[ReflectionRecord] = []

    def reflect_on_execution(self, goal_id: str, success: bool, duration: float, failures: int, retries: int) -> ReflectionRecord:
        """Evaluates completed execution quality and stores process lessons."""
        observations = []
        if retries > 0:
            observations.append(f"Required {retries} retries; investigate transient failures.")
        if not success:
            observations.append(f"Goal failed after {failures} failures.")
        else:
            observations.append("Execution completed successfully.")

        record = ReflectionRecord(
            goal_id=goal_id,
            success=success,
            duration_seconds=duration,
            failures=failures,
            retry_count=retries,
            observations=observations
        )
        self.reflections.append(record)
        logger.info("[ReflectionEngine] Recorded reflection for Goal %s | Success: %s", goal_id, success)
        return record
