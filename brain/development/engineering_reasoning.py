from __future__ import annotations

"""
ARIA Phase 1 — Step 41
Autonomous Engineering Reasoning Core

This module turns a raw development request plus verified repository
information into a deterministic engineering brief for the coding model.

It does not execute commands, modify files, deploy, or push anything.
Its purpose is to make the development brain reason about:
- what the user actually wants
- what must be true when the work is finished
- what evidence can prove completion
- what should be implemented and verified
- how failures should be interpreted and recovered from
"""

import re
from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass(frozen=True)
class EngineeringDecision:
    intent: str
    objective: str
    acceptance_criteria: tuple[str, ...] = ()
    implementation_principles: tuple[str, ...] = ()
    verification_strategy: tuple[str, ...] = ()
    recovery_strategy: tuple[str, ...] = ()
    scope_rules: tuple[str, ...] = ()
    confidence: str = "medium"

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "objective": self.objective,
            "acceptance_criteria": list(self.acceptance_criteria),
            "implementation_principles": list(
                self.implementation_principles
            ),
            "verification_strategy": list(
                self.verification_strategy
            ),
            "recovery_strategy": list(
                self.recovery_strategy
            ),
            "scope_rules": list(self.scope_rules),
            "confidence": self.confidence,
        }


class EngineeringReasoningCore:
    """
    General-purpose reasoning layer for ARIA's engineering brain.

    The core is intentionally deterministic. The LLM remains responsible
    for implementation reasoning, while this layer guarantees that every
    generation request is accompanied by explicit engineering objectives,
    acceptance evidence, verification policy, and recovery rules.
    """

    VERSION = "PHASE1-ENGINEERING-REASONING-20261004"

    _INTENT_PATTERNS = (
        (r"\b(build|create|develop|implement)\b", "implementation"),
        (r"\b(fix|repair|resolve|debug)\b", "repair"),
        (r"\b(refactor|restructure|cleanup)\b", "refactor"),
        (r"\b(updat|enhanc|improv|add|extend)\w*\b", "enhancement"),
        (r"\b(remove|delete|decommission)\b", "removal"),
        (r"\b(test|verify|validate)\b", "verification"),
        (r"\b(document|docs|documentation)\b", "documentation"),
    )

    _ACCEPTANCE_PATTERNS = (
        r"(?:must|should|needs to|need to|shall)\s+[^.;\n]+",
        r"(?:return|produce|output|contain|support)\s+[^.;\n]+",
        r"(?:works|working|complete|successfully|correctly)\b[^.;\n]*",
    )

    def reason(
        self,
        requirement: Any,
        *,
        requirement_analysis: Any | None = None,
        plan: Any | None = None,
        impact_analysis: Any | None = None,
        repository_context: dict[str, Any] | None = None,
        generated_changes: Iterable[Any] = (),
        failure: Any | None = None,
    ) -> EngineeringDecision:
        raw = self._text(requirement)
        analysis = self._to_dict(requirement_analysis)
        plan_data = self._to_dict(plan)
        impact = self._to_dict(impact_analysis)
        repo = repository_context or {}
        changes = list(generated_changes)

        intent = self._infer_intent(raw, analysis)
        objective = self._objective(raw, intent)

        acceptance = self._acceptance_criteria(
            raw,
            analysis,
            changes,
        )

        implementation = [
            "Implement the user's objective, not incidental wording.",
            "Inspect and preserve existing repository behavior unless the requirement changes it.",
            "Make the smallest coherent set of changes that satisfies the objective.",
            "Keep all development changes inside the isolated workspace.",
            "Prefer existing architecture, utilities, interfaces, and conventions over parallel implementations.",
            "Do not invent secrets, credentials, deployment changes, or unrelated infrastructure.",
        ]

        if impact:
            affected = impact.get("affected_files") or []
            if affected:
                implementation.append(
                    "Prioritize the repository areas identified by change-impact analysis."
                )

        verification = [
            "Verify the behavior required by the acceptance criteria.",
            "Prefer generated or directly relevant tests before broad regression testing.",
            "Use static validation and executable tests as evidence, not as substitutes for requirement acceptance.",
            "If targeted verification passes, perform broader regression verification when the change can affect existing behavior.",
            "A green test command alone is not sufficient if the original requirement remains unsatisfied.",
        ]

        recovery = [
            "Treat every failed command as evidence to investigate, not as an automatic reason to stop.",
            "Preserve the exact command, exit code, timeout state, stdout, stderr, and affected paths.",
            "Identify the most likely root cause before proposing a repair.",
            "Repair only the cause relevant to the requirement and preserve unrelated behavior.",
            "After repair, rerun the smallest relevant verification first, then reassess the full acceptance criteria.",
            "If evidence is insufficient, gather more repository or execution evidence before making another change.",
            "Stop only for a genuine safety boundary, unavailable dependency/resource, or a requirement that cannot be satisfied safely.",
        ]

        scope = [
            "Do not broaden scope merely because unrelated tests or files exist.",
            "Do not declare success from file creation alone when executable behavior is required.",
            "Do not declare failure merely because a diagnostic category is unfamiliar.",
        ]

        if failure is not None:
            recovery.insert(
                0,
                "A previous attempt failed; use its concrete execution evidence as the primary debugging signal.",
            )

        confidence = self._confidence(
            raw=raw,
            acceptance=acceptance,
            repo=repo,
            plan=plan_data,
        )

        return EngineeringDecision(
            intent=intent,
            objective=objective,
            acceptance_criteria=tuple(self._dedupe(acceptance)),
            implementation_principles=tuple(self._dedupe(implementation)),
            verification_strategy=tuple(self._dedupe(verification)),
            recovery_strategy=tuple(self._dedupe(recovery)),
            scope_rules=tuple(self._dedupe(scope)),
            confidence=confidence,
        )

    def _text(self, value: Any) -> str:
        if value is None:
            return ""
        if hasattr(value, "raw_text"):
            return str(getattr(value, "raw_text") or "").strip()
        return str(value).strip()

    @staticmethod
    def _to_dict(value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        try:
            data = value.to_dict()
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _infer_intent(
        self,
        raw: str,
        analysis: dict[str, Any],
    ) -> str:
        declared = str(analysis.get("intent") or "").strip().lower()
        if declared:
            return declared

        for pattern, intent in self._INTENT_PATTERNS:
            if re.search(pattern, raw, re.IGNORECASE):
                return intent

        return "engineering_change"

    def _objective(self, raw: str, intent: str) -> str:
        cleaned = re.sub(r"\s+", " ", raw).strip()
        if len(cleaned) > 700:
            cleaned = cleaned[:697] + "..."
        return f"{intent}: {cleaned}"

    def _acceptance_criteria(
        self,
        raw: str,
        analysis: dict[str, Any],
        changes: list[Any],
    ) -> list[str]:
        criteria: list[str] = []

        for item in analysis.get("acceptance_criteria") or []:
            if str(item).strip():
                criteria.append(str(item).strip())

        for pattern in self._ACCEPTANCE_PATTERNS:
            for match in re.finditer(pattern, raw, re.IGNORECASE):
                value = re.sub(r"\s+", " ", match.group(0)).strip()
                if len(value) >= 8:
                    criteria.append(value)

        if changes:
            criteria.append(
                "Every generated change must be syntactically valid and internally consistent."
            )

        criteria.append(
            "The final workspace must satisfy the original requirement, not merely complete an intermediate step."
        )

        return criteria

    @staticmethod
    def _confidence(
        *,
        raw: str,
        acceptance: list[str],
        repo: dict[str, Any],
        plan: dict[str, Any],
    ) -> str:
        score = 0
        if raw:
            score += 1
        if len(raw) >= 20:
            score += 1
        if acceptance:
            score += 1
        if repo.get("file_count"):
            score += 1
        if plan:
            score += 1

        if score >= 5:
            return "high"
        if score >= 3:
            return "medium"
        return "low"

    @staticmethod
    def _dedupe(items: Iterable[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for item in items:
            value = str(item).strip()
            key = value.casefold()
            if value and key not in seen:
                seen.add(key)
                result.append(value)
        return result

    def build_prompt_section(
        self,
        requirement: Any,
        *,
        requirement_analysis: Any | None = None,
        plan: Any | None = None,
        impact_analysis: Any | None = None,
        repository_context: dict[str, Any] | None = None,
        generated_changes: Iterable[Any] = (),
        failure: Any | None = None,
    ) -> str:
        decision = self.reason(
            requirement,
            requirement_analysis=requirement_analysis,
            plan=plan,
            impact_analysis=impact_analysis,
            repository_context=repository_context,
            generated_changes=generated_changes,
            failure=failure,
        )

        data = decision.to_dict()

        lines = [
            "",
            "AUTONOMOUS ENGINEERING REASONING:",
            "You are not merely completing a file-edit instruction.",
            "You are responsible for satisfying the user's underlying engineering objective.",
            "",
            f"Reasoning version: {self.VERSION}",
            f"Intent: {decision.intent}",
            f"Confidence: {decision.confidence}",
            f"Objective: {decision.objective}",
            "",
            "Acceptance criteria:",
        ]

        lines.extend(f"- {item}" for item in decision.acceptance_criteria)

        lines.extend(["", "Implementation principles:"])
        lines.extend(f"- {item}" for item in decision.implementation_principles)

        lines.extend(["", "Verification strategy:"])
        lines.extend(f"- {item}" for item in decision.verification_strategy)

        lines.extend(["", "Recovery strategy:"])
        lines.extend(f"- {item}" for item in decision.recovery_strategy)

        lines.extend(["", "Scope rules:"])
        lines.extend(f"- {item}" for item in decision.scope_rules)

        lines.extend(
            [
                "",
                "The structured reasoning above is guidance. "
                "Re-evaluate it against the verified repository and execution evidence.",
                "Never claim acceptance without evidence.",
            ]
        )

        return "\n".join(lines)
