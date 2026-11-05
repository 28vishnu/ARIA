from __future__ import annotations

"""ARIA Phase 1 — evidence-driven autonomous recovery.

This layer sits between DevelopmentAgent and the lower-level repair callback.
It deliberately does not edit files or execute shell commands itself.  It
coordinates fresh evidence, root-cause assessment, recovery strategy changes,
repair, retest, and reassessment.
"""

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from .failure_analyzer import FailureAnalysis
from .test_runner import TestResult


@dataclass(frozen=True)
class RecoveryDecision:
    """Decision for one recovery iteration."""

    strategy: str
    reason: str
    confidence: float
    gather_more_evidence: bool = False
    repair_allowed: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "reason": self.reason,
            "confidence": self.confidence,
            "gather_more_evidence": self.gather_more_evidence,
            "repair_allowed": self.repair_allowed,
        }


@dataclass(frozen=True)
class RecoveryCycle:
    cycle: int
    strategy: str
    status: str
    analysis: FailureAnalysis | None = None
    root_cause: Any | None = None
    test_result: TestResult | None = None
    repair_attempted: bool = False
    repair_applied: bool = False
    retest_passed: bool = False
    errors: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "cycle": self.cycle,
            "strategy": self.strategy,
            "status": self.status,
            "analysis": self.analysis.to_dict() if self.analysis else None,
            "root_cause": self.root_cause.to_dict() if hasattr(self.root_cause, "to_dict") else self.root_cause,
            "test_result": (
                {
                    **self.test_result.to_dict(),
                    "stdout": str(self.test_result.stdout)[-8000:],
                    "stderr": str(self.test_result.stderr)[-8000:],
                }
                if self.test_result
                else None
            ),
            "repair_attempted": self.repair_attempted,
            "repair_applied": self.repair_applied,
            "retest_passed": self.retest_passed,
            "errors": list(self.errors),
        }


@dataclass(frozen=True)
class RecoveryResult:
    success: bool
    attempts: int
    max_attempts: int
    stopped_reason: str
    final_result: TestResult
    history: tuple[RecoveryCycle, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
            "stopped_reason": self.stopped_reason,
            "final_result": self.final_result.to_dict(),
            "history": [item.to_dict() for item in self.history],
        }


AnalysisCallback = Callable[[TestResult], FailureAnalysis]
RootCauseCallback = Callable[[TestResult, FailureAnalysis], Any]
RepairCallback = Callable[[FailureAnalysis, int, RecoveryDecision], Awaitable[bool]]
RerunCallback = Callable[[], Awaitable[TestResult]]


class AutonomousRecoveryLoop:
    """General recovery controller with bounded strategy adaptation."""

    VERSION = "PHASE1-AUTONOMOUS-RECOVERY-20261004"

    def __init__(self, *, max_attempts: int = 4) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1.")
        self.max_attempts = int(max_attempts)

    @staticmethod
    def _decision(root_cause: Any, analysis: FailureAnalysis, cycle: int) -> RecoveryDecision:
        primary = getattr(root_cause, "primary", None)
        category = str(getattr(primary, "category", "unknown") or "unknown")
        confidence = float(getattr(primary, "confidence", 0.0) or 0.0)
        quality = float(getattr(root_cause, "evidence_quality", 0.0) or 0.0)
        needs_more = bool(getattr(root_cause, "needs_more_evidence", False))

        if category == "unknown" or needs_more or quality < 0.55:
            if cycle <= 2:
                return RecoveryDecision(
                    strategy="evidence_first" if cycle == 1 else "discriminating_evidence",
                    reason="Root cause is not sufficiently established; obtain fresh evidence before making a stronger repair decision.",
                    confidence=min(confidence, quality),
                    gather_more_evidence=True,
                    repair_allowed=True,
                )
            return RecoveryDecision(
                strategy="hypothesis_generation",
                reason="Fresh evidence remains inconclusive after multiple observations; let the engineering model form competing repair hypotheses from the complete evidence rather than stopping on an unfamiliar diagnostic.",
                confidence=max(0.25, min(0.60, quality)),
                gather_more_evidence=False,
                repair_allowed=True,
            )

        strategy_map = {
            "syntax": "syntax_repair",
            "import": "dependency_or_import_repair",
            "assertion": "behavior_contract_repair",
            "type": "type_contract_repair",
            "name": "symbol_resolution_repair",
            "file_or_path": "path_contract_repair",
            "permission": "environment_boundary_repair",
            "timeout": "execution_strategy_review",
            "dependency": "dependency_boundary_repair",
        }
        base = strategy_map.get(category, "root_cause_repair")
        if cycle > 1:
            base = f"alternate_{base}"

        return RecoveryDecision(
            strategy=base,
            reason=f"Evidence supports a {category} root cause; repair should target that cause rather than repeat the previous change blindly.",
            confidence=min(0.99, max(confidence, quality)),
            gather_more_evidence=False,
            repair_allowed=bool(analysis.repairable or confidence >= 0.65),
        )

    @staticmethod
    def _fingerprint(result: TestResult, root_cause: Any, strategy: str) -> tuple[Any, ...]:
        primary = getattr(root_cause, "primary", None)
        category = getattr(primary, "category", "unknown")
        return (
            tuple(result.command),
            result.return_code,
            result.timed_out,
            str(result.stdout)[-1200:],
            str(result.stderr)[-1200:],
            category,
            strategy,
        )

    async def run(
        self,
        initial_result: TestResult,
        *,
        analyze: AnalysisCallback,
        root_cause: RootCauseCallback,
        apply_repair: RepairCallback,
        rerun: RerunCallback,
    ) -> RecoveryResult:
        current = initial_result
        history: list[RecoveryCycle] = []
        seen: set[tuple[Any, ...]] = set()

        if current.passed:
            return RecoveryResult(True, 0, self.max_attempts, "initial_tests_passed", current)

        for cycle in range(1, self.max_attempts + 1):
            analysis = analyze(current)
            assessment = root_cause(current, analysis)
            decision = self._decision(assessment, analysis, cycle)

            fingerprint = self._fingerprint(current, assessment, decision.strategy)
            repeated = fingerprint in seen
            seen.add(fingerprint)
            if repeated:
                decision = RecoveryDecision(
                    strategy=f"new_evidence_{cycle}",
                    reason="The same failure evidence and strategy recurred; do not repeat an unchanged repair. Refresh evidence and change the recovery strategy.",
                    confidence=decision.confidence,
                    gather_more_evidence=True,
                    repair_allowed=True,
                )

            if decision.gather_more_evidence:
                try:
                    refreshed = await rerun()
                except Exception as exc:
                    history.append(RecoveryCycle(cycle, decision.strategy, "evidence_collection_failed", analysis, assessment, current, False, False, False, (str(exc),)))
                    return RecoveryResult(False, cycle, self.max_attempts, "evidence_collection_failed", current, tuple(history))
                current = refreshed
                history.append(RecoveryCycle(cycle, decision.strategy, "evidence_refreshed", analysis, assessment, current, False, False, current.passed, ()))
                if current.passed:
                    return RecoveryResult(True, cycle, self.max_attempts, "tests_passed_after_evidence_refresh", current, tuple(history))
                continue

            if not decision.repair_allowed:
                history.append(RecoveryCycle(cycle, decision.strategy, "repair_blocked_by_evidence", analysis, assessment, current, False, False, False, (decision.reason,)))
                return RecoveryResult(False, cycle - 1, self.max_attempts, "insufficient_repair_basis", current, tuple(history))

            try:
                applied = await apply_repair(analysis, cycle, decision)
            except Exception as exc:
                history.append(RecoveryCycle(cycle, decision.strategy, "repair_exception", analysis, assessment, current, True, False, False, (str(exc),)))
                applied = False

            if not applied:
                try:
                    refreshed = await rerun()
                except Exception as exc:
                    history.append(RecoveryCycle(cycle, decision.strategy, "repair_not_applied_and_retest_failed", analysis, assessment, current, True, False, False, (str(exc),)))
                    return RecoveryResult(False, cycle, self.max_attempts, "recovery_evidence_refresh_failed", current, tuple(history))
                current = refreshed
                history.append(RecoveryCycle(cycle, decision.strategy, "repair_not_applied_evidence_refreshed", analysis, assessment, current, True, False, current.passed, ()))
                if current.passed:
                    return RecoveryResult(True, cycle, self.max_attempts, "tests_passed_after_recovery_refresh", current, tuple(history))
                continue

            try:
                current = await rerun()
            except Exception as exc:
                history.append(RecoveryCycle(cycle, decision.strategy, "retest_failed_to_execute", analysis, assessment, current, True, True, False, (str(exc),)))
                return RecoveryResult(False, cycle, self.max_attempts, "retest_execution_failed", current, tuple(history))

            history.append(RecoveryCycle(cycle, decision.strategy, "retested", analysis, assessment, current, True, True, current.passed, ()))

            if current.passed:
                return RecoveryResult(True, cycle, self.max_attempts, "tests_passed_after_recovery", current, tuple(history))

        return RecoveryResult(False, self.max_attempts, self.max_attempts, "maximum_recovery_attempts_reached", current, tuple(history))
