"""
ARIA Code Writer.

Provides guarded file creation and modification inside an isolated
development workspace.

This module is deliberately lower-level than ChangePlanner.

Safety responsibilities:
    - never write outside FilesystemGuard
    - never modify an existing file when create_only=True
    - never delete unless deletion is explicitly enabled by the caller
    - reject unsafe/symlinked targets
    - preserve backups for permitted modifications
    - verify written content
    - keep writes bounded by file-size limits

This module does NOT:
    - generate code
    - execute code
    - run tests
    - commit
    - push
    - deploy
    - modify production
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from .filesystem_guard import FilesystemGuard


# ======================================================================
# Result model
# ======================================================================


@dataclass(frozen=True)
class WriteResult:
    """
    Result of a single filesystem write/delete operation.
    """

    path: str
    action: str
    changed: bool
    old_size: int
    new_size: int
    backup_path: str | None = None

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "action": self.action,
            "changed": self.changed,
            "old_size": self.old_size,
            "new_size": self.new_size,
            "backup_path": self.backup_path,
        }


# ======================================================================
# CodeWriter
# ======================================================================


class CodeWriter:
    """
    Safe source-code writer for isolated development workspaces.

    Supported operations:

        create
        modify
        delete

    Important safety rule:

        create_only=True

    means an existing file is never overwritten.

    The writer intentionally does not decide whether a change is
    authorized. That decision belongs to ChangePlanner /
    DevelopmentAgent. However, it enforces the concrete filesystem
    boundary so an upstream mistake cannot silently turn a create-only
    request into an overwrite.
    """

    # ------------------------------------------------------------------
    # Default limits
    # ------------------------------------------------------------------

    DEFAULT_MAX_FILE_SIZE_BYTES = (
        10 * 1024 * 1024
    )

    DEFAULT_MAX_TOTAL_WRITE_BYTES = (
        50 * 1024 * 1024
    )

    # ------------------------------------------------------------------
    # Internal temporary-file suffix.
    # ------------------------------------------------------------------

    TEMP_SUFFIX = ".aria.tmp"

    # ------------------------------------------------------------------
    # Supported actions.
    # ------------------------------------------------------------------

    VALID_ACTIONS = frozenset(
        {
            "create",
            "modify",
            "delete",
        }
    )

    # ==================================================================
    # Initialization
    # ==================================================================

    def __init__(
        self,
        guard: FilesystemGuard,
        *,
        max_file_size_bytes: int | None = None,
        max_total_write_bytes: int | None = None,
        allow_delete: bool = False,
    ) -> None:
        if guard is None:
            raise ValueError(
                "guard is required."
            )

        self.guard = guard

        self.max_file_size_bytes = (
            int(
                max_file_size_bytes
                if max_file_size_bytes is not None
                else self.DEFAULT_MAX_FILE_SIZE_BYTES
            )
        )

        self.max_total_write_bytes = (
            int(
                max_total_write_bytes
                if max_total_write_bytes is not None
                else self.DEFAULT_MAX_TOTAL_WRITE_BYTES
            )
        )

        self.allow_delete = bool(
            allow_delete
        )

        if (
            self.max_file_size_bytes
            <= 0
        ):
            raise ValueError(
                "max_file_size_bytes must be positive."
            )

        if (
            self.max_total_write_bytes
            <= 0
        ):
            raise ValueError(
                "max_total_write_bytes must be positive."
            )

    # ==================================================================
    # Write
    # ==================================================================

    def write(
        self,
        path: str | Path,
        content: str,
        *,
        create_only: bool = False,
        backup: bool = True,
    ) -> WriteResult:
        """
        Create or modify a file inside the guarded workspace.

        Args:
            path:
                Workspace-relative target path.

            content:
                Complete file contents.

            create_only:
                If True, an existing file causes FileExistsError.
                It can NEVER be overwritten.

            backup:
                If True, an existing file is backed up before
                modification.

        Returns:
            WriteResult

        Raises:
            TypeError:
                Invalid content.

            FileExistsError:
                Existing file encountered in create-only mode.

            IsADirectoryError:
                Target is a directory.

            ValueError:
                File exceeds configured size limit.

            PermissionError:
                Target is a symbolic link or otherwise unsafe.
        """

        if not isinstance(
            content,
            str,
        ):
            raise TypeError(
                "content must be a string."
            )

        # --------------------------------------------------------------
        # Validate content size before touching the filesystem.
        # --------------------------------------------------------------

        new_size = len(
            content.encode(
                "utf-8"
            )
        )

        self._validate_file_size(
            new_size
        )

        # --------------------------------------------------------------
        # Resolve target through the filesystem guard.
        # --------------------------------------------------------------

        target = self.guard.assert_allowed(
            path
        )

        self._validate_target(
            target
        )

        existed = target.exists()

        if existed and target.is_dir():
            raise IsADirectoryError(
                str(target)
            )

        # --------------------------------------------------------------
        # Hard create-only boundary.
        # --------------------------------------------------------------

        if (
            create_only
            and existed
        ):
            raise FileExistsError(
                f"Create-only write refused because "
                f"the file already exists: {target}"
            )

        # --------------------------------------------------------------
        # Read old contents when modifying.
        # --------------------------------------------------------------

        old_content = ""

        if existed:

            old_content = (
                target.read_text(
                    encoding="utf-8"
                )
            )

            old_size = len(
                old_content.encode(
                    "utf-8"
                )
            )

            self._validate_file_size(
                old_size
            )

            # ----------------------------------------------------------
            # No-op if content is already identical.
            # ----------------------------------------------------------

            if old_content == content:

                return WriteResult(
                    path=self._relative_path(
                        target
                    ),
                    action="unchanged",
                    changed=False,
                    old_size=old_size,
                    new_size=new_size,
                    backup_path=None,
                )

        else:
            old_size = 0

        # --------------------------------------------------------------
        # Backup existing content.
        # --------------------------------------------------------------

        backup_path = None

        if (
            existed
            and backup
        ):

            backup_path = (
                self._create_backup(
                    target,
                    old_content,
                )
            )

        # --------------------------------------------------------------
        # Write safely.
        # --------------------------------------------------------------

        self._atomic_write(
            target,
            content,
        )

        # --------------------------------------------------------------
        # Verify exact content.
        # --------------------------------------------------------------

        self._verify_written_content(
            target,
            content,
        )

        return WriteResult(
            path=self._relative_path(
                target
            ),
            action=(
                "modify"
                if existed
                else "create"
            ),
            changed=True,
            old_size=old_size,
            new_size=new_size,
            backup_path=backup_path,
        )

    # ==================================================================
    # Delete
    # ==================================================================

    def delete(
        self,
        path: str | Path,
        *,
        allow_delete: bool | None = None,
    ) -> WriteResult:
        """
        Delete a file inside the guarded workspace.

        Deletion is disabled by default.

        It requires BOTH:
            - CodeWriter.allow_delete=True
              OR allow_delete=True for this call
            - the FilesystemGuard to permit the target.

        This extra explicit gate prevents an accidental delete from
        being triggered by a generic write operation.
        """

        deletion_allowed = (
            self.allow_delete
            if allow_delete is None
            else bool(allow_delete)
        )

        if not deletion_allowed:
            raise PermissionError(
                "File deletion is disabled for this CodeWriter."
            )

        target = self.guard.assert_allowed(
            path,
            allow_missing=False,
        )

        self._validate_target(
            target
        )

        if target.is_dir():
            raise IsADirectoryError(
                str(target)
            )

        size = target.stat().st_size

        self.guard.delete(
            target
        )

        # --------------------------------------------------------------
        # Verify deletion.
        # --------------------------------------------------------------

        if target.exists():
            raise OSError(
                f"File deletion could not be verified: {target}"
            )

        return WriteResult(
            path=self._relative_path(
                target
            ),
            action="delete",
            changed=True,
            old_size=size,
            new_size=0,
            backup_path=None,
        )

    # ==================================================================
    # Apply multiple files
    # ==================================================================

    def apply_files(
        self,
        files: Iterable[
            tuple[str, str]
        ],
        *,
        backup: bool = True,
        create_only: bool = False,
        allow_delete: bool = False,
    ) -> list[WriteResult]:
        """
        Apply multiple file changes.

        Backward-compatible input:

            [
                ("aria_test.txt", "hello")
            ]

        means:

            write/create the file.

        The writer also accepts action records in the following form:

            [
                ("create", "file.txt", "content")
            ]

            [
                ("modify", "file.py", "content")
            ]

            [
                ("delete", "old.txt", "")
            ]

        The method intentionally supports the original two-element
        tuple format because DevelopmentAgent may already use it.

        Important:
            create_only=True applies to every write in the batch.

        If one operation fails, the method raises immediately rather
        than silently continuing with an incomplete development
        operation.
        """

        results: list[WriteResult] = []

        total_write_bytes = 0

        for item in files:

            operation = self._normalise_operation(
                item
            )

            action = operation[
                "action"
            ]

            path = operation[
                "path"
            ]

            content = operation.get(
                "content",
                "",
            )

            # ----------------------------------------------------------
            # Write/create/modify
            # ----------------------------------------------------------

            if action in {
                "create",
                "modify",
            }:

                if not isinstance(
                    content,
                    str,
                ):
                    raise TypeError(
                        f"Content for {path!r} "
                        "must be a string."
                    )

                content_size = len(
                    content.encode(
                        "utf-8"
                    )
                )

                total_write_bytes += (
                    content_size
                )

                if (
                    total_write_bytes
                    > self.max_total_write_bytes
                ):
                    raise ValueError(
                        "Development write batch exceeds "
                        "the configured total write limit."
                    )

                # ------------------------------------------------------
                # Explicit create action.
                # ------------------------------------------------------

                if action == "create":

                    result = self.write(
                        path,
                        content,
                        create_only=True,
                        backup=False,
                    )

                # ------------------------------------------------------
                # Explicit modify action.
                # ------------------------------------------------------

                else:

                    if create_only:
                        raise PermissionError(
                            "Modification requested while "
                            "create_only=True: "
                            f"{path}"
                        )

                    result = self.write(
                        path,
                        content,
                        create_only=False,
                        backup=backup,
                    )

                results.append(
                    result
                )

                continue

            # ----------------------------------------------------------
            # Delete
            # ----------------------------------------------------------

            if action == "delete":

                if not allow_delete:
                    raise PermissionError(
                        "Deletion requested in apply_files(), "
                        "but allow_delete=False."
                    )

                result = self.delete(
                    path,
                    allow_delete=True,
                )

                results.append(
                    result
                )

                continue

            raise ValueError(
                f"Unsupported file action: {action!r}"
            )

        return results

    # ==================================================================
    # Operation normalization
    # ==================================================================

    @staticmethod
    def _normalise_operation(
        item: Sequence[str],
    ) -> dict[str, str]:
        """
        Normalize supported batch operation formats.

        Supported:

            (path, content)

            (action, path, content)
        """

        if not isinstance(
            item,
            (tuple, list),
        ):
            raise TypeError(
                "Each file operation must be a tuple or list."
            )

        if len(item) == 2:

            path, content = item

            if not isinstance(
                path,
                str,
            ):
                raise TypeError(
                    "File path must be a string."
                )

            return {
                "action": "modify",
                "path": path,
                "content": (
                    content
                    if isinstance(
                        content,
                        str,
                    )
                    else str(content)
                ),
            }

        if len(item) == 3:

            action, path, content = item

            if not isinstance(
                action,
                str,
            ):
                raise TypeError(
                    "File action must be a string."
                )

            if not isinstance(
                path,
                str,
            ):
                raise TypeError(
                    "File path must be a string."
                )

            normalized_action = (
                action.strip().lower()
            )

            if normalized_action not in {
                "create",
                "modify",
                "delete",
            }:
                raise ValueError(
                    f"Unsupported file action: "
                    f"{action!r}"
                )

            return {
                "action": normalized_action,
                "path": path,
                "content": (
                    content
                    if isinstance(
                        content,
                        str,
                    )
                    else str(content)
                ),
            }

        raise ValueError(
            "File operation must contain either "
            "(path, content) or "
            "(action, path, content)."
        )

    # ==================================================================
    # Target validation
    # ==================================================================

    def _validate_target(
        self,
        target: Path,
    ) -> None:
        """
        Perform additional target validation after FilesystemGuard.

        The target must:
            - be inside the workspace
            - not be a symbolic link
            - not resolve through a symbolic-link parent
        """

        workspace_root = Path(
            self.guard.workspace_root
        ).resolve()

        try:
            target_absolute = (
                target.absolute()
            )

            target_resolved = (
                target.resolve(
                    strict=False
                )
            )

            target_resolved.relative_to(
                workspace_root
            )

        except (
            ValueError,
            RuntimeError,
        ) as exc:

            raise PermissionError(
                "Target resolves outside the development workspace."
            ) from exc

        # --------------------------------------------------------------
        # Existing symlink target.
        # --------------------------------------------------------------

        if target.is_symlink():
            raise PermissionError(
                "Symbolic-link targets are not permitted: "
                f"{target}"
            )

        # --------------------------------------------------------------
        # Check every existing parent component for symlinks.
        # --------------------------------------------------------------

        current = target_absolute.parent

        while True:

            if current == workspace_root:
                break

            try:
                if current.is_symlink():
                    raise PermissionError(
                        "Symbolic-link parent directories are "
                        "not permitted: "
                        f"{current}"
                    )
            except OSError as exc:
                raise PermissionError(
                    f"Could not safely inspect target parent: "
                    f"{current}"
                ) from exc

            parent = current.parent

            if parent == current:
                break

            current = parent

    # ==================================================================
    # File-size validation
    # ==================================================================

    def _validate_file_size(
        self,
        size: int,
    ) -> None:
        """
        Enforce the configured per-file limit.
        """

        if size < 0:
            raise ValueError(
                "File size cannot be negative."
            )

        if (
            size
            > self.max_file_size_bytes
        ):
            raise ValueError(
                "File exceeds the configured maximum size "
                f"of {self.max_file_size_bytes} bytes."
            )

    # ==================================================================
    # Backup
    # ==================================================================

    def _create_backup(
        self,
        target: Path,
        old_content: str,
    ) -> str:
        """
        Create a guarded backup of an existing file.
        """

        backup_file = target.with_name(
            target.name
            + ".aria.bak"
        )

        # --------------------------------------------------------------
        # Never overwrite a symbolic-link backup.
        # --------------------------------------------------------------

        if backup_file.is_symlink():
            raise PermissionError(
                "Backup target is a symbolic link: "
                f"{backup_file}"
            )

        backup_target = (
            self.guard.assert_allowed(
                backup_file
            )
        )

        backup_target.write_text(
            old_content,
            encoding="utf-8",
        )

        # --------------------------------------------------------------
        # Verify backup.
        # --------------------------------------------------------------

        if (
            backup_target.read_text(
                encoding="utf-8"
            )
            != old_content
        ):
            raise IOError(
                "Backup verification failed: "
                f"{backup_target}"
            )

        return self._relative_path(
            backup_target
        )

    # ==================================================================
    # Atomic write
    # ==================================================================

    def _atomic_write(
        self,
        target: Path,
        content: str,
    ) -> None:
        """
        Write complete content through a temporary file and replace
        the target only after the temporary file is fully written.

        The temporary file is created inside the same directory so
        os.replace() remains on the same filesystem.
        """

        parent = target.parent

        # --------------------------------------------------------------
        # Parent directory must remain inside the guarded workspace.
        # --------------------------------------------------------------

        parent_guarded = (
            self.guard.assert_allowed(
                parent
            )
        )

        parent_guarded.mkdir(
            parents=True,
            exist_ok=True,
        )

        temp_path: Path | None = None

        try:

            fd, temporary_name = (
                tempfile.mkstemp(
                    prefix=".aria-write-",
                    suffix=self.TEMP_SUFFIX,
                    dir=str(
                        parent_guarded
                    ),
                    text=True,
                )
            )

            temp_path = Path(
                temporary_name
            )

            # ----------------------------------------------------------
            # Write using the raw descriptor.
            # ----------------------------------------------------------

            with os.fdopen(
                fd,
                "w",
                encoding="utf-8",
                newline="",
            ) as handle:

                handle.write(
                    content
                )

                handle.flush()

                try:
                    os.fsync(
                        handle.fileno()
                    )
                except OSError:
                    # Some filesystems/environments do not support
                    # fsync. The write itself is still valid.
                    pass

            # ----------------------------------------------------------
            # Verify temporary file before replacing target.
            # ----------------------------------------------------------

            temporary_content = (
                temp_path.read_text(
                    encoding="utf-8"
                )
            )

            if (
                temporary_content
                != content
            ):
                raise IOError(
                    "Temporary file content verification failed."
                )

            # ----------------------------------------------------------
            # Replace target.
            # ----------------------------------------------------------

            os.replace(
                str(temp_path),
                str(target),
            )

            temp_path = None

        finally:

            if (
                temp_path is not None
                and temp_path.exists()
            ):
                try:
                    temp_path.unlink()
                except OSError:
                    pass

    # ==================================================================
    # Verification
    # ==================================================================

    def _verify_written_content(
        self,
        target: Path,
        expected: str,
    ) -> None:
        """
        Verify exact UTF-8 content after writing.
        """

        if not target.exists():
            raise IOError(
                f"Written file does not exist: {target}"
            )

        if target.is_symlink():
            raise PermissionError(
                "Written target became a symbolic link: "
                f"{target}"
            )

        actual = target.read_text(
            encoding="utf-8"
        )

        if actual != expected:
            raise IOError(
                "Exact content verification failed for: "
                f"{target}"
            )

        actual_size = len(
            actual.encode(
                "utf-8"
            )
        )

        expected_size = len(
            expected.encode(
                "utf-8"
            )
        )

        if actual_size != expected_size:
            raise IOError(
                "Written file size verification failed for: "
                f"{target}"
            )

    # ==================================================================
    # Relative path
    # ==================================================================

    def _relative_path(
        self,
        target: Path,
    ) -> str:
        """
        Return a workspace-relative normalized path.
        """

        root = Path(
            self.guard.workspace_root
        ).resolve()

        resolved_target = (
            target.resolve(
                strict=False
            )
        )

        try:

            relative = (
                resolved_target.relative_to(
                    root
                )
            )

        except ValueError as exc:

            raise PermissionError(
                "Target is outside the development workspace."
            ) from exc

        return str(
            relative
        ).replace(
            "\\",
            "/",
        )


__all__ = [
    "WriteResult",
    "CodeWriter",
]