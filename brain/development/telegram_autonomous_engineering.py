"""
ARIA Telegram Autonomous Engineering Interface.

Phase 1 Telegram entry point for the autonomous engineering runtime.

This layer is intentionally limited to:
- Master authorization
- command parsing
- runtime invocation
- bounded Telegram-safe reporting

It does not directly manipulate files, GitHub, deployment, or secrets.
Those responsibilities remain inside the Phase 1 runtime and its
permissioned services.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger("aria")


class TelegramAutonomousEngineeringInterface:
    """Master-only Telegram interface for Phase 1 autonomous engineering."""

    def __init__(
        self,
        phase1_runtime: Any,
    ) -> None:
        self.phase1_runtime = phase1_runtime

    # ============================================================
    # AUTHORIZATION
    # ============================================================

    @staticmethod
    def _authorized(
        user_id: Any,
    ) -> bool:

        allowed = os.getenv(
            "ALLOWED_TELEGRAM_USER_ID",
            "",
        ).strip()

        if not allowed:
            return False

        return (
            str(user_id).strip()
            == allowed
        )

    # ============================================================
    # SAFE TEXT
    # ============================================================

    @staticmethod
    def _bounded(
        value: Any,
        limit: int = 3500,
    ) -> str:

        try:
            text = str(value).strip()

        except Exception:
            return "<unavailable>"

        if not text:
            return "<empty>"

        return text[
            :max(
                1,
                int(limit),
            )
        ]

    # ============================================================
    # COMMAND PARSER
    # ============================================================

    @staticmethod
    def _parse(
        text: str,
    ) -> tuple[str, str | None]:

        if not isinstance(
            text,
            str,
        ):
            return (
                "none",
                None,
            )

        value = text.strip()

        lower = value.lower()

        if not value:
            return (
                "none",
                None,
            )

        # --------------------------------------------------------
        # AUTONOMOUS DEVELOPMENT
        # --------------------------------------------------------

        prefixes = (
            "/master develop",
            "master develop",
            "master, develop",
        )

        for prefix in prefixes:

            if lower.startswith(prefix):

                requirement = (
                    value[
                        len(prefix):
                    ].lstrip(
                        " :,-\t\r\n"
                    ).strip()
                )

                return (
                    "develop",
                    requirement
                    if requirement
                    else None,
                )

        # --------------------------------------------------------
        # STATUS
        # --------------------------------------------------------

        status_commands = {
            "/master phase1 status",
            "master phase1 status",
            "master, phase1 status",
            "/master self status",
            "master self status",
        }

        if lower in status_commands:

            return (
                "status",
                None,
            )

        # --------------------------------------------------------
        # HEALTH
        # --------------------------------------------------------

        health_commands = {
            "/master phase1 health",
            "master phase1 health",
            "master, phase1 health",
            "/master self health",
            "master self health",
        }

        if lower in health_commands:

            return (
                "health",
                None,
            )

        # --------------------------------------------------------
        # HELP
        # --------------------------------------------------------

        help_commands = {
            "/master phase1",
            "/master phase1 help",
            "master phase1",
            "master phase1 help",
            "master, phase1",
        }

        if lower in help_commands:

            return (
                "help",
                None,
            )

        return (
            "none",
            None,
        )

    # ============================================================
    # MAIN HANDLER
    # ============================================================

    async def handle(
        self,
        *,
        user_id: Any,
        text: str,
    ) -> dict[str, Any] | None:

        command, requirement = (
            self._parse(text)
        )

        if command == "none":
            return None

        # --------------------------------------------------------
        # MASTER AUTHORIZATION
        # --------------------------------------------------------

        if not self._authorized(
            user_id
        ):

            logger.warning(
                "[Phase1][TelegramEngineering] "
                "Unauthorized command | user_id=%s",
                user_id,
            )

            return {
                "handled": True,
                "success": False,
                "text": (
                    "I can only accept Phase 1 "
                    "engineering commands from the "
                    "authorized Master account."
                ),
            }

        # --------------------------------------------------------
        # HELP
        # --------------------------------------------------------

        if command == "help":

            return {
                "handled": True,
                "success": True,
                "text": (
                    "🧠 <b>ARIA Phase 1 Engineering</b>\n\n"

                    "<b>Autonomous development:</b>\n"
                    "/master develop &lt;requirement&gt;\n\n"

                    "<b>Runtime status:</b>\n"
                    "/master phase1 status\n\n"

                    "<b>Runtime health:</b>\n"
                    "/master phase1 health\n\n"

                    "Development runs through the "
                    "autonomous Phase 1 runtime.\n\n"

                    "GitHub push and deployment remain "
                    "permission-gated."
                ),
            }

        # --------------------------------------------------------
        # STATUS
        # --------------------------------------------------------

        if command == "status":

            return self._status_response()

        # --------------------------------------------------------
        # HEALTH
        # --------------------------------------------------------

        if command == "health":

            return self._health_response()

        # --------------------------------------------------------
        # REQUIREMENT VALIDATION
        # --------------------------------------------------------

        if not requirement:

            return {
                "handled": True,
                "success": False,
                "text": (
                    "🧠 Please provide a development "
                    "requirement.\n\n"

                    "Example:\n"
                    "/master develop implement Phase 2 "
                    "completely according to the specification"
                ),
            }

        # --------------------------------------------------------
        # AUTONOMOUS DEVELOPMENT
        # --------------------------------------------------------

        return await self._develop(
            requirement
        )

    # ============================================================
    # STATUS
    # ============================================================

    def _status_response(
        self,
    ) -> dict[str, Any]:

        try:

            data = (
                self.phase1_runtime.status()
            )

            return {
                "handled": True,
                "success": True,
                "text": (
                    "🧠 <b>Phase 1 Runtime Status</b>\n\n"
                    f"{self._format_structured(data)}"
                ),
                "status": data,
            }

        except Exception as exc:

            logger.exception(
                "[Phase1][TelegramEngineering] "
                "Status failed"
            )

            return {
                "handled": True,
                "success": False,
                "text": (
                    "Phase 1 status could not be "
                    "read safely.\n\n"
                    f"Reason: {self._bounded(exc)}"
                ),
            }

    # ============================================================
    # HEALTH
    # ============================================================

    def _health_response(
        self,
    ) -> dict[str, Any]:

        try:

            data = (
                self.phase1_runtime.health()
            )

            healthy = (
                bool(
                    data.get(
                        "healthy"
                    )
                )
                if isinstance(
                    data,
                    dict,
                )
                else False
            )

            icon = (
                "🟢"
                if healthy
                else "🔴"
            )

            return {
                "handled": True,
                "success": healthy,
                "text": (
                    f"{icon} "
                    "<b>Phase 1 Runtime Health</b>\n\n"
                    f"{self._format_structured(data)}"
                ),
                "health": data,
            }

        except Exception as exc:

            logger.exception(
                "[Phase1][TelegramEngineering] "
                "Health failed"
            )

            return {
                "handled": True,
                "success": False,
                "text": (
                    "Phase 1 health check failed safely.\n\n"
                    f"Reason: {self._bounded(exc)}"
                ),
            }

    # ============================================================
    # AUTONOMOUS DEVELOPMENT
    # ============================================================

    async def _develop(
        self,
        requirement: str,
    ) -> dict[str, Any]:

        logger.info(
            "[Phase1][TelegramEngineering] "
            "Starting autonomous development | "
            "requirement=%r",
            requirement,
        )

        try:

            result = (
                await self.phase1_runtime.develop(
                    requirement
                )
            )

        except RuntimeError as exc:

            logger.warning(
                "[Phase1][TelegramEngineering] "
                "Development rejected: %s",
                exc,
            )

            return {
                "handled": True,
                "success": False,
                "text": (
                    "🛠️ Autonomous development "
                    "could not start.\n\n"
                    f"Reason: {self._bounded(exc)}\n\n"
                    "No GitHub push or production "
                    "deployment was performed."
                ),
            }

        except Exception as exc:

            logger.exception(
                "[Phase1][TelegramEngineering] "
                "Autonomous development failed"
            )

            return {
                "handled": True,
                "success": False,
                "text": (
                    "🛠️ Autonomous development "
                    "failed safely.\n\n"
                    f"Reason: {self._bounded(exc)}\n\n"
                    "No GitHub push or production "
                    "deployment was performed."
                ),
            }

        data = self._serialize(
            result
        )

        success = (
            self._result_success(
                result,
                data,
            )
        )

        summary = (
            self._result_summary(
                result,
                data,
            )
        )

        if success:

            text = (
                "✅ <b>Autonomous development "
                "completed</b>\n\n"

                f"Requirement: "
                f"{self._bounded(requirement, 1200)}\n\n"

                f"{summary}\n\n"

                "GitHub push and production deployment "
                "remain controlled by the permissioned "
                "workflow."
            )

        else:

            text = (
                "🛠️ <b>Autonomous development "
                "finished without acceptance</b>\n\n"

                f"Requirement: "
                f"{self._bounded(requirement, 1200)}\n\n"

                f"{summary}\n\n"

                "The result remains isolated; no "
                "unapproved production deployment "
                "was performed."
            )

        return {
            "handled": True,
            "success": success,
            "text": text[:4000],
            "result": data,
        }

    # ============================================================
    # RESULT SERIALIZATION
    # ============================================================

    @staticmethod
    def _serialize(
        value: Any,
    ) -> Any:

        try:

            if hasattr(
                value,
                "to_dict",
            ):

                value = value.to_dict()

            elif hasattr(
                value,
                "model_dump",
            ):

                value = value.model_dump()

            elif (
                hasattr(
                    value,
                    "__dict__",
                )
                and not isinstance(
                    value,
                    dict,
                )
            ):

                value = dict(
                    value.__dict__
                )

        except Exception:

            return {
                "summary": str(
                    value
                )[:2000]
            }

        try:

            json.dumps(
                value,
                default=str,
            )

            return value

        except Exception:

            return {
                "summary": str(
                    value
                )[:2000]
            }

    # ============================================================
    # RESULT SUCCESS
    # ============================================================

    @staticmethod
    def _result_success(
        result: Any,
        data: Any,
    ) -> bool:

        for source in (
            data,
            result,
        ):

            if isinstance(
                source,
                dict,
            ):

                for key in (
                    "success",
                    "accepted",
                    "completed",
                ):

                    if key in source:

                        return bool(
                            source[key]
                        )

            else:

                for key in (
                    "success",
                    "accepted",
                    "completed",
                ):

                    value = getattr(
                        source,
                        key,
                        None,
                    )

                    if value is not None:

                        return bool(
                            value
                        )

        return False

    # ============================================================
    # RESULT SUMMARY
    # ============================================================

    def _result_summary(
        self,
        result: Any,
        data: Any,
    ) -> str:

        if isinstance(
            data,
            dict,
        ):

            preferred = (
                "summary",
                "message",
                "status",
                "job_id",
                "attempts",
                "validation",
                "repair",
                "errors",
                "failure",
            )

            compact = {
                key: data[key]
                for key in preferred
                if key in data
            }

            if compact:

                return (
                    self._format_structured(
                        compact
                    )
                )

        return self._bounded(
            result,
            3000,
        )

    # ============================================================
    # STRUCTURED OUTPUT
    # ============================================================

    @staticmethod
    def _format_structured(
        value: Any,
    ) -> str:

        try:

            raw = json.dumps(
                value,
                ensure_ascii=False,
                indent=2,
                default=str,
            )

            return raw[:3500]

        except Exception:

            return str(
                value
            )[:3500]


__all__ = [
    "TelegramAutonomousEngineeringInterface",
]