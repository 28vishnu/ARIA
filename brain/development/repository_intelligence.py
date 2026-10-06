from __future__ import annotations

"""Canonical, read-only repository intelligence for ARIA.

This module is deliberately an adapter, not a second repository engine.
It combines the repository/architecture services already owned by ARIA and
normalizes their outputs into one deterministic snapshot that planning,
engineering, and reasoning layers can consume.

It NEVER writes files, commits, pushes, deploys, or mutates repository state.
"""

import asyncio
import inspect
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

logger = logging.getLogger("aria.repository_intelligence")


@dataclass
class RepositorySnapshot:
    """Normalized read-only repository snapshot."""

    success: bool
    repository_root: str
    request: str
    inventory: Dict[str, Any] = field(default_factory=dict)
    architecture: Dict[str, Any] = field(default_factory=dict)
    dependencies: Dict[str, Any] = field(default_factory=dict)
    relevant_files: List[str] = field(default_factory=list)
    source_evidence: List[Dict[str, Any]] = field(default_factory=list)
    git: Dict[str, Any] = field(default_factory=dict)
    github: Dict[str, Any] = field(default_factory=dict)
    services: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    @property
    def healthy(self) -> bool:
        return bool(self.success)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "healthy": self.healthy,
            "repository_root": self.repository_root,
            "request": self.request,
            "inventory": self.inventory,
            "architecture": self.architecture,
            "dependencies": self.dependencies,
            "relevant_files": list(self.relevant_files),
            "source_evidence": list(self.source_evidence),
            "git": self.git,
            "github": self.github,
            "services": self.services,
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


class RepositoryIntelligence:
    """Canonical read-only gateway over ARIA's existing repository services."""

    VERSION = "ARIA-REPOSITORY-INTELLIGENCE-20261006"

    def __init__(
        self,
        repository_manager: Any = None,
        architecture_intelligence: Any = None,
        deep_repository_reasoner: Any = None,
        git_manager: Any = None,
        github_manager: Any = None,
        source_analyzer: Any = None,
        dependency_analyzer: Any = None,
        repository_analyzer: Any = None,
        code_parser: Any = None,
        dependency_graph: Any = None,
        repository_memory: Any = None,
        repository_root: Optional[str] = None,
        max_files: int = 4000,
        max_evidence: int = 80,
    ) -> None:
        self.repository_manager = repository_manager
        self.architecture_intelligence = architecture_intelligence
        self.deep_repository_reasoner = deep_repository_reasoner
        self.git_manager = git_manager
        self.github_manager = github_manager
        self.source_analyzer = source_analyzer
        self.dependency_analyzer = dependency_analyzer
        self.repository_analyzer = repository_analyzer
        self.code_parser = code_parser
        self.dependency_graph = dependency_graph
        self.repository_memory = repository_memory
        self.repository_root = Path(repository_root or os.getcwd()).resolve()
        self.max_files = max(100, int(max_files))
        self.max_evidence = max(10, int(max_evidence))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def inspect(
        self,
        request: str = "",
        *,
        query: Optional[str] = None,
        include_github: bool = True,
        include_git: bool = True,
        include_source_evidence: bool = True,
        max_files: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Inspect the repository without performing any mutation."""
        text = str(query if query is not None else request or "").strip()
        snapshot = await self._build_snapshot(
            text,
            include_github=include_github,
            include_git=include_git,
            include_source_evidence=include_source_evidence,
            max_files=max_files,
        )
        return snapshot.to_dict()

    async def analyze(
        self,
        request: str = "",
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Compatibility alias for inspect()."""
        return await self.inspect(request, **kwargs)

    async def analyze_repository(
        self,
        request: str = "",
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Compatibility alias used by engineering integrations."""
        return await self.inspect(request, **kwargs)

    async def get_snapshot(
        self,
        request: str = "",
        **kwargs: Any,
    ) -> Dict[str, Any]:
        return await self.inspect(request, **kwargs)

    async def inventory(self, request: str = "") -> Dict[str, Any]:
        """Return only normalized repository inventory."""
        snapshot = await self.inspect(
            request,
            include_github=False,
            include_git=False,
            include_source_evidence=False,
        )
        return snapshot.get("inventory", {})

    async def architecture(self, request: str = "") -> Dict[str, Any]:
        """Return only normalized architecture information."""
        snapshot = await self.inspect(
            request,
            include_github=False,
            include_git=False,
            include_source_evidence=False,
        )
        return snapshot.get("architecture", {})

    async def relevant_files(self, request: str) -> List[str]:
        snapshot = await self.inspect(
            request,
            include_github=False,
            include_git=False,
            include_source_evidence=True,
        )
        return list(snapshot.get("relevant_files", []))

    async def health(self) -> Dict[str, Any]:
        """Return service availability without performing a deep scan."""
        services = {
            "repository_manager": self.repository_manager is not None,
            "architecture_intelligence": self.architecture_intelligence is not None,
            "deep_repository_reasoner": self.deep_repository_reasoner is not None,
            "git_manager": self.git_manager is not None,
            "github_manager": self.github_manager is not None,
            "source_analyzer": self.source_analyzer is not None,
            "dependency_analyzer": self.dependency_analyzer is not None,
            "repository_analyzer": self.repository_analyzer is not None,
            "code_parser": self.code_parser is not None,
            "dependency_graph": self.dependency_graph is not None,
            "repository_memory": self.repository_memory is not None,
        }
        root_exists = self.repository_root.exists() and self.repository_root.is_dir()
        return {
            "healthy": bool(root_exists and any(services.values())),
            "version": self.VERSION,
            "repository_root": str(self.repository_root),
            "repository_root_exists": root_exists,
            "services": services,
            "read_only": True,
            "mutation_allowed": False,
            "commit_allowed": False,
            "github_push_allowed": False,
            "deployment_allowed": False,
        }

    def capabilities(self) -> Dict[str, Any]:
        return {
            "inventory": True,
            "architecture": True,
            "dependencies": True,
            "relevant_files": True,
            "source_evidence": True,
            "git_state": self.git_manager is not None,
            "github_metadata": self.github_manager is not None,
            "read_only": True,
            "mutation": False,
        }

    # ------------------------------------------------------------------
    # Snapshot construction
    # ------------------------------------------------------------------

    async def _build_snapshot(
        self,
        request: str,
        *,
        include_github: bool,
        include_git: bool,
        include_source_evidence: bool,
        max_files: Optional[int],
    ) -> RepositorySnapshot:
        warnings: List[str] = []
        errors: List[str] = []
        services: Dict[str, Any] = {}

        root = self.repository_root
        if not root.exists() or not root.is_dir():
            return RepositorySnapshot(
                success=False,
                repository_root=str(root),
                request=request,
                errors=[f"Repository root does not exist: {root}"],
            )

        # Local inventory is always the authoritative baseline. If an
        # optional analyzer fails, we still have concrete filesystem facts.
        inventory = self._filesystem_inventory(max_files or self.max_files)
        services["filesystem_inventory"] = True

        manager_inventory = await self._safe_service_call(
            self.repository_manager,
            ("inventory", "scan", "analyze", "inspect", "get_inventory", "get_repository_info"),
            request,
        )
        if manager_inventory is not None:
            inventory = self._merge_dict(inventory, self._normalize_mapping(manager_inventory))
            services["repository_manager"] = True
        else:
            services["repository_manager"] = self.repository_manager is None

        architecture = await self._collect_architecture(request, warnings)
        dependencies = await self._collect_dependencies(request, warnings)
        relevant = self._select_relevant_files(request, inventory)

        # Let the architecture/reasoning services contribute candidate paths,
        # but never trust nonexistent paths. This is the main anti-hallucination
        # boundary for downstream LLM reasoning.
        for candidate in self._extract_paths(architecture):
            if self._safe_relative_existing(candidate):
                relevant.append(self._relative(candidate))
        for candidate in self._extract_paths(dependencies):
            if self._safe_relative_existing(candidate):
                relevant.append(self._relative(candidate))
        relevant = self._dedupe_paths(relevant)[: self.max_files]

        evidence: List[Dict[str, Any]] = []
        if include_source_evidence:
            evidence = self._build_source_evidence(request, relevant)
            if not evidence:
                warnings.append("No source evidence matched the request.")

        git_state: Dict[str, Any] = {}
        if include_git and self.git_manager is not None:
            git_state = await self._collect_git_state(warnings)
            services["git_manager"] = True

        github_state: Dict[str, Any] = {}
        if include_github and self.github_manager is not None:
            github_state = await self._collect_github_state(warnings)
            services["github_manager"] = True

        # Optional repository-memory context is supporting evidence only.
        # It never overrides concrete filesystem facts.
        repository_memory = await self._safe_service_call(
            self.repository_memory,
            ("recall", "retrieve", "search", "get"),
            request,
        )
        if repository_memory is not None:
            services["repository_memory"] = True
            architecture = self._merge_dict(
                architecture,
                {"repository_memory_context": self._bounded(repository_memory, 30)},
            )

        success = bool(inventory.get("file_count", 0) >= 0)
        if errors:
            success = False

        return RepositorySnapshot(
            success=success,
            repository_root=str(root),
            request=request,
            inventory=inventory,
            architecture=architecture,
            dependencies=dependencies,
            relevant_files=relevant,
            source_evidence=evidence,
            git=git_state,
            github=github_state,
            services=services,
            warnings=self._dedupe_strings(warnings),
            errors=self._dedupe_strings(errors),
        )

    # ------------------------------------------------------------------
    # Concrete filesystem inventory
    # ------------------------------------------------------------------

    def _filesystem_inventory(self, limit: int) -> Dict[str, Any]:
        files: List[str] = []
        directories: List[str] = []
        extensions: Dict[str, int] = {}
        excluded = {
            ".git",
            ".venv",
            "venv",
            "node_modules",
            "__pycache__",
            ".pytest_cache",
            ".mypy_cache",
            ".ruff_cache",
            ".tox",
            "dist",
            "build",
            ".next",
            ".cache",
        }

        try:
            for path in self.repository_root.rglob("*"):
                if any(part in excluded for part in path.parts):
                    continue
                try:
                    rel = path.relative_to(self.repository_root).as_posix()
                except ValueError:
                    continue
                if path.is_dir():
                    if len(directories) < min(limit, 2000):
                        directories.append(rel)
                    continue
                if not path.is_file():
                    continue
                if len(files) < limit:
                    files.append(rel)
                ext = path.suffix.lower() or "<none>"
                extensions[ext] = extensions.get(ext, 0) + 1
        except Exception as exc:
            logger.warning("[RepositoryIntelligence] filesystem inventory failed: %s", exc)

        files.sort()
        directories.sort()
        return {
            "root": str(self.repository_root),
            "file_count": len(files),
            "directory_count": len(directories),
            "files": files,
            "directories": directories,
            "extensions": dict(sorted(extensions.items(), key=lambda item: (-item[1], item[0]))),
            "inventory_source": "filesystem",
            "authoritative_paths": True,
        }

    # ------------------------------------------------------------------
    # Architecture / dependency analysis
    # ------------------------------------------------------------------

    async def _collect_architecture(self, request: str, warnings: List[str]) -> Dict[str, Any]:
        result: Dict[str, Any] = {}

        for service, methods, label in (
            (
                self.architecture_intelligence,
                ("analyze", "inspect", "analyze_repository", "get_architecture", "build_architecture"),
                "architecture_intelligence",
            ),
            (
                self.deep_repository_reasoner,
                ("analyze", "reason", "inspect", "understand", "analyze_repository"),
                "deep_repository_reasoner",
            ),
            (
                self.repository_analyzer,
                ("analyze", "inspect", "scan", "analyze_repository"),
                "repository_analyzer",
            ),
        ):
            value = await self._safe_service_call(service, methods, request)
            if value is not None:
                result[label] = self._bounded(value, 100)
            elif service is not None:
                warnings.append(f"{label} was unavailable for this inspection.")

        # Deterministic architecture facts from the real tree.
        result["tree_facts"] = self._tree_architecture_facts()
        result["read_only"] = True
        result["path_policy"] = "Only filesystem-existing paths are authoritative."
        return result

    async def _collect_dependencies(self, request: str, warnings: List[str]) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for service, methods, label in (
            (
                self.dependency_analyzer,
                ("analyze", "scan", "build", "analyze_repository", "get_dependencies"),
                "dependency_analyzer",
            ),
            (
                self.dependency_graph,
                ("analyze", "build", "scan", "get_graph", "get_dependencies"),
                "dependency_graph",
            ),
            (
                self.code_parser,
                ("analyze", "parse", "scan", "inspect"),
                "code_parser",
            ),
        ):
            value = await self._safe_service_call(service, methods, request)
            if value is not None:
                result[label] = self._bounded(value, 100)
            elif service is not None:
                warnings.append(f"{label} was unavailable for this inspection.")

        result["declared_files"] = self._dependency_manifest_files()
        result["read_only"] = True
        return result

    def _tree_architecture_facts(self) -> Dict[str, Any]:
        top_level: List[str] = []
        packages: List[str] = []
        for path in self.repository_root.iterdir():
            if path.name in {".git", ".venv", "venv", "node_modules"}:
                continue
            if path.is_dir():
                top_level.append(path.name)
                if (path / "__init__.py").exists():
                    packages.append(path.name)
        return {
            "top_level_entries": sorted(top_level),
            "python_packages": sorted(packages),
            "known_core_paths": [
                p
                for p in (
                    "brain",
                    "core",
                    "actions",
                    "skills",
                    "automation_watchers.py",
                    "main.py",
                )
                if (self.repository_root / p).exists()
            ],
        }

    def _dependency_manifest_files(self) -> List[str]:
        candidates = (
            "requirements.txt",
            "pyproject.toml",
            "Pipfile",
            "poetry.lock",
            "package.json",
            "package-lock.json",
            "yarn.lock",
            "pnpm-lock.yaml",
        )
        return [name for name in candidates if (self.repository_root / name).exists()]

    # ------------------------------------------------------------------
    # Relevance and evidence
    # ------------------------------------------------------------------

    def _select_relevant_files(self, request: str, inventory: Mapping[str, Any]) -> List[str]:
        files = list(inventory.get("files") or [])
        q = request.lower()
        tokens = self._tokens(q)

        # Strong architecture/repository queries should expose the actual
        # bootstrap/core/development tree first.
        structural_terms = (
            "architecture", "repository", "pipeline", "phase 1", "phase1",
            "autonomous engineering", "integration", "bootstrap", "lifecycle",
        )
        scored: List[tuple[int, str]] = []
        for path in files:
            lower = path.lower()
            score = 0
            if any(term in q for term in structural_terms):
                if lower in {"core/bootstrap.py", "brain/core/cognitive_core.py"}:
                    score += 100
                if lower.startswith("brain/development/"):
                    score += 40
                if lower.startswith("brain/integration/"):
                    score += 30
                if lower.startswith("brain/core/"):
                    score += 30
            for token in tokens:
                if len(token) < 3:
                    continue
                if token in Path(lower).name:
                    score += 15
                elif token in lower:
                    score += 5
            if lower.endswith(".py"):
                score += 1
            if score:
                scored.append((score, path))

        scored.sort(key=lambda item: (-item[0], item[1]))
        result = [path for _, path in scored]

        # For broad architecture requests, include the actual tree baseline.
        if any(term in q for term in structural_terms):
            priority = [
                "core/bootstrap.py",
                "brain/core/cognitive_core.py",
                "brain/development/final_autonomous_engineer.py",
                "brain/development/authoritative_engineering_orchestrator.py",
                "brain/development/phase1_persistent_runtime_adapter.py",
                "brain/development/engineering_request_router.py",
                "brain/development/persistent_engineering_runtime.py",
            ]
            result = priority + result

        return self._dedupe_paths([p for p in result if p in files])

    def _build_source_evidence(self, request: str, relevant: Sequence[str]) -> List[Dict[str, Any]]:
        q_tokens = self._tokens(request.lower())
        evidence: List[Dict[str, Any]] = []
        limit = self.max_evidence

        # Read small source files directly. This gives downstream reasoning
        # concrete evidence instead of only filenames.
        for rel in relevant:
            if len(evidence) >= limit:
                break
            path = self.repository_root / rel
            if not path.is_file():
                continue
            if path.suffix.lower() not in {".py", ".toml", ".yaml", ".yml", ".json", ".md", ".txt"}:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            lines = text.splitlines()
            if not lines:
                continue

            matches: List[Dict[str, Any]] = []
            for index, line in enumerate(lines, start=1):
                lower = line.lower()
                if not q_tokens or any(token in lower for token in q_tokens if len(token) >= 4):
                    matches.append({"line": index, "text": line[:500]})
                if len(matches) >= 12:
                    break

            # Always expose a small structural sample for key integration files.
            if not matches and (
                rel in {
                    "core/bootstrap.py",
                    "brain/core/cognitive_core.py",
                    "brain/development/final_autonomous_engineer.py",
                    "brain/development/authoritative_engineering_orchestrator.py",
                }
            ):
                matches = [
                    {"line": i, "text": lines[i - 1][:500]}
                    for i in range(1, min(12, len(lines)) + 1)
                ]

            if matches:
                evidence.append({
                    "path": rel,
                    "exists": True,
                    "line_matches": matches,
                    "evidence_type": "source_file",
                })
        return evidence

    # ------------------------------------------------------------------
    # Git / GitHub read-only metadata
    # ------------------------------------------------------------------

    async def _collect_git_state(self, warnings: List[str]) -> Dict[str, Any]:
        value = await self._safe_service_call(
            self.git_manager,
            (
                "status",
                "get_status",
                "state",
                "get_state",
                "repository_status",
            ),
        )
        if value is not None:
            return self._bounded(value, 40)
        warnings.append("Git state could not be read from GitManager.")
        return {"available": False}

    async def _collect_github_state(self, warnings: List[str]) -> Dict[str, Any]:
        # These are deliberately read-oriented method names. We do not call
        # generic execute/push/sync methods because repository intelligence is
        # never allowed to mutate or trigger delivery.
        value = await self._safe_service_call(
            self.github_manager,
            (
                "repository_info",
                "get_repository_info",
                "get_remote_info",
                "remote_info",
                "repository_metadata",
                "get_metadata",
                "tree",
                "get_tree",
            ),
        )
        if value is not None:
            return self._bounded(value, 60)
        warnings.append("GitHub metadata could not be read from GitHubManager.")
        return {"available": False}

    # ------------------------------------------------------------------
    # Safe adapters
    # ------------------------------------------------------------------

    async def _safe_service_call(
        self,
        service: Any,
        methods: Iterable[str],
        *args: Any,
    ) -> Any:
        if service is None:
            return None
        for method_name in methods:
            method = getattr(service, method_name, None)
            if not callable(method):
                continue
            try:
                value = method(*args)
                if inspect.isawaitable(value):
                    value = await value
                return value
            except TypeError:
                # Some existing services expose the same read operation with
                # a narrower signature. Retry without optional request text.
                if args:
                    try:
                        value = method()
                        if inspect.isawaitable(value):
                            value = await value
                        return value
                    except Exception:
                        continue
            except Exception as exc:
                logger.debug(
                    "[RepositoryIntelligence] %s.%s failed: %s",
                    type(service).__name__,
                    method_name,
                    exc,
                )
                continue
        return None

    # ------------------------------------------------------------------
    # Normalization helpers
    # ------------------------------------------------------------------

    def _safe_relative_existing(self, candidate: Any) -> bool:
        if not candidate:
            return False
        try:
            path = Path(str(candidate))
            if path.is_absolute():
                resolved = path.resolve()
            else:
                resolved = (self.repository_root / path).resolve()
            resolved.relative_to(self.repository_root)
            return resolved.is_file() or resolved.is_dir()
        except Exception:
            return False

    def _relative(self, candidate: Any) -> str:
        path = Path(str(candidate))
        if not path.is_absolute():
            path = self.repository_root / path
        try:
            return path.resolve().relative_to(self.repository_root).as_posix()
        except Exception:
            return str(candidate)

    def _extract_paths(self, value: Any) -> List[str]:
        found: List[str] = []
        if isinstance(value, Mapping):
            for key, item in value.items():
                key_lower = str(key).lower()
                if any(word in key_lower for word in ("path", "file", "module", "target")):
                    found.extend(self._extract_paths(item))
                else:
                    found.extend(self._extract_paths(item))
        elif isinstance(value, (list, tuple, set)):
            for item in value:
                found.extend(self._extract_paths(item))
        elif isinstance(value, str):
            candidate = value.strip().strip("`'\"")
            if self._looks_like_path(candidate):
                found.append(candidate)
        return found[: self.max_files]

    @staticmethod
    def _looks_like_path(value: str) -> bool:
        if not value or len(value) > 500:
            return False
        return (
            "/" in value
            or "\\" in value
            or value.endswith((".py", ".json", ".toml", ".yaml", ".yml", ".md", ".txt"))
        )

    @staticmethod
    def _tokens(text: str) -> List[str]:
        raw = []
        current = []
        for char in text:
            if char.isalnum() or char in "_-":
                current.append(char.lower())
            else:
                if current:
                    raw.append("".join(current))
                    current = []
        if current:
            raw.append("".join(current))
        stop = {
            "the", "and", "for", "with", "from", "that", "this", "what",
            "current", "into", "about", "only", "just", "give", "explain",
            "please", "should", "would", "could", "does", "have", "been",
        }
        return [token for token in raw if len(token) >= 3 and token not in stop][:40]

    @staticmethod
    def _dedupe_paths(values: Iterable[str]) -> List[str]:
        seen = set()
        result = []
        for value in values:
            text = str(value).replace("\\", "/").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            result.append(text)
        return result

    @staticmethod
    def _dedupe_strings(values: Iterable[str]) -> List[str]:
        seen = set()
        result = []
        for value in values:
            text = str(value).strip()
            if text and text not in seen:
                seen.add(text)
                result.append(text)
        return result

    @staticmethod
    def _normalize_mapping(value: Any) -> Dict[str, Any]:
        if isinstance(value, Mapping):
            return dict(value)
        if hasattr(value, "to_dict") and callable(value.to_dict):
            try:
                converted = value.to_dict()
                if isinstance(converted, Mapping):
                    return dict(converted)
            except Exception:
                pass
        if hasattr(value, "__dict__"):
            try:
                return dict(vars(value))
            except Exception:
                pass
        return {"value": value}

    @classmethod
    def _merge_dict(cls, left: Mapping[str, Any], right: Mapping[str, Any]) -> Dict[str, Any]:
        result = dict(left)
        for key, value in right.items():
            if key not in result:
                result[key] = value
            elif isinstance(result[key], Mapping) and isinstance(value, Mapping):
                result[key] = cls._merge_dict(result[key], value)
            elif result[key] in (None, "", [], {}):
                result[key] = value
        return result

    @classmethod
    def _bounded(cls, value: Any, depth: int = 50) -> Any:
        """Convert service objects to bounded JSON-like data."""
        if depth <= 0:
            return "<depth-limit>"
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, Mapping):
            result: Dict[str, Any] = {}
            for index, (key, item) in enumerate(value.items()):
                if index >= 100:
                    break
                result[str(key)] = cls._bounded(item, depth - 1)
            return result
        if isinstance(value, (list, tuple, set)):
            return [cls._bounded(item, depth - 1) for item in list(value)[:100]]
        if hasattr(value, "to_dict") and callable(value.to_dict):
            try:
                return cls._bounded(value.to_dict(), depth - 1)
            except Exception:
                pass
        if hasattr(value, "__dict__"):
            try:
                return cls._bounded(vars(value), depth - 1)
            except Exception:
                pass
        return str(value)


__all__ = [
    "RepositorySnapshot",
    "RepositoryIntelligence",
]
