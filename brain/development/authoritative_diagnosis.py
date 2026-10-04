"""Authoritative root-cause diagnosis engine for ARIA.

Step 13 connects the new diagnosis contracts to ARIA's existing
root-cause/failure-analysis services.

The engine does not modify code.

Its responsibility is to normalize diagnostic evidence into one
authoritative decision that later recovery and repair layers can consume.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from .contracts.engineering_diagnosis import (
    DiagnosisAction,
    DiagnosisCategory,
    DiagnosisDecision,
    DiagnosisEvidence,
    DiagnosisRequest,
    DiagnosisResult,
    RootCauseHypothesis,
    confidence_level,
)


class AuthoritativeDiagnosisEngine:
    """Evidence-first root-cause diagnosis adapter."""

    VERSION = "PHASE1-AUTHORITATIVE-DIAGNOSIS-20261004"

    _PATTERNS: tuple[
        tuple[DiagnosisCategory, tuple[str, ...]],
        ...
    ] = (
        (
            DiagnosisCategory.SYNTAX,
            (
                "syntaxerror",
                "invalid syntax",
                "unexpected indent",
                "unterminated string",
            ),
        ),
        (
            DiagnosisCategory.IMPORT,
            (
                "modulenotfounderror",
                "importerror",
                "cannot import name",
                "no module named",
            ),
        ),
        (
            DiagnosisCategory.NAME,
            (
                "nameerror",
                "is not defined",
            ),
        ),
        (
            DiagnosisCategory.TYPE,
            (
                "typeerror",
                "expected type",
                "unsupported operand type",
            ),
        ),
        (
            DiagnosisCategory.ASSERTION,
            (
                "assertionerror",
                "assert ",
                "assertion failed",
            ),
        ),
        (
            DiagnosisCategory.FILE_OR_PATH,
            (
                "filenotfounderror",
                "not a directory",
                "no such file",
                "path does not exist",
            ),
        ),
        (
            DiagnosisCategory.PERMISSION,
            (
                "permissionerror",
                "permission denied",
                "operation not permitted",
            ),
        ),
        (
            DiagnosisCategory.TIMEOUT,
            (
                "timeout",
                "timed out",
            ),
        ),
        (
            DiagnosisCategory.DEPENDENCY,
            (
                "dependency",
                "package is required",
                "distribution was not found",
            ),
        ),
        (
            DiagnosisCategory.CONFIGURATION,
            (
                "configuration",
                "config error",
                "missing configuration",
                "invalid configuration",
            ),
        ),
        (
            DiagnosisCategory.INTERFACE,
            (
                "unexpected keyword argument",
                "missing required positional argument",
                "has no attribute",
                "signature",
            ),
        ),
        (
            DiagnosisCategory.ENVIRONMENT,
            (
                "environment variable",
                "runtime environment",
                "os.environ",
            ),
        ),
        (
            DiagnosisCategory.LOGIC,
            (
                "incorrect result",
                "wrong result",
                "expected",
                "actual",
            ),
        ),
    )

    async def diagnose(
        self,
        request: DiagnosisRequest,
        *,
        failure_analyzer: Any | None = None,
        root_cause_engine: Any | None = None,
    ) -> DiagnosisResult:
        """Diagnose a failure using available authoritative evidence."""

        if not isinstance(
            request,
            DiagnosisRequest,
        ):
            raise TypeError(
                "request must be a DiagnosisRequest."
            )

        external = await self._try_external_diagnosis(
            request,
            failure_analyzer=failure_analyzer,
            root_cause_engine=root_cause_engine,
        )

        if external is not None:
            return external

        return self._diagnose_from_evidence(
            request
        )

    async def _try_external_diagnosis(
        self,
        request: DiagnosisRequest,
        *,
        failure_analyzer: Any | None,
        root_cause_engine: Any | None,
    ) -> DiagnosisResult | None:
        """Use an existing diagnosis engine when it exposes a compatible API."""

        service = (
            root_cause_engine
            or failure_analyzer
        )

        if service is None:
            return None

        method = getattr(
            service,
            "assess",
            None,
        )

        if method is None:
            method = getattr(
                service,
                "analyze",
                None,
            )

        if method is None:
            method = getattr(
                service,
                "diagnose",
                None,
            )

        if method is None:
            return None

        try:
            raw = method(
                request.observed_failure
            )
        except TypeError:
            try:
                raw = method(
                    request
                )
            except Exception:
                return None
        except Exception:
            return None

        if hasattr(
            raw,
            "__await__",
        ):
            try:
                raw = await raw
            except Exception:
                return None

        return self._normalize_external_result(
            request,
            raw,
        )

    def _normalize_external_result(
        self,
        request: DiagnosisRequest,
        raw: Any,
    ) -> DiagnosisResult | None:
        if isinstance(
            raw,
            DiagnosisResult,
        ):
            return raw

        primary_raw = self._read_value(
            raw,
            "primary",
        )

        if primary_raw is None:
            primary_raw = self._read_value(
                raw,
                "root_cause",
            )

        if primary_raw is None:
            return None

        primary = self._normalize_hypothesis(
            primary_raw,
            request,
            "primary",
        )

        if primary is None:
            return None

        alternatives_raw = self._read_value(
            raw,
            "alternatives",
        )

        alternatives: list[
            RootCauseHypothesis
        ] = []

        if isinstance(
            alternatives_raw,
            (list, tuple),
        ):
            for index, item in enumerate(
                alternatives_raw
            ):
                normalized = self._normalize_hypothesis(
                    item,
                    request,
                    f"alternative-{index}",
                )

                if normalized is not None:
                    alternatives.append(
                        normalized
                    )

        raw_confidence = self._read_value(
            raw,
            "confidence",
        )

        confidence = self._safe_float(
            raw_confidence,
            primary.confidence,
        )

        needs_more = bool(
            self._read_value(
                raw,
                "needs_more_evidence",
            )
        )

        action = (
            DiagnosisAction.GATHER_EVIDENCE
            if needs_more
            else DiagnosisAction.REPAIR
        )

        decision = DiagnosisDecision(
            primary=primary,
            alternatives=tuple(
                alternatives
            ),
            evidence=(
                request.verification_evidence
                + request.implementation_evidence
            ),
            evidence_quality=self._evidence_quality(
                request
            ),
            confidence=confidence,
            needs_more_evidence=needs_more,
            next_evidence=self._next_evidence(
                request,
                primary,
            )
            if needs_more
            else (),
            action=action,
            observed_failure=(
                request.observed_failure
            ),
            metadata={
                "source": "legacy_diagnosis_adapter",
                "version": self.VERSION,
            },
        )

        return DiagnosisResult(
            session_id=request.session_id,
            task_id=request.task_id,
            decision=decision,
            metadata={
                "version": self.VERSION,
            },
        )

    def _diagnose_from_evidence(
        self,
        request: DiagnosisRequest,
    ) -> DiagnosisResult:
        """Perform deterministic evidence-first diagnosis."""

        text = self._failure_text(
            request
        )

        category = self._classify(
            text
        )

        evidence = (
            request.verification_evidence
            + request.implementation_evidence
        )

        evidence_quality = self._evidence_quality(
            request
        )

        confidence = self._calculate_confidence(
            category,
            evidence_quality,
        )

        if category is DiagnosisCategory.UNKNOWN:
            primary = None
            action = (
                DiagnosisAction.GATHER_EVIDENCE
            )
            needs_more = True

        else:
            statement = self._statement_for(
                category,
                request,
            )

            primary = RootCauseHypothesis(
                hypothesis_id=(
                    f"{request.session_id}:"
                    f"{request.task_id}:primary"
                ),
                category=category,
                statement=statement,
                confidence=confidence,
                confidence_level=confidence_level(
                    confidence
                ),
                evidence_ids=tuple(
                    item.evidence_id
                    for item in evidence
                    if item.supports
                ),
                affected_paths=(
                    request.changed_paths
                ),
                repair_direction=self._repair_direction(
                    category
                ),
                falsification_conditions=(
                    self._falsification_conditions(
                        category
                    )
                ),
                metadata={
                    "diagnosis_version": self.VERSION,
                },
            )

            needs_more = confidence < 0.55

            action = (
                DiagnosisAction.GATHER_EVIDENCE
                if needs_more
                else DiagnosisAction.REPAIR
            )

        next_evidence = (
            self._next_evidence(
                request,
                primary,
            )
            if needs_more
            else ()
        )

        decision = DiagnosisDecision(
            primary=primary,
            alternatives=(),
            evidence=evidence,
            evidence_quality=evidence_quality,
            confidence=confidence,
            needs_more_evidence=needs_more,
            next_evidence=next_evidence,
            action=action,
            observed_failure=(
                request.observed_failure
            ),
            metadata={
                "diagnosis_version": self.VERSION,
                "category": category.value,
            },
        )

        return DiagnosisResult(
            session_id=request.session_id,
            task_id=request.task_id,
            decision=decision,
            metadata={
                "diagnosis_version": self.VERSION,
                "evidence_count": len(
                    evidence
                ),
            },
        )

    @classmethod
    def _failure_text(
        cls,
        request: DiagnosisRequest,
    ) -> str:
        parts = [
            request.observed_failure,
            request.verification_status,
        ]

        for item in (
            request.verification_evidence
            + request.implementation_evidence
        ):
            parts.extend(
                [
                    item.description,
                    item.stdout,
                    item.stderr,
                ]
            )

        return "\n".join(
            part
            for part in parts
            if part
        ).lower()

    @classmethod
    def _classify(
        cls,
        text: str,
    ) -> DiagnosisCategory:
        scores: dict[
            DiagnosisCategory,
            int,
        ] = {}

        for category, patterns in cls._PATTERNS:
            score = 0

            for pattern in patterns:
                if pattern in text:
                    score += 1

            if score:
                scores[
                    category
                ] = score

        if not scores:
            return DiagnosisCategory.UNKNOWN

        return max(
            scores,
            key=scores.get,
        )

    @staticmethod
    def _calculate_confidence(
        category: DiagnosisCategory,
        evidence_quality: float,
    ) -> float:
        if category is DiagnosisCategory.UNKNOWN:
            return 0.0

        base = 0.35

        return max(
            0.0,
            min(
                1.0,
                base + (
                    evidence_quality * 0.60
                ),
            ),
        )

    @staticmethod
    def _evidence_quality(
        request: DiagnosisRequest,
    ) -> float:
        evidence = (
            request.verification_evidence
            + request.implementation_evidence
        )

        if not evidence:
            return 0.0

        total = 0.0
        weight = 0.0

        for item in evidence:
            item_weight = max(
                0.1,
                item.strength,
            )

            quality = 1.0

            if item.command:
                quality += 0.10

            if item.exit_code is not None:
                quality += 0.15

            if item.stdout:
                quality += 0.10

            if item.stderr:
                quality += 0.10

            total += min(
                1.0,
                quality * item_weight,
            )

            weight += item_weight

        if weight <= 0:
            return 0.0

        return max(
            0.0,
            min(
                1.0,
                total / weight,
            ),
        )

    @staticmethod
    def _statement_for(
        category: DiagnosisCategory,
        request: DiagnosisRequest,
    ) -> str:
        changed = (
            ", ".join(
                request.changed_paths
            )
            or "the implementation"
        )

        statements = {
            DiagnosisCategory.SYNTAX: (
                f"A syntax-level failure is present in "
                f"{changed} or its directly executed code."
            ),
            DiagnosisCategory.IMPORT: (
                f"An import/module-resolution failure is affecting "
                f"{changed} or a dependency it uses."
            ),
            DiagnosisCategory.NAME: (
                f"A required name or symbol is unresolved in "
                f"{changed} or its execution path."
            ),
            DiagnosisCategory.TYPE: (
                f"A value/type contract is being violated in "
                f"{changed} or a directly affected interface."
            ),
            DiagnosisCategory.ASSERTION: (
                "Observed evidence indicates an assertion or "
                "expected-behavior mismatch."
            ),
            DiagnosisCategory.FILE_OR_PATH: (
                "A required file or path cannot be resolved "
                "from the current execution context."
            ),
            DiagnosisCategory.PERMISSION: (
                "The operation is blocked by a filesystem or "
                "execution permission boundary."
            ),
            DiagnosisCategory.TIMEOUT: (
                "The operation exceeded its permitted execution "
                "time or failed to terminate as expected."
            ),
            DiagnosisCategory.DEPENDENCY: (
                "A required external dependency is unavailable "
                "or incompatible."
            ),
            DiagnosisCategory.CONFIGURATION: (
                "Runtime or application configuration does not "
                "satisfy the implementation requirement."
            ),
            DiagnosisCategory.ENVIRONMENT: (
                "The execution environment differs from the "
                "environment required by the implementation."
            ),
            DiagnosisCategory.INTERFACE: (
                "Two components have an incompatible interface, "
                "signature, or expected contract."
            ),
            DiagnosisCategory.LOGIC: (
                "The implementation executes but produces behavior "
                "inconsistent with the required result."
            ),
        }

        return statements.get(
            category,
            (
                "The available evidence does not yet establish "
                "a specific root cause."
            ),
        )

    @staticmethod
    def _repair_direction(
        category: DiagnosisCategory,
    ) -> str:
        directions = {
            DiagnosisCategory.SYNTAX: (
                "Repair the smallest syntax defect and rerun "
                "targeted static validation."
            ),
            DiagnosisCategory.IMPORT: (
                "Repair the import/module boundary or dependency "
                "reference, then rerun the affected verification."
            ),
            DiagnosisCategory.NAME: (
                "Resolve the missing or incorrectly scoped symbol "
                "without modifying unrelated code."
            ),
            DiagnosisCategory.TYPE: (
                "Restore the violated type/interface contract "
                "and rerun the narrowest relevant test."
            ),
            DiagnosisCategory.ASSERTION: (
                "Compare expected and actual behavior before changing "
                "implementation logic."
            ),
            DiagnosisCategory.FILE_OR_PATH: (
                "Correct the file/path resolution boundary and "
                "verify the isolated workspace again."
            ),
            DiagnosisCategory.PERMISSION: (
                "Resolve the authorized execution boundary; do not "
                "weaken security controls merely to pass verification."
            ),
            DiagnosisCategory.TIMEOUT: (
                "Determine whether the timeout is caused by a genuine "
                "performance/deadlock issue before changing limits."
            ),
            DiagnosisCategory.DEPENDENCY: (
                "Verify dependency availability and compatibility "
                "before changing application code."
            ),
            DiagnosisCategory.CONFIGURATION: (
                "Correct the relevant configuration contract and "
                "rerun targeted verification."
            ),
            DiagnosisCategory.ENVIRONMENT: (
                "Identify the environmental mismatch and restore the "
                "required execution conditions."
            ),
            DiagnosisCategory.INTERFACE: (
                "Align the smallest incompatible interface boundary "
                "while preserving existing contracts."
            ),
            DiagnosisCategory.LOGIC: (
                "Trace the incorrect behavior to its smallest causal "
                "implementation boundary and repair it."
            ),
        }

        return directions.get(
            category,
            (
                "Gather discriminating evidence before modifying code."
            ),
        )

    @staticmethod
    def _falsification_conditions(
        category: DiagnosisCategory,
    ) -> tuple[str, ...]:
        return (
            (
                f"Targeted verification does not reproduce the "
                f"{category.value} failure."
            ),
            (
                "A stronger contradictory evidence source identifies "
                "a different causal boundary."
            ),
        )

    @staticmethod
    def _next_evidence(
        request: DiagnosisRequest,
        primary: RootCauseHypothesis | None,
    ) -> tuple[str, ...]:
        if primary is None:
            return (
                "capture the exact failing command",
                "capture the exit code",
                "capture complete stdout",
                "capture complete stderr",
                "identify the first meaningful failure location",
                "compare the failure against changed files",
                "run the narrowest discriminating verification",
            )

        return (
            "preserve the exact failing command and exit code",
            "preserve complete stdout and stderr",
            "verify the first meaningful failure location",
            "compare evidence against affected paths",
            (
                "run the narrowest verification that can "
                "confirm or falsify the primary hypothesis"
            ),
        )

    @classmethod
    def _normalize_hypothesis(
        cls,
        raw: Any,
        request: DiagnosisRequest,
        fallback_id: str,
    ) -> RootCauseHypothesis | None:
        if isinstance(
            raw,
            RootCauseHypothesis,
        ):
            return raw

        if not isinstance(
            raw,
            Mapping,
        ):
            return None

        category_raw = str(
            raw.get(
                "category",
                DiagnosisCategory.UNKNOWN.value,
            )
        )

        try:
            category = DiagnosisCategory(
                category_raw
            )
        except ValueError:
            category = DiagnosisCategory.UNKNOWN

        confidence = cls._safe_float(
            raw.get(
                "confidence"
            ),
            0.0,
        )

        return RootCauseHypothesis(
            hypothesis_id=str(
                raw.get(
                    "hypothesis_id",
                    fallback_id,
                )
            ),
            category=category,
            statement=str(
                raw.get(
                    "statement",
                    raw.get(
                        "description",
                        "Unspecified root cause.",
                    ),
                )
            ),
            confidence=confidence,
            confidence_level=confidence_level(
                confidence
            ),
            evidence_ids=cls._tuple(
                raw.get(
                    "evidence_ids"
                )
            ),
            affected_paths=(
                request.changed_paths
            ),
            repair_direction=str(
                raw.get(
                    "repair_direction",
                    "",
                )
            ),
            falsification_conditions=cls._tuple(
                raw.get(
                    "falsification_conditions"
                )
            ),
            metadata=dict(
                raw.get(
                    "metadata",
                    {},
                )
            ),
        )

    @staticmethod
    def _read_value(
        value: Any,
        name: str,
    ) -> Any:
        if value is None:
            return None

        if isinstance(
            value,
            Mapping,
        ):
            return value.get(
                name
            )

        return getattr(
            value,
            name,
            None,
        )

    @staticmethod
    def _safe_float(
        value: Any,
        default: float,
    ) -> float:
        try:
            return max(
                0.0,
                min(
                    1.0,
                    float(
                        value
                    ),
                ),
            )
        except (
            TypeError,
            ValueError,
        ):
            return default

    @staticmethod
    def _tuple(
        value: Any,
    ) -> tuple[str, ...]:
        if value is None:
            return ()

        if isinstance(
            value,
            str,
        ):
            return (
                value,
            )

        if isinstance(
            value,
            (list, tuple, set),
        ):
            return tuple(
                str(item)
                for item in value
                if str(item).strip()
            )

        return ()


__all__ = [
    "AuthoritativeDiagnosisEngine",
]