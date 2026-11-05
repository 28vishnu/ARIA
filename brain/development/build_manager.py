from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .filesystem_guard import FilesystemGuard
from .sandbox import DevelopmentSandbox


@dataclass(frozen=True)
class BuildResult:
    success: bool
    build_id: str
    duration_seconds: float
    command: tuple[str, ...]
    return_code: int
    stdout: str
    stderr: str
    artifact_hash: str | None = None
    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "build_id": self.build_id,
            "duration_seconds": self.duration_seconds,
            "command": list(self.command),
            "return_code": self.return_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "artifact_hash": self.artifact_hash,
            "metadata": dict(self.metadata),
        }


class BuildManager:
    """
    Handles bounded builds inside a development workspace.

    The manager does not deploy anything.

    Build commands are explicitly supplied by the caller.
    Arbitrary production deployment commands are not
    automatically constructed here.
    """

    def __init__(
        self,
        sandbox: DevelopmentSandbox,
        *,
        build_timeout_seconds: float = 300.0,
        artifact_max_bytes: int = 50 * 1024 * 1024,
    ) -> None:

        if build_timeout_seconds <= 0:
            raise ValueError(
                "build_timeout_seconds must be positive."
            )

        if artifact_max_bytes <= 0:
            raise ValueError(
                "artifact_max_bytes must be positive."
            )

        self.sandbox = sandbox
        self.guard = sandbox.guard
        self.build_timeout_seconds = float(
            build_timeout_seconds
        )
        self.artifact_max_bytes = int(
            artifact_max_bytes
        )

    async def build(
        self,
        command: tuple[str, ...] | list[str],
        *,
        cwd: str = ".",
        build_id: str | None = None,
    ) -> BuildResult:

        if not command:
            raise ValueError(
                "Build command cannot be empty."
            )

        identifier = (
            build_id
            or f"build-{int(time.time())}"
        )

        started = time.monotonic()

        result = await self.sandbox.run(
            command,
            cwd=cwd,
        )

        duration = (
            time.monotonic() - started
        )

        return BuildResult(
            success=result.ok,
            build_id=identifier,
            duration_seconds=duration,
            command=result.command,
            return_code=result.return_code,
            stdout=result.stdout,
            stderr=result.stderr,
            metadata={
                "cwd": cwd,
            },
        )

    async def python_compile(
        self,
        *,
        path: str = ".",
        build_id: str | None = None,
    ) -> BuildResult:

        identifier = (
            build_id
            or f"python-compile-{int(time.time())}"
        )

        started = time.monotonic()

        result = await self.sandbox.python(
            (
                "-m",
                "compileall",
                "-q",
                path,
            )
        )

        duration = (
            time.monotonic() - started
        )

        return BuildResult(
            success=result.ok,
            build_id=identifier,
            duration_seconds=duration,
            command=result.command,
            return_code=result.return_code,
            stdout=result.stdout,
            stderr=result.stderr,
            metadata={
                "type": "python_compile",
                "path": path,
            },
        )

    def hash_file(
        self,
        path: str | Path,
    ) -> str:

        resolved = self.guard.assert_allowed(
            path,
            allow_missing=False,
        )

        if not resolved.is_file():
            raise IsADirectoryError(
                str(resolved)
            )

        size = resolved.stat().st_size

        if size > self.artifact_max_bytes:
            raise ValueError(
                "Artifact exceeds configured size limit."
            )

        digest = hashlib.sha256()

        with resolved.open(
            "rb"
        ) as file:

            while True:
                chunk = file.read(
                    1024 * 1024
                )

                if not chunk:
                    break

                digest.update(chunk)

        return digest.hexdigest()

    def write_build_manifest(
        self,
        result: BuildResult,
        *,
        path: str = "build-manifest.json",
    ) -> Path:

        target = self.guard.assert_allowed(
            path
        )

        target.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        target.write_text(
            json.dumps(
                result.to_dict(),
                indent=2,
            ),
            encoding="utf-8",
        )

        return target