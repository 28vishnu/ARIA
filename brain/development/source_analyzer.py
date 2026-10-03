"""
ARIA Source Analyzer
====================

Phase 1 / Step 1

Static source-code analysis for ARIA's self-development system.

The analyzer currently focuses on Python because ARIA itself is
primarily a Python application.

The analyzer is deliberately read-only.

It does not:
    - execute source code
    - import the target module
    - modify files
    - install packages
    - run subprocesses

That makes it suitable for the first stage of ARIA's
self-development pipeline.
"""

from __future__ import annotations

import ast
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional


logger = logging.getLogger("aria.development.source")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class ImportInfo:
    """
    One import statement.
    """

    module: str
    imported_names: List[str] = field(
        default_factory=list
    )
    is_from_import: bool = False
    line: int = 0


@dataclass
class SymbolInfo:
    """
    One source-level symbol.
    """

    name: str
    symbol_type: str

    line_start: int
    line_end: int

    parent: Optional[str] = None

    is_async: bool = False
    is_private: bool = False
    decorators: List[str] = field(
        default_factory=list
    )

    bases: List[str] = field(
        default_factory=list
    )

    arguments: List[str] = field(
        default_factory=list
    )


@dataclass
class CallInfo:
    """
    One function/method call discovered by AST analysis.
    """

    target: str
    line: int


@dataclass
class SourceAnalysis:
    """
    Complete static analysis result for one Python source file.
    """

    path: str

    valid_python: bool

    syntax_error: Optional[str] = None

    imports: List[ImportInfo] = field(
        default_factory=list
    )

    symbols: List[SymbolInfo] = field(
        default_factory=list
    )

    calls: List[CallInfo] = field(
        default_factory=list
    )

    classes: List[str] = field(
        default_factory=list
    )

    functions: List[str] = field(
        default_factory=list
    )

    async_functions: List[str] = field(
        default_factory=list
    )

    constants: List[str] = field(
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
            "classes": list(self.classes),
            "functions": list(self.functions),
            "async_functions": list(
                self.async_functions
            ),
            "constants": list(self.constants),
            "line_count": self.line_count,
        }


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------


class SourceAnalyzer:
    """
    Read-only Python source analyzer.
    """

    def analyze_file(
        self,
        file_path: str | Path,
        repository_root: str | Path | None = None,
    ) -> SourceAnalysis:
        """
        Analyze one Python file.

        The source is parsed with ast.parse().

        The file is never imported or executed.
        """

        path = Path(
            file_path
        ).expanduser().resolve()

        display_path = self._display_path(
            path,
            repository_root,
        )

        if not path.exists():
            raise FileNotFoundError(
                f"Source file does not exist: {path}"
            )

        if not path.is_file():
            raise ValueError(
                f"Source path is not a file: {path}"
            )

        if path.suffix.lower() != ".py":
            raise ValueError(
                f"SourceAnalyzer currently supports Python files only: "
                f"{path}"
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

        line_count = (
            len(source.splitlines())
        )

        try:

            tree = ast.parse(
                source,
                filename=str(path),
            )

        except SyntaxError as exc:

            message = self._format_syntax_error(
                exc
            )

            logger.warning(
                "[SourceAnalyzer] Syntax error in %s: %s",
                display_path,
                message,
            )

            return SourceAnalysis(
                path=display_path,
                valid_python=False,
                syntax_error=message,
                line_count=line_count,
            )

        result = SourceAnalysis(
            path=display_path,
            valid_python=True,
            line_count=line_count,
        )

        visitor = _PythonASTVisitor()

        visitor.visit(tree)

        result.imports = visitor.imports
        result.symbols = visitor.symbols
        result.calls = visitor.calls

        result.classes = visitor.classes
        result.functions = visitor.functions
        result.async_functions = (
            visitor.async_functions
        )
        result.constants = visitor.constants

        logger.debug(
            "[SourceAnalyzer] %s | classes=%d functions=%d imports=%d",
            display_path,
            len(result.classes),
            len(result.functions),
            len(result.imports),
        )

        return result

    def analyze_source(
        self,
        source: str,
        virtual_path: str = "<memory>.py",
    ) -> SourceAnalysis:
        """
        Analyze source code already held in memory.

        This is important later when ARIA generates a candidate patch
        before writing it to disk.
        """

        if not isinstance(
            source,
            str,
        ):
            raise TypeError(
                "source must be a string"
            )

        try:

            tree = ast.parse(
                source,
                filename=virtual_path,
            )

        except SyntaxError as exc:

            return SourceAnalysis(
                path=virtual_path,
                valid_python=False,
                syntax_error=self._format_syntax_error(
                    exc
                ),
                line_count=len(
                    source.splitlines()
                ),
            )

        visitor = _PythonASTVisitor()

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
            line_count=len(
                source.splitlines()
            ),
        )

    def analyze_repository(
        self,
        repository_root: str | Path,
    ) -> List[SourceAnalysis]:
        """
        Analyze every Python file in a repository.

        Generated/cache directories are skipped.
        """

        root = Path(
            repository_root
        ).expanduser().resolve()

        if not root.is_dir():
            raise ValueError(
                f"Repository root is not a directory: {root}"
            )

        results: List[SourceAnalysis] = []

        for path in sorted(
            root.rglob("*.py")
        ):

            if self._should_skip(
                path,
                root,
            ):
                continue

            try:

                results.append(
                    self.analyze_file(
                        path,
                        repository_root=root,
                    )
                )

            except (
                OSError,
                UnicodeError,
                ValueError,
            ) as exc:

                logger.warning(
                    "[SourceAnalyzer] Failed to analyze %s: %s",
                    path,
                    exc,
                )

        logger.info(
            "[SourceAnalyzer] Repository analysis complete | "
            "python_files=%d",
            len(results),
        )

        return results

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _display_path(
        path: Path,
        repository_root: str | Path | None,
    ) -> str:

        if repository_root is None:
            return str(path)

        root = Path(
            repository_root
        ).expanduser().resolve()

        try:

            return str(
                path.relative_to(root)
            ).replace(
                "\\",
                "/",
            )

        except ValueError:

            return str(path)

    @staticmethod
    def _format_syntax_error(
        exc: SyntaxError,
    ) -> str:

        location = ""

        if exc.lineno is not None:
            location = f"line {exc.lineno}"

            if exc.offset is not None:
                location += (
                    f", column {exc.offset}"
                )

        if location:
            return (
                f"{exc.msg} ({location})"
            )

        return exc.msg

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
            relative_parts = path.relative_to(
                root
            ).parts

        except ValueError:
            return True

        return any(
            part in ignored
            for part in relative_parts
        )


# ---------------------------------------------------------------------------
# AST Visitor
# ---------------------------------------------------------------------------


class _PythonASTVisitor(ast.NodeVisitor):
    """
    Internal AST visitor.

    Keeps the public SourceAnalyzer API small and stable.
    """

    def __init__(self) -> None:

        self.imports: List[ImportInfo] = []
        self.symbols: List[SymbolInfo] = []
        self.calls: List[CallInfo] = []

        self.classes: List[str] = []
        self.functions: List[str] = []
        self.async_functions: List[str] = []
        self.constants: List[str] = []

        self._class_stack: List[str] = []

    # ------------------------------------------------------------------
    # Imports
    # ------------------------------------------------------------------

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

        module = node.module or ""

        self.imports.append(
            ImportInfo(
                module=module,
                imported_names=[
                    alias.name
                    for alias in node.names
                ],
                is_from_import=True,
                line=node.lineno,
            )
        )

        self.generic_visit(node)

    # ------------------------------------------------------------------
    # Classes
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Functions
    # ------------------------------------------------------------------

    def visit_FunctionDef(
        self,
        node: ast.FunctionDef,
    ) -> None:

        self._record_function(
            node,
            is_async=False,
        )

    def visit_AsyncFunctionDef(
        self,
        node: ast.AsyncFunctionDef,
    ) -> None:

        self._record_function(
            node,
            is_async=True,
        )

    def _record_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        is_async: bool,
    ) -> None:

        parent = (
            self._class_stack[-1]
            if self._class_stack
            else None
        )

        if parent is None:
            self.functions.append(
                node.name
            )

        else:
            self.functions.append(
                f"{parent}.{node.name}"
            )

        if is_async:
            self.async_functions.append(
                node.name
            )

        arguments = [
            arg.arg
            for arg in (
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

    # ------------------------------------------------------------------
    # Assignments / constants
    # ------------------------------------------------------------------

    def visit_Assign(
        self,
        node: ast.Assign,
    ) -> None:

        for target in node.targets:

            if isinstance(
                target,
                ast.Name,
            ):

                if target.id.isupper():

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

    # ------------------------------------------------------------------
    # Calls
    # ------------------------------------------------------------------

    def visit_Call(
        self,
        node: ast.Call,
    ) -> None:

        target = self._expression_name(
            node.func
        )

        self.calls.append(
            CallInfo(
                target=target,
                line=node.lineno,
            )
        )

        self.generic_visit(node)

    # ------------------------------------------------------------------
    # AST helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _decorators(
        decorators: List[ast.expr],
    ) -> List[str]:

        return [
            _PythonASTVisitor._expression_name(
                decorator
            )
            for decorator in decorators
        ]

    @staticmethod
    def _expression_name(
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

            parent = (
                _PythonASTVisitor._expression_name(
                    node.value
                )
            )

            if parent:
                return f"{parent}.{node.attr}"

            return node.attr

        if isinstance(
            node,
            ast.Call,
        ):
            return (
                _PythonASTVisitor._expression_name(
                    node.func
                )
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