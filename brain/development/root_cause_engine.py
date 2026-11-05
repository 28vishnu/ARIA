from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class RootCauseHypothesis:
    category: str
    confidence: float
    statement: str
    evidence: tuple[str, ...] = ()
    affected_paths: tuple[str, ...] = ()
    repair_direction: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "confidence": self.confidence,
            "statement": self.statement,
            "evidence": list(self.evidence),
            "affected_paths": list(self.affected_paths),
            "repair_direction": self.repair_direction,
        }


@dataclass(frozen=True)
class RootCauseAssessment:
    primary: RootCauseHypothesis | None
    alternatives: tuple[RootCauseHypothesis, ...] = ()
    evidence_quality: float = 0.0
    needs_more_evidence: bool = False
    next_evidence: tuple[str, ...] = ()
    observed_failure: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "primary": self.primary.to_dict() if self.primary else None,
            "alternatives": [x.to_dict() for x in self.alternatives],
            "evidence_quality": self.evidence_quality,
            "needs_more_evidence": self.needs_more_evidence,
            "next_evidence": list(self.next_evidence),
            "observed_failure": dict(self.observed_failure),
        }


class RootCauseEngine:
    """General evidence-driven root-cause reasoning."""

    VERSION = "PHASE1-ROOT-CAUSE-20261004"

    _PATTERNS = (
        ("syntax", (r"syntaxerror", r"indentationerror", r"unexpected indent", r"invalid syntax")),
        ("import", (r"modulenotfounderror", r"no module named", r"importerror", r"cannot import name")),
        ("assertion", (r"assertionerror",)),
        ("type", (r"typeerror", r"attributeerror", r"object .* has no attribute")),
        ("name", (r"nameerror", r"is not defined")),
        ("file_or_path", (r"filenotfounderror", r"no such file or directory", r"file not found")),
        ("permission", (r"permissionerror", r"permission denied")),
        ("timeout", (r"timeout", r"timed out")),
        ("dependency", (r"dependency", r"package .* not installed", r"could not find a version")),
    )

    def assess(
        self,
        *,
        test_result: Any | None = None,
        validation: Any | None = None,
        errors: Iterable[str] = (),
        changed_paths: Iterable[str] = (),
        requirement_text: str = "",
    ) -> RootCauseAssessment:
        parts: list[str] = [str(x) for x in errors if str(x).strip()]
        observed: dict[str, Any] = {}

        if validation is not None:
            parts.append(self._object_text(validation))
            observed["validation"] = self._object_dict(validation)

        if test_result is not None:
            parts.append(self._object_text(test_result))
            observed["test_result"] = self._object_dict(test_result)

        combined = "\n".join(x for x in parts if x)
        lowered = combined.lower()
        changed = tuple(
            str(x).replace("\\", "/")
            for x in changed_paths
            if str(x).strip()
        )

        hypotheses: list[RootCauseHypothesis] = []

        for category, patterns in self._PATTERNS:
            hits = [
                pattern for pattern in patterns
                if re.search(pattern, lowered, flags=re.IGNORECASE)
            ]
            if not hits:
                continue

            affected = self._infer_paths(combined, changed)
            confidence = min(
                0.96,
                0.60 + 0.08 * len(hits) + (0.05 if affected else 0.0),
            )
            hypotheses.append(
                RootCauseHypothesis(
                    category=category,
                    confidence=confidence,
                    statement=self._statement(category),
                    evidence=tuple(hits),
                    affected_paths=affected,
                    repair_direction=self._repair_direction(category),
                )
            )

        if not hypotheses and (combined.strip() or test_result is not None):
            hypotheses.append(
                RootCauseHypothesis(
                    category="unknown",
                    confidence=0.15,
                    statement="The run failed, but the available evidence does not identify a reliable root cause.",
                    evidence=("No recognized diagnostic pattern matched the supplied evidence.",),
                    affected_paths=changed,
                    repair_direction="Gather discriminating evidence before editing code.",
                )
            )

        hypotheses.sort(key=lambda x: (-x.confidence, x.category))
        primary = hypotheses[0] if hypotheses else None
        alternatives = tuple(hypotheses[1:4])

        quality = self._evidence_quality(combined, test_result, validation, primary)
        needs_more = primary is None or primary.category == "unknown" or quality < 0.55

        next_evidence: list[str] = []
        if needs_more:
            next_evidence.extend((
                "Capture the exact failing command.",
                "Capture process exit code and timeout state.",
                "Capture complete stdout and stderr.",
                "Identify the first meaningful failure location.",
                "Compare the failure against changed files.",
                "Run the narrowest verification that distinguishes competing hypotheses.",
            ))

        if primary and primary.category == "assertion":
            next_evidence.append("Compare expected and actual values before changing implementation.")

        return RootCauseAssessment(
            primary=primary,
            alternatives=alternatives,
            evidence_quality=round(quality, 3),
            needs_more_evidence=needs_more,
            next_evidence=tuple(dict.fromkeys(next_evidence)),
            observed_failure=observed,
        )

    def build_prompt_section(self, assessment: RootCauseAssessment | None) -> str:
        if assessment is None:
            return ""
        primary = assessment.primary
        return (
            "\nROOT-CAUSE ENGINEERING EVIDENCE:\n"
            f"Primary category: {primary.category if primary else 'none'}\n"
            f"Confidence: {primary.confidence if primary else 0.0}\n"
            f"Statement: {primary.statement if primary else 'More evidence is required.'}\n"
            f"Affected paths: {list(primary.affected_paths) if primary else []}\n"
            f"Repair direction: {primary.repair_direction if primary else 'Gather evidence before repairing.'}\n"
            f"Evidence quality: {assessment.evidence_quality}\n"
            f"Needs more evidence: {assessment.needs_more_evidence}\n"
            f"Next evidence: {list(assessment.next_evidence)}\n"
            "Repair rules:\n"
            "- Diagnose the root cause before editing code.\n"
            "- Preserve alternative hypotheses when evidence is ambiguous.\n"
            "- If evidence quality is low, gather discriminating evidence instead of guessing.\n"
            "- Do not modify unrelated files merely to silence a test suite.\n"
            "- Unknown is a valid diagnostic state; never fabricate a category.\n"
        )

    @staticmethod
    def _statement(category: str) -> str:
        return {
            "syntax": "The failure is consistent with invalid source syntax or indentation.",
            "import": "The failure is consistent with an import or module-resolution problem.",
            "assertion": "The implementation produced behavior different from the verified expectation.",
            "type": "The failure is consistent with an incompatible runtime value or interface.",
            "name": "The failure is consistent with an unresolved name or symbol.",
            "file_or_path": "The failure is consistent with a missing or incorrectly addressed file/path.",
            "permission": "The failure is consistent with a filesystem or execution permission problem.",
            "timeout": "The process did not complete within its allowed execution window.",
            "dependency": "The failure is consistent with an unavailable or incompatible dependency.",
        }.get(category, "The failure requires additional evidence.")

    @staticmethod
    def _repair_direction(category: str) -> str:
        return {
            "syntax": "Inspect the reported source location and surrounding syntax before rewriting.",
            "import": "Inspect module paths, package structure, and imports used by changed code.",
            "assertion": "Inspect expected/actual values and trace behavior to the smallest responsible change.",
            "type": "Trace the value and interface contract producing the incompatible operation.",
            "name": "Trace symbol definition, scope, spelling, and imports.",
            "file_or_path": "Verify the intended path and filesystem state before changing path logic.",
            "permission": "Verify workspace permissions and guarded execution state before code changes.",
            "timeout": "Determine whether the operation is genuinely slow or blocked before changing implementation.",
            "dependency": "Inspect dependency declarations and the isolated environment.",
        }.get(category, "Gather evidence before repairing.")

    @staticmethod
    def _object_text(value: Any) -> str:
        parts: list[str] = []
        for name in ("summary", "error", "stdout", "stderr", "command", "message", "details", "reason"):
            item = getattr(value, name, None)
            if item:
                parts.append(str(item))
        return "\n".join(parts)

    @staticmethod
    def _object_dict(value: Any) -> dict[str, Any]:
        if hasattr(value, "to_dict"):
            try:
                result = value.to_dict()
                return result if isinstance(result, dict) else {}
            except Exception:
                return {}
        return {}

    @staticmethod
    def _infer_paths(text: str, changed: tuple[str, ...]) -> tuple[str, ...]:
        found = list(changed)
        pattern = r"(?:(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+\.[A-Za-z0-9_]+|[A-Za-z0-9_.-]+\.(?:py|js|ts|tsx|java|go|rs|c|cpp|h|hpp))"
        for match in re.findall(pattern, text):
            normalized = match.replace("\\", "/")
            if normalized not in found:
                found.append(normalized)
        return tuple(found[:20])

    @staticmethod
    def _evidence_quality(
        combined: str,
        test_result: Any | None,
        validation: Any | None,
        primary: RootCauseHypothesis | None,
    ) -> float:
        score = 0.0
        if combined.strip():
            score += 0.25
        if test_result is not None:
            score += 0.20
        if validation is not None:
            score += 0.15
        lowered = combined.lower()
        for token in ("stdout", "stderr", "command", "return_code", "exit_code"):
            if token in lowered:
                score += 0.07
        if primary and primary.category != "unknown":
            score += 0.20
        return min(1.0, score)
