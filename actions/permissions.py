import logging
from typing import Literal

logger = logging.getLogger("aria")

PermissionDecision = Literal[
    "allow",
    "confirm",
    "deny",
]


class PermissionManager:
    def __init__(self, default_mode: str = "confirm"):
        # Modes:
        # autonomous -> safe actions execute automatically;
        #              confirm-level actions require confirmation
        # strict     -> every non-safe action requires confirmation
        # locked     -> only safe actions are allowed
        self.mode = default_mode

    def evaluate(
        self,
        action_name: str,
        permission_level: str,
    ) -> PermissionDecision:
        """
        Evaluate whether an action may execute.

        Returns:
            "allow"   -> execute immediately
            "confirm" -> pause and request user confirmation
            "deny"    -> reject execution
        """

        # Explicitly denied actions always remain denied.
        if permission_level == "deny":
            logger.warning(
                "[PermissionManager] Action '%s' is explicitly denied.",
                action_name,
            )
            return "deny"

        # Safe actions can always execute.
        if permission_level == "safe":
            return "allow"

        # Locked mode allows only safe actions.
        if self.mode == "locked":
            logger.warning(
                "[PermissionManager] Action '%s' blocked by locked system policy.",
                action_name,
            )
            return "deny"

        # Strict mode requires confirmation for non-safe actions.
        if self.mode == "strict":
            logger.info(
                "[PermissionManager] Action '%s' requires confirmation in strict mode.",
                action_name,
            )
            return "confirm"

        # Normal/autonomous mode:
        # confirm-level actions pause for user approval.
        if permission_level == "confirm":
            logger.info(
                "[PermissionManager] Action '%s' requires user confirmation.",
                action_name,
            )
            return "confirm"

        # Unknown permission levels should fail closed.
        logger.warning(
            "[PermissionManager] Unknown permission level '%s' for action '%s'.",
            permission_level,
            action_name,
        )
        return "deny"