from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
import re


@dataclass(frozen=True)
class VerificationEvidence:
    kind: str
    status: str
    source: str
    detail: str = ""
    confidence: float = 0.0
    related_paths: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "status": self.status,
            "source": self.source,
            "detail": self.detail,
            "confidence": self.confidence,
            "related_paths": list(self.related_paths),
        }


@dataclass(frozen=True)
class VerificationDecision:
    sufficient: bool
    confidence: float
    required_evidence: tuple[str, ...]
    satisfied_evidence: tuple[str, ...]
    missing_evidence: tuple[str, ...]
    blocking_reasons: tuple[str, ...]
    evidence: tuple[VerificationEvidence, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "sufficient": self.sufficient,
            "confidence": self.confidence,
            "required_evidence": list(self.required_evidence),
            "satisfied_evidence": list(self.satisfied_evidence),
            "missing_evidence": list(self.missing_evidence),
            "blocking_reasons": list(self.blocking_reasons),
            "evidence": [item.to_dict() for item in self.evidence],
        }


class IntelligentVerification:
    """Requirement-aware evidence and acceptance engine."""

    VERSION = "PHASE1-INTELLIGENT-VERIFICATION-20261004"

    def build_requirements(
        self,
        requirement_text: str,
        generated_changes: Iterable[Any] = (),
    ) -> tuple[str, ...]:
        text = str(requirement_text or "").lower()
        required: list[str] = ["implementation", "isolation"]
        code_suffixes = {
            ".py", ".pyw", ".js", ".jsx", ".ts", ".tsx",
            ".java", ".go", ".rs", ".c", ".cpp", ".h", ".hpp",
            ".cs", ".php", ".rb", ".swift", ".kt", ".kts",
        }
        code_changed = any(
            Path(str(getattr(item, "path", ""))).suffix.lower() in code_suffixes
            for item in generated_changes
        )
        if code_changed:
            required.extend(("static", "behavioral"))
        if any(
            phrase in text
            for phrase in (
                "exactly", "must return", "must contain", "equals",
                "should return", "verify", "acceptance", "requirement passes",
            )
        ):
            required.append("acceptance")
        return tuple(dict.fromkeys(required))

    def rank_test_paths(
        self,
        candidates: Iterable[str],
        *,
        generated_paths: Iterable[str] = (),
        requirement_text: str = "",
    ) -> list[str]:
        generated_stems = {
            Path(str(path)).with_suffix("").name.lower()
            for path in generated_paths
        }
        words = {
            word.lower()
            for word in re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{2,}", requirement_text or "")
        }
        scored: list[tuple[int, str]] = []
        for raw in candidates:
            path = str(raw).replace("\\", "/").strip()
            if not path:
                continue
            lower = path.lower()
            score = 0
            if Path(path).stem.lower().startswith("test_"):
                score += 3
            if any(token in lower for token in ("test", "spec", "check")):
                score += 2
            score += sum(8 for stem in generated_stems if stem and stem in lower)
            score += sum(1 for word in words if word in lower)
            scored.append((score, path))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [path for _, path in scored]

    def evaluate(
        self,
        *,
        requirement_text: str,
        generated_changes: Iterable[Any] = (),
        validation: Any | None = None,
        test_result: Any | None = None,
        acceptance_error: str | None = None,
        workspace_verified: bool = False,
        tests_selected: Iterable[str] = (),
    ) -> VerificationDecision:
        required = self.build_requirements(requirement_text, generated_changes)
        evidence: list[VerificationEvidence] = []
        generated = list(generated_changes)

        evidence.append(VerificationEvidence(
            kind="implementation",
            status="passed" if generated else "missing",
            source="guarded_workspace_writes",
            detail=f"{len(generated)} implementation change(s) were accepted." if generated else "No implementation changes are available.",
            confidence=0.90 if generated else 0.0,
            related_paths=tuple(str(getattr(item, "path", "")) for item in generated),
        ))
        evidence.append(VerificationEvidence(
            kind="isolation",
            status="passed" if workspace_verified else "missing",
            source="workspace_verification",
            detail="Evidence was produced inside the isolated workspace." if workspace_verified else "The isolated workspace has not been positively verified.",
            confidence=0.95 if workspace_verified else 0.0,
        ))

        if validation is None:
            evidence.append(VerificationEvidence("static", "missing", "development_validator", "Static validation produced no result."))
        else:
            valid = bool(getattr(validation, "valid", False))
            evidence.append(VerificationEvidence(
                "static", "passed" if valid else "failed", "development_validator",
                "Static validation passed." if valid else "Static validation reported failure.",
                0.95 if valid else 0.0,
            ))

        if test_result is None:
            evidence.append(VerificationEvidence("behavioral", "missing", "development_test_runner", "No behavioral test result is available."))
        else:
            passed = bool(getattr(test_result, "passed", False))
            results = getattr(test_result, "results", None)
            count = len(results) if results is not None else 0
            good = passed and count > 0
            evidence.append(VerificationEvidence(
                "behavioral", "passed" if good else "failed", "development_test_runner",
                f"{count} test result(s) passed." if good else "Behavioral verification did not produce a passing result.",
                0.95 if good else 0.0,
                tuple(str(x) for x in tests_selected),
            ))

        evidence.append(VerificationEvidence(
            "acceptance", "passed" if acceptance_error is None else "failed", "acceptance_gate",
            "No explicit acceptance violation was detected." if acceptance_error is None else str(acceptance_error),
            0.90 if acceptance_error is None else 0.0,
        ))

        by_kind = {item.kind: item for item in evidence}
        satisfied = tuple(kind for kind in required if by_kind.get(kind) and by_kind[kind].status == "passed")
        missing = tuple(kind for kind in required if not by_kind.get(kind) or by_kind[kind].status == "missing")
        failed = tuple(kind for kind in required if by_kind.get(kind) and by_kind[kind].status == "failed")
        blockers = tuple(
            [*(f"Required evidence '{kind}' is missing." for kind in missing),
             *(f"Required evidence '{kind}' failed." for kind in failed)]
        )
        values = [by_kind[kind].confidence for kind in required if kind in by_kind]
        confidence = round(sum(values) / len(values), 3) if values else 0.0
        return VerificationDecision(
            sufficient=bool(required) and not missing and not failed,
            confidence=confidence,
            required_evidence=required,
            satisfied_evidence=satisfied,
            missing_evidence=missing,
            blocking_reasons=blockers,
            evidence=tuple(evidence),
        )

    def build_prompt_section(
        self,
        requirement_text: str,
        generated_changes: Iterable[Any] = (),
    ) -> str:
        required = self.build_requirements(requirement_text, generated_changes)
        return (
            "\nINTELLIGENT VERIFICATION POLICY:\n"
            f"- Required evidence dimensions: {', '.join(required)}\n"
            "- Prove the underlying requirement, not merely file creation.\n"
            "- Prefer targeted relevant behavioral evidence before unrelated regression suites.\n"
            "- Preserve command, exit status, stdout, stderr, and timeout evidence.\n"
            "- Unknown diagnostic categories require more evidence; they are not proof of success or failure.\n"
            "- Missing evidence means gather evidence rather than declare success.\n"
            "- Do not claim success until every required evidence dimension is satisfied.\n"
            "- Do not broaden verification into unrelated tests merely because they exist.\n"
        )
