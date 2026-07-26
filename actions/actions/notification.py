import logging
from typing import Dict, Any
from actions.base import BaseAction, ActionResult

logger = logging.getLogger("aria")

class NotificationAction(BaseAction):
    name = "notification_action"
    description = "Dispatches system alerts or terminal notifications."
    permission_level = "safe"

    async def validate(self, params: Dict[str, Any]) -> bool:
        return bool(params.get("message"))

    async def execute(self, params: Dict[str, Any]) -> ActionResult:
        message = params.get("message")
        logger.info("[NOTIFICATION DISPATCHED]: %s", message)
        return ActionResult(success=True, action_name=self.name, data={"delivered": True, "message": message})
