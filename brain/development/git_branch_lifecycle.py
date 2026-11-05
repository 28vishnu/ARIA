from __future__ import annotations

import logging
import re
from dataclasses import dataclass, asdict
from typing import Any

from .git_manager import GitManager

logger = logging.getLogger("aria.git_branch_lifecycle")


@dataclass(frozen=True)
class BranchLifecycleResult:
    success: bool
    operation: str
    branch: str | None = None
    previous_branch: str | None = None
    commit_id: str | None = None
    changed: bool = False
    message: str = ""
    stdout: str = ""
    stderr: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class GitBranchLifecycle:
    """
    Safe local Git branch lifecycle for autonomous engineering.

    ARIA can:
      - create isolated engineering branches
      - switch branches
      - create local checkpoints
      - abort an engineering branch
      - inspect branch state

    This component NEVER pushes to GitHub.
    """

    def __init__(
        self,
        git_manager: GitManager,
        *,
        prefix: str = "aria/auto",
    ) -> None:

        self.git = git_manager
        self.prefix = self._validate_prefix(
            prefix
        )

    @staticmethod
    def _validate_prefix(
        prefix: str,
    ) -> str:

        prefix = (
            str(prefix or "")
            .strip()
            .strip("/")
        )

        if not prefix:
            raise ValueError(
                "Branch prefix cannot be empty."
            )

        if not re.fullmatch(
            r"[A-Za-z0-9._/-]+",
            prefix,
        ):
            raise ValueError(
                "Invalid branch prefix."
            )

        if (
            ".." in prefix
            or "@{" in prefix
        ):
            raise ValueError(
                "Unsafe branch prefix."
            )

        return prefix

    @staticmethod
    def _validate_slug(
        slug: str,
    ) -> str:

        value = (
            str(slug or "")
            .strip()
            .lower()
        )

        value = re.sub(
            r"[^a-z0-9._/-]+",
            "-",
            value,
        )

        value = re.sub(
            r"-+",
            "-",
            value,
        ).strip(
            "-./"
        )

        if not value:
            raise ValueError(
                "Branch slug cannot be empty."
            )

        if (
            ".." in value
            or "@{" in value
        ):
            raise ValueError(
                "Unsafe branch slug."
            )

        return value[:100]

    async def current(
        self,
    ) -> str | None:

        return await self.git.current_branch()

    async def is_dirty(
        self,
    ) -> bool:

        result = await self.git.status()

        return bool(
            result.stdout.strip()
            or result.stderr.strip()
        )

    async def start(
        self,
        slug: str,
        *,
        from_ref: str | None = None,
        require_clean: bool = True,
    ) -> BranchLifecycleResult:

        previous = await self.current()

        if (
            require_clean
            and await self.is_dirty()
        ):

            return BranchLifecycleResult(
                success=False,
                operation="start",
                previous_branch=previous,
                message=(
                    "Branch creation refused because "
                    "the working tree is dirty."
                ),
            )

        branch = (
            f"{self.prefix}/"
            f"{self._validate_slug(slug)}"
        )

        result = await self.git.create_branch(
            branch,
            from_ref=from_ref,
        )

        return BranchLifecycleResult(
            success=result.ok,
            operation="start",
            branch=(
                branch
                if result.ok
                else None
            ),
            previous_branch=previous,
            changed=result.ok,
            stdout=result.stdout,
            stderr=result.stderr,
            message=(
                "Isolated engineering branch created."
                if result.ok
                else
                "Engineering branch creation failed."
            ),
        )

    async def switch(
        self,
        branch: str,
        *,
        require_clean: bool = True,
    ) -> BranchLifecycleResult:

        previous = await self.current()

        if (
            require_clean
            and await self.is_dirty()
        ):

            return BranchLifecycleResult(
                success=False,
                operation="switch",
                branch=branch,
                previous_branch=previous,
                message=(
                    "Branch switch refused because "
                    "the working tree is dirty."
                ),
            )

        result = await self.git.switch_branch(
            branch
        )

        return BranchLifecycleResult(
            success=result.ok,
            operation="switch",
            branch=(
                branch
                if result.ok
                else previous
            ),
            previous_branch=previous,
            changed=(
                result.ok
                and previous != branch
            ),
            stdout=result.stdout,
            stderr=result.stderr,
            message=(
                "Branch switched successfully."
                if result.ok
                else
                "Branch switch failed."
            ),
        )

    async def checkpoint(
        self,
        message: str,
        *,
        add_all: bool = True,
    ) -> BranchLifecycleResult:

        branch = await self.current()

        if not branch:

            return BranchLifecycleResult(
                success=False,
                operation="checkpoint",
                message=(
                    "No active Git branch is available."
                ),
            )

        if add_all:

            staged = await self.git.add_all()

            if not staged.ok:

                return BranchLifecycleResult(
                    success=False,
                    operation="checkpoint",
                    branch=branch,
                    stdout=staged.stdout,
                    stderr=staged.stderr,
                    message=(
                        "Failed to stage engineering changes."
                    ),
                )

        commit = await self.git.commit(
            message
        )

        if not commit.ok:

            return BranchLifecycleResult(
                success=False,
                operation="checkpoint",
                branch=branch,
                stdout=commit.stdout,
                stderr=commit.stderr,
                message=(
                    "Engineering checkpoint "
                    "commit failed."
                ),
            )

        head = await self.git.head_commit()

        return BranchLifecycleResult(
            success=True,
            operation="checkpoint",
            branch=branch,
            commit_id=head,
            changed=True,
            stdout=commit.stdout,
            stderr=commit.stderr,
            message=(
                "Local engineering checkpoint created."
            ),
        )

    async def abort(
        self,
        *,
        target_branch: str,
        restore_commit: str | None = None,
    ) -> BranchLifecycleResult:

        current = await self.current()

        if current == target_branch:

            return BranchLifecycleResult(
                success=False,
                operation="abort",
                branch=current,
                message=(
                    "Abort target must be different "
                    "from the active branch."
                ),
            )

        if restore_commit:

            reset = await self.git.reset_hard(
                restore_commit
            )

            if not reset.ok:

                return BranchLifecycleResult(
                    success=False,
                    operation="abort",
                    branch=current,
                    stdout=reset.stdout,
                    stderr=reset.stderr,
                    message=(
                        "Failed to restore the "
                        "requested checkpoint."
                    ),
                )

        result = await self.git.switch_branch(
            target_branch
        )

        return BranchLifecycleResult(
            success=result.ok,
            operation="abort",
            branch=(
                target_branch
                if result.ok
                else current
            ),
            previous_branch=current,
            changed=result.ok,
            stdout=result.stdout,
            stderr=result.stderr,
            message=(
                "Engineering branch aborted and "
                "control returned to the target branch."
                if result.ok
                else
                "Failed to return to the target branch."
            ),
        )

    async def status(
        self,
    ) -> dict[str, Any]:

        branch = await self.current()
        dirty = await self.is_dirty()
        head = await self.git.head_commit()

        return {
            "branch": branch,
            "dirty": dirty,
            "head_commit": head,
            "prefix": self.prefix,
            "push_enabled": False,
        }

    def describe(
        self,
    ) -> dict[str, Any]:

        return {
            "name": "git_branch_lifecycle",
            "capabilities": [
                "create_isolated_branch",
                "switch_branch",
                "local_checkpoint",
                "abort_engineering_branch",
                "branch_status",
            ],
            "safety": [
                "local_only",
                "no_push",
                "dirty_tree_protection",
                "no_force_push",
            ],
        }


__all__ = [
    "BranchLifecycleResult",
    "GitBranchLifecycle",
]