"""Explicit planning-only versus executable engineering mode boundary.

This component is intentionally independent from CognitiveCore. It provides a
stable contract that the final CognitiveCore integration can call once all
Phase 1-10 capabilities have been assembled.

It never executes engineering work. It only classifies the requested operating
mode and produces a safe execution decision for the authoritative orchestrator.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
import re
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class EngineeringExecutionDecision:
    """Immutable decision describing whether engineering may execute."""

    mode: str
    plan_only: bool
    execution_allowed: bool
    repository_inspection_allowed: bool
    mutation_allowed: bool
    commit_allowed: bool
    github_push_allowed: bool
    deployment_allowed: bool
    authorization_required: bool
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class EngineeringExecutionMode:
    """Deterministic safety boundary for engineering requests."""

    VERSION = "ARIA-ENGINEERING-EXECUTION-MODE-20261006"

    PLAN_ONLY_PATTERNS = (
        r"\bplan(?:\s+out)?\b",
        r"\bplanning\s+only\b",
        r"\bexplain\s+(?:the\s+)?(?:steps|phases|architecture|design)\b",
        r"\bgive\s+(?:me\s+)?(?:the\s+)?(?:steps|phases)\b",
        r"\bdesign\s+(?:the\s+)?(?:system|architecture|solution)\b",
        r"\banaly[sz]e\b(?:\s+the)?\s+(?:phases|steps|architecture|design)\b",
        r"\bplan\s+only\b",
        r"\binspect\b.*\bonly\b",
        r"\breview\b.*\bonly\b",
        r"\bwhat\s+should\s+we\s+do\b",
    )

    NO_EXECUTION_PATTERNS = (
        r"\bdo\s+not\s+(?:modify|change|edit|write|create|delete|implement|execute)\b",
        r"\bdon['’]?t\s+(?:modify|change|edit|write|create|delete|implement|execute)\b",
        r"\bwithout\s+(?:modifying|changing|editing|writing|creating|deleting|implementing|executing)\b",
        r"\bread[- ]only\b",
        r"\bno\s+(?:code|implementation|changes?|modifications?)\b",
    )

    EXECUTION_PATTERNS = (
        r"\bimplement\b",
        r"\bbuild\b",
        r"\bcreate\s+(?:the|a|an)\s+(?:file|feature|system|module|service)\b",
        r"\bfix\b",
        r"\bmodify\b",
        r"\bchange\b",
        r"\bwrite\s+(?:the|a|an)\s+(?:code|file)\b",
        r"\bdevelop\b",
        r"\brefactor\b",
    )

    AUTHORIZATION_PATTERNS = (
        r"\bauthori[sz](?:e|ed|ation)\b",
        r"\bapprove(?:d|s|)?\b",
        r"\bpermission\b",
        r"\bpush\s+to\s+(?:github|git)\b",
        r"\bdeploy\b",
    )

    def __init__(
        self,
        *,
        repository_engine: Any = None,
        readiness_gateway: Any = None,
    ) -> None:
        self.repository_engine = repository_engine
        self.readiness_gateway = readiness_gateway

    def decide(
        self,
        request: str,
        *,
        explicit_execution: Optional[bool] = None,
        authorization: Optional[bool] = None,
    ) -> EngineeringExecutionDecision:
        """Return a deterministic mode decision without executing anything."""

        if not isinstance(request, str):
            raise TypeError("request must be a string")

        text = request.strip()
        if not text:
            raise ValueError("request cannot be empty")

        lowered = text.lower()

        plan_only = self._matches(
            lowered,
            self.PLAN_ONLY_PATTERNS,
        )
        no_execution = self._matches(
            lowered,
            self.NO_EXECUTION_PATTERNS,
        )
        execution_language = self._matches(
            lowered,
            self.EXECUTION_PATTERNS,
        )
        authorization_language = self._matches(
            lowered,
            self.AUTHORIZATION_PATTERNS,
        )

        if explicit_execution is True:
            requested_execution = True
        elif explicit_execution is False:
            requested_execution = False
        else:
            requested_execution = execution_language

        if plan_only or no_execution:
            requested_execution = False

        authorized = (
            bool(authorization)
            if authorization is not None
            else authorization_language
        )

        if plan_only:
            return EngineeringExecutionDecision(
                mode="plan_only",
                plan_only=True,
                execution_allowed=False,
                repository_inspection_allowed=True,
                mutation_allowed=False,
                commit_allowed=False,
                github_push_allowed=False,
                deployment_allowed=False,
                authorization_required=False,
                reason="The request asks for planning, explanation, analysis, or phases only.",
            )

        if no_execution:
            return EngineeringExecutionDecision(
                mode="inspect_only",
                plan_only=False,
                execution_allowed=False,
                repository_inspection_allowed=True,
                mutation_allowed=False,
                commit_allowed=False,
                github_push_allowed=False,
                deployment_allowed=False,
                authorization_required=False,
                reason="The request explicitly prohibits implementation or mutation.",
            )

        if requested_execution:
            return EngineeringExecutionDecision(
                mode="execute",
                plan_only=False,
                execution_allowed=True,
                repository_inspection_allowed=True,
                mutation_allowed=True,
                commit_allowed=False,
                github_push_allowed=False,
                deployment_allowed=False,
                authorization_required=not authorized,
                reason=(
                    "Engineering execution is requested; repository inspection is allowed, "
                    "but GitHub push and deployment remain separately authorization-gated."
                ),
            )

        return EngineeringExecutionDecision(
            mode="answer_or_research",
            plan_only=False,
            execution_allowed=False,
            repository_inspection_allowed=True,
            mutation_allowed=False,
            commit_allowed=False,
            github_push_allowed=False,
            deployment_allowed=False,
            authorization_required=False,
            reason="No explicit engineering execution request was detected.",
        )

    def health(self) -> Dict[str, Any]:
        return {
            "healthy": True,
            "version": self.VERSION,
            "read_only_decision_layer": True,
            "repository_engine_connected": self.repository_engine is not None,
            "readiness_gateway_connected": self.readiness_gateway is not None,
            "github_push_default": False,
            "deployment_default": False,
        }

    @staticmethod
    def _matches(text: str, patterns: tuple[str, ...]) -> bool:
        return any(re.search(pattern, text, re.IGNORECASE | re.DOTALL) for pattern in patterns)


__all__ = [
    "EngineeringExecutionDecision",
    "EngineeringExecutionMode",
]
