from __future__ import annotations

"""
Canonical Phase 1 engineering request router.

This module is a routing boundary only. It does not implement a second
engineering lifecycle.

Canonical executable path:

    CognitiveCore
        -> EngineeringRequestRouter
        -> Phase1PersistentRuntimeAdapter
        -> FinalAutonomousEngineer
        -> AuthoritativeEngineeringOrchestrator
"""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EngineeringRequestClassification:
    is_engineering: bool
    is_read_only: bool
    confidence: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_engineering": self.is_engineering,
            "is_read_only": self.is_read_only,
            "confidence": self.confidence,
            "reason": self.reason,
        }


class EngineeringRequestRouter:
    """Route software-engineering requests to the canonical Phase 1 runtime."""

    ENGINEERING_TERMS = (
        "code",
        "coding",
        "program",
        "programming",
        "software",
        "repository",
        "repo",
        "github",
        "git",
        "implement",
        "implementation",
        "develop",
        "development",
        "developer",
        "build",
        "bug",
        "debug",
        "debugging",
        "fix the error",
        "fix error",
        "fix the bug",
        "refactor",
        "refactoring",
        "feature",
        "functionality",
        "api",
        "backend",
        "frontend",
        "architecture",
        "deployment",
        "deploy",
        "test the code",
        "write code",
        "modify the code",
        "change the code",
        "create a file",
        "modify a file",
        "delete a file",
        "autonomous engineering",
        "engineering lifecycle",
        "engineering task",
    )

    SOFTWARE_INTENTS = {
        "software_development",
        "coding",
        "programming",
        "development",
        "engineering",
        "software_engineering",
        "repository_engineering",
    }

    READ_ONLY_TERMS = (
        "read only",
        "read-only",
        "readonly",
        "only inspect",
        "inspect only",
        "just inspect",
        "only analyze",
        "analyze only",
        "analysis only",
        "do not create",
        "don't create",
        "do not modify",
        "don't modify",
        "do not change",
        "don't change",
        "do not delete",
        "don't delete",
        "do not commit",
        "don't commit",
        "do not push",
        "don't push",
        "do not deploy",
        "don't deploy",
        "without modifying",
        "without changes",
        "without changing",
        "without creating",
        "without deleting",
        "without committing",
        "without pushing",
        "without deploying",
        "no modifications",
        "no changes",
    )

    def __init__(self, runtime: Any = None) -> None:
        self.runtime = runtime

    def classify(
        self,
        query: str,
        *,
        intent: Any = None,
        decision: Any = None,
    ) -> EngineeringRequestClassification:
        text = str(query or "").strip().lower()

        if not text:
            return EngineeringRequestClassification(
                is_engineering=False,
                is_read_only=False,
                confidence=0.0,
                reason="empty_request",
            )

        intent_name = self._intent_name(intent)

        if not intent_name:
            intent_name = self._intent_name(
                self._decision_value(decision, "intent")
            )

        route_name = str(
            self._decision_value(decision, "route", "") or ""
        ).strip().lower()

        action_name = str(
            self._decision_value(decision, "action", "") or ""
        ).strip().lower()

        if (
            intent_name in self.SOFTWARE_INTENTS
            or route_name in self.SOFTWARE_INTENTS
            or action_name in {
                "coding",
                "development",
                "software_development",
                "engineering",
            }
        ):
            engineering = True
            confidence = 0.99
            reason = "software_development_decision"
        else:
            matches = [
                term
                for term in self.ENGINEERING_TERMS
                if term in text
            ]

            engineering = bool(matches)

            if len(matches) >= 3:
                confidence = 0.98
            elif len(matches) == 2:
                confidence = 0.95
            elif len(matches) == 1:
                confidence = 0.90
            else:
                confidence = 0.0

            reason = (
                "engineering_keywords"
                if engineering
                else "non_engineering_request"
            )

        read_only_matches = [
            term
            for term in self.READ_ONLY_TERMS
            if term in text
        ]

        is_read_only = bool(
            engineering and read_only_matches
        )

        if is_read_only:
            reason = "explicit_read_only_constraint"

        return EngineeringRequestClassification(
            is_engineering=engineering,
            is_read_only=is_read_only,
            confidence=confidence,
            reason=reason,
        )

    async def route(
        self,
        query: str,
        *,
        session_id: str = "",
        user_id: str = "",
        metadata: dict[str, Any] | None = None,
        intent: Any = None,
        decision: Any = None,
        **kwargs: Any,
    ) -> Any:
        classification = self.classify(
            query,
            intent=intent,
            decision=decision,
        )

        if not classification.is_engineering:
            return None

        if classification.is_read_only:
            return {
                "success": True,
                "handled": False,
                "read_only": True,
                "requires_readiness_gateway": True,
                "classification": classification.to_dict(),
                "message": (
                    "This engineering request is read-only. "
                    "No implementation lifecycle was started."
                ),
            }

        runtime = self.runtime

        if runtime is None:
            raise RuntimeError(
                "Canonical Phase 1 runtime is not available."
            )

        develop = getattr(runtime, "develop", None)

        if not callable(develop):
            raise RuntimeError(
                "Canonical Phase 1 runtime does not expose develop()."
            )

        request_metadata = dict(metadata or {})
        request_metadata.setdefault("source", "cognitive_core")
        request_metadata.setdefault("engineering_router", "canonical")
        request_metadata.setdefault(
            "engineering_classification",
            classification.to_dict(),
        )

        result = await develop(
            query,
            session_id=session_id or None,
            metadata=request_metadata,
            user_id=user_id,
            **kwargs,
        )

        return {
            "success": True,
            "handled": True,
            "read_only": False,
            "classification": classification.to_dict(),
            "result": result,
        }

    @staticmethod
    def _intent_name(value: Any) -> str:
        if value is None:
            return ""

        if isinstance(value, str):
            return value.strip().lower()

        name = getattr(value, "name", None)
        if name is None:
            name = getattr(value, "intent", None)

        if name is None:
            return ""

        return str(name).strip().lower()

    @staticmethod
    def _decision_value(
        decision: Any,
        key: str,
        default: Any = None,
    ) -> Any:
        if decision is None:
            return default

        if isinstance(decision, dict):
            return decision.get(key, default)

        return getattr(decision, key, default)


__all__ = [
    "EngineeringRequestClassification",
    "EngineeringRequestRouter",
]
