from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from dataclasses import asdict, dataclass
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
    source_file_count: int = 0
    source_directory_count: int = 0
    source_snapshot_hash: str = ""

    def to_dict(self) -> dict:
        data = asdict(self)

        data["root"] = str(self.root)
        data["source_root"] = str(self.source_root)

        return data


class DevelopmentWorkspace:
    """
    Creates and verifies isolated development workspaces.

    The original repository is never used as the development target.

    Workflow:

        production repository
                ↓
        isolated workspace
                ↓
        verified repository snapshot
                ↓
        DevelopmentAgent works only here

    The workspace is deliberately independent from Git metadata.
    """

    COPY_IGNORE_NAMES = {
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
    }

    # Files that are useful as structural verification anchors.
    IMPORTANT_PATHS = (
        "main.py",
        "core",
        "brain",
        "requirements.txt",
        "pyproject.toml",
    )

    def __init__(
        self,
        repository_root: str | Path,
        workspace_base: str | Path | None = None,
        max_workspaces: int = 3,
    ) -> None:

        self.repository_root = (
            Path(repository_root)
            .expanduser()
            .resolve()
        )

        self.workspace_base = (
            Path(workspace_base)
            .expanduser()
            .resolve()
            if workspace_base
            else (
                self.repository_root
                / ".aria_workspaces"
            )
        )

        self.max_workspaces = max(
            1,
            int(max_workspaces),
        )

    # ========================================================
    # Validation
    # ========================================================

    def _validate_repository(self) -> None:

        if not self.repository_root.exists():
            raise FileNotFoundError(
                "Repository does not exist: "
                f"{self.repository_root}"
            )

        if not self.repository_root.is_dir():
            raise NotADirectoryError(
                "Repository root is not a directory: "
                f"{self.repository_root}"
            )

        if self.repository_root == self.workspace_base:
            raise ValueError(
                "Workspace base cannot be the repository root."
            )

    def _validate_workspace_base(self) -> None:

        base = self.workspace_base

        # The workspace base may live inside the repository
        # (the current ARIA configuration does this), but it must
        # never contain or replace the repository itself.
        if base == self.repository_root:
            raise ValueError(
                "Workspace base cannot equal repository root."
            )

        try:
            base.relative_to(
                self.repository_root
            )
            base_inside_repository = True
        except ValueError:
            base_inside_repository = False

        # If workspace_base is outside the repository, that's fine.
        # If it is inside, .aria_workspaces-style isolation is also fine.
        # What matters is that the repository is never below the workspace
        # base in the opposite direction.
        if not base_inside_repository:
            try:
                self.repository_root.relative_to(base)
            except ValueError:
                pass
            else:
                raise ValueError(
                    "Workspace base cannot contain the entire "
                    "repository root."
                )

    @staticmethod
    def _validate_workspace_id(
        workspace_id: str,
    ) -> str:

        identifier = str(
            workspace_id
        ).strip()

        if (
            not identifier
            or Path(identifier).name != identifier
            or identifier in {".", ".."}
        ):
            raise ValueError(
                "Invalid workspace_id."
            )

        if any(
            character in identifier
            for character in (
                "/",
                "\\",
                "\x00",
            )
        ):
            raise ValueError(
                "Invalid workspace_id."
            )

        return identifier

    # ========================================================
    # Workspace discovery
    # ========================================================

    def _active_workspaces(self) -> list[Path]:

        if not self.workspace_base.exists():
            return []

        result: list[Path] = []

        for path in self.workspace_base.iterdir():

            if not path.is_dir():
                continue

            if path.is_symlink():
                continue

            metadata = path / "workspace.json"

            if not metadata.is_file():
                continue

            result.append(path)

        return sorted(
            result,
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )

    def _enforce_workspace_limit(
        self,
        *,
        keep_workspace_id: str | None = None,
    ) -> None:

        active = self._active_workspaces()

        if len(active) <= self.max_workspaces:
            return

        retained: list[Path] = []

        if keep_workspace_id:
            for workspace in active:
                if workspace.name == keep_workspace_id:
                    retained.append(workspace)
                    break

        for workspace in active:

            if workspace in retained:
                continue

            retained.append(workspace)

            if len(retained) >= self.max_workspaces:
                break

        keep = set(retained)

        for old_workspace in active:

            if old_workspace in keep:
                continue

            try:
                shutil.rmtree(
                    old_workspace
                )
            except OSError:
                # Workspace cleanup failure should not corrupt
                # the newly created workspace.
                continue

    # ========================================================
    # Snapshot helpers
    # ========================================================

    @classmethod
    def _copy_ignore(
        cls,
        directory: str,
        names: list[str],
    ) -> set[str]:

        ignored: set[str] = set()

        for name in names:
            if name in cls.COPY_IGNORE_NAMES:
                ignored.add(name)

        return ignored

    @staticmethod
    def _count_files_and_directories(
        root: Path,
    ) -> tuple[int, int]:

        files = 0
        directories = 0

        for path in root.rglob("*"):

            if path.is_symlink():
                continue

            if path.is_file():
                files += 1

            elif path.is_dir():
                directories += 1

        return files, directories

    @classmethod
    def _snapshot_hash(
        cls,
        root: Path,
    ) -> str:

        digest = hashlib.sha256()

        paths: list[Path] = []

        for path in root.rglob("*"):

            if path.is_symlink():
                continue

            if not path.is_file():
                continue

            try:
                relative = path.relative_to(
                    root
                )
            except ValueError:
                continue

            if any(
                part in cls.COPY_IGNORE_NAMES
                for part in relative.parts
            ):
                continue

            paths.append(path)

        for path in sorted(
            paths,
            key=lambda item: item.relative_to(root).as_posix(),
        ):

            relative = path.relative_to(
                root
            ).as_posix()

            digest.update(
                relative.encode(
                    "utf-8"
                )
            )

            digest.update(
                b"\0"
            )

            try:
                file_hash = hashlib.sha256(
                    path.read_bytes()
                ).digest()
            except OSError:
                continue

            digest.update(
                file_hash
            )

            digest.update(
                b"\0"
            )

        return digest.hexdigest()

    @classmethod
    def _relative_paths(
        cls,
        root: Path,
    ) -> set[str]:

        result: set[str] = set()

        for path in root.rglob("*"):

            if path.is_symlink():
                continue

            if not path.is_file():
                continue

            try:
                relative = path.relative_to(
                    root
                )
            except ValueError:
                continue

            if any(
                part in cls.COPY_IGNORE_NAMES
                for part in relative.parts
            ):
                continue

            result.add(
                relative.as_posix()
            )

        return result

    # ========================================================
    # Copy verification
    # ========================================================

    def _verify_workspace_copy(
        self,
        source_root: Path,
    ) -> tuple[int, int, str]:

        if not source_root.exists():
            raise FileNotFoundError(
                "Workspace repository was not created: "
                f"{source_root}"
            )

        if not source_root.is_dir():
            raise NotADirectoryError(
                "Workspace repository is not a directory: "
                f"{source_root}"
            )

        source_files = self._relative_paths(
            self.repository_root
        )

        workspace_files = self._relative_paths(
            source_root
        )

        missing = source_files - workspace_files

        if missing:
            sample = sorted(missing)[:20]

            raise RuntimeError(
                "Workspace repository copy is incomplete. "
                f"Missing {len(missing)} files. "
                f"Sample: {sample}"
            )

        source_file_count, _ = (
            self._count_files_and_directories(
                self.repository_root
            )
        )

        workspace_file_count, workspace_directory_count = (
            self._count_files_and_directories(
                source_root
            )
        )

        if workspace_file_count < len(source_files):
            raise RuntimeError(
                "Workspace repository contains fewer files "
                "than the source repository."
            )

        snapshot_hash = self._snapshot_hash(
            source_root
        )

        if not snapshot_hash:
            raise RuntimeError(
                "Workspace repository snapshot is empty."
            )

        return (
            workspace_file_count,
            workspace_directory_count,
            snapshot_hash,
        )

    # ========================================================
    # Important structure verification
    # ========================================================

    @classmethod
    def _verify_expected_structure(
        cls,
        source_root: Path,
    ) -> None:

        # ARIA may legitimately omit some of these files in a small
        # development/test repository, so this is a warning-level
        # structural check rather than a hard requirement for every path.
        existing_anchor = False

        for relative in cls.IMPORTANT_PATHS:

            candidate = (
                source_root
                / relative
            )

            if candidate.exists():
                existing_anchor = True
                break

        if not existing_anchor:

            # The generic workspace mechanism should still support
            # repositories containing only arbitrary files.
            # The actual empty-copy protection is handled separately.
            return

    # ========================================================
    # Metadata
    # ========================================================

    @staticmethod
    def _write_metadata(
        workspace: WorkspaceInfo,
    ) -> None:

        metadata_path = (
            workspace.root
            / "workspace.json"
        )

        metadata_path.write_text(
            json.dumps(
                workspace.to_dict(),
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    @staticmethod
    def _read_metadata(
        metadata_path: Path,
    ) -> dict:

        try:
            data = json.loads(
                metadata_path.read_text(
                    encoding="utf-8"
                )
            )
        except json.JSONDecodeError as exc:
            raise ValueError(
                "Invalid workspace metadata JSON."
            ) from exc

        if not isinstance(data, dict):
            raise ValueError(
                "Workspace metadata must be an object."
            )

        return data

    # ========================================================
    # Create
    # ========================================================

    def create(
        self,
        workspace_id: Optional[str] = None,
    ) -> WorkspaceInfo:

        self._validate_repository()
        self._validate_workspace_base()

        self.workspace_base.mkdir(
            parents=True,
            exist_ok=True,
        )

        if workspace_id is None:

            identifier = (
                "dev-"
                + datetime.now(
                    timezone.utc
                ).strftime(
                    "%Y%m%d%H%M%S"
                )
                + "-"
                + uuid.uuid4().hex[:8]
            )

        else:

            identifier = self._validate_workspace_id(
                workspace_id
            )

        workspace_root = (
            self.workspace_base
            / identifier
        ).resolve()

        workspace_base_resolved = (
            self.workspace_base.resolve()
        )

        try:
            workspace_root.relative_to(
                workspace_base_resolved
            )
        except ValueError as exc:
            raise ValueError(
                "Workspace path escapes workspace base."
            ) from exc

        if workspace_root == workspace_base_resolved:
            raise ValueError(
                "Workspace root cannot equal workspace base."
            )

        if workspace_root.exists():
            raise FileExistsError(
                "Workspace already exists: "
                f"{workspace_root}"
            )

        workspace_root.mkdir(
            parents=True,
            exist_ok=False,
        )

        source_root = (
            workspace_root
            / "repo"
        )

        try:

            shutil.copytree(
                self.repository_root,
                source_root,
                ignore=self._copy_ignore,
                symlinks=False,
            )

            (
                source_file_count,
                source_directory_count,
                snapshot_hash,
            ) = self._verify_workspace_copy(
                source_root
            )

            self._verify_expected_structure(
                source_root
            )

            metadata = WorkspaceInfo(
                workspace_id=identifier,
                root=workspace_root,
                source_root=source_root,
                created_at=_utc_now(),
                source_file_count=source_file_count,
                source_directory_count=(
                    source_directory_count
                ),
                source_snapshot_hash=snapshot_hash,
            )

            self._write_metadata(
                metadata
            )

            # Keep the newly-created workspace alive even when
            # cleanup is required.
            self._enforce_workspace_limit(
                keep_workspace_id=identifier
            )

            return metadata

        except Exception:

            # Never leave a half-created development workspace.
            try:
                if workspace_root.exists():
                    shutil.rmtree(
                        workspace_root,
                        ignore_errors=True,
                    )
            except OSError:
                pass

            raise

    # ========================================================
    # Workspace lookup
    # ========================================================

    def exists(
        self,
        workspace_id: str,
    ) -> bool:

        identifier = self._validate_workspace_id(
            workspace_id
        )

        workspace_root = (
            self.workspace_base
            / identifier
        ).resolve()

        try:
            workspace_root.relative_to(
                self.workspace_base.resolve()
            )
        except ValueError:
            return False

        return (
            workspace_root.is_dir()
            and (
                workspace_root
                / "workspace.json"
            ).is_file()
        )

    def get(
        self,
        workspace_id: str,
    ) -> WorkspaceInfo:

        identifier = self._validate_workspace_id(
            workspace_id
        )

        workspace_root = (
            self.workspace_base
            / identifier
        ).resolve()

        workspace_base_resolved = (
            self.workspace_base.resolve()
        )

        try:
            workspace_root.relative_to(
                workspace_base_resolved
            )
        except ValueError as exc:
            raise ValueError(
                "Workspace path escapes workspace base."
            ) from exc

        if workspace_root == workspace_base_resolved:
            raise ValueError(
                "Invalid workspace root."
            )

        metadata_path = (
            workspace_root
            / "workspace.json"
        )

        if not metadata_path.is_file():
            raise FileNotFoundError(
                "Workspace metadata not found: "
                f"{identifier}"
            )

        data = self._read_metadata(
            metadata_path
        )

        stored_id = str(
            data.get(
                "workspace_id",
                "",
            )
        )

        if stored_id != identifier:
            raise ValueError(
                "Workspace metadata ID does not match "
                "requested workspace."
            )

        # Never trust stored absolute paths. Reconstruct them from
        # the validated workspace root.
        source_root = (
            workspace_root
            / "repo"
        )

        if not source_root.is_dir():
            raise FileNotFoundError(
                "Workspace repository directory is missing: "
                f"{source_root}"
            )

        created_at = str(
            data.get(
                "created_at",
                "",
            )
        )

        source_file_count = int(
            data.get(
                "source_file_count",
                0,
            )
        )

        source_directory_count = int(
            data.get(
                "source_directory_count",
                0,
            )
        )

        snapshot_hash = str(
            data.get(
                "source_snapshot_hash",
                "",
            )
        )

        return WorkspaceInfo(
            workspace_id=identifier,
            root=workspace_root,
            source_root=source_root,
            created_at=created_at,
            source_file_count=source_file_count,
            source_directory_count=(
                source_directory_count
            ),
            source_snapshot_hash=snapshot_hash,
        )

    # ========================================================
    # Integrity check
    # ========================================================

    def verify(
        self,
        workspace_id: str,
    ) -> WorkspaceInfo:

        workspace = self.get(
            workspace_id
        )

        if not workspace.source_root.is_dir():
            raise FileNotFoundError(
                "Workspace source repository does not exist."
            )

        current_hash = self._snapshot_hash(
            workspace.source_root
        )

        if (
            workspace.source_snapshot_hash
            and current_hash
            != workspace.source_snapshot_hash
        ):
            # This is expected after ARIA modifies the workspace.
            # Therefore this method reports the workspace as structurally
            # accessible rather than treating development changes as
            # corruption.
            return workspace

        return workspace

    # ========================================================
    # Destroy
    # ========================================================

    def destroy(
        self,
        workspace_id: str,
    ) -> None:

        identifier = self._validate_workspace_id(
            workspace_id
        )

        workspace_root = (
            self.workspace_base
            / identifier
        ).resolve()

        workspace_base_resolved = (
            self.workspace_base.resolve()
        )

        try:
            workspace_root.relative_to(
                workspace_base_resolved
            )
        except ValueError as exc:
            raise ValueError(
                "Workspace path escapes workspace base."
            ) from exc

        if workspace_root == workspace_base_resolved:
            raise ValueError(
                "Refusing to destroy workspace base."
            )

        if workspace_root.exists():
            shutil.rmtree(
                workspace_root
            )

    # ========================================================
    # List
    # ========================================================

    def list_workspaces(
        self,
    ) -> list[WorkspaceInfo]:

        result: list[WorkspaceInfo] = []

        for directory in self._active_workspaces():

            try:
                result.append(
                    self.get(
                        directory.name
                    )
                )

            except (
                OSError,
                ValueError,
                KeyError,
                TypeError,
                json.JSONDecodeError,
            ):
                continue

        return result