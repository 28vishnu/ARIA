from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .filesystem_guard import FilesystemGuard


@dataclass(frozen=True)
class GitResult:
    command: tuple[str, ...]
    return_code: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.return_code == 0

    def to_dict(self) -> dict:
        return {
            "command": list(self.command),
            "return_code": self.return_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "ok": self.ok,
        }


@dataclass(frozen=True)
class GitCommit:
    commit_hash: str
    branch: str
    message: str

    def to_dict(self) -> dict:
        return {
            "commit_hash": self.commit_hash,
            "branch": self.branch,
            "message": self.message,
        }


class GitManager:
    """
    Safe Git operations for a development workspace.

    This manager deliberately operates only inside the supplied
    workspace.

    It supports:

    - repository inspection
    - branch creation
    - status
    - diff
    - staging
    - commits
    - checkout
    - reset/rollback to a known commit

    It does NOT push to GitHub.

    GitHub pushing is handled separately by GitHubManager and
    is disabled unless explicitly enabled by the caller.
    """

    _BRANCH_PATTERN = re.compile(
        r"^[A-Za-z0-9._/-]+$"
    )

    _FORBIDDEN_BRANCH_PARTS = (
        "..",
        "@{",
    )

    def __init__(
        self,
        repository_root: str | Path,
        *,
        command_timeout: float = 60.0,
    ) -> None:

        if command_timeout <= 0:
            raise ValueError(
                "command_timeout must be positive."
            )

        self.repository_root = (
            Path(repository_root)
            .expanduser()
            .resolve()
        )

        if not self.repository_root.is_dir():
            raise NotADirectoryError(
                str(self.repository_root)
            )

        self.guard = FilesystemGuard(
            self.repository_root
        )

        self.command_timeout = float(
            command_timeout
        )

    @staticmethod
    def _validate_branch_name(
        branch: str,
    ) -> str:

        if not isinstance(
            branch,
            str,
        ):
            raise TypeError(
                "branch must be a string."
            )

        branch = branch.strip()

        if not branch:
            raise ValueError(
                "branch cannot be empty."
            )

        if (
            not GitManager._BRANCH_PATTERN.fullmatch(
                branch
            )
        ):
            raise ValueError(
                "Invalid Git branch name."
            )

        if any(
            part in branch
            for part in GitManager._FORBIDDEN_BRANCH_PARTS
        ):
            raise ValueError(
                "Unsafe Git branch name."
            )

        if branch.startswith(
            ("/", ".")
        ) or branch.endswith(
            ("/", ".")
        ):
            raise ValueError(
                "Unsafe Git branch name."
            )

        return branch

    @staticmethod
    def _validate_commit_message(
        message: str,
    ) -> str:

        if not isinstance(
            message,
            str,
        ):
            raise TypeError(
                "Commit message must be a string."
            )

        message = " ".join(
            message.strip().split()
        )

        if not message:
            raise ValueError(
                "Commit message cannot be empty."
            )

        if len(message) > 200:
            raise ValueError(
                "Commit message is too long."
            )

        return message

    async def _run(
        self,
        command: Sequence[str],
    ) -> GitResult:

        normalized = tuple(
            str(part)
            for part in command
        )

        if not normalized:
            raise ValueError(
                "Git command cannot be empty."
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
                    self.repository_root
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
                stderr="Git command timed out.",
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

    async def is_repository(self) -> bool:

        result = await self._run(
            (
                "git",
                "rev-parse",
                "--is-inside-work-tree",
            )
        )

        return (
            result.ok
            and result.stdout.strip()
            == "true"
        )

    async def current_branch(
        self,
    ) -> str | None:

        result = await self._run(
            (
                "git",
                "branch",
                "--show-current",
            )
        )

        if not result.ok:
            return None

        branch = result.stdout.strip()

        return branch or None

    async def status(
        self,
    ) -> GitResult:

        return await self._run(
            (
                "git",
                "status",
                "--short",
            )
        )

    async def diff(
        self,
        *,
        staged: bool = False,
    ) -> GitResult:

        command = [
            "git",
            "diff",
        ]

        if staged:
            command.append(
                "--cached"
            )

        return await self._run(
            command
        )

    async def create_branch(
        self,
        branch: str,
        *,
        from_ref: str | None = None,
    ) -> GitResult:

        branch = self._validate_branch_name(
            branch
        )

        command = [
            "git",
            "switch",
            "-c",
            branch,
        ]

        if from_ref:
            command.extend(
                [
                    "--no-track",
                    from_ref,
                ]
            )

        return await self._run(
            command
        )

    async def switch_branch(
        self,
        branch: str,
    ) -> GitResult:

        branch = self._validate_branch_name(
            branch
        )

        return await self._run(
            (
                "git",
                "switch",
                branch,
            )
        )

    async def add(
        self,
        paths: Sequence[str],
    ) -> GitResult:

        if not paths:
            raise ValueError(
                "At least one path is required."
            )

        safe_paths: list[str] = []

        for path in paths:

            resolved = self.guard.assert_allowed(
                path
            )

            relative = resolved.relative_to(
                self.repository_root
            )

            safe_paths.append(
                relative.as_posix()
            )

        return await self._run(
            (
                "git",
                "add",
                "--",
                *safe_paths,
            )
        )

    async def add_all(
        self,
    ) -> GitResult:

        return await self._run(
            (
                "git",
                "add",
                "-A",
            )
        )

    async def commit(
        self,
        message: str,
    ) -> GitCommit | None:

        message = self._validate_commit_message(
            message
        )

        result = await self._run(
            (
                "git",
                "commit",
                "-m",
                message,
            )
        )

        if not result.ok:
            return None

        hash_result = await self._run(
            (
                "git",
                "rev-parse",
                "HEAD",
            )
        )

        branch = await self.current_branch()

        if (
            not hash_result.ok
            or not branch
        ):
            return None

        commit_hash = (
            hash_result.stdout.strip()
        )

        return GitCommit(
            commit_hash=commit_hash,
            branch=branch,
            message=message,
        )

    async def head_commit(
        self,
    ) -> str | None:

        result = await self._run(
            (
                "git",
                "rev-parse",
                "HEAD",
            )
        )

        if not result.ok:
            return None

        return result.stdout.strip()

    async def log(
        self,
        limit: int = 10,
    ) -> GitResult:

        limit = max(
            1,
            min(
                int(limit),
                100,
            ),
        )

        return await self._run(
            (
                "git",
                "log",
                f"-{limit}",
                "--oneline",
                "--decorate",
            )
        )

    async def reset_hard(
        self,
        commit_hash: str,
    ) -> GitResult:

        if not re.fullmatch(
            r"[0-9a-fA-F]{7,64}",
            commit_hash.strip(),
        ):
            raise ValueError(
                "Invalid Git commit hash."
            )

        return await self._run(
            (
                "git",
                "reset",
                "--hard",
                commit_hash.strip(),
            )
        )

    async def restore_worktree(
        self,
    ) -> GitResult:

        return await self._run(
            (
                "git",
                "restore",
                "--worktree",
                "--staged",
                "--",
                ".",
            )
        )