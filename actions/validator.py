import logging
from typing import Dict, Any

logger = logging.getLogger("aria")

class ActionValidator:
    async def validate_params(self, action_name: str, action_instance, params: Dict[str, Any]) -> bool:
        """Runs pre-execution validation checks."""
        try:
            is_valid = await action_instance.validate(params)
            if not is_valid:
                logger.warning("[ActionValidator] Validation failed for action: %s with params: %s", action_name, params)
            return is_valid
        except Exception as e:
            logger.exception("[ActionValidator ERROR] Validation exception in action %s: %s", action_name, e)
            return False
