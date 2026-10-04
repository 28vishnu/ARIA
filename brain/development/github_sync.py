from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from .git_manager import GitManager, GitResult
from .github_manager import (
    GitHubManager,
    GitHubRepository,
)

logger = logging.getLogger("aria.github_sync")


# ============================================================
# Result Models
# ============================================================

@dataclass(frozen=True)
class RepositorySyncResult:
    success: bool
    operation: str
    repository_path: str
    branch: str | None = None
    remote: str | None = None
    commit_before: str | None = None
    commit_after: str | None = None
    changed: bool = False
    stdout: str = ""
    stderr: str = ""
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RepositoryState:
    repository_path: str
    is_repository: bool
    branch: str | None
    head_commit: str | None
    remote_url: str | None
    github_repository: dict[str, Any] | None
    dirty: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ============================================================
# GitHub Synchronization
# ============================================================

class GitHubSync:
    """
    Safe Git/GitHub synchronization layer.

    Responsibilities:

    - inspect repository state
    - inspect GitHub remote
    - fetch remote changes
    - prune deleted remote branches
    - fast-forward pull
    - synchronize the current branch safely
    - clone repositories into isolated directories

    This class does NOT:

    - push
    - force-push
    - merge arbitrary branches
    - delete repositories
    - expose GitHub tokens to the model
    - overwrite dirty working trees
    """

    _GITHUB_URL = re.compile(
        r"^(?:"
        r"https://github\.com/"
        r"|http://github\.com/"
        r"|git@github\.com:"
        r"|ssh://git@github\.com/"
        r")"
        r"[^/\s]+/"
        r"[^/\s]+"
        r"(?:\.git)?/?$",
        re.IGNORECASE,
    )

    def __init__(
        self,
        git_manager: GitManager,
        github_manager: GitHubManager,
        *,
        command_timeout: float = 180.0,
    ) -> None:

        if command_timeout <= 0:
            raise ValueError(
                "command_timeout must be positive."
            )

        self.git = git_manager
        self.github = github_manager
        self.command_timeout = float(
            command_timeout
        )

    # ========================================================
    # Internal command runner
    # ========================================================

    async def _run(
        self,
        command: tuple[str, ...] | list[str],
        *,
        cwd: Path | None = None,
    ) -> GitResult:

        normalized = tuple(
            str(item)
            for item in command
        )

        if not normalized:
            raise ValueError(
                "Command cannot be empty."
            )

        working_directory = (
            cwd
            if cwd is not None
            else self.git.repository_root
        )

        working_directory = (
            working_directory
            .expanduser()
            .resolve()
        )

        if not working_directory.is_dir():
            return GitResult(
                command=normalized,
                return_code=127,
                stdout="",
                stderr=(
                    "Working directory does not exist."
                ),
            )

        environment = {
            "PATH": os.environ.get(
                "PATH",
                "",
            ),
            "HOME": os.environ.get(
                "HOME",
                "",
            ),
            "LANG": os.environ.get(
                "LANG",
                "C.UTF-8",
            ),
            "LC_ALL": os.environ.get(
                "LC_ALL",
                "C.UTF-8",
            ),
            "GIT_TERMINAL_PROMPT": "0",
        }

        process = (
            await asyncio.create_subprocess_exec(
                *normalized,
                cwd=str(
                    working_directory
                ),
                env=environment,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        )

        try:

            stdout, stderr = (
                await asyncio.wait_for(
                    process.communicate(),
                    timeout=self.command_timeout,
                )
            )

        except asyncio.TimeoutError:

            try:
                process.kill()
            except ProcessLookupError:
                pass

            await process.communicate()

            return GitResult(
                command=normalized,
                return_code=-1,
                stdout="",
                stderr=(
                    "GitHub synchronization "
                    "command timed out."
                ),
            )

        return GitResult(
            command=normalized,
            return_code=(
                process.returncode
                if process.returncode is not None
                else -1
            ),
            stdout=stdout.decode(
                "utf-8",
                errors="replace",
            ),
            stderr=stderr.decode(
                "utf-8",
                errors="replace",
            ),
        )

    # ========================================================
    # Repository state
    # ========================================================

    async def state(
        self,
        *,
        remote: str = "origin",
    ) -> RepositoryState:

        is_repository = (
            await self.git.is_repository()
        )

        if not is_repository:

            return RepositoryState(
                repository_path=str(
                    self.git.repository_root
                ),
                is_repository=False,
                branch=None,
                head_commit=None,
                remote_url=None,
                github_repository=None,
                dirty=False,
            )

        branch = (
            await self.git.current_branch()
        )

        head = (
            await self.git.head_commit()
        )

        remote_url = (
            await self.github.remote_url(
                remote
            )
        )

        repository = (
            await self.github.repository(
                remote
            )
        )

        status = await self.git.status()

        dirty = bool(
            status.stdout.strip()
            or status.stderr.strip()
        )

        return RepositoryState(
            repository_path=str(
                self.git.repository_root
            ),
            is_repository=True,
            branch=branch,
            head_commit=head,
            remote_url=remote_url,
            github_repository=(
                repository.to_dict()
                if repository
                else None
            ),
            dirty=dirty,
        )

    # ========================================================
    # Fetch
    # ========================================================

    async def fetch(
        self,
        *,
        remote: str = "origin",
        prune: bool = True,
    ) -> RepositorySyncResult:

        state_before = await self.state(
            remote=remote
        )

        if not state_before.is_repository:

            return RepositorySyncResult(
                success=False,
                operation="fetch",
                repository_path=str(
                    self.git.repository_root
                ),
                remote=remote,
                message=(
                    "The configured path is not "
                    "a Git repository."
                ),
            )

        command = [
            "git",
            "fetch",
            "--no-tags",
        ]

        if prune:
            command.append(
                "--prune"
            )

        command.append(
            remote
        )

        result = await self._run(
            command
        )

        state_after = await self.state(
            remote=remote
        )

        return RepositorySyncResult(
            success=result.ok,
            operation="fetch",
            repository_path=str(
                self.git.repository_root
            ),
            branch=state_after.branch,
            remote=remote,
            commit_before=state_before.head_commit,
            commit_after=state_after.head_commit,
            changed=(
                state_before.head_commit
                != state_after.head_commit
            ),
            stdout=result.stdout,
            stderr=result.stderr,
            message=(
                "Remote references fetched successfully."
                if result.ok
                else
                "Remote fetch failed."
            ),
        )

    # ========================================================
    # Pull — FAST FORWARD ONLY
    # ========================================================

    async def pull_fast_forward(
        self,
        *,
        remote: str = "origin",
        branch: str | None = None,
    ) -> RepositorySyncResult:

        state_before = await self.state(
            remote=remote
        )

        if not state_before.is_repository:

            return RepositorySyncResult(
                success=False,
                operation="pull",
                repository_path=str(
                    self.git.repository_root
                ),
                remote=remote,
                message=(
                    "The configured path is not "
                    "a Git repository."
                ),
            )

        if state_before.dirty:

            return RepositorySyncResult(
                success=False,
                operation="pull",
                repository_path=str(
                    self.git.repository_root
                ),
                branch=state_before.branch,
                remote=remote,
                commit_before=state_before.head_commit,
                commit_after=state_before.head_commit,
                changed=False,
                message=(
                    "Pull refused because the "
                    "working tree contains local changes."
                ),
            )

        target_branch = (
            branch
            or state_before.branch
        )

        if not target_branch:

            return RepositorySyncResult(
                success=False,
                operation="pull",
                repository_path=str(
                    self.git.repository_root
                ),
                remote=remote,
                message=(
                    "No current branch was found."
                ),
            )

        fetch_result = await self.fetch(
            remote=remote,
            prune=True,
        )

        if not fetch_result.success:

            return fetch_result

        command = (
            "git",
            "pull",
            "--ff-only",
            remote,
            target_branch,
        )

        result = await self._run(
            command
        )

        state_after = await self.state(
            remote=remote
        )

        return RepositorySyncResult(
            success=result.ok,
            operation="pull",
            repository_path=str(
                self.git.repository_root
            ),
            branch=state_after.branch,
            remote=remote,
            commit_before=state_before.head_commit,
            commit_after=state_after.head_commit,
            changed=(
                state_before.head_commit
                != state_after.head_commit
            ),
            stdout=result.stdout,
            stderr=result.stderr,
            message=(
                "Repository fast-forwarded successfully."
                if result.ok
                else
                "Fast-forward pull failed. "
                "No automatic merge was attempted."
            ),
        )

    # ========================================================
    # Full synchronization
    # ========================================================

    async def synchronize(
        self,
        *,
        remote: str = "origin",
        pull: bool = True,
    ) -> RepositorySyncResult:

        state_before = await self.state(
            remote=remote
        )

        if not state_before.is_repository:

            return RepositorySyncResult(
                success=False,
                operation="synchronize",
                repository_path=str(
                    self.git.repository_root
                ),
                remote=remote,
                message=(
                    "The configured path is not "
                    "a Git repository."
                ),
            )

        fetch_result = await self.fetch(
            remote=remote,
            prune=True,
        )

        if not fetch_result.success:

            return RepositorySyncResult(
                success=False,
                operation="synchronize",
                repository_path=str(
                    self.git.repository_root
                ),
                branch=state_before.branch,
                remote=remote,
                commit_before=state_before.head_commit,
                commit_after=state_before.head_commit,
                stdout=fetch_result.stdout,
                stderr=fetch_result.stderr,
                message=(
                    "Synchronization stopped after "
                    "remote fetch failed."
                ),
            )

        if not pull:

            state_after = await self.state(
                remote=remote
            )

            return RepositorySyncResult(
                success=True,
                operation="synchronize",
                repository_path=str(
                    self.git.repository_root
                ),
                branch=state_after.branch,
                remote=remote,
                commit_before=state_before.head_commit,
                commit_after=state_after.head_commit,
                changed=(
                    state_before.head_commit
                    != state_after.head_commit
                ),
                stdout=fetch_result.stdout,
                stderr=fetch_result.stderr,
                message=(
                    "Remote references synchronized."
                ),
            )

        pull_result = (
            await self.pull_fast_forward(
                remote=remote
            )
        )

        return RepositorySyncResult(
            success=pull_result.success,
            operation="synchronize",
            repository_path=pull_result.repository_path,
            branch=pull_result.branch,
            remote=remote,
            commit_before=state_before.head_commit,
            commit_after=pull_result.commit_after,
            changed=pull_result.changed,
            stdout=(
                fetch_result.stdout
                + pull_result.stdout
            ),
            stderr=(
                fetch_result.stderr
                + pull_result.stderr
            ),
            message=pull_result.message,
        )

    # ========================================================
    # Clone
    # ========================================================

    @classmethod
    def _validate_clone_url(
        cls,
        repository_url: str,
    ) -> str:

        if not isinstance(
            repository_url,
            str,
        ):
            raise TypeError(
                "repository_url must be a string."
            )

        value = repository_url.strip()

        if not value:
            raise ValueError(
                "repository_url cannot be empty."
            )

        if (
            not cls._GITHUB_URL.fullmatch(
                value
            )
        ):

            raise ValueError(
                "Only valid GitHub repository URLs "
                "are accepted."
            )

        return value

    @staticmethod
    def _validate_clone_destination(
        destination: str | Path,
    ) -> Path:

        path = (
            Path(destination)
            .expanduser()
            .resolve()
        )

        if path.exists():

            if not path.is_dir():

                raise ValueError(
                    "Clone destination is not a directory."
                )

            try:

                if any(path.iterdir()):

                    raise ValueError(
                        "Clone destination must be empty."
                    )

            except PermissionError as exc:

                raise ValueError(
                    "Clone destination cannot be inspected."
                ) from exc

        else:

            path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

        return path

    async def clone(
        self,
        repository_url: str,
        destination: str | Path,
        *,
        branch: str | None = None,
        depth: int | None = None,
    ) -> RepositorySyncResult:

        url = self._validate_clone_url(
            repository_url
        )

        destination_path = (
            self._validate_clone_destination(
                destination
            )
        )

        command = [
            "git",
            "clone",
        ]

        if branch:

            if not re.fullmatch(
                r"[A-Za-z0-9._/-]+",
                branch,
            ):
                raise ValueError(
                    "Invalid branch name."
                )

            command.extend(
                [
                    "--branch",
                    branch,
                ]
            )

        if depth is not None:

            depth = int(depth)

            if depth <= 0:
                raise ValueError(
                    "depth must be positive."
                )

            command.extend(
                [
                    "--depth",
                    str(depth),
                ]
            )

        command.extend(
            [
                url,
                str(destination_path),
            ]
        )

        result = await self._run(
            command,
            cwd=destination_path.parent,
        )

        if result.ok:

            message = (
                "GitHub repository cloned successfully."
            )

        else:

            # Remove only the destination created by
            # this clone attempt. Never delete an existing
            # non-empty directory.
            try:

                if destination_path.exists():

                    if destination_path.is_dir():

                        shutil.rmtree(
                            destination_path
                        )

            except Exception:

                logger.exception(
                    "Failed to clean up failed clone."
                )

            message = (
                "GitHub repository clone failed."
            )

        return RepositorySyncResult(
            success=result.ok,
            operation="clone",
            repository_path=str(
                destination_path
            ),
            branch=branch,
            remote="origin",
            stdout=result.stdout,
            stderr=result.stderr,
            message=message,
        )

    # ========================================================
    # Remote information
    # ========================================================

    async def remote_info(
        self,
        *,
        remote: str = "origin",
    ) -> dict[str, Any]:

        url = await self.github.remote_url(
            remote
        )

        repository = (
            await self.github.repository(
                remote
            )
        )

        return {
            "remote": remote,
            "url": url,
            "github_repository": (
                repository.to_dict()
                if repository
                else None
            ),
            "configured_authentication": (
                self.github.configured()
            ),
        }

    # ========================================================
    # Health
    # ========================================================

    async def health(self) -> dict[str, Any]:

        try:

            state = await self.state()

            return {
                "healthy": bool(
                    state.is_repository
                ),
                "repository": state.to_dict(),
            }

        except Exception as exc:

            logger.exception(
                "GitHub synchronization health check failed."
            )

            return {
                "healthy": False,
                "error": str(exc),
            }

    # ========================================================
    # Description
    # ========================================================

    def describe(self) -> dict[str, Any]:

        return {
            "name": "github_sync",
            "capabilities": [
                "repository_state",
                "remote_inspection",
                "fetch",
                "fetch_prune",
                "fast_forward_pull",
                "safe_synchronize",
                "github_clone",
            ],
            "safety": [
                "no_push",
                "no_force_push",
                "no_automatic_merge",
                "dirty_tree_pull_protection",
                "github_token_not_exposed",
            ],
        }


__all__ = [
    "RepositorySyncResult",
    "RepositoryState",
    "GitHubSync",
]