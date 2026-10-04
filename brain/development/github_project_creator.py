from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from typing import Any

logger = logging.getLogger("aria.github_project_creator")


@dataclass(frozen=True)
class ProjectCreationAuthorization:
    approved: bool
    approved_by: str = "Master"
    reason: str = ""

    def is_valid(self) -> bool:
        return self.approved and bool(self.approved_by.strip())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProjectCreationResult:
    success: bool
    operation: str
    project_path: str | None = None
    repository_url: str | None = None
    clone_url: str | None = None
    branch: str | None = None
    message: str = ""
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class GitHubProjectCreator:
    """Permissioned creation of isolated local/GitHub projects."""

    def __init__(
        self,
        *,
        workspace_root: str | Path,
        api_timeout: float = 60.0,
    ) -> None:
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.api_timeout = float(api_timeout)
        if self.api_timeout <= 0:
            raise ValueError("api_timeout must be positive.")
        self._last_result: ProjectCreationResult | None = None

    @staticmethod
    def _validate_name(name: str) -> str:
        value = str(name or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", value):
            raise ValueError(
                "Project/repository name must contain only letters, numbers, '.', '_' or '-'."
            )
        if value in {".", ".."}:
            raise ValueError("Unsafe project name.")
        return value

    @staticmethod
    def _validate_branch(branch: str) -> str:
        value = str(branch or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9._/-]+", value):
            raise ValueError("Invalid initial branch name.")
        if ".." in value or "@{" in value or value.startswith("/") or value.endswith("/"):
            raise ValueError("Unsafe initial branch name.")
        return value

    @staticmethod
    def _token() -> str | None:
        return os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")

    async def _api_request(
        self,
        *,
        method: str,
        url: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        token = self._token()
        if not token:
            raise RuntimeError("No GitHub authentication token is configured.")

        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(
            url,
            data=body,
            method=method.upper(),
            headers={
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "ARIA-AI",
            },
        )

        def perform() -> dict[str, Any]:
            try:
                with urlopen(request, timeout=self.api_timeout) as response:
                    raw = response.read()
                    return json.loads(raw.decode("utf-8")) if raw else {}
            except HTTPError as exc:
                try:
                    detail = exc.read().decode("utf-8", errors="replace")[:1200]
                except Exception:
                    detail = ""
                raise RuntimeError(
                    f"GitHub API request failed with HTTP {exc.code}: {detail}"
                ) from exc
            except URLError as exc:
                raise RuntimeError(f"GitHub API connection failed: {exc.reason}") from exc

        return await asyncio.to_thread(perform)

    async def create_local(
        self,
        *,
        name: str,
        branch: str = "main",
        description: str = "",
    ) -> ProjectCreationResult:
        try:
            name = self._validate_name(name)
            branch = self._validate_branch(branch)
            destination = (self.workspace_root / name).resolve()

            if destination.parent != self.workspace_root:
                raise ValueError("Project path escaped the workspace root.")
            if destination.exists() and any(destination.iterdir()):
                raise FileExistsError(
                    f"Project directory already exists and is not empty: {destination}"
                )

            destination.mkdir(parents=True, exist_ok=True)

            def run_git(*args: str) -> tuple[int, str, str]:
                import subprocess
                process = subprocess.run(
                    ["git", *args],
                    cwd=str(destination),
                    env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
                    capture_output=True,
                    text=True,
                    timeout=self.api_timeout,
                )
                return process.returncode, process.stdout, process.stderr

            code, stdout, stderr = run_git("init", "-b", branch)
            if code != 0:
                # Older Git versions may not support -b on init.
                code, stdout, stderr = run_git("init")
                if code != 0:
                    raise RuntimeError(stderr or stdout or "git init failed")
                code, stdout, stderr = run_git("switch", "-c", branch)
                if code != 0:
                    raise RuntimeError(stderr or stdout or "initial branch creation failed")

            readme = destination / "README.md"
            readme.write_text(
                f"# {name}\n\n{description.strip()}\n",
                encoding="utf-8",
            )

            gitignore = destination / ".gitignore"
            if not gitignore.exists():
                gitignore.write_text(
                    "__pycache__/\n.env\n.venv/\n*.pyc\n",
                    encoding="utf-8",
                )

            code, stdout, stderr = run_git("add", "README.md", ".gitignore")
            if code != 0:
                raise RuntimeError(stderr or stdout or "git add failed")

            code, stdout, stderr = run_git("-c", "user.name=ARIA AI", "-c", "user.email=aria@localhost", "commit", "-m", "Initialize project")
            if code != 0:
                raise RuntimeError(stderr or stdout or "initial commit failed")

            result = ProjectCreationResult(
                success=True,
                operation="create_local",
                project_path=str(destination),
                branch=branch,
                message="Isolated local project created successfully.",
            )
        except Exception as exc:
            logger.exception("Local project creation failed.")
            result = ProjectCreationResult(
                success=False,
                operation="create_local",
                message="Local project creation failed.",
                error=str(exc),
            )

        self._last_result = result
        return result

    async def create_github_repository(
        self,
        *,
        name: str,
        description: str = "",
        private: bool = True,
        authorization: ProjectCreationAuthorization | None = None,
    ) -> ProjectCreationResult:
        if authorization is None or not authorization.is_valid():
            result = ProjectCreationResult(
                success=False,
                operation="create_github_repository",
                message="GitHub repository creation requires explicit Master authorization.",
            )
            self._last_result = result
            return result

        try:
            name = self._validate_name(name)
            payload = {
                "name": name,
                "description": str(description or "")[:350],
                "private": bool(private),
                "auto_init": False,
            }
            response = await self._api_request(
                method="POST",
                url="https://api.github.com/user/repos",
                payload=payload,
            )
            result = ProjectCreationResult(
                success=True,
                operation="create_github_repository",
                repository_url=response.get("html_url"),
                clone_url=response.get("clone_url"),
                message="GitHub repository created successfully.",
            )
        except Exception as exc:
            logger.exception("GitHub repository creation failed.")
            result = ProjectCreationResult(
                success=False,
                operation="create_github_repository",
                message="GitHub repository creation failed.",
                error=str(exc),
            )

        self._last_result = result
        return result

    async def create_project(
        self,
        *,
        name: str,
        description: str = "",
        branch: str = "main",
        create_remote: bool = False,
        private: bool = True,
        authorization: ProjectCreationAuthorization | None = None,
    ) -> ProjectCreationResult:
        if create_remote and (authorization is None or not authorization.is_valid()):
            result = ProjectCreationResult(
                success=False,
                operation="create_project",
                message="Remote project creation requires explicit Master authorization.",
            )
            self._last_result = result
            return result

        local = await self.create_local(
            name=name,
            branch=branch,
            description=description,
        )
        if not local.success:
            return local

        if not create_remote:
            return local

        remote = await self.create_github_repository(
            name=name,
            description=description,
            private=private,
            authorization=authorization,
        )
        if not remote.success:
            return ProjectCreationResult(
                success=False,
                operation="create_project",
                project_path=local.project_path,
                branch=branch,
                message=(
                    "Local project was created, but GitHub repository creation failed."
                ),
                error=remote.error,
            )

        try:
            destination = Path(local.project_path).resolve()
            import subprocess
            process = await asyncio.to_thread(
                subprocess.run,
                ["git", "remote", "add", "origin", remote.clone_url],
                cwd=str(destination),
                env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
                capture_output=True,
                text=True,
                timeout=self.api_timeout,
            )
            if process.returncode != 0:
                raise RuntimeError(process.stderr or process.stdout or "git remote add failed")
        except Exception as exc:
            return ProjectCreationResult(
                success=False,
                operation="create_project",
                project_path=local.project_path,
                repository_url=remote.repository_url,
                clone_url=remote.clone_url,
                branch=branch,
                message="GitHub repository exists, but local remote configuration failed.",
                error=str(exc),
            )

        result = ProjectCreationResult(
            success=True,
            operation="create_project",
            project_path=local.project_path,
            repository_url=remote.repository_url,
            clone_url=remote.clone_url,
            branch=branch,
            message="Local project and GitHub repository created successfully.",
        )
        self._last_result = result
        return result

    def status(self) -> dict[str, Any]:
        return {
            "workspace_root": str(self.workspace_root),
            "github_authentication_configured": bool(self._token()),
            "last_result": self._last_result.to_dict() if self._last_result else None,
            "remote_creation_requires_authorization": True,
        }

    def health(self) -> dict[str, Any]:
        return {
            "healthy": self.workspace_root.is_dir(),
            "workspace_root": str(self.workspace_root),
            "github_authentication_configured": bool(self._token()),
        }

    def describe(self) -> dict[str, Any]:
        return {
            "name": "github_project_creator",
            "capabilities": [
                "create_isolated_local_project",
                "initialize_git",
                "create_github_repository_with_authorization",
                "connect_local_project_to_github",
            ],
            "safety": [
                "isolated_workspace_root",
                "existing_nonempty_directory_protection",
                "explicit_master_authorization_for_remote_creation",
                "token_hidden_from_model",
                "no_force_push",
                "no_automatic_deployment",
            ],
        }


__all__ = [
    "ProjectCreationAuthorization",
    "ProjectCreationResult",
    "GitHubProjectCreator",
]
