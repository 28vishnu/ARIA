import logging
import time
import asyncio
from typing import Dict, Any
from actions.base import BaseAction, ActionResult
from actions.permissions import PermissionManager
from actions.validator import ActionValidator

logger = logging.getLogger("aria")

class ActionManager:
    def __init__(self, permission_mode: str = "confirm"):
        self.actions: Dict[str, BaseAction] = {}
        self.permissions = PermissionManager(permission_mode)
        self.validator = ActionValidator()

    def register(self, action: BaseAction):
        self.actions[action.name] = action
        logger.info("[ActionManager] Registered action: %s (Permission: %s)", action.name, action.permission_level)

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

        # 1. Evaluate permissions
        #
        # "confirm" actions may execute only after CognitiveCore has
        # explicitly received user confirmation.
        if action.permission_level == "confirm" and not confirmed:
            return ActionResult(
                success=False,
                action_name=action_name,
                error="Action requires explicit user confirmation."
            )

        if action.permission_level != "confirm":
            if not self.permissions.evaluate(
                action.name,
                action.permission_level
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
        max_retries = 2
        attempt = 0
        last_error = None
        start_time = time.perf_counter()

        while attempt <= max_retries:
            try:
                # Wrap execution in asyncio timeout
                async def _run():
                    return await action.execute(params)

                result = await asyncio.wait_for(_run(), timeout=action.timeout_seconds)

                elapsed_ms = (time.perf_counter() - start_time) * 1000
                logger.info("[ActionManager] Action: %s | Success: %s | Time: %.1f ms", action.name, result.success, elapsed_ms)

                if result.success:
                    return result
                else:
                    last_error = result.error
            except asyncio.TimeoutError:
                last_error = f"Action timed out after {action.timeout_seconds}s"
                logger.warning("[ActionManager] Action '%s' timed out (Attempt %d/%d)", action.name, attempt + 1, max_retries + 1)
            except Exception as e:
                last_error = str(e)
                logger.exception("[ActionManager ERROR] Exception executing action '%s'", action.name)

            attempt += 1
            if attempt <= max_retries:
                await asyncio.sleep(1.0 * attempt) # Backoff

        # If all retries failed, attempt rollback
        rolled_back = False
        try:
            rolled_back = await action.rollback(params)
        except Exception:
            pass

        return ActionResult(success=False, action_name=action_name, error=last_error, rolled_back=rolled_back)
