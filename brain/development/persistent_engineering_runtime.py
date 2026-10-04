from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .authoritative_engineering_lifecycle_runtime import (
    AuthoritativeEngineeringLifecycleRuntime,
)
from .engineering_evidence import EngineeringEvidenceRecorder


logger = logging.getLogger("aria")


@dataclass(frozen=True)
class PersistentEngineeringResult:
    """
    Stable result returned by the persistent engineering runtime.

    `success` describes execution success.

    `accepted` describes genuine requirement acceptance.

    They are intentionally separate.
    """

    success: bool
    accepted: bool = False
    session_id: str | None = None
    status: str = "unknown"
    result: Any = None
    error: str | None = None
    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "accepted": self.accepted,
            "session_id": self.session_id,
            "status": self.status,
            "result": self._serialize(self.result),
            "error": self.error,
            "metadata": dict(self.metadata),
        }

    @staticmethod
    def _serialize(value: Any) -> Any:
        if value is None:
            return None

        if isinstance(value, dict):
            return {
                str(key): PersistentEngineeringResult._serialize(
                    item
                )
                for key, item in value.items()
            }

        if isinstance(value, (list, tuple)):
            return [
                PersistentEngineeringResult._serialize(
                    item
                )
                for item in value
            ]

        to_dict = getattr(
            value,
            "to_dict",
            None,
        )

        if callable(to_dict):
            try:
                return to_dict()
            except Exception:
                pass

        return value


class PersistentEngineeringRuntime:
    """
    Persistent authoritative engineering runtime.

    Architecture:

        Telegram / external command
                    ↓
        PersistentEngineeringRuntime
                    ↓
        AuthoritativeEngineeringLifecycleRuntime
                    ↓
        EvidenceAwareEngineeringLifecycle
                    ↓
        EngineeringEvidenceRecorder
                    ↓
        Existing development runtime
                    ↓
        persistent session checkpoint

    The wrapped development runtime remains responsible for the
    actual implementation machinery.

    This class owns:
        - engineering session identity
        - authoritative lifecycle
        - evidence recording
        - persistence
        - resume
        - status
        - acceptance boundary

    It does NOT:
        - push GitHub
        - deploy
        - bypass authorization
        - execute arbitrary shell commands
    """

    def __init__(
        self,
        runtime: Any | None = None,
        *,
        legacy_runtime: Any | None = None,
        persistence: Any | None = None,
        engineering_persistence: Any | None = None,
        lifecycle_runtime: Any | None = None,
        development_runtime: Any | None = None,
        **kwargs: Any,
    ) -> None:
        self.runtime = (
            runtime
            or legacy_runtime
            or development_runtime
        )

        if self.runtime is None:
            raise ValueError(
                "PersistentEngineeringRuntime requires "
                "an underlying development runtime."
            )

        self.persistence = (
            persistence
            or engineering_persistence
        )

        self._lifecycle_runtime = (
            lifecycle_runtime
        )

        self._sessions: dict[
            str,
            AuthoritativeEngineeringLifecycleRuntime,
        ] = {}

        self._active_session_id: str | None = None

        self.metadata = dict(kwargs)

    # ============================================================
    # Lifecycle runtime creation
    # ============================================================

    def _create_lifecycle_runtime(
        self,
        *,
        session_id: str | None = None,
        requirement: Any | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AuthoritativeEngineeringLifecycleRuntime:
        lifecycle = (
            AuthoritativeEngineeringLifecycleRuntime(
                persistence=self.persistence,
                session_id=session_id,
                requirement=requirement,
                metadata=metadata,
            )
        )

        self._sessions[
            lifecycle.session_id
        ] = lifecycle

        self._active_session_id = (
            lifecycle.session_id
        )

        return lifecycle

    def _get_lifecycle(
        self,
        session_id: str | None = None,
    ) -> AuthoritativeEngineeringLifecycleRuntime | None:
        target = (
            session_id
            or self._active_session_id
        )

        if target is None:
            return None

        return self._sessions.get(target)

    # ============================================================
    # Underlying runtime invocation
    # ============================================================

    async def _invoke_runtime(
        self,
        requirement: str,
        *,
        changes: list[tuple[str, str]] | None = None,
        test_paths: list[str] | None = None,
        workspace_id: str | None = None,
        session_id: str | None = None,
        **kwargs: Any,
    ) -> Any:
        runtime = self.runtime

        develop = getattr(
            runtime,
            "develop",
            None,
        )

        execute = getattr(
            runtime,
            "execute",
            None,
        )

        target = (
            develop
            if callable(develop)
            else execute
        )

        if target is None:
            raise RuntimeError(
                "Underlying engineering runtime exposes "
                "neither develop() nor execute()."
            )

        call_kwargs = dict(kwargs)

        if changes is not None:
            call_kwargs["changes"] = changes

        if test_paths is not None:
            call_kwargs["test_paths"] = test_paths

        if workspace_id is not None:
            call_kwargs["workspace_id"] = workspace_id

        if session_id is not None:
            call_kwargs["session_id"] = session_id

        # First try the complete modern signature.
        try:
            result = target(
                requirement,
                **call_kwargs,
            )
        except TypeError:
            # Compatibility fallback for older runtimes.
            result = target(
                requirement
            )

        if inspect.isawaitable(result):
            result = await result

        return result

    # ============================================================
    # Result interpretation
    # ============================================================

    @staticmethod
    def _execution_success(
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

        if isinstance(result, dict):
            if "success" in result:
                return bool(
                    result["success"]
                )

        return False

    @staticmethod
    def _explicit_acceptance(
        result: Any,
    ) -> bool:
        """
        Acceptance must be explicitly reported.

        A generic `success=True` is NEVER treated as acceptance.
        """

        value = getattr(
            result,
            "accepted",
            None,
        )

        if value is not None:
            return bool(value)

        value = getattr(
            result,
            "is_accepted",
            None,
        )

        if value is not None:
            return bool(value)

        if isinstance(result, dict):
            if "accepted" in result:
                return bool(
                    result["accepted"]
                )

            if "is_accepted" in result:
                return bool(
                    result["is_accepted"]
                )

        return False

    @staticmethod
    def _result_status(
        result: Any,
    ) -> str:
        value = getattr(
            result,
            "status",
            None,
        )

        if value:
            return str(value)

        if isinstance(result, dict):
            value = result.get("status")

            if value:
                return str(value)

        if PersistentEngineeringRuntime._execution_success(
            result
        ):
            return "completed"

        return "failed"

    @staticmethod
    def _result_error(
        result: Any,
    ) -> str | None:
        value = getattr(
            result,
            "error",
            None,
        )

        if value:
            return str(value)

        if isinstance(result, dict):
            value = result.get("error")

            if value:
                return str(value)

        return None

    # ============================================================
    # Evidence
    # ============================================================

    @staticmethod
    def _record_runtime_evidence(
        lifecycle: AuthoritativeEngineeringLifecycleRuntime,
        *,
        kind: str,
        summary: str,
        details: Any = None,
    ) -> None:
        try:
            recorder = lifecycle.evidence

            recorder.record(
                kind=kind,
                summary=summary,
                details=details,
                source="persistent_engineering_runtime",
            )

        except Exception:
            logger.exception(
                "[PersistentEngineeringRuntime] "
                "Could not record runtime evidence."
            )

    # ============================================================
    # Development
    # ============================================================

    async def develop(
        self,
        requirement: str,
        *,
        changes: list[tuple[str, str]] | None = None,
        test_paths: list[str] | None = None,
        workspace_id: str | None = None,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> PersistentEngineeringResult:
        started_at = datetime.now(
            timezone.utc
        ).isoformat()

        lifecycle = self._create_lifecycle_runtime(
            session_id=session_id,
            requirement=requirement,
            metadata={
                **(metadata or {}),
                "started_at": started_at,
                "runtime": (
                    "persistent_engineering_runtime"
                ),
            },
        )

        try:
            lifecycle.mark_created(
                reason=(
                    "Persistent engineering session "
                    "created."
                )
            )

            lifecycle.mark_understanding(
                reason=(
                    "Engineering session entered "
                    "authoritative understanding phase."
                )
            )

            self._record_runtime_evidence(
                lifecycle,
                kind="requirement",
                summary=(
                    "Persistent runtime received "
                    "the engineering requirement."
                ),
                details={
                    "requirement": requirement,
                },
            )

            lifecycle.mark_planning(
                reason=(
                    "Engineering planning phase started."
                )
            )

            lifecycle.mark_graph_ready(
                reason=(
                    "Authoritative runtime is ready "
                    "to invoke the development engine."
                )
            )

            lifecycle.mark_implementing(
                reason=(
                    "Underlying development engine "
                    "started."
                )
            )

            result = await self._invoke_runtime(
                requirement,
                changes=changes,
                test_paths=test_paths,
                workspace_id=workspace_id,
                session_id=lifecycle.session_id,
                **kwargs,
            )

            execution_success = (
                self._execution_success(result)
            )

            explicit_acceptance = (
                self._explicit_acceptance(result)
            )

            status = self._result_status(
                result
            )

            error = self._result_error(
                result
            )

            self._record_runtime_evidence(
                lifecycle,
                kind=(
                    "execution"
                    if execution_success
                    else "failure"
                ),
                summary=(
                    "Underlying engineering runtime "
                    "completed successfully."
                    if execution_success
                    else
                    "Underlying engineering runtime "
                    "reported failure."
                ),
                details=(
                    result.to_dict()
                    if hasattr(
                        result,
                        "to_dict",
                    )
                    else result
                ),
            )

            if not execution_success:
                lifecycle.mark_failed(
                    reason=(
                        error
                        or
                        "Underlying engineering runtime "
                        "failed."
                    )
                )

                return PersistentEngineeringResult(
                    success=False,
                    accepted=False,
                    session_id=lifecycle.session_id,
                    status="failed",
                    result=result,
                    error=(
                        error
                        or "Engineering execution failed."
                    ),
                    metadata={
                        "acceptance_boundary": (
                            "not_satisfied"
                        ),
                    },
                )

            lifecycle.mark_verifying(
                reason=(
                    "Execution completed; "
                    "verification evidence is required."
                )
            )

            lifecycle.mark_testing(
                reason=(
                    "Execution completed; test/verification "
                    "evidence is being finalized."
                )
            )

            lifecycle.mark_reassessing(
                reason=(
                    "Engineering result is being "
                    "reassessed before acceptance."
                )
            )

            if explicit_acceptance:
                lifecycle.mark_accepting(
                    reason=(
                        "Underlying result explicitly "
                        "reported acceptance."
                    )
                )

                lifecycle.mark_accepted(
                    reason=(
                        "Requirement explicitly accepted "
                        "by the engineering result."
                    ),
                    evidence={
                        "source": (
                            "underlying_engineering_result"
                        ),
                        "result_status": status,
                        "accepted": True,
                    },
                )

            else:
                """
                Deliberately do NOT call mark_accepted().

                A successful implementation can still lack
                sufficient acceptance evidence.

                Keep the session at the authoritative
                reassessment boundary until the acceptance
                engine supplies explicit evidence.
                """

                self._record_runtime_evidence(
                    lifecycle,
                    kind="acceptance",
                    summary=(
                        "Execution succeeded but explicit "
                        "acceptance evidence was not supplied."
                    ),
                    details={
                        "accepted": False,
                        "execution_success": True,
                        "status": status,
                    },
                )

            return PersistentEngineeringResult(
                success=True,
                accepted=explicit_acceptance,
                session_id=lifecycle.session_id,
                status=(
                    "accepted"
                    if explicit_acceptance
                    else "completed_pending_acceptance"
                ),
                result=result,
                metadata={
                    "execution_success": True,
                    "acceptance_evidence": (
                        explicit_acceptance
                    ),
                    "acceptance_boundary": (
                        "satisfied"
                        if explicit_acceptance
                        else "not_satisfied"
                    ),
                },
            )

        except Exception as exc:
            logger.exception(
                "[PersistentEngineeringRuntime] "
                "Engineering execution failed."
            )

            try:
                lifecycle.mark_failed(
                    reason=str(exc)
                )
            except Exception:
                logger.exception(
                    "[PersistentEngineeringRuntime] "
                    "Could not transition failed state."
                )

            return PersistentEngineeringResult(
                success=False,
                accepted=False,
                session_id=lifecycle.session_id,
                status="failed",
                error=str(exc),
                metadata={
                    "exception_type": type(
                        exc
                    ).__name__,
                },
            )

    # ============================================================
    # Resume
    # ============================================================

    async def resume(
        self,
        session_id: str,
        **kwargs: Any,
    ) -> PersistentEngineeringResult:
        lifecycle = await self._restore_session(
            session_id
        )

        if lifecycle is None:
            return PersistentEngineeringResult(
                success=False,
                accepted=False,
                session_id=session_id,
                status="session_not_found",
                error=(
                    f"Engineering session '{session_id}' "
                    "could not be restored."
                ),
            )

        self._sessions[
            session_id
        ] = lifecycle

        self._active_session_id = session_id

        self._record_runtime_evidence(
            lifecycle,
            kind="execution",
            summary=(
                "Engineering session resumed from "
                "persistent state."
            ),
            details={
                "session_id": session_id,
            },
        )

        return PersistentEngineeringResult(
            success=True,
            accepted=(
                self._session_is_accepted(
                    lifecycle
                )
            ),
            session_id=session_id,
            status="resumed",
            result=lifecycle.snapshot(),
            metadata={
                "resumed": True,
            },
        )

    async def _restore_session(
        self,
        session_id: str,
    ) -> AuthoritativeEngineeringLifecycleRuntime | None:
        persistence = self.persistence

        if persistence is None:
            return self._sessions.get(
                session_id
            )

        loader_names = (
            "load",
            "restore",
            "recover",
            "get",
        )

        raw: Any = None

        for name in loader_names:
            method = getattr(
                persistence,
                name,
                None,
            )

            if not callable(method):
                continue

            attempts = (
                lambda: method(session_id),
                lambda: method(
                    session_id=session_id
                ),
            )

            for attempt in attempts:
                try:
                    raw = attempt()

                    if inspect.isawaitable(
                        raw
                    ):
                        raw = await raw

                    break

                except TypeError:
                    continue
                except Exception:
                    logger.exception(
                        "[PersistentEngineeringRuntime] "
                        "Persistence load failed | method=%s",
                        name,
                    )
                    return None

            if raw is not None:
                break

        if raw is None:
            return self._sessions.get(
                session_id
            )

        lifecycle = (
            self._lifecycle_from_snapshot(
                raw,
                session_id,
            )
        )

        if lifecycle is not None:
            self._sessions[
                session_id
            ] = lifecycle

            self._active_session_id = (
                session_id
            )

        return lifecycle

    def _lifecycle_from_snapshot(
        self,
        raw: Any,
        session_id: str,
    ) -> AuthoritativeEngineeringLifecycleRuntime | None:
        """
        Restore through the session contract when the persistence
        implementation exposes a session snapshot.

        If a persistence backend already returns an authoritative
        runtime/session object, reuse it.
        """

        if isinstance(
            raw,
            AuthoritativeEngineeringLifecycleRuntime,
        ):
            return raw

        session = None

        if isinstance(raw, dict):
            session = raw.get(
                "session"
            )

            if session is None:
                session = raw

        else:
            session = getattr(
                raw,
                "session",
                None,
            )

        if session is None:
            return None

        lifecycle = (
            AuthoritativeEngineeringLifecycleRuntime(
                session=session,
                persistence=self.persistence,
                session_id=session_id,
            )
        )

        return lifecycle

    # ============================================================
    # Status
    # ============================================================

    def engineering_status(
        self,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        lifecycle = self._get_lifecycle(
            session_id
        )

        if lifecycle is None:
            return {
                "available": False,
                "session_id": (
                    session_id
                    or self._active_session_id
                ),
                "status": "no_active_session",
            }

        return {
            "available": True,
            "session_id": lifecycle.session_id,
            "status": lifecycle.status,
            "health": lifecycle.health(),
            "snapshot": lifecycle.snapshot(),
        }

    def status(
        self,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        return self.engineering_status(
            session_id
        )

    # ============================================================
    # Session helpers
    # ============================================================

    def _session_is_accepted(
        self,
        lifecycle: AuthoritativeEngineeringLifecycleRuntime,
    ) -> bool:
        phase = getattr(
            lifecycle.session,
            "phase",
            None,
        )

        if phase is None:
            return False

        value = getattr(
            phase,
            "value",
            phase,
        )

        return str(value).lower() == "accepted"

    def active_session(
        self,
    ) -> AuthoritativeEngineeringLifecycleRuntime | None:
        return self._get_lifecycle()

    def recoverable_sessions(
        self,
    ) -> list[str]:
        if self.persistence is None:
            return list(
                self._sessions.keys()
            )

        for name in (
            "recoverable_sessions",
            "list_recoverable",
            "list_sessions",
        ):
            method = getattr(
                self.persistence,
                name,
                None,
            )

            if not callable(method):
                continue

            try:
                result = method()

                if inspect.isawaitable(
                    result
                ):
                    return []

                if result is None:
                    return []

                return [
                    str(item)
                    for item in result
                ]

            except Exception:
                logger.exception(
                    "[PersistentEngineeringRuntime] "
                    "Could not list recoverable sessions."
                )
                return []

        return list(
            self._sessions.keys()
        )

    # ============================================================
    # Checkpoint / health
    # ============================================================

    def checkpoint(
        self,
        session_id: str | None = None,
    ) -> Any:
        lifecycle = self._get_lifecycle(
            session_id
        )

        if lifecycle is None:
            return None

        return lifecycle.checkpoint()

    def save(
        self,
        session_id: str | None = None,
    ) -> Any:
        return self.checkpoint(
            session_id
        )

    def persist(
        self,
        session_id: str | None = None,
    ) -> Any:
        return self.checkpoint(
            session_id
        )

    def health(self) -> dict[str, Any]:
        lifecycle = self._get_lifecycle()

        return {
            "healthy": True,
            "persistent": self.persistence is not None,
            "authoritative": True,
            "evidence_aware": True,
            "active_session_id": (
                self._active_session_id
            ),
            "active_session": (
                lifecycle.health()
                if lifecycle is not None
                else None
            ),
            "recoverable_session_count": len(
                self.recoverable_sessions()
            ),
        }

    # ============================================================
    # Compatibility
    # ============================================================

    def get(
        self,
        key: str,
        default: Any = None,
    ) -> Any:
        """
        Compatibility accessor used by existing bootstrap/
        capability-registry integrations.
        """

        mapping = {
            "persistent_engineering_runtime": self,
            "engineering_persistence": (
                self.persistence
            ),
            "authoritative_lifecycle": (
                self._get_lifecycle()
            ),
            "engineering_lifecycle": (
                self._get_lifecycle()
            ),
            "engineering_evidence": (
                self._get_lifecycle().evidence
                if self._get_lifecycle()
                else None
            ),
        }

        return mapping.get(
            key,
            default,
        )