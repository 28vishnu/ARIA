from __future__ import annotations

import inspect
import logging
from typing import Any

from .persistent_engineering_runtime import (
    PersistentEngineeringRuntime,
    PersistentEngineeringResult,
)

logger = logging.getLogger("aria")


class Phase1PersistentRuntimeAdapter:
    """
    Final Phase 1 runtime integration boundary.

    Bootstrap continues to create this adapter exactly as before.

    The adapter now routes engineering requests through the final
    autonomous-engineer facade while preserving the existing persistent
    Phase 1 runtime and capability-registry compatibility.
    """

    def __init__(
        self,
        legacy_phase1_runtime: Any,
        *,
        development_controller: Any = None,
    ) -> None:
        if legacy_phase1_runtime is None:
            raise ValueError(
                "legacy_phase1_runtime is required."
            )

        self.legacy_phase1_runtime = legacy_phase1_runtime
        self.development_controller = development_controller

        self.persistent_runtime = (
            self._build_persistent_runtime()
        )

        self.final_engineer = (
            self._build_final_engineer()
        )

        logger.info(
            "[Phase1][FinalRuntime] Initialized | "
            "final_engineer=%s | persistent_runtime=%s",
            self.final_engineer is not None,
            type(self.persistent_runtime).__name__,
        )

    # ============================================================
    # Runtime construction
    # ============================================================

    def _build_persistent_runtime(self) -> Any:
        """
        Reuse an already-created persistent runtime when supplied.

        Otherwise construct one when its constructor supports the
        currently available runtime dependencies.
        """

        if isinstance(
            self.legacy_phase1_runtime,
            PersistentEngineeringRuntime,
        ):
            return self.legacy_phase1_runtime

        try:
            signature = inspect.signature(
                PersistentEngineeringRuntime
            )

            parameters = signature.parameters
            kwargs: dict[str, Any] = {}

            aliases = {
                "legacy_runtime": self.legacy_phase1_runtime,
                "legacy_phase1_runtime": self.legacy_phase1_runtime,
                "runtime": self.legacy_phase1_runtime,
                "development_controller": (
                    self.development_controller
                ),
            }

            for name in parameters:
                if name in aliases:
                    kwargs[name] = aliases[name]

            if kwargs:
                try:
                    return PersistentEngineeringRuntime(
                        **kwargs
                    )
                except Exception:
                    logger.exception(
                        "[Phase1][FinalRuntime] "
                        "Persistent runtime construction failed."
                    )

        except Exception:
            logger.exception(
                "[Phase1][FinalRuntime] "
                "Persistent runtime inspection failed."
            )

        return self.legacy_phase1_runtime

    def _build_final_engineer(self) -> Any:
        """
        Construct FinalAutonomousEngineer while remaining compatible
        with its constructor signature.
        """

        try:
            from .final_autonomous_engineer import (
                FinalAutonomousEngineer,
            )
        except Exception as exc:
            logger.warning(
                "[Phase1][FinalRuntime] "
                "FinalAutonomousEngineer unavailable: %s",
                exc,
            )
            return None

        try:
            signature = inspect.signature(
                FinalAutonomousEngineer
            )

            available = {
                "legacy_runtime": (
                    self.legacy_phase1_runtime
                ),
                "legacy_phase1_runtime": (
                    self.legacy_phase1_runtime
                ),
                "persistent_runtime": (
                    self.persistent_runtime
                ),
                "development_controller": (
                    self.development_controller
                ),
            }

            kwargs: dict[str, Any] = {}

            for name in signature.parameters:
                if name in available:
                    kwargs[name] = available[name]

            try:
                engineer = FinalAutonomousEngineer(
                    **kwargs
                )
            except TypeError:
                engineer = FinalAutonomousEngineer()

            logger.info(
                "[Phase1][FinalRuntime] "
                "Final autonomous engineer connected | "
                "class=%s",
                type(engineer).__name__,
            )

            return engineer

        except Exception:
            logger.exception(
                "[Phase1][FinalRuntime] "
                "Final autonomous engineer initialization failed."
            )
            return None

    # ============================================================
    # Invocation
    # ============================================================

    @staticmethod
    async def _invoke(
        target: Any,
        method_name: str,
        *args: Any,
        **kwargs: Any,
    ) -> Any:

        method = getattr(
            target,
            method_name,
            None,
        )

        if method is None:
            raise AttributeError(
                f"{type(target).__name__} has no "
                f"method '{method_name}'."
            )

        result = method(
            *args,
            **kwargs,
        )

        if inspect.isawaitable(result):
            return await result

        return result

    @staticmethod
    def _success(result: Any) -> bool:

        if isinstance(result, bool):
            return result

        if isinstance(result, dict):
            return bool(
                result.get(
                    "success",
                    False,
                )
            )

        return bool(
            getattr(
                result,
                "success",
                False,
            )
        )

    @staticmethod
    def _accepted(result: Any) -> bool:

        if isinstance(result, dict):
            return bool(
                result.get(
                    "accepted",
                    result.get(
                        "is_accepted",
                        False,
                    ),
                )
            )

        return bool(
            getattr(
                result,
                "accepted",
                getattr(
                    result,
                    "is_accepted",
                    False,
                ),
            )
        )

    @staticmethod
    def _status(result: Any) -> str:

        if isinstance(result, dict):
            return str(
                result.get(
                    "status",
                    "completed"
                    if result.get("success")
                    else "failed",
                )
            )

        return str(
            getattr(
                result,
                "status",
                "completed"
                if getattr(
                    result,
                    "success",
                    False,
                )
                else "failed",
            )
        )

    @staticmethod
    def _session_id(
        result: Any,
    ) -> str | None:

        if isinstance(result, dict):
            value = result.get(
                "session_id"
            )
        else:
            value = getattr(
                result,
                "session_id",
                None,
            )

        return (
            str(value)
            if value
            else None
        )

    @staticmethod
    def _summary(
        result: Any,
    ) -> str:

        if isinstance(result, dict):
            return str(
                result.get(
                    "summary",
                    result.get(
                        "message",
                        "",
                    ),
                )
            )

        return str(
            getattr(
                result,
                "summary",
                getattr(
                    result,
                    "message",
                    "",
                ),
            )
        )

    @staticmethod
    def _errors(
        result: Any,
    ) -> tuple[str, ...]:

        if isinstance(result, dict):
            value = result.get(
                "errors",
                (),
            )
        else:
            value = getattr(
                result,
                "errors",
                (),
            )

        if value is None:
            return ()

        if isinstance(value, str):
            return (value,)

        try:
            return tuple(
                str(item)
                for item in value
                if str(item).strip()
            )
        except TypeError:
            return (str(value),)

    def _normalize_result(
        self,
        result: Any,
    ) -> Any:
        """
        Preserve richer result objects while making plain dictionaries
        compatible with the existing persistent result contract.
        """

        if isinstance(
            result,
            PersistentEngineeringResult,
        ):
            return result

        if (
            hasattr(result, "success")
            and hasattr(result, "accepted")
            and hasattr(result, "status")
        ):
            return result

        return PersistentEngineeringResult(
            success=self._success(result),
            accepted=self._accepted(result),
            status=self._status(result),
            session_id=self._session_id(result),
            summary=self._summary(result),
            errors=self._errors(result),
            metadata={
                "final_engineer_result": (
                    result.to_dict()
                    if hasattr(
                        result,
                        "to_dict",
                    )
                    else result
                ),
            },
        )

    # ============================================================
    # Final autonomous engineering API
    # ============================================================

    async def develop(
        self,
        requirement: str,
        *,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:

        if self.final_engineer is not None:

            logger.info(
                "[Phase1][FinalRuntime] "
                "Starting final autonomous engineering | "
                "session=%s",
                session_id or "new",
            )

            try:
                result = await self._invoke(
                    self.final_engineer,
                    "develop",
                    requirement,
                    session_id=session_id,
                    metadata=metadata,
                    **kwargs,
                )

            except TypeError:
                logger.warning(
                    "[Phase1][FinalRuntime] "
                    "Final engineer argument compatibility "
                    "fallback activated."
                )

                result = await self._invoke(
                    self.final_engineer,
                    "develop",
                    requirement,
                )

            normalized = (
                self._normalize_result(
                    result
                )
            )

            logger.info(
                "[Phase1][FinalRuntime] "
                "Final autonomous engineering finished | "
                "success=%s | accepted=%s | status=%s",
                self._success(normalized),
                self._accepted(normalized),
                self._status(normalized),
            )

            return normalized

        logger.info(
            "[Phase1][FinalRuntime] "
            "Final engineer unavailable; "
            "using persistent Phase 1 runtime."
        )

        return await self._invoke(
            self.persistent_runtime,
            "develop",
            requirement,
            session_id=session_id,
            metadata=metadata,
            **kwargs,
        )

    async def execute(
        self,
        requirement: str,
        **kwargs: Any,
    ) -> Any:

        return await self.develop(
            requirement,
            **kwargs,
        )

    async def run(
        self,
        requirement: str,
        **kwargs: Any,
    ) -> Any:

        return await self.develop(
            requirement,
            **kwargs,
        )

    # ============================================================
    # Resume
    # ============================================================

    async def resume(
        self,
        session_id: str,
        **kwargs: Any,
    ) -> Any:

        if self.final_engineer is not None:

            method = getattr(
                self.final_engineer,
                "resume",
                None,
            )

            if method is not None:

                try:
                    result = await self._invoke(
                        self.final_engineer,
                        "resume",
                        session_id,
                        **kwargs,
                    )

                    return self._normalize_result(
                        result
                    )

                except Exception:
                    logger.exception(
                        "[Phase1][FinalRuntime] "
                        "Final engineer resume failed."
                    )

        return await self._invoke(
            self.persistent_runtime,
            "resume",
            session_id,
            **kwargs,
        )

    # ============================================================
    # Status
    # ============================================================

    def engineering_status(
        self,
        session_id: str | None = None,
    ) -> dict[str, Any]:

        if self.final_engineer is not None:

            method = getattr(
                self.final_engineer,
                "status",
                None,
            )

            if method is not None:

                try:
                    value = method(
                        session_id=session_id
                    )

                    if (
                        not inspect.isawaitable(
                            value
                        )
                        and isinstance(
                            value,
                            dict,
                        )
                    ):
                        return value

                except Exception:
                    logger.debug(
                        "[Phase1][FinalRuntime] "
                        "Final engineer status unavailable.",
                        exc_info=True,
                    )

        for name in (
            "engineering_status",
            "status",
        ):

            method = getattr(
                self.persistent_runtime,
                name,
                None,
            )

            if method is None:
                continue

            try:
                value = method(
                    session_id=session_id
                )
            except TypeError:
                value = method()

            if isinstance(
                value,
                dict,
            ):
                return value

        return {
            "healthy": False,
            "status": "unavailable",
            "session_id": session_id,
        }

    def status(
        self,
        session_id: str | None = None,
    ) -> dict[str, Any]:

        return self.engineering_status(
            session_id=session_id
        )

    # ============================================================
    # Persistence
    # ============================================================

    def checkpoint(
        self,
        session_id: str | None = None,
    ) -> Any:

        method = getattr(
            self.persistent_runtime,
            "checkpoint",
            None,
        )

        if method is None:
            return None

        try:
            return method(
                session_id=session_id
            )
        except TypeError:
            return method()

    def save(
        self,
        session_id: str | None = None,
    ) -> Any:

        method = getattr(
            self.persistent_runtime,
            "save",
            None,
        )

        if method is None:
            return self.checkpoint(
                session_id=session_id
            )

        try:
            return method(
                session_id=session_id
            )
        except TypeError:
            return method()

    def persist(
        self,
        session_id: str | None = None,
    ) -> Any:

        return self.save(
            session_id=session_id
        )

    # ============================================================
    # Health
    # ============================================================

    def health(self) -> dict[str, Any]:

        result: dict[str, Any] = {}

        method = getattr(
            self.persistent_runtime,
            "health",
            None,
        )

        if method is not None:

            try:
                value = method()

                if isinstance(
                    value,
                    dict,
                ):
                    result.update(value)

            except Exception:
                logger.debug(
                    "[Phase1][FinalRuntime] "
                    "Persistent runtime health failed.",
                    exc_info=True,
                )

        result.update(
            {
                "adapter": True,
                "final_autonomous_engineer": (
                    self.final_engineer
                    is not None
                ),
                "runtime_type": type(
                    self.persistent_runtime
                ).__name__,
            }
        )

        return result

    # ============================================================
    # Capability registry compatibility
    # ============================================================

    def get(
        self,
        name: str,
        default: Any = None,
    ) -> Any:

        for source in (
            self.persistent_runtime,
            self.legacy_phase1_runtime,
        ):

            getter = getattr(
                source,
                "get",
                None,
            )

            if getter is None:
                continue

            try:
                value = getter(
                    name,
                    default,
                )
            except TypeError:
                try:
                    value = getter(
                        name
                    )
                except Exception:
                    continue

            if value is not None:
                return value

        return default

    def __getattr__(
        self,
        name: str,
    ) -> Any:

        for source in (
            self.persistent_runtime,
            self.legacy_phase1_runtime,
        ):

            try:
                return getattr(
                    source,
                    name,
                )
            except AttributeError:
                continue

        raise AttributeError(
            f"{type(self).__name__} "
            f"has no attribute {name!r}"
        )


__all__ = [
    "Phase1PersistentRuntimeAdapter",
]