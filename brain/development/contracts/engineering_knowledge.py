"""Knowledge contracts for ARIA autonomous engineering.

Step 8 defines how ARIA represents and ranks knowledge used during engineering.

Knowledge sources are intentionally separated so:
- repository facts remain repository facts
- external research remains external research
- prior experience remains learned experience
- user requirements remain authoritative requirements

No knowledge source is allowed to silently override permissions,
repository safety, or acceptance criteria.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Sequence


class KnowledgeKind(str, Enum):
    """Canonical knowledge categories."""

    REQUIREMENT = "requirement"
    REPOSITORY = "repository"
    ARCHITECTURE = "architecture"
    DOCUMENTATION = "documentation"
    RESEARCH = "research"
    EXPERIENCE = "experience"
    TEST = "test"
    FAILURE = "failure"
    SOLUTION = "solution"
    CONSTRAINT = "constraint"


class KnowledgeAuthority(str, Enum):
    """Relative authority of a knowledge source."""

    USER = "user"
    REPOSITORY = "repository"
    EXECUTION = "execution"
    OFFICIAL_DOCUMENTATION = "official_documentation"
    EXTERNAL_RESEARCH = "external_research"
    HISTORICAL_EXPERIENCE = "historical_experience"
    INFERENCE = "inference"


@dataclass(frozen=True)
class EngineeringKnowledgeItem:
    """One auditable piece of engineering knowledge."""

    knowledge_id: str
    kind: KnowledgeKind
    authority: KnowledgeAuthority

    title: str
    content: str

    source: str = ""
    task_id: str | None = None

    paths: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()

    confidence: float = 0.0
    relevance: float = 0.0

    verified: bool = False
    stale: bool = False

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        if not self.knowledge_id.strip():
            raise ValueError(
                "knowledge_id must not be empty."
            )

        if not self.title.strip():
            raise ValueError(
                "Knowledge title must not be empty."
            )

        if not self.content.strip():
            raise ValueError(
                "Knowledge content must not be empty."
            )

        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                "confidence must be between 0 and 1."
            )

        if not 0.0 <= self.relevance <= 1.0:
            raise ValueError(
                "relevance must be between 0 and 1."
            )

    @property
    def score(self) -> float:
        """Combined usefulness score.

        Relevance dominates confidence because knowledge that is correct but
        unrelated to the current task should not control the plan.
        """

        authority_weight = {
            KnowledgeAuthority.USER: 1.00,
            KnowledgeAuthority.EXECUTION: 1.00,
            KnowledgeAuthority.REPOSITORY: 0.98,
            KnowledgeAuthority.OFFICIAL_DOCUMENTATION: 0.90,
            KnowledgeAuthority.EXTERNAL_RESEARCH: 0.75,
            KnowledgeAuthority.HISTORICAL_EXPERIENCE: 0.70,
            KnowledgeAuthority.INFERENCE: 0.45,
        }[self.authority]

        verification_weight = (
            1.0
            if self.verified
            else 0.75
        )

        stale_weight = (
            0.25
            if self.stale
            else 1.0
        )

        return (
            self.relevance
            * self.confidence
            * authority_weight
            * verification_weight
            * stale_weight
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "knowledge_id": self.knowledge_id,
            "kind": self.kind.value,
            "authority": self.authority.value,
            "title": self.title,
            "content": self.content,
            "source": self.source,
            "task_id": self.task_id,
            "paths": list(self.paths),
            "tags": list(self.tags),
            "confidence": self.confidence,
            "relevance": self.relevance,
            "score": self.score,
            "verified": self.verified,
            "stale": self.stale,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(
        cls,
        payload: dict[str, Any],
    ) -> "EngineeringKnowledgeItem":
        if not isinstance(
            payload,
            dict,
        ):
            raise TypeError(
                "EngineeringKnowledgeItem payload "
                "must be a dictionary."
            )

        try:
            kind = KnowledgeKind(
                str(
                    payload.get(
                        "kind",
                        KnowledgeKind.RESEARCH.value,
                    )
                )
            )
        except ValueError:
            kind = KnowledgeKind.RESEARCH

        try:
            authority = KnowledgeAuthority(
                str(
                    payload.get(
                        "authority",
                        KnowledgeAuthority.INFERENCE.value,
                    )
                )
            )
        except ValueError:
            authority = KnowledgeAuthority.INFERENCE

        return cls(
            knowledge_id=str(
                payload.get(
                    "knowledge_id",
                    "",
                )
            ),
            kind=kind,
            authority=authority,
            title=str(
                payload.get(
                    "title",
                    "",
                )
            ),
            content=str(
                payload.get(
                    "content",
                    "",
                )
            ),
            source=str(
                payload.get(
                    "source",
                    "",
                )
            ),
            task_id=(
                None
                if payload.get("task_id") is None
                else str(
                    payload.get("task_id")
                )
            ),
            paths=_string_tuple(
                payload.get("paths")
            ),
            tags=_string_tuple(
                payload.get("tags")
            ),
            confidence=float(
                payload.get(
                    "confidence",
                    0.0,
                )
            ),
            relevance=float(
                payload.get(
                    "relevance",
                    0.0,
                )
            ),
            verified=bool(
                payload.get(
                    "verified",
                    False,
                )
            ),
            stale=bool(
                payload.get(
                    "stale",
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
class EngineeringKnowledgeContext:
    """Knowledge assembled for one engineering decision."""

    context_id: str

    items: tuple[
        EngineeringKnowledgeItem,
        ...
    ] = ()

    query: str = ""

    repository_facts: tuple[str, ...] = ()
    research_findings: tuple[str, ...] = ()
    experience_findings: tuple[str, ...] = ()

    warnings: tuple[str, ...] = ()

    confidence: float = 0.0

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def ranked(
        self,
    ) -> tuple[EngineeringKnowledgeItem, ...]:
        """Return knowledge from strongest to weakest."""

        return tuple(
            sorted(
                self.items,
                key=lambda item: item.score,
                reverse=True,
            )
        )

    def by_kind(
        self,
        kind: KnowledgeKind,
    ) -> tuple[EngineeringKnowledgeItem, ...]:
        return tuple(
            item
            for item in self.items
            if item.kind is kind
        )

    def verified_items(
        self,
    ) -> tuple[EngineeringKnowledgeItem, ...]:
        return tuple(
            item
            for item in self.items
            if item.verified
            and not item.stale
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "context_id": self.context_id,
            "items": [
                item.to_dict()
                for item in self.items
            ],
            "query": self.query,
            "repository_facts": list(
                self.repository_facts
            ),
            "research_findings": list(
                self.research_findings
            ),
            "experience_findings": list(
                self.experience_findings
            ),
            "warnings": list(
                self.warnings
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
    ) -> "EngineeringKnowledgeContext":
        if not isinstance(
            payload,
            dict,
        ):
            raise TypeError(
                "EngineeringKnowledgeContext payload "
                "must be a dictionary."
            )

        items = tuple(
            EngineeringKnowledgeItem.from_dict(
                item
            )
            for item in payload.get(
                "items",
                [],
            )
            if isinstance(
                item,
                dict,
            )
        )

        return cls(
            context_id=str(
                payload.get(
                    "context_id",
                    "",
                )
            ),
            items=items,
            query=str(
                payload.get(
                    "query",
                    "",
                )
            ),
            repository_facts=_string_tuple(
                payload.get(
                    "repository_facts"
                )
            ),
            research_findings=_string_tuple(
                payload.get(
                    "research_findings"
                )
            ),
            experience_findings=_string_tuple(
                payload.get(
                    "experience_findings"
                )
            ),
            warnings=_string_tuple(
                payload.get(
                    "warnings"
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


class EngineeringKnowledgePolicy:
    """Rules for combining knowledge sources safely."""

    VERSION = (
        "PHASE1-ENGINEERING-KNOWLEDGE-POLICY-20261004"
    )

    @staticmethod
    def can_override(
        candidate: EngineeringKnowledgeItem,
        existing: EngineeringKnowledgeItem,
    ) -> bool:
        """Determine whether one knowledge item may outrank another."""

        authority_rank = {
            KnowledgeAuthority.USER: 100,
            KnowledgeAuthority.EXECUTION: 95,
            KnowledgeAuthority.REPOSITORY: 90,
            KnowledgeAuthority.OFFICIAL_DOCUMENTATION: 80,
            KnowledgeAuthority.EXTERNAL_RESEARCH: 60,
            KnowledgeAuthority.HISTORICAL_EXPERIENCE: 50,
            KnowledgeAuthority.INFERENCE: 20,
        }

        candidate_rank = authority_rank[
            candidate.authority
        ]

        existing_rank = authority_rank[
            existing.authority
        ]

        if candidate_rank > existing_rank:
            return True

        if candidate_rank < existing_rank:
            return False

        return candidate.score > existing.score

    @staticmethod
    def prioritize(
        items: Sequence[
            EngineeringKnowledgeItem
        ],
    ) -> tuple[
        EngineeringKnowledgeItem,
        ...
    ]:
        return tuple(
            sorted(
                items,
                key=lambda item: (
                    item.authority_rank
                    if hasattr(
                        item,
                        "authority_rank",
                    )
                    else 0,
                    item.score,
                ),
                reverse=True,
            )
        )


def _string_tuple(
    value: Any,
) -> tuple[str, ...]:
    if value is None:
        return ()

    if isinstance(value, str):
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
    "KnowledgeKind",
    "KnowledgeAuthority",
    "EngineeringKnowledgeItem",
    "EngineeringKnowledgeContext",
    "EngineeringKnowledgePolicy",
]