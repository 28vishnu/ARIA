from __future__ import annotations

import ast
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional


logger = logging.getLogger(
    "aria.development.source"
)


@dataclass
class ImportInfo:
    module: str

    imported_names: list[str] = field(
        default_factory=list
    )

    is_from_import: bool = False
    line: int = 0


@dataclass
class SymbolInfo:
    name: str
    symbol_type: str

    line_start: int
    line_end: int

    parent: Optional[str] = None

    is_async: bool = False
    is_private: bool = False

    decorators: list[str] = field(
        default_factory=list
    )

    bases: list[str] = field(
        default_factory=list
    )

    arguments: list[str] = field(
        default_factory=list
    )


@dataclass
class CallInfo:
    target: str
    line: int


@dataclass
class SourceAnalysis:
    path: str
    valid_python: bool

    syntax_error: Optional[str] = None

    imports: list[ImportInfo] = field(
        default_factory=list
    )

    symbols: list[SymbolInfo] = field(
        default_factory=list
    )

    calls: list[CallInfo] = field(
        default_factory=list
    )

    classes: list[str] = field(
        default_factory=list
    )

    functions: list[str] = field(
        default_factory=list
    )

    async_functions: list[str] = field(
        default_factory=list
    )

    constants: list[str] = field(
        default_factory=list
    )

    line_count: int = 0

    def to_dict(self) -> dict:

        return {
            "path": self.path,
            "valid_python": self.valid_python,
            "syntax_error": self.syntax_error,
            "imports": [
                asdict(item)
                for item in self.imports
            ],
            "symbols": [
                asdict(item)
                for item in self.symbols
            ],
            "calls": [
                asdict(item)
                for item in self.calls
            ],
            "classes": self.classes,
            "functions": self.functions,
            "async_functions": self.async_functions,
            "constants": self.constants,
            "line_count": self.line_count,
        }


class SourceAnalyzer:
    """
    Read-only Python AST analyzer.

    It never imports or executes the analyzed source.
    """

    def analyze_file(
        self,
        file_path: str | Path,
        repository_root: str | Path | None = None,
    ) -> SourceAnalysis:

        path = (
            Path(file_path)
            .expanduser()
            .resolve()
        )

        if not path.is_file():
            raise FileNotFoundError(
                str(path)
            )

        if path.suffix.lower() != ".py":
            raise ValueError(
                f"Python file required: {path}"
            )

        display_path = self._display_path(
            path,
            repository_root,
        )

        source = path.read_text(
            encoding="utf-8",
            errors="replace",
        )

        return self.analyze_source(
            source,
            display_path,
        )

    def analyze_source(
        self,
        source: str,
        virtual_path: str = "<memory>.py",
    ) -> SourceAnalysis:

        if not isinstance(source, str):
            raise TypeError(
                "source must be a string"
            )

        line_count = len(
            source.splitlines()
        )

        try:

            tree = ast.parse(
                source,
                filename=virtual_path,
            )

        except SyntaxError as exc:

            location = (
                f"line {exc.lineno}"
                if exc.lineno
                else "unknown location"
            )

            return SourceAnalysis(
                path=virtual_path,
                valid_python=False,
                syntax_error=(
                    f"{exc.msg} ({location})"
                ),
                line_count=line_count,
            )

        visitor = _PythonVisitor()

        visitor.visit(tree)

        return SourceAnalysis(
            path=virtual_path,
            valid_python=True,
            imports=visitor.imports,
            symbols=visitor.symbols,
            calls=visitor.calls,
            classes=visitor.classes,
            functions=visitor.functions,
            async_functions=visitor.async_functions,
            constants=visitor.constants,
            line_count=line_count,
        )

    def analyze_repository(
        self,
        repository_root: str | Path,
    ) -> list[SourceAnalysis]:

        root = (
            Path(repository_root)
            .expanduser()
            .resolve()
        )

        if not root.is_dir():
            raise ValueError(
                f"Repository root is not a directory: {root}"
            )

        results = []

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

        for path in sorted(
            root.rglob("*.py")
        ):

            relative_parts = (
                path.relative_to(root).parts
            )

            if any(
                part in ignored
                for part in relative_parts
            ):
                continue

            try:

                results.append(
                    self.analyze_file(
                        path,
                        root,
                    )
                )

            except (
                OSError,
                UnicodeError,
            ):

                logger.warning(
                    "[SourceAnalyzer] "
                    "Could not analyze %s",
                    path,
                    exc_info=True,
                )

        return results

    @staticmethod
    def _display_path(
        path: Path,
        repository_root: str | Path | None,
    ) -> str:

        if repository_root is None:
            return str(path)

        root = (
            Path(repository_root)
            .expanduser()
            .resolve()
        )

        try:

            return str(
                path.relative_to(root)
            ).replace(
                "\\",
                "/",
            )

        except ValueError:

            return str(path)


class _PythonVisitor(ast.NodeVisitor):

    def __init__(self) -> None:

        self.imports = []
        self.symbols = []
        self.calls = []

        self.classes = []
        self.functions = []
        self.async_functions = []
        self.constants = []

        self._class_stack = []

    def visit_Import(
        self,
        node: ast.Import,
    ) -> None:

        self.imports.append(
            ImportInfo(
                module="",
                imported_names=[
                    alias.name
                    for alias in node.names
                ],
                is_from_import=False,
                line=node.lineno,
            )
        )

        self.generic_visit(node)

    def visit_ImportFrom(
        self,
        node: ast.ImportFrom,
    ) -> None:

        self.imports.append(
            ImportInfo(
                module=node.module or "",
                imported_names=[
                    alias.name
                    for alias in node.names
                ],
                is_from_import=True,
                line=node.lineno,
            )
        )

        self.generic_visit(node)

    def visit_ClassDef(
        self,
        node: ast.ClassDef,
    ) -> None:

        parent = (
            self._class_stack[-1]
            if self._class_stack
            else None
        )

        self.classes.append(
            node.name
        )

        self.symbols.append(
            SymbolInfo(
                name=node.name,
                symbol_type="class",
                line_start=node.lineno,
                line_end=getattr(
                    node,
                    "end_lineno",
                    node.lineno,
                ),
                parent=parent,
                is_private=node.name.startswith(
                    "_"
                ),
                decorators=self._decorators(
                    node.decorator_list
                ),
                bases=[
                    self._expression_name(base)
                    for base in node.bases
                ],
            )
        )

        self._class_stack.append(
            node.name
        )

        self.generic_visit(node)

        self._class_stack.pop()

    def visit_FunctionDef(
        self,
        node: ast.FunctionDef,
    ) -> None:

        self._record_function(
            node,
            False,
        )

    def visit_AsyncFunctionDef(
        self,
        node: ast.AsyncFunctionDef,
    ) -> None:

        self._record_function(
            node,
            True,
        )

    def _record_function(
        self,
        node,
        is_async: bool,
    ) -> None:

        parent = (
            self._class_stack[-1]
            if self._class_stack
            else None
        )

        qualified_name = (
            f"{parent}.{node.name}"
            if parent
            else node.name
        )

        self.functions.append(
            qualified_name
        )

        if is_async:
            self.async_functions.append(
                qualified_name
            )

        arguments = [
            argument.arg
            for argument in (
                list(node.args.posonlyargs)
                + list(node.args.args)
                + list(node.args.kwonlyargs)
            )
        ]

        self.symbols.append(
            SymbolInfo(
                name=node.name,
                symbol_type=(
                    "async_function"
                    if is_async
                    else "function"
                ),
                line_start=node.lineno,
                line_end=getattr(
                    node,
                    "end_lineno",
                    node.lineno,
                ),
                parent=parent,
                is_async=is_async,
                is_private=node.name.startswith(
                    "_"
                ),
                decorators=self._decorators(
                    node.decorator_list
                ),
                arguments=arguments,
            )
        )

        self.generic_visit(node)

    def visit_Assign(
        self,
        node: ast.Assign,
    ) -> None:

        for target in node.targets:

            if (
                isinstance(target, ast.Name)
                and target.id.isupper()
            ):

                self.constants.append(
                    target.id
                )

                self.symbols.append(
                    SymbolInfo(
                        name=target.id,
                        symbol_type="constant",
                        line_start=node.lineno,
                        line_end=getattr(
                            node,
                            "end_lineno",
                            node.lineno,
                        ),
                        parent=(
                            self._class_stack[-1]
                            if self._class_stack
                            else None
                        ),
                        is_private=target.id.startswith(
                            "_"
                        ),
                    )
                )

        self.generic_visit(node)

    def visit_Call(
        self,
        node: ast.Call,
    ) -> None:

        self.calls.append(
            CallInfo(
                target=self._expression_name(
                    node.func
                ),
                line=node.lineno,
            )
        )

        self.generic_visit(node)

    @classmethod
    def _decorators(
        cls,
        nodes,
    ) -> list[str]:

        return [
            cls._expression_name(node)
            for node in nodes
        ]

    @classmethod
    def _expression_name(
        cls,
        node: ast.AST,
    ) -> str:

        if isinstance(
            node,
            ast.Name,
        ):
            return node.id

        if isinstance(
            node,
            ast.Attribute,
        ):

            parent = cls._expression_name(
                node.value
            )

            if parent:
                return (
                    f"{parent}.{node.attr}"
                )

            return node.attr

        if isinstance(
            node,
            ast.Call,
        ):
            return cls._expression_name(
                node.func
            )

        if isinstance(
            node,
            ast.Constant,
        ):
            return repr(node.value)

        return ast.dump(
            node,
            annotate_fields=False,
        )


__all__ = [
    "SourceAnalyzer",
    "SourceAnalysis",
    "ImportInfo",
    "SymbolInfo",
    "CallInfo",
]