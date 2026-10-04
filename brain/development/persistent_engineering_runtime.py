from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass, field
from typing import Any

from .authoritative_engineering_persistence import (
    EngineeringPersistence,
)
from .contracts import (
    EngineeringPhase,
    EngineeringSession,
)

logger = logging.getLogger(
    "aria.persistent_engineering_runtime"
)


@dataclass(frozen=True)
class PersistentEngineeringResult:
    """
    Result returned by the persistence-aware engineering runtime.
    """

    success: bool
    session_id: str
    status: str

    resumed: bool = False
    checkpointed: bool = False

    result: Any = None
    error: str | None = None

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    @property
    def accepted(self) -> bool:
        return bool(
            self.success
            and self.status == "accepted"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "session_id": self.session_id,
            "status": self.status,
            "resumed": self.resumed,
            "checkpointed": self.checkpointed,
            "error": self.error,
            "metadata": dict(self.metadata),
        }


class PersistentEngineeringRuntime:
    """
    Authoritative persistence-aware wrapper around ARIA's engineering
    runtime.

    Lifecycle:

        requirement
            ↓
        create/restore session
            ↓
        checkpoint
            ↓
        existing engineering runtime
            ↓
        checkpoint
            ↓
        final result

    If the process disappears during execution, the session and evidence
    remain recoverable.

    This class deliberately does NOT:
        - write repository source files itself
        - execute arbitrary shell commands
        - push GitHub
        - deploy
        - bypass authorization
        - declare success from persistence alone
    """

    VERSION = (
        "PERSISTENT-ENGINEERING-RUNTIME-V1"
    )

    def __init__(
        self,
        engineering_runtime: Any,
        *,
        persistence: EngineeringPersistence | None = None,
    ) -> None:
        if engineering_runtime is None:
            raise ValueError(
                "engineering_runtime is required."
            )

        self.engineering_runtime = (
            engineering_runtime
        )

        self.persistence = (
            persistence
            or EngineeringPersistence()
        )

        self._active_sessions: dict[
            str,
            EngineeringSession,
        ] = {}

    # ==========================================================
    # START
    # ==========================================================

    async def develop(
        self,
        requirement: str,
        *,
        session_id: str | None = None,
        **kwargs: Any,
    ) -> PersistentEngineeringResult:
        """
        Start a new engineering request.

        If session_id already exists, resume() is used instead of
        accidentally creating a duplicate engineering session.
        """

        requirement_text = str(
            requirement
        ).strip()

        if not requirement_text:
            return PersistentEngineeringResult(
                success=False,
                session_id=(
                    str(session_id or "")
                ),
                status="blocked",
                error=(
                    "Engineering requirement cannot be empty."
                ),
            )

        if session_id:
            existing = await self.persistence.load_session(
                session_id
            )

            if existing is not None:
                return await self._resume_existing(
                    existing,
                    **kwargs,
                )

        session = self._create_session(
            requirement_text,
            session_id=session_id,
        )

        sid = self._session_id(
            session
        )

        if not sid:
            return PersistentEngineeringResult(
                success=False,
                session_id="",
                status="blocked",
                error=(
                    "Engineering session could not "
                    "be assigned a session_id."
                ),
            )

        self._active_sessions[
            sid
        ] = session

        await self._checkpoint(
            session
        )

        try:
            self._advance(
                session,
                EngineeringPhase.UNDERSTANDING,
            )

            await self._checkpoint(
                session
            )

            result = await self._invoke_runtime(
                requirement_text,
                session=session,
                **kwargs,
            )

            self._apply_result_state(
                session,
                result,
            )

            await self._checkpoint(
                session
            )

            return self._result(
                session,
                result,
                resumed=False,
            )

        except Exception as exc:
            logger.exception(
                "[PersistentEngineeringRuntime] "
                "Engineering execution failed."
            )

            self._mark_failure(
                session,
                exc,
            )

            try:
                await self._checkpoint(
                    session
                )
            except Exception:
                logger.exception(
                    "[PersistentEngineeringRuntime] "
                    "Failure checkpoint failed."
                )

            return PersistentEngineeringResult(
                success=False,
                session_id=sid,
                status="failed",
                resumed=False,
                checkpointed=True,
                error=str(exc),
                metadata={
                    "runtime_version": self.VERSION,
                    "exception_type": type(
                        exc
                    ).__name__,
                },
            )

    # ==========================================================
    # RESUME
    # ==========================================================

    async def resume(
        self,
        session_id: str,
        **kwargs: Any,
    ) -> PersistentEngineeringResult:
        """
        Restore and continue an interrupted engineering session.
        """

        normalized = str(
            session_id
        ).strip()

        if not normalized:
            return PersistentEngineeringResult(
                success=False,
                session_id="",
                status="blocked",
                error=(
                    "session_id is required."
                ),
            )

        session = (
            await self.persistence.recover_latest(
                normalized
            )
        )

        if session is None:
            return PersistentEngineeringResult(
                success=False,
                session_id=normalized,
                status="not_found",
                error=(
                    "No persisted engineering session "
                    f"was found for '{normalized}'."
                ),
            )

        return await self._resume_existing(
            session,
            **kwargs,
        )

    async def _resume_existing(
        self,
        session: EngineeringSession,
        **kwargs: Any,
    ) -> PersistentEngineeringResult:
        sid = self._session_id(
            session
        )

        if not sid:
            return PersistentEngineeringResult(
                success=False,
                session_id="",
                status="blocked",
                error=(
                    "Persisted session has no session_id."
                ),
            )

        self._active_sessions[
            sid
        ] = session

        if self._is_terminal(
            session
        ):
            return PersistentEngineeringResult(
                success=(
                    self._session_success(
                        session
                    )
                ),
                session_id=sid,
                status=(
                    self._session_status(
                        session
                    )
                ),
                resumed=True,
                checkpointed=True,
                metadata={
                    "runtime_version": self.VERSION,
                    "terminal_session": True,
                },
            )

        requirement = self._requirement(
            session
        )

        if not requirement:
            return PersistentEngineeringResult(
                success=False,
                session_id=sid,
                status="blocked",
                resumed=True,
                checkpointed=True,
                error=(
                    "Persisted session contains no "
                    "recoverable engineering requirement."
                ),
            )

        try:
            self._mark_resume(
                session
            )

            await self._checkpoint(
                session
            )

            result = await self._invoke_runtime(
                requirement,
                session=session,
                **kwargs,
            )

            self._apply_result_state(
                session,
                result,
            )

            await self._checkpoint(
                session
            )

            return self._result(
                session,
                result,
                resumed=True,
            )

        except Exception as exc:
            logger.exception(
                "[PersistentEngineeringRuntime] "
                "Resume execution failed."
            )

            self._mark_failure(
                session,
                exc,
            )

            try:
                await self._checkpoint(
                    session
                )
            except Exception:
                logger.exception(
                    "[PersistentEngineeringRuntime] "
                    "Resume failure checkpoint failed."
                )

            return PersistentEngineeringResult(
                success=False,
                session_id=sid,
                status="failed",
                resumed=True,
                checkpointed=True,
                error=str(exc),
                metadata={
                    "runtime_version": self.VERSION,
                    "exception_type": type(
                        exc
                    ).__name__,
                },
            )

    # ==========================================================
    # STATUS
    # ==========================================================

    async def status(
        self,
        session_id: str,
    ) -> dict[str, Any]:
        session = self._active_sessions.get(
            str(session_id).strip()
        )

        if session is None:
            session = (
                await self.persistence.load_session(
                    session_id
                )
            )

        if session is None:
            return {
                "found": False,
                "session_id": str(
                    session_id
                ),
            }

        evidence = (
            await self.persistence.load_evidence(
                session_id
            )
        )

        return {
            "found": True,
            "session_id": self._session_id(
                session
            ),
            "status": self._session_status(
                session
            ),
            "phase": self._phase_name(
                session
            ),
            "requirement": self._requirement(
                session
            ),
            "evidence_count": len(
                evidence
            ),
            "terminal": self._is_terminal(
                session
            ),
            "success": self._session_success(
                session
            ),
        }

    async def recoverable_sessions(
        self,
    ) -> tuple[str, ...]:
        return (
            await self.persistence.recoverable_sessions()
        )

    # ==========================================================
    # CHECKPOINT
    # ==========================================================

    async def checkpoint(
        self,
        session_id: str,
    ) -> bool:
        session = self._active_sessions.get(
            str(session_id).strip()
        )

        if session is None:
            session = (
                await self.persistence.load_session(
                    session_id
                )
            )

        if session is None:
            return False

        return await self._checkpoint(
            session
        )

    async def _checkpoint(
        self,
        session: EngineeringSession,
    ) -> bool:
        await self.persistence.checkpoint(
            session
        )

        return True

    # ==========================================================
    # RUNTIME INVOCATION
    # ==========================================================

    async def _invoke_runtime(
        self,
        requirement: str,
        *,
        session: EngineeringSession,
        **kwargs: Any,
    ) -> Any:
        """
        Compatibility boundary for existing engineering runtimes.

        Supported methods:
            develop()
            execute()
            run()
        """

        runtime = (
            self.engineering_runtime
        )

        method = None

        for name in (
            "develop",
            "execute",
            "run",
        ):
            candidate = getattr(
                runtime,
                name,
                None,
            )

            if callable(candidate):
                method = candidate
                break

        if method is None:
            raise RuntimeError(
                "Connected engineering runtime exposes "
                "no develop(), execute(), or run() method."
            )

        try:
            signature = inspect.signature(
                method
            )

            parameters = signature.parameters

            call_kwargs: dict[str, Any] = {}

            if (
                "session" in parameters
            ):
                call_kwargs[
                    "session"
                ] = session

            if (
                "engineering_session"
                in parameters
            ):
                call_kwargs[
                    "engineering_session"
                ] = session

            if (
                "session_id"
                in parameters
            ):
                call_kwargs[
                    "session_id"
                ] = self._session_id(
                    session
                )

            for key, value in kwargs.items():
                if key in parameters:
                    call_kwargs[
                        key
                    ] = value

            result = method(
                requirement,
                **call_kwargs,
            )

        except (TypeError, ValueError):
            result = method(
                requirement
            )

        if inspect.isawaitable(
            result
        ):
            result = await result

        return result

    # ==========================================================
    # SESSION CREATION
    # ==========================================================

    @staticmethod
    def _create_session(
        requirement: str,
        *,
        session_id: str | None,
    ) -> EngineeringSession:
        """
        Create an authoritative session using the richest compatible
        constructor available.
        """

        candidates = (
            {
                "session_id": session_id,
                "requirement": requirement,
            },
            {
                "session_id": session_id,
                "raw_request": requirement,
            },
            {
                "requirement": requirement,
            },
            {
                "raw_request": requirement,
            },
        )

        last_error: Exception | None = None

        for payload in candidates:
            if payload.get(
                "session_id"
            ) is None:
                payload.pop(
                    "session_id",
                    None,
                )

            try:
                return EngineeringSession(
                    **payload
                )

            except Exception as exc:
                last_error = exc

        raise RuntimeError(
            "Unable to construct EngineeringSession."
        ) from last_error

    # ==========================================================
    # STATE APPLICATION
    # ==========================================================

    def _apply_result_state(
        self,
        session: EngineeringSession,
        result: Any,
    ) -> None:
        success = self._result_success(
            result
        )

        status = self._result_status(
            result
        )

        if success:
            self._advance_safely(
                session,
                EngineeringPhase.ACCEPTING,
            )

            self._advance_safely(
                session,
                EngineeringPhase.ACCEPTED,
            )

            return

        if status in {
            "blocked",
            "rejected",
        }:
            self._advance_safely(
                session,
                EngineeringPhase.BLOCKED,
            )

            return

        self._advance_safely(
            session,
            EngineeringPhase.FAILED,
        )

    def _mark_failure(
        self,
        session: EngineeringSession,
        exc: Exception,
    ) -> None:
        metadata = getattr(
            session,
            "metadata",
            None,
        )

        if isinstance(
            metadata,
            dict,
        ):
            metadata[
                "last_runtime_error"
            ] = str(exc)

            metadata[
                "last_runtime_error_type"
            ] = type(
                exc
            ).__name__

        self._advance_safely(
            session,
            EngineeringPhase.FAILED,
        )

    def _mark_resume(
        self,
        session: EngineeringSession,
    ) -> None:
        metadata = getattr(
            session,
            "metadata",
            None,
        )

        if isinstance(
            metadata,
            dict,
        ):
            metadata[
                "resume_count"
            ] = int(
                metadata.get(
                    "resume_count",
                    0,
                )
            ) + 1

            metadata[
                "last_resumed"
            ] = True

    # ==========================================================
    # LIFECYCLE
    # ==========================================================

    @staticmethod
    def _advance(
        session: EngineeringSession,
        phase: EngineeringPhase,
    ) -> None:
        transition = getattr(
            session,
            "transition",
            None,
        )

        if callable(transition):
            transition(
                phase
            )
            return

        advance = getattr(
            session,
            "advance",
            None,
        )

        if callable(advance):
            advance(
                phase
            )
            return

        raise RuntimeError(
            "EngineeringSession exposes no "
            "transition()/advance() lifecycle API."
        )

    @classmethod
    def _advance_safely(
        cls,
        session: EngineeringSession,
        phase: EngineeringPhase,
    ) -> None:
        try:
            cls._advance(
                session,
                phase,
            )

        except Exception:
            logger.debug(
                "[PersistentEngineeringRuntime] "
                "Lifecycle transition unavailable: %s",
                phase,
                exc_info=True,
            )

    # ==========================================================
    # RESULT NORMALIZATION
    # ==========================================================

    def _result(
        self,
        session: EngineeringSession,
        result: Any,
        *,
        resumed: bool,
    ) -> PersistentEngineeringResult:
        success = self._result_success(
            result
        )

        status = self._result_status(
            result
        )

        return PersistentEngineeringResult(
            success=success,
            session_id=self._session_id(
                session
            ),
            status=status,
            resumed=resumed,
            checkpointed=True,
            result=result,
            error=(
                None
                if success
                else self._result_error(
                    result
                )
            ),
            metadata={
                "runtime_version": self.VERSION,
                "result_type": type(
                    result
                ).__name__,
            },
        )

    @staticmethod
    def _result_success(
        result: Any,
    ) -> bool:
        if result is None:
            return False

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
            if "success" in result:
                return bool(
                    result["success"]
                )

        return False

    @staticmethod
    def _result_status(
        result: Any,
    ) -> str:
        if result is None:
            return "failed"

        value = getattr(
            result,
            "status",
            None,
        )

        if value is None and isinstance(
            result,
            dict,
        ):
            value = result.get(
                "status"
            )

        if value is None:
            return (
                "accepted"
                if bool(
                    getattr(
                        result,
                        "success",
                        False,
                    )
                )
                else "failed"
            )

        return str(
            value
        ).strip().lower()

    @staticmethod
    def _result_error(
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
                )[:4000]

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
                    )[:4000]

        return None

    # ==========================================================
    # SESSION HELPERS
    # ==========================================================

    @staticmethod
    def _session_id(
        session: EngineeringSession,
    ) -> str:
        value = getattr(
            session,
            "session_id",
            None,
        )

        if value is None:
            value = getattr(
                session,
                "id",
                None,
            )

        return str(
            value or ""
        ).strip()

    @staticmethod
    def _requirement(
        session: EngineeringSession,
    ) -> str:
        for name in (
            "requirement",
            "raw_request",
            "objective",
        ):
            value = getattr(
                session,
                name,
                None,
            )

            if isinstance(
                value,
                str,
            ) and value.strip():
                return value.strip()

        for name in (
            "engineering_requirement",
            "requirement_contract",
        ):
            value = getattr(
                session,
                name,
                None,
            )

            if value is None:
                continue

            raw = getattr(
                value,
                "raw_request",
                None,
            )

            if raw:
                return str(
                    raw
                ).strip()

            raw = getattr(
                value,
                "raw_text",
                None,
            )

            if raw:
                return str(
                    raw
                ).strip()

        return ""

    @staticmethod
    def _phase_name(
        session: EngineeringSession,
    ) -> str:
        for name in (
            "phase",
            "state",
        ):
            value = getattr(
                session,
                name,
                None,
            )

            if value is not None:
                raw = getattr(
                    value,
                    "value",
                    value,
                )

                return str(
                    raw
                )

        return "unknown"

    @classmethod
    def _session_status(
        cls,
        session: EngineeringSession,
    ) -> str:
        phase = cls._phase_name(
            session
        )

        if phase in {
            "accepted",
            "ACCEPTED",
        }:
            return "accepted"

        if phase in {
            "blocked",
            "BLOCKED",
        }:
            return "blocked"

        if phase in {
            "failed",
            "FAILED",
        }:
            return "failed"

        return phase.lower()

    @classmethod
    def _session_success(
        cls,
        session: EngineeringSession,
    ) -> bool:
        return (
            cls._session_status(
                session
            )
            == "accepted"
        )

    @classmethod
    def _is_terminal(
        cls,
        session: EngineeringSession,
    ) -> bool:
        return cls._session_status(
            session
        ) in {
            "accepted",
            "failed",
            "blocked",
        }


__all__ = [
    "PersistentEngineeringResult",
    "PersistentEngineeringRuntime",
]