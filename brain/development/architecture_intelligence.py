from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

from .dependency_analyzer import DependencyAnalyzer, DependencyGraph
from .repository_manager import RepositoryManager, RepositorySnapshot
from .source_analyzer import SourceAnalysis, SourceAnalyzer

logger = logging.getLogger("aria.development.architecture")


@dataclass
class ComponentInfo:
    """Static description of one logical repository component."""

    name: str
    root: str
    files: list[str] = field(default_factory=list)
    python_modules: list[str] = field(default_factory=list)
    classes: list[str] = field(default_factory=list)
    functions: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    dependents: list[str] = field(default_factory=list)
    responsibilities: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "root": self.root,
            "files": list(self.files),
            "python_modules": list(self.python_modules),
            "classes": list(self.classes),
            "functions": list(self.functions),
            "dependencies": list(self.dependencies),
            "dependents": list(self.dependents),
            "responsibilities": list(self.responsibilities),
        }


@dataclass
class ArchitectureSnapshot:
    """Read-only architectural model derived from repository evidence."""

    repository: dict[str, Any]
    components: list[ComponentInfo] = field(default_factory=list)
    module_roles: dict[str, str] = field(default_factory=dict)
    module_components: dict[str, str] = field(default_factory=dict)
    change_impact: dict[str, list[str]] = field(default_factory=dict)
    protected_areas: list[str] = field(default_factory=list)
    architecture_warnings: list[str] = field(default_factory=list)
    recommended_locations: dict[str, list[str]] = field(default_factory=dict)
    analysis_errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "repository": self.repository,
            "components": [item.to_dict() for item in self.components],
            "module_roles": dict(self.module_roles),
            "module_components": dict(self.module_components),
            "change_impact": {
                key: list(value)
                for key, value in self.change_impact.items()
            },
            "protected_areas": list(self.protected_areas),
            "architecture_warnings": list(self.architecture_warnings),
            "recommended_locations": {
                key: list(value)
                for key, value in self.recommended_locations.items()
            },
            "analysis_errors": list(self.analysis_errors),
        }


class ArchitectureIntelligence:
    """
    Static architecture-understanding layer for ARIA's development system.

    It does not import, execute, modify, or deploy repository code.  It builds
    an evidence-based model from RepositoryManager, SourceAnalyzer, and
    DependencyAnalyzer output so later development planning can decide where
    a feature belongs and estimate which modules may be affected.
    """

    RESPONSIBILITY_RULES = {
        "brain": "cognitive/brain intelligence and orchestration",
        "brain/development": "self-development, repository engineering, testing and deployment",
        "brain/llm": "language-model routing and generation",
        "brain/memory": "memory and persistence intelligence",
        "brain/knowledge": "knowledge ingestion, retrieval and semantic knowledge",
        "brain/tools": "tool integrations and deterministic capabilities",
        "brain/agents": "agent coordination and specialized agents",
        "brain/reasoning": "reasoning and decision support",
        "brain/planner": "planning and task decomposition",
        "brain/executor": "workflow/tool execution",
        "brain/security": "security, authorization and protected operations",
        "tests": "automated tests",
        "test": "automated tests",
        "docs": "documentation",
        "scripts": "operational/development scripts",
        "config": "configuration",
        "web": "web/application interface",
        "api": "API interface",
        "telegram": "Telegram interface/integration",
    }

    ROLE_RULES = (
        ("manager", "management/coordinator"),
        ("controller", "controller/orchestration"),
        ("router", "routing"),
        ("analyzer", "analysis"),
        ("parser", "parsing"),
        ("planner", "planning"),
        ("executor", "execution"),
        ("writer", "code/file writing"),
        ("validator", "validation"),
        ("runner", "execution/testing"),
        ("test", "testing"),
        ("deployment", "deployment"),
        ("rollback", "rollback/recovery"),
        ("monitor", "monitoring"),
        ("repository", "repository management"),
        ("github", "GitHub integration"),
        ("git", "version control"),
        ("memory", "memory/persistence"),
        ("knowledge", "knowledge"),
        ("search", "search/retrieval"),
        ("api", "API integration"),
        ("client", "external/service client"),
        ("service", "service layer"),
        ("model", "data/model layer"),
        ("schema", "schema/data contract"),
        ("config", "configuration"),
        ("security", "security"),
        ("auth", "authentication/authorization"),
    )

    def __init__(
        self,
        repository_manager: Optional[RepositoryManager] = None,
        source_analyzer: Optional[SourceAnalyzer] = None,
        dependency_analyzer: Optional[DependencyAnalyzer] = None,
        max_source_files: int = 2000,
    ) -> None:
        self.repository_manager = repository_manager or RepositoryManager()
        self.source_analyzer = source_analyzer or SourceAnalyzer()
        self.dependency_analyzer = dependency_analyzer or DependencyAnalyzer()
        self.max_source_files = max(1, int(max_source_files))

    def inspect(
        self,
        repository_path: str | Path,
        *,
        source_analyses: Optional[dict[str, SourceAnalysis]] = None,
        dependency_graph: Optional[DependencyGraph] = None,
    ) -> ArchitectureSnapshot:
        """Build a complete static architecture snapshot."""
        root = Path(repository_path).expanduser().resolve()
        snapshot = self.repository_manager.inspect(root)
        errors: list[str] = []

        if source_analyses is None:
            source_analyses = self._analyze_sources(root, snapshot, errors)

        if dependency_graph is None:
            try:
                python_files = [item.path for item in snapshot.files if item.language == "python"]
                dependency_graph = self.dependency_analyzer.build(
                    root,
                    python_files=python_files,
                )
            except Exception as exc:
                dependency_graph = DependencyGraph()
                errors.append(f"dependency analysis failed: {exc}")
                logger.exception("[ArchitectureIntelligence] Dependency analysis failed")

        components = self._build_components(root, snapshot, source_analyses, dependency_graph)
        module_roles = self._build_module_roles(snapshot, source_analyses)
        module_components = self._build_module_components(snapshot)
        impact = self._build_change_impact(dependency_graph)
        protected = sorted(snapshot.protected_files)
        warnings = self._architecture_warnings(snapshot, source_analyses, dependency_graph)
        locations = self._recommended_locations(snapshot)

        return ArchitectureSnapshot(
            repository={
                "root": str(root),
                "project_type": self._project_type(snapshot),
                "languages": list(snapshot.languages),
                "entry_points": list(snapshot.entry_points),
                "configuration_files": list(snapshot.configuration_files),
                "total_files": snapshot.total_files,
                "total_directories": snapshot.total_directories,
                "total_size_bytes": snapshot.total_size_bytes,
                "python_packages": list(snapshot.python_packages),
                "python_modules": list(snapshot.python_modules),
            },
            components=components,
            module_roles=module_roles,
            module_components=module_components,
            change_impact=impact,
            protected_areas=protected,
            architecture_warnings=warnings,
            recommended_locations=locations,
            analysis_errors=errors,
        )

    def inspect_to_dict(self, repository_path: str | Path) -> dict[str, Any]:
        return self.inspect(repository_path).to_dict()

    def find_affected_modules(
        self,
        repository_path: str | Path,
        changed_modules: Iterable[str],
        *,
        dependency_graph: Optional[DependencyGraph] = None,
    ) -> dict[str, list[str]]:
        """Return direct and transitive dependents of changed modules."""
        root = Path(repository_path).expanduser().resolve()
        if dependency_graph is None:
            snapshot = self.repository_manager.inspect(root)
            python_files = [item.path for item in snapshot.files if item.language == "python"]
            dependency_graph = self.dependency_analyzer.build(root, python_files=python_files)

        result: dict[str, list[str]] = {}
        for module in changed_modules:
            result[module] = self._transitive_dependents(dependency_graph, module)
        return result

    def recommend_locations(
        self,
        repository_path: str | Path,
        requirement_keywords: Iterable[str],
    ) -> list[str]:
        """Recommend existing repository directories from static evidence."""
        snapshot = self.repository_manager.inspect(repository_path)
        keywords = {str(item).lower().strip() for item in requirement_keywords if str(item).strip()}
        scored: list[tuple[int, str]] = []
        for directory in snapshot.directories:
            lowered = directory.lower()
            score = sum(3 for keyword in keywords if keyword in lowered)
            if score:
                scored.append((score, directory))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [directory for _, directory in scored[:10]]

    def _analyze_sources(
        self,
        root: Path,
        snapshot: RepositorySnapshot,
        errors: list[str],
    ) -> dict[str, SourceAnalysis]:
        results: dict[str, SourceAnalysis] = {}
        python_paths = [
            item.path
            for item in snapshot.files
            if item.language == "python" and not item.is_protected
        ]
        for relative in python_paths[: self.max_source_files]:
            path = root / relative
            try:
                results[relative] = self.source_analyzer.analyze_file(path, root)
            except Exception as exc:
                errors.append(f"source analysis failed for {relative}: {exc}")
        if len(python_paths) > self.max_source_files:
            errors.append(
                f"source analysis limited to {self.max_source_files} files out of {len(python_paths)}"
            )
        return results

    def _build_components(
        self,
        root: Path,
        snapshot: RepositorySnapshot,
        analyses: dict[str, SourceAnalysis],
        graph: DependencyGraph,
    ) -> list[ComponentInfo]:
        grouped: dict[str, list[str]] = defaultdict(list)
        for item in snapshot.files:
            component = self._component_for_path(item.path)
            grouped[component].append(item.path)

        module_to_component = self._build_module_components(snapshot)
        components: list[ComponentInfo] = []
        for name, files in sorted(grouped.items()):
            modules = [module for module in graph.modules if module_to_component.get(module) == name]
            classes: list[str] = []
            functions: list[str] = []
            deps: set[str] = set()
            dependents: set[str] = set()
            roles: Counter[str] = Counter()

            for relative in files:
                analysis = analyses.get(relative)
                if analysis:
                    classes.extend(analysis.classes)
                    functions.extend(analysis.functions)
                    role = self._role_for_path(relative)
                    if role:
                        roles[role] += 1

            for module in modules:
                info = graph.modules[module]
                for target in info.imports:
                    component = module_to_component.get(target)
                    if component and component != name:
                        deps.add(component)
                for source in info.imported_by:
                    component = module_to_component.get(source)
                    if component and component != name:
                        dependents.add(component)

            responsibilities = [role for role, _ in roles.most_common(5)]
            if not responsibilities:
                responsibilities = [self._responsibility_for_component(name)]

            components.append(
                ComponentInfo(
                    name=name,
                    root=self._component_root(files),
                    files=sorted(files),
                    python_modules=sorted(modules),
                    classes=sorted(set(classes)),
                    functions=sorted(set(functions)),
                    dependencies=sorted(deps),
                    dependents=sorted(dependents),
                    responsibilities=responsibilities,
                )
            )
        return components

    def _build_module_roles(
        self,
        snapshot: RepositorySnapshot,
        analyses: dict[str, SourceAnalysis],
    ) -> dict[str, str]:
        roles: dict[str, str] = {}
        for item in snapshot.files:
            if item.language != "python":
                continue
            role = self._role_for_path(item.path)
            analysis = analyses.get(item.path)
            if analysis and analysis.classes:
                class_names = " ".join(analysis.classes).lower()
                role = role or self._role_from_text(class_names)
            if role:
                roles[item.path] = role
        return roles

    def _build_module_components(self, snapshot: RepositorySnapshot) -> dict[str, str]:
        mapping: dict[str, str] = {}
        package_roots = set(snapshot.python_packages)
        for relative in snapshot.python_modules:
            component = self._component_for_path(relative)
            module = relative[:-3] if relative.endswith(".py") else relative
            module = module.replace("/", ".")
            if module.endswith(".__init__"):
                module = module[:-9]
            mapping[module] = component
        # Keep known package roots discoverable even if no __init__ mapping exists.
        for package in package_roots:
            mapping.setdefault(package.replace("/", "."), self._component_for_path(package))
        return mapping

    def _build_change_impact(self, graph: DependencyGraph) -> dict[str, list[str]]:
        return {
            module: self._transitive_dependents(graph, module)
            for module in sorted(graph.modules)
        }

    def _transitive_dependents(self, graph: DependencyGraph, module: str) -> list[str]:
        seen: set[str] = set()
        queue = list(graph.dependents_of(module))
        while queue:
            current = queue.pop(0)
            if current in seen or current == module:
                continue
            seen.add(current)
            queue.extend(graph.dependents_of(current))
        return sorted(seen)

    def _architecture_warnings(
        self,
        snapshot: RepositorySnapshot,
        analyses: dict[str, SourceAnalysis],
        graph: DependencyGraph,
    ) -> list[str]:
        warnings: list[str] = []
        syntax_errors = [path for path, analysis in analyses.items() if not analysis.valid_python]
        if syntax_errors:
            warnings.append(f"Python syntax errors detected in {len(syntax_errors)} analyzed file(s).")

        high_fan_in = [
            module
            for module, info in graph.modules.items()
            if len(info.imported_by) >= 15
        ]
        if high_fan_in:
            warnings.append(
                f"High fan-in modules detected: {', '.join(sorted(high_fan_in)[:10])}."
            )

        protected = set(snapshot.protected_files)
        if protected:
            warnings.append(
                f"Protected paths detected: {len(protected)}. Changes require elevated policy review."
            )

        return warnings

    def _recommended_locations(self, snapshot: RepositorySnapshot) -> dict[str, list[str]]:
        result: dict[str, list[str]] = defaultdict(list)
        for directory in snapshot.directories:
            lowered = directory.lower().replace("\\", "/")
            for key, responsibility in self.RESPONSIBILITY_RULES.items():
                if lowered == key or lowered.startswith(key + "/") or f"/{key}/" in "/" + lowered + "/":
                    result[responsibility].append(directory)
        return {key: sorted(set(value)) for key, value in sorted(result.items())}

    def _project_type(self, snapshot: RepositorySnapshot) -> str:
        names = {Path(item.path).name.lower() for item in snapshot.files}
        languages = set(snapshot.languages)
        if "package.json" in names and "python" in languages:
            return "python-javascript"
        if "package.json" in names:
            return "javascript"
        if "pyproject.toml" in names or "requirements.txt" in names or "python" in languages:
            return "python"
        if "dockerfile" in names:
            return "containerized-multi-language"
        return "multi-language" if len(languages) > 1 else (next(iter(languages)) if languages else "unknown")

    def _component_for_path(self, relative: str) -> str:
        normalized = relative.replace("\\", "/").strip("/")
        parts = normalized.split("/") if normalized else []
        if not parts:
            return "."
        if parts[0] == "brain" and len(parts) >= 2:
            return "/".join(parts[:2])
        return parts[0]

    def _component_root(self, files: list[str]) -> str:
        if not files:
            return "."
        first = files[0].replace("\\", "/")
        return first.split("/")[0]

    def _responsibility_for_component(self, component: str) -> str:
        lowered = component.lower()
        for key, responsibility in self.RESPONSIBILITY_RULES.items():
            if key in lowered:
                return responsibility
        return "repository component"

    def _role_for_path(self, relative: str) -> Optional[str]:
        stem = Path(relative).stem.lower()
        return self._role_from_text(stem)

    def _role_from_text(self, text: str) -> Optional[str]:
        lowered = text.lower().replace("-", "_")
        for token, role in self.ROLE_RULES:
            if token in lowered:
                return role
        return None

    @staticmethod
    def to_json(snapshot: ArchitectureSnapshot, *, indent: int = 2) -> str:
        return json.dumps(snapshot.to_dict(), indent=indent, ensure_ascii=False, sort_keys=True)
