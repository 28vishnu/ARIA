from __future__ import annotations

import inspect
import logging
import uuid
from dataclasses import asdict, is_dataclass
from typing import Any

from .contracts.engineering_lifecycle import (
    EngineeringLifecycle,
)
from .contracts.engineering_session import (
    EngineeringSession,
)
from .contracts.engineering_state import (
    EngineeringPhase,
)

logger = logging.getLogger(
    "aria.authoritative_engineering_lifecycle_runtime"
)


class AuthoritativeEngineeringLifecycleRuntime:
    """
    Authoritative lifecycle boundary for autonomous engineering.

    This class does NOT replace the existing development engine.

    Existing execution remains responsible for:
        repository inspection
        planning
        workspace creation
        code generation
        guarded writes
        validation
        testing
        repair

    This runtime owns the higher-level engineering state:

        requirement
             ↓
        session creation
             ↓
        understanding
             ↓
        planning
             ↓
        graph ready
             ↓
        implementation
             ↓
        verification
             ↓
        testing
             ↓
        diagnosis / recovery
             ↓
        reassessment
             ↓
        acceptance
             ↓
        accepted / failed / blocked
    """

    VERSION = (
        "AUTHORITATIVE-ENGINEERING-LIFECYCLE-V1"
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

        self.persistence = persistence

        self._sessions: dict[
            str,
            EngineeringSession,
        ] = {}

        self._lifecycles: dict[
            str,
            EngineeringLifecycle,
        ] = {}

    # ============================================================
    # SESSION CREATION
    # ============================================================

    @staticmethod
    def _new_session_id() -> str:
        return (
            "eng-"
            + uuid.uuid4().hex
        )

    def _construct_session(
        self,
        session_id: str,
        requirement: str,
    ) -> EngineeringSession:
        """
        Construct EngineeringSession without assuming one exact
        constructor signature.

        This keeps the lifecycle integration compatible with the
        authoritative session contract as it evolves.
        """

        session_class = EngineeringSession

        # --------------------------------------------------------
        # Preferred factory methods
        # --------------------------------------------------------

        for factory_name in (
            "create",
            "new",
            "from_requirement",
        ):

            factory = getattr(
                session_class,
                factory_name,
                None,
            )

            if not callable(factory):
                continue

            attempts = (
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

            for kwargs in attempts:

                try:

                    session = factory(
                        **kwargs
                    )

                    if session is not None:
                        return session

                except TypeError:
                    continue

        # --------------------------------------------------------
        # Constructor compatibility
        # --------------------------------------------------------

        constructor = session_class

        try:
            signature = inspect.signature(
                constructor
            )

        except Exception as exc:

            raise RuntimeError(
                "Unable to inspect EngineeringSession "
                "constructor."
            ) from exc

        parameters = signature.parameters

        kwargs: dict[str, Any] = {}

        if "session_id" in parameters:
            kwargs["session_id"] = session_id

        if "requirement" in parameters:
            kwargs["requirement"] = requirement

        elif "raw_request" in parameters:
            kwargs["raw_request"] = requirement

        elif "request" in parameters:
            kwargs["request"] = requirement

        elif "objective" in parameters:
            kwargs["objective"] = requirement

        try:

            return constructor(
                **kwargs
            )

        except Exception as exc:

            raise RuntimeError(
                "Unable to construct authoritative "
                "EngineeringSession."
            ) from exc

    # ============================================================
    # LIFECYCLE CREATION
    # ============================================================

    def _construct_lifecycle(
        self,
        session: EngineeringSession,
    ) -> EngineeringLifecycle:

        lifecycle_class = EngineeringLifecycle

        attempts = (
            {
                "session": session,
            },
            {
                "engineering_session": session,
            },
            {},
        )

        for kwargs in attempts:

            try:

                lifecycle = lifecycle_class(
                    **kwargs
                )

                return lifecycle

            except TypeError:
                continue

        raise RuntimeError(
            "Unable to construct EngineeringLifecycle."
        )

    # ============================================================
    # PHASE HELPERS
    # ============================================================

    @staticmethod
    def _phase_name(
        phase: Any,
    ) -> str:

        value = getattr(
            phase,
            "value",
            phase,
        )

        return str(
            value
        ).lower()

    def _transition(
        self,
        session: EngineeringSession,
        lifecycle: EngineeringLifecycle,
        phase: Any,
    ) -> bool:
        """
        Advance the authoritative lifecycle.

        Multiple compatibility APIs are supported because the
        lifecycle contract may expose transition methods under
        different names.
        """

        methods = (
            "transition",
            "advance",
            "move_to",
            "set_phase",
        )

        for method_name in methods:

            method = getattr(
                lifecycle,
                method_name,
                None,
            )

            if not callable(method):
                continue

            attempts = (
                (phase,),
                (
                    getattr(
                        phase,
                        "value",
                        phase,
                    ),
                ),
            )

            for args in attempts:

                try:

                    result = method(
                        *args
                    )

                    if inspect.isawaitable(
                        result
                    ):
                        # Lifecycle transitions are intentionally
                        # synchronous state operations.
                        logger.warning(
                            "[EngineeringLifecycle] "
                            "Async transition method ignored."
                        )
                        continue

                    return True

                except (
                    TypeError,
                    ValueError,
                ):

                    continue

                except Exception:

                    logger.exception(
                        "[EngineeringLifecycle] "
                        "Transition failed | phase=%s",
                        self._phase_name(
                            phase
                        ),
                    )

                    return False

        # --------------------------------------------------------
        # Session-owned transition fallback
        # --------------------------------------------------------

        for method_name in (
            "transition",
            "advance",
            "set_phase",
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
                    phase
                )

                return True

            except (
                TypeError,
                ValueError,
            ):

                continue

            except Exception:

                logger.exception(
                    "[EngineeringLifecycle] "
                    "Session transition failed."
                )

                return False

        return False

    # ============================================================
    # SESSION REGISTRATION
    # ============================================================

    def create_session(
        self,
        requirement: str,
        *,
        session_id: str | None = None,
    ) -> EngineeringSession:

        normalized = str(
            requirement or ""
        ).strip()

        if not normalized:
            raise ValueError(
                "Engineering requirement cannot be empty."
            )

        resolved_id = (
            str(session_id).strip()
            if session_id
            else self._new_session_id()
        )

        session = self._construct_session(
            resolved_id,
            normalized,
        )

        lifecycle = self._construct_lifecycle(
            session
        )

        self._sessions[
            resolved_id
        ] = session

        self._lifecycles[
            resolved_id
        ] = lifecycle

        # Initial authoritative state.
        self._transition(
            session,
            lifecycle,
            EngineeringPhase.CREATED,
        )

        self._persist(
            session
        )

        logger.info(
            "[EngineeringLifecycle] "
            "Session created | session_id=%s",
            resolved_id,
        )

        return session

    # ============================================================
    # RESUME
    # ============================================================

    def register_existing_session(
        self,
        session: EngineeringSession,
    ) -> EngineeringLifecycle:

        session_id = self._session_id(
            session
        )

        if not session_id:
            raise ValueError(
                "EngineeringSession does not expose "
                "a session identifier."
            )

        lifecycle = self._construct_lifecycle(
            session
        )

        self._sessions[
            session_id
        ] = session

        self._lifecycles[
            session_id
        ] = lifecycle

        return lifecycle

    def get_session(
        self,
        session_id: str,
    ) -> EngineeringSession | None:

        return self._sessions.get(
            str(session_id)
        )

    def get_lifecycle(
        self,
        session_id: str,
    ) -> EngineeringLifecycle | None:

        return self._lifecycles.get(
            str(session_id)
        )

    # ============================================================
    # LIFECYCLE EXECUTION STATE
    # ============================================================

    def mark_understanding(
        self,
        session_id: str,
    ) -> bool:

        return self._move(
            session_id,
            EngineeringPhase.UNDERSTANDING,
        )

    def mark_planning(
        self,
        session_id: str,
    ) -> bool:

        return self._move(
            session_id,
            EngineeringPhase.PLANNING,
        )

    def mark_graph_ready(
        self,
        session_id: str,
    ) -> bool:

        return self._move(
            session_id,
            EngineeringPhase.GRAPH_READY,
        )

    def mark_implementing(
        self,
        session_id: str,
    ) -> bool:

        return self._move(
            session_id,
            EngineeringPhase.IMPLEMENTING,
        )

    def mark_verifying(
        self,
        session_id: str,
    ) -> bool:

        return self._move(
            session_id,
            EngineeringPhase.VERIFYING,
        )

    def mark_testing(
        self,
        session_id: str,
    ) -> bool:

        return self._move(
            session_id,
            EngineeringPhase.TESTING,
        )

    def mark_diagnosing(
        self,
        session_id: str,
    ) -> bool:

        return self._move(
            session_id,
            EngineeringPhase.DIAGNOSING,
        )

    def mark_recovering(
        self,
        session_id: str,
    ) -> bool:

        return self._move(
            session_id,
            EngineeringPhase.RECOVERING,
        )

    def mark_retesting(
        self,
        session_id: str,
    ) -> bool:

        return self._move(
            session_id,
            EngineeringPhase.RETESTING,
        )

    def mark_reassessing(
        self,
        session_id: str,
    ) -> bool:

        return self._move(
            session_id,
            EngineeringPhase.REASSESSING,
        )

    def mark_accepting(
        self,
        session_id: str,
    ) -> bool:

        return self._move(
            session_id,
            EngineeringPhase.ACCEPTING,
        )

    def mark_accepted(
        self,
        session_id: str,
    ) -> bool:

        return self._move(
            session_id,
            EngineeringPhase.ACCEPTED,
        )

    def mark_blocked(
        self,
        session_id: str,
    ) -> bool:

        return self._move(
            session_id,
            EngineeringPhase.BLOCKED,
        )

    def mark_failed(
        self,
        session_id: str,
    ) -> bool:

        return self._move(
            session_id,
            EngineeringPhase.FAILED,
        )

    # ============================================================
    # INTERNAL TRANSITION
    # ============================================================

    def _move(
        self,
        session_id: str,
        phase: Any,
    ) -> bool:

        session = self.get_session(
            session_id
        )

        lifecycle = self.get_lifecycle(
            session_id
        )

        if session is None or lifecycle is None:
            return False

        success = self._transition(
            session,
            lifecycle,
            phase,
        )

        if success:
            self._persist(
                session
            )

        return success

    # ============================================================
    # SESSION ID
    # ============================================================

    @staticmethod
    def _session_id(
        session: Any,
    ) -> str | None:

        for name in (
            "session_id",
            "id",
        ):

            value = getattr(
                session,
                name,
                None,
            )

            if value:
                return str(
                    value
                )

        return None

    # ============================================================
    # PERSISTENCE
    # ============================================================

    def _persist(
        self,
        session: EngineeringSession,
    ) -> None:

        if self.persistence is None:
            return

        session_id = self._session_id(
            session
        )

        if not session_id:
            return

        # --------------------------------------------------------
        # checkpoint()
        # --------------------------------------------------------

        checkpoint = getattr(
            self.persistence,
            "checkpoint",
            None,
        )

        if callable(checkpoint):

            try:

                result = checkpoint(
                    session
                )

                if inspect.isawaitable(
                    result
                ):
                    logger.warning(
                        "[EngineeringLifecycle] "
                        "Async persistence checkpoint "
                        "requires runtime integration."
                    )

                return

            except TypeError:
                pass

            except Exception:

                logger.exception(
                    "[EngineeringLifecycle] "
                    "Checkpoint failed."
                )

        # --------------------------------------------------------
        # save()
        # --------------------------------------------------------

        save = getattr(
            self.persistence,
            "save",
            None,
        )

        if callable(save):

            try:

                snapshot = self._snapshot(
                    session
                )

                result = save(
                    session_id,
                    snapshot,
                )

                if inspect.isawaitable(
                    result
                ):
                    logger.warning(
                        "[EngineeringLifecycle] "
                        "Async save was not awaited."
                    )

            except TypeError:

                try:

                    result = save(
                        session
                    )

                    if inspect.isawaitable(
                        result
                    ):
                        logger.warning(
                            "[EngineeringLifecycle] "
                            "Async save was not awaited."
                        )

                except Exception:

                    logger.exception(
                        "[EngineeringLifecycle] "
                        "Session save failed."
                    )

            except Exception:

                logger.exception(
                    "[EngineeringLifecycle] "
                    "Session persistence failed."
                )

    # ============================================================
    # SNAPSHOT
    # ============================================================

    @staticmethod
    def _snapshot(
        session: Any,
    ) -> dict[str, Any]:

        for method_name in (
            "snapshot",
            "to_snapshot",
            "to_dict",
        ):

            method = getattr(
                session,
                method_name,
                None,
            )

            if not callable(method):
                continue

            try:

                value = method()

                if isinstance(
                    value,
                    dict,
                ):
                    return dict(
                        value
                    )

            except Exception:

                continue

        if is_dataclass(
            session
        ):
            try:
                return asdict(
                    session
                )
            except Exception:
                pass

        result: dict[str, Any] = {}

        for name in (
            "session_id",
            "state",
            "phase",
            "requirement",
            "objective",
            "metadata",
        ):

            if hasattr(
                session,
                name,
            ):

                try:

                    value = getattr(
                        session,
                        name,
                    )

                    if hasattr(
                        value,
                        "value",
                    ):
                        value = value.value

                    result[name] = value

                except Exception:
                    continue

        return result

    # ============================================================
    # STATUS
    # ============================================================

    def status(
        self,
        session_id: str | None = None,
    ) -> dict[str, Any]:

        if session_id is not None:

            session = self.get_session(
                session_id
            )

            lifecycle = self.get_lifecycle(
                session_id
            )

            if session is None:
                return {
                    "healthy": False,
                    "found": False,
                    "session_id": str(
                        session_id
                    ),
                }

            return {
                "healthy": True,
                "found": True,
                "session_id": str(
                    session_id
                ),
                "session": self._snapshot(
                    session
                ),
                "lifecycle": self._lifecycle_snapshot(
                    lifecycle
                ),
            }

        return {
            "healthy": True,
            "version": self.VERSION,
            "active_sessions": len(
                self._sessions
            ),
            "sessions": [
                self._session_id(
                    session
                )
                for session in self._sessions.values()
            ],
        }

    def _lifecycle_snapshot(
        self,
        lifecycle: Any,
    ) -> dict[str, Any]:

        if lifecycle is None:
            return {}

        for method_name in (
            "snapshot",
            "to_dict",
        ):

            method = getattr(
                lifecycle,
                method_name,
                None,
            )

            if not callable(method):
                continue

            try:

                value = method()

                if isinstance(
                    value,
                    dict,
                ):
                    return dict(
                        value
                    )

            except Exception:
                continue

        result: dict[str, Any] = {}

        for name in (
            "phase",
            "current_phase",
            "state",
            "status",
        ):

            if hasattr(
                lifecycle,
                name,
            ):

                try:

                    value = getattr(
                        lifecycle,
                        name,
                    )

                    if hasattr(
                        value,
                        "value",
                    ):
                        value = value.value

                    result[name] = value

                except Exception:
                    continue

        return result

    # ============================================================
    # HEALTH
    # ============================================================

    def health(
        self,
    ) -> dict[str, Any]:

        runtime_available = (
            self.development_runtime
            is not None
        )

        lifecycle_available = (
            EngineeringLifecycle
            is not None
        )

        session_available = (
            EngineeringSession
            is not None
        )

        healthy = (
            runtime_available
            and lifecycle_available
            and session_available
        )

        return {
            "healthy": healthy,
            "version": self.VERSION,
            "development_runtime": runtime_available,
            "engineering_session": session_available,
            "engineering_lifecycle": lifecycle_available,
            "active_sessions": len(
                self._sessions
            ),
        }


__all__ = [
    "AuthoritativeEngineeringLifecycleRuntime",
]