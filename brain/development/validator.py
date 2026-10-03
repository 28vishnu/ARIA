from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from .filesystem_guard import FilesystemGuard


@dataclass(frozen=True)
class ValidationIssue:
    path: str
    severity: str
    message: str
    line: int | None = None
    column: int | None = None

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "severity": self.severity,
            "message": self.message,
            "line": self.line,
            "column": self.column,
        }


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    files_checked: int
    issues: tuple[ValidationIssue, ...] = field(
        default_factory=tuple
    )

    def to_dict(self) -> dict:
        return {
            "valid": self.valid,
            "files_checked": self.files_checked,
            "issues": [
                issue.to_dict()
                for issue in self.issues
            ],
        }


class DevelopmentValidator:
    """
    Static validation for Python source inside a
    development workspace.

    This component does not execute source code.
    """

    def __init__(
        self,
        guard: FilesystemGuard,
        *,
        max_file_size_bytes: int = 10 * 1024 * 1024,
    ) -> None:

        if max_file_size_bytes <= 0:
            raise ValueError(
                "max_file_size_bytes must be positive."
            )

        self.guard = guard
        self.max_file_size_bytes = int(
            max_file_size_bytes
        )

    def validate_file(
        self,
        path: str | Path,
    ) -> tuple[ValidationIssue, ...]:

        resolved = self.guard.assert_allowed(
            path,
            allow_missing=False,
        )

        if not resolved.is_file():
            raise IsADirectoryError(
                str(resolved)
            )

        if resolved.suffix != ".py":
            return ()

        if (
            resolved.stat().st_size
            > self.max_file_size_bytes
        ):
            return (
                ValidationIssue(
                    path=self._relative(resolved),
                    severity="error",
                    message=(
                        "Python file exceeds "
                        "validation size limit."
                    ),
                ),
            )

        try:
            source = resolved.read_text(
                encoding="utf-8"
            )

        except UnicodeDecodeError as exc:
            return (
                ValidationIssue(
                    path=self._relative(resolved),
                    severity="error",
                    message=(
                        f"UTF-8 decode failed: {exc}"
                    ),
                ),
            )

        try:
            ast.parse(
                source,
                filename=str(resolved),
            )

        except SyntaxError as exc:
            return (
                ValidationIssue(
                    path=self._relative(resolved),
                    severity="error",
                    message=exc.msg,
                    line=exc.lineno,
                    column=exc.offset,
                ),
            )

        return ()

    def validate_paths(
        self,
        paths: Iterable[str | Path],
    ) -> ValidationResult:

        issues: list[ValidationIssue] = []
        checked = 0

        for path in paths:

            resolved = self.guard.assert_allowed(
                path,
                allow_missing=False,
            )

            if resolved.suffix != ".py":
                continue

            checked += 1

            issues.extend(
                self.validate_file(
                    resolved
                )
            )

        return ValidationResult(
            valid=not any(
                issue.severity == "error"
                for issue in issues
            ),
            files_checked=checked,
            issues=tuple(issues),
        )

    def validate_repository(
        self,
        *,
        include_tests: bool = True,
    ) -> ValidationResult:

        paths = self.guard.list_files(
            "."
        )

        selected: list[Path] = []

        for path in paths:

            if path.suffix != ".py":
                continue

            relative = (
                path.relative_to(
                    self.guard.workspace_root
                ).as_posix()
            )

            if (
                not include_tests
                and (
                    relative.startswith(
                        "tests/"
                    )
                    or relative.startswith(
                        "test_"
                    )
                    or relative.endswith(
                        "_test.py"
                    )
                )
            ):
                continue

            selected.append(path)

        return self.validate_paths(
            selected
        )

    def _relative(
        self,
        path: Path,
    ) -> str:

        return path.relative_to(
            self.guard.workspace_root
        ).as_posix()