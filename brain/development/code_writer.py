from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .filesystem_guard import FilesystemGuard


@dataclass(frozen=True)
class WriteResult:
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


class CodeWriter:
    """
    Safe source-code writer for development workspaces.

    It can:

    - create files
    - replace files
    - create backups
    - delete files

    It cannot write outside the FilesystemGuard workspace.

    It does not:

    - commit
    - push
    - deploy
    - modify production
    - access protected files
    """

    def __init__(
        self,
        guard: FilesystemGuard,
    ) -> None:
        self.guard = guard

    def write(
        self,
        path: str | Path,
        content: str,
        *,
        create_only: bool = False,
        backup: bool = True,
    ) -> WriteResult:

        if not isinstance(
            content,
            str,
        ):
            raise TypeError(
                "content must be a string."
            )

        target = self.guard.assert_allowed(
            path
        )

        existed = target.exists()

        if existed and target.is_dir():
            raise IsADirectoryError(
                str(target)
            )

        if create_only and existed:
            raise FileExistsError(
                str(target)
            )

        old_content = ""

        if existed:
            old_content = (
                target.read_text(
                    encoding="utf-8"
                )
            )

            if old_content == content:

                return WriteResult(
                    path=str(
                        target.relative_to(
                            self.guard.workspace_root
                        )
                    ),
                    action="unchanged",
                    changed=False,
                    old_size=len(
                        old_content.encode(
                            "utf-8"
                        )
                    ),
                    new_size=len(
                        content.encode(
                            "utf-8"
                        )
                    ),
                )

        backup_path = None

        if existed and backup:

            backup_file = target.with_name(
                target.name + ".aria.bak"
            )

            self.guard.assert_allowed(
                backup_file
            )

            backup_file.write_text(
                old_content,
                encoding="utf-8",
            )

            backup_path = str(
                backup_file.relative_to(
                    self.guard.workspace_root
                )
            )

        self.guard.write_text(
            target,
            content,
        )

        return WriteResult(
            path=str(
                target.relative_to(
                    self.guard.workspace_root
                )
            ),
            action=(
                "modify"
                if existed
                else "create"
            ),
            changed=True,
            old_size=len(
                old_content.encode(
                    "utf-8"
                )
            ),
            new_size=len(
                content.encode(
                    "utf-8"
                )
            ),
            backup_path=backup_path,
        )

    def delete(
        self,
        path: str | Path,
    ) -> WriteResult:

        target = self.guard.assert_allowed(
            path,
            allow_missing=False,
        )

        if target.is_dir():
            raise IsADirectoryError(
                str(target)
            )

        size = target.stat().st_size

        self.guard.delete(
            target
        )

        return WriteResult(
            path=str(
                target.relative_to(
                    self.guard.workspace_root
                )
            ),
            action="delete",
            changed=True,
            old_size=size,
            new_size=0,
        )

    def apply_files(
        self,
        files: Iterable[
            tuple[str, str]
        ],
        *,
        backup: bool = True,
    ) -> list[WriteResult]:

        results: list[WriteResult] = []

        for path, content in files:
            results.append(
                self.write(
                    path,
                    content,
                    backup=backup,
                )
            )

        return results