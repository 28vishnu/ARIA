from __future__ import annotations

import hashlib
from collections.abc import Iterable
from typing import Any

from .contracts.self_modification import (
    SelfModificationAction,
    SelfModificationConstraint,
    SelfModificationDecision,
    SelfModificationKind,
    SelfModificationPlan,
    SelfModificationRequest,
    SelfModificationRisk,
    SelfModificationRollback,
    SelfModificationScope,
    SelfModificationStatus,
    SelfModificationTarget,
    SelfModificationVerification,
)


class AuthoritativeSelfModificationPlanner:
    """
    Plans modifications to ARIA itself.

    This component is deliberately a planning boundary.

    It does NOT:
        - write files
        - execute generated code
        - commit code
        - push GitHub
        - deploy
        - restart production
        - bypass permissions

    Those capabilities are integrated only by later phases.
    """

    DEFAULT_PROTECTED_PATTERNS = (
        ".env",
        ".env.",
        "*.pem",
        "*.key",
        "*.crt",
        "secrets/",
        "credentials/",
        ".git/",
        ".github/workflows/",
    )

    HIGH_RISK_PATTERNS = (
        "core/bootstrap.py",
        "main.py",
        "brain/integration/",
        "brain/development/",
        "security/",
        "permissions/",
        "deployment/",
    )

    CRITICAL_PATTERNS = (
        "core/bootstrap.py",
        ".github/workflows/",
        "security/",
        "permissions/",
    )

    def __init__(
        self,
        *,
        repository_model: Any | None = None,
        reasoning_engine: Any | None = None,
        protected_paths: Iterable[str] = (),
    ) -> None:
        self.repository_model = repository_model
        self.reasoning_engine = reasoning_engine

        self.protected_paths = tuple(
            dict.fromkeys(
                (
                    *self.DEFAULT_PROTECTED_PATTERNS,
                    *tuple(protected_paths),
                )
            )
        )

    def plan(
        self,
        request: SelfModificationRequest,
    ) -> SelfModificationDecision:
        if not request.session_id.strip():
            return self._blocked(
                "Self-modification requires a session_id."
            )

        if not request.requirement.strip():
            return self._blocked(
                "Self-modification requires the original requirement."
            )

        if not request.objective.strip():
            return self._blocked(
                "Self-modification requires an engineering objective."
            )

        kind = self._classify_kind(request)
        targets = self._identify_targets(request)

        risk = self._calculate_risk(
            request=request,
            targets=targets,
            kind=kind,
        )

        scope = self._calculate_scope(targets)

        blockers = self._find_blockers(
            request=request,
            targets=targets,
        )

        warnings = self._find_warnings(
            request=request,
            targets=targets,
            risk=risk,
        )

        constraints = self._build_constraints(
            request=request,
            targets=targets,
        )

        verification = self._build_verification(
            request=request,
            targets=targets,
            kind=kind,
        )

        rollback = self._build_rollback(
            request=request,
            risk=risk,
        )

        confidence = self._calculate_confidence(
            request=request,
            targets=targets,
            blockers=blockers,
        )

        plan = SelfModificationPlan(
            plan_id=self._plan_id(request),
            session_id=request.session_id,
            requirement=request.requirement,
            objective=request.objective,
            kind=kind,
            scope=scope,
            risk=risk,
            status=(
                SelfModificationStatus.BLOCKED
                if blockers
                else SelfModificationStatus.READY
            ),
            targets=tuple(targets),
            constraints=tuple(constraints),
            verification=tuple(verification),
            rollback=tuple(rollback),
            rationale=self._build_rationale(
                request=request,
                kind=kind,
                scope=scope,
                risk=risk,
                targets=targets,
            ),
            assumptions=self._build_assumptions(
                request,
                targets,
            ),
            risks=tuple(warnings),
            expected_benefits=self._expected_benefits(
                request,
                kind,
            ),
            dependencies=self._dependencies(
                targets
            ),
            forbidden_paths=tuple(
                self.protected_paths
            ),
            approval_required=True,
            confidence=confidence,
        )

        if blockers:
            return SelfModificationDecision(
                status=SelfModificationStatus.BLOCKED,
                action=SelfModificationAction.BLOCK,
                risk=risk,
                scope=scope,
                confidence=confidence,
                rationale=(
                    "The self-modification plan cannot safely proceed "
                    "because one or more blocking conditions exist."
                ),
                plan=plan,
                blockers=tuple(blockers),
                warnings=tuple(warnings),
                required_approvals=self._required_approvals(
                    risk
                ),
                next_actions=(
                    "Resolve the blockers.",
                    "Reassess the self-modification plan.",
                ),
            )

        if risk in {
            SelfModificationRisk.HIGH,
            SelfModificationRisk.CRITICAL,
        }:
            return SelfModificationDecision(
                status=SelfModificationStatus.READY,
                action=SelfModificationAction.REQUEST_APPROVAL,
                risk=risk,
                scope=scope,
                confidence=confidence,
                rationale=(
                    "The self-modification is technically plan-ready, "
                    "but its risk requires an explicit authorization "
                    "decision before implementation."
                ),
                plan=plan,
                warnings=tuple(warnings),
                required_approvals=self._required_approvals(
                    risk
                ),
                next_actions=(
                    "Obtain the required approval.",
                    "Create an isolated engineering workspace.",
                    "Implement only the approved plan.",
                    "Run all required verification.",
                ),
            )

        return SelfModificationDecision(
            status=SelfModificationStatus.READY,
            action=SelfModificationAction.IMPLEMENT,
            risk=risk,
            scope=scope,
            confidence=confidence,
            rationale=(
                "The self-modification has a coherent scope, explicit "
                "constraints, verification strategy, and rollback plan."
            ),
            plan=plan,
            warnings=tuple(warnings),
            required_approvals=self._required_approvals(
                risk
            ),
            next_actions=(
                "Create an isolated engineering workspace.",
                "Implement only the approved targets.",
                "Run static and behavioral verification.",
                "Evaluate acceptance against the original requirement.",
            ),
        )

    def _identify_targets(
        self,
        request: SelfModificationRequest,
    ) -> list[SelfModificationTarget]:
        targets: list[SelfModificationTarget] = []

        for path in request.repository_paths:
            normalized = self._normalize_path(path)

            if not normalized:
                continue

            protected = self._is_protected(normalized)

            targets.append(
                SelfModificationTarget(
                    path=normalized,
                    reason=(
                        "Explicitly identified by the engineering request."
                    ),
                    component=self._component_for_path(
                        normalized
                    ),
                    protected=protected,
                    writable=not protected,
                    risk=self._path_risk(normalized),
                )
            )

        if not targets:
            inferred = self._infer_targets(
                request.requirement
            )

            for path in inferred:
                protected = self._is_protected(path)

                targets.append(
                    SelfModificationTarget(
                        path=path,
                        reason=(
                            "Inferred from the self-modification "
                            "requirement."
                        ),
                        component=self._component_for_path(
                            path
                        ),
                        protected=protected,
                        writable=not protected,
                        risk=self._path_risk(path),
                    )
                )

        return targets

    def _infer_targets(
        self,
        requirement: str,
    ) -> list[str]:
        lowered = requirement.lower()
        targets: list[str] = []

        if "bootstrap" in lowered:
            targets.append("core/bootstrap.py")

        if "telegram" in lowered:
            targets.append(
                "brain/integration/"
            )

        if (
            "development engine" in lowered
            or "autonomous engineer" in lowered
            or "coding engine" in lowered
        ):
            targets.append(
                "brain/development/"
            )

        if (
            "security" in lowered
            or "permission" in lowered
        ):
            targets.append(
                "security/"
            )

        if (
            "deployment" in lowered
            or "deploy" in lowered
        ):
            targets.append(
                "brain/integration/"
            )

        return list(
            dict.fromkeys(targets)
        )

    def _find_blockers(
        self,
        *,
        request: SelfModificationRequest,
        targets: list[SelfModificationTarget],
    ) -> list[str]:
        blockers: list[str] = []

        for target in targets:
            if target.protected:
                blockers.append(
                    f"Protected target requires explicit authorization: "
                    f"{target.path}"
                )

            if not target.writable:
                blockers.append(
                    f"Target is not currently writable: {target.path}"
                )

        forbidden = {
            item.strip().lower()
            for item in request.forbidden_actions
            if item.strip()
        }

        if "self-modification" in forbidden:
            blockers.append(
                "The request explicitly forbids self-modification."
            )

        return list(
            dict.fromkeys(blockers)
        )

    def _find_warnings(
        self,
        *,
        request: SelfModificationRequest,
        targets: list[SelfModificationTarget],
        risk: SelfModificationRisk,
    ) -> list[str]:
        warnings: list[str] = []

        if risk == SelfModificationRisk.CRITICAL:
            warnings.append(
                "The requested change can affect ARIA's core safety "
                "or execution boundary."
            )

        if risk == SelfModificationRisk.HIGH:
            warnings.append(
                "The requested change can affect multiple runtime "
                "components and requires stronger verification."
            )

        if not request.acceptance_criteria:
            warnings.append(
                "No explicit acceptance criteria were supplied."
            )

        if not request.protected_paths:
            warnings.append(
                "No request-specific protected paths were supplied; "
                "system protection rules remain active."
            )

        if len(targets) > 10:
            warnings.append(
                "The requested self-modification has a broad target scope."
            )

        return list(
            dict.fromkeys(warnings)
        )

    def _build_constraints(
        self,
        *,
        request: SelfModificationRequest,
        targets: list[SelfModificationTarget],
    ) -> list[SelfModificationConstraint]:
        constraints = [
            SelfModificationConstraint(
                constraint_id="isolated-workspace",
                description=(
                    "All implementation must occur inside an isolated "
                    "engineering workspace."
                ),
            ),
            SelfModificationConstraint(
                constraint_id="preserve-production",
                description=(
                    "Do not modify production state directly during "
                    "self-modification."
                ),
            ),
            SelfModificationConstraint(
                constraint_id="current-evidence-authoritative",
                description=(
                    "Historical learning cannot override current "
                    "verification evidence."
                ),
            ),
            SelfModificationConstraint(
                constraint_id="acceptance-required",
                description=(
                    "The original requirement must pass the authoritative "
                    "acceptance judgment before completion."
                ),
            ),
            SelfModificationConstraint(
                constraint_id="rollback-required",
                description=(
                    "A rollback path must exist before high-risk "
                    "self-modification is implemented."
                ),
            ),
        ]

        for constraint in request.constraints:
            constraints.append(
                SelfModificationConstraint(
                    constraint_id=(
                        "request-"
                        + hashlib.sha256(
                            constraint.encode(
                                "utf-8"
                            )
                        ).hexdigest()[:12]
                    ),
                    description=constraint,
                    source="user",
                )
            )

        protected_paths = [
            target.path
            for target in targets
            if target.protected
        ]

        if protected_paths:
            constraints.append(
                SelfModificationConstraint(
                    constraint_id="protected-targets",
                    description=(
                        "Protected targets cannot be changed without "
                        "the dedicated self-upgrade authorization flow: "
                        + ", ".join(protected_paths)
                    ),
                    source="system",
                )
            )

        return constraints

    def _build_verification(
        self,
        *,
        request: SelfModificationRequest,
        targets: list[SelfModificationTarget],
        kind: SelfModificationKind,
    ) -> list[SelfModificationVerification]:
        affected_paths = tuple(
            target.path
            for target in targets
        )

        verification = [
            SelfModificationVerification(
                verification_id="static-validation",
                description=(
                    "Statically validate all changed files and "
                    "interfaces."
                ),
                affected_paths=affected_paths,
            ),
            SelfModificationVerification(
                verification_id="targeted-tests",
                description=(
                    "Run tests directly related to the modified "
                    "components."
                ),
                affected_paths=affected_paths,
            ),
            SelfModificationVerification(
                verification_id="regression-tests",
                description=(
                    "Run relevant regression tests to detect "
                    "unintended behavioral changes."
                ),
                affected_paths=affected_paths,
            ),
            SelfModificationVerification(
                verification_id="acceptance",
                description=(
                    "Evaluate the original self-modification "
                    "requirement against authoritative acceptance "
                    "criteria."
                ),
                affected_paths=affected_paths,
            ),
        ]

        if kind in {
            SelfModificationKind.SECURITY,
            SelfModificationKind.ARCHITECTURE,
            SelfModificationKind.CAPABILITY,
            SelfModificationKind.SELF_IMPROVEMENT,
        }:
            verification.append(
                SelfModificationVerification(
                    verification_id="architecture-integrity",
                    description=(
                        "Verify that the self-modification does not "
                        "create competing state owners, bypass "
                        "permission boundaries, or break lifecycle "
                        "invariants."
                    ),
                    affected_paths=affected_paths,
                )
            )

        return verification

    def _build_rollback(
        self,
        *,
        request: SelfModificationRequest,
        risk: SelfModificationRisk,
    ) -> list[SelfModificationRollback]:
        rollback = [
            SelfModificationRollback(
                rollback_id="workspace-discard",
                description=(
                    "Discard the isolated workspace without affecting "
                    "production state."
                ),
                trigger=(
                    "Verification fails or acceptance is rejected "
                    "before approved integration."
                ),
            )
        ]

        if risk in {
            SelfModificationRisk.HIGH,
            SelfModificationRisk.CRITICAL,
        }:
            rollback.append(
                SelfModificationRollback(
                    rollback_id="integration-revert",
                    description=(
                        "Revert the integrated self-modification to "
                        "the last verified state."
                    ),
                    trigger=(
                        "Post-integration health or regression "
                        "verification fails."
                    ),
                )
            )

        return rollback

    def _calculate_risk(
        self,
        *,
        request: SelfModificationRequest,
        targets: list[SelfModificationTarget],
        kind: SelfModificationKind,
    ) -> SelfModificationRisk:
        if any(
            self._is_critical_path(target.path)
            for target in targets
        ):
            return SelfModificationRisk.CRITICAL

        if kind in {
            SelfModificationKind.SECURITY,
            SelfModificationKind.ARCHITECTURE,
            SelfModificationKind.SELF_IMPROVEMENT,
        }:
            return SelfModificationRisk.HIGH

        if any(
            target.risk == SelfModificationRisk.HIGH
            for target in targets
        ):
            return SelfModificationRisk.HIGH

        if (
            len(targets) > 5
            or len(request.repository_paths) > 5
        ):
            return SelfModificationRisk.HIGH

        if kind in {
            SelfModificationKind.CAPABILITY,
            SelfModificationKind.RELIABILITY,
        }:
            return SelfModificationRisk.MEDIUM

        return SelfModificationRisk.LOW

    @staticmethod
    def _calculate_scope(
        targets: list[SelfModificationTarget],
    ) -> SelfModificationScope:
        if not targets:
            return SelfModificationScope.LOCAL

        components = {
            target.component
            for target in targets
            if target.component
        }

        if len(targets) == 1:
            return SelfModificationScope.LOCAL

        if len(components) <= 1:
            return SelfModificationScope.COMPONENT

        if len(components) <= 3:
            return SelfModificationScope.SUBSYSTEM

        return SelfModificationScope.SYSTEM

    def _classify_kind(
        self,
        request: SelfModificationRequest,
    ) -> SelfModificationKind:
        text = (
            f"{request.requirement}\n"
            f"{request.objective}"
        ).lower()

        if "security" in text:
            return SelfModificationKind.SECURITY

        if any(
            phrase in text
            for phrase in (
                "architecture",
                "architectural",
                "redesign",
            )
        ):
            return SelfModificationKind.ARCHITECTURE

        if any(
            phrase in text
            for phrase in (
                "self improve",
                "self-improve",
                "improve itself",
                "upgrade itself",
            )
        ):
            return SelfModificationKind.SELF_IMPROVEMENT

        if any(
            phrase in text
            for phrase in (
                "new capability",
                "new capability",
                "capability",
            )
        ):
            return SelfModificationKind.CAPABILITY

        if any(
            phrase in text
            for phrase in (
                "performance",
                "faster",
                "optimize",
            )
        ):
            return SelfModificationKind.PERFORMANCE

        if any(
            phrase in text
            for phrase in (
                "reliability",
                "resilience",
                "stability",
            )
        ):
            return SelfModificationKind.RELIABILITY

        if any(
            phrase in text
            for phrase in (
                "refactor",
                "cleanup",
                "restructure",
            )
        ):
            return SelfModificationKind.REFACTOR

        if any(
            phrase in text
            for phrase in (
                "bug",
                "fix",
                "failure",
                "error",
            )
        ):
            return SelfModificationKind.BUG_FIX

        if "learning" in text:
            return SelfModificationKind.LEARNING

        return SelfModificationKind.FEATURE

    def _path_risk(
        self,
        path: str,
    ) -> SelfModificationRisk:
        if self._is_critical_path(path):
            return SelfModificationRisk.CRITICAL

        if any(
            pattern in path
            for pattern in self.HIGH_RISK_PATTERNS
        ):
            return SelfModificationRisk.HIGH

        return SelfModificationRisk.MEDIUM

    def _is_critical_path(
        self,
        path: str,
    ) -> bool:
        return any(
            pattern in path
            for pattern in self.CRITICAL_PATTERNS
        )

    def _is_protected(
        self,
        path: str,
    ) -> bool:
        normalized = self._normalize_path(path)

        if normalized.startswith(".git/"):
            return True

        if normalized.startswith(".github/workflows/"):
            return True

        if normalized in {
            ".env",
            "credentials",
            "secrets",
        }:
            return True

        for pattern in self.protected_paths:
            pattern = pattern.rstrip("/")

            if pattern.endswith("."):
                if normalized.startswith(pattern):
                    return True

            elif pattern.endswith("/"):
                if normalized.startswith(pattern):
                    return True

            elif "*" in pattern:
                prefix = pattern.split("*", 1)[0]

                if normalized.startswith(prefix):
                    return True

            elif normalized == pattern:
                return True

        return False

    @staticmethod
    def _component_for_path(
        path: str,
    ) -> str:
        parts = path.strip("/").split("/")

        if not parts:
            return "unknown"

        if len(parts) == 1:
            return parts[0]

        return "/".join(parts[:2])

    @staticmethod
    def _normalize_path(
        path: str,
    ) -> str:
        return (
            str(path)
            .strip()
            .replace("\\", "/")
            .lstrip("./")
            .rstrip("/")
        )

    @staticmethod
    def _plan_id(
        request: SelfModificationRequest,
    ) -> str:
        identity = (
            f"{request.session_id}|"
            f"{request.requirement}|"
            f"{request.objective}"
        )

        return (
            "selfmod-"
            + hashlib.sha256(
                identity.encode("utf-8")
            ).hexdigest()[:20]
        )

    @staticmethod
    def _calculate_confidence(
        *,
        request: SelfModificationRequest,
        targets: list[SelfModificationTarget],
        blockers: list[str],
    ) -> float:
        if blockers:
            return 0.20

        confidence = 0.60

        if request.repository_paths:
            confidence += 0.15

        if request.acceptance_criteria:
            confidence += 0.10

        if request.constraints:
            confidence += 0.05

        if targets:
            confidence += 0.10

        return min(0.95, confidence)

    @staticmethod
    def _build_rationale(
        *,
        request: SelfModificationRequest,
        kind: SelfModificationKind,
        scope: SelfModificationScope,
        risk: SelfModificationRisk,
        targets: list[SelfModificationTarget],
    ) -> str:
        target_text = ", ".join(
            target.path
            for target in targets
        )

        return (
            f"The requested change is classified as "
            f"{kind.value} with {scope.value} scope and "
            f"{risk.value} risk. "
            f"Relevant targets: "
            f"{target_text or 'not yet identified'}. "
            f"The plan requires isolated implementation, "
            f"verification, acceptance, and rollback protection."
        )

    @staticmethod
    def _build_assumptions(
        request: SelfModificationRequest,
        targets: list[SelfModificationTarget],
    ) -> tuple[str, ...]:
        assumptions = [
            (
                "The current repository model is sufficiently complete "
                "to reason about the requested change."
            ),
            (
                "Implementation will occur in an isolated workspace."
            ),
            (
                "Current verification evidence has higher authority "
                "than historical experience."
            ),
        ]

        if not request.repository_paths:
            assumptions.append(
                (
                    "Target paths may need to be refined after "
                    "repository inspection."
                )
            )

        if not targets:
            assumptions.append(
                (
                    "No concrete implementation target has yet been "
                    "identified."
                )
            )

        return tuple(assumptions)

    @staticmethod
    def _expected_benefits(
        request: SelfModificationRequest,
        kind: SelfModificationKind,
    ) -> tuple[str, ...]:
        benefits = [
            (
                "Satisfy the user's requested engineering objective."
            ),
            (
                "Improve ARIA's ability to perform future engineering "
                "work autonomously."
            ),
        ]

        if kind == SelfModificationKind.SELF_IMPROVEMENT:
            benefits.append(
                (
                    "Increase the capability, reliability, or reasoning "
                    "quality of ARIA itself."
                )
            )

        return tuple(benefits)

    @staticmethod
    def _dependencies(
        targets: list[SelfModificationTarget],
    ) -> tuple[str, ...]:
        dependencies: list[str] = []

        for target in targets:
            dependencies.extend(
                target.dependencies
            )

            if target.component:
                dependencies.append(
                    target.component
                )

        return tuple(
            dict.fromkeys(dependencies)
        )

    @staticmethod
    def _required_approvals(
        risk: SelfModificationRisk,
    ) -> tuple[str, ...]:
        if risk == SelfModificationRisk.CRITICAL:
            return (
                "explicit_user_authorization",
                "self_upgrade_safety_gate",
                "pre_integration_verification",
                "post_integration_health_check",
            )

        if risk == SelfModificationRisk.HIGH:
            return (
                "explicit_user_authorization",
                "self_upgrade_safety_gate",
                "pre_integration_verification",
            )

        return (
            "self_upgrade_safety_gate",
        )

    @staticmethod
    def _blocked(
        reason: str,
    ) -> SelfModificationDecision:
        return SelfModificationDecision(
            status=SelfModificationStatus.BLOCKED,
            action=SelfModificationAction.BLOCK,
            risk=SelfModificationRisk.CRITICAL,
            scope=SelfModificationScope.SYSTEM,
            confidence=0.99,
            rationale=reason,
            blockers=(reason,),
            next_actions=(
                "Correct the self-modification request.",
            ),
        )