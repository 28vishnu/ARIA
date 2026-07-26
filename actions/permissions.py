import logging

logger = logging.getLogger("aria")

class PermissionManager:
    def __init__(self, default_mode: str = "confirm"):
        # Modes: "autonomous" (allow safe/confirm), "strict" (confirm all), "locked" (deny all except safe)
        self.mode = default_mode

    def evaluate(self, action_name: str, permission_level: str) -> bool:
        """Evaluates whether an action is permitted to execute under current system policies."""
        if permission_level == "deny":
            logger.warning("[PermissionManager] Action '%s' is explicitly denied.", action_name)
            return False
        
        if permission_level == "safe":
            return True

        if self.mode == "locked":
            logger.warning("[PermissionManager] Action '%s' blocked by locked system policy.", action_name)
            return False

        if self.mode == "strict" and permission_level == "confirm":
            logger.info("[PermissionManager] Action '%s' requires manual user confirmation.", action_name)
            return False  # Requires explicit UI/Telegram confirmation step

        return True
