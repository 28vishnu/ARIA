from __future__ import annotations

import logging
from typing import Any

from .autonomous_development_bridge import (
    AutonomousDevelopmentBridge,
)
from .persistent_engineering_runtime import (
    PersistentEngineeringRuntime,
)

logger = logging.getLogger(
    "aria.phase1_persistent_runtime"
)


class Phase1PersistentRuntime:
    """
    Production-facing Phase 1 runtime.

    This is the concrete connection between:

        Telegram
            ↓
        TelegramEngineeringRuntime
            ↓
        PersistentEngineeringRuntime
            ↓
        AutonomousDevelopmentBridge
            ↓
        DevelopmentController
            ↓
        DevelopmentAgent

    The bridge remains the authoritative implementation engine.
    Persistence remains the authoritative recovery boundary.
    """

    VERSION = (
        "PHASE1-PERSISTENT-RUNTIME-V1"
    )

    def __init__(
        self,
        development_controller: Any,
        *,
        timeout_seconds: float = 1800.0,
        persistence: Any | None = None,
    ) -> None:
        if development_controller is None:
            raise ValueError(
                "development_controller is required."
            )

        self.development_controller = (
            development_controller
        )

        self.bridge = (
            AutonomousDevelopmentBridge(
                development_controller,
                timeout_seconds=timeout_seconds,
            )
        )

        self.runtime = (
            PersistentEngineeringRuntime(
                self.bridge,
                persistence=persistence,
            )
        )

    # ==========================================================
    # DEVELOPMENT
    # ==========================================================

    async def develop(
        self,
        requirement: str,
        **kwargs: Any,
    ) -> Any:
        """
        Start autonomous Phase 1 development.
        """

        return await self.runtime.develop(
            requirement,
            **kwargs,
        )

    # ==========================================================
    # RESUME
    # ==========================================================

    async def resume(
        self,
        session_id: str,
        **kwargs: Any,
    ) -> Any:
        """
        Resume an interrupted Phase 1 engineering session.
        """

        return await self.runtime.resume(
            session_id,
            **kwargs,
        )

    # ==========================================================
    # STATUS
    # ==========================================================

    async def engineering_status(
        self,
        session_id: str,
    ) -> dict[str, Any]:
        return await self.runtime.status(
            session_id
        )

    async def recoverable_sessions(
        self,
    ) -> tuple[str, ...]:
        return await self.runtime.recoverable_sessions()

    # ==========================================================
    # CHECKPOINT
    # ==========================================================

    async def checkpoint(
        self,
        session_id: str,
    ) -> bool:
        return await self.runtime.checkpoint(
            session_id
        )

    # ==========================================================
    # LEGACY STATUS
    # ==========================================================

    def status(
        self,
    ) -> dict[str, Any]:
        try:
            bridge_status = (
                self.bridge.status()
                if hasattr(
                    self.bridge,
                    "status",
                )
                else {}
            )

            return {
                "healthy": True,
                "runtime_version": self.VERSION,
                "bridge": bridge_status,
                "persistent_runtime": True,
            }

        except Exception as exc:
            logger.exception(
                "[Phase1PersistentRuntime] "
                "Status failed."
            )

            return {
                "healthy": False,
                "runtime_version": self.VERSION,
                "persistent_runtime": True,
                "error": str(exc),
            }

    def health(
        self,
    ) -> dict[str, Any]:
        try:
            bridge_health = (
                self.bridge.health()
                if hasattr(
                    self.bridge,
                    "health",
                )
                else {}
            )

            return {
                "healthy": True,
                "runtime_version": self.VERSION,
                "bridge": bridge_health,
                "persistent_runtime": True,
            }

        except Exception as exc:
            logger.exception(
                "[Phase1PersistentRuntime] "
                "Health failed."
            )

            return {
                "healthy": False,
                "runtime_version": self.VERSION,
                "persistent_runtime": True,
                "error": str(exc),
            }


__all__ = [
    "Phase1PersistentRuntime",
]