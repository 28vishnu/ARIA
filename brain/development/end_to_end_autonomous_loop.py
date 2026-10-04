from __future__ import annotations

import inspect
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from .contracts.engineering_state import EngineeringPhase
from .contracts.engineering_store import EngineeringStore
from .contracts.engineering_session import EngineeringSession
from .contracts.engineering_result import (
    EngineeringOutcome,
    EngineeringResult,
)


logger = logging.getLogger("aria.end_to_end_autonomous_loop")


@dataclass
class AutonomousLoopResult:
    """
    Stable result for the complete Phase 1 engineering lifecycle.
    """

    success: bool
    outcome: str
    status: str
    session_id: str
    requirement: str

    development_result: Any = None

    phases_completed: list[str] = field(
        default_factory=list
    )

    errors: list[str] = field(
        default_factory=list
    )

    elapsed_seconds: float = 0.0

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, Any]:
        development_result = (
            self.development_result
        )

        if hasattr(
            development_result,
            "to_dict",
        ):
            try:
                development_result = (
                    development_result.to_dict()
                )
            except Exception:
                development_result = str(
                    development_result
                )

        return {
            "success": self.success,
            "outcome": self.outcome,
            "status": self.status,
            "session_id": self.session_id,
            "requirement": self.requirement,
            "development_result": development_result,
            "phases_completed": list(
                self.phases_completed
            ),
            "errors": list(self.errors),
            "elapsed_seconds": (
                self.elapsed_seconds
            ),
            "metadata": dict(
                self.metadata
            ),
        }


class EndToEndAutonomousLoop:
    """
    Authoritative outer lifecycle for ARIA Phase 1.

    This class does not replace the existing development engine.

    It establishes the missing outer control plane:

        requirement
             ↓
        engineering session
             ↓
        lifecycle state
             ↓
        existing autonomous development engine
             ↓
        evidence/result
             ↓
        authoritative outcome
             ↓
        persistent session

    The existing DevelopmentController remains responsible for the
    actual implementation, validation, testing and bounded repair.

    This loop is intentionally conservative:

        - no direct filesystem writes;
        - no arbitrary shell execution;
        - no GitHub push;
        - no deployment;
        - no acceptance from an exception-free call alone;
        - no success when the underlying development result is failed;
        - session state is persisted whenever possible.
    """

    VERSION = (
        "PHASE1-END-TO-END-AUTONOMOUS-LOOP-20261004"
    )

    DEFAULT_TIMEOUT_SECONDS = 3600.0

    def __init__(
        self,
        development_runtime: Any,
        *,
        store: EngineeringStore | None = None,
        timeout_seconds: float = (
            DEFAULT_TIMEOUT_SECONDS
        ),
    ) -> None:

        if development_runtime is None:
            raise ValueError(
                "development_runtime is required."
            )

        self.development_runtime = (
            development_runtime
        )

        self.store = store

        self.timeout_seconds = max(
            30.0,
            min(
                7200.0,
                float(timeout_seconds),
            ),
        )

        self._active_sessions: dict[
            str,
            EngineeringSession,
        ] = {}

        self.statistics = {
            "requests": 0,
            "successful": 0,
            "failed": 0,
            "blocked": 0,
            "timeouts": 0,
        }

    # ============================================================
    # PUBLIC EXECUTION
    # ============================================================

    async def execute(
        self,
        requirement: str,
        *,
        session_id: str | None = None,
        changes: list[tuple[str, str]]
        | None = None,
        test_paths: list[str]
        | None = None,
        workspace_id: str | None = None,
        context: dict[str, Any]
        | None = None,
    ) -> AutonomousLoopResult:

        started = time.monotonic()

        normalized_requirement = (
            str(
                requirement or ""
            ).strip()
        )

        if not normalized_requirement:
            return self._failure(
                requirement="",
                session_id=(
                    session_id
                    or self._new_session_id()
                ),
                status="invalid_request",
                error=(
                    "Engineering requirement "
                    "is empty."
                ),
            )

        self.statistics["requests"] += 1

        sid = (
            str(session_id).strip()
            if session_id
            else self._new_session_id()
        )

        session = self._create_or_restore_session(
            sid,
            normalized_requirement,
        )

        self._active_sessions[sid] = session

        phases: list[str] = []
        errors: list[str] = []

        try:
            # ----------------------------------------------------
            # 1. UNDERSTANDING
            # ----------------------------------------------------

            self._phase(
                session,
                EngineeringPhase.UNDERSTANDING,
            )

            phases.append(
                EngineeringPhase.UNDERSTANDING.value
            )

            self._persist(session)

            # ----------------------------------------------------
            # 2. PLANNING
            # ----------------------------------------------------

            self._phase(
                session,
                EngineeringPhase.PLANNING,
            )

            phases.append(
                EngineeringPhase.PLANNING.value
            )

            self._persist(session)

            # ----------------------------------------------------
            # 3. GRAPH READY
            # ----------------------------------------------------

            self._phase(
                session,
                EngineeringPhase.GRAPH_READY,
            )

            phases.append(
                EngineeringPhase.GRAPH_READY.value
            )

            self._persist(session)

            # ----------------------------------------------------
            # 4. IMPLEMENTATION → VERIFICATION → REPAIR
            #
            # The existing development runtime owns these
            # operations. The outer loop observes its actual result.
            # ----------------------------------------------------

            self._phase(
                session,
                EngineeringPhase.IMPLEMENTING,
            )

            phases.append(
                EngineeringPhase.IMPLEMENTING.value
            )

            self._persist(session)

            development_result = await self._invoke_runtime(
                normalized_requirement,
                changes=changes,
                test_paths=test_paths,
                workspace_id=workspace_id,
                context=context,
            )

            # ----------------------------------------------------
            # 5. OBSERVE ACTUAL RESULT
            # ----------------------------------------------------

            success = self._result_success(
                development_result
            )

            status = self._result_status(
                development_result
            )

            result_errors = self._result_errors(
                development_result
            )

            errors.extend(
                result_errors
            )

            if success:
                # -----------------------------------------------
                # VERIFICATION
                # -----------------------------------------------

                self._phase(
                    session,
                    EngineeringPhase.VERIFYING,
                )

                phases.append(
                    EngineeringPhase.VERIFYING.value
                )

                self._persist(session)

                # -----------------------------------------------
                # TESTING
                # -----------------------------------------------

                self._phase(
                    session,
                    EngineeringPhase.TESTING,
                )

                phases.append(
                    EngineeringPhase.TESTING.value
                )

                self._persist(session)

                # -----------------------------------------------
                # REASSESSMENT
                # -----------------------------------------------

                self._phase(
                    session,
                    EngineeringPhase.REASSESSING,
                )

                phases.append(
                    EngineeringPhase.REASSESSING.value
                )

                self._persist(session)

                # -----------------------------------------------
                # ACCEPTANCE
                # -----------------------------------------------

                self._phase(
                    session,
                    EngineeringPhase.ACCEPTING,
                )

                phases.append(
                    EngineeringPhase.ACCEPTING.value
                )

                self._persist(session)

                # IMPORTANT:
                #
                # We accept only when the underlying development
                # runtime itself reports genuine success.
                #
                # Merely reaching this code path is not enough.
                #

                self._phase(
                    session,
                    EngineeringPhase.ACCEPTED,
                )

                phases.append(
                    EngineeringPhase.ACCEPTED.value
                )

                self._persist(session)

                self.statistics[
                    "successful"
                ] += 1

                elapsed = (
                    time.monotonic()
                    - started
                )

                return AutonomousLoopResult(
                    success=True,
                    outcome=(
                        EngineeringOutcome.ACCEPTED.value
                    ),
                    status="accepted",
                    session_id=sid,
                    requirement=(
                        normalized_requirement
                    ),
                    development_result=(
                        development_result
                    ),
                    phases_completed=phases,
                    errors=errors,
                    elapsed_seconds=elapsed,
                    metadata={
                        "version": self.VERSION,
                        "runtime_status": status,
                    },
                )

            # ----------------------------------------------------
            # FAILURE PATH
            # ----------------------------------------------------

            self._phase(
                session,
                EngineeringPhase.DIAGNOSING,
            )

            phases.append(
                EngineeringPhase.DIAGNOSING.value
            )

            self._persist(session)

            # The existing development runtime already owns its
            # bounded repair/retest mechanism. If it reports failure,
            # we preserve that evidence rather than pretending the
            # outer loop independently repaired anything.
            #
            # This prevents a false "autonomous recovery" claim.

            if self._result_has_recovery_evidence(
                development_result
            ):
                self._phase(
                    session,
                    EngineeringPhase.RECOVERING,
                )

                phases.append(
                    EngineeringPhase.RECOVERING.value
                )

                self._persist(session)

                self._phase(
                    session,
                    EngineeringPhase.RETESTING,
                )

                phases.append(
                    EngineeringPhase.RETESTING.value
                )

                self._persist(session)

            self._phase(
                session,
                EngineeringPhase.REASSESSING,
            )

            phases.append(
                EngineeringPhase.REASSESSING.value
            )

            self._persist(session)

            self.statistics[
                "failed"
            ] += 1

            elapsed = (
                time.monotonic()
                - started
            )

            return AutonomousLoopResult(
                success=False,
                outcome=(
                    EngineeringOutcome.FAILED.value
                ),
                status=(
                    status
                    or "development_failed"
                ),
                session_id=sid,
                requirement=(
                    normalized_requirement
                ),
                development_result=(
                    development_result
                ),
                phases_completed=phases,
                errors=errors
                or [
                    "Autonomous development "
                    "did not satisfy the requirement."
                ],
                elapsed_seconds=elapsed,
                metadata={
                    "version": self.VERSION,
                    "runtime_status": status,
                },
            )

        except TimeoutError as exc:

            self.statistics[
                "timeouts"
            ] += 1

            self._safe_fail_session(
                session,
                str(exc),
            )

            elapsed = (
                time.monotonic()
                - started
            )

            return AutonomousLoopResult(
                success=False,
                outcome=(
                    EngineeringOutcome.BLOCKED.value
                ),
                status="timeout",
                session_id=sid,
                requirement=(
                    normalized_requirement
                ),
                phases_completed=phases,
                errors=[
                    str(exc)
                ],
                elapsed_seconds=elapsed,
                metadata={
                    "version": self.VERSION,
                },
            )

        except Exception as exc:

            logger.exception(
                "[EndToEndAutonomousLoop] "
                "Engineering lifecycle failed"
            )

            self.statistics[
                "failed"
            ] += 1

            self._safe_fail_session(
                session,
                str(exc),
            )

            elapsed = (
                time.monotonic()
                - started
            )

            return AutonomousLoopResult(
                success=False,
                outcome=(
                    EngineeringOutcome.FAILED.value
                ),
                status="lifecycle_failed",
                session_id=sid,
                requirement=(
                    normalized_requirement
                ),
                phases_completed=phases,
                errors=[
                    f"{type(exc).__name__}: {exc}"
                ],
                elapsed_seconds=elapsed,
                metadata={
                    "version": self.VERSION,
                },
            )

        finally:
            self._active_sessions.pop(
                sid,
                None,
            )

    # ============================================================
    # RUNTIME INVOCATION
    # ============================================================

    async def _invoke_runtime(
        self,
        requirement: str,
        *,
        changes: list[tuple[str, str]]
        | None,
        test_paths: list[str]
        | None,
        workspace_id: str | None,
        context: dict[str, Any]
        | None,
    ) -> Any:

        method = getattr(
            self.development_runtime,
            "develop",
            None,
        )

        if not callable(method):
            method = getattr(
                self.development_runtime,
                "execute",
                None,
            )

        if not callable(method):
            raise RuntimeError(
                "Connected development runtime "
                "does not expose develop() or execute()."
            )

        kwargs = {
            "changes": changes,
            "test_paths": test_paths,
            "workspace_id": workspace_id,
            "context": context,
        }

        filtered = self._supported_kwargs(
            method,
            kwargs,
        )

        result = method(
            requirement,
            **filtered,
        )

        if inspect.isawaitable(result):
            result = await result

        return result

    @staticmethod
    def _supported_kwargs(
        method: Callable[..., Any],
        kwargs: dict[str, Any],
    ) -> dict[str, Any]:

        try:
            signature = inspect.signature(
                method
            )
        except (TypeError, ValueError):
            return {}

        parameters = signature.parameters

        if any(
            parameter.kind
            == inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        ):
            return kwargs

        return {
            key: value
            for key, value in kwargs.items()
            if key in parameters
            and value is not None
        }

    # ============================================================
    # SESSION
    # ============================================================

    def _create_or_restore_session(
        self,
        session_id: str,
        requirement: str,
    ) -> EngineeringSession:

        existing = self._load_session(
            session_id
        )

        if existing is not None:
            return existing

        session = self._new_session(
            session_id,
            requirement,
        )

        return session

    def _new_session(
        self,
        session_id: str,
        requirement: str,
    ) -> EngineeringSession:

        factory = getattr(
            EngineeringSession,
            "create",
            None,
        )

        if callable(factory):
            attempts = (
                {
                    "session_id": session_id,
                    "requirement": requirement,
                },
                {
                    "requirement": requirement,
                    "session_id": session_id,
                },
                {
                    "session_id": session_id,
                    "raw_request": requirement,
                },
            )

            for kwargs in attempts:
                try:
                    return factory(
                        **kwargs
                    )
                except TypeError:
                    continue

        # Fall back to the actual constructor while respecting
        # whichever contract shape is installed.
        try:
            signature = inspect.signature(
                EngineeringSession
            )
        except (TypeError, ValueError):
            signature = None

        if signature is not None:
            values: dict[str, Any] = {}

            if (
                "session_id"
                in signature.parameters
            ):
                values["session_id"] = (
                    session_id
                )

            if (
                "requirement"
                in signature.parameters
            ):
                values["requirement"] = (
                    requirement
                )

            if (
                "raw_request"
                in signature.parameters
            ):
                values["raw_request"] = (
                    requirement
                )

            try:
                return EngineeringSession(
                    **values
                )
            except Exception:
                pass

        raise RuntimeError(
            "Unable to construct the authoritative "
            "EngineeringSession contract."
        )

    def _load_session(
        self,
        session_id: str,
    ) -> EngineeringSession | None:

        if self.store is None:
            return None

        loader = getattr(
            self.store,
            "load",
            None,
        )

        if not callable(loader):
            return None

        try:
            value = loader(
                session_id
            )

            if inspect.isawaitable(value):
                return None

            if isinstance(
                value,
                EngineeringSession,
            ):
                return value

        except Exception:
            logger.warning(
                "[EndToEndAutonomousLoop] "
                "Unable to restore session %s",
                session_id,
                exc_info=True,
            )

        return None

    def _persist(
        self,
        session: EngineeringSession,
    ) -> None:

        if self.store is None:
            return

        saver = getattr(
            self.store,
            "save",
            None,
        )

        if not callable(saver):
            return

        try:
            result = saver(
                session
            )

            if inspect.isawaitable(result):
                logger.warning(
                    "[EndToEndAutonomousLoop] "
                    "Async store.save() is not awaited."
                )

        except Exception:
            logger.warning(
                "[EndToEndAutonomousLoop] "
                "Session persistence failed.",
                exc_info=True,
            )

    # ============================================================
    # LIFECYCLE STATE
    # ============================================================

    @staticmethod
    def _phase(
        session: EngineeringSession,
        phase: EngineeringPhase,
    ) -> None:

        transition = getattr(
            session,
            "transition",
            None,
        )

        if callable(transition):
            try:
                transition(
                    phase
                )
                return
            except TypeError:
                try:
                    transition(
                        target=phase
                    )
                    return
                except Exception:
                    pass
            except Exception:
                # Do not silently convert a real lifecycle conflict
                # into success.
                raise

        setter = getattr(
            session,
            "set_phase",
            None,
        )

        if callable(setter):
            setter(
                phase
            )
            return

        # If the contract has no mutation API, do not fake state.
        raise RuntimeError(
            "EngineeringSession does not expose "
            "a lifecycle transition API."
        )

    def _safe_fail_session(
        self,
        session: EngineeringSession,
        reason: str,
    ) -> None:

        for method_name in (
            "fail",
            "block",
        ):
            method = getattr(
                session,
                method_name,
                None,
            )

            if not callable(method):
                continue

            try:
                method(
                    reason
                )
                self._persist(
                    session
                )
                return
            except TypeError:
                try:
                    method(
                        error=reason
                    )
                    self._persist(
                        session
                    )
                    return
                except Exception:
                    continue
            except Exception:
                continue

    # ============================================================
    # RESULT INTERPRETATION
    # ============================================================

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
            return bool(
                result.get(
                    "success",
                    False,
                )
            )

        return False

    @staticmethod
    def _result_status(
        result: Any,
    ) -> str:

        if result is None:
            return "no_result"

        value = getattr(
            result,
            "status",
            None,
        )

        if value is not None:
            return str(
                value
            )

        if isinstance(
            result,
            dict,
        ):
            return str(
                result.get(
                    "status",
                    "",
                )
                or ""
            )

        return ""

    @staticmethod
    def _result_errors(
        result: Any,
    ) -> list[str]:

        if result is None:
            return [
                "Development runtime returned no result."
            ]

        value = getattr(
            result,
            "errors",
            None,
        )

        if value is None and isinstance(
            result,
            dict,
        ):
            value = result.get(
                "errors",
                [],
            )

        if isinstance(
            value,
            str,
        ):
            return [
                value
            ] if value.strip() else []

        if value is None:
            return []

        try:
            return [
                str(item)
                for item in value
                if str(item).strip()
            ]
        except TypeError:
            return [
                str(value)
            ]

    @staticmethod
    def _result_has_recovery_evidence(
        result: Any,
    ) -> bool:

        if result is None:
            return False

        metadata = getattr(
            result,
            "metadata",
            None,
        )

        if metadata is None and isinstance(
            result,
            dict,
        ):
            metadata = result.get(
                "metadata"
            )

        if not isinstance(
            metadata,
            dict,
        ):
            return False

        recovery_keys = (
            "repair_attempts",
            "recovery",
            "recovered",
            "retest",
        )

        return any(
            key in metadata
            for key in recovery_keys
        )

    # ============================================================
    # HELPERS
    # ============================================================

    @staticmethod
    def _new_session_id() -> str:
        return (
            "eng-"
            + uuid.uuid4().hex[:16]
        )

    def _failure(
        self,
        *,
        requirement: str,
        session_id: str,
        status: str,
        error: str,
    ) -> AutonomousLoopResult:

        self.statistics[
            "failed"
        ] += 1

        return AutonomousLoopResult(
            success=False,
            outcome=(
                EngineeringOutcome.FAILED.value
            ),
            status=status,
            session_id=session_id,
            requirement=requirement,
            errors=[
                error
            ],
            metadata={
                "version": self.VERSION,
            },
        )

    # ============================================================
    # STATUS / HEALTH
    # ============================================================

    def status(self) -> dict[str, Any]:
        return {
            "version": self.VERSION,
            "active_sessions": list(
                self._active_sessions.keys()
            ),
            "active_count": len(
                self._active_sessions
            ),
            "timeout_seconds": (
                self.timeout_seconds
            ),
            "statistics": dict(
                self.statistics
            ),
        }

    def health(self) -> dict[str, Any]:
        runtime_available = (
            self.development_runtime
            is not None
            and (
                callable(
                    getattr(
                        self.development_runtime,
                        "develop",
                        None,
                    )
                )
                or callable(
                    getattr(
                        self.development_runtime,
                        "execute",
                        None,
                    )
                )
            )
        )

        return {
            "healthy": runtime_available,
            "version": self.VERSION,
            "runtime_available": (
                runtime_available
            ),
            "store_available": (
                self.store is not None
            ),
            "active_count": len(
                self._active_sessions
            ),
        }


__all__ = [
    "AutonomousLoopResult",
    "EndToEndAutonomousLoop",
]