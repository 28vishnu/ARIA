"""
ARIA Dependency Analyzer
========================

Phase 1 / Step 1

Builds a static dependency graph for a Python repository.

The analyzer does not execute application code.

It uses Python's AST and filesystem information to determine:

    module -> modules it imports

and the reverse relationship:

    module -> modules that import it

This information will later allow ARIA's development planner to
understand the blast radius of a proposed code change.
"""

from __future__ import annotations

import ast
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set


logger = logging.getLogger(
    "aria.development.dependencies"
)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class DependencyInfo:
    """
    One dependency relationship.
    """

    source_module: str
    target_module: str

    import_type: str

    imported_names: List[str] = field(
        default_factory=list
    )

    line: int = 0

    resolved_local: bool = False


@dataclass
class ModuleInfo:
    """
    Static information about one Python module.
    """

    module_name: str
    path: str

    is_package: bool = False

    imports: List[str] = field(
        default_factory=list
    )

    imported_by: List[str] = field(
        default_factory=list
    )


@dataclass
class DependencyGraph:
    """
    Repository-wide dependency graph.
    """

    modules: Dict[str, ModuleInfo] = field(
        default_factory=dict
    )

    dependencies: List[DependencyInfo] = field(
        default_factory=list
    )

    unresolved_imports: Dict[str, List[str]] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict:

        return {
            "modules": {
                name: asdict(info)
                for name, info in self.modules.items()
            },
            "dependencies": [
                asdict(item)
                for item in self.dependencies
            ],
            "unresolved_imports": {
                key: list(value)
                for key, value in self.unresolved_imports.items()
            },
        }

    def dependencies_of(
        self,
        module_name: str,
    ) -> List[str]:

        info = self.modules.get(
            module_name
        )

        if info is None:
            return []

        return list(
            info.imports
        )

    def dependents_of(
        self,
        module_name: str,
    ) -> List[str]:

        info = self.modules.get(
            module_name
        )

        if info is None:
            return []

        return list(
            info.imported_by
        )


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------


class DependencyAnalyzer:
    """
    Static Python dependency graph builder.
    """

    def build(
        self,
        repository_root: str | Path,
        python_files: Optional[
            Iterable[str | Path]
        ] = None,
    ) -> DependencyGraph:
        """
        Build a dependency graph for a repository.

        Args:
            repository_root:
                Root directory of the repository.

            python_files:
                Optional list of files to analyze.

                When omitted, every Python file under the repository
                is discovered automatically.
        """

        root = Path(
            repository_root
        ).expanduser().resolve()

        if not root.is_dir():
            raise ValueError(
                f"Repository root is not a directory: {root}"
            )

        module_index = self._build_module_index(
            root,
            python_files,
        )

        graph = DependencyGraph()

        for module_name, module_data in module_index.items():

            graph.modules[module_name] = ModuleInfo(
                module_name=module_name,
                path=module_data["path"],
                is_package=module_data["is_package"],
            )

        for module_name, module_data in module_index.items():

            path = Path(
                module_data["absolute_path"]
            )

            try:

                source = path.read_text(
                    encoding="utf-8"
                )

            except UnicodeDecodeError:

                source = path.read_text(
                    encoding="utf-8",
                    errors="replace",
                )

            try:

                tree = ast.parse(
                    source,
                    filename=str(path),
                )

            except SyntaxError as exc:

                logger.warning(
                    "[DependencyAnalyzer] "
                    "Skipping invalid Python file %s: %s",
                    path,
                    exc,
                )

                continue

            for node in ast.walk(tree):

                if isinstance(
                    node,
                    ast.Import,
                ):

                    self._process_import(
                        graph=graph,
                        module_name=module_name,
                        imported_module=None,
                        imported_names=[
                            alias.name
                            for alias in node.names
                        ],
                        import_type="absolute",
                        line=node.lineno,
                        module_index=module_index,
                    )

                elif isinstance(
                    node,
                    ast.ImportFrom,
                ):

                    self._process_from_import(
                        graph=graph,
                        module_name=module_name,
                        node=node,
                        module_index=module_index,
                    )

        self._finalize_graph(
            graph
        )

        logger.info(
            "[DependencyAnalyzer] Graph built | "
            "modules=%d dependencies=%d unresolved=%d",
            len(graph.modules),
            len(graph.dependencies),
            sum(
                len(items)
                for items in graph.unresolved_imports.values()
            ),
        )

        return graph

    # ------------------------------------------------------------------
    # Module index
    # ------------------------------------------------------------------

    def _build_module_index(
        self,
        root: Path,
        python_files: Optional[
            Iterable[str | Path]
        ],
    ) -> Dict[str, dict]:

        index: Dict[str, dict] = {}

        if python_files is None:

            paths = root.rglob(
                "*.py"
            )

        else:

            paths = [
                self._resolve_file(
                    root,
                    path,
                )
                for path in python_files
            ]

        for path in paths:

            path = Path(path)

            if not path.exists():
                continue

            if not path.is_file():
                continue

            if self._should_skip(
                path,
                root,
            ):
                continue

            module_name, is_package = (
                self._path_to_module(
                    root,
                    path,
                )
            )

            if not module_name:
                continue

            index[module_name] = {
                "path": self._relative_path(
                    root,
                    path,
                ),
                "absolute_path": str(
                    path
                ),
                "is_package": is_package,
            }

        return index

    # ------------------------------------------------------------------
    # Import processing
    # ------------------------------------------------------------------

    def _process_import(
        self,
        graph: DependencyGraph,
        module_name: str,
        imported_module: Optional[str],
        imported_names: List[str],
        import_type: str,
        line: int,
        module_index: Dict[str, dict],
    ) -> None:

        names = imported_names

        for imported_name in names:

            target = (
                imported_module
                if imported_module
                else imported_name
            )

            resolved = self._resolve_target(
                target,
                module_index,
            )

            dependency = DependencyInfo(
                source_module=module_name,
                target_module=(
                    resolved
                    if resolved
                    else target
                ),
                import_type=import_type,
                imported_names=[
                    imported_name
                ],
                line=line,
                resolved_local=(
                    resolved is not None
                ),
            )

            graph.dependencies.append(
                dependency
            )

            if resolved:

                graph.modules[
                    module_name
                ].imports.append(
                    resolved
                )

            else:

                graph.unresolved_imports.setdefault(
                    module_name,
                    [],
                ).append(
                    target
                )

    def _process_from_import(
        self,
        graph: DependencyGraph,
        module_name: str,
        node: ast.ImportFrom,
        module_index: Dict[str, dict],
    ) -> None:

        base_module = node.module or ""

        target = self._resolve_relative_import(
            source_module=module_name,
            module=node.module,
            level=node.level,
        )

        if target is None:
            target = base_module

        resolved = self._resolve_target(
            target,
            module_index,
        )

        imported_names = [
            alias.name
            for alias in node.names
        ]

        dependency = DependencyInfo(
            source_module=module_name,
            target_module=(
                resolved
                if resolved
                else target
            ),
            import_type=(
                "relative"
                if node.level
                else "absolute"
            ),
            imported_names=imported_names,
            line=node.lineno,
            resolved_local=(
                resolved is not None
            ),
        )

        graph.dependencies.append(
            dependency
        )

        if resolved:

            graph.modules[
                module_name
            ].imports.append(
                resolved
            )

        elif target:

            graph.unresolved_imports.setdefault(
                module_name,
                [],
            ).append(
                target
            )

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_target(
        target: str,
        module_index: Dict[str, dict],
    ) -> Optional[str]:
        """
        Resolve an imported name against repository modules.

        Example:

            brain.core.cognitive_core

        may resolve directly.

        For:

            brain.memory

        we also check whether:
            brain.memory.__init__

        exists as a package.
        """

        if not target:
            return None

        if target in module_index:
            return target

        package_target = (
            f"{target}.__init__"
        )

        if package_target in module_index:
            return target

        parts = target.split(".")

        while parts:

            candidate = ".".join(parts)

            if candidate in module_index:
                return candidate

            package_candidate = (
                f"{candidate}.__init__"
            )

            if package_candidate in module_index:
                return candidate

            parts.pop()

        return None

    def _resolve_relative_import(
        self,
        source_module: str,
        module: Optional[str],
        level: int,
    ) -> Optional[str]:

        if level <= 0:
            return module

        source_parts = source_module.split(
            "."
        )

        # A module itself is not a package.
        # Therefore the first level moves to its parent.
        if source_parts:
            source_parts = source_parts[:-1]

        # level=1 means current package.
        # level=2 means parent package, etc.
        moves = max(
            level - 1,
            0,
        )

        if moves:

            if moves > len(source_parts):
                return module

            source_parts = source_parts[
                : len(source_parts) - moves
            ]

        if module:
            source_parts.append(
                module
            )

        return ".".join(
            part
            for part in source_parts
            if part
        )

    # ------------------------------------------------------------------
    # Graph finalization
    # ------------------------------------------------------------------

    def _finalize_graph(
        self,
        graph: DependencyGraph,
    ) -> None:

        for module in graph.modules.values():

            module.imports = sorted(
                set(module.imports)
            )

            module.imported_by = sorted(
                set(module.imported_by)
            )

        for dependency in graph.dependencies:

            if not dependency.resolved_local:
                continue

            source = graph.modules.get(
                dependency.source_module
            )

            target = graph.modules.get(
                dependency.target_module
            )

            if source is None or target is None:
                continue

            if (
                dependency.target_module
                not in source.imports
            ):
                source.imports.append(
                    dependency.target_module
                )

            if (
                dependency.source_module
                not in target.imported_by
            ):
                target.imported_by.append(
                    dependency.source_module
                )

        for module in graph.modules.values():

            module.imports.sort()
            module.imported_by.sort()

        for key in list(
            graph.unresolved_imports
        ):

            graph.unresolved_imports[key] = sorted(
                set(
                    graph.unresolved_imports[key]
                )
            )

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _path_to_module(
        root: Path,
        path: Path,
    ) -> tuple[str, bool]:

        relative = path.relative_to(
            root
        )

        parts = list(
            relative.parts
        )

        if not parts:
            return "", False

        if parts[-1] == "__init__.py":

            parts = parts[:-1]

            if not parts:
                return "", True

            return ".".join(parts), True

        if parts[-1].endswith(
            ".py"
        ):

            parts[-1] = parts[-1][
                :-3
            ]

        return ".".join(parts), False

    @staticmethod
    def _relative_path(
        root: Path,
        path: Path,
    ) -> str:

        return str(
            path.relative_to(root)
        ).replace(
            "\\",
            "/",
        )

    @staticmethod
    def _resolve_file(
        root: Path,
        path: str | Path,
    ) -> Path:

        candidate = Path(path)

        if not candidate.is_absolute():
            candidate = root / candidate

        return candidate.resolve()

    @staticmethod
    def _should_skip(
        path: Path,
        root: Path,
    ) -> bool:

        ignored = {
            ".git",
            ".venv",
            "venv",
            "__pycache__",
            ".pytest_cache",
            ".mypy_cache",
            ".ruff_cache",
            "node_modules",
            "dist",
            "build",
        }

        try:
            parts = path.relative_to(
                root
            ).parts

        except ValueError:
            return True

        return any(
            part in ignored
            for part in parts
        )


__all__ = [
    "DependencyAnalyzer",
    "DependencyGraph",
    "DependencyInfo",
    "ModuleInfo",
]