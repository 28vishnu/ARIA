from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Sequence

from .git_manager import GitManager, GitResult


@dataclass(frozen=True)
class GitHubRepository:
    owner: str
    name: str
    default_branch: str | None = None

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"

    def to_dict(self) -> dict:
        return {
            "owner": self.owner,
            "name": self.name,
            "full_name": self.full_name,
            "default_branch": self.default_branch,
        }


class GitHubManager:
    """
    GitHub integration for ARIA development.

    By default, push operations are disabled.

    This class can:

    - inspect the configured Git remote
    - determine repository identity
    - prepare authenticated Git operations
    - push a specific branch when explicitly enabled

    The manager never receives or stores a GitHub token
    permanently.

    The token is read only from the environment at the
    moment a permitted push is requested.
    """

    def __init__(
        self,
        git_manager: GitManager,
        *,
        allow_push: bool = False,
        command_timeout: float = 120.0,
    ) -> None:

        if command_timeout <= 0:
            raise ValueError(
                "command_timeout must be positive."
            )

        self.git = git_manager
        self.allow_push = bool(
            allow_push
        )
        self.command_timeout = float(
            command_timeout
        )

    async def remote_url(
        self,
        remote: str = "origin",
    ) -> str | None:

        if not remote.strip():
            raise ValueError(
                "remote cannot be empty."
            )

        result = await self.git._run(
            (
                "git",
                "remote",
                "get-url",
                remote,
            )
        )

        if not result.ok:
            return None

        value = result.stdout.strip()

        return value or None

    @staticmethod
    def parse_repository_url(
        url: str,
    ) -> GitHubRepository | None:

        if not isinstance(
            url,
            str,
        ):
            return None

        value = url.strip()

        if value.endswith(".git"):
            value = value[:-4]

        owner = None
        name = None

        if value.startswith(
            "git@github.com:"
        ):

            path = value[
                len("git@github.com:") :
            ]

            parts = path.split(
                "/",
                1,
            )

            if len(parts) == 2:
                owner, name = parts

        elif value.startswith(
            "https://github.com/"
        ):

            path = value[
                len("https://github.com/") :
            ]

            parts = path.split(
                "/",
                1,
            )

            if len(parts) == 2:
                owner, name = parts

        elif value.startswith(
            "http://github.com/"
        ):

            path = value[
                len("http://github.com/") :
            ]

            parts = path.split(
                "/",
                1,
            )

            if len(parts) == 2:
                owner, name = parts

        if not owner or not name:
            return None

        if (
            "/" in owner
            or "/" in name
            or " " in owner
            or " " in name
        ):
            return None

        return GitHubRepository(
            owner=owner,
            name=name,
        )

    async def repository(
        self,
        remote: str = "origin",
    ) -> GitHubRepository | None:

        url = await self.remote_url(
            remote
        )

        if not url:
            return None

        return self.parse_repository_url(
            url
        )

    def configured(
        self,
    ) -> bool:

        token = (
            os.getenv("GITHUB_TOKEN")
            or os.getenv("GH_TOKEN")
        )

        return bool(token)

    async def push(
        self,
        branch: str,
        *,
        remote: str = "origin",
        force: bool = False,
        explicit_authorization: bool = False,
    ) -> GitResult:

        if not self.allow_push:

            return GitResult(
                command=(
                    "git",
                    "push",
                    remote,
                    branch,
                ),
                return_code=126,
                stdout="",
                stderr=(
                    "GitHub push is disabled. "
                    "Enable it only through the "
                    "future deployment policy."
                ),
            )

        if not explicit_authorization:

            return GitResult(
                command=(
                    "git",
                    "push",
                    remote,
                    branch,
                ),
                return_code=126,
                stdout="",
                stderr=(
                    "Explicit push authorization "
                    "is required."
                ),
            )

        token = (
            os.getenv("GITHUB_TOKEN")
            or os.getenv("GH_TOKEN")
        )

        if not token:

            return GitResult(
                command=(
                    "git",
                    "push",
                    remote,
                    branch,
                ),
                return_code=127,
                stdout="",
                stderr=(
                    "No GitHub authentication token "
                    "is configured."
                ),
            )

        if force:

            return GitResult(
                command=(
                    "git",
                    "push",
                    remote,
                    branch,
                ),
                return_code=126,
                stdout="",
                stderr=(
                    "Force push is prohibited by "
                    "GitHubManager."
                ),
            )

        # Authentication is deliberately provided through
        # Git's credential environment rather than putting
        # the token in the command-line arguments.
        environment = {
            "GIT_TERMINAL_PROMPT": "0",
            "GH_TOKEN": token,
        }

        command: Sequence[str] = (
            "git",
            "push",
            "--set-upstream",
            remote,
            branch,
        )

        process = (
            await asyncio.create_subprocess_exec(
                *command,
                cwd=str(
                    self.git.repository_root
                ),
                env={
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
                    "GH_TOKEN": environment[
                        "GH_TOKEN"
                    ],
                },
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
                command=tuple(command),
                return_code=-1,
                stdout="",
                stderr=(
                    "GitHub push timed out."
                ),
            )

        return GitResult(
            command=tuple(command),
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