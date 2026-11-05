"""
ARIA Phase 1 — Step 26
Permissioned Git / GitHub Workflow

Architecture:

    Autonomous Developer
            |
            v
    PermissionedGitWorkflow
            |
       +----+----+
       |         |
      Git      GitHub
       |         |
    commit     push
                ^
                |
        EXPLICIT USER APPROVAL

Important safety rule:

    ARIA may prepare and create local Git checkpoints
    according to the existing Git subsystem.

    ARIA MUST NOT push to GitHub unless the caller explicitly
    authorizes the push operation.

    Deployment is NOT performed by this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class GitWorkflowResult:
    success: bool
    status: str

    operation: str

    commit_created: bool = False
    push_attempted: bool = False
    push_authorized: bool = False
    pushed: bool = False

    commit_id: str | None = None
    branch: str | None = None
    remote: str | None = None

    message: str = ""

    errors: tuple[str, ...] = ()

    created_at: str = ""

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "status": self.status,
            "operation": self.operation,
            "commit_created": self.commit_created,
            "push_attempted": self.push_attempted,
            "push_authorized": self.push_authorized,
            "pushed": self.pushed,
            "commit_id": self.commit_id,
            "branch": self.branch,
            "remote": self.remote,
            "message": self.message,
            "errors": list(self.errors),
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }


class GitPushAuthorization:
    """
    Explicit, single-operation authorization object.

    An authorization is intentionally not a permanent permission.

    The caller must create a new authorization for each push request.
    """

    def __init__(
        self,
        *,
        approved: bool,
        reason: str = "",
        approved_by: str = "user",
        operation: str = "github_push",
    ) -> None:

        self.approved = bool(approved)
        self.reason = str(reason or "").strip()
        self.approved_by = (
            str(approved_by or "user").strip()
        )
        self.operation = (
            str(operation or "github_push").strip()
        )

        self.created_at = _utc_now()

    def is_valid(self) -> bool:
        return (
            self.approved
            and self.operation == "github_push"
            and bool(self.approved_by)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "approved": self.approved,
            "reason": self.reason,
            "approved_by": self.approved_by,
            "operation": self.operation,
            "created_at": self.created_at,
        }


class PermissionedGitWorkflow:
    """
    Safety wrapper around existing Git and GitHub services.

    The services are dependency-injected deliberately.

    This prevents this layer from becoming a second Git implementation.

    Supported service styles are intentionally flexible because ARIA's
    existing Git/GitHub implementations may expose different method names.
    """

    LOCAL_GIT_METHODS = (
        "commit",
        "create_commit",
        "checkpoint",
        "create_checkpoint",
    )

    STATUS_METHODS = (
        "status",
        "get_status",
        "repository_status",
    )

    PUSH_METHODS = (
        "push",
        "push_to_github",
        "github_push",
        "push_changes",
    )

    BRANCH_METHODS = (
        "current_branch",
        "get_current_branch",
        "branch",
    )

    def __init__(
        self,
        git_service=None,
        github_service=None,
    ) -> None:

        self.git = git_service
        self.github = github_service

        self._last_result: (
            GitWorkflowResult | None
        ) = None

    # ==========================================================
    # SERVICE DISCOVERY
    # ==========================================================

    @staticmethod
    def _find_method(
        service: Any,
        names: tuple[str, ...],
    ):
        if service is None:
            return None

        for name in names:
            method = getattr(
                service,
                name,
                None,
            )

            if callable(method):
                return method

        return None

    @staticmethod
    async def _call(
        method,
        **kwargs,
    ):
        """
        Call an existing service method while tolerating common
        synchronous/asynchronous implementations.
        """

        result = method(**kwargs)

        if hasattr(
            result,
            "__await__",
        ):
            result = await result

        return result

    @staticmethod
    def _extract(
        result: Any,
        *names: str,
        default=None,
    ):
        if result is None:
            return default

        if isinstance(
            result,
            Mapping,
        ):
            for name in names:
                if name in result:
                    return result[name]

            return default

        for name in names:
            value = getattr(
                result,
                name,
                None,
            )

            if value is not None:
                return value

        return default

    # ==========================================================
    # LOCAL GIT
    # ==========================================================

    async def create_checkpoint(
        self,
        *,
        message: str,
        workspace_id: str | None = None,
        files: list[str] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> GitWorkflowResult:
        """
        Create a local Git checkpoint.

        No GitHub operation is performed.
        """

        method = self._find_method(
            self.git,
            self.LOCAL_GIT_METHODS,
        )

        if method is None:
            result = GitWorkflowResult(
                success=False,
                status="git_service_unavailable",
                operation="commit",
                message=(
                    "No compatible local Git commit "
                    "method is available."
                ),
                created_at=_utc_now(),
            )

            self._last_result = result
            return result

        try:
            response = await self._call(
                method,
                message=message,
                workspace_id=workspace_id,
                files=files,
            )

            success = bool(
                self._extract(
                    response,
                    "success",
                    "ok",
                    default=True,
                )
            )

            commit_id = self._extract(
                response,
                "commit_id",
                "sha",
                "hash",
                "commit",
            )

            branch = self._extract(
                response,
                "branch",
                "branch_name",
            )

            result = GitWorkflowResult(
                success=success,
                status=(
                    "commit_created"
                    if success
                    else "commit_failed"
                ),
                operation="commit",
                commit_created=success,
                commit_id=(
                    str(commit_id)
                    if commit_id
                    else None
                ),
                branch=(
                    str(branch)
                    if branch
                    else None
                ),
                message=message,
                created_at=_utc_now(),
                metadata=dict(
                    metadata or {}
                ),
            )

        except Exception as exc:

            result = GitWorkflowResult(
                success=False,
                status="commit_error",
                operation="commit",
                message=message,
                errors=(str(exc),),
                created_at=_utc_now(),
                metadata=dict(
                    metadata or {}
                ),
            )

        self._last_result = result
        return result

    # ==========================================================
    # GITHUB PUSH
    # ==========================================================

    async def push_to_github(
        self,
        *,
        authorization: GitPushAuthorization | None,
        branch: str | None = None,
        remote: str = "origin",
        commit_id: str | None = None,
        workspace_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> GitWorkflowResult:
        """
        Push to GitHub ONLY when explicit authorization is supplied.

        There is deliberately no default authorization.

        Passing None always blocks the operation.
        """

        if authorization is None:
            result = GitWorkflowResult(
                success=False,
                status="push_not_authorized",
                operation="github_push",
                push_attempted=False,
                push_authorized=False,
                pushed=False,
                branch=branch,
                remote=remote,
                commit_id=commit_id,
                message=(
                    "GitHub push requires explicit user "
                    "authorization."
                ),
                created_at=_utc_now(),
                metadata=dict(
                    metadata or {}
                ),
            )

            self._last_result = result
            return result

        if not authorization.is_valid():
            result = GitWorkflowResult(
                success=False,
                status="invalid_authorization",
                operation="github_push",
                push_attempted=False,
                push_authorized=False,
                pushed=False,
                branch=branch,
                remote=remote,
                commit_id=commit_id,
                message=(
                    "The supplied GitHub push authorization "
                    "is invalid."
                ),
                created_at=_utc_now(),
                metadata={
                    **dict(metadata or {}),
                    "authorization":
                        authorization.to_dict(),
                },
            )

            self._last_result = result
            return result

        method = self._find_method(
            self.github,
            self.PUSH_METHODS,
        )

        if method is None:
            result = GitWorkflowResult(
                success=False,
                status="github_service_unavailable",
                operation="github_push",
                push_attempted=False,
                push_authorized=True,
                pushed=False,
                branch=branch,
                remote=remote,
                commit_id=commit_id,
                message=(
                    "No compatible GitHub push method "
                    "is available."
                ),
                created_at=_utc_now(),
                metadata={
                    **dict(metadata or {}),
                    "authorization":
                        authorization.to_dict(),
                },
            )

            self._last_result = result
            return result

        try:
            response = await self._call(
                method,
                branch=branch,
                remote=remote,
                commit_id=commit_id,
                workspace_id=workspace_id,
            )

            pushed = bool(
                self._extract(
                    response,
                    "pushed",
                    "success",
                    "ok",
                    default=True,
                )
            )

            result = GitWorkflowResult(
                success=pushed,
                status=(
                    "github_push_completed"
                    if pushed
                    else "github_push_failed"
                ),
                operation="github_push",
                push_attempted=True,
                push_authorized=True,
                pushed=pushed,
                branch=branch,
                remote=remote,
                commit_id=commit_id,
                message=(
                    "GitHub push completed."
                    if pushed
                    else "GitHub push failed."
                ),
                created_at=_utc_now(),
                metadata={
                    **dict(metadata or {}),
                    "authorization":
                        authorization.to_dict(),
                },
            )

        except Exception as exc:

            result = GitWorkflowResult(
                success=False,
                status="github_push_error",
                operation="github_push",
                push_attempted=True,
                push_authorized=True,
                pushed=False,
                branch=branch,
                remote=remote,
                commit_id=commit_id,
                message="GitHub push raised an exception.",
                errors=(str(exc),),
                created_at=_utc_now(),
                metadata={
                    **dict(metadata or {}),
                    "authorization":
                        authorization.to_dict(),
                },
            )

        self._last_result = result
        return result

    # ==========================================================
    # COMBINED CHECKPOINT + OPTIONAL PUSH
    # ==========================================================

    async def checkpoint(
        self,
        *,
        message: str,
        workspace_id: str | None = None,
        files: list[str] | None = None,
        branch: str | None = None,
        remote: str = "origin",
        push: bool = False,
        authorization: GitPushAuthorization | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> GitWorkflowResult:
        """
        Create a local checkpoint.

        If push=False:
            only local Git is touched.

        If push=True:
            a valid explicit authorization object is mandatory.
        """

        commit_result = (
            await self.create_checkpoint(
                message=message,
                workspace_id=workspace_id,
                files=files,
                metadata=metadata,
            )
        )

        if not commit_result.success:
            return commit_result

        if not push:
            return commit_result

        return await self.push_to_github(
            authorization=authorization,
            branch=branch
            or commit_result.branch,
            remote=remote,
            commit_id=commit_result.commit_id,
            workspace_id=workspace_id,
            metadata=metadata,
        )

    # ==========================================================
    # READ-ONLY STATUS
    # ==========================================================

    async def repository_status(
        self,
        *,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:

        method = self._find_method(
            self.git,
            self.STATUS_METHODS,
        )

        if method is None:
            return {
                "available": False,
                "status": "git_service_unavailable",
            }

        try:

            response = await self._call(
                method,
                workspace_id=workspace_id,
            )

            if isinstance(
                response,
                Mapping,
            ):
                return {
                    "available": True,
                    **dict(response),
                }

            return {
                "available": True,
                "status": str(response),
            }

        except Exception as exc:

            return {
                "available": False,
                "status": "error",
                "error": str(exc),
            }

    # ==========================================================
    # INSPECTION
    # ==========================================================

    def status(self) -> dict[str, Any]:
        return {
            "has_git_service": (
                self.git is not None
            ),
            "has_github_service": (
                self.github is not None
            ),
            "last_result": (
                self._last_result.to_dict()
                if self._last_result is not None
                else None
            ),
        }

    def health(self) -> dict[str, Any]:
        return {
            "healthy": (
                self.git is not None
                or self.github is not None
            ),
            "git_available": (
                self.git is not None
            ),
            "github_available": (
                self.github is not None
            ),
        }

    def describe(self) -> dict[str, Any]:
        return {
            "name": "permissioned_git_workflow",
            "purpose": (
                "Safely coordinate local Git checkpoints and "
                "explicitly authorized GitHub pushes."
            ),
            "local_git": True,
            "github_push": True,
            "push_requires_explicit_authorization": True,
            "default_push": False,
            "deployment": False,
            "automatic_github_push": False,
        }


__all__ = [
    "GitWorkflowResult",
    "GitPushAuthorization",
    "PermissionedGitWorkflow",
]