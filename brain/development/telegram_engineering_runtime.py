from __future__ import annotations

import logging
from typing import Any

from .telegram_engineering_interface import (
    TelegramEngineeringCommandInterface,
)
from .contracts.telegram_engineering import (
    TelegramEngineeringRequest,
    TelegramEngineeringResponse,
)

logger = logging.getLogger("aria.telegram_engineering_runtime")


class TelegramEngineeringRuntime:
    """
    Runtime adapter between Telegram and ARIA's authoritative
    engineering system.

    This layer owns no engineering logic.

    Flow:

        Telegram
            ↓
        TelegramEngineeringCommandInterface
            ↓
        Engineering runtime
            ↓
        Authoritative engineering lifecycle

    Safety-sensitive operations remain behind their existing
    approval gates.
    """

    def __init__(
        self,
        *,
        engineering_runtime: Any | None = None,
        approval_runtime: Any | None = None,
        authorized_user_id: str | None = None,
    ) -> None:
        self.engineering_runtime = engineering_runtime
        self.approval_runtime = approval_runtime

        self.interface = (
            TelegramEngineeringCommandInterface(
                authorized_user_id=authorized_user_id,
                execution_gateway=engineering_runtime,
                approval_gateway=approval_runtime,
            )
        )

    # ============================================================
    # Telegram entry point
    # ============================================================

    async def handle(
        self,
        *,
        user_id: Any,
        text: str,
    ) -> TelegramEngineeringResponse | None:
        """
        Handle one Telegram message.

        Ordinary Telegram messages return None so the normal
        conversational pipeline can continue processing them.
        """

        request = self.interface.parse(
            user_id=user_id,
            text=text,
        )

        if request is None:
            return None

        validation = self.interface.validate(
            request
        )

        if validation is not None:
            return validation

        return await self._dispatch(request)

    # ============================================================
    # Authoritative dispatch
    # ============================================================

    async def _dispatch(
        self,
        request: TelegramEngineeringRequest,
    ) -> TelegramEngineeringResponse:
        """
        Dispatch only after the command boundary has parsed and
        authorized the request.
        """

        try:
            return await self.interface.handle(
                user_id=request.user_id,
                text=request.raw_text,
            )

        except Exception as exc:
            logger.exception(
                "[TelegramEngineeringRuntime] "
                "Engineering dispatch failed"
            )

            return TelegramEngineeringResponse(
                handled=True,
                success=False,
                text=(
                    "🛑 ARIA engineering stopped safely.\n\n"
                    f"Reason: {str(exc)[:1500]}"
                ),
                command=request.command,
                action=request.action,
                session_id=request.session_id,
                error=str(exc),
            )

    # ============================================================
    # Runtime connection
    # ============================================================

    def connect_engineering_runtime(
        self,
        runtime: Any,
    ) -> None:
        """
        Attach the authoritative engineering runtime.

        This does not execute anything.
        """

        self.engineering_runtime = runtime

        self.interface.execution_gateway = runtime

    def connect_approval_runtime(
        self,
        runtime: Any,
    ) -> None:
        """
        Attach the approval runtime.

        Approval decisions continue through the existing approval
        system; this adapter never grants authorization itself.
        """

        self.approval_runtime = runtime

        self.interface.approval_gateway = runtime

    # ============================================================
    # Status / health
    # ============================================================

    def status(self) -> dict[str, Any]:
        interface_status = (
            self.interface.status()
        )

        return {
            "healthy": bool(
                interface_status.get(
                    "healthy",
                    False,
                )
            ),
            "name": "telegram_engineering_runtime",
            "interface": interface_status,
            "engineering_runtime_connected": (
                self.engineering_runtime is not None
            ),
            "approval_runtime_connected": (
                self.approval_runtime is not None
            ),
        }

    def health(self) -> dict[str, Any]:
        status = self.status()

        return {
            "healthy": bool(
                status.get(
                    "healthy",
                    False,
                )
            ),
            "engineering_runtime_connected": (
                self.engineering_runtime is not None
            ),
            "approval_runtime_connected": (
                self.approval_runtime is not None
            ),
        }


__all__ = [
    "TelegramEngineeringRuntime",
]