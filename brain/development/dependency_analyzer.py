from __future__ import annotations

import ast
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class DependencyInfo:
    source_module: str
    target_module: str
    import_type: str

    imported_names: list[str] = field(
        default_factory=list
    )

    line: int = 0
    resolved_local: bool = False


@dataclass
class ModuleInfo:
    module_name: str
    path: str

    is_package: bool = False

    imports: list[str] = field(
        default_factory=list
    )

    imported_by: list[str] = field(
        default_factory=list
    )


@dataclass
class DependencyGraph:
    modules: dict[str, ModuleInfo] = field(
        default_factory=dict
    )

    dependencies: list[DependencyInfo] = field(
        default_factory=list
    )

    unresolved_imports: dict[str, list[str]] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict:

        return {
            "modules": {
                key: asdict(value)
                for key, value in self.modules.items()
            },
            "dependencies": [
                asdict(item)
                for item in self.dependencies
            ],
            "unresolved_imports": self.unresolved_imports,
        }

    def dependencies_of(
        self,
        module_name: str,
    ) -> list[str]:

        module = self.modules.get(
            module_name
        )

        if module is None:
            return []

        return list(
            module.imports
        )

    def dependents_of(
        self,
        module_name: str,
    ) -> list[str]:

        module = self.modules.get(
            module_name
        )

        if module is None:
            return []

        return list(
            module.imported_by
        )


class DependencyAnalyzer:
    """
    Build a static Python dependency graph.

    No project code is imported or executed.
    """

    def build(
        self,
        repository_root: str | Path,
        python_files: Optional[
            list[str | Path]
        ] = None,
    ) -> DependencyGraph:

        root = (
            Path(repository_root)
            .expanduser()
            .resolve()
        )

        if not root.is_dir():
            raise ValueError(
                f"Repository root is not a directory: {root}"
            )

        module_index = self._build_module_index(
            root,
            python_files,
        )

        graph = DependencyGraph()

        for module_name, data in module_index.items():

            graph.modules[module_name] = (
                ModuleInfo(
                    module_name=module_name,
                    path=data["relative"],
                    is_package=data["package"],
                )
            )

        for module_name, data in module_index.items():

            path = Path(
                data["absolute"]
            )

            source = path.read_text(
                encoding="utf-8",
                errors="replace",
            )

            try:

                tree = ast.parse(
                    source,
                    filename=str(path),
                )

            except SyntaxError:
                continue

            for node in ast.walk(tree):

                if isinstance(
                    node,
                    ast.Import,
                ):

                    for alias in node.names:

                        self._add_dependency(
                            graph=graph,
                            source_module=module_name,
                            target=alias.name,
                            imported_names=[
                                alias.name
                            ],
                            import_type="absolute",
                            line=node.lineno,
                            module_index=module_index,
                        )

                elif isinstance(
                    node,
                    ast.ImportFrom,
                ):

                    target = (
                        self._resolve_relative_target(
                            source_module=module_name,
                            module=node.module or "",
                            level=node.level,
                        )
                    )

                    self._add_dependency(
                        graph=graph,
                        source_module=module_name,
                        target=target,
                        imported_names=[
                            alias.name
                            for alias in node.names
                        ],
                        import_type=(
                            "relative"
                            if node.level
                            else "absolute"
                        ),
                        line=node.lineno,
                        module_index=module_index,
                    )

        self._finalize(
            graph
        )

        return graph

    def _build_module_index(
        self,
        root: Path,
        python_files: Optional[
            list[str | Path]
        ],
    ) -> dict:

        if python_files is None:

            paths = root.rglob(
                "*.py"
            )

        else:

            paths = [
                self._resolve_path(
                    root,
                    item,
                )
                for item in python_files
            ]

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

        index = {}

        for path in paths:

            path = Path(path)

            if not path.is_file():
                continue

            try:
                relative = path.relative_to(
                    root
                )
            except ValueError:
                continue

            if any(
                part in ignored
                for part in relative.parts
            ):
                continue

            parts = list(
                relative.parts
            )

            is_package = (
                parts[-1]
                == "__init__.py"
            )

            if is_package:
                parts = parts[:-1]

            else:
                parts[-1] = (
                    parts[-1][:-3]
                )

            if not parts:
                continue

            module_name = ".".join(
                parts
            )

            index[module_name] = {
                "relative": str(
                    relative
                ).replace(
                    "\\",
                    "/",
                ),
                "absolute": str(path),
                "package": is_package,
            }

        return index

    def _add_dependency(
        self,
        graph: DependencyGraph,
        source_module: str,
        target: str,
        imported_names: list[str],
        import_type: str,
        line: int,
        module_index: dict,
    ) -> None:

        if not target:
            return

        resolved = self._resolve_target(
            target,
            module_index,
        )

        final_target = (
            resolved
            if resolved
            else target
        )

        graph.dependencies.append(
            DependencyInfo(
                source_module=source_module,
                target_module=final_target,
                import_type=import_type,
                imported_names=imported_names,
                line=line,
                resolved_local=(
                    resolved is not None
                ),
            )
        )

        if resolved:

            graph.modules[
                source_module
            ].imports.append(
                resolved
            )

        else:

            graph.unresolved_imports.setdefault(
                source_module,
                [],
            ).append(
                target
            )

    @staticmethod
    def _resolve_target(
        target: str,
        module_index: dict,
    ) -> Optional[str]:

        if not target:
            return None

        if target in module_index:
            return target

        if (
            target + ".__init__"
            in module_index
        ):
            return target

        parts = target.split(".")

        while parts:

            candidate = ".".join(
                parts
            )

            if candidate in module_index:
                return candidate

            if (
                candidate + ".__init__"
                in module_index
            ):
                return candidate

            parts.pop()

        return None

    @staticmethod
    def _resolve_relative_target(
        source_module: str,
        module: str,
        level: int,
    ) -> str:

        parts = source_module.split(".")

        if parts:
            parts = parts[:-1]

        for _ in range(
            max(level - 1, 0)
        ):

            if parts:
                parts.pop()

        if module:
            parts.extend(
                module.split(".")
            )

        return ".".join(
            parts
        )

    @staticmethod
    def _finalize(
        graph: DependencyGraph,
    ) -> None:

        for module in graph.modules.values():

            module.imports = sorted(
                set(module.imports)
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

            target.imported_by.append(
                dependency.source_module
            )

        for module in graph.modules.values():

            module.imported_by = sorted(
                set(module.imported_by)
            )

        for key, values in (
            graph.unresolved_imports.items()
        ):

            graph.unresolved_imports[key] = sorted(
                set(values)
            )

    @staticmethod
    def _resolve_path(
        root: Path,
        path: str | Path,
    ) -> Path:

        candidate = Path(path)

        if candidate.is_absolute():
            return candidate.resolve()

        return (
            root / candidate
        ).resolve()


__all__ = [
    "DependencyAnalyzer",
    "DependencyGraph",
    "DependencyInfo",
    "ModuleInfo",
]