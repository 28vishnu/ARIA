from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, asdict
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .github_manager import GitHubManager

logger = logging.getLogger("aria.github_pull_request")


@dataclass(frozen=True)
class PullRequestResult:
    success: bool
    operation: str
    number: int | None = None
    url: str | None = None
    title: str | None = None
    head: str | None = None
    base: str | None = None
    message: str = ""
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PullRequestAuthorization:
    approved: bool
    approved_by: str = "user"
    reason: str = ""

    def is_valid(self) -> bool:
        return (
            self.approved
            and bool(self.approved_by.strip())
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class GitHubPullRequestWorkflow:
    """
    Permissioned GitHub Pull Request workflow.

    Safe by default:

    - PR creation is disabled without explicit authorization.
    - GitHub credentials are read only inside this component.
    - Tokens are never returned in results.
    - No force push.
    - No automatic merge.
    - No automatic production deployment.
    """

    def __init__(
        self,
        github_manager: GitHubManager,
        *,
        api_timeout: float = 60.0,
    ) -> None:

        if api_timeout <= 0:
            raise ValueError(
                "api_timeout must be positive."
            )

        self.github = github_manager
        self.api_timeout = float(
            api_timeout
        )

        self._last_result: (
            PullRequestResult | None
        ) = None

    # ============================================================
    # TOKEN
    # ============================================================

    @staticmethod
    def _token() -> str | None:
        return (
            os.getenv("GITHUB_TOKEN")
            or os.getenv("GH_TOKEN")
        )

    # ============================================================
    # REPOSITORY
    # ============================================================

    async def repository(self):
        return await self.github.repository(
            "origin"
        )

    # ============================================================
    # READ-ONLY REMOTE CHECK
    # ============================================================

    async def remote_status(self) -> dict[str, Any]:

        repository = await self.repository()

        if repository is None:
            return {
                "available": False,
                "message": (
                    "No GitHub repository is configured "
                    "for origin."
                ),
            }

        return {
            "available": True,
            "owner": repository.owner,
            "name": repository.name,
            "default_branch": (
                repository.default_branch
            ),
            "authenticated": bool(
                self._token()
            ),
        }

    # ============================================================
    # VALIDATION
    # ============================================================

    @staticmethod
    def _validate_text(
        value: str,
        field: str,
        maximum: int,
    ) -> str:

        value = str(value or "").strip()

        if not value:
            raise ValueError(
                f"{field} cannot be empty."
            )

        if len(value) > maximum:
            raise ValueError(
                f"{field} exceeds {maximum} characters."
            )

        return value

    @staticmethod
    def _validate_branch(
        branch: str,
    ) -> str:

        branch = str(branch or "").strip()

        if not branch:
            raise ValueError(
                "head branch cannot be empty."
            )

        if (
            ".." in branch
            or "@{" in branch
            or branch.startswith("/")
            or branch.endswith("/")
        ):
            raise ValueError(
                "Unsafe Git branch name."
            )

        return branch

    # ============================================================
    # GITHUB API
    # ============================================================

    async def _api_request(
        self,
        *,
        method: str,
        url: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:

        token = self._token()

        if not token:
            raise RuntimeError(
                "No GitHub authentication token is configured."
            )

        body = None

        if payload is not None:
            body = json.dumps(
                payload
            ).encode("utf-8")

        request = Request(
            url,
            data=body,
            method=method.upper(),
            headers={
                "Accept": (
                    "application/vnd.github+json"
                ),
                "Content-Type": "application/json",
                "Authorization": (
                    f"Bearer {token}"
                ),
                "X-GitHub-Api-Version": (
                    "2022-11-28"
                ),
                "User-Agent": "ARIA-AI",
            },
        )

        def perform():
            try:

                with urlopen(
                    request,
                    timeout=self.api_timeout,
                ) as response:

                    raw = response.read()

                    if not raw:
                        return {}

                    return json.loads(
                        raw.decode(
                            "utf-8"
                        )
                    )

            except HTTPError as exc:

                try:
                    raw = exc.read()
                    decoded = raw.decode(
                        "utf-8",
                        errors="replace",
                    )
                except Exception:
                    decoded = ""

                raise RuntimeError(
                    f"GitHub API request failed "
                    f"with HTTP {exc.code}: "
                    f"{decoded[:1000]}"
                ) from exc

            except URLError as exc:

                raise RuntimeError(
                    f"GitHub API connection failed: "
                    f"{exc.reason}"
                ) from exc

        return await asyncio.to_thread(
            perform
        )

    # ============================================================
    # CREATE PR
    # ============================================================

    async def create(
        self,
        *,
        authorization: PullRequestAuthorization | None,
        head: str,
        base: str | None = None,
        title: str,
        body: str = "",
        draft: bool = False,
    ) -> PullRequestResult:

        if authorization is None:

            result = PullRequestResult(
                success=False,
                operation="create_pull_request",
                head=head,
                base=base,
                title=title,
                message=(
                    "Pull Request creation requires "
                    "explicit authorization."
                ),
            )

            self._last_result = result
            return result

        if not authorization.is_valid():

            result = PullRequestResult(
                success=False,
                operation="create_pull_request",
                head=head,
                base=base,
                title=title,
                message=(
                    "Pull Request authorization is invalid."
                ),
            )

            self._last_result = result
            return result

        try:

            head = self._validate_branch(
                head
            )

            title = self._validate_text(
                title,
                "title",
                256,
            )

            body = str(
                body or ""
            ).strip()

            if len(body) > 65536:
                raise ValueError(
                    "Pull Request body is too long."
                )

            repository = await self.repository()

            if repository is None:

                raise RuntimeError(
                    "No GitHub repository is configured."
                )

            base = (
                str(base).strip()
                if base
                else (
                    repository.default_branch
                    or "main"
                )
            )

            base = self._validate_branch(
                base
            )

            token = self._token()

            if not token:
                raise RuntimeError(
                    "No GitHub authentication token "
                    "is configured."
                )

            api_url = (
                "https://api.github.com/repos/"
                f"{repository.owner}/"
                f"{repository.name}/pulls"
            )

            response = await self._api_request(
                method="POST",
                url=api_url,
                payload={
                    "title": title,
                    "head": head,
                    "base": base,
                    "body": body,
                    "draft": bool(draft),
                },
            )

            number = response.get(
                "number"
            )

            html_url = response.get(
                "html_url"
            )

            result = PullRequestResult(
                success=True,
                operation="create_pull_request",
                number=(
                    int(number)
                    if number is not None
                    else None
                ),
                url=(
                    str(html_url)
                    if html_url
                    else None
                ),
                title=title,
                head=head,
                base=base,
                message=(
                    "GitHub Pull Request created successfully."
                ),
            )

        except Exception as exc:

            logger.exception(
                "GitHub Pull Request creation failed."
            )

            result = PullRequestResult(
                success=False,
                operation="create_pull_request",
                title=title,
                head=head,
                base=base,
                message=(
                    "GitHub Pull Request creation failed."
                ),
                error=str(exc),
            )

        self._last_result = result
        return result

    # ============================================================
    # INSPECTION
    # ============================================================

    def status(self) -> dict[str, Any]:

        return {
            "last_result": (
                self._last_result.to_dict()
                if self._last_result
                else None
            ),
            "authenticated": bool(
                self._token()
            ),
            "automatic_merge": False,
            "automatic_deployment": False,
        }

    def health(self) -> dict[str, Any]:

        return {
            "healthy": (
                self.github is not None
            ),
            "github_manager": (
                self.github is not None
            ),
            "authentication_configured": bool(
                self._token()
            ),
        }

    def describe(self) -> dict[str, Any]:

        return {
            "name": "github_pull_request",
            "capabilities": [
                "remote_repository_inspection",
                "pull_request_creation",
            ],
            "safety": [
                "explicit_pr_authorization",
                "no_force_push",
                "no_automatic_merge",
                "no_automatic_deployment",
                "token_hidden_from_model",
            ],
        }


__all__ = [
    "PullRequestResult",
    "PullRequestAuthorization",
    "GitHubPullRequestWorkflow",
]