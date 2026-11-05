"""
ARIA Change Impact Planner.

Phase 1 Step 4.

Determines which repository modules/files are likely to be affected by a
requirement before code generation.  It is read-only and evidence based:
ArchitectureIntelligence supplies dependency and reverse-dependency data,
while RequirementIntelligence supplies the structured requirement.

This module never writes files, executes repository code, deploys, or pushes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .architecture_intelligence import ArchitectureIntelligence, ArchitectureSnapshot
from .requirement_intelligence import RequirementAnalysis
from .requirement_parser import Requirement


@dataclass(frozen=True)
class ImpactTarget:
    path: str
    reason: str
    confidence: float = 0.0
    relation: str = "direct"
    risk: str = "low"

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "reason": self.reason,
            "confidence": self.confidence,
            "relation": self.relation,
            "risk": self.risk,
        }


@dataclass(frozen=True)
class ChangeImpactAnalysis:
    requirement: Requirement
    direct_targets: tuple[ImpactTarget, ...] = ()
    dependent_targets: tuple[ImpactTarget, ...] = ()
    related_targets: tuple[ImpactTarget, ...] = ()
    affected_files: tuple[str, ...] = ()
    affected_components: tuple[str, ...] = ()
    protected_affected: tuple[str, ...] = ()
    risk_flags: tuple[str, ...] = ()
    recommended_tests: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    architecture_errors: tuple[str, ...] = ()
    confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def blocked(self) -> bool:
        return bool(self.protected_affected)

    def to_dict(self) -> dict[str, Any]:
        return {
            "requirement": self.requirement.to_dict(),
            "direct_targets": [x.to_dict() for x in self.direct_targets],
            "dependent_targets": [x.to_dict() for x in self.dependent_targets],
            "related_targets": [x.to_dict() for x in self.related_targets],
            "affected_files": list(self.affected_files),
            "affected_components": list(self.affected_components),
            "protected_affected": list(self.protected_affected),
            "risk_flags": list(self.risk_flags),
            "recommended_tests": list(self.recommended_tests),
            "warnings": list(self.warnings),
            "architecture_errors": list(self.architecture_errors),
            "confidence": self.confidence,
            "blocked": self.blocked,
            "metadata": dict(self.metadata),
        }


class ChangeImpactPlanner:
    """Build a conservative static impact map for a development request."""

    _KEYWORD_COMPONENTS = (
        ("telegram", ("telegram", "webhook", "voice", "bot")),
        ("brain/development", ("development", "self-development", "code generation", "workspace", "sandbox", "test runner")),
        ("brain/llm", ("llm", "model", "qwen", "ollama", "groq", "gemini", "mistral", "openrouter")),
        ("brain/memory", ("memory", "remember", "semantic memory", "vector")),
        ("brain/knowledge", ("knowledge", "wikipedia", "wikidata", "retrieval", "ingestion")),
        ("database", ("mongodb", "database", "collection", "schema", "sql")),
        ("github", ("github", "git", "pull request", "commit")),
        ("deployment", ("deploy", "deployment", "production", "render", "docker")),
        ("tests", ("test", "pytest", "unittest", "coverage")),
        ("web", ("fastapi", "api", "endpoint", "http", "web")),
    )

    _TEST_HINTS = (
        ("telegram", ("telegram", "webhook", "voice", "bot"), ("telegram", "webhook")),
        ("database", ("mongodb", "database", "collection", "schema"), ("database", "integration")),
        ("llm", ("llm", "model", "ollama", "qwen", "generation"), ("llm", "generation")),
        ("deployment", ("deploy", "deployment", "production", "docker"), ("deployment", "health")),
        ("web", ("fastapi", "endpoint", "http", "api"), ("api", "integration")),
        ("generic", (), ("targeted", "regression")),
    )

    def __init__(
        self,
        architecture_intelligence: ArchitectureIntelligence | None = None,
        *,
        max_targets: int = 40,
        max_dependency_hops: int = 2,
    ) -> None:
        self.architecture = architecture_intelligence or ArchitectureIntelligence()
        self.max_targets = max(5, int(max_targets))
        self.max_dependency_hops = max(1, int(max_dependency_hops))

    def analyze(
        self,
        requirement_analysis: RequirementAnalysis | Requirement,
        repository_path: str | Path,
        *,
        architecture_snapshot: ArchitectureSnapshot | None = None,
        existing_paths: Iterable[str] = (),
    ) -> ChangeImpactAnalysis:
        if isinstance(requirement_analysis, RequirementAnalysis):
            requirement = requirement_analysis.requirement
            analysis = requirement_analysis
        elif isinstance(requirement_analysis, Requirement):
            requirement = requirement_analysis
            analysis = None
        else:
            raise TypeError("requirement_analysis must be RequirementAnalysis or Requirement")

        snapshot = architecture_snapshot or self.architecture.inspect(repository_path)
        normalized_existing = self._normalize_paths(existing_paths)
        if not normalized_existing:
            normalized_existing = self._snapshot_paths(snapshot)

        direct: list[ImpactTarget] = []
        dependents: list[ImpactTarget] = []
        related: list[ImpactTarget] = []

        # Explicit files are the strongest evidence.
        for raw in requirement.requested_files:
            path = self._normalize_path(raw)
            if not path:
                continue
            if path in normalized_existing or path in snapshot.module_roles or self._looks_like_new_path(path):
                direct.append(ImpactTarget(path, "explicitly requested by the requirement", 1.0, "direct", self._path_risk(path)))
                for affected in self._reverse_dependencies(snapshot, path):
                    if affected != path:
                        dependents.append(ImpactTarget(affected, f"depends on explicitly targeted module {path}", 0.88, "dependent", self._path_risk(affected)))

        lower = str(requirement.raw_text or "").lower()

        # Component/name matching supplies additional evidence when the user
        # describes a capability rather than a file.
        matched_components = self._matched_components(lower, snapshot)
        for component in matched_components:
            info = next((c for c in snapshot.components if c.name == component), None)
            if info is None:
                continue
            for path in info.files[: self.max_targets]:
                if path not in {x.path for x in direct}:
                    related.append(ImpactTarget(path, f"belongs to requirement-matched component {component}", 0.78, "component", self._path_risk(path)))

        # Module role and filename keyword matching catches common requests
        # such as "fix the router" without allowing arbitrary repository-wide
        # modifications.
        for path, role in snapshot.module_roles.items():
            if self._text_matches_path(lower, path, role):
                if path not in {x.path for x in direct + related}:
                    related.append(ImpactTarget(path, f"module name/role matches requirement: {role}", 0.70, "role", self._path_risk(path)))

        direct = self._dedupe_targets(direct)
        dependents = self._dedupe_targets(dependents, exclude={x.path for x in direct})
        related = self._dedupe_targets(related, exclude={x.path for x in direct + dependents})

        direct = direct[: self.max_targets]
        dependents = dependents[: self.max_targets]
        related = related[: self.max_targets]

        affected = self._dedupe_paths([x.path for x in direct + dependents + related])
        components = self._affected_components(affected, snapshot)
        protected = [p for p in affected if self._is_protected(p, snapshot)]

        risks = list(requirement.risk_flags)
        if protected:
            risks.append("protected_impact")
        if len(affected) > 20:
            risks.append("wide_impact")
        if len(dependents) > 10:
            risks.append("high_reverse_dependency_impact")
        if any(x.risk in {"high", "critical"} for x in direct + dependents + related):
            risks.append("high_risk_target")

        warnings: list[str] = []
        if not direct and not related and requirement.requested_files:
            warnings.append("Requested paths could not be mapped to the inspected architecture.")
        if not direct and not related and not requirement.requested_files:
            warnings.append("No concrete impact target was inferred; implementation should not guess a file.")
        if len(affected) >= self.max_targets:
            warnings.append(f"Impact target list capped at {self.max_targets} files.")
        if snapshot.architecture_warnings:
            warnings.extend(snapshot.architecture_warnings[:5])

        tests = self._recommended_tests(lower, affected, snapshot)
        confidence = self._confidence(direct, dependents, related, protected, warnings, analysis)

        metadata = {
            "repository_root": str(Path(repository_path).expanduser().resolve()),
            "direct_target_count": len(direct),
            "dependent_target_count": len(dependents),
            "related_target_count": len(related),
            "affected_file_count": len(affected),
            "affected_component_count": len(components),
            "dependency_hops": self.max_dependency_hops,
        }

        return ChangeImpactAnalysis(
            requirement=requirement,
            direct_targets=tuple(direct),
            dependent_targets=tuple(dependents),
            related_targets=tuple(related),
            affected_files=tuple(affected),
            affected_components=tuple(components),
            protected_affected=tuple(protected),
            risk_flags=tuple(self._dedupe_strings(risks)),
            recommended_tests=tuple(tests),
            warnings=tuple(self._dedupe_strings(warnings)),
            architecture_errors=tuple(snapshot.analysis_errors),
            confidence=confidence,
            metadata=metadata,
        )

    def _reverse_dependencies(self, snapshot: ArchitectureSnapshot, path: str) -> list[str]:
        result: list[str] = []
        queue = [path]
        seen = {path}
        for _ in range(self.max_dependency_hops):
            next_queue: list[str] = []
            for current in queue:
                for candidate in snapshot.change_impact.get(current, []):
                    normalized = self._normalize_path(candidate)
                    if normalized and normalized not in seen:
                        seen.add(normalized)
                        result.append(normalized)
                        next_queue.append(normalized)
            queue = next_queue
            if not queue:
                break
        return result

    def _matched_components(self, text: str, snapshot: ArchitectureSnapshot) -> list[str]:
        matches: list[str] = []
        for name, keywords in self._KEYWORD_COMPONENTS:
            if any(k in text for k in keywords):
                candidates = [c.name for c in snapshot.components if c.name == name or c.root == name or c.name.startswith(name + "/")]
                matches.extend(candidates)
        return self._dedupe_strings(matches)

    @staticmethod
    def _text_matches_path(text: str, path: str, role: str) -> bool:
        tokens = set(replace_non_alnum(path.lower()).split()) | set(replace_non_alnum(role.lower()).split())
        return any(len(t) >= 4 and t in text for t in tokens)

    @staticmethod
    def _affected_components(paths: Iterable[str], snapshot: ArchitectureSnapshot) -> list[str]:
        names: list[str] = []
        for path in paths:
            component = snapshot.module_components.get(path)
            if component:
                names.append(component)
            else:
                for info in snapshot.components:
                    if path in info.files:
                        names.append(info.name)
        return sorted(set(names))

    @staticmethod
    def _snapshot_paths(snapshot: ArchitectureSnapshot) -> set[str]:
        paths: set[str] = set()
        for component in snapshot.components:
            paths.update(ChangeImpactPlanner._normalize_path(p) for p in component.files if ChangeImpactPlanner._normalize_path(p))
        paths.update(ChangeImpactPlanner._normalize_path(p) for p in snapshot.module_roles if ChangeImpactPlanner._normalize_path(p))
        return paths

    @staticmethod
    def _normalize_paths(paths: Iterable[str]) -> set[str]:
        result = set()
        for p in paths:
            n = ChangeImpactPlanner._normalize_path(str(p))
            if n:
                result.add(n)
        return result

    @staticmethod
    def _normalize_path(path: str) -> str | None:
        value = str(path).strip().replace("\\", "/")
        while value.startswith("./"):
            value = value[2:]
        if not value or value.startswith("/") or (len(value) > 1 and value[1] == ":"):
            return None
        parts = [p for p in value.split("/") if p]
        if any(p == ".." for p in parts):
            return None
        return "/".join(parts) or None

    @staticmethod
    def _looks_like_new_path(path: str) -> bool:
        return "." in path.rsplit("/", 1)[-1] or "/" in path

    @staticmethod
    def _path_risk(path: str) -> str:
        lower = path.lower()
        if lower in {"main.py", "core/bootstrap.py", "dockerfile", "requirements.txt", "pyproject.toml"}:
            return "high"
        if any(x in lower for x in (".env", "secret", "credential", "private", ".pem", ".key")):
            return "critical"
        return "low"

    @staticmethod
    def _is_protected(path: str, snapshot: ArchitectureSnapshot) -> bool:
        lower = path.lower()
        if lower in {p.lower() for p in snapshot.protected_areas}:
            return True
        return lower.startswith((".git/", ".github/workflows/", ".aria_workspaces/")) or any(x in lower.rsplit("/", 1)[-1] for x in ("secret", "credential", ".pem", ".key"))

    @staticmethod
    def _dedupe_targets(items: list[ImpactTarget], exclude: set[str] | None = None) -> list[ImpactTarget]:
        seen = set(exclude or ())
        result: list[ImpactTarget] = []
        for item in sorted(items, key=lambda x: (-x.confidence, x.path)):
            if item.path not in seen:
                seen.add(item.path)
                result.append(item)
        return result

    @staticmethod
    def _dedupe_paths(items: Iterable[str]) -> list[str]:
        return list(dict.fromkeys(p for p in items if p))

    @staticmethod
    def _dedupe_strings(items: Iterable[str]) -> list[str]:
        return list(dict.fromkeys(str(x) for x in items if str(x).strip()))

    def _recommended_tests(self, text: str, affected: list[str], snapshot: ArchitectureSnapshot) -> list[str]:
        tests: list[str] = []
        for _, keywords, labels in self._TEST_HINTS:
            if not keywords or any(k in text for k in keywords):
                for label in labels:
                    tests.append(label)
        existing_tests = [p for p in self._snapshot_paths(snapshot) if "/test" in p.lower() or p.lower().startswith("test")]
        tests.extend(existing_tests[:4])
        if affected:
            tests.append("targeted validation for affected modules")
        return self._dedupe_strings(tests)[:12]

    @staticmethod
    def _confidence(direct: list[ImpactTarget], dependents: list[ImpactTarget], related: list[ImpactTarget], protected: list[str], warnings: list[str], analysis: RequirementAnalysis | None) -> float:
        base = 0.35
        if direct:
            base += 0.40
        elif related:
            base += 0.20
        if dependents:
            base += 0.10
        if analysis is not None:
            base += min(0.10, max(0.0, analysis.confidence) * 0.10)
        if protected:
            base -= 0.15
        if warnings:
            base -= min(0.15, 0.03 * len(warnings))
        return round(max(0.0, min(1.0, base)), 3)


def replace_non_alnum(value: str) -> str:
    return "".join(ch if ch.isalnum() else " " for ch in value)
