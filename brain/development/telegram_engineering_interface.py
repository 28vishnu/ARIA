from __future__ import annotations

import logging
import os
import re
from typing import Any

from .contracts.telegram_engineering import (
    TelegramAuthorizationStatus,
    TelegramEngineeringAction,
    TelegramEngineeringCommand,
    TelegramEngineeringRequest,
    TelegramEngineeringResponse,
)

logger = logging.getLogger("aria.telegram_engineering")


class TelegramEngineeringCommandInterface:
    """
    Authoritative Telegram command boundary for ARIA engineering.

    Responsibilities:
        Telegram text
            ↓
        command parsing
            ↓
        authorization classification
            ↓
        canonical engineering request

    This class deliberately does NOT:
        - write files
        - execute shell commands
        - push GitHub
        - merge pull requests
        - deploy
        - bypass approval gates
        - directly mutate production

    Actual execution belongs to the authoritative engineering lifecycle.
    """

    DEVELOP_PREFIXES = (
        "/master develop",
        "master develop",
        "master, develop",
        "/master, develop",
    )

    RESUME_PREFIXES = (
        "/master resume",
        "master resume",
        "master, resume",
        "/master, resume",
    )

    STATUS_COMMANDS = {
        "/master status",
        "master status",
        "master, status",
    }

    APPROVAL_LIST_COMMANDS = {
        "/master approvals",
        "/master approval",
        "master approvals",
        "master approval",
    }

    APPROVE_PREFIXES = (
        "/master approve",
        "master approve",
        "master, approve",
        "/master, approve",
    )

    REJECT_PREFIXES = (
        "/master reject",
        "master reject",
        "master, reject",
        "/master, reject",
    )

    CANCEL_PREFIXES = (
        "/master cancel",
        "master cancel",
        "master, cancel",
    )

    SELF_UPGRADE_PREFIXES = (
        "/master self-upgrade",
        "/master self_upgrade",
        "master self-upgrade",
        "master self_upgrade",
        "master, self-upgrade",
        "master, self_upgrade",
    )

    HELP_COMMANDS = {
        "/master help",
        "master help",
        "master, help",
    }

    def __init__(
        self,
        *,
        authorized_user_id: str | None = None,
        execution_gateway: Any | None = None,
        approval_gateway: Any | None = None,
    ) -> None:
        self.authorized_user_id = (
            str(
                authorized_user_id
                if authorized_user_id is not None
                else os.getenv(
                    "ALLOWED_TELEGRAM_USER_ID",
                    "",
                )
            ).strip()
        )

        self.execution_gateway = execution_gateway
        self.approval_gateway = approval_gateway

    # ============================================================
    # Authorization
    # ============================================================

    def authorization_status(
        self,
        user_id: Any,
    ) -> TelegramAuthorizationStatus:
        configured = bool(self.authorized_user_id)

        if not configured:
            return TelegramAuthorizationStatus.NOT_CONFIGURED

        if str(user_id).strip() == self.authorized_user_id:
            return TelegramAuthorizationStatus.AUTHORIZED

        return TelegramAuthorizationStatus.UNAUTHORIZED

    def authorized(self, user_id: Any) -> bool:
        return (
            self.authorization_status(user_id)
            == TelegramAuthorizationStatus.AUTHORIZED
        )

    # ============================================================
    # Parsing helpers
    # ============================================================

    @staticmethod
    def _clean(text: Any) -> str:
        if not isinstance(text, str):
            return ""

        return re.sub(
            r"\s+",
            " ",
            text.strip(),
        )

    @classmethod
    def _extract_after_prefix(
        cls,
        text: str,
        prefixes: tuple[str, ...],
    ) -> str | None:
        value = cls._clean(text)

        if not value:
            return None

        lowered = value.lower()

        ordered = sorted(
            prefixes,
            key=len,
            reverse=True,
        )

        for prefix in ordered:
            if lowered.startswith(prefix.lower()):
                remainder = value[len(prefix):]

                if remainder.startswith(":"):
                    remainder = remainder[1:]

                return remainder.strip(
                    " \t\r\n:-,"
                ) or None

        return None

    @staticmethod
    def _split_identifier(
        value: str | None,
    ) -> tuple[str | None, str | None]:
        if not value:
            return None, None

        parts = value.split(
            maxsplit=1
        )

        identifier = parts[0].strip()

        if not identifier:
            return None, None

        remainder = (
            parts[1].strip()
            if len(parts) > 1
            else None
        )

        return identifier, remainder

    # ============================================================
    # Canonical command parser
    # ============================================================

    def parse(
        self,
        *,
        user_id: Any,
        text: str,
    ) -> TelegramEngineeringRequest | None:
        value = self._clean(text)

        if not value:
            return None

        authorization = self.authorization_status(
            user_id
        )

        # --------------------------------------------------------
        # HELP
        # --------------------------------------------------------

        if value.lower() in {
            item.lower()
            for item in self.HELP_COMMANDS
        }:
            return TelegramEngineeringRequest(
                command=TelegramEngineeringCommand.HELP,
                action=TelegramEngineeringAction.SHOW_HELP,
                raw_text=value,
                user_id=str(user_id),
                authorization=authorization,
            )

        # --------------------------------------------------------
        # STATUS
        # --------------------------------------------------------

        if value.lower() in {
            item.lower()
            for item in self.STATUS_COMMANDS
        }:
            return TelegramEngineeringRequest(
                command=TelegramEngineeringCommand.STATUS,
                action=TelegramEngineeringAction.SHOW_STATUS,
                raw_text=value,
                user_id=str(user_id),
                authorization=authorization,
            )

        # --------------------------------------------------------
        # APPROVAL LIST
        # --------------------------------------------------------

        if value.lower() in {
            item.lower()
            for item in self.APPROVAL_LIST_COMMANDS
        }:
            return TelegramEngineeringRequest(
                command=TelegramEngineeringCommand.APPROVE,
                action=TelegramEngineeringAction.SHOW_STATUS,
                raw_text=value,
                user_id=str(user_id),
                authorization=authorization,
                metadata={
                    "approval_list": True,
                },
            )

        # --------------------------------------------------------
        # DEVELOP
        # --------------------------------------------------------

        requirement = self._extract_after_prefix(
            value,
            self.DEVELOP_PREFIXES,
        )

        if requirement is not None:
            return TelegramEngineeringRequest(
                command=TelegramEngineeringCommand.DEVELOP,
                action=TelegramEngineeringAction.START_ENGINEERING,
                raw_text=value,
                requirement_text=requirement,
                user_id=str(user_id),
                authorization=authorization,
            )

        # --------------------------------------------------------
        # RESUME
        # --------------------------------------------------------

        resume_value = self._extract_after_prefix(
            value,
            self.RESUME_PREFIXES,
        )

        if resume_value is not None:
            session_id, remainder = (
                self._split_identifier(
                    resume_value
                )
            )

            return TelegramEngineeringRequest(
                command=TelegramEngineeringCommand.RESUME,
                action=TelegramEngineeringAction.RESUME_ENGINEERING,
                raw_text=value,
                requirement_text=remainder,
                session_id=session_id,
                user_id=str(user_id),
                authorization=authorization,
            )

        # --------------------------------------------------------
        # APPROVE
        # --------------------------------------------------------

        approval_value = self._extract_after_prefix(
            value,
            self.APPROVE_PREFIXES,
        )

        if approval_value is not None:
            approval_id, _ = (
                self._split_identifier(
                    approval_value
                )
            )

            return TelegramEngineeringRequest(
                command=TelegramEngineeringCommand.APPROVE,
                action=TelegramEngineeringAction.APPROVE_OPERATION,
                raw_text=value,
                approval_id=approval_id,
                user_id=str(user_id),
                authorization=authorization,
            )

        # --------------------------------------------------------
        # REJECT
        # --------------------------------------------------------

        reject_value = self._extract_after_prefix(
            value,
            self.REJECT_PREFIXES,
        )

        if reject_value is not None:
            approval_id, _ = (
                self._split_identifier(
                    reject_value
                )
            )

            return TelegramEngineeringRequest(
                command=TelegramEngineeringCommand.REJECT,
                action=TelegramEngineeringAction.REJECT_OPERATION,
                raw_text=value,
                approval_id=approval_id,
                user_id=str(user_id),
                authorization=authorization,
            )

        # --------------------------------------------------------
        # CANCEL
        # --------------------------------------------------------

        cancel_value = self._extract_after_prefix(
            value,
            self.CANCEL_PREFIXES,
        )

        if cancel_value is not None:
            session_id, _ = (
                self._split_identifier(
                    cancel_value
                )
            )

            return TelegramEngineeringRequest(
                command=TelegramEngineeringCommand.CANCEL,
                action=TelegramEngineeringAction.CANCEL_ENGINEERING,
                raw_text=value,
                session_id=session_id,
                user_id=str(user_id),
                authorization=authorization,
            )

        # --------------------------------------------------------
        # SELF-UPGRADE
        # --------------------------------------------------------

        upgrade_value = self._extract_after_prefix(
            value,
            self.SELF_UPGRADE_PREFIXES,
        )

        if upgrade_value is not None:
            return TelegramEngineeringRequest(
                command=TelegramEngineeringCommand.SELF_UPGRADE,
                action=TelegramEngineeringAction.PLAN_SELF_UPGRADE,
                raw_text=value,
                requirement_text=upgrade_value,
                user_id=str(user_id),
                authorization=authorization,
                metadata={
                    "explicit_self_upgrade": True,
                },
            )

        return None

    # ============================================================
    # Request validation
    # ============================================================

    def validate(
        self,
        request: TelegramEngineeringRequest,
    ) -> TelegramEngineeringResponse | None:
        if not request.requires_authorization:
            return None

        if (
            request.authorization
            == TelegramAuthorizationStatus.NOT_CONFIGURED
        ):
            return TelegramEngineeringResponse(
                handled=True,
                success=False,
                text=(
                    "🔒 ARIA engineering access is not configured. "
                    "The Master Telegram authorization is missing."
                ),
                command=request.command,
                action=request.action,
                error="telegram_authorization_not_configured",
            )

        if (
            request.authorization
            == TelegramAuthorizationStatus.UNAUTHORIZED
        ):
            return TelegramEngineeringResponse(
                handled=True,
                success=False,
                text=(
                    "🔒 This engineering interface is restricted "
                    "to the authorized Master account."
                ),
                command=request.command,
                action=request.action,
                error="telegram_user_unauthorized",
            )

        return None

    # ============================================================
    # Gateway dispatch
    # ============================================================

    async def handle(
        self,
        *,
        user_id: Any,
        text: str,
    ) -> TelegramEngineeringResponse | None:
        request = self.parse(
            user_id=user_id,
            text=text,
        )

        if request is None:
            return None

        validation = self.validate(
            request
        )

        if validation is not None:
            return validation

        try:
            if request.action == (
                TelegramEngineeringAction.SHOW_HELP
            ):
                return self._help_response(
                    request
                )

            if request.action == (
                TelegramEngineeringAction.SHOW_STATUS
            ):
                return await self._status(
                    request
                )

            if request.action == (
                TelegramEngineeringAction.START_ENGINEERING
            ):
                return await self._dispatch(
                    request,
                    method_names=(
                        "start_engineering",
                        "develop",
                        "execute",
                    ),
                )

            if request.action == (
                TelegramEngineeringAction.RESUME_ENGINEERING
            ):
                return await self._dispatch(
                    request,
                    method_names=(
                        "resume_engineering",
                        "resume",
                    ),
                )

            if request.action == (
                TelegramEngineeringAction.APPROVE_OPERATION
            ):
                return await self._dispatch(
                    request,
                    method_names=(
                        "approve",
                        "approve_operation",
                    ),
                )

            if request.action == (
                TelegramEngineeringAction.REJECT_OPERATION
            ):
                return await self._dispatch(
                    request,
                    method_names=(
                        "reject",
                        "reject_operation",
                    ),
                )

            if request.action == (
                TelegramEngineeringAction.CANCEL_ENGINEERING
            ):
                return await self._dispatch(
                    request,
                    method_names=(
                        "cancel_engineering",
                        "cancel",
                    ),
                )

            if request.action == (
                TelegramEngineeringAction.PLAN_SELF_UPGRADE
            ):
                return await self._dispatch(
                    request,
                    method_names=(
                        "plan_self_upgrade",
                        "self_upgrade",
                    ),
                )

            return TelegramEngineeringResponse(
                handled=True,
                success=False,
                text="Unsupported engineering command.",
                command=request.command,
                action=request.action,
                error="unsupported_engineering_action",
            )

        except Exception as exc:
            logger.exception(
                "[TelegramEngineering] Command dispatch failed"
            )

            return TelegramEngineeringResponse(
                handled=True,
                success=False,
                text=(
                    "🛑 Engineering command failed safely.\n\n"
                    f"Reason: {str(exc)[:1500]}"
                ),
                command=request.command,
                action=request.action,
                error=str(exc),
            )

    # ============================================================
    # Dispatch compatibility boundary
    # ============================================================

    async def _dispatch(
        self,
        request: TelegramEngineeringRequest,
        *,
        method_names: tuple[str, ...],
    ) -> TelegramEngineeringResponse:
        gateway = (
            self.execution_gateway
            if request.action
            in {
                TelegramEngineeringAction.START_ENGINEERING,
                TelegramEngineeringAction.RESUME_ENGINEERING,
                TelegramEngineeringAction.CANCEL_ENGINEERING,
                TelegramEngineeringAction.PLAN_SELF_UPGRADE,
            }
            else self.approval_gateway
        )

        if gateway is None:
            return TelegramEngineeringResponse(
                handled=True,
                success=False,
                text=(
                    "The Telegram command was parsed and authorized, "
                    "but its engineering gateway is not connected yet."
                ),
                command=request.command,
                action=request.action,
                error="engineering_gateway_not_connected",
                metadata={
                    "request": request.to_dict(),
                    "required_methods": list(method_names),
                },
            )

        method = None

        for name in method_names:
            candidate = getattr(
                gateway,
                name,
                None,
            )

            if callable(candidate):
                method = candidate
                break

        if method is None:
            return TelegramEngineeringResponse(
                handled=True,
                success=False,
                text=(
                    "The engineering gateway is connected, "
                    "but does not expose the required operation yet."
                ),
                command=request.command,
                action=request.action,
                error="engineering_gateway_method_missing",
                metadata={
                    "request": request.to_dict(),
                    "required_methods": list(method_names),
                },
            )

        payload = request.to_dict()

        try:
            result = method(
                request
            )
        except TypeError:
            try:
                result = method(
                    payload
                )
            except TypeError:
                result = method(
                    **payload
                )

        if hasattr(
            result,
            "__await__",
        ):
            result = await result

        return self._result_response(
            request,
            result,
        )

    # ============================================================
    # Status
    # ============================================================

    async def _status(
        self,
        request: TelegramEngineeringRequest,
    ) -> TelegramEngineeringResponse:
        gateway = (
            self.execution_gateway
        )

        if gateway is None:
            return TelegramEngineeringResponse(
                handled=True,
                success=False,
                text=(
                    "ARIA engineering status is not connected yet."
                ),
                command=request.command,
                action=request.action,
                error="engineering_gateway_not_connected",
            )

        method = getattr(
            gateway,
            "status",
            None,
        )

        if not callable(method):
            return TelegramEngineeringResponse(
                handled=True,
                success=False,
                text=(
                    "ARIA engineering status is not available yet."
                ),
                command=request.command,
                action=request.action,
                error="engineering_status_unavailable",
            )

        result = method()

        if hasattr(
            result,
            "__await__",
        ):
            result = await result

        return self._result_response(
            request,
            result,
            default_text="ARIA engineering status retrieved.",
        )

    # ============================================================
    # Help
    # ============================================================

    @staticmethod
    def _help_response(
        request: TelegramEngineeringRequest,
    ) -> TelegramEngineeringResponse:
        text = (
            "🧠 <b>ARIA Engineering Interface</b>\n\n"
            "<b>Start autonomous development</b>\n"
            "/master develop &lt;high-level requirement&gt;\n\n"
            "<b>Resume a session</b>\n"
            "/master resume &lt;session_id&gt;\n\n"
            "<b>Engineering status</b>\n"
            "/master status\n\n"
            "<b>Pending approvals</b>\n"
            "/master approvals\n\n"
            "<b>Approve gated operation</b>\n"
            "/master approve &lt;approval_id&gt;\n\n"
            "<b>Reject gated operation</b>\n"
            "/master reject &lt;approval_id&gt;\n\n"
            "<b>Cancel engineering session</b>\n"
            "/master cancel &lt;session_id&gt;\n\n"
            "<b>Plan a self-upgrade</b>\n"
            "/master self-upgrade &lt;requirement&gt;\n\n"
            "GitHub push, PR merge, deployment, and "
            "high-risk self-upgrades remain behind explicit "
            "authorization gates."
        )

        return TelegramEngineeringResponse(
            handled=True,
            success=True,
            text=text,
            command=request.command,
            action=request.action,
        )

    # ============================================================
    # Result normalization
    # ============================================================

    @staticmethod
    def _result_response(
        request: TelegramEngineeringRequest,
        result: Any,
        *,
        default_text: str | None = None,
    ) -> TelegramEngineeringResponse:
        if isinstance(
            result,
            TelegramEngineeringResponse,
        ):
            return result

        if isinstance(
            result,
            dict,
        ):
            success = bool(
                result.get(
                    "success",
                    result.get(
                        "accepted",
                        False,
                    ),
                )
            )

            text = str(
                result.get(
                    "text",
                    default_text
                    or (
                        "✅ Engineering operation completed."
                        if success
                        else "🛑 Engineering operation did not complete."
                    ),
                )
            )

            session_id = result.get(
                "session_id"
            )

            status = result.get(
                "status"
            )

        else:
            success = bool(
                getattr(
                    result,
                    "success",
                    getattr(
                        result,
                        "accepted",
                        False,
                    ),
                )
            )

            text = str(
                getattr(
                    result,
                    "text",
                    default_text
                    or (
                        "✅ Engineering operation completed."
                        if success
                        else "🛑 Engineering operation did not complete."
                    ),
                )
            )

            session_id = getattr(
                result,
                "session_id",
                None,
            )

            status = getattr(
                result,
                "status",
                None,
            )

        return TelegramEngineeringResponse(
            handled=True,
            success=success,
            text=text,
            command=request.command,
            action=request.action,
            session_id=(
                str(session_id)
                if session_id is not None
                else None
            ),
            status=(
                str(status)
                if status is not None
                else None
            ),
            result=result,
        )

    # ============================================================
    # Introspection
    # ============================================================

    def status(self) -> dict[str, Any]:
        return {
            "healthy": True,
            "name": "telegram_engineering_command_interface",
            "authorization_configured": bool(
                self.authorized_user_id
            ),
            "execution_gateway_connected": (
                self.execution_gateway is not None
            ),
            "approval_gateway_connected": (
                self.approval_gateway is not None
            ),
            "capabilities": [
                "master_develop",
                "master_status",
                "master_resume",
                "master_approvals",
                "master_approve",
                "master_reject",
                "master_cancel",
                "master_self_upgrade",
            ],
            "safety": [
                "master_only",
                "fail_closed",
                "no_direct_file_execution",
                "no_direct_shell_execution",
                "no_direct_github_push",
                "no_direct_deployment",
                "approval_boundary_preserved",
            ],
        }


__all__ = [
    "TelegramEngineeringCommandInterface",
]