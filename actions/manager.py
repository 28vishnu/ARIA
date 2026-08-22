import asyncio
import logging
import time
from typing import Any, Dict

from actions.base import ActionResult, BaseAction
from actions.permissions import PermissionManager
from actions.validator import ActionValidator

logger = logging.getLogger("aria")

NON_RETRYABLE_ACTION_ERRORS = [
    "not found",
    "permission",
    "validation failed",
    "blocked",
    "invalid",
    "does not exist",
    "rate-limited",
    "rate limited",
    "too many requests",
]

class ActionManager:
    def __init__(self, permission_mode: str = "confirm"):
        self.actions: Dict[str, BaseAction] = {}
        self.permissions = PermissionManager(permission_mode)
        self.validator = ActionValidator()

    def register(self, action: BaseAction):
        self.actions[action.name] = action

        logger.info(
            "[ActionManager] Registered action: %s (Permission: %s)",
            action.name,
            action.permission_level
        )

    def get_capabilities(self) -> Dict[str, Dict[str, Any]]:
        """
        Return the actions currently available to ARIA.

        This allows reasoning/planning layers to discover capabilities
        dynamically instead of hard-coding action names.
        """

        capabilities = {}

        for name, action in self.actions.items():
            capabilities[name] = {
                "name": name,
                "permission_level": getattr(
                    action,
                    "permission_level",
                    "confirm",
                ),
                "description": getattr(
                    action,
                    "description",
                    "",
                ),
                "timeout_seconds": getattr(
                    action,
                    "timeout_seconds",
                    None,
                ),
                "supports_rollback": callable(
                    getattr(action, "rollback", None)
                ),
            }

        return capabilities

    def has_action(self, action_name: str) -> bool:
        """
        Check whether an action actually exists.
        """

        return (
            isinstance(action_name, str)
            and action_name in self.actions
        )

    async def execute_decision(
        self,
        decision: Dict[str, Any],
        confirmed: bool = False,
    ) -> ActionResult:
        """
        Execute an action selected by ARIA's cognitive decision layer.

        This is the controlled boundary between:
            CognitiveCore -> ActionManager

        The ActionManager remains responsible for:
            - action existence
            - parameter normalization
            - permissions
            - validation
            - timeout
            - rollback

        The LLM must never call actions directly.
        """

        if not isinstance(decision, dict):
            return ActionResult(
                success=False,
                action_name="",
                error="Invalid cognitive decision.",
            )

        action_name = decision.get("action")

        if not isinstance(action_name, str):
            action_name = ""

        action_name = action_name.strip()

        if not action_name:
            return ActionResult(
                success=False,
                action_name="",
                error="No action was selected by the cognitive layer.",
            )

        if not self.has_action(action_name):
            logger.warning(
                "[ActionManager] Cognitive decision selected "
                "unknown action: %s",
                action_name,
            )

            return ActionResult(
                success=False,
                action_name=action_name,
                error=(
                    f"Action '{action_name}' is not available."
                ),
            )

        params = decision.get("params", {})

        if params is None:
            params = {}

        if not isinstance(params, dict):
            return ActionResult(
                success=False,
                action_name=action_name,
                error=(
                    f"Invalid parameters supplied for "
                    f"action '{action_name}'."
                ),
            )

        logger.info(
            "[ActionManager] Executing cognitive decision: "
            "action=%s confirmed=%s",
            action_name,
            confirmed,
        )

        return await self.execute_action(
            action_name=action_name,
            params=params,
            confirmed=confirmed,
        )

    async def execute_action(
        self,
        action_name: str,
        params: Dict[str, Any],
        confirmed: bool = False
    ) -> ActionResult:
        """Manages permissions, validation, timeout handling, retries, and rollbacks for system actions."""
        if action_name not in self.actions:
            return ActionResult(success=False, action_name=action_name, error=f"Action '{action_name}' not found.")

        action = self.actions[action_name]

        # Phase 3 defensive parameter isolation.
        params = dict(params or {})

        logger.debug(
            "[ActionManager] Parameters prepared for action '%s': keys=%s",
            action_name,
            list(params.keys()),
        )

        # 1. Evaluate permissions
        #
        # Some actions have operation-specific permissions.
        # File reads are non-destructive and may run without confirmation.
        # File writes remain confirmation-protected.

        effective_permission = action.permission_level

        if action.name == "file_action":
            file_mode = str(params.get("mode", "")).lower().strip()

            if file_mode == "read":
                effective_permission = "safe"

            elif file_mode == "write":
                effective_permission = "confirm"

        if effective_permission == "confirm" and not confirmed:
            return ActionResult(
                success=False,
                action_name=action_name,
                error="Action requires explicit user confirmation."
            )

        if effective_permission != "confirm":
            if not self.permissions.evaluate(
                action.name,
                effective_permission
            ):
                return ActionResult(
                    success=False,
                    action_name=action_name,
                    error="Action blocked by permission policy."
                )

        # 2. Validate parameters
        if not await self.validator.validate_params(action.name, action, params):
            return ActionResult(success=False, action_name=action_name, error="Parameter validation failed.")

        # 3. Execute with timeout, retries, and rollback support
        # Phase 3: Task-level retries are controlled by Executor.
        # ActionManager executes an action once to prevent duplicate side effects.
        max_retries = 0
        attempt = 0
        last_error = None
        execution_started = False
        start_time = time.perf_counter()

        while attempt <= max_retries:
            try:
                # Wrap execution in asyncio timeout
                async def _run():
                    return await action.execute(params)

                execution_started = True

                result = await asyncio.wait_for(_run(), timeout=action.timeout_seconds)

                elapsed_ms = (time.perf_counter() - start_time) * 1000
                logger.info("[ActionManager] Action: %s | Success: %s | Time: %.1f ms", action.name, result.success, elapsed_ms)

                if result.success:
                    return result

                last_error = result.error or "Action execution failed."

                normalized_error = last_error.lower()

                if any(
                    phrase in normalized_error
                    for phrase in NON_RETRYABLE_ACTION_ERRORS
                ):
                    logger.warning(
                        "[ActionManager] Non-retryable failure for '%s': %s",
                        action.name,
                        last_error,
                    )
                    break
            except asyncio.TimeoutError:
                last_error = f"Action timed out after {action.timeout_seconds}s"
                logger.warning("[ActionManager] Action '%s' timed out.", action.name)
            except Exception as e:
                last_error = str(e)
                logger.exception("[ActionManager ERROR] Exception executing action '%s'", action.name)

            attempt += 1

        # If execution started, attempt rollback
        rolled_back = False
        if execution_started:
            try:
                rolled_back = await action.rollback(params)
            except Exception:
                logger.exception(
                    "[ActionManager] Rollback failed for '%s'",
                    action_name,
                )

        return ActionResult(
            success=False,
            action_name=action_name,
            error=last_error or "Action execution failed.",
            rolled_back=rolled_back,
        )
