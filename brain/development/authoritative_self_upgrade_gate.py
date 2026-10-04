from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .contracts.self_upgrade_gate import (
    SelfUpgradeGateRequest,
    SelfUpgradeGateDecision,
    UpgradeAuthority,
    UpgradeGateAction,
    UpgradeGateFinding,
    UpgradeGateStatus,
)


class AuthoritativeSelfUpgradeGate:
    """
    Safety boundary for autonomous self-upgrade.

    This component decides whether a previously created self-modification
    plan may proceed.

    It does NOT:
        - modify files
        - execute code
        - push GitHub
        - deploy
        - restart production
        - grant permissions to itself

    User authorization is never inferred from the requested change alone.
    """

    PROTECTED_ACTIONS = (
        "modify_security_boundary",
        "modify_permission_boundary",
        "modify_deployment_policy",
        "modify_git_authorization",
        "modify_user_authorization",
        "modify_secret_handling",
        "modify_core_bootstrap",
        "modify_runtime_safety",
    )

    REQUIRED_HIGH_RISK_APPROVALS = (
        "explicit_user_authorization",
        "isolated_workspace",
        "verification",
        "acceptance",
        "rollback",
    )

    REQUIRED_CRITICAL_APPROVALS = (
        "explicit_user_authorization",
        "isolated_workspace",
        "verification",
        "acceptance",
        "rollback",
        "post_integration_health_check",
    )

    def evaluate(
        self,
        request: SelfUpgradeGateRequest,
    ) -> SelfUpgradeGateDecision:
        if not request.session_id.strip():
            return self._blocked(
                "Self-upgrade gate requires a session_id."
            )

        plan = request.plan

        if not plan:
            return self._blocked(
                "Self-upgrade gate requires a self-modification plan."
            )

        findings: list[UpgradeGateFinding] = []
        blockers: list[str] = []

        risk = self._value(plan.get("risk", "high"))
        status = self._value(plan.get("status", "planned"))

        targets = self._targets(plan)
        protected_targets = self._protected_targets(
            plan,
            targets,
        )

        if protected_targets:
            findings.append(
                UpgradeGateFinding(
                    finding_id="protected-target",
                    severity="critical",
                    statement=(
                        "The self-upgrade targets a protected component: "
                        + ", ".join(protected_targets)
                    ),
                    blocking=True,
                )
            )

            blockers.append(
                "Protected components require explicit user authorization."
            )

        if status in {
            "blocked",
            "rejected",
        }:
            findings.append(
                UpgradeGateFinding(
                    finding_id="plan-status",
                    severity="critical",
                    statement=(
                        f"The self-modification plan itself is "
                        f"{status}."
                    ),
                    blocking=True,
                )
            )

            blockers.append(
                f"Self-modification plan status is {status}."
            )

        if not request.workspace_id:
            findings.append(
                UpgradeGateFinding(
                    finding_id="workspace",
                    severity="critical",
                    statement=(
                        "No isolated engineering workspace is associated "
                        "with the upgrade."
                    ),
                    blocking=True,
                )
            )

            blockers.append(
                "An isolated workspace is mandatory."
            )

        if not request.rollback_available:
            findings.append(
                UpgradeGateFinding(
                    finding_id="rollback",
                    severity="critical",
                    statement=(
                        "No verified rollback path is available."
                    ),
                    blocking=True,
                )
            )

            blockers.append(
                "A rollback path is mandatory before self-upgrade."
            )

        required_approvals = self._required_approvals(
            risk=risk,
            protected_targets=protected_targets,
        )

        authorization_result = self._evaluate_authorization(
            request.authorization,
            required_approvals,
            protected_targets,
        )

        findings.extend(
            authorization_result["findings"]
        )
        blockers.extend(
            authorization_result["blockers"]
        )

        if risk in {"high", "critical"}:
            if not request.verification_passed:
                findings.append(
                    UpgradeGateFinding(
                        finding_id="verification",
                        severity="critical",
                        statement=(
                            "Required pre-integration verification "
                            "has not passed."
                        ),
                        blocking=True,
                    )
                )

                blockers.append(
                    "Pre-integration verification must pass."
                )

            if not request.acceptance_passed:
                findings.append(
                    UpgradeGateFinding(
                        finding_id="acceptance",
                        severity="critical",
                        statement=(
                            "Authoritative acceptance has not passed."
                        ),
                        blocking=True,
                    )

                blockers.append(
                    "Authoritative acceptance must pass."
                )

        if blockers:
            return SelfUpgradeGateDecision(
                status=(
                    UpgradeGateStatus.REJECTED
                    if self._has_explicit_denial(
                        request.authorization
                    )
                    else UpgradeGateStatus.BLOCKED
                ),
                action=UpgradeGateAction.BLOCK,
                authority=self._authority(
                    request.authorization
                ),
                confidence=0.99,
                rationale=(
                    "Self-upgrade cannot proceed because one or more "
                    "safety invariants or authorization requirements "
                    "are not satisfied."
                ),
                findings=tuple(findings),
                blockers=tuple(
                    dict.fromkeys(blockers)
                ),
                required_approvals=tuple(
                    required_approvals
                ),
                permitted_actions=(),
                next_actions=(
                    "Resolve every blocking condition.",
                    "Re-evaluate the self-upgrade gate.",
                ),
            )

        if risk in {"high", "critical"}:
            return SelfUpgradeGateDecision(
                status=UpgradeGateStatus.APPROVED,
                action=UpgradeGateAction.PROCEED,
                authority=self._authority(
                    request.authorization
                ),
                confidence=0.98,
                rationale=(
                    "All required self-upgrade safety conditions and "
                    "authorization requirements are satisfied."
                ),
                findings=tuple(findings),
                required_approvals=tuple(
                    required_approvals
                ),
                permitted_actions=self._permitted_actions(
                    plan
                ),
                next_actions=(
                    "Implement only the approved plan.",
                    "Do not expand scope without re-evaluation.",
                    "Run verification after implementation.",
                    "Re-run acceptance before integration.",
                ),
            )

        return SelfUpgradeGateDecision(
            status=UpgradeGateStatus.APPROVED,
            action=UpgradeGateAction.PROCEED,
            authority=self._authority(
                request.authorization
            ),
            confidence=0.95,
            rationale=(
                "The self-upgrade satisfies the safety gate for its "
                "current risk level."
            ),
            findings=tuple(findings),
            required_approvals=tuple(
                required_approvals
            ),
            permitted_actions=self._permitted_actions(
                plan
            ),
            next_actions=(
                "Implement only the approved plan.",
                "Run verification.",
                "Evaluate acceptance.",
            ),
        )

    def _evaluate_authorization(
        self,
        authorization: Any,
        required: Iterable[str],
        protected_targets: Iterable[str],
    ) -> dict[str, Any]:
        findings: list[UpgradeGateFinding] = []
        blockers: list[str] = []

        required = tuple(required)
        protected_targets = tuple(protected_targets)

        if not required:
            return {
                "findings": findings,
                "blockers": blockers,
            }

        if authorization is None:
            findings.append(
                UpgradeGateFinding(
                    finding_id="missing-authorization",
                    severity="critical",
                    statement=(
                        "No explicit authorization was supplied for "
                        "the requested self-upgrade."
                    ),
                    blocking=True,
                )
            )

            blockers.append(
                "Explicit authorization is required."
            )

            return {
                "findings": findings,
                "blockers": blockers,
            }

        granted = self._authorization_granted(
            authorization
        )

        authority = self._value(
            self._get(
                authorization,
                "authority",
                "unknown",
            )
        )

        if not granted:
            findings.append(
                UpgradeGateFinding(
                    finding_id="authorization-denied",
                    severity="critical",
                    statement=(
                        "The supplied authorization does not grant "
                        "the requested self-upgrade."
                    ),
                    blocking=True,
                )
            )

            blockers.append(
                "Self-upgrade authorization was not granted."
            )

            return {
                "findings": findings,
                "blockers": blockers,
            }

        if authority != UpgradeAuthority.USER.value:
            findings.append(
                UpgradeGateFinding(
                    finding_id="authorization-authority",
                    severity="critical",
                    statement=(
                        "Only explicit user authorization can authorize "
                        "a high-risk or critical self-upgrade."
                    ),
                    blocking=True,
                )
            )

            blockers.append(
                "Authorization authority must be the user."
            )

        if protected_targets:
            scope = tuple(
                self._get(
                    authorization,
                    "scope",
                    (),
                )
                or ()
            )

            actions = tuple(
                self._get(
                    authorization,
                    "actions",
                    (),
                )
                or ()
            )

            for target in protected_targets:
                if not self._scope_contains(
                    scope,
                    target,
                ):
                    blockers.append(
                        "Authorization scope does not include protected "
                        f"target: {target}"
                    )

            if not any(
                action in actions
                for action in (
                    "self_upgrade",
                    "modify_protected_components",
                    "modify_aria",
                )
            ):
                blockers.append(
                    "Authorization does not explicitly permit "
                    "self-upgrade."
                )

        return {
            "findings": findings,
            "blockers": blockers,
        }

    @staticmethod
    def _authorization_granted(
        authorization: Any,
    ) -> bool:
        value = AuthoritativeSelfUpgradeGate._get(
            authorization,
            "granted",
            False,
        )

        return bool(value)

    @staticmethod
    def _required_approvals(
        *,
        risk: str,
        protected_targets: Iterable[str],
    ) -> tuple[str, ...]:
        if risk == "critical":
            return (
                *AuthoritativeSelfUpgradeGate.REQUIRED_CRITICAL_APPROVALS,
            )

        if risk == "high" or tuple(protected_targets):
            return (
                *AuthoritativeSelfUpgradeGate.REQUIRED_HIGH_RISK_APPROVALS,
            )

        return (
            "self_upgrade_safety_gate",
            "rollback",
        )

    @staticmethod
    def _protected_targets(
        plan: Mapping[str, Any],
        targets: Iterable[Any],
    ) -> list[str]:
        protected: list[str] = []

        for target in targets:
            if isinstance(target, Mapping):
                if bool(target.get("protected", False)):
                    path = str(
                        target.get("path", "")
                    )

                    if path:
                        protected.append(path)

        forbidden = plan.get(
            "forbidden_paths",
            (),
        )

        for target in targets:
            path = (
                str(target.get("path", ""))
                if isinstance(target, Mapping)
                else str(target)
            )

            for forbidden_path in forbidden or ():
                forbidden_path = str(
                    forbidden_path
                ).rstrip("/")

                if (
                    path == forbidden_path
                    or path.startswith(
                        forbidden_path + "/"
                    )
                ):
                    if path not in protected:
                        protected.append(path)

        return list(
            dict.fromkeys(protected)
        )

    @staticmethod
    def _targets(
        plan: Mapping[str, Any],
    ) -> tuple[Any, ...]:
        targets = plan.get("targets", ())

        if isinstance(targets, Mapping):
            return tuple(
                targets.values()
            )

        if isinstance(targets, (str, bytes)):
            return ()

        return tuple(targets or ())

    @staticmethod
    def _permitted_actions(
        plan: Mapping[str, Any],
    ) -> tuple[str, ...]:
        targets = AuthoritativeSelfUpgradeGate._targets(
            plan
        )

        paths = []

        for target in targets:
            if isinstance(target, Mapping):
                path = str(
                    target.get("path", "")
                )

                if path:
                    paths.append(path)

        return (
            "create_isolated_workspace",
            "modify_approved_targets",
            "run_static_validation",
            "run_targeted_tests",
            "run_regression_tests",
            "run_acceptance",
            "create_git_branch",
            "prepare_commit",
        ) + tuple(
            f"modify:{path}"
            for path in paths
        )

    @staticmethod
    def _scope_contains(
        scope: Iterable[str],
        target: str,
    ) -> bool:
        normalized_target = target.rstrip("/")

        for item in scope:
            item = str(item).rstrip("/")

            if item in {
                "*",
                "self_upgrade",
                "modify_aria",
            }:
                return True

            if (
                normalized_target == item
                or normalized_target.startswith(
                    item + "/"
                )
            ):
                return True

        return False

    @staticmethod
    def _has_explicit_denial(
        authorization: Any,
    ) -> bool:
        if authorization is None:
            return False

        return not bool(
            AuthoritativeSelfUpgradeGate._get(
                authorization,
                "granted",
                False,
            )
        )

    @staticmethod
    def _authority(
        authorization: Any,
    ) -> UpgradeAuthority:
        value = AuthoritativeSelfUpgradeGate._get(
            authorization,
            "authority",
            UpgradeAuthority.UNKNOWN.value,
        )

        try:
            return UpgradeAuthority(
                str(value)
            )
        except ValueError:
            return UpgradeAuthority.UNKNOWN

    @staticmethod
    def _value(
        value: Any,
    ) -> str:
        if hasattr(value, "value"):
            return str(value.value)

        return str(value).lower()

    @staticmethod
    def _get(
        obj: Any,
        name: str,
        default: Any = None,
    ) -> Any:
        if isinstance(obj, Mapping):
            return obj.get(name, default)

        return getattr(obj, name, default)

    @staticmethod
    def _blocked(
        reason: str,
    ) -> SelfUpgradeGateDecision:
        return SelfUpgradeGateDecision(
            status=UpgradeGateStatus.BLOCKED,
            action=UpgradeGateAction.BLOCK,
            authority=UpgradeAuthority.UNKNOWN,
            confidence=0.99,
            rationale=reason,
            blockers=(reason,),
            next_actions=(
                "Correct the self-upgrade request.",
            ),
        )