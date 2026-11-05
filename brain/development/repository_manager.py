from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Optional


logger = logging.getLogger("aria.development.repository")


DEFAULT_IGNORED_DIRECTORIES = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "dist",
    "build",
    ".eggs",
    ".idea",
    ".vscode",
}


LANGUAGE_BY_EXTENSION = {
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


CONFIG_NAMES = {
    "requirements.txt",
    "requirements-dev.txt",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "package.json",
    "package-lock.json",
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


ENTRY_POINT_NAMES = {
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


DEFAULT_PROTECTED_PATTERNS = (
    ".env",
    ".env.",
    "secrets/",
    "secret/",
    "credentials/",
    "credential/",
    "private/",
    "certificates/",
    "certs/",
    ".github/workflows/",
)


@dataclass(frozen=True)
class FileMetadata:
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
    root: str

    directories: list[str] = field(
        default_factory=list
    )

    files: list[FileMetadata] = field(
        default_factory=list
    )

    languages: list[str] = field(
        default_factory=list
    )

    configuration_files: list[str] = field(
        default_factory=list
    )

    entry_points: list[str] = field(
        default_factory=list
    )

    protected_files: list[str] = field(
        default_factory=list
    )

    python_packages: list[str] = field(
        default_factory=list
    )

    python_modules: list[str] = field(
        default_factory=list
    )

    total_files: int = 0
    total_directories: int = 0
    total_size_bytes: int = 0

    def to_dict(self) -> dict:
        return {
            "root": self.root,
            "directories": self.directories,
            "files": [
                asdict(item)
                for item in self.files
            ],
            "languages": self.languages,
            "configuration_files": self.configuration_files,
            "entry_points": self.entry_points,
            "protected_files": self.protected_files,
            "python_packages": self.python_packages,
            "python_modules": self.python_modules,
            "total_files": self.total_files,
            "total_directories": self.total_directories,
            "total_size_bytes": self.total_size_bytes,
        }


class RepositoryManager:
    """
    Read-only repository discovery and metadata service.

    This class never modifies repository files.
    """

    def __init__(
        self,
        ignored_directories: Optional[
            Iterable[str]
        ] = None,
        protected_patterns: Optional[
            Iterable[str]
        ] = None,
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
            else DEFAULT_PROTECTED_PATTERNS
        )

        self.max_file_size_bytes = max(
            1,
            int(max_file_size_bytes),
        )

    def inspect(
        self,
        repository_path: str | Path,
    ) -> RepositorySnapshot:

        root = (
            Path(repository_path)
            .expanduser()
            .resolve()
        )

        if not root.is_dir():
            raise ValueError(
                f"Repository path is not a directory: {root}"
            )

        snapshot = RepositorySnapshot(
            root=str(root)
        )

        languages = set()

        for current_root, directories, files in os.walk(
            root,
            topdown=True,
            followlinks=False,
        ):

            directories[:] = sorted(
                directory
                for directory in directories
                if not self._ignored(directory)
            )

            current = Path(current_root)

            for directory in directories:
                snapshot.directories.append(
                    self._relative(
                        current / directory,
                        root,
                    )
                )

            for filename in sorted(files):

                metadata = self._inspect_file(
                    current / filename,
                    root,
                )

                if metadata is None:
                    continue

                snapshot.files.append(metadata)

                snapshot.total_size_bytes += (
                    metadata.size_bytes
                )

                if metadata.language:
                    languages.add(
                        metadata.language
                    )

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

        snapshot.files.sort(
            key=lambda item: item.path
        )

        snapshot.directories.sort()

        snapshot.configuration_files.sort()
        snapshot.entry_points.sort()
        snapshot.protected_files.sort()

        snapshot.languages = sorted(
            languages
        )

        self._python_structure(
            snapshot
        )

        snapshot.total_files = len(
            snapshot.files
        )

        snapshot.total_directories = len(
            snapshot.directories
        )

        logger.info(
            "[RepositoryManager] "
            "Repository inspected | files=%d directories=%d",
            snapshot.total_files,
            snapshot.total_directories,
        )

        return snapshot

    def get_file_metadata(
        self,
        repository_path: str | Path,
        relative_path: str,
    ) -> FileMetadata:

        root = (
            Path(repository_path)
            .expanduser()
            .resolve()
        )

        path = (
            root / relative_path
        ).resolve()

        self._ensure_inside(
            path,
            root,
        )

        if not path.is_file():
            raise FileNotFoundError(
                relative_path
            )

        result = self._inspect_file(
            path,
            root,
        )

        if result is None:
            raise ValueError(
                f"Unable to inspect file: {relative_path}"
            )

        return result

    def file_exists(
        self,
        repository_path: str | Path,
        relative_path: str,
    ) -> bool:

        root = (
            Path(repository_path)
            .expanduser()
            .resolve()
        )

        path = (
            root / relative_path
        ).resolve()

        try:
            self._ensure_inside(
                path,
                root,
            )
        except ValueError:
            return False

        return path.exists()

    def is_protected_path(
        self,
        relative_path: str,
    ) -> bool:

        value = self._normalize(
            relative_path
        ).lower()

        for pattern in self.protected_patterns:

            normalized = self._normalize(
                pattern
            ).lower()

            if normalized.endswith("/"):
                if (
                    value.startswith(normalized)
                    or f"/{normalized}" in value
                ):
                    return True

            elif (
                value == normalized
                or value.startswith(normalized)
                or f"/{normalized}" in value
            ):
                return True

        return False

    def _inspect_file(
        self,
        path: Path,
        root: Path,
    ) -> Optional[FileMetadata]:

        try:

            if path.is_symlink():
                return None

            size = path.stat().st_size

            if size > self.max_file_size_bytes:
                logger.warning(
                    "[RepositoryManager] "
                    "Skipping oversized file: %s",
                    path,
                )
                return None

            digest = hashlib.sha256()

            with path.open("rb") as handle:

                for chunk in iter(
                    lambda: handle.read(
                        1024 * 1024
                    ),
                    b"",
                ):
                    digest.update(chunk)

        except (
            OSError,
            PermissionError,
        ):

            logger.warning(
                "[RepositoryManager] "
                "Could not inspect file: %s",
                path,
            )

            return None

        name = path.name
        extension = path.suffix.lower()

        language = LANGUAGE_BY_EXTENSION.get(
            extension
        )

        if name.lower() == "dockerfile":
            language = "docker"

        relative = self._relative(
            path,
            root,
        )

        return FileMetadata(
            path=relative,
            name=name,
            extension=extension,
            language=language,
            size_bytes=size,
            sha256=digest.hexdigest(),
            is_configuration=(
                name.lower() in CONFIG_NAMES
                or name.lower().startswith(".env")
            ),
            is_entry_point=(
                name in ENTRY_POINT_NAMES
            ),
            is_protected=self.is_protected_path(
                relative
            ),
        )

    def _python_structure(
        self,
        snapshot: RepositorySnapshot,
    ) -> None:

        packages = set()
        modules = set()

        for item in snapshot.files:

            if item.language != "python":
                continue

            path = Path(item.path)

            if path.name == "__init__.py":

                if path.parent != Path("."):
                    packages.add(
                        ".".join(
                            path.parent.parts
                        )
                    )

            else:

                modules.add(
                    ".".join(
                        path.with_suffix("").parts
                    )
                )

        snapshot.python_packages = sorted(
            packages
        )

        snapshot.python_modules = sorted(
            modules
        )

    def _ignored(
        self,
        name: str,
    ) -> bool:

        return (
            name in self.ignored_directories
            or name.endswith(".egg-info")
        )

    @staticmethod
    def _relative(
        path: Path,
        root: Path,
    ) -> str:

        return str(
            path.relative_to(root)
        ).replace(
            "\\",
            "/",
        )

    @staticmethod
    def _normalize(
        path: str | Path,
    ) -> str:

        return str(path).replace(
            "\\",
            "/",
        ).strip("/")

    @staticmethod
    def _ensure_inside(
        path: Path,
        root: Path,
    ) -> None:

        try:
            path.relative_to(root)

        except ValueError as exc:

            raise ValueError(
                f"Path escapes repository root: {path}"
            ) from exc


__all__ = [
    "RepositoryManager",
    "RepositorySnapshot",
    "FileMetadata",
]