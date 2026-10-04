"""Adaptive engineering-plan contracts for ARIA.

Step 9 defines durable planning and replanning structures.

Plans are evidence-aware:
- the original objective remains stable
- implementation strategy may change
- completed work is preserved
- failed assumptions are recorded
- replanning produces a new revision rather than silently replacing history

This module does not execute code, modify repositories, run tests, deploy,
or push to GitHub.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Sequence


class PlanStatus(str, Enum):
    """Current status of an engineering plan."""

    PROPOSED = "proposed"
    ACTIVE = "active"
    REVISED = "revised"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    ABANDONED = "abandoned"


class PlanChangeReason(str, Enum):
    """Why an engineering plan was changed."""

    INITIAL = "initial"
    NEW_EVIDENCE = "new_evidence"
    TEST_FAILURE = "test_failure"
    ROOT_CAUSE = "root_cause"
    REPOSITORY_CHANGE = "repository_change"
    REQUIREMENT_CHANGE = "requirement_change"
    DEPENDENCY_CHANGE = "dependency_change"
    SAFETY_CONSTRAINT = "safety_constraint"
    ACCEPTANCE_GAP = "acceptance_gap"
    RECOVERY = "recovery"


@dataclass(frozen=True)
class EngineeringPlanStep:
    """One actionable step in an engineering plan."""

    step_id: str
    title: str
    objective: str

    dependencies: tuple[str, ...] = ()
    expected_evidence: tuple[str, ...] = ()
    affected_paths: tuple[str, ...] = ()

    verification: tuple[str, ...] = ()

    priority: int = 100
    risk: str = "normal"

    completed: bool = False
    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        if not self.step_id.strip():
            raise ValueError(
                "step_id must not be empty."
            )

        if not self.title.strip():
            raise ValueError(
                "Plan step title must not be empty."
            )

        if not self.objective.strip():
            raise ValueError(
                "Plan step objective must not be empty."
            )

        if self.priority < 0:
            raise ValueError(
                "priority must be non-negative."
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "title": self.title,
            "objective": self.objective,
            "dependencies": list(
                self.dependencies
            ),
            "expected_evidence": list(
                self.expected_evidence
            ),
            "affected_paths": list(
                self.affected_paths
            ),
            "verification": list(
                self.verification
            ),
            "priority": self.priority,
            "risk": self.risk,
            "completed": self.completed,
            "metadata": dict(
                self.metadata
            ),
        }

    @classmethod
    def from_dict(
        cls,
        payload: dict[str, Any],
    ) -> "EngineeringPlanStep":
        if not isinstance(
            payload,
            dict,
        ):
            raise TypeError(
                "EngineeringPlanStep payload "
                "must be a dictionary."
            )

        return cls(
            step_id=str(
                payload.get(
                    "step_id",
                    "",
                )
            ),
            title=str(
                payload.get(
                    "title",
                    "",
                )
            ),
            objective=str(
                payload.get(
                    "objective",
                    "",
                )
            ),
            dependencies=_string_tuple(
                payload.get(
                    "dependencies"
                )
            ),
            expected_evidence=_string_tuple(
                payload.get(
                    "expected_evidence"
                )
            ),
            affected_paths=_string_tuple(
                payload.get(
                    "affected_paths"
                )
            ),
            verification=_string_tuple(
                payload.get(
                    "verification"
                )
            ),
            priority=int(
                payload.get(
                    "priority",
                    100,
                )
            ),
            risk=str(
                payload.get(
                    "risk",
                    "normal",
                )
            ),
            completed=bool(
                payload.get(
                    "completed",
                    False,
                )
            ),
            metadata=dict(
                payload.get(
                    "metadata",
                    {},
                )
            ),
        )


@dataclass(frozen=True)
class PlanRevision:
    """Immutable record of a plan revision."""

    revision: int
    reason: PlanChangeReason
    explanation: str

    changed_steps: tuple[str, ...] = ()
    preserved_steps: tuple[str, ...] = ()
    removed_steps: tuple[str, ...] = ()

    evidence_ids: tuple[str, ...] = ()

    confidence: float = 0.0

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        if self.revision < 0:
            raise ValueError(
                "revision must be non-negative."
            )

        if not self.explanation.strip():
            raise ValueError(
                "Plan revision explanation must not be empty."
            )

        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                "confidence must be between 0 and 1."
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "revision": self.revision,
            "reason": self.reason.value,
            "explanation": self.explanation,
            "changed_steps": list(
                self.changed_steps
            ),
            "preserved_steps": list(
                self.preserved_steps
            ),
            "removed_steps": list(
                self.removed_steps
            ),
            "evidence_ids": list(
                self.evidence_ids
            ),
            "confidence": self.confidence,
            "metadata": dict(
                self.metadata
            ),
        }

    @classmethod
    def from_dict(
        cls,
        payload: dict[str, Any],
    ) -> "PlanRevision":
        if not isinstance(
            payload,
            dict,
        ):
            raise TypeError(
                "PlanRevision payload must be a dictionary."
            )

        try:
            reason = PlanChangeReason(
                str(
                    payload.get(
                        "reason",
                        PlanChangeReason.NEW_EVIDENCE.value,
                    )
                )
            )
        except ValueError:
            reason = PlanChangeReason.NEW_EVIDENCE

        return cls(
            revision=int(
                payload.get(
                    "revision",
                    0,
                )
            ),
            reason=reason,
            explanation=str(
                payload.get(
                    "explanation",
                    "",
                )
            ),
            changed_steps=_string_tuple(
                payload.get(
                    "changed_steps"
                )
            ),
            preserved_steps=_string_tuple(
                payload.get(
                    "preserved_steps"
                )
            ),
            removed_steps=_string_tuple(
                payload.get(
                    "removed_steps"
                )
            ),
            evidence_ids=_string_tuple(
                payload.get(
                    "evidence_ids"
                )
            ),
            confidence=float(
                payload.get(
                    "confidence",
                    0.0,
                )
            ),
            metadata=dict(
                payload.get(
                    "metadata",
                    {},
                )
            ),
        )


@dataclass
class AdaptiveEngineeringPlan:
    """Current plan plus its complete revision history."""

    plan_id: str

    objective: str

    steps: tuple[
        EngineeringPlanStep,
        ...
    ] = ()

    status: PlanStatus = PlanStatus.PROPOSED

    revision: int = 0

    assumptions: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()

    revisions: list[
        PlanRevision
    ] = field(
        default_factory=list
    )

    completed_steps: list[str] = field(
        default_factory=list
    )

    confidence: float = 0.0

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        if not self.plan_id.strip():
            raise ValueError(
                "plan_id must not be empty."
            )

        if not self.objective.strip():
            raise ValueError(
                "objective must not be empty."
            )

        if self.revision < 0:
            raise ValueError(
                "revision must be non-negative."
            )

        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                "confidence must be between 0 and 1."
            )

    # ------------------------------------------------------------------
    # Plan queries
    # ------------------------------------------------------------------

    def step(
        self,
        step_id: str,
    ) -> EngineeringPlanStep | None:
        target = str(step_id)

        for item in self.steps:
            if item.step_id == target:
                return item

        return None

    def ready_steps(
        self,
    ) -> tuple[EngineeringPlanStep, ...]:
        completed = set(
            self.completed_steps
        )

        ready: list[
            EngineeringPlanStep
        ] = []

        for step in self.steps:
            if step.step_id in completed:
                continue

            if all(
                dependency in completed
                for dependency in step.dependencies
            ):
                ready.append(step)

        return tuple(
            sorted(
                ready,
                key=lambda item: (
                    item.priority,
                    item.step_id,
                ),
            )
        )

    # ------------------------------------------------------------------
    # Progress
    # ------------------------------------------------------------------

    def mark_completed(
        self,
        step_id: str,
    ) -> None:
        target = str(step_id)

        step = self.step(
            target
        )

        if step is None:
            raise KeyError(
                f"Unknown plan step: {target}"
            )

        if target not in self.completed_steps:
            self.completed_steps.append(
                target
            )

        if all(
            item.step_id in self.completed_steps
            for item in self.steps
        ):
            self.status = PlanStatus.COMPLETED
        else:
            self.status = PlanStatus.ACTIVE

    # ------------------------------------------------------------------
    # Replanning
    # ------------------------------------------------------------------

    def revise(
        self,
        *,
        steps: Sequence[EngineeringPlanStep],
        reason: PlanChangeReason,
        explanation: str,
        evidence_ids: Sequence[str] = (),
        confidence: float | None = None,
        assumptions: Sequence[str] | None = None,
        risks: Sequence[str] | None = None,
    ) -> PlanRevision:
        """Create a new plan revision while preserving historical state."""

        new_steps = tuple(
            steps
        )

        previous_ids = {
            item.step_id
            for item in self.steps
        }

        new_ids = {
            item.step_id
            for item in new_steps
        }

        preserved = tuple(
            sorted(
                previous_ids & new_ids
            )
        )

        changed = tuple(
            sorted(
                new_ids - previous_ids
            )
        )

        removed = tuple(
            sorted(
                previous_ids - new_ids
            )
        )

        next_revision = (
            self.revision + 1
        )

        revision_record = PlanRevision(
            revision=next_revision,
            reason=reason,
            explanation=explanation,
            changed_steps=changed,
            preserved_steps=preserved,
            removed_steps=removed,
            evidence_ids=tuple(
                str(item)
                for item in evidence_ids
            ),
            confidence=(
                self.confidence
                if confidence is None
                else confidence
            ),
        )

        self.steps = new_steps
        self.revision = next_revision
        self.status = PlanStatus.REVISED

        self.revisions.append(
            revision_record
        )

        if assumptions is not None:
            self.assumptions = tuple(
                str(item)
                for item in assumptions
            )

        if risks is not None:
            self.risks = tuple(
                str(item)
                for item in risks
            )

        if confidence is not None:
            self.confidence = confidence

        # Preserve only completed steps that still exist in the revised plan.
        self.completed_steps = [
            item
            for item in self.completed_steps
            if item in new_ids
        ]

        return revision_record

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "objective": self.objective,
            "steps": [
                item.to_dict()
                for item in self.steps
            ],
            "status": self.status.value,
            "revision": self.revision,
            "assumptions": list(
                self.assumptions
            ),
            "risks": list(
                self.risks
            ),
            "revisions": [
                item.to_dict()
                for item in self.revisions
            ],
            "completed_steps": list(
                self.completed_steps
            ),
            "confidence": self.confidence,
            "metadata": dict(
                self.metadata
            ),
        }

    @classmethod
    def from_dict(
        cls,
        payload: dict[str, Any],
    ) -> "AdaptiveEngineeringPlan":
        if not isinstance(
            payload,
            dict,
        ):
            raise TypeError(
                "AdaptiveEngineeringPlan payload "
                "must be a dictionary."
            )

        try:
            status = PlanStatus(
                str(
                    payload.get(
                        "status",
                        PlanStatus.PROPOSED.value,
                    )
                )
            )
        except ValueError:
            status = PlanStatus.PROPOSED

        steps = tuple(
            EngineeringPlanStep.from_dict(
                item
            )
            for item in payload.get(
                "steps",
                [],
            )
            if isinstance(
                item,
                dict,
            )
        )

        revisions = [
            PlanRevision.from_dict(
                item
            )
            for item in payload.get(
                "revisions",
                [],
            )
            if isinstance(
                item,
                dict,
            )
        ]

        return cls(
            plan_id=str(
                payload.get(
                    "plan_id",
                    "",
                )
            ),
            objective=str(
                payload.get(
                    "objective",
                    "",
                )
            ),
            steps=steps,
            status=status,
            revision=int(
                payload.get(
                    "revision",
                    0,
                )
            ),
            assumptions=_string_tuple(
                payload.get(
                    "assumptions"
                )
            ),
            risks=_string_tuple(
                payload.get(
                    "risks"
                )
            ),
            revisions=revisions,
            completed_steps=list(
                _string_tuple(
                    payload.get(
                        "completed_steps"
                    )
                )
            ),
            confidence=float(
                payload.get(
                    "confidence",
                    0.0,
                )
            ),
            metadata=dict(
                payload.get(
                    "metadata",
                    {},
                )
            ),
        )


def _string_tuple(
    value: Any,
) -> tuple[str, ...]:
    if value is None:
        return ()

    if isinstance(
        value,
        str,
    ):
        return (value,)

    if not isinstance(
        value,
        (list, tuple, set),
    ):
        raise TypeError(
            "Expected a string or sequence of strings."
        )

    return tuple(
        str(item)
        for item in value
    )


__all__ = [
    "PlanStatus",
    "PlanChangeReason",
    "EngineeringPlanStep",
    "PlanRevision",
    "AdaptiveEngineeringPlan",
]