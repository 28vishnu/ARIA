"""Authoritative mutable engineering session for ARIA.

The EngineeringSession is the single in-memory source of truth for one
autonomous engineering run.

It connects:

    Requirement
        ↓
    Knowledge
        ↓
    Plan
        ↓
    Task Graph
        ↓
    Execution
        ↓
    Evidence
        ↓
    Verification
        ↓
    Acceptance

The session itself does not execute code. It owns engineering state and
provides controlled state transitions to the execution layers.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

from .engineering_evidence import (
    EngineeringEvidence,
)
from .engineering_requirement import (
    EngineeringRequirement,
)
from .engineering_state import (
    EngineeringPhase,
    EngineeringState,
)
from .engineering_result import (
    EngineeringResult,
)


def _utc_now() -> str:
    """Return the current UTC timestamp in ISO-8601 form."""
    return datetime.now(
        timezone.utc
    ).isoformat()


@dataclass(frozen=True)
class SessionTransition:
    """Record one authoritative session transition."""

    from_phase: EngineeringPhase
    to_phase: EngineeringPhase
    reason: str
    timestamp: str = field(
        default_factory=_utc_now
    )
    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_phase": self.from_phase.value,
            "to_phase": self.to_phase.value,
            "reason": self.reason,
            "timestamp": self.timestamp,
            "metadata": deepcopy(
                self.metadata
            ),
        }


class EngineeringSession:
    """Authoritative mutable engineering session."""

    VERSION = "PHASE1-ENGINEERING-SESSION-20261004"

    def __init__(
        self,
        *,
        session_id: str,
        requirement: EngineeringRequirement | None = None,
        state: EngineeringState | None = None,
    ) -> None:
        if not str(session_id).strip():
            raise ValueError(
                "session_id must not be empty."
            )

        self.session_id = str(
            session_id
        )

        self.requirement = requirement

        self.state = (
            state
            if state is not None
            else EngineeringState()
        )

        self.created_at = _utc_now()
        self.updated_at = self.created_at

        self.transitions: list[
            SessionTransition
        ] = []

        self._evidence: dict[
            str,
            EngineeringEvidence,
        ] = {}

        self._metadata: dict[
            str,
            Any,
        ] = {}

        self._engineering_plan: dict[
            str,
            Any,
        ] | None = None

        self._engineering_task_graph: dict[
            str,
            Any,
        ] | None = None

        self._verification: dict[
            str,
            Any,
        ] | None = None

        self._acceptance: dict[
            str,
            Any,
        ] | None = None

        self._failure: dict[
            str,
            Any,
        ] | None = None

        self._repair: dict[
            str,
            Any,
        ] | None = None

        self._result: EngineeringResult | None = None

    # ==============================================================
    # STATE
    # ==============================================================

    @property
    def phase(self) -> EngineeringPhase:
        """Return the current authoritative engineering phase."""
        return self.state.phase

    def transition(
        self,
        phase: EngineeringPhase,
        *,
        reason: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> SessionTransition:
        """Move the session to a new engineering phase."""

        if not isinstance(
            phase,
            EngineeringPhase,
        ):
            raise TypeError(
                "phase must be an EngineeringPhase."
            )

        previous = self.state.phase

        transition = SessionTransition(
            from_phase=previous,
            to_phase=phase,
            reason=str(reason),
            metadata=dict(
                metadata or {}
            ),
        )

        self.state.phase = phase

        self.transitions.append(
            transition
        )

        self.touch()

        return transition

    def set_phase(
        self,
        phase: EngineeringPhase,
        *,
        reason: str = "",
    ) -> None:
        """Compatibility helper for explicit phase changes."""

        self.transition(
            phase,
            reason=(
                reason
                or f"phase changed to {phase.value}"
            ),
        )

    # ==============================================================
    # REQUIREMENT
    # ==============================================================

    def set_requirement(
        self,
        requirement: EngineeringRequirement,
    ) -> None:
        """Attach the authoritative structured requirement."""

        if not isinstance(
            requirement,
            EngineeringRequirement,
        ):
            raise TypeError(
                "requirement must be an EngineeringRequirement."
            )

        self.requirement = requirement

        self.touch()

    def get_requirement(
        self,
    ) -> EngineeringRequirement | None:
        return self.requirement

    # ==============================================================
    # KNOWLEDGE
    # ==============================================================

    def set_knowledge_context(
        self,
        knowledge_context: Any,
    ) -> None:
        """Attach the authoritative engineering knowledge context."""

        self.state.knowledge_context = deepcopy(
            knowledge_context
        )

        self.touch()

    def knowledge_context(
        self,
    ) -> Any:
        """Return the current knowledge context."""

        return deepcopy(
            getattr(
                self.state,
                "knowledge_context",
                None,
            )
        )

    # ==============================================================
    # PLAN
    # ==============================================================

    def set_engineering_plan(
        self,
        plan: Any,
    ) -> None:
        """Attach the current adaptive engineering plan."""

        if plan is None:
            self._engineering_plan = None

            if hasattr(
                self.state,
                "engineering_plan",
            ):
                self.state.engineering_plan = None

            self.touch()

            return

        if hasattr(
            plan,
            "to_dict",
        ):
            payload = plan.to_dict()
        elif isinstance(
            plan,
            Mapping,
        ):
            payload = dict(plan)
        else:
            raise TypeError(
                "engineering plan must provide to_dict() "
                "or be a mapping."
            )

        self._engineering_plan = deepcopy(
            payload
        )

        if hasattr(
            self.state,
            "engineering_plan",
        ):
            self.state.engineering_plan = deepcopy(
                payload
            )

        self.touch()

    def engineering_plan(
        self,
    ) -> dict[str, Any] | None:
        """Return a copy of the current engineering plan."""

        if self._engineering_plan is not None:
            return deepcopy(
                self._engineering_plan
            )

        value = getattr(
            self.state,
            "engineering_plan",
            None,
        )

        if value is None:
            return None

        return deepcopy(
            value
        )

    # ==============================================================
    # TASK GRAPH
    # ==============================================================

    def set_engineering_task_graph(
        self,
        task_graph: Any,
    ) -> None:
        """Attach the authoritative engineering task graph.

        The graph is stored as a serializable snapshot so the session
        remains independent of any particular graph implementation.
        """

        if task_graph is None:
            self._engineering_task_graph = None

            self.touch()

            return

        if hasattr(
            task_graph,
            "to_dict",
        ):
            payload = task_graph.to_dict()
        elif isinstance(
            task_graph,
            Mapping,
        ):
            payload = dict(task_graph)
        else:
            raise TypeError(
                "engineering task graph must provide to_dict() "
                "or be a mapping."
            )

        self._engineering_task_graph = deepcopy(
            payload
        )

        self.touch()

    def engineering_task_graph(
        self,
    ) -> dict[str, Any] | None:
        """Return a copy of the authoritative task graph."""

        if self._engineering_task_graph is None:
            return None

        return deepcopy(
            self._engineering_task_graph
        )

    # ==============================================================
    # EVIDENCE
    # ==============================================================

    def add_evidence(
        self,
        evidence: EngineeringEvidence,
    ) -> None:
        """Register authoritative engineering evidence."""

        if not isinstance(
            evidence,
            EngineeringEvidence,
        ):
            raise TypeError(
                "evidence must be an EngineeringEvidence."
            )

        evidence_id = str(
            getattr(
                evidence,
                "evidence_id",
                "",
            )
        ).strip()

        if not evidence_id:
            raise ValueError(
                "Engineering evidence must have an evidence_id."
            )

        self._evidence[
            evidence_id
        ] = evidence

        self.touch()

    def record_evidence(
        self,
        evidence: EngineeringEvidence,
    ) -> None:
        """Alias for add_evidence()."""

        self.add_evidence(
            evidence
        )

    def evidence(
        self,
        evidence_id: str | None = None,
    ) -> (
        EngineeringEvidence
        | tuple[EngineeringEvidence, ...]
        | None
    ):
        """Return one evidence item or all evidence."""

        if evidence_id is not None:
            return self._evidence.get(
                str(evidence_id)
            )

        return tuple(
            self._evidence.values()
        )

    def evidence_count(self) -> int:
        return len(
            self._evidence
        )

    # ==============================================================
    # VERIFICATION
    # ==============================================================

    def set_verification(
        self,
        verification: Any,
    ) -> None:
        """Store the latest verification decision/evidence."""

        if hasattr(
            verification,
            "to_dict",
        ):
            verification = verification.to_dict()

        if verification is None:
            self._verification = None
        elif isinstance(
            verification,
            Mapping,
        ):
            self._verification = deepcopy(
                dict(verification)
            )
        else:
            self._verification = {
                "value": deepcopy(
                    verification
                )
            }

        self.touch()

    def verification(
        self,
    ) -> dict[str, Any] | None:
        return deepcopy(
            self._verification
        )

    # ==============================================================
    # ACCEPTANCE
    # ==============================================================

    def set_acceptance(
        self,
        acceptance: Any,
    ) -> None:
        """Store the latest acceptance judgment."""

        if hasattr(
            acceptance,
            "to_dict",
        ):
            acceptance = acceptance.to_dict()

        if acceptance is None:
            self._acceptance = None
        elif isinstance(
            acceptance,
            Mapping,
        ):
            self._acceptance = deepcopy(
                dict(acceptance)
            )
        else:
            self._acceptance = {
                "value": deepcopy(
                    acceptance
                )
            }

        self.touch()

    def acceptance(
        self,
    ) -> dict[str, Any] | None:
        return deepcopy(
            self._acceptance
        )

    # ==============================================================
    # FAILURE / REPAIR
    # ==============================================================

    def record_failure(
        self,
        failure: Any,
    ) -> None:
        """Record the latest engineering failure."""

        if hasattr(
            failure,
            "to_dict",
        ):
            failure = failure.to_dict()

        if isinstance(
            failure,
            Mapping,
        ):
            self._failure = deepcopy(
                dict(failure)
            )
        else:
            self._failure = {
                "value": deepcopy(
                    failure
                )
            }

        self.touch()

    def failure(
        self,
    ) -> dict[str, Any] | None:
        return deepcopy(
            self._failure
        )

    def record_repair(
        self,
        repair: Any,
    ) -> None:
        """Record the latest recovery/repair action."""

        if hasattr(
            repair,
            "to_dict",
        ):
            repair = repair.to_dict()

        if isinstance(
            repair,
            Mapping,
        ):
            self._repair = deepcopy(
                dict(repair)
            )
        else:
            self._repair = {
                "value": deepcopy(
                    repair
                )
            }

        self.touch()

    def repair(
        self,
    ) -> dict[str, Any] | None:
        return deepcopy(
            self._repair
        )

    # ==============================================================
    # TASK PROGRESS
    # ==============================================================

    def start_task(
        self,
        task_id: str,
    ) -> None:
        """Record that a task has started."""

        self._set_task_metadata(
            task_id,
            status="running",
        )

    def complete_task(
        self,
        task_id: str,
        *,
        evidence: Mapping[str, Any] | None = None,
    ) -> None:
        """Record task completion and optional evidence."""

        self._set_task_metadata(
            task_id,
            status="completed",
            evidence=dict(
                evidence or {}
            ),
        )

    def fail_task(
        self,
        task_id: str,
        *,
        reason: str = "",
    ) -> None:
        """Record task failure."""

        self._set_task_metadata(
            task_id,
            status="failed",
            failure_reason=str(
                reason
            ),
        )

    def _set_task_metadata(
        self,
        task_id: str,
        *,
        status: str,
        **values: Any,
    ) -> None:
        """Update a task inside the stored graph snapshot."""

        graph = self._engineering_task_graph

        if graph is None:
            raise RuntimeError(
                "Cannot update task progress before "
                "an engineering task graph is attached."
            )

        payload = deepcopy(
            graph
        )

        tasks = payload.get(
            "tasks",
            [],
        )

        found = False

        for task in tasks:
            if not isinstance(
                task,
                dict,
            ):
                continue

            if str(
                task.get(
                    "task_id",
                    "",
                )
            ) != str(task_id):
                continue

            task[
                "status"
            ] = status

            metadata = task.get(
                "metadata",
                {},
            )

            if not isinstance(
                metadata,
                dict,
            ):
                metadata = {}

            metadata.update(
                values
            )

            task[
                "metadata"
            ] = metadata

            found = True

            break

        if not found:
            raise KeyError(
                f"Unknown engineering task: {task_id}"
            )

        self._engineering_task_graph = payload

        self.touch()

    # ==============================================================
    # METADATA
    # ==============================================================

    def set_metadata(
        self,
        key: str,
        value: Any,
    ) -> None:
        if not str(key).strip():
            raise ValueError(
                "metadata key must not be empty."
            )

        self._metadata[
            str(key)
        ] = deepcopy(
            value
        )

        self.touch()

    def metadata(
        self,
    ) -> dict[str, Any]:
        return deepcopy(
            self._metadata
        )

    # ==============================================================
    # RESULT
    # ==============================================================

    def set_result(
        self,
        result: EngineeringResult,
    ) -> None:
        """Attach the final engineering result."""

        if not isinstance(
            result,
            EngineeringResult,
        ):
            raise TypeError(
                "result must be an EngineeringResult."
            )

        self._result = result

        self.touch()

    def result(
        self,
    ) -> EngineeringResult | None:
        return self._result

    # ==============================================================
    # SNAPSHOT / RESTORE
    # ==============================================================

    def snapshot(
        self,
    ) -> dict[str, Any]:
        """Create a JSON-serializable session snapshot."""

        return {
            "version": self.VERSION,
            "session_id": self.session_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "requirement": (
                self.requirement.to_dict()
                if self.requirement is not None
                and hasattr(
                    self.requirement,
                    "to_dict",
                )
                else deepcopy(
                    self.requirement
                )
            ),
            "state": (
                self.state.to_dict()
                if hasattr(
                    self.state,
                    "to_dict",
                )
                else deepcopy(
                    self.state
                )
            ),
            "transitions": [
                item.to_dict()
                for item in self.transitions
            ],
            "evidence": {
                key: (
                    value.to_dict()
                    if hasattr(
                        value,
                        "to_dict",
                    )
                    else deepcopy(
                        value
                    )
                )
                for key, value
                in self._evidence.items()
            },
            "engineering_plan": deepcopy(
                self._engineering_plan
            ),
            "engineering_task_graph": deepcopy(
                self._engineering_task_graph
            ),
            "verification": deepcopy(
                self._verification
            ),
            "acceptance": deepcopy(
                self._acceptance
            ),
            "failure": deepcopy(
                self._failure
            ),
            "repair": deepcopy(
                self._repair
            ),
            "metadata": deepcopy(
                self._metadata
            ),
            "result": (
                self._result.to_dict()
                if self._result is not None
                and hasattr(
                    self._result,
                    "to_dict",
                )
                else deepcopy(
                    self._result
                )
            ),
        }

    def to_dict(
        self,
    ) -> dict[str, Any]:
        """Alias for snapshot()."""
        return self.snapshot()

    # ==============================================================
    # TIME
    # ==============================================================

    def touch(self) -> None:
        """Update the session modification timestamp."""

        self.updated_at = _utc_now()

    # ==============================================================
    # DEBUGGING
    # ==============================================================

    def summary(
        self,
    ) -> dict[str, Any]:
        """Return a compact operational summary."""

        graph = self._engineering_task_graph or {}

        tasks = graph.get(
            "tasks",
            [],
        )

        completed = 0
        failed = 0
        pending = 0

        for task in tasks:
            if not isinstance(
                task,
                dict,
            ):
                continue

            status = str(
                task.get(
                    "status",
                    "",
                )
            )

            if status == "completed":
                completed += 1
            elif status == "failed":
                failed += 1
            else:
                pending += 1

        return {
            "session_id": self.session_id,
            "phase": self.state.phase.value,
            "tasks_total": len(tasks),
            "tasks_completed": completed,
            "tasks_failed": failed,
            "tasks_pending": pending,
            "evidence_count": self.evidence_count(),
            "has_requirement": (
                self.requirement is not None
            ),
            "has_plan": (
                self._engineering_plan is not None
            ),
            "has_task_graph": (
                self._engineering_task_graph is not None
            ),
            "has_verification": (
                self._verification is not None
            ),
            "has_acceptance": (
                self._acceptance is not None
            ),
            "updated_at": self.updated_at,
        }


# Backward/semantic alias used by future Phase 1 components.
AuthoritativeEngineeringSession = EngineeringSession


__all__ = [
    "SessionTransition",
    "EngineeringSession",
    "AuthoritativeEngineeringSession",
]