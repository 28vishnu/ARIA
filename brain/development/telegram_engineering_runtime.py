from __future__ import annotations

import inspect
import logging
from typing import Any

from .contracts import (
    TelegramAuthorizationStatus,
    TelegramEngineeringAction,
    TelegramEngineeringCommand,
    TelegramEngineeringRequest,
    TelegramEngineeringResponse,
)
from .persistent_engineering_runtime import (
    PersistentEngineeringRuntime,
)

logger = logging.getLogger(
    "aria.telegram_engineering_runtime"
)


class TelegramEngineeringRuntime:
    """
    Canonical Telegram gateway for ARIA's autonomous engineering system.

    Supported commands:

        /master develop <requirement>
        /master resume <session_id>
        /master status
        /master status <session_id>
        /master approvals
        /master approve <approval_id>
        /master reject <approval_id>
        /master cancel <session_id>
        /master self-upgrade <requirement>
        /master help

    The runtime is intentionally an adapter.

    It does not:
        - directly modify repository files
        - execute arbitrary commands
        - push GitHub without authorization
        - deploy without authorization

    Those responsibilities remain behind the authoritative engineering
    and permission boundaries.
    """

    VERSION = (
        "TELEGRAM-ENGINEERING-RUNTIME-V1"
    )

    def __init__(
        self,
        engineering_runtime: Any | None = None,
        approval_runtime: Any | None = None,
        *,
        persistent_runtime: (
            PersistentEngineeringRuntime | None
        ) = None,
        allowed_user_id: Any | None = None,
    ) -> None:
        self.engineering_runtime = (
            engineering_runtime
        )

        self.approval_runtime = (
            approval_runtime
        )

        self.persistent_runtime = (
            persistent_runtime
        )

        self.allowed_user_id = (
            allowed_user_id
            if allowed_user_id is not None
            else self._configured_user_id()
        )

    # ==========================================================
    # CONNECTION
    # ==========================================================

    def connect_engineering_runtime(
        self,
        runtime: Any,
    ) -> None:
        self.engineering_runtime = runtime
        self.persistent_runtime = None

    def connect_approval_runtime(
        self,
        runtime: Any,
    ) -> None:
        self.approval_runtime = runtime

    # ==========================================================
    # MAIN HANDLER
    # ==========================================================

    async def handle(
        self,
        *,
        user_id: Any,
        text: str,
    ) -> TelegramEngineeringResponse | None:
        request = self._parse(
            user_id=user_id,
            text=text,
        )

        if request.command == TelegramEngineeringCommand.NONE:
            return None

        if (
            request.authorization
            == TelegramAuthorizationStatus.UNAUTHORIZED
        ):
            return TelegramEngineeringResponse(
                handled=True,
                success=False,
                text=(
                    "⛔ Unauthorized.\n\n"
                    "Autonomous engineering commands are "
                    "restricted to the authorized Master."
                ),
                command=request.command,
                action=request.action,
                error="unauthorized",
            )

        if (
            request.authorization
            == TelegramAuthorizationStatus.NOT_CONFIGURED
        ):
            return TelegramEngineeringResponse(
                handled=True,
                success=False,
                text=(
                    "🛑 Autonomous engineering is blocked "
                    "because the Master authorization is not "
                    "configured."
                ),
                command=request.command,
                action=request.action,
                error="authorization_not_configured",
            )

        try:
            return await self._dispatch(
                request
            )

        except Exception as exc:
            logger.exception(
                "[TelegramEngineeringRuntime] "
                "Command execution failed."
            )

            return TelegramEngineeringResponse(
                handled=True,
                success=False,
                text=(
                    "🛑 Autonomous engineering command "
                    "failed safely.\n\n"
                    f"Reason: {str(exc)[:1500]}"
                ),
                command=request.command,
                action=request.action,
                session_id=request.session_id,
                error=str(exc),
            )

    # ==========================================================
    # DISPATCH
    # ==========================================================

    async def _dispatch(
        self,
        request: TelegramEngineeringRequest,
    ) -> TelegramEngineeringResponse:
        if request.action == (
            TelegramEngineeringAction.SHOW_HELP
        ):
            return self._help_response(
                request
            )

        if request.action == (
            TelegramEngineeringAction.START_ENGINEERING
        ):
            return await self._develop(
                request
            )

        if request.action == (
            TelegramEngineeringAction.RESUME_ENGINEERING
        ):
            return await self._resume(
                request
            )

        if request.action == (
            TelegramEngineeringAction.SHOW_STATUS
        ):
            return await self._status(
                request
            )

        if request.action == (
            TelegramEngineeringAction.APPROVE_OPERATION
        ):
            return await self._approval(
                request,
                approve=True,
            )

        if request.action == (
            TelegramEngineeringAction.REJECT_OPERATION
        ):
            return await self._approval(
                request,
                approve=False,
            )

        if request.action == (
            TelegramEngineeringAction.CANCEL_ENGINEERING
        ):
            return await self._cancel(
                request
            )

        if request.action == (
            TelegramEngineeringAction.PLAN_SELF_UPGRADE
        ):
            return await self._self_upgrade(
                request
            )

        return TelegramEngineeringResponse(
            handled=True,
            success=False,
            text=(
                "I understood the engineering command, "
                "but no execution action is registered."
            ),
            command=request.command,
            action=request.action,
            error="unsupported_action",
        )

    # ==========================================================
    # DEVELOP
    # ==========================================================

    async def _develop(
        self,
        request: TelegramEngineeringRequest,
    ) -> TelegramEngineeringResponse:
        requirement = (
            request.requirement_text
            or ""
        ).strip()

        if not requirement:
            return TelegramEngineeringResponse(
                handled=True,
                success=False,
                text=(
                    "⚠️ Missing engineering requirement.\n\n"
                    "Example:\n"
                    "/master develop Build Phase 2 completely "
                    "according to the specification."
                ),
                command=request.command,
                action=request.action,
                error="missing_requirement",
            )

        runtime = (
            await self._persistent()
        )

        result = await runtime.develop(
            requirement,
        )

        success = bool(
            getattr(
                result,
                "success",
                False,
            )
        )

        session_id = str(
            getattr(
                result,
                "session_id",
                "",
            )
            or ""
        )

        status = str(
            getattr(
                result,
                "status",
                "unknown",
            )
        )

        if success:
            text = (
                "✅ Autonomous engineering completed.\n\n"
                f"Session: `{session_id}`\n"
                f"Status: `{status}`"
            )
        else:
            error = getattr(
                result,
                "error",
                None,
            )

            text = (
                "⚠️ Autonomous engineering did not "
                "reach acceptance.\n\n"
                f"Session: `{session_id}`\n"
                f"Status: `{status}`"
            )

            if error:
                text += (
                    "\n"
                    f"Reason: {str(error)[:1200]}"
                )

            if session_id:
                text += (
                    "\n\n"
                    "The session has been persisted. "
                    "Use:\n"
                    f"`/master resume {session_id}`"
                )

        return TelegramEngineeringResponse(
            handled=True,
            success=success,
            text=text,
            command=request.command,
            action=request.action,
            session_id=session_id,
            status=status,
            result=result,
            error=(
                None
                if success
                else getattr(
                    result,
                    "error",
                    None,
                )
            ),
            metadata={
                "runtime_version": self.VERSION,
                "resumed": False,
            },
        )

    # ==========================================================
    # RESUME
    # ==========================================================

    async def _resume(
        self,
        request: TelegramEngineeringRequest,
    ) -> TelegramEngineeringResponse:
        session_id = (
            request.session_id
            or ""
        ).strip()

        if not session_id:
            return TelegramEngineeringResponse(
                handled=True,
                success=False,
                text=(
                    "⚠️ Missing session ID.\n\n"
                    "Use:\n"
                    "`/master resume <session_id>`"
                ),
                command=request.command,
                action=request.action,
                error="missing_session_id",
            )

        runtime = (
            await self._persistent()
        )

        result = await runtime.resume(
            session_id
        )

        success = bool(
            getattr(
                result,
                "success",
                False,
            )
        )

        status = str(
            getattr(
                result,
                "status",
                "unknown",
            )
        )

        error = getattr(
            result,
            "error",
            None,
        )

        if success:
            text = (
                "✅ Engineering session resumed "
                "and reached acceptance.\n\n"
                f"Session: `{session_id}`\n"
                f"Status: `{status}`"
            )

        elif status == "not_found":
            text = (
                "❌ Engineering session was not found.\n\n"
                f"Session: `{session_id}`"
            )

        else:
            text = (
                "⚠️ Engineering session resumed, but "
                "acceptance has not been reached.\n\n"
                f"Session: `{session_id}`\n"
                f"Status: `{status}`"
            )

            if error:
                text += (
                    "\n"
                    f"Reason: {str(error)[:1200]}"
                )

        return TelegramEngineeringResponse(
            handled=True,
            success=success,
            text=text,
            command=request.command,
            action=request.action,
            session_id=session_id,
            status=status,
            result=result,
            error=(
                None
                if success
                else error
            ),
            metadata={
                "runtime_version": self.VERSION,
                "resumed": True,
            },
        )

    # ==========================================================
    # STATUS
    # ==========================================================

    async def _status(
        self,
        request: TelegramEngineeringRequest,
    ) -> TelegramEngineeringResponse:
        runtime = (
            await self._persistent()
        )

        session_id = (
            request.session_id
            or ""
        ).strip()

        if session_id:
            status = await runtime.status(
                session_id
            )

            if not status.get(
                "found",
                False,
            ):
                text = (
                    "ℹ️ Engineering session not found.\n\n"
                    f"Session: `{session_id}`"
                )

                return TelegramEngineeringResponse(
                    handled=True,
                    success=False,
                    text=text,
                    command=request.command,
                    action=request.action,
                    session_id=session_id,
                    status="not_found",
                )

            text = self._format_status(
                status
            )

            return TelegramEngineeringResponse(
                handled=True,
                success=True,
                text=text,
                command=request.command,
                action=request.action,
                session_id=session_id,
                status=str(
                    status.get(
                        "status",
                        "unknown",
                    )
                ),
                result=status,
            )

        sessions = (
            await runtime.recoverable_sessions()
        )

        if not sessions:
            return TelegramEngineeringResponse(
                handled=True,
                success=True,
                text=(
                    "ℹ️ No persisted engineering "
                    "sessions found."
                ),
                command=request.command,
                action=request.action,
                status="empty",
            )

        lines = [
            "🧠 Persisted engineering sessions:",
            "",
        ]

        for item in sessions[
            -20:
        ]:
            lines.append(
                f"• `{item}`"
            )

        lines.extend(
            [
                "",
                "Use:",
                "`/master status <session_id>`",
                "or",
                "`/master resume <session_id>`",
            ]
        )

        return TelegramEngineeringResponse(
            handled=True,
            success=True,
            text="\n".join(
                lines
            ),
            command=request.command,
            action=request.action,
            status="available",
            result={
                "sessions": list(
                    sessions
                )
            },
        )

    # ==========================================================
    # APPROVALS
    # ==========================================================

    async def _approval(
        self,
        request: TelegramEngineeringRequest,
        *,
        approve: bool,
    ) -> TelegramEngineeringResponse:
        runtime = (
            self.approval_runtime
        )

        if runtime is None:
            return TelegramEngineeringResponse(
                handled=True,
                success=False,
                text=(
                    "🛑 Approval runtime is not connected."
                ),
                command=request.command,
                action=request.action,
                error="approval_runtime_missing",
            )

        approval_id = (
            request.approval_id
            or ""
        ).strip()

        if not approval_id:
            return TelegramEngineeringResponse(
                handled=True,
                success=False,
                text=(
                    "⚠️ Missing approval ID."
                ),
                command=request.command,
                action=request.action,
                error="missing_approval_id",
            )

        method_names = (
            (
                "approve",
                "approve_request",
                "approve_operation",
            )
            if approve
            else (
                "reject",
                "reject_request",
                "reject_operation",
            )
        )

        result = await self._invoke_named(
            runtime,
            method_names,
            approval_id,
        )

        success = self._extract_success(
            result
        )

        action_word = (
            "approved"
            if approve
            else "rejected"
        )

        return TelegramEngineeringResponse(
            handled=True,
            success=success,
            text=(
                (
                    "✅"
                    if success
                    else "⚠️"
                )
                + f" Approval `{approval_id}` "
                f"{action_word}."
            ),
            command=request.command,
            action=request.action,
            result=result,
            error=(
                None
                if success
                else self._extract_error(
                    result
                )
            ),
        )

    # ==========================================================
    # CANCEL
    # ==========================================================

    async def _cancel(
        self,
        request: TelegramEngineeringRequest,
    ) -> TelegramEngineeringResponse:
        session_id = (
            request.session_id
            or ""
        ).strip()

        if not session_id:
            return TelegramEngineeringResponse(
                handled=True,
                success=False,
                text=(
                    "⚠️ Missing session ID."
                ),
                command=request.command,
                action=request.action,
                error="missing_session_id",
            )

        runtime = (
            self.engineering_runtime
        )

        if runtime is None:
            return TelegramEngineeringResponse(
                handled=True,
                success=False,
                text=(
                    "🛑 Engineering runtime is not connected."
                ),
                command=request.command,
                action=request.action,
                session_id=session_id,
                error="engineering_runtime_missing",
            )

        result = await self._invoke_named(
            runtime,
            (
                "cancel",
                "cancel_session",
                "stop",
            ),
            session_id,
        )

        success = self._extract_success(
            result
        )

        return TelegramEngineeringResponse(
            handled=True,
            success=success,
            text=(
                "✅ Engineering session cancellation "
                "requested."
                if success
                else
                "⚠️ Engineering session could not "
                "be cancelled."
            ),
            command=request.command,
            action=request.action,
            session_id=session_id,
            result=result,
            error=(
                None
                if success
                else self._extract_error(
                    result
                )
            ),
        )

    # ==========================================================
    # SELF-UPGRADE
    # ==========================================================

    async def _self_upgrade(
        self,
        request: TelegramEngineeringRequest,
    ) -> TelegramEngineeringResponse:
        runtime = (
            self.engineering_runtime
        )

        if runtime is None:
            return TelegramEngineeringResponse(
                handled=True,
                success=False,
                text=(
                    "🛑 Engineering runtime is not connected."
                ),
                command=request.command,
                action=request.action,
                error="engineering_runtime_missing",
            )

        requirement = (
            request.requirement_text
            or ""
        ).strip()

        if not requirement:
            return TelegramEngineeringResponse(
                handled=True,
                success=False,
                text=(
                    "⚠️ Missing self-upgrade requirement."
                ),
                command=request.command,
                action=request.action,
                error="missing_requirement",
            )

        result = await self._invoke_named(
            runtime,
            (
                "self_upgrade",
                "plan_self_upgrade",
                "upgrade",
            ),
            requirement,
        )

        success = self._extract_success(
            result
        )

        return TelegramEngineeringResponse(
            handled=True,
            success=success,
            text=(
                (
                    "🧠 Self-upgrade request accepted "
                    "for engineering analysis."
                    if success
                    else
                    "⚠️ Self-upgrade request could not "
                    "be accepted."
                )
            ),
            command=request.command,
            action=request.action,
            result=result,
            error=(
                None
                if success
                else self._extract_error(
                    result
                )
            ),
        )

    # ==========================================================
    # PERSISTENT RUNTIME
    # ==========================================================

    async def _persistent(
        self,
    ) -> PersistentEngineeringRuntime:
        if self.persistent_runtime is not None:
            return self.persistent_runtime

        if self.engineering_runtime is None:
            raise RuntimeError(
                "Engineering runtime is not connected."
            )

        self.persistent_runtime = (
            PersistentEngineeringRuntime(
                self.engineering_runtime
            )
        )

        return self.persistent_runtime

    # ==========================================================
    # PARSING
    # ==========================================================

    def _parse(
        self,
        *,
        user_id: Any,
        text: str,
    ) -> TelegramEngineeringRequest:
        raw = str(
            text or ""
        ).strip()

        authorization = (
            self._authorization(
                user_id
            )
        )

        if not raw.lower().startswith(
            "/master"
        ) and not raw.lower().startswith(
            "master "
        ) and raw.lower() != "master":
            return TelegramEngineeringRequest(
                command=TelegramEngineeringCommand.NONE,
                action=TelegramEngineeringAction.IGNORE,
                raw_text=raw,
                user_id=str(
                    user_id
                ),
                authorization=authorization,
            )

        normalized = raw

        if normalized.lower().startswith(
            "/master"
        ):
            normalized = normalized[
                len("/master"):
            ].strip()

        elif normalized.lower().startswith(
            "master"
        ):
            normalized = normalized[
                len("master"):
            ].strip()

        if not normalized:
            return TelegramEngineeringRequest(
                command=TelegramEngineeringCommand.HELP,
                action=TelegramEngineeringAction.SHOW_HELP,
                raw_text=raw,
                user_id=str(
                    user_id
                ),
                authorization=authorization,
            )

        parts = normalized.split(
            maxsplit=1
        )

        command_text = (
            parts[0]
            .strip()
            .lower()
        )

        remainder = (
            parts[1].strip()
            if len(parts) > 1
            else ""
        )

        command_map = {
            "develop": (
                TelegramEngineeringCommand.DEVELOP,
                TelegramEngineeringAction.START_ENGINEERING,
            ),
            "resume": (
                TelegramEngineeringCommand.RESUME,
                TelegramEngineeringAction.RESUME_ENGINEERING,
            ),
            "status": (
                TelegramEngineeringCommand.STATUS,
                TelegramEngineeringAction.SHOW_STATUS,
            ),
            "approvals": (
                TelegramEngineeringCommand.STATUS,
                TelegramEngineeringAction.SHOW_STATUS,
            ),
            "approve": (
                TelegramEngineeringCommand.APPROVE,
                TelegramEngineeringAction.APPROVE_OPERATION,
            ),
            "reject": (
                TelegramEngineeringCommand.REJECT,
                TelegramEngineeringAction.REJECT_OPERATION,
            ),
            "cancel": (
                TelegramEngineeringCommand.CANCEL,
                TelegramEngineeringAction.CANCEL_ENGINEERING,
            ),
            "self-upgrade": (
                TelegramEngineeringCommand.SELF_UPGRADE,
                TelegramEngineeringAction.PLAN_SELF_UPGRADE,
            ),
            "self_upgrade": (
                TelegramEngineeringCommand.SELF_UPGRADE,
                TelegramEngineeringAction.PLAN_SELF_UPGRADE,
            ),
            "help": (
                TelegramEngineeringCommand.HELP,
                TelegramEngineeringAction.SHOW_HELP,
            ),
        }

        command, action = command_map.get(
            command_text,
            (
                TelegramEngineeringCommand.NONE,
                TelegramEngineeringAction.IGNORE,
            ),
        )

        session_id = None
        approval_id = None
        requirement = None

        if command in {
            TelegramEngineeringCommand.RESUME,
            TelegramEngineeringCommand.CANCEL,
        }:
            session_id = remainder

        elif command in {
            TelegramEngineeringCommand.APPROVE,
            TelegramEngineeringCommand.REJECT,
        }:
            approval_id = remainder

        elif command in {
            TelegramEngineeringCommand.DEVELOP,
            TelegramEngineeringCommand.SELF_UPGRADE,
        }:
            requirement = remainder

        elif command == (
            TelegramEngineeringCommand.STATUS
        ):
            session_id = (
                remainder
                or None
            )

        return TelegramEngineeringRequest(
            command=command,
            action=action,
            raw_text=raw,
            requirement_text=requirement,
            session_id=session_id,
            approval_id=approval_id,
            user_id=str(
                user_id
            ),
            authorization=authorization,
        )

    # ==========================================================
    # AUTHORIZATION
    # ==========================================================

    def _authorization(
        self,
        user_id: Any,
    ) -> TelegramAuthorizationStatus:
        configured = self.allowed_user_id

        if configured is None:
            return (
                TelegramAuthorizationStatus.NOT_CONFIGURED
            )

        return (
            TelegramAuthorizationStatus.AUTHORIZED
            if str(user_id).strip()
            == str(configured).strip()
            else
            TelegramAuthorizationStatus.UNAUTHORIZED
        )

    @staticmethod
    def _configured_user_id() -> Any | None:
        import os

        for key in (
            "ALLOWED_TELEGRAM_USER_ID",
            "TELEGRAM_MASTER_USER_ID",
            "MASTER_TELEGRAM_USER_ID",
        ):
            value = os.getenv(
                key
            )

            if value:
                return value.strip()

        return None

    # ==========================================================
    # HELP
    # ==========================================================

    @staticmethod
    def _help_response(
        request: TelegramEngineeringRequest,
    ) -> TelegramEngineeringResponse:
        return TelegramEngineeringResponse(
            handled=True,
            success=True,
            text=(
                "🧠 ARIA Autonomous Engineering\n\n"
                "Start:\n"
                "`/master develop <requirement>`\n\n"
                "Resume:\n"
                "`/master resume <session_id>`\n\n"
                "Status:\n"
                "`/master status`\n"
                "`/master status <session_id>`\n\n"
                "Approvals:\n"
                "`/master approvals`\n"
                "`/master approve <approval_id>`\n"
                "`/master reject <approval_id>`\n\n"
                "Cancel:\n"
                "`/master cancel <session_id>`\n\n"
                "Self-upgrade:\n"
                "`/master self-upgrade <requirement>`\n\n"
                "ARIA persists engineering sessions and "
                "evidence so interrupted work can be resumed."
            ),
            command=request.command,
            action=request.action,
        )

    # ==========================================================
    # STATUS FORMATTING
    # ==========================================================

    @staticmethod
    def _format_status(
        status: dict[str, Any],
    ) -> str:
        return (
            "🧠 Engineering session\n\n"
            f"Session: `{status.get('session_id', '')}`\n"
            f"Status: `{status.get('status', 'unknown')}`\n"
            f"Phase: `{status.get('phase', 'unknown')}`\n"
            f"Evidence: `{status.get('evidence_count', 0)}`\n"
            f"Terminal: `{status.get('terminal', False)}`\n"
            f"Accepted: `{status.get('success', False)}`"
        )

    # ==========================================================
    # GENERIC COMPATIBILITY INVOCATION
    # ==========================================================

    @staticmethod
    async def _invoke_named(
        runtime: Any,
        names: tuple[str, ...],
        argument: Any,
    ) -> Any:
        for name in names:
            method = getattr(
                runtime,
                name,
                None,
            )

            if not callable(method):
                continue

            result = method(
                argument
            )

            if inspect.isawaitable(
                result
            ):
                result = await result

            return result

        raise RuntimeError(
            "Connected runtime does not expose any "
            f"compatible method: {', '.join(names)}"
        )

    @staticmethod
    def _extract_success(
        result: Any,
    ) -> bool:
        if isinstance(
            result,
            bool,
        ):
            return result

        value = getattr(
            result,
            "success",
            None,
        )

        if value is not None:
            return bool(value)

        if isinstance(
            result,
            dict,
        ):
            return bool(
                result.get(
                    "success",
                    False,
                )
            )

        return False

    @staticmethod
    def _extract_error(
        result: Any,
    ) -> str | None:
        for name in (
            "error",
            "errors",
            "failure",
            "message",
        ):
            value = getattr(
                result,
                name,
                None,
            )

            if value:
                return str(
                    value
                )[:2000]

        if isinstance(
            result,
            dict,
        ):
            for name in (
                "error",
                "errors",
                "failure",
                "message",
            ):
                value = result.get(
                    name
                )

                if value:
                    return str(
                        value
                    )[:2000]

        return None

    # ==========================================================
    # HEALTH / STATUS
    # ==========================================================

    def status(
        self,
    ) -> dict[str, Any]:
        return {
            "healthy": (
                self.engineering_runtime
                is not None
            ),
            "runtime_version": self.VERSION,
            "engineering_runtime_connected": (
                self.engineering_runtime
                is not None
            ),
            "approval_runtime_connected": (
                self.approval_runtime
                is not None
            ),
            "persistent_runtime_connected": (
                self.persistent_runtime
                is not None
            ),
        }

    def health(
        self,
    ) -> dict[str, Any]:
        return self.status()


__all__ = [
    "TelegramEngineeringRuntime",
]