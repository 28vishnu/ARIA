"""
ARIA Repository Manager
=======================

Phase 1 / Step 1

Provides safe, deterministic repository discovery for ARIA's
self-development system.

Responsibilities
----------------
- Discover repository files and directories.
- Ignore generated/cache/runtime directories.
- Calculate file metadata.
- Calculate SHA-256 hashes.
- Detect programming languages.
- Detect configuration files.
- Detect likely application entry points.
- Identify Python packages/modules.
- Identify protected paths.
- Produce a deterministic repository snapshot.

This module DOES NOT modify repository files.

That separation is intentional.

The repository manager is read-only and should be safe to run against
ARIA's production source tree.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set


logger = logging.getLogger("aria.development.repository")


# ---------------------------------------------------------------------------
# Default ignored directories
# ---------------------------------------------------------------------------

DEFAULT_IGNORED_DIRECTORIES: Set[str] = {
    ".git",
    ".github",
    ".idea",
    ".vscode",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".coverage",
    "venv",
    ".venv",
    "env",
    ".env",
    "node_modules",
    "dist",
    "build",
    "site-packages",
    ".eggs",
    "*.egg-info",
}


# ---------------------------------------------------------------------------
# File classification
# ---------------------------------------------------------------------------

LANGUAGE_BY_EXTENSION: Dict[str, str] = {
    ".py": "python",
    ".pyw": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".java": "java",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".go": "go",
    ".rs": "rust",
    ".php": "php",
    ".rb": "ruby",
    ".swift": "swift",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".scss": "scss",
    ".sass": "sass",
    ".sql": "sql",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".ps1": "powershell",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".ini": "ini",
    ".cfg": "config",
    ".conf": "config",
    ".md": "markdown",
    ".txt": "text",
}


CONFIG_FILE_NAMES: Set[str] = {
    "requirements.txt",
    "requirements-dev.txt",
    "requirements-test.txt",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "poetry.lock",
    "pipfile",
    "pipfile.lock",
    "dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yml",
    "compose.yaml",
    ".env",
    ".env.example",
    ".gitignore",
    ".dockerignore",
    "makefile",
    "readme.md",
}


ENTRY_POINT_NAMES: Set[str] = {
    "main.py",
    "app.py",
    "run.py",
    "server.py",
    "manage.py",
    "wsgi.py",
    "asgi.py",
    "cli.py",
    "bot.py",
    "index.js",
    "server.js",
    "app.js",
}


# ---------------------------------------------------------------------------
# Protected paths
# ---------------------------------------------------------------------------

# These paths are classified as protected metadata. The repository manager
# does not block anything itself; later development-policy components will
# decide which modifications require Master approval.
DEFAULT_PROTECTED_PATH_PATTERNS: tuple[str, ...] = (
    ".git/",
    ".github/workflows/",
    ".env",
    ".env.",
    "secrets",
    "secret",
    "credentials",
    "credential",
    "keys",
    "private",
    "certificates",
    "certs",
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FileMetadata:
    """
    Immutable metadata describing one repository file.
    """

    path: str
    name: str
    extension: str
    language: Optional[str]
    size_bytes: int
    sha256: str
    is_configuration: bool
    is_entry_point: bool
    is_protected: bool


@dataclass
class RepositorySnapshot:
    """
    Complete deterministic snapshot of a repository.
    """

    root: str

    directories: List[str] = field(default_factory=list)
    files: List[FileMetadata] = field(default_factory=list)

    languages: List[str] = field(default_factory=list)
    configuration_files: List[str] = field(default_factory=list)
    entry_points: List[str] = field(default_factory=list)
    protected_files: List[str] = field(default_factory=list)

    python_packages: List[str] = field(default_factory=list)
    python_modules: List[str] = field(default_factory=list)

    total_files: int = 0
    total_directories: int = 0
    total_size_bytes: int = 0

    def to_dict(self) -> dict:
        """
        Convert the snapshot into a JSON-serializable dictionary.
        """

        return {
            "root": self.root,
            "directories": list(self.directories),
            "files": [
                asdict(file_metadata)
                for file_metadata in self.files
            ],
            "languages": list(self.languages),
            "configuration_files": list(self.configuration_files),
            "entry_points": list(self.entry_points),
            "protected_files": list(self.protected_files),
            "python_packages": list(self.python_packages),
            "python_modules": list(self.python_modules),
            "total_files": self.total_files,
            "total_directories": self.total_directories,
            "total_size_bytes": self.total_size_bytes,
        }


# ---------------------------------------------------------------------------
# Repository Manager
# ---------------------------------------------------------------------------


class RepositoryManager:
    """
    Read-only repository intelligence manager.

    This class deliberately does not modify source code.

    Future components such as CodeWriter, ChangePlanner and
    DevelopmentController will consume the information generated here.
    """

    def __init__(
        self,
        ignored_directories: Optional[Iterable[str]] = None,
        protected_patterns: Optional[Iterable[str]] = None,
        max_file_size_bytes: int = 10 * 1024 * 1024,
    ) -> None:

        self.ignored_directories = set(
            ignored_directories
            if ignored_directories is not None
            else DEFAULT_IGNORED_DIRECTORIES
        )

        self.protected_patterns = tuple(
            protected_patterns
            if protected_patterns is not None
            else DEFAULT_PROTECTED_PATH_PATTERNS
        )

        self.max_file_size_bytes = max(
            1,
            int(max_file_size_bytes),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def inspect(
        self,
        repository_path: str | Path,
    ) -> RepositorySnapshot:
        """
        Inspect a repository without modifying anything.

        Raises:
            ValueError:
                If the supplied path does not exist or is not a directory.
        """

        root = Path(repository_path).expanduser().resolve()

        if not root.exists():
            raise ValueError(
                f"Repository path does not exist: {root}"
            )

        if not root.is_dir():
            raise ValueError(
                f"Repository path is not a directory: {root}"
            )

        snapshot = RepositorySnapshot(
            root=str(root)
        )

        languages: Set[str] = set()

        for current_root, directory_names, file_names in self._walk(root):

            current_path = Path(current_root)

            for directory_name in sorted(directory_names):

                directory_path = current_path / directory_name

                relative = self._relative_path(
                    directory_path,
                    root,
                )

                snapshot.directories.append(relative)

            for file_name in sorted(file_names):

                file_path = current_path / file_name

                metadata = self._inspect_file(
                    file_path,
                    root,
                )

                if metadata is None:
                    continue

                snapshot.files.append(metadata)

                if metadata.language:
                    languages.add(metadata.language)

                if metadata.is_configuration:
                    snapshot.configuration_files.append(
                        metadata.path
                    )

                if metadata.is_entry_point:
                    snapshot.entry_points.append(
                        metadata.path
                    )

                if metadata.is_protected:
                    snapshot.protected_files.append(
                        metadata.path
                    )

                snapshot.total_size_bytes += metadata.size_bytes

        snapshot.files.sort(
            key=lambda item: item.path
        )

        snapshot.directories.sort()

        snapshot.configuration_files.sort()
        snapshot.entry_points.sort()
        snapshot.protected_files.sort()

        snapshot.languages = sorted(languages)

        self._discover_python_structure(
            root=root,
            snapshot=snapshot,
        )

        snapshot.total_files = len(snapshot.files)
        snapshot.total_directories = len(
            snapshot.directories
        )

        logger.info(
            "[RepositoryManager] Repository inspected | "
            "files=%d directories=%d languages=%s",
            snapshot.total_files,
            snapshot.total_directories,
            ",".join(snapshot.languages),
        )

        return snapshot

    def get_file_metadata(
        self,
        repository_path: str | Path,
        relative_path: str,
    ) -> FileMetadata:
        """
        Inspect one file inside a repository.

        The file must remain inside the repository root.
        """

        root = Path(repository_path).expanduser().resolve()

        if not root.is_dir():
            raise ValueError(
                f"Repository path is not a directory: {root}"
            )

        file_path = (root / relative_path).resolve()

        self._ensure_inside_repository(
            file_path,
            root,
        )

        if not file_path.exists():
            raise FileNotFoundError(
                f"Repository file does not exist: {relative_path}"
            )

        if not file_path.is_file():
            raise ValueError(
                f"Repository path is not a file: {relative_path}"
            )

        metadata = self._inspect_file(
            file_path,
            root,
        )

        if metadata is None:
            raise ValueError(
                f"Unable to inspect file: {relative_path}"
            )

        return metadata

    def file_exists(
        self,
        repository_path: str | Path,
        relative_path: str,
    ) -> bool:
        """
        Return True when the requested relative path exists inside
        the repository.
        """

        root = Path(repository_path).expanduser().resolve()
        candidate = (root / relative_path).resolve()

        try:
            self._ensure_inside_repository(
                candidate,
                root,
            )
        except ValueError:
            return False

        return candidate.exists()

    def is_protected_path(
        self,
        relative_path: str,
    ) -> bool:
        """
        Determine whether a repository path belongs to the protected
        area.

        This is classification only.

        Actual authorization will be handled by the future
        DeploymentPolicy / ApprovalManager components.
        """

        normalized = self._normalize_relative_path(
            relative_path
        )

        lower = normalized.lower()

        for pattern in self.protected_patterns:

            normalized_pattern = (
                pattern.replace("\\", "/")
                .strip("/")
                .lower()
            )

            if not normalized_pattern:
                continue

            if normalized_pattern.endswith("/"):

                if (
                    lower.startswith(
                        normalized_pattern
                    )
                    or f"/{normalized_pattern}" in lower
                ):
                    return True

            elif normalized_pattern in lower:
                return True

        return False

    # ------------------------------------------------------------------
    # Walking
    # ------------------------------------------------------------------

    def _walk(
        self,
        root: Path,
    ):
        """
        Safe os.walk-style repository traversal.

        Symlinked directories are not followed.
        """

        import os

        for current_root, directory_names, file_names in os.walk(
            root,
            topdown=True,
            followlinks=False,
        ):

            directory_names[:] = [
                name
                for name in directory_names
                if not self._is_ignored_directory(name)
            ]

            yield current_root, directory_names, file_names

    def _is_ignored_directory(
        self,
        name: str,
    ) -> bool:
        """
        Check whether a directory should be excluded.
        """

        if name in self.ignored_directories:
            return True

        if name.endswith(".egg-info"):
            return True

        if name.startswith(".") and name not in {
            ".github",
        }:
            return True

        return False

    # ------------------------------------------------------------------
    # File inspection
    # ------------------------------------------------------------------

    def _inspect_file(
        self,
        file_path: Path,
        root: Path,
    ) -> Optional[FileMetadata]:

        try:

            if file_path.is_symlink():
                return None

            stat = file_path.stat()

        except (OSError, PermissionError) as exc:

            logger.warning(
                "[RepositoryManager] Cannot stat %s: %s",
                file_path,
                exc,
            )

            return None

        if stat.st_size > self.max_file_size_bytes:

            logger.warning(
                "[RepositoryManager] Skipping oversized file: %s "
                "(%d bytes)",
                file_path,
                stat.st_size,
            )

            return None

        relative = self._relative_path(
            file_path,
            root,
        )

        extension = file_path.suffix.lower()

        language = LANGUAGE_BY_EXTENSION.get(
            extension
        )

        if (
            not language
            and file_path.name.lower() == "dockerfile"
        ):
            language = "docker"

        try:

            digest = self._sha256(
                file_path
            )

        except (OSError, PermissionError) as exc:

            logger.warning(
                "[RepositoryManager] Cannot hash %s: %s",
                file_path,
                exc,
            )

            return None

        return FileMetadata(
            path=relative,
            name=file_path.name,
            extension=extension,
            language=language,
            size_bytes=stat.st_size,
            sha256=digest,
            is_configuration=self._is_configuration_file(
                file_path
            ),
            is_entry_point=self._is_entry_point(
                file_path
            ),
            is_protected=self.is_protected_path(
                relative
            ),
        )

    @staticmethod
    def _sha256(
        file_path: Path,
        chunk_size: int = 1024 * 1024,
    ) -> str:
        """
        Calculate SHA-256 incrementally.
        """

        digest = hashlib.sha256()

        with file_path.open(
            "rb"
        ) as handle:

            while True:

                chunk = handle.read(
                    chunk_size
                )

                if not chunk:
                    break

                digest.update(chunk)

        return digest.hexdigest()

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    @staticmethod
    def _is_configuration_file(
        file_path: Path,
    ) -> bool:

        name = file_path.name.lower()

        if name in CONFIG_FILE_NAMES:
            return True

        if name.startswith(".env"):
            return True

        return False

    @staticmethod
    def _is_entry_point(
        file_path: Path,
    ) -> bool:

        return file_path.name in ENTRY_POINT_NAMES

    # ------------------------------------------------------------------
    # Python structure
    # ------------------------------------------------------------------

    def _discover_python_structure(
        self,
        root: Path,
        snapshot: RepositorySnapshot,
    ) -> None:
        """
        Discover Python packages and modules.

        A package is a directory containing __init__.py.
        """

        packages: Set[str] = set()
        modules: Set[str] = set()

        for file_metadata in snapshot.files:

            if file_metadata.language != "python":
                continue

            path = Path(file_metadata.path)

            if path.name == "__init__.py":

                package_path = path.parent

                if str(package_path) == ".":
                    continue

                packages.add(
                    self._path_to_module_name(
                        package_path
                    )
                )

            else:

                if path.suffix.lower() != ".py":
                    continue

                modules.add(
                    self._path_to_module_name(
                        path.with_suffix("")
                    )
                )

        snapshot.python_packages = sorted(
            packages
        )

        snapshot.python_modules = sorted(
            modules
        )

    @staticmethod
    def _path_to_module_name(
        path: Path,
    ) -> str:

        parts = [
            part
            for part in path.parts
            if part not in {
                "",
                ".",
            }
        ]

        return ".".join(parts)

    # ------------------------------------------------------------------
    # Path safety
    # ------------------------------------------------------------------

    @staticmethod
    def _ensure_inside_repository(
        candidate: Path,
        root: Path,
    ) -> None:

        try:
            candidate.relative_to(root)

        except ValueError as exc:

            raise ValueError(
                "Path escapes repository root: "
                f"{candidate}"
            ) from exc

    @staticmethod
    def _relative_path(
        path: Path,
        root: Path,
    ) -> str:

        relative = path.relative_to(
            root
        )

        return RepositoryManager._normalize_relative_path(
            relative
        )

    @staticmethod
    def _normalize_relative_path(
        path: str | Path,
    ) -> str:

        return str(path).replace(
            "\\",
            "/",
        ).strip("/")


__all__ = [
    "RepositoryManager",
    "RepositorySnapshot",
    "FileMetadata",
]