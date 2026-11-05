"""
ARIA Requirement Intelligence.

Phase 1 Requirement Intelligence converts a Master's natural-language
request into a deterministic development analysis before planning or
code generation.

This module is intentionally side-effect free. It does not:
    - call an LLM
    - modify files
    - execute commands
    - deploy
    - push to GitHub

It builds on RequirementParser so the existing parser remains the
single source of truth for the structured Requirement object.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .requirement_parser import Requirement, RequirementParser


@dataclass(frozen=True)
class RequirementAnalysis:
    """Deterministic machine-readable interpretation of a requirement."""

    requirement: Requirement
    intent: str
    primary_action: str
    scope: str
    explicit_actions: tuple[str, ...] = ()
    entities: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()
    ambiguity_flags: tuple[str, ...] = ()
    clarification_questions: tuple[str, ...] = ()
    confidence: float = 0.0
    ready_for_planning: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "requirement": self.requirement.to_dict(),
            "intent": self.intent,
            "primary_action": self.primary_action,
            "scope": self.scope,
            "explicit_actions": list(self.explicit_actions),
            "entities": list(self.entities),
            "dependencies": list(self.dependencies),
            "ambiguity_flags": list(self.ambiguity_flags),
            "clarification_questions": list(self.clarification_questions),
            "confidence": self.confidence,
            "ready_for_planning": self.ready_for_planning,
            "metadata": dict(self.metadata),
        }


class RequirementIntelligence:
    """Deterministically analyze development requirements."""

    _ACTION_PATTERNS = (
        ("create", r"\b(create|add|generate|make|introduce)\b"),
        ("modify", r"\b(update|modify|change|edit|improve|enhance)\b"),
        ("fix", r"\b(fix|repair|resolve|correct|debug)\b"),
        ("refactor", r"\b(refactor|restructure|reorganize|clean up)\b"),
        ("remove", r"\b(remove|delete|destroy)\b"),
        ("inspect", r"\b(inspect|analy[sz]e|review|audit|check|understand)\b"),
        ("test", r"\b(test|validate|verify)\b"),
        ("deploy", r"\b(deploy|release|publish)\b"),
        ("configure", r"\b(configure|setup|set up|enable|disable)\b"),
    )

    _INTENT_RULES = (
        ("create", ("create", "add", "new file", "new module", "build", "introduce")),
        ("fix", ("fix", "repair", "bug", "error", "broken", "crash", "failure")),
        ("refactor", ("refactor", "restructure", "reorganize", "clean up")),
        ("modify", ("update", "modify", "change", "improve", "enhance", "replace")),
        ("remove", ("remove", "delete", "destroy")),
        ("inspect", ("inspect", "analyze", "analyse", "review", "audit", "understand")),
        ("test", ("test", "validate", "verify")),
        ("deploy", ("deploy", "release", "publish")),
        ("configure", ("configure", "setup", "set up", "enable", "disable")),
    )

    _SCOPE_RULES = (
        ("file", ("file", "filename", "path", "module")),
        ("feature", ("feature", "functionality", "capability", "support")),
        ("bug", ("bug", "error", "failure", "crash", "broken", "issue")),
        ("repository", ("repository", "repo", "project", "codebase", "architecture")),
        ("configuration", ("config", "configuration", ".env", "environment variable")),
        ("database", ("database", "mongodb", "postgres", "mysql", "sql", "collection", "schema")),
        ("deployment", ("deploy", "deployment", "production", "release")),
        ("documentation", ("documentation", "readme", "docs", "document")),
        ("testing", ("test", "tests", "pytest", "unittest", "coverage")),
    )

    _DEPENDENCY_PATTERNS = (
        ("python", r"\bpython\b|\.py\b|pip\b|pytest\b|fastapi\b"),
        ("javascript", r"\bjavascript\b|\bnode(?:\.js)?\b|npm\b|pnpm\b|yarn\b|\.js\b|\.ts\b"),
        ("telegram", r"\btelegram\b|telegram bot|webhook"),
        ("github", r"\bgithub\b|git push|pull request|repository"),
        ("docker", r"\bdocker\b|dockerfile|container"),
        ("mongodb", r"\bmongodb\b|\bmongo\b|motor\b"),
        ("chromadb", r"\bchromadb\b|\bchroma\b"),
        ("ollama", r"\bollama\b"),
        ("llm", r"\bllm\b|language model|qwen|llama|mistral|gemini|groq|openrouter"),
    )

    _VAGUE_TERMS = (
        "something",
        "somehow",
        "better",
        "properly",
        "as needed",
        "etc",
        "and so on",
        "best way",
        "make it good",
        "make it advanced",
        "make it smart",
        "like jarvis",
    )

    _HIGH_RISK_ACTIVE_TERMS = (
        "deploy",
        "production",
        "delete",
        "destroy",
        "remove",
        "secret",
        "credential",
        "private key",
        "sudo",
        "permission",
        "github actions",
        "workflow",
    )

    _NEGATION_RE = re.compile(
        r"\b(?:do not|don't|dont|never|must not|should not|shouldn't|without|avoid|no)\b",
        re.IGNORECASE,
    )

    def __init__(self, parser: RequirementParser | None = None) -> None:
        self.parser = parser or RequirementParser()

    def analyze(self, text: str) -> RequirementAnalysis:
        """Parse and deterministically analyze one requirement."""
        requirement = self.parser.parse(text)
        raw = requirement.raw_text
        lower = raw.lower()

        actions = self._extract_actions(lower)
        intent = self._classify_intent(lower, actions)
        primary_action = self._primary_action(intent, actions)
        scope = self._classify_scope(lower, requirement)
        entities = self._extract_entities(raw, requirement)
        dependencies = self._extract_dependencies(lower)
        ambiguity_flags, questions = self._detect_ambiguity(
            lower,
            requirement,
            intent,
            scope,
        )

        confidence = self._confidence(
            requirement=requirement,
            intent=intent,
            actions=actions,
            scope=scope,
            ambiguity_flags=ambiguity_flags,
        )

        ready = bool(requirement.goals or requirement.requested_files)
        if intent == "unknown" and not requirement.requested_files:
            ready = False
        if "MISSING_TARGET" in ambiguity_flags and not requirement.requested_files:
            ready = False

        active_risk_terms = self._active_risk_terms(lower)
        metadata = {
            "parser": "RequirementParser",
            "parser_version": "phase1",
            "active_risk_terms": active_risk_terms,
            "goal_count": len(requirement.goals),
            "constraint_count": len(requirement.constraints),
            "acceptance_criteria_count": len(requirement.acceptance_criteria),
            "requested_file_count": len(requirement.requested_files),
            "has_explicit_acceptance": bool(requirement.acceptance_criteria),
            "has_explicit_constraints": bool(requirement.constraints),
        }

        return RequirementAnalysis(
            requirement=requirement,
            intent=intent,
            primary_action=primary_action,
            scope=scope,
            explicit_actions=tuple(actions),
            entities=tuple(entities),
            dependencies=tuple(dependencies),
            ambiguity_flags=tuple(ambiguity_flags),
            clarification_questions=tuple(questions),
            confidence=confidence,
            ready_for_planning=ready,
            metadata=metadata,
        )

    def analyze_to_dict(self, text: str) -> dict[str, Any]:
        return self.analyze(text).to_dict()

    def _extract_actions(self, lower: str) -> list[str]:
        found: list[str] = []
        for action, pattern in self._ACTION_PATTERNS:
            for match in re.finditer(pattern, lower):
                prefix = lower[max(0, match.start() - 30):match.start()]
                if self._NEGATION_RE.search(prefix):
                    continue
                if action not in found:
                    found.append(action)
        return found

    def _classify_intent(self, lower: str, actions: list[str]) -> str:
        scores: dict[str, int] = {name: 0 for name, _ in self._INTENT_RULES}
        for name, terms in self._INTENT_RULES:
            scores[name] = sum(2 for term in terms if term in lower)
        for action in actions:
            scores[action] = scores.get(action, 0) + 1
        ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        if not ranked or ranked[0][1] == 0:
            return "unknown"
        if len(ranked) > 1 and ranked[0][1] == ranked[1][1] and ranked[0][1] > 0:
            return "mixed"
        return ranked[0][0]

    @staticmethod
    def _primary_action(intent: str, actions: list[str]) -> str:
        if intent != "mixed" and intent != "unknown":
            return intent
        priority = ("remove", "deploy", "fix", "refactor", "modify", "create", "configure", "test", "inspect")
        for item in priority:
            if item in actions:
                return item
        return "unknown"

    def _classify_scope(self, lower: str, requirement: Requirement) -> str:
        if requirement.requested_files:
            return "file"
        scores = [(scope, sum(1 for term in terms if term in lower)) for scope, terms in self._SCOPE_RULES]
        scores.sort(key=lambda item: (-item[1], item[0]))
        return scores[0][0] if scores and scores[0][1] else "unspecified"

    def _extract_entities(self, raw: str, requirement: Requirement) -> list[str]:
        entities: list[str] = []
        entities.extend(requirement.requested_files)

        for pattern in (
            r"\b(?:telegram|github|docker|mongodb|chromadb|ollama)\b",
            r"\b(?:FastAPI|Python|JavaScript|TypeScript|React|Node\.js)\b",
            r"\b(?:Qwen(?:[- ]Coder)?|Llama|Mistral|Gemini|Groq|OpenRouter)\b",
        ):
            for value in re.findall(pattern, raw, flags=re.IGNORECASE):
                normalized = value.strip()
                if normalized and normalized.lower() not in {x.lower() for x in entities}:
                    entities.append(normalized)
        return entities

    def _extract_dependencies(self, lower: str) -> list[str]:
        found: list[str] = []
        for name, pattern in self._DEPENDENCY_PATTERNS:
            if re.search(pattern, lower, flags=re.IGNORECASE):
                found.append(name)
        return found

    def _detect_ambiguity(
        self,
        lower: str,
        requirement: Requirement,
        intent: str,
        scope: str,
    ) -> tuple[list[str], list[str]]:
        flags: list[str] = []
        questions: list[str] = []

        if intent == "unknown" and not requirement.requested_files:
            flags.append("UNKNOWN_INTENT")
            questions.append("What exact change should ARIA make?")

        if scope == "unspecified" and not requirement.requested_files:
            flags.append("MISSING_TARGET")
            questions.append("Which feature, module, or file should be changed?")

        if any(term in lower for term in self._VAGUE_TERMS):
            flags.append("VAGUE_LANGUAGE")
            questions.append("What concrete behavior or acceptance result is expected?")

        if ("modify" in lower or "change" in lower or "update" in lower) and not requirement.requested_files and scope == "unspecified":
            flags.append("UNBOUNDED_MODIFICATION")
            questions.append("What part of the repository is in scope for modification?")

        if any(term in lower for term in ("deploy", "production", "release")) and not requirement.constraints and not self._has_negated_term(lower, ("deploy", "production", "release")):
            flags.append("DEPLOYMENT_INTENT_UNSPECIFIED")
            questions.append("Should deployment be performed, or only prepared and validated?")

        if "mixed" == intent and len(requirement.goals) > 1:
            flags.append("MULTIPLE_PRIMARY_INTENTS")

        return self._dedupe(flags), self._dedupe(questions)

    def _confidence(
        self,
        *,
        requirement: Requirement,
        intent: str,
        actions: list[str],
        scope: str,
        ambiguity_flags: list[str],
    ) -> float:
        score = 0.45
        if intent not in {"unknown", "mixed"}:
            score += 0.25
        if actions:
            score += 0.10
        if requirement.goals:
            score += 0.08
        if requirement.requested_files:
            score += 0.08
        if requirement.acceptance_criteria:
            score += 0.04
        if requirement.constraints:
            score += 0.04
        if scope != "unspecified":
            score += 0.04
        score -= min(0.35, 0.07 * len(ambiguity_flags))
        return round(max(0.0, min(1.0, score)), 3)

    def _active_risk_terms(self, lower: str) -> list[str]:
        return [term for term in self._HIGH_RISK_ACTIVE_TERMS if self._is_active_term(lower, term)]

    def _is_active_term(self, text: str, term: str) -> bool:
        for match in re.finditer(re.escape(term), text):
            prefix = text[max(0, match.start() - 35):match.start()]
            if not self._NEGATION_RE.search(prefix):
                return True
        return False

    def _has_negated_term(self, text: str, terms: tuple[str, ...]) -> bool:
        return any(not self._is_active_term(text, term) and term in text for term in terms)

    @staticmethod
    def _dedupe(items: list[str]) -> list[str]:
        return list(dict.fromkeys(items))


__all__ = [
    "RequirementAnalysis",
    "RequirementIntelligence",
]
