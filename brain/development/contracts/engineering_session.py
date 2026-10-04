"""Authoritative engineering session for ARIA.

The EngineeringSession is the single mutable source of truth for one
autonomous engineering run.

It owns:
- lifecycle state
- engineering objective
- permissions
- repository/workspace information
- plans
- task progress
- knowledge context
- evidence
- failures
- repairs
- verification
- acceptance
- lifecycle history

It does NOT:
- execute shell commands
- edit repositories
- deploy
- push GitHub
- bypass permissions
- make autonomous engineering decisions by itself

Those responsibilities remain with specialized subsystems.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import RLock
from typing import Any, Sequence
from uuid import uuid4

from .engineering_evidence import (
    EngineeringEvidence,
    EvidenceKind,
)
from .engineering_state import (
    EngineeringPhase,
    EngineeringState,
    TERMINAL_PHASES,
)


@dataclass(frozen=True)
class SessionTransition:
    """Immutable record of one lifecycle transition."""

    revision: int

    from_phase: EngineeringPhase

    to_phase: EngineeringPhase

    reason: str

    timestamp: str

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "revision": self.revision,

            "from_phase": self.from_phase.value,

            "to_phase": self.to_phase.value,

            "reason": self.reason,

            "timestamp": self.timestamp,

            "metadata": deepcopy(
                self.metadata
            ),
        }


class EngineeringSession:
    """Authoritative state container for one engineering lifecycle."""

    VERSION = (
        "PHASE1-ENGINEERING-SESSION-20261004"
    )

    def __init__(
        self,
        *,
        session_id: str | None = None,
        goal: str = "",
        objective: str = "",
        constraints: Sequence[str] | None = None,
        acceptance_criteria: Sequence[str] | None = None,
        permissions: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._lock = RLock()

        resolved_session_id = (
            str(session_id).strip()
            if session_id is not None
            else ""
        )

        if not resolved_session_id:
            resolved_session_id = (
                f"eng-{uuid4().hex}"
            )

        self._session_id = (
            resolved_session_id
        )

        self._state = EngineeringState(
            phase=EngineeringPhase.CREATED,

            goal=str(goal),

            objective=str(objective),

            constraints=[
                str(item)
                for item in (
                    constraints or ()
                )
            ],

            acceptance_criteria=[
                str(item)
                for item in (
                    acceptance_criteria or ()
                )
            ],

            permissions=deepcopy(
                permissions or {}
            ),

            metadata=deepcopy(
                metadata or {}
            ),
        )

        self._evidence: dict[
            str,
            EngineeringEvidence,
        ] = {}

        self._transitions: list[
            SessionTransition
        ] = []

        self._created_at = (
            self._now()
        )

        self._updated_at = (
            self._created_at
        )

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def state(self) -> EngineeringState:
        """Return a defensive state copy."""

        with self._lock:
            return EngineeringState.from_dict(
                self._state.to_dict()
            )

    @property
    def phase(self) -> EngineeringPhase:
        with self._lock:
            return self._state.phase

    @property
    def created_at(self) -> str:
        return self._created_at

    @property
    def updated_at(self) -> str:
        with self._lock:
            return self._updated_at

    @property
    def terminal(self) -> bool:
        with self._lock:
            return (
                self._state.phase
                in TERMINAL_PHASES
            )

    # ------------------------------------------------------------------
    # Requirement
    # ------------------------------------------------------------------

    def set_goal(
        self,
        *,
        goal: str | None = None,
        objective: str | None = None,
        constraints: Sequence[str] | None = None,
        acceptance_criteria: Sequence[str] | None = None,
    ) -> None:
        """Update requirement-level information."""

        with self._lock:
            if goal is not None:
                self._state.goal = str(
                    goal
                )

            if objective is not None:
                self._state.objective = str(
                    objective
                )

            if constraints is not None:
                self._state.constraints = [
                    str(item)
                    for item in constraints
                ]

            if acceptance_criteria is not None:
                self._state.acceptance_criteria = [
                    str(item)
                    for item in acceptance_criteria
                ]

            self._touch()

    def set_permissions(
        self,
        permissions: dict[str, Any],
    ) -> None:
        if not isinstance(
            permissions,
            dict,
        ):
            raise TypeError(
                "permissions must be a dictionary."
            )

        with self._lock:
            self._state.permissions = deepcopy(
                permissions
            )

            self._touch()

    # ------------------------------------------------------------------
    # Repository / workspace
    # ------------------------------------------------------------------

    def set_repository_snapshot(
        self,
        snapshot: dict[str, Any],
    ) -> None:
        self._set_mapping(
            "repository_snapshot",
            snapshot,
        )

    def set_workspace(
        self,
        workspace: dict[str, Any],
    ) -> None:
        self._set_mapping(
            "workspace",
            workspace,
        )

    # ------------------------------------------------------------------
    # Planning
    # ------------------------------------------------------------------

    def set_plan(
        self,
        plan: dict[str, Any],
    ) -> None:
        self._set_mapping(
            "plan",
            plan,
        )

    def set_engineering_plan(
        self,
        plan: dict[str, Any],
    ) -> None:
        """Record the current adaptive engineering plan."""

        if not isinstance(
            plan,
            dict,
        ):
            raise TypeError(
                "plan must be a dictionary."
            )

        with self._lock:
            self._state.engineering_plan = (
                deepcopy(plan)
            )

            self._touch()

    def engineering_plan(
        self,
    ) -> dict[str, Any]:
        """Return a defensive copy of the adaptive plan."""

        with self._lock:
            return deepcopy(
                self._state.engineering_plan
            )

    def set_task_graph(
        self,
        task_graph: dict[str, Any],
    ) -> None:
        self._set_mapping(
            "task_graph",
            task_graph,
        )

    # ------------------------------------------------------------------
    # Knowledge
    # ------------------------------------------------------------------

    def set_knowledge_context(
        self,
        knowledge_context: dict[str, Any],
    ) -> None:
        """Record the knowledge used by this engineering run."""

        if not isinstance(
            knowledge_context,
            dict,
        ):
            raise TypeError(
                "knowledge_context must be a dictionary."
            )

        with self._lock:
            self._state.knowledge_context = (
                deepcopy(
                    knowledge_context
                )
            )

            self._touch()

    def knowledge_context(
        self,
    ) -> dict[str, Any]:
        """Return a defensive copy of the knowledge context."""

        with self._lock:
            return deepcopy(
                self._state.knowledge_context
            )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def transition(
        self,
        phase: EngineeringPhase | str,
        *,
        reason: str,
        metadata: dict[str, Any] | None = None,
        allow_terminal_reopen: bool = False,
    ) -> SessionTransition:
        """Move the session to another lifecycle phase."""

        if isinstance(
            phase,
            EngineeringPhase,
        ):
            target = phase
        else:
            try:
                target = EngineeringPhase(
                    str(phase)
                )
            except ValueError as exc:
                raise ValueError(
                    f"Unknown engineering phase: {phase!r}"
                ) from exc

        reason_text = str(
            reason
        ).strip()

        if not reason_text:
            raise ValueError(
                "A lifecycle transition requires a reason."
            )

        with self._lock:
            current = self._state.phase

            if (
                current in TERMINAL_PHASES
                and target != current
                and not allow_terminal_reopen
            ):
                raise RuntimeError(
                    "Terminal engineering session cannot be "
                    f"reopened: {current.value} -> "
                    f"{target.value}"
                )

            if current is target:
                self._touch()

                transition = SessionTransition(
                    revision=self._state.revision,

                    from_phase=current,

                    to_phase=target,

                    reason=reason_text,

                    timestamp=self._now(),

                    metadata=deepcopy(
                        metadata or {}
                    ),
                )

                self._transitions.append(
                    transition
                )

                return transition

            self._state.revision += 1

            self._state.phase = target

            self._touch()

            transition = SessionTransition(
                revision=self._state.revision,

                from_phase=current,

                to_phase=target,

                reason=reason_text,

                timestamp=self._now(),

                metadata=deepcopy(
                    metadata or {}
                ),
            )

            self._transitions.append(
                transition
            )

            return transition

    # ------------------------------------------------------------------
    # Tasks
    # ------------------------------------------------------------------

    def start_task(
        self,
        task_id: str,
    ) -> None:
        task = self._require_text(
            task_id,
            "task_id",
        )

        with self._lock:
            self._state.current_task = (
                task
            )

            self._touch()

    def complete_task(
        self,
        task_id: str,
    ) -> None:
        task = self._require_text(
            task_id,
            "task_id",
        )

        with self._lock:
            if (
                task
                not in self._state.completed_tasks
            ):
                self._state.completed_tasks.append(
                    task
                )

            if (
                self._state.current_task
                == task
            ):
                self._state.current_task = None

            self._touch()

    def is_task_completed(
        self,
        task_id: str,
    ) -> bool:
        with self._lock:
            return (
                str(task_id)
                in self._state.completed_tasks
            )

    def completed_tasks(
        self,
    ) -> tuple[str, ...]:
        with self._lock:
            return tuple(
                self._state.completed_tasks
            )

    # ------------------------------------------------------------------
    # Evidence
    # ------------------------------------------------------------------

    def add_evidence(
        self,
        evidence: EngineeringEvidence,
    ) -> None:
        """Record immutable evidence exactly once."""

        if not isinstance(
            evidence,
            EngineeringEvidence,
        ):
            raise TypeError(
                "evidence must be an "
                "EngineeringEvidence instance."
            )

        with self._lock:
            existing = self._evidence.get(
                evidence.evidence_id
            )

            if existing is not None:
                if existing != evidence:
                    raise ValueError(
                        "Evidence ID already exists with "
                        "different content: "
                        f"{evidence.evidence_id}"
                    )

                return

            self._evidence[
                evidence.evidence_id
            ] = evidence

            if (
                evidence.evidence_id
                not in self._state.evidence_ids
            ):
                self._state.evidence_ids.append(
                    evidence.evidence_id
                )

            if (
                evidence.kind
                is EvidenceKind.FAILURE
            ):
                if (
                    evidence.evidence_id
                    not in self._state.failure_ids
                ):
                    self._state.failure_ids.append(
                        evidence.evidence_id
                    )

            if (
                evidence.kind
                is EvidenceKind.REPAIR
            ):
                if (
                    evidence.evidence_id
                    not in self._state.repair_ids
                ):
                    self._state.repair_ids.append(
                        evidence.evidence_id
                    )

            self._touch()

    def evidence(
        self,
        evidence_id: str,
    ) -> EngineeringEvidence | None:
        with self._lock:
            return self._evidence.get(
                str(evidence_id)
            )

    def evidence_ids(
        self,
    ) -> Sequence[str]:
        with self._lock:
            return tuple(
                self._state.evidence_ids
            )

    def evidence_by_kind(
        self,
        kind: EvidenceKind | str,
    ) -> tuple[
        EngineeringEvidence,
        ...
    ]:
        if isinstance(
            kind,
            EvidenceKind,
        ):
            resolved_kind = kind
        else:
            resolved_kind = EvidenceKind(
                str(kind)
            )

        with self._lock:
            return tuple(
                evidence
                for evidence in (
                    self._evidence.values()
                )
                if evidence.kind
                is resolved_kind
            )

    def all_evidence(
        self,
    ) -> tuple[
        EngineeringEvidence,
        ...
    ]:
        with self._lock:
            return tuple(
                self._evidence.values()
            )

    # ------------------------------------------------------------------
    # Verification / acceptance
    # ------------------------------------------------------------------

    def set_verification(
        self,
        verification: dict[str, Any],
    ) -> None:
        self._set_mapping(
            "verification",
            verification,
        )

    def set_acceptance(
        self,
        acceptance: dict[str, Any],
    ) -> None:
        self._set_mapping(
            "acceptance",
            acceptance,
        )

    # ------------------------------------------------------------------
    # Failure / repair
    # ------------------------------------------------------------------

    def register_failure(
        self,
        evidence: EngineeringEvidence,
    ) -> None:
        if (
            evidence.kind
            is not EvidenceKind.FAILURE
        ):
            raise ValueError(
                "register_failure requires FAILURE evidence."
            )

        self.add_evidence(
            evidence
        )

    def register_repair(
        self,
        evidence: EngineeringEvidence,
    ) -> None:
        if (
            evidence.kind
            is not EvidenceKind.REPAIR
        ):
            raise ValueError(
                "register_repair requires REPAIR evidence."
            )

        self.add_evidence(
            evidence
        )

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------

    def set_metadata(
        self,
        key: str,
        value: Any,
    ) -> None:
        metadata_key = self._require_text(
            key,
            "metadata key",
        )

        with self._lock:
            self._state.metadata[
                metadata_key
            ] = deepcopy(
                value
            )

            self._touch()

    def get_metadata(
        self,
        key: str,
        default: Any = None,
    ) -> Any:
        with self._lock:
            return deepcopy(
                self._state.metadata.get(
                    str(key),
                    default,
                )
            )

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    def transitions(
        self,
    ) -> tuple[
        SessionTransition,
        ...
    ]:
        with self._lock:
            return tuple(
                self._transitions
            )

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------

    def snapshot(
        self,
    ) -> dict[str, Any]:
        """Return a complete serializable session snapshot."""

        with self._lock:
            return {
                "version": self.VERSION,

                "session_id": self._session_id,

                "created_at": self._created_at,

                "updated_at": self._updated_at,

                "state": self._state.to_dict(),

                "evidence": [
                    item.to_dict()
                    for item in (
                        self._evidence.values()
                    )
                ],

                "transitions": [
                    item.to_dict()
                    for item in (
                        self._transitions
                    )
                ],
            }

    # ------------------------------------------------------------------
    # Restoration
    # ------------------------------------------------------------------

    @classmethod
    def from_snapshot(
        cls,
        snapshot: dict[str, Any],
    ) -> "EngineeringSession":
        """Restore a session without executing engineering work."""

        if not isinstance(
            snapshot,
            dict,
        ):
            raise TypeError(
                "Session snapshot must be a dictionary."
            )

        state_payload = snapshot.get(
            "state"
        )

        if not isinstance(
            state_payload,
            dict,
        ):
            raise ValueError(
                "Session snapshot is missing state."
            )

        state = EngineeringState.from_dict(
            state_payload
        )

        session = cls(
            session_id=str(
                snapshot.get(
                    "session_id",
                    "",
                )
            ),

            goal=state.goal,

            objective=state.objective,

            constraints=state.constraints,

            acceptance_criteria=(
                state.acceptance_criteria
            ),

            permissions=state.permissions,

            metadata=state.metadata,
        )

        with session._lock:
            session._state = state

            created_at = snapshot.get(
                "created_at"
            )

            if created_at:
                session._created_at = str(
                    created_at
                )

            updated_at = snapshot.get(
                "updated_at"
            )

            if updated_at:
                session._updated_at = str(
                    updated_at
                )

            raw_evidence = snapshot.get(
                "evidence",
                [],
            )

            if not isinstance(
                raw_evidence,
                list,
            ):
                raise TypeError(
                    "Session evidence must be a list."
                )

            for item in raw_evidence:
                evidence = (
                    EngineeringEvidence.from_dict(
                        item
                    )
                )

                session._evidence[
                    evidence.evidence_id
                ] = evidence

            raw_transitions = snapshot.get(
                "transitions",
                [],
            )

            if not isinstance(
                raw_transitions,
                list,
            ):
                raise TypeError(
                    "Session transitions must be a list."
                )

            for item in raw_transitions:
                session._transitions.append(
                    SessionTransition(
                        revision=int(
                            item.get(
                                "revision",
                                0,
                            )
                        ),

                        from_phase=(
                            EngineeringPhase(
                                str(
                                    item.get(
                                        "from_phase"
                                    )
                                )
                            )
                        ),

                        to_phase=(
                            EngineeringPhase(
                                str(
                                    item.get(
                                        "to_phase"
                                    )
                                )
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
                                "",
                            )
                        ),

                        metadata=deepcopy(
                            item.get(
                                "metadata",
                                {},
                            )
                        ),
                    )
                )

        return session

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _set_mapping(
        self,
        attribute: str,
        value: dict[str, Any],
    ) -> None:
        if not isinstance(
            value,
            dict,
        ):
            raise TypeError(
                f"{attribute} must be a dictionary."
            )

        with self._lock:
            setattr(
                self._state,
                attribute,
                deepcopy(
                    value
                ),
            )

            self._touch()

    def _touch(self) -> None:
        self._updated_at = (
            self._now()
        )

    @staticmethod
    def _now() -> str:
        return datetime.now(
            timezone.utc
        ).isoformat()

    @staticmethod
    def _require_text(
        value: Any,
        field_name: str,
    ) -> str:
        text = str(
            value
        ).strip()

        if not text:
            raise ValueError(
                f"{field_name} must not be empty."
            )

        return text


AuthoritativeEngineeringSession = (
    EngineeringSession
)


__all__ = [
    "SessionTransition",
    "EngineeringSession",
    "AuthoritativeEngineeringSession",
]