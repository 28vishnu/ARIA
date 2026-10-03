from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class WorkspaceInfo:
    workspace_id: str
    root: Path
    source_root: Path
    created_at: str

    def to_dict(self) -> dict:
        data = asdict(self)
        data["root"] = str(self.root)
        data["source_root"] = str(self.source_root)
        return data


class DevelopmentWorkspace:
    """
    Creates isolated development workspaces.

    The source repository is copied into a separate directory.
    Changes made inside the workspace do not modify the original
    repository.
    """

    def __init__(
        self,
        repository_root: str | Path,
        workspace_base: str | Path | None = None,
        max_workspaces: int = 3,
    ) -> None:
        self.repository_root = Path(repository_root).resolve()

        self.workspace_base = (
            Path(workspace_base).expanduser().resolve()
            if workspace_base
            else self.repository_root / ".aria_workspaces"
        )

        self.max_workspaces = max(
            1,
            int(max_workspaces),
        )

    def _validate_repository(self) -> None:
        if not self.repository_root.exists():
            raise FileNotFoundError(
                f"Repository does not exist: {self.repository_root}"
            )

        if not self.repository_root.is_dir():
            raise NotADirectoryError(
                f"Repository root is not a directory: "
                f"{self.repository_root}"
            )

    def _active_workspaces(self) -> list[Path]:
        if not self.workspace_base.exists():
            return []

        return sorted(
            (
                path
                for path in self.workspace_base.iterdir()
                if path.is_dir()
            ),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )

    def _enforce_workspace_limit(self) -> None:
        active = self._active_workspaces()

        for old_workspace in active[self.max_workspaces - 1:]:
            shutil.rmtree(
                old_workspace,
                ignore_errors=True,
            )

    def create(
        self,
        workspace_id: Optional[str] = None,
    ) -> WorkspaceInfo:
        self._validate_repository()

        self.workspace_base.mkdir(
            parents=True,
            exist_ok=True,
        )

        identifier = workspace_id or (
            f"dev-"
            f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-"
            f"{uuid.uuid4().hex[:8]}"
        )

        if (
            not identifier
            or Path(identifier).name != identifier
            or identifier in {".", ".."}
        ):
            raise ValueError(
                "Invalid workspace_id."
            )

        workspace_root = (
            self.workspace_base / identifier
        ).resolve()

        if workspace_root.exists():
            raise FileExistsError(
                f"Workspace already exists: "
                f"{workspace_root}"
            )

        workspace_root.mkdir(
            parents=True,
        )

        source_root = workspace_root / "repo"

        shutil.copytree(
            self.repository_root,
            source_root,
            ignore=shutil.ignore_patterns(
                ".git",
                ".aria_workspaces",
                "__pycache__",
                ".pytest_cache",
                ".mypy_cache",
                ".ruff_cache",
                ".venv",
                "venv",
                "node_modules",
                "dist",
                "build",
            ),
        )

        metadata = WorkspaceInfo(
            workspace_id=identifier,
            root=workspace_root,
            source_root=source_root,
            created_at=_utc_now(),
        )

        (
            workspace_root / "workspace.json"
        ).write_text(
            json.dumps(
                metadata.to_dict(),
                indent=2,
            ),
            encoding="utf-8",
        )

        self._enforce_workspace_limit()

        return metadata

    def exists(
        self,
        workspace_id: str,
    ) -> bool:
        return (
            self.workspace_base / workspace_id
        ).is_dir()

    def get(
        self,
        workspace_id: str,
    ) -> WorkspaceInfo:
        workspace_root = (
            self.workspace_base / workspace_id
        ).resolve()

        metadata_path = (
            workspace_root / "workspace.json"
        )

        if not workspace_root.is_relative_to(
            self.workspace_base.resolve()
        ):
            raise ValueError(
                "Workspace path escapes workspace base."
            )

        if not metadata_path.is_file():
            raise FileNotFoundError(
                f"Workspace metadata not found: "
                f"{workspace_id}"
            )

        data = json.loads(
            metadata_path.read_text(
                encoding="utf-8",
            )
        )

        return WorkspaceInfo(
            workspace_id=data["workspace_id"],
            root=Path(
                data["root"]
            ).resolve(),
            source_root=Path(
                data["source_root"]
            ).resolve(),
            created_at=data["created_at"],
        )

    def destroy(
        self,
        workspace_id: str,
    ) -> None:
        workspace_root = (
            self.workspace_base / workspace_id
        ).resolve()

        if not workspace_root.is_relative_to(
            self.workspace_base.resolve()
        ):
            raise ValueError(
                "Workspace path escapes workspace base."
            )

        if workspace_root == self.workspace_base.resolve():
            raise ValueError(
                "Refusing to destroy workspace base."
            )

        if workspace_root.exists():
            shutil.rmtree(
                workspace_root
            )

    def list_workspaces(
        self,
    ) -> list[WorkspaceInfo]:
        result: list[WorkspaceInfo] = []

        for directory in self._active_workspaces():
            try:
                result.append(
                    self.get(directory.name)
                )
            except (
                OSError,
                ValueError,
                KeyError,
                json.JSONDecodeError,
            ):
                continue

        return result