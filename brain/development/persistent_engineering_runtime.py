from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass
from typing import Any

from .authoritative_engineering_lifecycle_runtime import (
    AuthoritativeEngineeringLifecycleRuntime,
)
from .authoritative_engineering_persistence import (
    EngineeringPersistence,
)

logger = logging.getLogger(
    "aria.persistent_engineering_runtime"
)


@dataclass(frozen=True)
class PersistentEngineeringResult:
    success: bool
    status: str
    session_id: str
    requirement: str
    result: Any = None
    error: str | None = None
    resumed: bool = False
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        raw_result = self.result

        if hasattr(
            raw_result,
            "to_dict",
        ):
            try:
                raw_result = raw_result.to_dict()
            except Exception:
                pass

        return {
            "success": self.success,
            "status": self.status,
            "session_id": self.session_id,
            "requirement": self.requirement,
            "result": raw_result,
            "error": self.error,
            "resumed": self.resumed,
            "metadata": dict(
                self.metadata or {}
            ),
        }


class PersistentEngineeringRuntime:
    """
    Persistent autonomous engineering runtime.

    Responsibilities:

        session identity
        lifecycle ownership
        persistence
        crash recovery
        checkpointing
        resume
        delegation to existing development engine

    The existing development runtime remains responsible for
    actually performing engineering work.
    """

    VERSION = (
        "PERSISTENT-ENGINEERING-RUNTIME-V2"
    )

    def __init__(
        self,
        development_runtime: Any,
        *,
        persistence: Any | None = None,
    ) -> None:

        if development_runtime is None:
            raise ValueError(
                "development_runtime is required."
            )

        self.development_runtime = (
            development_runtime
        )

        self.persistence = (
            persistence
            if persistence is not None
            else EngineeringPersistence()
        )

        self.lifecycle = (
            AuthoritativeEngineeringLifecycleRuntime(
                development_runtime,
                persistence=self.persistence,
            )
        )

    # ============================================================
    # DEVELOPMENT
    # ============================================================

    async def develop(
        self,
        requirement: str,
        *,
        session_id: str | None = None,
        **kwargs: Any,
    ) -> PersistentEngineeringResult:

        normalized = str(
            requirement or ""
        ).strip()

        if not normalized:
            raise ValueError(
                "Engineering requirement cannot be empty."
            )

        session = (
            self.lifecycle.create_session(
                normalized,
                session_id=session_id,
            )
        )

        resolved_session_id = (
            self.lifecycle._session_id(
                session
            )
        )

        if not resolved_session_id:
            raise RuntimeError(
                "Engineering session did not expose "
                "a valid session_id."
            )

        return await self._execute(
            requirement=normalized,
            session_id=resolved_session_id,
            kwargs=kwargs,
            resumed=False,
        )

    # ============================================================
    # RESUME
    # ============================================================

    async def resume(
        self,
        session_id: str,
        **kwargs: Any,
    ) -> PersistentEngineeringResult:

        resolved_id = str(
            session_id or ""
        ).strip()

        if not resolved_id:
            raise ValueError(
                "session_id is required."
            )

        session = (
            self._load_session(
                resolved_id
            )
        )

        if session is None:

            raise RuntimeError(
                "Engineering session could not be recovered: "
                f"{resolved_id}"
            )

        self.lifecycle.register_existing_session(
            session
        )

        requirement = (
            self._extract_requirement(
                session
            )
        )

        if not requirement:
            raise RuntimeError(
                "Recovered engineering session does not "
                "contain its original requirement."
            )

        logger.info(
            "[PersistentEngineeringRuntime] "
            "Resuming session | session_id=%s",
            resolved_id,
        )

        return await self._execute(
            requirement=requirement,
            session_id=resolved_id,
            kwargs=kwargs,
            resumed=True,
        )

    # ============================================================
    # EXECUTION
    # ============================================================

    async def _execute(
        self,
        *,
        requirement: str,
        session_id: str,
        kwargs: dict[str, Any],
        resumed: bool,
    ) -> PersistentEngineeringResult:

        try:

            # ----------------------------------------------------
            # Authoritative lifecycle
            # ----------------------------------------------------

            self.lifecycle.mark_understanding(
                session_id
            )

            self.lifecycle.mark_planning(
                session_id
            )

            self.lifecycle.mark_graph_ready(
                session_id
            )

            self.lifecycle.mark_implementing(
                session_id
            )

            # ----------------------------------------------------
            # Existing autonomous development engine
            # ----------------------------------------------------

            result = await self._invoke_runtime(
                requirement,
                kwargs,
            )

            success = self._result_success(
                result
            )

            # ----------------------------------------------------
            # Actual result drives lifecycle.
            #
            # We never declare success merely because
            # execution returned without throwing.
            # ----------------------------------------------------

            if success:

                self.lifecycle.mark_verifying(
                    session_id
                )

                self.lifecycle.mark_testing(
                    session_id
                )

                self.lifecycle.mark_reassessing(
                    session_id
                )

                self.lifecycle.mark_accepting(
                    session_id
                )

                accepted = (
                    self._result_accepted(
                        result
                    )
                )

                if accepted or success:

                    self.lifecycle.mark_accepted(
                        session_id
                    )

                    return PersistentEngineeringResult(
                        success=True,
                        status="accepted",
                        session_id=session_id,
                        requirement=requirement,
                        result=result,
                        resumed=resumed,
                        metadata={
                            "runtime_version": self.VERSION,
                            "lifecycle_integrated": True,
                        },
                    )

            # ----------------------------------------------------
            # Failure path
            # ----------------------------------------------------

            self.lifecycle.mark_diagnosing(
                session_id
            )

            self.lifecycle.mark_recovering(
                session_id
            )

            self.lifecycle.mark_retesting(
                session_id
            )

            self.lifecycle.mark_reassessing(
                session_id
            )

            # The underlying engine has already performed whatever
            # bounded recovery it supports. If its final result is
            # still unsuccessful, the authoritative session must
            # remain failed rather than pretending recovery succeeded.

            self.lifecycle.mark_failed(
                session_id
            )

            return PersistentEngineeringResult(
                success=False,
                status="failed",
                session_id=session_id,
                requirement=requirement,
                result=result,
                resumed=resumed,
                metadata={
                    "runtime_version": self.VERSION,
                    "lifecycle_integrated": True,
                },
            )

        except Exception as exc:

            logger.exception(
                "[PersistentEngineeringRuntime] "
                "Engineering lifecycle execution failed."
            )

            self.lifecycle.mark_failed(
                session_id
            )

            return PersistentEngineeringResult(
                success=False,
                status="failed",
                session_id=session_id,
                requirement=requirement,
                error=str(exc),
                resumed=resumed,
                metadata={
                    "runtime_version": self.VERSION,
                    "lifecycle_integrated": True,
                },
            )

    # ============================================================
    # DEVELOPMENT RUNTIME INVOCATION
    # ============================================================

    async def _invoke_runtime(
        self,
        requirement: str,
        kwargs: dict[str, Any],
    ) -> Any:

        runtime = self.development_runtime

        method = getattr(
            runtime,
            "develop",
            None,
        )

        if not callable(method):

            method = getattr(
                runtime,
                "execute",
                None,
            )

        if not callable(method):

            raise RuntimeError(
                "Development runtime does not expose "
                "develop() or execute()."
            )

        try:

            signature = inspect.signature(
                method
            )

            parameters = signature.parameters

            accepted_kwargs: dict[str, Any] = {}

            for key, value in kwargs.items():

                if key in parameters:
                    accepted_kwargs[
                        key
                    ] = value

            result = method(
                requirement,
                **accepted_kwargs,
            )

        except (
            TypeError,
            ValueError,
        ):

            result = method(
                requirement
            )

        if inspect.isawaitable(
            result
        ):
            return await result

        return result

    # ============================================================
    # RESULT INTERPRETATION
    # ============================================================

    @staticmethod
    def _result_success(
        result: Any,
    ) -> bool:

        if result is None:
            return False

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

        value = getattr(
            result,
            "success",
            None,
        )

        if value is not None:
            return bool(
                value
            )

        return False

    @staticmethod
    def _result_accepted(
        result: Any,
    ) -> bool:

        if isinstance(
            result,
            dict,
        ):

            if "accepted" in result:
                return bool(
                    result["accepted"]
                )

            status = str(
                result.get(
                    "status",
                    "",
                )
            ).lower()

            return status in {
                "accepted",
                "completed",
                "success",
            }

        accepted = getattr(
            result,
            "accepted",
            None,
        )

        if accepted is not None:
            return bool(
                accepted
            )

        status = str(
            getattr(
                result,
                "status",
                "",
            )
        ).lower()

        return status in {
            "accepted",
            "completed",
            "success",
        }

    # ============================================================
    # RECOVERY
    # ============================================================

    def _load_session(
        self,
        session_id: str,
    ) -> Any:

        for method_name in (
            "load_session",
            "load",
            "recover",
        ):

            method = getattr(
                self.persistence,
                method_name,
                None,
            )

            if not callable(method):
                continue

            try:

                value = method(
                    session_id
                )

                if inspect.isawaitable(
                    value
                ):
                    logger.warning(
                        "[PersistentEngineeringRuntime] "
                        "Async persistence loader cannot be awaited "
                        "from this synchronous recovery boundary."
                    )
                    continue

                if value is not None:
                    return value

            except (
                KeyError,
                FileNotFoundError,
            ):

                continue

            except Exception:

                logger.exception(
                    "[PersistentEngineeringRuntime] "
                    "Session recovery failed."
                )

        return None

    @staticmethod
    def _extract_requirement(
        session: Any,
    ) -> str:

        for name in (
            "requirement",
            "raw_request",
            "objective",
            "goal",
        ):

            value = getattr(
                session,
                name,
                None,
            )

            if value is None:
                continue

            if isinstance(
                value,
                str,
            ):

                if value.strip():
                    return value.strip()

            raw_text = getattr(
                value,
                "raw_text",
                None,
            )

            if raw_text:
                return str(
                    raw_text
                ).strip()

        return ""

    # ============================================================
    # STATUS
    # ============================================================

    async def status(
        self,
        session_id: str,
    ) -> dict[str, Any]:

        return self.lifecycle.status(
            session_id
        )

    async def recoverable_sessions(
        self,
    ) -> tuple[str, ...]:

        method = getattr(
            self.persistence,
            "recoverable_sessions",
            None,
        )

        if not callable(method):
            return ()

        try:

            result = method()

            if inspect.isawaitable(
                result
            ):
                result = await result

            if result is None:
                return ()

            return tuple(
                str(item)
                for item in result
            )

        except Exception:

            logger.exception(
                "[PersistentEngineeringRuntime] "
                "Recoverable-session lookup failed."
            )

            return ()

    async def checkpoint(
        self,
        session_id: str,
    ) -> bool:

        session = self.lifecycle.get_session(
            session_id
        )

        if session is None:
            return False

        checkpoint = getattr(
            self.persistence,
            "checkpoint",
            None,
        )

        if not callable(checkpoint):
            return False

        try:

            result = checkpoint(
                session
            )

            if inspect.isawaitable(
                result
            ):
                result = await result

            return (
                True
                if result is None
                else bool(result)
            )

        except Exception:

            logger.exception(
                "[PersistentEngineeringRuntime] "
                "Checkpoint failed."
            )

            return False

    # ============================================================
    # HEALTH
    # ============================================================

    def health(
        self,
    ) -> dict[str, Any]:

        lifecycle_health = (
            self.lifecycle.health()
        )

        return {
            "healthy": bool(
                lifecycle_health.get(
                    "healthy",
                    False,
                )
            ),
            "version": self.VERSION,
            "persistent": True,
            "lifecycle_integrated": True,
            "lifecycle": lifecycle_health,
        }


__all__ = [
    "PersistentEngineeringResult",
    "PersistentEngineeringRuntime",
]