from __future__ import annotations

import copy
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


logger = logging.getLogger("aria")

from .contracts.engineering_state import EngineeringPhase
from .contracts.engineering_evidence import EngineeringEvidence
from .contracts.engineering_requirement import EngineeringRequirement
from .contracts.engineering_result import EngineeringResult


@dataclass(frozen=True)
class SessionTransition:
    """
    Immutable record describing one engineering lifecycle transition.
    """

    transition_id: str
    session_id: str
    from_phase: str | None
    to_phase: str
    reason: str = ""
    timestamp: str = field(
        default_factory=lambda: datetime.now(
            timezone.utc
        ).isoformat()
    )
    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "transition_id": self.transition_id,
            "session_id": self.session_id,
            "from_phase": self.from_phase,
            "to_phase": self.to_phase,
            "reason": self.reason,
            "timestamp": self.timestamp,
            "metadata": dict(self.metadata),
        }


class EngineeringSession:
    """
    Authoritative mutable engineering session.

    This object owns the state of one autonomous engineering operation.

    Responsibilities:

        - session identity
        - requirement
        - lifecycle phase
        - task state
        - evidence
        - verification state
        - acceptance state
        - failure / repair state
        - metadata
        - transition history
        - persistence-compatible snapshots

    It deliberately does NOT execute code, run shell commands,
    push GitHub, deploy, or bypass permission boundaries.
    """

    VERSION = (
        "ENGINEERING-SESSION-20261004"
    )

    def __init__(
        self,
        requirement: Any | None = None,
        *,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        phase: EngineeringPhase | str = (
            EngineeringPhase.CREATED
        ),
        created_at: str | None = None,
        updated_at: str | None = None,
        transitions: list[Any] | None = None,
        evidence: list[Any] | None = None,
        tasks: dict[str, Any] | None = None,
        completed_tasks: list[str] | None = None,
        active_task_id: str | None = None,
        verification: Any = None,
        acceptance: Any = None,
        failures: list[Any] | None = None,
        repairs: list[Any] | None = None,
        metadata_extra: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        now = datetime.now(
            timezone.utc
        ).isoformat()

        self.session_id = (
            session_id
            or self._generate_session_id()
        )

        self.requirement = requirement

        self.phase = self._normalize_phase(
            phase
        )

        self.created_at = (
            created_at
            or now
        )

        self.updated_at = (
            updated_at
            or self.created_at
        )

        self.metadata: dict[str, Any] = dict(
            metadata or {}
        )

        if metadata_extra:
            self.metadata.update(
                metadata_extra
            )

        if kwargs:
            self.metadata.update(
                kwargs
            )

        self.transitions: list[
            SessionTransition
        ] = self._restore_transitions(
            transitions
        )

        self.evidence: list[Any] = list(
            evidence or []
        )

        self.tasks: dict[str, Any] = dict(
            tasks or {}
        )

        self.completed_tasks: list[str] = list(
            completed_tasks or []
        )

        self.active_task_id = (
            active_task_id
        )

        self.verification = verification

        self.acceptance = acceptance

        self.failures: list[Any] = list(
            failures or []
        )

        self.repairs: list[Any] = list(
            repairs or []
        )

        self._acceptance_explicit = (
            self.phase
            == EngineeringPhase.ACCEPTED
        )

        self._version = self.VERSION

    # ==========================================================
    # Identity
    # ==========================================================

    @staticmethod
    def _generate_session_id() -> str:
        return (
            "eng-"
            + uuid.uuid4().hex
        )

    @staticmethod
    def _generate_transition_id() -> str:
        return (
            "transition-"
            + uuid.uuid4().hex
        )

    @staticmethod
    def _normalize_phase(
        phase: EngineeringPhase | str | None,
    ) -> EngineeringPhase:
        if isinstance(
            phase,
            EngineeringPhase,
        ):
            return phase

        if phase is None:
            return EngineeringPhase.CREATED

        value = str(
            getattr(
                phase,
                "value",
                phase,
            )
        ).lower()

        try:
            return EngineeringPhase(
                value
            )
        except ValueError:
            return EngineeringPhase.CREATED

    # ==========================================================
    # Properties
    # ==========================================================

    @property
    def id(self) -> str:
        return self.session_id

    @property
    def status(self) -> str:
        return self.phase.value

    @property
    def current_phase(self) -> EngineeringPhase:
        return self.phase

    @property
    def is_accepted(self) -> bool:
        return (
            self.phase
            == EngineeringPhase.ACCEPTED
        )

    @property
    def accepted(self) -> bool:
        return self.is_accepted

    @property
    def is_terminal(self) -> bool:
        return self.phase in {
            EngineeringPhase.ACCEPTED,
            EngineeringPhase.BLOCKED,
            EngineeringPhase.FAILED,
        }

    @property
    def failed(self) -> bool:
        return (
            self.phase
            == EngineeringPhase.FAILED
        )

    @property
    def blocked(self) -> bool:
        return (
            self.phase
            == EngineeringPhase.BLOCKED
        )

    @property
    def transition_count(self) -> int:
        return len(
            self.transitions
        )

    @property
    def evidence_count(self) -> int:
        return len(
            self.evidence
        )

    # ==========================================================
    # Lifecycle
    # ==========================================================

    def transition(
        self,
        to_phase: EngineeringPhase | str,
        *,
        reason: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> SessionTransition:
        target = self._normalize_phase(
            to_phase
        )

        previous = self.phase

        transition = SessionTransition(
            transition_id=(
                self._generate_transition_id()
            ),
            session_id=self.session_id,
            from_phase=previous.value,
            to_phase=target.value,
            reason=str(
                reason
            ),
            metadata=dict(
                metadata or {}
            ),
        )

        self.phase = target

        self.transitions.append(
            transition
        )

        self.updated_at = (
            transition.timestamp
        )

        if target == EngineeringPhase.ACCEPTED:
            self._acceptance_explicit = True

        return transition

    def mark_created(
        self,
        *,
        reason: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> SessionTransition:
        return self.transition(
            EngineeringPhase.CREATED,
            reason=reason,
            metadata=metadata,
        )

    def mark_understanding(
        self,
        *,
        reason: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> SessionTransition:
        return self.transition(
            EngineeringPhase.UNDERSTANDING,
            reason=reason,
            metadata=metadata,
        )

    def mark_planning(
        self,
        *,
        reason: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> SessionTransition:
        return self.transition(
            EngineeringPhase.PLANNING,
            reason=reason,
            metadata=metadata,
        )

    def mark_graph_ready(
        self,
        *,
        reason: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> SessionTransition:
        return self.transition(
            EngineeringPhase.GRAPH_READY,
            reason=reason,
            metadata=metadata,
        )

    def mark_implementing(
        self,
        *,
        reason: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> SessionTransition:
        return self.transition(
            EngineeringPhase.IMPLEMENTING,
            reason=reason,
            metadata=metadata,
        )

    def mark_verifying(
        self,
        *,
        reason: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> SessionTransition:
        return self.transition(
            EngineeringPhase.VERIFYING,
            reason=reason,
            metadata=metadata,
        )

    def mark_testing(
        self,
        *,
        reason: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> SessionTransition:
        return self.transition(
            EngineeringPhase.TESTING,
            reason=reason,
            metadata=metadata,
        )

    def mark_diagnosing(
        self,
        *,
        reason: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> SessionTransition:
        return self.transition(
            EngineeringPhase.DIAGNOSING,
            reason=reason,
            metadata=metadata,
        )

    def mark_recovering(
        self,
        *,
        reason: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> SessionTransition:
        return self.transition(
            EngineeringPhase.RECOVERING,
            reason=reason,
            metadata=metadata,
        )

    def mark_retesting(
        self,
        *,
        reason: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> SessionTransition:
        return self.transition(
            EngineeringPhase.RETESTING,
            reason=reason,
            metadata=metadata,
        )

    def mark_reassessing(
        self,
        *,
        reason: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> SessionTransition:
        return self.transition(
            EngineeringPhase.REASSESSING,
            reason=reason,
            metadata=metadata,
        )

    def mark_accepting(
        self,
        *,
        reason: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> SessionTransition:
        return self.transition(
            EngineeringPhase.ACCEPTING,
            reason=reason,
            metadata=metadata,
        )

    def mark_accepted(
        self,
        *,
        reason: str = "",
        evidence: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> SessionTransition:
        """
        Mark the requirement genuinely accepted.

        Acceptance is explicit and may carry evidence.
        """

        if evidence is not None:
            self.acceptance = evidence

            self.add_evidence(
                evidence
            )

        self._acceptance_explicit = True

        return self.transition(
            EngineeringPhase.ACCEPTED,
            reason=reason,
            metadata=metadata,
        )

    def mark_blocked(
        self,
        *,
        reason: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> SessionTransition:
        return self.transition(
            EngineeringPhase.BLOCKED,
            reason=reason,
            metadata=metadata,
        )

    def mark_failed(
        self,
        *,
        reason: str = "",
        error: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> SessionTransition:
        failure = {
            "reason": reason,
            "error": self._serialize(
                error
            ),
            "timestamp": datetime.now(
                timezone.utc
            ).isoformat(),
        }

        self.failures.append(
            failure
        )

        return self.transition(
            EngineeringPhase.FAILED,
            reason=(
                reason
                or str(error or "Engineering failure")
            ),
            metadata=metadata,
        )

    # ==========================================================
    # Task state
    # ==========================================================

    def register_task(
        self,
        task_id: str,
        task: Any = None,
    ) -> Any:
        key = str(
            task_id
        )

        self.tasks[key] = (
            task
            if task is not None
            else {
                "task_id": key,
            }
        )

        self.updated_at = (
            datetime.now(
                timezone.utc
            ).isoformat()
        )

        return self.tasks[key]

    def start_task(
        self,
        task_id: str,
        task: Any = None,
    ) -> Any:
        key = str(
            task_id
        )

        if task is not None:
            self.tasks[key] = task
        elif key not in self.tasks:
            self.tasks[key] = {
                "task_id": key
            }

        self.active_task_id = key

        self._update_task_status(
            key,
            "running",
        )

        self.updated_at = (
            datetime.now(
                timezone.utc
            ).isoformat()
        )

        return self.tasks[key]

    def complete_task(
        self,
        task_id: str,
        result: Any = None,
    ) -> Any:
        key = str(
            task_id
        )

        if key not in self.tasks:
            self.tasks[key] = {
                "task_id": key
            }

        self._update_task_status(
            key,
            "completed",
        )

        if result is not None:
            self._attach_task_result(
                key,
                result,
            )

        if key not in self.completed_tasks:
            self.completed_tasks.append(
                key
            )

        if self.active_task_id == key:
            self.active_task_id = None

        self.updated_at = (
            datetime.now(
                timezone.utc
            ).isoformat()
        )

        return self.tasks[key]

    def fail_task(
        self,
        task_id: str,
        error: Any = None,
    ) -> Any:
        key = str(
            task_id
        )

        if key not in self.tasks:
            self.tasks[key] = {
                "task_id": key
            }

        self._update_task_status(
            key,
            "failed",
        )

        self._attach_task_error(
            key,
            error,
        )

        self.updated_at = (
            datetime.now(
                timezone.utc
            ).isoformat()
        )

        return self.tasks[key]

    def _update_task_status(
        self,
        task_id: str,
        status: str,
    ) -> None:
        task = self.tasks.get(
            task_id
        )

        if isinstance(
            task,
            dict,
        ):
            task["status"] = status
            task["updated_at"] = (
                datetime.now(
                    timezone.utc
                ).isoformat()
            )
            return

        try:
            setattr(
                task,
                "status",
                status,
            )
        except Exception:
            pass

    def _attach_task_result(
        self,
        task_id: str,
        result: Any,
    ) -> None:
        task = self.tasks.get(
            task_id
        )

        if isinstance(
            task,
            dict,
        ):
            task["result"] = self._serialize(
                result
            )
            return

        try:
            setattr(
                task,
                "result",
                result,
            )
        except Exception:
            pass

    def _attach_task_error(
        self,
        task_id: str,
        error: Any,
    ) -> None:
        task = self.tasks.get(
            task_id
        )

        if isinstance(
            task,
            dict,
        ):
            task["error"] = self._serialize(
                error
            )
            return

        try:
            setattr(
                task,
                "error",
                error,
            )
        except Exception:
            pass

    def task_status(
        self,
        task_id: str,
    ) -> str | None:
        task = self.tasks.get(
            str(task_id)
        )

        if task is None:
            return None

        if isinstance(
            task,
            dict,
        ):
            value = task.get(
                "status"
            )

            return (
                str(value)
                if value is not None
                else None
            )

        value = getattr(
            task,
            "status",
            None,
        )

        if value is None:
            return None

        return str(
            getattr(
                value,
                "value",
                value,
            )
        )

    # ==========================================================
    # Evidence
    # ==========================================================

    def add_evidence(
        self,
        evidence: Any,
    ) -> Any:
        """
        Attach evidence to the session.

        Evidence is stored as-is so that richer evidence records
        from the central recorder remain recoverable.
        """

        if evidence is None:
            return None

        self.evidence.append(
            evidence
        )

        self.updated_at = (
            datetime.now(
                timezone.utc
            ).isoformat()
        )

        return evidence

    def record_evidence(
        self,
        evidence: Any = None,
        *,
        kind: str | None = None,
        summary: str | None = None,
        details: Any = None,
        source: str = "engineering_session",
        **kwargs: Any,
    ) -> Any:
        if evidence is None:
            evidence = {
                "kind": (
                    kind
                    or "engineering"
                ),
                "summary": (
                    summary
                    or ""
                ),
                "details": self._serialize(
                    details
                ),
                "source": source,
                "timestamp": datetime.now(
                    timezone.utc
                ).isoformat(),
                **kwargs,
            }

        return self.add_evidence(
            evidence
        )

    def append_evidence(
        self,
        evidence: Any,
    ) -> Any:
        return self.add_evidence(
            evidence
        )

    def latest_evidence(
        self,
        count: int = 1,
    ) -> list[Any]:
        if count <= 0:
            return []

        return list(
            self.evidence[-count:]
        )

    # ==========================================================
    # Verification / acceptance
    # ==========================================================

    def set_verification(
        self,
        verification: Any,
    ) -> Any:
        self.verification = verification

        self.add_evidence(
            {
                "kind": "verification",
                "details": self._serialize(
                    verification
                ),
                "timestamp": datetime.now(
                    timezone.utc
                ).isoformat(),
            }
        )

        return verification

    def set_acceptance(
        self,
        acceptance: Any,
    ) -> Any:
        self.acceptance = acceptance

        self.add_evidence(
            {
                "kind": "acceptance",
                "details": self._serialize(
                    acceptance
                ),
                "timestamp": datetime.now(
                    timezone.utc
                ).isoformat(),
            }
        )

        return acceptance

    def has_acceptance_evidence(
        self,
    ) -> bool:
        if self._acceptance_explicit:
            return True

        if self.acceptance is not None:
            return True

        for evidence in self.evidence:
            if isinstance(
                evidence,
                dict,
            ):
                kind = str(
                    evidence.get(
                        "kind",
                        "",
                    )
                ).lower()

                if kind == "acceptance":
                    return True

            else:
                kind = getattr(
                    evidence,
                    "kind",
                    None,
                )

                if (
                    kind is not None
                    and str(
                        getattr(
                            kind,
                            "value",
                            kind,
                        )
                    ).lower()
                    == "acceptance"
                ):
                    return True

        return False

    # ==========================================================
    # Failure / recovery
    # ==========================================================

    def add_failure(
        self,
        failure: Any,
    ) -> Any:
        self.failures.append(
            failure
        )

        self.updated_at = (
            datetime.now(
                timezone.utc
            ).isoformat()
        )

        return failure

    def add_repair(
        self,
        repair: Any,
    ) -> Any:
        self.repairs.append(
            repair
        )

        self.updated_at = (
            datetime.now(
                timezone.utc
            ).isoformat()
        )

        return repair

    # ==========================================================
    # Metadata
    # ==========================================================

    def set_metadata(
        self,
        key: str,
        value: Any,
    ) -> Any:
        self.metadata[
            str(key)
        ] = value

        self.updated_at = (
            datetime.now(
                timezone.utc
            ).isoformat()
        )

        return value

    def update_metadata(
        self,
        values: dict[str, Any],
    ) -> None:
        self.metadata.update(
            values
        )

        self.updated_at = (
            datetime.now(
                timezone.utc
            ).isoformat()
        )

    # ==========================================================
    # Persistence
    # ==========================================================

    def snapshot(
        self,
    ) -> dict[str, Any]:
        """
        Produce a persistence-safe session snapshot.
        """

        return {
            "version": self.VERSION,
            "session_id": self.session_id,
            "requirement": self._serialize(
                self.requirement
            ),
            "phase": self.phase.value,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self._serialize(
                self.metadata
            ),
            "transitions": [
                self._serialize(
                    item
                )
                for item in self.transitions
            ],
            "evidence": [
                self._serialize(
                    item
                )
                for item in self.evidence
            ],
            "tasks": self._serialize(
                self.tasks
            ),
            "completed_tasks": list(
                self.completed_tasks
            ),
            "active_task_id": (
                self.active_task_id
            ),
            "verification": self._serialize(
                self.verification
            ),
            "acceptance": self._serialize(
                self.acceptance
            ),
            "acceptance_explicit": (
                self._acceptance_explicit
            ),
            "failures": self._serialize(
                self.failures
            ),
            "repairs": self._serialize(
                self.repairs
            ),
        }

    def to_dict(
        self,
    ) -> dict[str, Any]:
        return self.snapshot()

    def save(
        self,
        persistence: Any | None = None,
    ) -> Any:
        """
        Persist through a supplied persistence backend.

        This method intentionally performs no filesystem or network
        operations itself.
        """

        backend = persistence

        if backend is None:
            return self.snapshot()

        payload = self.snapshot()

        for name in (
            "save",
            "persist",
            "checkpoint",
            "store",
        ):
            method = getattr(
                backend,
                name,
                None,
            )

            if not callable(method):
                continue

            attempts = (
                lambda: method(
                    self.session_id,
                    payload,
                ),
                lambda: method(
                    session_id=self.session_id,
                    snapshot=payload,
                ),
                lambda: method(
                    payload
                ),
            )

            for attempt in attempts:
                try:
                    return attempt()
                except TypeError:
                    continue
                except Exception:
                    logger.exception(
                        "[EngineeringSession] "
                        "Persistence failed | method=%s",
                        name,
                    )
                    return None

        return payload

    def persist(
        self,
        persistence: Any | None = None,
    ) -> Any:
        return self.save(
            persistence
        )

    def checkpoint(
        self,
        persistence: Any | None = None,
    ) -> Any:
        return self.save(
            persistence
        )

    # ==========================================================
    # Restore
    # ==========================================================

    @classmethod
    def from_snapshot(
        cls,
        snapshot: Any,
        *,
        persistence: Any | None = None,
    ) -> "EngineeringSession":
        if isinstance(
            snapshot,
            cls,
        ):
            return snapshot

        if snapshot is None:
            return cls()

        if not isinstance(
            snapshot,
            dict,
        ):
            session = getattr(
                snapshot,
                "session",
                None,
            )

            if session is not None:
                return cls.from_snapshot(
                    session,
                    persistence=persistence,
                )

            return cls(
                requirement=snapshot
            )

        return cls(
            requirement=snapshot.get(
                "requirement"
            ),
            session_id=snapshot.get(
                "session_id"
            ),
            metadata=snapshot.get(
                "metadata",
                {},
            ),
            phase=snapshot.get(
                "phase",
                EngineeringPhase.CREATED.value,
            ),
            created_at=snapshot.get(
                "created_at"
            ),
            updated_at=snapshot.get(
                "updated_at"
            ),
            transitions=snapshot.get(
                "transitions",
                [],
            ),
            evidence=snapshot.get(
                "evidence",
                [],
            ),
            tasks=snapshot.get(
                "tasks",
                {},
            ),
            completed_tasks=snapshot.get(
                "completed_tasks",
                [],
            ),
            active_task_id=snapshot.get(
                "active_task_id"
            ),
            verification=snapshot.get(
                "verification"
            ),
            acceptance=snapshot.get(
                "acceptance"
            ),
            failures=snapshot.get(
                "failures",
                [],
            ),
            repairs=snapshot.get(
                "repairs",
                [],
            ),
            metadata_extra={
                "restored": True,
                "persistence_available": (
                    persistence is not None
                ),
            },
        )

    @classmethod
    def restore(
        cls,
        snapshot: Any,
        *,
        persistence: Any | None = None,
    ) -> "EngineeringSession":
        return cls.from_snapshot(
            snapshot,
            persistence=persistence,
        )

    # ==========================================================
    # Transition restoration
    # ==========================================================

    @classmethod
    def _restore_transitions(
        cls,
        values: list[Any] | None,
    ) -> list[SessionTransition]:
        restored: list[
            SessionTransition
        ] = []

        for item in values or []:
            if isinstance(
                item,
                SessionTransition,
            ):
                restored.append(
                    item
                )
                continue

            if not isinstance(
                item,
                dict,
            ):
                continue

            restored.append(
                SessionTransition(
                    transition_id=str(
                        item.get(
                            "transition_id",
                            cls._generate_transition_id(),
                        )
                    ),
                    session_id=str(
                        item.get(
                            "session_id",
                            "",
                        )
                    ),
                    from_phase=item.get(
                        "from_phase"
                    ),
                    to_phase=str(
                        item.get(
                            "to_phase",
                            EngineeringPhase.CREATED.value,
                        )
                    ),
                    reason=str(
                        item.get(
                            "reason",
                            "",
                        )
                    ),
                    timestamp=str(
                        item.get(
                            "timestamp",
                            datetime.now(
                                timezone.utc
                            ).isoformat(),
                        )
                    ),
                    metadata=dict(
                        item.get(
                            "metadata",
                            {},
                        )
                        if isinstance(
                            item.get(
                                "metadata",
                                {},
                            ),
                            dict,
                        )
                        else {}
                    ),
                )
            )

        return restored

    # ==========================================================
    # Health / status
    # ==========================================================

    def health(
        self,
    ) -> dict[str, Any]:
        return {
            "healthy": True,
            "session_id": self.session_id,
            "phase": self.phase.value,
            "status": self.status,
            "accepted": self.is_accepted,
            "failed": self.failed,
            "blocked": self.blocked,
            "terminal": self.is_terminal,
            "transition_count": len(
                self.transitions
            ),
            "evidence_count": len(
                self.evidence
            ),
            "task_count": len(
                self.tasks
            ),
            "completed_task_count": len(
                self.completed_tasks
            ),
            "failure_count": len(
                self.failures
            ),
            "repair_count": len(
                self.repairs
            ),
        }

    def status_dict(
        self,
    ) -> dict[str, Any]:
        return self.health()

    # ==========================================================
    # Serialization helper
    # ==========================================================

    @classmethod
    def _serialize(
        cls,
        value: Any,
    ) -> Any:
        if value is None:
            return None

        if isinstance(
            value,
            Enum,
        ):
            return value.value

        if isinstance(
            value,
            dict,
        ):
            return {
                str(key): cls._serialize(
                    item
                )
                for key, item in value.items()
            }

        if isinstance(
            value,
            (list, tuple, set),
        ):
            return [
                cls._serialize(
                    item
                )
                for item in value
            ]

        if isinstance(
            value,
            datetime,
        ):
            return value.isoformat()

        to_dict = getattr(
            value,
            "to_dict",
            None,
        )

        if callable(to_dict):
            try:
                return cls._serialize(
                    to_dict()
                )
            except Exception:
                pass

        if hasattr(
            value,
            "__dict__",
        ):
            try:
                return {
                    str(key): cls._serialize(
                        item
                    )
                    for key, item in vars(
                        value
                    ).items()
                    if not str(
                        key
                    ).startswith("_")
                }
            except Exception:
                pass

        try:
            copy.deepcopy(
                value
            )
            return value
        except Exception:
            return str(
                value
            )


# Compatibility alias used by earlier Phase 1 integrations.
AuthoritativeEngineeringSession = (
    EngineeringSession
)


__all__ = [
    "EngineeringPhase",
    "SessionTransition",
    "EngineeringSession",
    "AuthoritativeEngineeringSession",
]
