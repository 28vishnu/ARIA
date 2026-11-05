from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(
    "aria.telegram_engineering_runtime"
)


class TelegramEngineeringRuntime:
    """
    Canonical Telegram gateway for ARIA autonomous engineering.

    Telegram is only the command surface.

    Architecture:

        Telegram
            ↓
        TelegramEngineeringRuntime
            ↓
        Phase1PersistentRuntimeAdapter
            ↓
        PersistentEngineeringRuntime
            ↓
        Authoritative Engineering Lifecycle
            ↓
        Existing Autonomous Development Engine

    This class never performs GitHub push or deployment by itself.
    """

    VERSION = (
        "TELEGRAM-ENGINEERING-RUNTIME-V2"
    )

    def __init__(
        self,
        engineering_runtime: Any,
        approval_runtime: Any | None = None,
    ) -> None:

        if engineering_runtime is None:
            raise ValueError(
                "engineering_runtime is required."
            )

        self.engineering_runtime = (
            engineering_runtime
        )

        self.approval_runtime = (
            approval_runtime
        )

    # ============================================================
    # AUTHORIZATION
    # ============================================================

    @staticmethod
    def _allowed_user_id() -> str:
        for name in (
            "ALLOWED_TELEGRAM_USER_ID",
            "TELEGRAM_MASTER_USER_ID",
            "MASTER_TELEGRAM_USER_ID",
        ):

            value = os.getenv(
                name,
                "",
            ).strip()

            if value:
                return value

        return ""

    @classmethod
    def authorized(
        cls,
        user_id: Any,
    ) -> bool:

        allowed = cls._allowed_user_id()

        if not allowed:
            return False

        return (
            str(user_id).strip()
            == allowed
        )

    # ============================================================
    # COMMAND PARSING
    # ============================================================

    @staticmethod
    def _normalized(
        text: str,
    ) -> str:

        return str(
            text or ""
        ).strip()

    @classmethod
    def _remove_master_prefix(
        cls,
        text: str,
    ) -> str | None:

        value = cls._normalized(
            text
        )

        lower = value.lower()

        prefixes = (
            "/master",
            "master",
        )

        for prefix in prefixes:

            if lower == prefix:
                return ""

            if lower.startswith(
                prefix + " "
            ):

                return value[
                    len(prefix):
                ].strip()

            if lower.startswith(
                prefix + ":"
            ):

                return value[
                    len(prefix) + 1:
                ].strip()

        return None

    @classmethod
    def parse(
        cls,
        text: str,
    ) -> tuple[
        str,
        str,
    ]:

        command_text = (
            cls._remove_master_prefix(
                text
            )
        )

        if command_text is None:
            return (
                "",
                "",
            )

        if not command_text:
            return (
                "help",
                "",
            )

        parts = command_text.split(
            maxsplit=1
        )

        command = (
            parts[0]
            .strip()
            .lower()
        )

        argument = (
            parts[1].strip()
            if len(parts) > 1
            else ""
        )

        aliases = {
            "develop": "develop",
            "development": "develop",
            "build": "develop",
            "implement": "develop",
            "resume": "resume",
            "continue": "resume",
            "status": "status",
            "state": "status",
            "approvals": "approvals",
            "approval": "approvals",
            "approve": "approve",
            "reject": "reject",
            "cancel": "cancel",
            "stop": "cancel",
            "self-upgrade": "self-upgrade",
            "self_upgrade": "self-upgrade",
            "upgrade": "self-upgrade",
            "help": "help",
            "?": "help",
        }

        return (
            aliases.get(
                command,
                command,
            ),
            argument,
        )

    # ============================================================
    # MAIN TELEGRAM HANDLER
    # ============================================================

    async def handle(
        self,
        *,
        user_id: Any,
        text: str,
    ) -> Any:

        command, argument = (
            self.parse(text)
        )

        # Not an engineering command.
        if not command:
            return None

        if not self.authorized(
            user_id
        ):

            return self._response(
                success=False,
                text=(
                    "🔐 Unauthorized.\n\n"
                    "Autonomous engineering commands "
                    "are restricted to the Master account."
                ),
            )

        try:

            if command == "develop":

                return await self._develop(
                    argument
                )

            if command == "resume":

                return await self._resume(
                    argument
                )

            if command == "status":

                return await self._status(
                    argument
                )

            if command == "approvals":

                return await self._approvals()

            if command == "approve":

                return await self._approve(
                    argument
                )

            if command == "reject":

                return await self._reject(
                    argument
                )

            if command == "cancel":

                return await self._cancel(
                    argument
                )

            if command == "self-upgrade":

                return await self._self_upgrade(
                    argument
                )

            if command == "help":

                return self._help()

            return self._response(
                success=False,
                text=(
                    "❓ Unknown Master engineering command.\n\n"
                    "Use `/master help`."
                ),
            )

        except Exception as exc:

            logger.exception(
                "[TelegramEngineeringRuntime] "
                "Command failed | command=%s",
                command,
            )

            return self._response(
                success=False,
                text=(
                    "🛑 Autonomous engineering failed safely.\n\n"
                    f"Reason: {self._bounded(exc)}"
                ),
                error=str(exc),
            )

    # ============================================================
    # DEVELOP
    # ============================================================

    async def _develop(
        self,
        requirement: str,
    ) -> dict[str, Any]:

        requirement = str(
            requirement or ""
        ).strip()

        if not requirement:

            return self._response(
                success=False,
                text=(
                    "⚠️ Missing engineering requirement.\n\n"
                    "Example:\n"
                    "`/master develop Implement Phase 2 completely "
                    "according to the specification.`"
                ),
            )

        runtime = (
            self._engineering_runtime()
        )

        logger.info(
            "[TelegramEngineeringRuntime] "
            "Starting persistent engineering | requirement=%r",
            requirement,
        )

        result = await runtime.develop(
            requirement
        )

        data = self._result_to_dict(
            result
        )

        success = self._result_success(
            result,
            data,
        )

        session_id = (
            data.get(
                "session_id"
            )
            if isinstance(
                data,
                dict,
            )
            else None
        )

        lifecycle = await self._lifecycle_status(
            session_id
        )

        if isinstance(
            data,
            dict,
        ):

            data[
                "lifecycle"
            ] = lifecycle

        return self._response(
            success=success,
            text=self._development_message(
                success=success,
                data=data,
                session_id=session_id,
            ),
            result=data,
            session_id=session_id,
        )

    # ============================================================
    # RESUME
    # ============================================================

    async def _resume(
        self,
        session_id: str,
    ) -> dict[str, Any]:

        session_id = str(
            session_id or ""
        ).strip()

        if not session_id:

            return self._response(
                success=False,
                text=(
                    "⚠️ Missing session ID.\n\n"
                    "Use:\n"
                    "`/master resume <session_id>`"
                ),
            )

        runtime = (
            self._engineering_runtime()
        )

        result = await runtime.resume(
            session_id
        )

        data = self._result_to_dict(
            result
        )

        success = self._result_success(
            result,
            data,
        )

        lifecycle = await self._lifecycle_status(
            session_id
        )

        if isinstance(
            data,
            dict,
        ):

            data[
                "lifecycle"
            ] = lifecycle

        return self._response(
            success=success,
            text=self._development_message(
                success=success,
                data=data,
                session_id=session_id,
                resumed=True,
            ),
            result=data,
            session_id=session_id,
        )

    # ============================================================
    # STATUS
    # ============================================================

    async def _status(
        self,
        session_id: str,
    ) -> dict[str, Any]:

        runtime = (
            self._engineering_runtime()
        )

        session_id = str(
            session_id or ""
        ).strip()

        if session_id:

            status_method = getattr(
                runtime,
                "engineering_status",
                None,
            )

            if callable(
                status_method
            ):

                result = (
                    await status_method(
                        session_id
                    )
                )

            else:

                status_method = getattr(
                    runtime,
                    "status",
                    None,
                )

                if not callable(
                    status_method
                ):

                    result = {
                        "healthy": False,
                        "error": (
                            "Runtime does not expose "
                            "session status."
                        ),
                    }

                else:

                    result = status_method(
                        session_id
                    )

                    if hasattr(
                        result,
                        "__await__",
                    ):
                        result = await result

            return self._response(
                success=bool(
                    result.get(
                        "healthy",
                        False,
                    )
                )
                if isinstance(
                    result,
                    dict,
                )
                else True,
                text=self._json(
                    result
                ),
                result=result,
                session_id=session_id,
            )

        # Global runtime status.
        method = getattr(
            runtime,
            "status",
            None,
        )

        if not callable(
            method
        ):

            result = {
                "healthy": False,
                "error": (
                    "Runtime does not expose status()."
                ),
            }

        else:

            result = method()

            if hasattr(
                result,
                "__await__",
            ):
                result = await result

        return self._response(
            success=bool(
                result.get(
                    "healthy",
                    False,
                )
            )
            if isinstance(
                result,
                dict,
            )
            else True,
            text=self._json(
                result
            ),
            result=result,
        )

    # ============================================================
    # LIFECYCLE STATUS
    # ============================================================

    async def _lifecycle_status(
        self,
        session_id: str | None,
    ) -> dict[str, Any]:

        if not session_id:
            return {}

        runtime = (
            self._engineering_runtime()
        )

        method = getattr(
            runtime,
            "engineering_status",
            None,
        )

        if not callable(
            method
        ):
            return {}

        try:

            result = method(
                session_id
            )

            if hasattr(
                result,
                "__await__",
            ):
                result = await result

            return (
                result
                if isinstance(
                    result,
                    dict,
                )
                else {}
            )

        except Exception:

            logger.exception(
                "[TelegramEngineeringRuntime] "
                "Lifecycle status lookup failed."
            )

            return {}

    # ============================================================
    # APPROVALS
    # ============================================================

    async def _approvals(
        self,
    ) -> dict[str, Any]:

        runtime = (
            self.approval_runtime
        )

        if runtime is None:

            return self._response(
                success=True,
                text=(
                    "ℹ️ No approval runtime is connected."
                ),
            )

        for name in (
            "list_pending",
            "pending",
            "get_pending",
            "status",
        ):

            method = getattr(
                runtime,
                name,
                None,
            )

            if not callable(
                method
            ):
                continue

            try:

                result = method()

                if hasattr(
                    result,
                    "__await__",
                ):
                    result = await result

                return self._response(
                    success=True,
                    text=self._json(
                        result
                    ),
                    result=result,
                )

            except TypeError:
                continue

        return self._response(
            success=False,
            text=(
                "⚠️ Approval runtime is connected, "
                "but does not expose a supported "
                "pending-approval API."
            ),
        )

    async def _approve(
        self,
        approval_id: str,
    ) -> dict[str, Any]:

        return await self._approval_action(
            "approve",
            approval_id,
        )

    async def _reject(
        self,
        approval_id: str,
    ) -> dict[str, Any]:

        return await self._approval_action(
            "reject",
            approval_id,
        )

    async def _approval_action(
        self,
        action: str,
        approval_id: str,
    ) -> dict[str, Any]:

        approval_id = str(
            approval_id or ""
        ).strip()

        if not approval_id:

            return self._response(
                success=False,
                text=(
                    f"⚠️ Missing approval ID.\n\n"
                    f"Use `/master {action} <approval_id>`."
                ),
            )

        runtime = (
            self.approval_runtime
        )

        if runtime is None:

            return self._response(
                success=False,
                text=(
                    "🛑 Approval runtime is not connected."
                ),
            )

        method = getattr(
            runtime,
            action,
            None,
        )

        if not callable(
            method
        ):

            return self._response(
                success=False,
                text=(
                    f"🛑 Approval runtime does not "
                    f"support `{action}`."
                ),
            )

        result = method(
            approval_id
        )

        if hasattr(
            result,
            "__await__",
        ):
            result = await result

        return self._response(
            success=self._result_success(
                result,
                self._result_to_dict(
                    result
                ),
            ),
            text=self._json(
                result
            ),
            result=result,
        )

    # ============================================================
    # CANCEL
    # ============================================================

    async def _cancel(
        self,
        session_id: str,
    ) -> dict[str, Any]:

        session_id = str(
            session_id or ""
        ).strip()

        if not session_id:

            return self._response(
                success=False,
                text=(
                    "⚠️ Missing session ID.\n\n"
                    "Use `/master cancel <session_id>`."
                ),
            )

        runtime = (
            self._engineering_runtime()
        )

        # Try persistent/runtime cancellation first.
        for name in (
            "cancel",
            "cancel_session",
        ):

            method = getattr(
                runtime,
                name,
                None,
            )

            if not callable(
                method
            ):
                continue

            try:

                result = method(
                    session_id
                )

                if hasattr(
                    result,
                    "__await__",
                ):
                    result = await result

                return self._response(
                    success=True,
                    text=self._json(
                        result
                    ),
                    result=result,
                    session_id=session_id,
                )

            except TypeError:
                continue

        # Fallback to the legacy runtime capability.
        legacy = getattr(
            runtime,
            "legacy_runtime",
            None,
        )

        if legacy is not None:

            for name in (
                "cancel",
                "cancel_session",
            ):

                method = getattr(
                    legacy,
                    name,
                    None,
                )

                if not callable(
                    method
                ):
                    continue

                try:

                    result = method(
                        session_id
                    )

                    if hasattr(
                        result,
                        "__await__",
                    ):
                        result = await result

                    return self._response(
                        success=True,
                        text=self._json(
                            result
                        ),
                        result=result,
                        session_id=session_id,
                    )

                except TypeError:
                    continue

        return self._response(
            success=False,
            text=(
                "⚠️ This runtime does not expose "
                "session cancellation yet."
            ),
            session_id=session_id,
        )

    # ============================================================
    # SELF-UPGRADE
    # ============================================================

    async def _self_upgrade(
        self,
        requirement: str,
    ) -> dict[str, Any]:

        requirement = str(
            requirement or ""
        ).strip()

        if not requirement:

            return self._response(
                success=False,
                text=(
                    "⚠️ Missing self-upgrade requirement."
                ),
            )

        runtime = (
            self._engineering_runtime()
        )

        # Prefer an explicit self-upgrade planner.
        for name in (
            "plan_self_upgrade",
            "self_upgrade",
            "plan_upgrade",
        ):

            method = getattr(
                runtime,
                name,
                None,
            )

            if not callable(
                method
            ):
                continue

            result = method(
                requirement
            )

            if hasattr(
                result,
                "__await__",
            ):
                result = await result

            return self._response(
                success=True,
                text=self._json(
                    result
                ),
                result=result,
            )

        # Safe fallback: route the request through normal
        # engineering planning. Actual high/critical self-upgrade
        # authorization remains enforced by the self-upgrade gate.
        result = await runtime.develop(
            requirement
        )

        data = self._result_to_dict(
            result
        )

        return self._response(
            success=self._result_success(
                result,
                data,
            ),
            text=self._development_message(
                success=self._result_success(
                    result,
                    data,
                ),
                data=data,
            ),
            result=data,
        )

    # ============================================================
    # HELP
    # ============================================================

    def _help(
        self,
    ) -> dict[str, Any]:

        return self._response(
            success=True,
            text=(
                "🤖 ARIA Autonomous Engineering\n\n"
                "Commands:\n\n"
                "`/master develop <requirement>`\n"
                "Start autonomous engineering.\n\n"
                "`/master resume <session_id>`\n"
                "Resume a persisted engineering session.\n\n"
                "`/master status`\n"
                "Show engineering runtime status.\n\n"
                "`/master status <session_id>`\n"
                "Show lifecycle state of a session.\n\n"
                "`/master approvals`\n"
                "Show pending approvals.\n\n"
                "`/master approve <approval_id>`\n"
                "Approve a permissioned operation.\n\n"
                "`/master reject <approval_id>`\n"
                "Reject a permissioned operation.\n\n"
                "`/master cancel <session_id>`\n"
                "Request cancellation.\n\n"
                "`/master self-upgrade <requirement>`\n"
                "Plan/request an ARIA self-upgrade.\n\n"
                "Engineering lifecycle:\n"
                "`UNDERSTANDING → PLANNING → "
                "IMPLEMENTING → VERIFYING → TESTING → "
                "DIAGNOSING → RECOVERING → RETESTING → "
                "REASSESSING → ACCEPTING`"
            ),
        )

    # ============================================================
    # RUNTIME ACCESS
    # ============================================================

    def _engineering_runtime(
        self,
    ) -> Any:

        runtime = (
            self.engineering_runtime
        )

        # The Phase1PersistentRuntimeAdapter is already the
        # authoritative gateway. Never wrap it again.
        if (
            callable(
                getattr(
                    runtime,
                    "develop",
                    None,
                )
            )
            and callable(
                getattr(
                    runtime,
                    "resume",
                    None,
                )
            )
            and callable(
                getattr(
                    runtime,
                    "engineering_status",
                    None,
                )
            )
        ):

            return runtime

        # If the supplied runtime exposes a persistent runtime,
        # use that directly.
        persistent = getattr(
            runtime,
            "runtime",
            None,
        )

        if (
            persistent is not None
            and callable(
                getattr(
                    persistent,
                    "develop",
                    None,
                )
            )
        ):

            return persistent

        return runtime

    # ============================================================
    # CONNECTORS
    # ============================================================

    def connect_engineering_runtime(
        self,
        runtime: Any,
    ) -> None:

        if runtime is None:
            raise ValueError(
                "engineering runtime cannot be None."
            )

        self.engineering_runtime = (
            runtime
        )

    def connect_approval_runtime(
        self,
        runtime: Any,
    ) -> None:

        self.approval_runtime = (
            runtime
        )

    # ============================================================
    # RESULT HELPERS
    # ============================================================

    @staticmethod
    def _result_to_dict(
        result: Any,
    ) -> Any:

        if result is None:
            return None

        if isinstance(
            result,
            dict,
        ):
            return dict(
                result
            )

        method = getattr(
            result,
            "to_dict",
            None,
        )

        if callable(
            method
        ):

            try:
                value = method()

                if isinstance(
                    value,
                    dict,
                ):
                    return value

                return value

            except Exception:
                pass

        return {
            "value": str(
                result
            ),
            "success": bool(
                getattr(
                    result,
                    "success",
                    False,
                )
            ),
            "status": str(
                getattr(
                    result,
                    "status",
                    "",
                )
            ),
        }

    @staticmethod
    def _result_success(
        result: Any,
        data: Any = None,
    ) -> bool:

        if isinstance(
            data,
            dict,
        ):

            if "success" in data:
                return bool(
                    data["success"]
                )

        if result is None:
            return False

        return bool(
            getattr(
                result,
                "success",
                False,
            )
        )

    # ============================================================
    # FORMATTING
    # ============================================================

    @staticmethod
    def _bounded(
        value: Any,
        limit: int = 1800,
    ) -> str:

        text = str(
            value or ""
        ).strip()

        if len(text) > limit:
            return (
                text[: limit - 3]
                + "..."
            )

        return text

    @classmethod
    def _json(
        cls,
        value: Any,
    ) -> str:

        try:

            return json.dumps(
                value,
                ensure_ascii=False,
                indent=2,
                default=str,
            )[:3500]

        except Exception:

            return cls._bounded(
                value,
                3500,
            )

    @classmethod
    def _development_message(
        cls,
        *,
        success: bool,
        data: Any,
        session_id: str | None = None,
        resumed: bool = False,
    ) -> str:

        if success:

            heading = (
                "✅ Autonomous engineering accepted."
            )

        else:

            heading = (
                "🛠️ Autonomous engineering "
                "did not reach acceptance."
            )

        lines = [
            heading,
        ]

        if resumed:
            lines.append(
                "↻ Persisted session resumed."
            )

        if session_id:
            lines.append(
                f"🆔 Session: `{session_id}`"
            )

        lines.extend(
            [
                "",
                cls._json(
                    data
                ),
            ]
        )

        return "\n".join(
            lines
        )

    @staticmethod
    def _response(
        *,
        success: bool,
        text: str,
        result: Any = None,
        session_id: str | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:

        return {
            "handled": True,
            "success": bool(
                success
            ),
            "text": str(
                text
            ),
            "result": result,
            "session_id": session_id,
            "error": error,
            "runtime_version": (
                TelegramEngineeringRuntime.VERSION
            ),
        }

    # ============================================================
    # STATUS / HEALTH
    # ============================================================

    def status(
        self,
    ) -> dict[str, Any]:

        runtime = (
            self._engineering_runtime()
        )

        method = getattr(
            runtime,
            "status",
            None,
        )

        if not callable(
            method
        ):

            return {
                "healthy": False,
                "error": (
                    "Engineering runtime does not "
                    "expose status()."
                ),
            }

        try:

            result = method()

            if isinstance(
                result,
                dict,
            ):
                return {
                    **result,
                    "telegram_engineering_runtime": (
                        self.VERSION
                    ),
                }

            return {
                "healthy": True,
                "telegram_engineering_runtime": (
                    self.VERSION
                ),
                "runtime_status": str(
                    result
                ),
            }

        except Exception as exc:

            logger.exception(
                "[TelegramEngineeringRuntime] "
                "Status failed."
            )

            return {
                "healthy": False,
                "telegram_engineering_runtime": (
                    self.VERSION
                ),
                "error": str(
                    exc
                ),
            }

    def health(
        self,
    ) -> dict[str, Any]:

        runtime = (
            self._engineering_runtime()
        )

        method = getattr(
            runtime,
            "health",
            None,
        )

        if not callable(
            method
        ):

            return {
                "healthy": False,
                "telegram_engineering_runtime": (
                    self.VERSION
                ),
                "error": (
                    "Engineering runtime does not "
                    "expose health()."
                ),
            }

        try:

            result = method()

            if isinstance(
                result,
                dict,
            ):

                return {
                    **result,
                    "telegram_engineering_runtime": (
                        self.VERSION
                    ),
                }

            return {
                "healthy": True,
                "telegram_engineering_runtime": (
                    self.VERSION
                ),
            }

        except Exception as exc:

            logger.exception(
                "[TelegramEngineeringRuntime] "
                "Health failed."
            )

            return {
                "healthy": False,
                "telegram_engineering_runtime": (
                    self.VERSION
                ),
                "error": str(
                    exc
                ),
            }


__all__ = [
    "TelegramEngineeringRuntime",
]