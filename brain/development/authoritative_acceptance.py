from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .contracts.engineering_acceptance import (
    AcceptanceCriterion,
    AcceptanceCriterionStatus,
    AcceptanceDecision,
    AcceptanceDecisionResult,
    AcceptanceFinding,
    AcceptanceRequest,
    AcceptanceStatus,
)


class AuthoritativeAcceptanceEngine:
    """
    Final engineering judgment boundary.

    This engine deliberately does NOT equate:
        tests passed == requirement satisfied

    Acceptance requires the original requirement, acceptance criteria,
    implementation evidence, verification evidence, and constraints
    to agree.

    It is intentionally deterministic at this layer. Higher-level
    reasoning may supply richer evidence, but cannot bypass these
    acceptance invariants.
    """

    def __init__(
        self,
        *,
        judgment_engine: Any | None = None,
        verification_engine: Any | None = None,
    ) -> None:
        self.judgment_engine = judgment_engine
        self.verification_engine = verification_engine

    def evaluate(
        self,
        request: AcceptanceRequest,
    ) -> AcceptanceDecisionResult:
        """
        Evaluate whether the engineering requirement is genuinely satisfied.
        """
        criteria = tuple(request.criteria)

        if not request.requirement.strip():
            return self._blocked(
                "Cannot evaluate acceptance without the original requirement.",
                "Restore the original requirement before acceptance.",
            )

        if not request.objective.strip():
            return self._blocked(
                "Cannot evaluate acceptance without an engineering objective.",
                "Restore the engineering objective before acceptance.",
            )

        if not criteria:
            return self._evaluate_without_explicit_criteria(request)

        return self._evaluate_criteria(request, criteria)

    def accept(
        self,
        request: AcceptanceRequest,
    ) -> AcceptanceDecisionResult:
        return self.evaluate(request)

    def _evaluate_criteria(
        self,
        request: AcceptanceRequest,
        criteria: tuple[AcceptanceCriterion, ...],
    ) -> AcceptanceDecisionResult:
        findings: list[AcceptanceFinding] = []
        evaluated: list[AcceptanceCriterion] = []
        missing_evidence: list[str] = []
        violated_constraints: list[str] = []

        verification_status = (
            str(request.verification_status or "unknown").strip().lower()
        )

        for criterion in criteria:
            result = self._evaluate_criterion(
                criterion,
                request=request,
                verification_status=verification_status,
            )

            evaluated.append(result["criterion"])
            findings.append(result["finding"])
            missing_evidence.extend(result["missing_evidence"])

        violated_constraints.extend(
            self._find_constraint_violations(request)
        )

        required_unsatisfied = [
            criterion
            for criterion in evaluated
            if criterion.required
            and criterion.status
            == AcceptanceCriterionStatus.UNSATISFIED
        ]

        required_unknown = [
            criterion
            for criterion in evaluated
            if criterion.required
            and criterion.status
            in (
                AcceptanceCriterionStatus.UNKNOWN,
                AcceptanceCriterionStatus.INCONCLUSIVE,
            )
        ]

        if violated_constraints:
            return AcceptanceDecisionResult(
                status=AcceptanceStatus.REJECTED,
                decision=AcceptanceDecision.REPAIR,
                confidence=0.98,
                criterion_results=tuple(evaluated),
                findings=tuple(findings),
                missing_evidence=tuple(dict.fromkeys(missing_evidence)),
                violated_constraints=tuple(
                    dict.fromkeys(violated_constraints)
                ),
                next_actions=(
                    "Repair the constraint violation.",
                    "Re-run verification after repair.",
                    "Re-evaluate acceptance against the original requirement.",
                ),
                rationale=(
                    "The implementation cannot be accepted because one or "
                    "more explicit engineering constraints were violated."
                ),
            )

        if required_unsatisfied:
            return AcceptanceDecisionResult(
                status=AcceptanceStatus.REJECTED,
                decision=AcceptanceDecision.REPAIR,
                confidence=0.97,
                criterion_results=tuple(evaluated),
                findings=tuple(findings),
                missing_evidence=tuple(dict.fromkeys(missing_evidence)),
                next_actions=(
                    "Repair the unsatisfied acceptance criteria.",
                    "Run targeted verification.",
                    "Retest affected behavior.",
                    "Re-evaluate acceptance.",
                ),
                rationale=(
                    "One or more required acceptance criteria are "
                    "explicitly unsatisfied."
                ),
            )

        if required_unknown:
            return AcceptanceDecisionResult(
                status=AcceptanceStatus.INCONCLUSIVE,
                decision=AcceptanceDecision.REVERIFY,
                confidence=0.90,
                criterion_results=tuple(evaluated),
                findings=tuple(findings),
                missing_evidence=tuple(dict.fromkeys(missing_evidence)),
                next_actions=(
                    "Gather the missing evidence.",
                    "Run the narrowest verification that can distinguish "
                    "the remaining uncertainty.",
                    "Re-evaluate acceptance.",
                ),
                rationale=(
                    "The available evidence is insufficient to prove every "
                    "required acceptance criterion."
                ),
            )

        if verification_status in {
            "failed",
            "blocked",
        }:
            return AcceptanceDecisionResult(
                status=AcceptanceStatus.REJECTED,
                decision=AcceptanceDecision.REPAIR,
                confidence=0.96,
                criterion_results=tuple(evaluated),
                findings=tuple(findings),
                missing_evidence=tuple(dict.fromkeys(missing_evidence)),
                next_actions=(
                    "Diagnose the verification failure.",
                    "Repair the root cause.",
                    "Retest.",
                    "Re-evaluate acceptance.",
                ),
                rationale=(
                    "The acceptance criteria may appear satisfied, but "
                    "verification evidence contains a blocking failure."
                ),
            )

        return AcceptanceDecisionResult(
            status=AcceptanceStatus.ACCEPTED,
            decision=AcceptanceDecision.ACCEPT,
            confidence=self._acceptance_confidence(
                evaluated,
                verification_status,
            ),
            criterion_results=tuple(evaluated),
            findings=tuple(findings),
            missing_evidence=tuple(dict.fromkeys(missing_evidence)),
            next_actions=(),
            rationale=(
                "All required acceptance criteria are satisfied and the "
                "available engineering evidence contains no blocking "
                "constraint or verification failure."
            ),
        )

    def _evaluate_criterion(
        self,
        criterion: AcceptanceCriterion,
        *,
        request: AcceptanceRequest,
        verification_status: str,
    ) -> dict[str, Any]:
        existing_status = criterion.status

        evidence_ids = tuple(criterion.evidence_ids)
        verification_ids = tuple(criterion.verification_ids)

        evidence_text = self._collect_evidence_text(
            request.evidence,
            request.verification_findings,
        )

        criterion_text = criterion.description.lower()
        combined = f"{criterion_text}\n{evidence_text}".lower()

        explicit_failure = self._contains_failure_signal(combined)
        explicit_success = self._contains_success_signal(combined)

        if existing_status == AcceptanceCriterionStatus.SATISFIED:
            status = AcceptanceCriterionStatus.SATISFIED

        elif existing_status == AcceptanceCriterionStatus.UNSATISFIED:
            status = AcceptanceCriterionStatus.UNSATISFIED

        elif existing_status == AcceptanceCriterionStatus.INCONCLUSIVE:
            status = AcceptanceCriterionStatus.INCONCLUSIVE

        elif verification_status in {"failed", "blocked"}:
            status = AcceptanceCriterionStatus.INCONCLUSIVE

        elif explicit_failure:
            status = AcceptanceCriterionStatus.UNSATISFIED

        elif explicit_success:
            status = AcceptanceCriterionStatus.SATISFIED

        elif evidence_ids or verification_ids:
            status = AcceptanceCriterionStatus.INCONCLUSIVE

        else:
            status = AcceptanceCriterionStatus.UNKNOWN

        missing: list[str] = []

        if status in {
            AcceptanceCriterionStatus.UNKNOWN,
            AcceptanceCriterionStatus.INCONCLUSIVE,
        }:
            missing.append(
                f"Evidence proving criterion '{criterion.criterion_id}' "
                f"({criterion.description})"
            )

        updated = criterion.with_status(
            status,
            evidence_ids=evidence_ids,
            verification_ids=verification_ids,
            notes=criterion.notes,
        )

        severity = "info"

        if status == AcceptanceCriterionStatus.UNSATISFIED:
            severity = "error"
        elif status in {
            AcceptanceCriterionStatus.UNKNOWN,
            AcceptanceCriterionStatus.INCONCLUSIVE,
        }:
            severity = "warning"

        finding = AcceptanceFinding(
            finding_id=f"acceptance-{criterion.criterion_id}",
            criterion_id=criterion.criterion_id,
            status=status,
            statement=self._criterion_statement(
                criterion,
                status,
            ),
            evidence_ids=evidence_ids,
            verification_ids=verification_ids,
            severity=severity,
            confidence=self._criterion_confidence(status),
        )

        return {
            "criterion": updated,
            "finding": finding,
            "missing_evidence": missing,
        }

    def _evaluate_without_explicit_criteria(
        self,
        request: AcceptanceRequest,
    ) -> AcceptanceDecisionResult:
        """
        Do not fabricate acceptance criteria.

        If the caller supplied no criteria, acceptance is only possible when
        a trusted upstream judgment engine explicitly establishes them.
        """
        if self.judgment_engine is None:
            return AcceptanceDecisionResult(
                status=AcceptanceStatus.BLOCKED,
                decision=AcceptanceDecision.BLOCK,
                confidence=0.98,
                criterion_results=(),
                findings=(
                    AcceptanceFinding(
                        finding_id="acceptance-missing-criteria",
                        criterion_id=None,
                        status=AcceptanceCriterionStatus.UNKNOWN,
                        statement=(
                            "No explicit acceptance criteria were supplied "
                            "and no trusted judgment engine is available "
                            "to derive them."
                        ),
                        severity="error",
                        confidence=0.98,
                    ),
                ),
                missing_evidence=(
                    "Explicit acceptance criteria.",
                ),
                next_actions=(
                    "Derive acceptance criteria from the original requirement "
                    "using a trusted engineering reasoning component.",
                    "Verify each criterion independently.",
                    "Re-evaluate acceptance.",
                ),
                rationale=(
                    "Acceptance cannot be proven safely without explicit "
                    "criteria or a trusted mechanism for deriving them."
                ),
            )

        derived = self._derive_criteria(request)

        if not derived:
            return AcceptanceDecisionResult(
                status=AcceptanceStatus.BLOCKED,
                decision=AcceptanceDecision.BLOCK,
                confidence=0.96,
                missing_evidence=(
                    "Explicit acceptance criteria.",
                ),
                next_actions=(
                    "Derive concrete acceptance criteria.",
                    "Verify the criteria.",
                ),
                rationale=(
                    "The available judgment component did not produce "
                    "verifiable acceptance criteria."
                ),
            )

        derived_request = AcceptanceRequest(
            session_id=request.session_id,
            requirement=request.requirement,
            objective=request.objective,
            criteria=tuple(derived),
            verification_status=request.verification_status,
            verification_findings=request.verification_findings,
            evidence=request.evidence,
            implementation_summary=request.implementation_summary,
            changed_paths=request.changed_paths,
            protected_paths=request.protected_paths,
            workspace_id=request.workspace_id,
            constraints=request.constraints,
            forbidden_actions=request.forbidden_actions,
            metadata=request.metadata,
        )

        result = self._evaluate_criteria(
            derived_request,
            tuple(derived),
        )

        return result

    def _derive_criteria(
        self,
        request: AcceptanceRequest,
    ) -> list[AcceptanceCriterion]:
        engine = self.judgment_engine

        candidates: Any = None

        for method_name in (
            "derive_acceptance_criteria",
            "build_acceptance_criteria",
            "evaluate_requirement",
        ):
            method = getattr(engine, method_name, None)

            if not callable(method):
                continue

            try:
                candidates = method(
                    requirement=request.requirement,
                    objective=request.objective,
                    metadata=dict(request.metadata),
                )
            except TypeError:
                try:
                    candidates = method(request.requirement)
                except Exception:
                    continue
            except Exception:
                continue

            if candidates is not None:
                break

        if candidates is None:
            return []

        if isinstance(candidates, AcceptanceCriterion):
            return [candidates]

        if isinstance(candidates, Mapping):
            candidates = candidates.get(
                "criteria",
                candidates.get("acceptance_criteria", []),
            )

        if not isinstance(candidates, Iterable) or isinstance(
            candidates,
            (str, bytes),
        ):
            return []

        result: list[AcceptanceCriterion] = []

        for index, item in enumerate(candidates, start=1):
            if isinstance(item, AcceptanceCriterion):
                result.append(item)
                continue

            if isinstance(item, Mapping):
                description = str(
                    item.get("description")
                    or item.get("criterion")
                    or item.get("text")
                    or ""
                ).strip()

                if not description:
                    continue

                result.append(
                    AcceptanceCriterion(
                        criterion_id=str(
                            item.get(
                                "criterion_id",
                                f"derived-{index}",
                            )
                        ),
                        description=description,
                        required=bool(item.get("required", True)),
                    )
                )

        return result

    def _find_constraint_violations(
        self,
        request: AcceptanceRequest,
    ) -> list[str]:
        violations: list[str] = []

        changed = set(request.changed_paths)
        protected = set(request.protected_paths)

        protected_hits = sorted(changed & protected)

        for path in protected_hits:
            violations.append(
                f"Protected path was modified: {path}"
            )

        implementation_text = (
            f"{request.implementation_summary}\n"
            f"{self._collect_evidence_text(request.evidence, ())}"
        ).lower()

        for forbidden in request.forbidden_actions:
            if forbidden.strip().lower() in implementation_text:
                violations.append(
                    f"Forbidden action appears in implementation evidence: "
                    f"{forbidden}"
                )

        return violations

    @staticmethod
    def _collect_evidence_text(
        evidence: Iterable[Mapping[str, Any]],
        verification_findings: Iterable[Mapping[str, Any]],
    ) -> str:
        parts: list[str] = []

        for item in list(evidence) + list(verification_findings):
            if not isinstance(item, Mapping):
                continue

            for key in (
                "statement",
                "summary",
                "message",
                "stdout",
                "stderr",
                "diagnostics",
                "result",
                "status",
                "rationale",
            ):
                value = item.get(key)

                if value is None:
                    continue

                if isinstance(value, (list, tuple)):
                    parts.extend(str(value_item) for value_item in value)
                elif isinstance(value, Mapping):
                    parts.append(str(dict(value)))
                else:
                    parts.append(str(value))

        return "\n".join(parts)

    @staticmethod
    def _contains_failure_signal(text: str) -> bool:
        signals = (
            "failed",
            "failure",
            "error",
            "exception",
            "traceback",
            "assertionerror",
            "not satisfied",
            "unsatisfied",
            "blocked",
        )

        return any(signal in text for signal in signals)

    @staticmethod
    def _contains_success_signal(text: str) -> bool:
        signals = (
            "passed",
            "success",
            "satisfied",
            "verified",
            "verified successfully",
            "implemented successfully",
            "accepted",
        )

        return any(signal in text for signal in signals)

    @staticmethod
    def _criterion_statement(
        criterion: AcceptanceCriterion,
        status: AcceptanceCriterionStatus,
    ) -> str:
        if status == AcceptanceCriterionStatus.SATISFIED:
            return (
                f"Acceptance criterion '{criterion.criterion_id}' is "
                f"satisfied: {criterion.description}"
            )

        if status == AcceptanceCriterionStatus.UNSATISFIED:
            return (
                f"Acceptance criterion '{criterion.criterion_id}' is "
                f"not satisfied: {criterion.description}"
            )

        if status == AcceptanceCriterionStatus.INCONCLUSIVE:
            return (
                f"Acceptance criterion '{criterion.criterion_id}' cannot "
                f"yet be proven: {criterion.description}"
            )

        return (
            f"Acceptance criterion '{criterion.criterion_id}' has not "
            f"yet been established: {criterion.description}"
        )

    @staticmethod
    def _criterion_confidence(
        status: AcceptanceCriterionStatus,
    ) -> float:
        return {
            AcceptanceCriterionStatus.SATISFIED: 0.92,
            AcceptanceCriterionStatus.UNSATISFIED: 0.95,
            AcceptanceCriterionStatus.INCONCLUSIVE: 0.85,
            AcceptanceCriterionStatus.UNKNOWN: 0.90,
            AcceptanceCriterionStatus.NOT_APPLICABLE: 0.90,
        }.get(status, 0.0)

    @staticmethod
    def _acceptance_confidence(
        criteria: list[AcceptanceCriterion],
        verification_status: str,
    ) -> float:
        if not criteria:
            return 0.0

        base = min(
            AuthoritativeAcceptanceEngine._criterion_confidence(
                criterion.status
            )
            for criterion in criteria
        )

        if verification_status == "passed":
            return min(0.99, base + 0.04)

        return base

    @staticmethod
    def _blocked(
        rationale: str,
        action: str,
    ) -> AcceptanceDecisionResult:
        return AcceptanceDecisionResult(
            status=AcceptanceStatus.BLOCKED,
            decision=AcceptanceDecision.BLOCK,
            confidence=0.99,
            next_actions=(action,),
            rationale=rationale,
        )