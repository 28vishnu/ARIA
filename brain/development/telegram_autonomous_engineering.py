from __future__ import annotations

import logging
from typing import Any

from .telegram_engineering_runtime import (
    TelegramEngineeringRuntime,
)

logger = logging.getLogger("aria.telegram_engineering")


class TelegramAutonomousEngineeringInterface:
    """
    Backward-compatible Telegram gateway for Phase 1 engineering.

    The public API is intentionally preserved so existing bootstrap
    and Telegram wiring do not need to change yet.

    Internally, command parsing and authorization are delegated to
    the authoritative Telegram engineering runtime.
    """

    def __init__(
        self,
        phase1_runtime: Any,
        approval_runtime: Any | None = None,
    ) -> None:
        self.phase1_runtime = phase1_runtime
        self.approval_runtime = approval_runtime

        self.runtime = TelegramEngineeringRuntime(
            engineering_runtime=phase1_runtime,
            approval_runtime=approval_runtime,
        )

    # ============================================================
    # Telegram entry point
    # ============================================================

    async def handle(
        self,
        *,
        user_id: Any,
        text: str,
    ) -> dict[str, Any] | None:
        """
        Preserve the legacy dictionary response expected by the
        existing Telegram layer.
        """

        try:
            response = await self.runtime.handle(
                user_id=user_id,
                text=text,
            )

            if response is None:
                return None

            return response.to_dict()

        except Exception as exc:
            logger.exception(
                "[Phase1][TelegramEngineering] "
                "Canonical engineering interface failed"
            )

            return {
                "handled": True,
                "success": False,
                "text": (
                    "🛑 Autonomous engineering failed safely.\n\n"
                    f"Reason: {str(exc)[:1500]}"
                ),
                "error": str(exc),
            }

    # ============================================================
    # Runtime connection
    # ============================================================

    def connect_engineering_runtime(
        self,
        runtime: Any,
    ) -> None:
        """
        Replace the engineering runtime without changing the
        surrounding Telegram integration.
        """

        self.phase1_runtime = runtime

        self.runtime.connect_engineering_runtime(
            runtime
        )

    def connect_approval_runtime(
        self,
        runtime: Any,
    ) -> None:
        """
        Attach the existing approval system.

        This adapter never grants approval itself.
        """

        self.approval_runtime = runtime

        self.runtime.connect_approval_runtime(
            runtime
        )

    # ============================================================
    # Status
    # ============================================================

    def status(self) -> dict[str, Any]:
        try:
            return self.runtime.status()

        except Exception as exc:
            logger.exception(
                "[TelegramEngineering] "
                "Status check failed"
            )

            return {
                "healthy": False,
                "error": str(exc),
            }

    # ============================================================
    # Health
    # ============================================================

    def health(self) -> dict[str, Any]:
        try:
            return self.runtime.health()

        except Exception as exc:
            logger.exception(
                "[TelegramEngineering] "
                "Health check failed"
            )

            return {
                "healthy": False,
                "error": str(exc),
            }


__all__ = [
    "TelegramAutonomousEngineeringInterface",
]