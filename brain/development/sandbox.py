from __future__ import annotations

import asyncio
import os
import signal
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from .filesystem_guard import FilesystemGuard


@dataclass(frozen=True)
class CommandResult:
    command: tuple[str, ...]
    return_code: int
    stdout: str
    stderr: str
    timed_out: bool

    @property
    def ok(self) -> bool:
        return (
            self.return_code == 0
            and not self.timed_out
        )

    def to_dict(self) -> dict:
        return {
            "command": list(self.command),
            "return_code": self.return_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "timed_out": self.timed_out,
            "ok": self.ok,
        }


class DevelopmentSandbox:
    """
    Executes development commands only inside an approved
    workspace.

    This is a process/filesystem safety boundary, not a
    full OS container.

    Production deployment, Git push, network access, and
    secrets are not enabled by this class.
    """

    def __init__(
        self,
        workspace_root: str | Path,
        *,
        timeout_seconds: float = 120.0,
        max_output_bytes: int = 1_000_000,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError(
                "timeout_seconds must be positive"
            )

        if max_output_bytes <= 0:
            raise ValueError(
                "max_output_bytes must be positive"
            )

        self.guard = FilesystemGuard(
            workspace_root
        )

        self.timeout_seconds = float(
            timeout_seconds
        )

        self.max_output_bytes = int(
            max_output_bytes
        )

    @staticmethod
    def _normalize_command(
        command: Sequence[str],
    ) -> tuple[str, ...]:
        if not command:
            raise ValueError(
                "Command cannot be empty."
            )

        normalized = tuple(
            str(part)
            for part in command
        )

        if any(
            not part
            for part in normalized
        ):
            raise ValueError(
                "Command arguments cannot be empty."
            )

        return normalized

    def _build_environment(
        self,
        extra_env: Mapping[str, str] | None,
    ) -> dict[str, str]:
        environment = (
            self.guard.environment()
        )

        if extra_env:
            for key, value in extra_env.items():

                if (
                    not isinstance(key, str)
                    or not isinstance(value, str)
                ):
                    raise TypeError(
                        "Environment keys and values "
                        "must be strings."
                    )

                if any(
                    token in key.upper()
                    for token in (
                        "TOKEN",
                        "SECRET",
                        "PASSWORD",
                        "API_KEY",
                        "PRIVATE_KEY",
                    )
                ):
                    raise PermissionError(
                        "Secret environment variable "
                        f"is not permitted: {key}"
                    )

                environment[key] = value

        return environment

    async def run(
        self,
        command: Sequence[str],
        *,
        cwd: str | Path = ".",
        extra_env: Mapping[str, str] | None = None,
    ) -> CommandResult:
        normalized = (
            self._normalize_command(command)
        )

        working_directory = (
            self.guard.resolve(cwd)
        )

        if not working_directory.is_dir():
            raise NotADirectoryError(
                str(working_directory)
            )

        if self.guard.is_protected(
            working_directory
        ):
            raise PermissionError(
                "Cannot execute inside protected "
                f"path: {working_directory}"
            )

        environment = (
            self._build_environment(
                extra_env
            )
        )

        process = (
            await asyncio.create_subprocess_exec(
                *normalized,
                cwd=str(working_directory),
                env=environment,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
        )

        timed_out = False

        try:
            stdout, stderr = (
                await asyncio.wait_for(
                    process.communicate(),
                    timeout=self.timeout_seconds,
                )
            )

        except asyncio.TimeoutError:
            timed_out = True

            try:
                os.killpg(
                    process.pid,
                    signal.SIGKILL,
                )

            except (
                ProcessLookupError,
                PermissionError,
            ):

                try:
                    process.kill()

                except ProcessLookupError:
                    pass

            stdout, stderr = (
                await process.communicate()
            )

        stdout_text = stdout[
            : self.max_output_bytes
        ].decode(
            "utf-8",
            errors="replace",
        )

        stderr_text = stderr[
            : self.max_output_bytes
        ].decode(
            "utf-8",
            errors="replace",
        )

        return CommandResult(
            command=normalized,
            return_code=(
                process.returncode
                if process.returncode is not None
                else -1
            ),
            stdout=stdout_text,
            stderr=stderr_text,
            timed_out=timed_out,
        )

    async def python(
        self,
        args: Sequence[str],
        *,
        cwd: str | Path = ".",
    ) -> CommandResult:
        return await self.run(
            (
                sys.executable,
                *tuple(args),
            ),
            cwd=cwd,
        )

    async def compile_python(
        self,
        path: str | Path,
    ) -> CommandResult:
        resolved = self.guard.assert_allowed(
            path,
            allow_missing=False,
        )

        if resolved.suffix != ".py":
            raise ValueError(
                f"Expected Python file, got: "
                f"{resolved}"
            )

        relative = (
            resolved.relative_to(
                self.guard.workspace_root
            )
        )

        return await self.python(
            (
                "-m",
                "py_compile",
                str(relative),
            )
        )