"""Repository scanning policy for ARIA autonomous engineering.

The policy provides generic filesystem boundaries for repository intelligence.

Most importantly, ARIA must never treat its own runtime workspaces as part of
the source repository being analyzed. This prevents recursive workspace
discovery such as:

    334 files -> 669 files -> 1004 files

during repeated autonomous attempts.

The policy is descriptive. The actual repository scanner will consume it in a
later integration step.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatch
from typing import Any, Sequence


@dataclass(frozen=True)
class RepositoryScanPolicy:
    """Immutable repository discovery boundaries."""

    policy_version: str = (
        "PHASE1-REPOSITORY-SCAN-POLICY-20261004"
    )

    ignored_directories: tuple[str, ...] = (
        ".git",
        ".aria_workspaces",
        ".aria_runtime",
        ".aria_sessions",
        ".aria_cache",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "venv",
        "env",
        "node_modules",
        "__pycache__",
        ".idea",
        ".vscode",
    )

    ignored_files: tuple[str, ...] = (
        ".DS_Store",
        "Thumbs.db",
    )

    ignored_globs: tuple[str, ...] = (
        "*.pyc",
        "*.pyo",
        "*.log",
        "*.tmp",
        "*.temp",
    )

    protected_globs: tuple[str, ...] = (
        ".env",
        ".env.*",
        "*.pem",
        "*.key",
        "*.crt",
        "*.p12",
        "*.pfx",
    )

    generated_globs: tuple[str, ...] = (
        "*.pyc",
        "*.log",
        "*.tmp",
        "*.temp",
    )

    max_file_size_bytes: int = 5_000_000

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        if self.max_file_size_bytes <= 0:
            raise ValueError(
                "max_file_size_bytes must be positive."
            )

    def should_ignore_directory(
        self,
        name: str,
    ) -> bool:
        value = str(name)

        return value in self.ignored_directories

    def should_ignore_file(
        self,
        name: str,
    ) -> bool:
        value = str(name)

        if value in self.ignored_files:
            return True

        return self.matches_any(
            value,
            self.ignored_globs,
        )

    def is_protected(
        self,
        relative_path: str,
    ) -> bool:
        value = str(
            relative_path
        )

        return self.matches_any(
            value,
            self.protected_globs,
        )

    def is_generated(
        self,
        relative_path: str,
    ) -> bool:
        value = str(
            relative_path
        )

        return self.matches_any(
            value,
            self.generated_globs,
        )

    def is_within_runtime_area(
        self,
        relative_path: str,
    ) -> bool:
        parts = [
            part
            for part in str(
                relative_path
            ).replace(
                "\\",
                "/",
            ).split("/")
            if part
        ]

        return any(
            part in self.ignored_directories
            for part in parts
        )

    @staticmethod
    def matches_any(
        value: str,
        patterns: Sequence[str],
    ) -> bool:
        normalized = value.replace(
            "\\",
            "/",
        )

        return any(
            fnmatch(
                normalized,
                pattern,
            )
            or fnmatch(
                normalized.rsplit(
                    "/",
                    1,
                )[-1],
                pattern,
            )
            for pattern in patterns
        )


DEFAULT_REPOSITORY_SCAN_POLICY = (
    RepositoryScanPolicy()
)


__all__ = [
    "RepositoryScanPolicy",
    "DEFAULT_REPOSITORY_SCAN_POLICY",
]