from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# ============================================================
# Helpers
# ============================================================

def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalise_path(path: Path) -> str:
    return str(path).replace("\\", "/").lstrip("./")


# ============================================================
# Workspace metadata
# ============================================================

@dataclass(frozen=True)
class WorkspaceInfo:
    workspace_id: str
    root: Path
    source_root: Path
    created_at: str

    # Snapshot information.
    source_file_count: int = 0
    source_directory_count: int = 0
    source_snapshot_hash: str = ""

    # Actual copied repository information.
    copied_file_count: int = 0
    copied_directory_count: int = 0
    copied_snapshot_hash: str = ""

    def to_dict(self) -> dict:
        data = asdict(self)

        data["root"] = str(self.root)
        data["source_root"] = str(self.source_root)

        return data


# ============================================================
# Development Workspace
# ============================================================

class DevelopmentWorkspace:
    """
    Creates isolated development workspaces.

    Production repository:
        /app

    Development workspace:
        /app/.aria_workspaces/<job-id>/repo

    The production repository is never modified by this class.

    Important implementation detail:

    The default workspace directory is located INSIDE the
    repository. Therefore shutil.copytree() is deliberately not
    used for the repository snapshot.

    Instead:

        1. Snapshot the source tree first.
        2. Create the destination.
        3. Copy the recorded files explicitly.
        4. Verify the destination.
        5. Write workspace metadata.

    This prevents recursive/nested workspace-copy problems.
    """

    # Directories that must never be copied into a development
    # workspace.
    DEFAULT_IGNORED_DIRECTORIES = frozenset(
        {
            ".git",
            ".aria_workspaces",
            "__pycache__",
            ".pytest_cache",
            ".mypy_cache",
            ".ruff_cache",
            ".venv",
            "venv",
            "env",
            "node_modules",
            "dist",
            "build",
        }
    )

    # Files that are normally unnecessary for development
    # context and may contain local/environment information.
    DEFAULT_IGNORED_FILES = frozenset(
        {
            ".DS_Store",
        }
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
            if workspace_base is not None
            else self.repository_root / ".aria_workspaces"
        )

        self.max_workspaces = max(
            1,
            int(max_workspaces),
        )

        # Keep the ignored sets immutable.
        self.ignored_directories = set(
            self.DEFAULT_IGNORED_DIRECTORIES
        )

        self.ignored_files = set(
            self.DEFAULT_IGNORED_FILES
        )

    # ========================================================
    # Validation
    # ========================================================

    def _validate_repository(self) -> None:
        if not self.repository_root.exists():
            raise FileNotFoundError(
                f"Repository does not exist: "
                f"{self.repository_root}"
            )

        if not self.repository_root.is_dir():
            raise NotADirectoryError(
                f"Repository root is not a directory: "
                f"{self.repository_root}"
            )

    def _validate_workspace_base(self) -> None:
        self.workspace_base.mkdir(
            parents=True,
            exist_ok=True,
        )

        resolved_base = (
            self.workspace_base.resolve()
        )

        # If workspace_base is inside the repository, that is
        # supported. It is explicitly excluded from the source
        # snapshot.
        try:
            resolved_base.relative_to(
                self.repository_root
            )
            return
        except ValueError:
            pass

        # A workspace outside the repository is also valid.

    @staticmethod
    def _validate_workspace_id(
        identifier: str,
    ) -> None:

        if not identifier:
            raise ValueError(
                "Workspace ID cannot be empty."
            )

        path = Path(identifier)

        if (
            path.name != identifier
            or identifier in {".", ".."}
            or "/" in identifier
            or "\\" in identifier
        ):
            raise ValueError(
                "Invalid workspace_id."
            )

    # ========================================================
    # Path helpers
    # ========================================================

    def _is_workspace_base_path(
        self,
        path: Path,
    ) -> bool:

        try:
            path.resolve().relative_to(
                self.workspace_base.resolve()
            )
            return True
        except ValueError:
            return False

    def _is_ignored_directory(
        self,
        directory: Path,
    ) -> bool:

        if directory.name in self.ignored_directories:
            return True

        # Most importantly, prevent the destination workspace
        # tree from being treated as source material when the
        # workspace base lives inside the repository.
        if self._is_workspace_base_path(directory):
            return True

        return False

    def _is_ignored_file(
        self,
        file_path: Path,
    ) -> bool:

        if file_path.name in self.ignored_files:
            return True

        if self._is_workspace_base_path(file_path):
            return True

        return False

    def _relative_source_path(
        self,
        path: Path,
    ) -> Path:

        return path.resolve().relative_to(
            self.repository_root
        )

    # ========================================================
    # Source snapshot
    # ========================================================

    def _snapshot_source_tree(
        self,
    ) -> tuple[list[Path], list[Path], str]:
        """
        Build a complete source manifest BEFORE creating the
        destination workspace.

        This is intentionally done before workspace creation so
        the destination cannot accidentally become part of the
        source traversal.
        """

        files: list[Path] = []
        directories: list[Path] = []

        root = self.repository_root

        for current_root, dir_names, file_names in os.walk(
            root,
            topdown=True,
            followlinks=False,
        ):
            current = Path(current_root)

            # Remove ignored directories from traversal.
            kept_dirs: list[str] = []

            for directory_name in sorted(dir_names):
                directory = current / directory_name

                if self._is_ignored_directory(
                    directory
                ):
                    continue

                kept_dirs.append(
                    directory_name
                )

                directories.append(
                    directory
                )

            # Mutate os.walk's traversal list.
            dir_names[:] = kept_dirs

            for file_name in sorted(file_names):
                file_path = current / file_name

                if self._is_ignored_file(
                    file_path
                ):
                    continue

                # Never follow symlinked files. They may point
                # outside the repository.
                if file_path.is_symlink():
                    continue

                if not file_path.is_file():
                    continue

                files.append(
                    file_path
                )

        files.sort(
            key=lambda path: _normalise_path(
                self._relative_source_path(path)
            )
        )

        directories.sort(
            key=lambda path: _normalise_path(
                self._relative_source_path(path)
            )
        )

        snapshot_hash = (
            self._calculate_snapshot_hash(
                files
            )
        )

        return (
            files,
            directories,
            snapshot_hash,
        )

    def _calculate_snapshot_hash(
        self,
        files: list[Path],
    ) -> str:

        digest = hashlib.sha256()

        for file_path in files:
            try:
                relative = (
                    self._relative_source_path(
                        file_path
                    )
                )

                stat = file_path.stat()

                digest.update(
                    _normalise_path(
                        relative
                    ).encode(
                        "utf-8"
                    )
                )

                digest.update(
                    str(stat.st_size).encode(
                        "utf-8"
                    )
                )

                digest.update(
                    str(
                        stat.st_mtime_ns
                    ).encode(
                        "utf-8"
                    )
                )

            except (
                OSError,
                ValueError,
            ):
                continue

        return digest.hexdigest()

    # ========================================================
    # Workspace copy
    # ========================================================

    def _copy_source_tree(
        self,
        source_files: list[Path],
        source_directories: list[Path],
        source_root: Path,
    ) -> tuple[int, int]:

        # Create directories first.
        for source_directory in source_directories:

            relative = (
                self._relative_source_path(
                    source_directory
                )
            )

            destination = (
                source_root / relative
            )

            destination.mkdir(
                parents=True,
                exist_ok=True,
            )

        copied_files = 0

        for source_file in source_files:

            relative = (
                self._relative_source_path(
                    source_file
                )
            )

            destination = (
                source_root / relative
            )

            destination.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            # Final safety check.
            resolved_destination = (
                destination.resolve()
            )

            resolved_source_root = (
                source_root.resolve()
            )

            try:
                resolved_destination.relative_to(
                    resolved_source_root
                )
            except ValueError as exc:
                raise ValueError(
                    "Refusing to copy outside workspace "
                    f"source root: {destination}"
                ) from exc

            shutil.copy2(
                source_file,
                destination,
                follow_symlinks=False,
            )

            copied_files += 1

        return (
            copied_files,
            len(source_directories),
        )

    # ========================================================
    # Destination verification
    # ========================================================

    def _verify_workspace_copy(
        self,
        source_files: list[Path],
        source_root: Path,
    ) -> tuple[
        bool,
        int,
        int,
        str,
        list[str],
    ]:

        actual_files: list[Path] = []

        if not source_root.exists():
            return (
                False,
                0,
                0,
                "",
                [],
            )

        for current_root, _, file_names in os.walk(
            source_root,
            topdown=True,
            followlinks=False,
        ):
            current = Path(current_root)

            for file_name in file_names:
                path = current / file_name

                if path.is_symlink():
                    continue

                if path.is_file():
                    actual_files.append(
                        path
                    )

        actual_files.sort(
            key=lambda path: _normalise_path(
                path.relative_to(
                    source_root
                )
            )
        )

        expected_relative = {
            _normalise_path(
                self._relative_source_path(
                    path
                )
            )
            for path in source_files
        }

        actual_relative = {
            _normalise_path(
                path.relative_to(
                    source_root
                )
            )
            for path in actual_files
        }

        missing = sorted(
            expected_relative - actual_relative
        )

        unexpected = sorted(
            actual_relative - expected_relative
        )

        errors: list[str] = []

        if missing:
            errors.append(
                "Missing copied files: "
                + ", ".join(
                    missing[:20]
                )
            )

        if unexpected:
            errors.append(
                "Unexpected copied files: "
                + ", ".join(
                    unexpected[:20]
                )
            )

        # Verify file sizes and contents.
        if not errors:

            for source_file in source_files:

                relative = (
                    self._relative_source_path(
                        source_file
                    )
                )

                destination = (
                    source_root / relative
                )

                try:
                    source_size = (
                        source_file.stat().st_size
                    )

                    destination_size = (
                        destination.stat().st_size
                    )

                except OSError as exc:
                    errors.append(
                        f"Unable to stat copied file "
                        f"{relative}: {exc}"
                    )
                    continue

                if source_size != destination_size:
                    errors.append(
                        f"Size mismatch for "
                        f"{relative}: "
                        f"{source_size} != "
                        f"{destination_size}"
                    )
                    continue

        copied_hash = (
            self._calculate_workspace_hash(
                actual_files,
                source_root,
            )
        )

        valid = (
            not errors
            and len(source_files)
            == len(actual_files)
        )

        sample = sorted(
            actual_relative
        )[:10]

        return (
            valid,
            len(actual_files),
            len(actual_relative),
            copied_hash,
            sample,
        )

    @staticmethod
    def _calculate_workspace_hash(
        files: list[Path],
        source_root: Path,
    ) -> str:

        digest = hashlib.sha256()

        for file_path in files:

            try:
                relative = file_path.relative_to(
                    source_root
                )

                stat = file_path.stat()

                digest.update(
                    _normalise_path(
                        relative
                    ).encode(
                        "utf-8"
                    )
                )

                digest.update(
                    str(stat.st_size).encode(
                        "utf-8"
                    )
                )

                digest.update(
                    str(stat.st_mtime_ns).encode(
                        "utf-8"
                    )
                )

            except OSError:
                continue

        return digest.hexdigest()

    # ========================================================
    # Workspace lifecycle
    # ========================================================

    def _active_workspaces(self) -> list[Path]:

        if not self.workspace_base.exists():
            return []

        result: list[Path] = []

        for path in self.workspace_base.iterdir():

            if not path.is_dir():
                continue

            # Only treat directories containing workspace.json
            # as managed workspaces.
            if not (
                path / "workspace.json"
            ).is_file():
                continue

            result.append(
                path
            )

        return sorted(
            result,
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )

    def _enforce_workspace_limit(
        self,
        keep_workspace: Path | None = None,
    ) -> None:

        active = self._active_workspaces()

        # Always keep the workspace that was just created.
        if keep_workspace is not None:
            keep_workspace = (
                keep_workspace.resolve()
            )

        for old_workspace in active:

            if len(
                self._active_workspaces()
            ) <= self.max_workspaces:
                break

            if (
                keep_workspace is not None
                and old_workspace.resolve()
                == keep_workspace
            ):
                continue

            try:
                shutil.rmtree(
                    old_workspace
                )
            except OSError:
                continue

    # ========================================================
    # Create
    # ========================================================

    def create(
        self,
        workspace_id: Optional[str] = None,
    ) -> WorkspaceInfo:

        self._validate_repository()
        self._validate_workspace_base()

        # ----------------------------------------------------
        # CRITICAL:
        # Snapshot the source BEFORE creating the destination.
        # ----------------------------------------------------

        (
            source_files,
            source_directories,
            source_snapshot_hash,
        ) = self._snapshot_source_tree()

        if not source_files:
            raise RuntimeError(
                "Repository snapshot is empty; "
                "refusing to create an empty development workspace."
            )

        identifier = workspace_id or (
            "dev-"
            + datetime.now(
                timezone.utc
            ).strftime(
                "%Y%m%d%H%M%S"
            )
            + "-"
            + uuid.uuid4().hex[:8]
        )

        self._validate_workspace_id(
            identifier
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

        if workspace_root.exists():
            raise FileExistsError(
                "Workspace already exists: "
                f"{workspace_root}"
            )

        source_root = (
            workspace_root / "repo"
        )

        try:
            workspace_root.mkdir(
                parents=True,
                exist_ok=False,
            )

            source_root.mkdir(
                parents=True,
                exist_ok=False,
            )

            (
                copied_files,
                copied_directories,
            ) = self._copy_source_tree(
                source_files=source_files,
                source_directories=source_directories,
                source_root=source_root,
            )

            (
                valid,
                verified_file_count,
                verified_path_count,
                copied_snapshot_hash,
                sample,
            ) = self._verify_workspace_copy(
                source_files=source_files,
                source_root=source_root,
            )

            if not valid:
                raise RuntimeError(
                    "Workspace copy verification failed. "
                    f"expected_files={len(source_files)} "
                    f"actual_files={verified_file_count} "
                    f"sample={sample}"
                )

            if copied_files != len(
                source_files
            ):
                raise RuntimeError(
                    "Workspace copy count mismatch. "
                    f"source={len(source_files)} "
                    f"copied={copied_files}"
                )

            metadata = WorkspaceInfo(
                workspace_id=identifier,
                root=workspace_root,
                source_root=source_root,
                created_at=_utc_now(),
                source_file_count=len(
                    source_files
                ),
                source_directory_count=len(
                    source_directories
                ),
                source_snapshot_hash=(
                    source_snapshot_hash
                ),
                copied_file_count=(
                    verified_file_count
                ),
                copied_directory_count=(
                    copied_directories
                ),
                copied_snapshot_hash=(
                    copied_snapshot_hash
                ),
            )

            metadata_path = (
                workspace_root
                / "workspace.json"
            )

            metadata_path.write_text(
                json.dumps(
                    metadata.to_dict(),
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )

            # Verify metadata exists before returning.
            if not metadata_path.is_file():
                raise RuntimeError(
                    "Workspace metadata could not be created."
                )

            # Keep the newly-created workspace.
            self._enforce_workspace_limit(
                keep_workspace=workspace_root
            )

            return metadata

        except Exception:

            # Never leave a partially-created workspace behind.
            if workspace_root.exists():

                try:
                    shutil.rmtree(
                        workspace_root
                    )
                except OSError:
                    pass

            raise

    # ========================================================
    # Lookup
    # ========================================================

    def exists(
        self,
        workspace_id: str,
    ) -> bool:

        self._validate_workspace_id(
            workspace_id
        )

        workspace_root = (
            self.workspace_base
            / workspace_id
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

        self._validate_workspace_id(
            workspace_id
        )

        workspace_root = (
            self.workspace_base
            / workspace_id
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

        metadata_path = (
            workspace_root
            / "workspace.json"
        )

        if not metadata_path.is_file():
            raise FileNotFoundError(
                "Workspace metadata not found: "
                f"{workspace_id}"
            )

        data = json.loads(
            metadata_path.read_text(
                encoding="utf-8"
            )
        )

        source_root = (
            workspace_root / "repo"
        ).resolve()

        # Do not trust an arbitrary source_root stored in
        # metadata. Reconstruct it from the verified workspace
        # root.
        try:
            source_root.relative_to(
                workspace_root
            )
        except ValueError as exc:
            raise ValueError(
                "Workspace repository path escapes workspace root."
            ) from exc

        return WorkspaceInfo(
            workspace_id=str(
                data["workspace_id"]
            ),
            root=workspace_root,
            source_root=source_root,
            created_at=str(
                data["created_at"]
            ),
            source_file_count=int(
                data.get(
                    "source_file_count",
                    0,
                )
            ),
            source_directory_count=int(
                data.get(
                    "source_directory_count",
                    0,
                )
            ),
            source_snapshot_hash=str(
                data.get(
                    "source_snapshot_hash",
                    "",
                )
            ),
            copied_file_count=int(
                data.get(
                    "copied_file_count",
                    0,
                )
            ),
            copied_directory_count=int(
                data.get(
                    "copied_directory_count",
                    0,
                )
            ),
            copied_snapshot_hash=str(
                data.get(
                    "copied_snapshot_hash",
                    "",
                )
            ),
        )

    # ========================================================
    # Verification
    # ========================================================

    def verify(
        self,
        workspace_id: str,
    ) -> dict:

        workspace = self.get(
            workspace_id
        )

        source_root = (
            workspace.source_root
        )

        if not source_root.is_dir():
            return {
                "valid": False,
                "workspace_id": workspace_id,
                "files": 0,
                "directories": 0,
                "expected_files": (
                    workspace.source_file_count
                ),
                "error": (
                    "Workspace repository directory "
                    "does not exist."
                ),
            }

        actual_files = 0
        actual_directories = 0

        for current_root, dir_names, file_names in os.walk(
            source_root,
            topdown=True,
            followlinks=False,
        ):
            actual_directories += len(
                dir_names
            )

            actual_files += sum(
                1
                for name in file_names
                if not (
                    Path(current_root)
                    / name
                ).is_symlink()
            )

        valid = (
            actual_files > 0
            and (
                workspace.source_file_count == 0
                or actual_files
                == workspace.source_file_count
            )
        )

        return {
            "valid": valid,
            "workspace_id": workspace_id,
            "files": actual_files,
            "directories": actual_directories,
            "expected_files": (
                workspace.source_file_count
            ),
            "source_snapshot_hash": (
                workspace.source_snapshot_hash
            ),
            "copied_snapshot_hash": (
                workspace.copied_snapshot_hash
            ),
            "source_root": str(
                source_root
            ),
        }

    # ========================================================
    # Destroy
    # ========================================================

    def destroy(
        self,
        workspace_id: str,
    ) -> None:

        self._validate_workspace_id(
            workspace_id
        )

        workspace_root = (
            self.workspace_base
            / workspace_id
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

        if (
            workspace_root
            == workspace_base_resolved
        ):
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