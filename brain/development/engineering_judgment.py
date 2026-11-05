from __future__ import annotations

"""ARIA Phase 1 — acceptance and engineering judgment.

This layer decides whether the evidence actually proves the requested
engineering outcome. It never writes files or executes commands.
"""

from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass(frozen=True)
class EngineeringJudgment:
    decision: str
    confidence: float
    rationale: str
    satisfied_criteria: tuple[str, ...] = ()
    missing_criteria: tuple[str, ...] = ()
    blocking_reasons: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    next_actions: tuple[str, ...] = ()
    genuine_blocker: bool = False

    @property
    def accepted(self) -> bool:
        return self.decision == "accepted"

    @property
    def requires_recovery(self) -> bool:
        return self.decision == "repair_required"

    @property
    def needs_more_evidence(self) -> bool:
        return self.decision == "needs_more_evidence"

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "satisfied_criteria": list(self.satisfied_criteria),
            "missing_criteria": list(self.missing_criteria),
            "blocking_reasons": list(self.blocking_reasons),
            "evidence": list(self.evidence),
            "next_actions": list(self.next_actions),
            "genuine_blocker": self.genuine_blocker,
        }


class EngineeringJudgmentEngine:
    """Evidence-first acceptance gate for autonomous engineering."""

    VERSION = "PHASE1-ENGINEERING-JUDGMENT-20261004"

    _BLOCKER_WORDS = (
        "permission denied",
        "credential",
        "authentication required",
        "not authorized",
        "resource exhausted",
        "out of memory",
        "network unavailable",
        "service unavailable",
        "unsatisfiable",
    )

    def judge(
        self,
        *,
        requirement: Any,
        validation: Any,
        test_result: Any | None,
        verification: Any | None,
        acceptance_error: str | None,
        generated_changes: Iterable[Any] = (),
        recovery: Any | None = None,
        task_graph: Any | None = None,
    ) -> EngineeringJudgment:
        requirement_text = str(getattr(requirement, "raw_text", requirement) or "").strip()
        validation_valid = bool(getattr(validation, "valid", False)) if validation is not None else False
        tests_ran = test_result is not None
        tests_passed = bool(getattr(test_result, "passed", False)) if tests_ran else False
        verification_sufficient = bool(getattr(verification, "sufficient", False)) if verification is not None else False
        verification_confidence = float(getattr(verification, "confidence", 0.0) or 0.0) if verification is not None else 0.0
        changes = tuple(generated_changes)
        acceptance_ok = not acceptance_error

        missing: list[str] = []
        satisfied: list[str] = []
        evidence: list[str] = []
        blockers: list[str] = []
        next_actions: list[str] = []

        if validation_valid:
            satisfied.append("repository validation")
            evidence.append("repository validation passed")
        else:
            missing.append("repository validation")
            blockers.append("repository validation has not passed")
            next_actions.append("diagnose and repair validation failures")

        if tests_ran:
            if tests_passed:
                satisfied.append("behavioral verification")
                evidence.append("selected behavioral tests passed")
            else:
                missing.append("behavioral verification")
                blockers.append("selected behavioral tests did not pass")
                next_actions.append("recover from the latest test evidence and retest")
        else:
            # Absence of tests is acceptable only when the verification layer
            # explicitly establishes that no executable behavioral test applies.
            evidence.append("no executable test result was supplied")
            if verification_sufficient and validation_valid and acceptance_ok:
                satisfied.append("non-test verification")
            else:
                missing.append("sufficient behavioral or non-test evidence")
                next_actions.append("gather the narrowest evidence that can prove the requirement")

        if acceptance_ok:
            satisfied.append("explicit acceptance checks")
            evidence.append("no exact-content acceptance failure")
        else:
            missing.append("explicit acceptance checks")
            blockers.append(str(acceptance_error))
            next_actions.append("repair the unmet acceptance condition")

        if verification_sufficient:
            satisfied.append("intelligent verification gate")
            evidence.append(f"verification confidence={verification_confidence:.2f}")
        else:
            missing.append("intelligent verification sufficiency")
            reasons = tuple(getattr(verification, "blocking_reasons", ()) or ()) if verification is not None else ()
            blockers.extend(str(item) for item in reasons)
            next_actions.append("obtain stronger requirement-specific verification evidence")

        if changes:
            evidence.append(f"{len(changes)} generated change(s) were examined")
        else:
            evidence.append("no generated change set was required")

        # A task graph must not contain a failed acceptance gate.
        if task_graph is not None:
            failed = getattr(task_graph, "failed", None)
            if failed:
                try:
                    failed_items = tuple(failed)
                except TypeError:
                    failed_items = ()
                if failed_items:
                    blockers.append(f"task graph has failed nodes: {', '.join(map(str, failed_items))}")
                    next_actions.append("repair or rebuild the failed task-graph branch")

        if validation_valid and acceptance_ok and verification_sufficient and tests_ran and tests_passed:
            return EngineeringJudgment(
                decision="accepted",
                confidence=min(0.99, max(0.80, verification_confidence)),
                rationale="The requirement is supported by passing behavioral evidence, repository validation, and the acceptance gate.",
                satisfied_criteria=tuple(dict.fromkeys(satisfied)),
                evidence=tuple(dict.fromkeys(evidence)),
            )

        # Genuine blockers are environmental/resource constraints, not merely
        # unfamiliar diagnostics. They justify stopping but never silently
        # convert an unproven implementation into success.
        combined = " ".join(blockers + list(getattr(verification, "blocking_reasons", ()) or ())).lower()
        genuine_blocker = any(word in combined for word in self._BLOCKER_WORDS)

        if genuine_blocker:
            return EngineeringJudgment(
                decision="blocked",
                confidence=0.88,
                rationale="The available evidence indicates an external safety, authorization, resource, or environment blocker rather than an ordinary implementation failure.",
                satisfied_criteria=tuple(dict.fromkeys(satisfied)),
                missing_criteria=tuple(dict.fromkeys(missing)),
                blocking_reasons=tuple(dict.fromkeys(blockers)),
                evidence=tuple(dict.fromkeys(evidence)),
                next_actions=tuple(dict.fromkeys(next_actions)),
                genuine_blocker=True,
            )

        if test_result is not None and not tests_passed:
            decision = "repair_required"
            rationale = "The latest behavioral evidence disproves acceptance; recovery must continue from the newest evidence."
        elif not verification_sufficient:
            decision = "needs_more_evidence"
            rationale = "The implementation may be viable, but the evidence is insufficient to make an engineering acceptance decision."
        else:
            decision = "repair_required"
            rationale = "At least one acceptance dimension remains unsatisfied; the system must continue engineering work rather than claim success."

        return EngineeringJudgment(
            decision=decision,
            confidence=min(0.75, max(0.10, verification_confidence)),
            rationale=rationale,
            satisfied_criteria=tuple(dict.fromkeys(satisfied)),
            missing_criteria=tuple(dict.fromkeys(missing)),
            blocking_reasons=tuple(dict.fromkeys(blockers)),
            evidence=tuple(dict.fromkeys(evidence)),
            next_actions=tuple(dict.fromkeys(next_actions)),
            genuine_blocker=False,
        )

    def build_prompt_section(self, judgment: EngineeringJudgment | None) -> str:
        if judgment is None:
            return (
                "ENGINEERING JUDGMENT POLICY:\n"
                "Do not declare success from file creation alone. Prove the underlying requirement with the strongest relevant evidence."
            )
        return (
            "ENGINEERING JUDGMENT:\n"
            f"decision={judgment.decision}\n"
            f"confidence={judgment.confidence:.2f}\n"
            f"rationale={judgment.rationale}\n"
            f"missing={list(judgment.missing_criteria)}\n"
            f"next_actions={list(judgment.next_actions)}\n"
            "Never claim acceptance unless the evidence actually proves the requirement."
        )
