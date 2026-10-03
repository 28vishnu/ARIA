from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from typing import Any, Sequence

from .build_manager import BuildResult
from .git_manager import GitManager


@dataclass(frozen=True)
class DeploymentResult:
    success: bool
    deployment_id: str
    version: str
    environment: str
    duration_seconds: float
    command: tuple[str, ...] = ()
    return_code: int = 0
    stdout: str = ""
    stderr: str = ""
    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "deployment_id": self.deployment_id,
            "version": self.version,
            "environment": self.environment,
            "duration_seconds": self.duration_seconds,
            "command": list(self.command),
            "return_code": self.return_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "metadata": dict(self.metadata),
        }


class DeploymentManager:
    """
    Controls deployment commands.

    Important:

    - Production deployment is disabled by default.
    - Staging and production are treated separately.
    - The caller must explicitly authorize deployment.
    - A successful build is required before deployment.
    - This class does not decide whether ARIA is allowed to deploy.
      That belongs to deployment_policy.py in Step 8.
    """

    def __init__(
        self,
        git_manager: GitManager,
        *,
        allow_staging: bool = True,
        allow_production: bool = False,
        command_timeout_seconds: float = 600.0,
    ) -> None:

        if command_timeout_seconds <= 0:
            raise ValueError(
                "command_timeout_seconds must be positive."
            )

        self.git = git_manager
        self.allow_staging = bool(
            allow_staging
        )
        self.allow_production = bool(
            allow_production
        )
        self.command_timeout_seconds = float(
            command_timeout_seconds
        )

    async def deploy(
        self,
        build: BuildResult,
        *,
        version: str,
        environment: str = "staging",
        command: Sequence[str] | None = None,
        explicit_authorization: bool = False,
    ) -> DeploymentResult:

        environment = environment.strip().lower()

        if environment not in {
            "staging",
            "production",
        }:
            raise ValueError(
                "environment must be staging or production."
            )

        if not build.success:
            return DeploymentResult(
                success=False,
                deployment_id=(
                    f"deployment-{int(time.time())}"
                ),
                version=version,
                environment=environment,
                duration_seconds=0.0,
                stderr=(
                    "Deployment blocked because "
                    "the build did not succeed."
                ),
            )

        if environment == "production":
            if not self.allow_production:
                return DeploymentResult(
                    success=False,
                    deployment_id=(
                        f"deployment-{int(time.time())}"
                    ),
                    version=version,
                    environment=environment,
                    duration_seconds=0.0,
                    return_code=126,
                    stderr=(
                        "Production deployment is "
                        "disabled."
                    ),
                )

            if not explicit_authorization:
                return DeploymentResult(
                    success=False,
                    deployment_id=(
                        f"deployment-{int(time.time())}"
                    ),
                    version=version,
                    environment=environment,
                    duration_seconds=0.0,
                    return_code=126,
                    stderr=(
                        "Explicit production deployment "
                        "authorization is required."
                    ),
                )

        if (
            environment == "staging"
            and not self.allow_staging
        ):
            return DeploymentResult(
                success=False,
                deployment_id=(
                    f"deployment-{int(time.time())}"
                ),
                version=version,
                environment=environment,
                duration_seconds=0.0,
                return_code=126,
                stderr=(
                    "Staging deployment is disabled."
                ),
            )

        if not command:
            return DeploymentResult(
                success=False,
                deployment_id=(
                    f"deployment-{int(time.time())}"
                ),
                version=version,
                environment=environment,
                duration_seconds=0.0,
                return_code=127,
                stderr=(
                    "No deployment command was supplied."
                ),
            )

        safe_command = tuple(
            str(item)
            for item in command
        )

        if not safe_command:
            raise ValueError(
                "Deployment command cannot be empty."
            )

        started = time.monotonic()

        environment_vars = {
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
                *safe_command,
                cwd=str(
                    self.git.repository_root
                ),
                env=environment_vars,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        )

        try:

            stdout, stderr = (
                await asyncio.wait_for(
                    process.communicate(),
                    timeout=self.command_timeout_seconds,
                )
            )

        except asyncio.TimeoutError:

            try:
                process.kill()
            except ProcessLookupError:
                pass

            await process.communicate()

            return DeploymentResult(
                success=False,
                deployment_id=(
                    f"deployment-{int(time.time())}"
                ),
                version=version,
                environment=environment,
                duration_seconds=(
                    time.monotonic() - started
                ),
                command=safe_command,
                return_code=-1,
                stderr=(
                    "Deployment command timed out."
                ),
            )

        return DeploymentResult(
            success=(
                process.returncode == 0
            ),
            deployment_id=(
                f"deployment-{int(time.time())}"
            ),
            version=version,
            environment=environment,
            duration_seconds=(
                time.monotonic() - started
            ),
            command=safe_command,
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