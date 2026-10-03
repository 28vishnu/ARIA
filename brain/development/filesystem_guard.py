from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Iterable


class FilesystemGuard:
    """
    Restricts development filesystem operations to an approved
    workspace.

    This guard is deliberately independent of the development
    agent. It can be used by future writers, patchers, test
    runners, and deployment logic.
    """

    DEFAULT_PROTECTED_NAMES = frozenset(
        {
            ".git",
            ".env",
            ".env.local",
            ".env.production",
            ".env.prod",
            "id_rsa",
            "id_ed25519",
        }
    )

    DEFAULT_PROTECTED_DIRS = frozenset(
        {
            ".git",
            ".github/workflows",
            ".aria_workspaces",
        }
    )

    def __init__(
        self,
        workspace_root: str | Path,
        protected_names: Iterable[str] | None = None,
        protected_dirs: Iterable[str] | None = None,
    ) -> None:
        self.workspace_root = (
            Path(workspace_root)
            .expanduser()
            .resolve()
        )

        if not self.workspace_root.exists():
            raise FileNotFoundError(
                f"Workspace does not exist: "
                f"{self.workspace_root}"
            )

        if not self.workspace_root.is_dir():
            raise NotADirectoryError(
                f"Workspace is not a directory: "
                f"{self.workspace_root}"
            )

        self.protected_names = set(
            protected_names
            or self.DEFAULT_PROTECTED_NAMES
        )

        self.protected_dirs = {
            Path(item).as_posix().strip("/")
            for item in (
                protected_dirs
                or self.DEFAULT_PROTECTED_DIRS
            )
        }

    def resolve(
        self,
        path: str | Path,
    ) -> Path:
        candidate = Path(path).expanduser()

        if not candidate.is_absolute():
            candidate = (
                self.workspace_root / candidate
            )

        resolved = candidate.resolve()

        if not resolved.is_relative_to(
            self.workspace_root
        ):
            raise PermissionError(
                f"Path is outside development workspace: "
                f"{path}"
            )

        return resolved

    def _relative(
        self,
        path: Path,
    ) -> Path:
        return path.relative_to(
            self.workspace_root
        )

    def is_protected(
        self,
        path: str | Path,
    ) -> bool:
        resolved = self.resolve(path)

        relative = self._relative(
            resolved
        )

        for part in relative.parts:
            if part in self.protected_names:
                return True

        relative_text = relative.as_posix()

        for protected_dir in self.protected_dirs:
            if (
                relative_text == protected_dir
                or relative_text.startswith(
                    protected_dir + "/"
                )
            ):
                return True

        return False

    def assert_allowed(
        self,
        path: str | Path,
        *,
        allow_missing: bool = True,
        allow_protected: bool = False,
    ) -> Path:
        resolved = self.resolve(path)

        if (
            not allow_missing
            and not resolved.exists()
        ):
            raise FileNotFoundError(
                str(resolved)
            )

        if (
            self.is_protected(resolved)
            and not allow_protected
        ):
            raise PermissionError(
                f"Protected development path: "
                f"{self._relative(resolved).as_posix()}"
            )

        return resolved

    def read_text(
        self,
        path: str | Path,
        encoding: str = "utf-8",
    ) -> str:
        resolved = self.assert_allowed(
            path,
            allow_missing=False,
        )

        if not resolved.is_file():
            raise IsADirectoryError(
                str(resolved)
            )

        return resolved.read_text(
            encoding=encoding
        )

    def write_text(
        self,
        path: str | Path,
        content: str,
        encoding: str = "utf-8",
    ) -> Path:
        resolved = self.assert_allowed(
            path
        )

        if not isinstance(content, str):
            raise TypeError(
                "content must be a string"
            )

        resolved.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        resolved.write_text(
            content,
            encoding=encoding,
        )

        return resolved

    def delete(
        self,
        path: str | Path,
    ) -> None:
        resolved = self.assert_allowed(
            path,
            allow_missing=True,
            allow_protected=False,
        )

        if resolved == self.workspace_root:
            raise PermissionError(
                "Refusing to delete the workspace root."
            )

        if resolved.is_dir():
            shutil.rmtree(resolved)

        elif resolved.exists():
            resolved.unlink()

    def list_files(
        self,
        path: str | Path = ".",
    ) -> list[Path]:
        resolved = self.assert_allowed(
            path,
            allow_missing=False,
        )

        if not resolved.is_dir():
            raise NotADirectoryError(
                str(resolved)
            )

        return sorted(
            path
            for path in resolved.rglob("*")
            if path.is_file()
            and not self.is_protected(path)
        )

    def can_write(
        self,
        path: str | Path,
    ) -> bool:
        try:
            self.assert_allowed(path)
            return True
        except (
            PermissionError,
            OSError,
        ):
            return False

    def environment(self) -> dict[str, str]:
        """
        Returns a sanitized environment for future
        subprocess execution.

        Secrets are deliberately not copied into the
        development environment by this component.
        """

        allowed = {
            "PATH",
            "HOME",
            "LANG",
            "LC_ALL",
            "PYTHONPATH",
            "VIRTUAL_ENV",
        }

        return {
            key: value
            for key, value in os.environ.items()
            if key in allowed
        }