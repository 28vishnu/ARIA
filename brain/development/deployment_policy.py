from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass(frozen=True)
class DeploymentEvidence:
    """
    Evidence collected before a deployment decision.
    """

    tests_passed: bool = False
    validation_passed: bool = False
    staging_healthy: bool = False
    build_passed: bool = False

    confidence: float = 0.0

    risk_flags: tuple[str, ...] = ()

    protected_paths_changed: bool = False
    production_requested: bool = False
    explicit_master_approval: bool = False

    rollback_available: bool = False

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def normalized_confidence(self) -> float:
        return max(
            0.0,
            min(
                1.0,
                float(self.confidence),
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "tests_passed": self.tests_passed,
            "validation_passed": (
                self.validation_passed
            ),
            "staging_healthy": (
                self.staging_healthy
            ),
            "build_passed": self.build_passed,
            "confidence": (
                self.normalized_confidence()
            ),
            "risk_flags": list(
                self.risk_flags
            ),
            "protected_paths_changed": (
                self.protected_paths_changed
            ),
            "production_requested": (
                self.production_requested
            ),
            "explicit_master_approval": (
                self.explicit_master_approval
            ),
            "rollback_available": (
                self.rollback_available
            ),
            "metadata": dict(
                self.metadata
            ),
        }


@dataclass(frozen=True)
class DeploymentDecision:
    allowed: bool
    environment: str
    risk_level: str
    requires_approval: bool
    reasons: tuple[str, ...] = ()
    blocked_by: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "environment": self.environment,
            "risk_level": self.risk_level,
            "requires_approval": (
                self.requires_approval
            ),
            "reasons": list(
                self.reasons
            ),
            "blocked_by": list(
                self.blocked_by
            ),
        }


class DeploymentPolicy:
    """
    Determines whether ARIA may proceed with deployment.

    The policy deliberately uses multiple independent conditions.

    Confidence alone can NEVER authorize production deployment.

    Production requires:

    - successful validation
    - successful tests
    - successful build
    - healthy staging
    - rollback availability
    - no protected-path violation
    - explicit Master approval

    Low-risk staging can be autonomous when the required
    validation/build/test conditions are satisfied.
    """

    DEFAULT_HIGH_RISK_FLAGS = frozenset(
        {
            "production",
            "deployment",
            "security",
            "authentication",
            "authorization",
            "credential",
            "secret",
            "api key",
            "database",
            "github workflow",
            "protected_path",
        }
    )

    def __init__(
        self,
        *,
        autonomous_staging: bool = True,
        autonomous_production: bool = False,
        minimum_confidence: float = 0.80,
        high_risk_flags: Iterable[str] | None = None,
    ) -> None:

        if not 0.0 <= minimum_confidence <= 1.0:
            raise ValueError(
                "minimum_confidence must be between "
                "0 and 1."
            )

        self.autonomous_staging = bool(
            autonomous_staging
        )

        self.autonomous_production = bool(
            autonomous_production
        )

        self.minimum_confidence = float(
            minimum_confidence
        )

        self.high_risk_flags = {
            str(flag).strip().lower()
            for flag in (
                high_risk_flags
                or self.DEFAULT_HIGH_RISK_FLAGS
            )
        }

    def assess_risk(
        self,
        evidence: DeploymentEvidence,
    ) -> str:

        flags = {
            str(flag).strip().lower()
            for flag in evidence.risk_flags
        }

        if (
            evidence.protected_paths_changed
            or flags & self.high_risk_flags
            or evidence.production_requested
        ):
            return "high"

        if (
            not evidence.tests_passed
            or not evidence.validation_passed
            or not evidence.build_passed
        ):
            return "medium"

        if (
            evidence.confidence
            < self.minimum_confidence
        ):
            return "medium"

        return "low"

    def evaluate(
        self,
        evidence: DeploymentEvidence,
        *,
        environment: str = "staging",
    ) -> DeploymentDecision:

        environment = (
            environment.strip().lower()
        )

        if environment not in {
            "staging",
            "production",
        }:
            raise ValueError(
                "environment must be staging "
                "or production."
            )

        risk_level = self.assess_risk(
            evidence
        )

        reasons: list[str] = []
        blocked: list[str] = []

        if not evidence.validation_passed:
            blocked.append(
                "validation_failed"
            )
        else:
            reasons.append(
                "validation_passed"
            )

        if not evidence.tests_passed:
            blocked.append(
                "tests_failed"
            )
        else:
            reasons.append(
                "tests_passed"
            )

        if not evidence.build_passed:
            blocked.append(
                "build_failed"
            )
        else:
            reasons.append(
                "build_passed"
            )

        if (
            evidence.confidence
            < self.minimum_confidence
        ):
            blocked.append(
                "confidence_below_threshold"
            )
        else:
            reasons.append(
                "confidence_threshold_met"
            )

        if (
            evidence.protected_paths_changed
        ):
            blocked.append(
                "protected_paths_changed"
            )

        if environment == "staging":

            if not self.autonomous_staging:
                blocked.append(
                    "autonomous_staging_disabled"
                )

            allowed = (
                not blocked
                and risk_level != "high"
            )

            return DeploymentDecision(
                allowed=allowed,
                environment=environment,
                risk_level=risk_level,
                requires_approval=(
                    not allowed
                ),
                reasons=tuple(
                    reasons
                ),
                blocked_by=tuple(
                    blocked
                ),
            )

        # Production rules begin here.

        if not evidence.staging_healthy:
            blocked.append(
                "staging_not_healthy"
            )
        else:
            reasons.append(
                "staging_healthy"
            )

        if not evidence.rollback_available:
            blocked.append(
                "rollback_unavailable"
            )
        else:
            reasons.append(
                "rollback_available"
            )

        if not evidence.explicit_master_approval:
            blocked.append(
                "master_approval_required"
            )
        else:
            reasons.append(
                "master_approval_present"
            )

        if not self.autonomous_production:
            reasons.append(
                "autonomous_production_disabled"
            )

        # Production is never allowed solely because
        # confidence is high.
        allowed = (
            self.autonomous_production
            and not blocked
            and risk_level != "high"
        )

        return DeploymentDecision(
            allowed=allowed,
            environment=environment,
            risk_level=risk_level,
            requires_approval=(
                not allowed
            ),
            reasons=tuple(
                reasons
            ),
            blocked_by=tuple(
                blocked
            ),
        )

    def can_autonomously_stage(
        self,
        evidence: DeploymentEvidence,
    ) -> bool:

        decision = self.evaluate(
            evidence,
            environment="staging",
        )

        return decision.allowed

    def can_autonomously_produce(
        self,
        evidence: DeploymentEvidence,
    ) -> bool:

        decision = self.evaluate(
            evidence,
            environment="production",
        )

        return decision.allowed

    def explain(
        self,
        evidence: DeploymentEvidence,
        *,
        environment: str = "production",
    ) -> dict[str, Any]:

        decision = self.evaluate(
            evidence,
            environment=environment,
        )

        return {
            "decision": decision.to_dict(),
            "evidence": evidence.to_dict(),
            "policy": {
                "autonomous_staging": (
                    self.autonomous_staging
                ),
                "autonomous_production": (
                    self.autonomous_production
                ),
                "minimum_confidence": (
                    self.minimum_confidence
                ),
            },
        }