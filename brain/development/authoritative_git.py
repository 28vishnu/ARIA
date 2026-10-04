from __future__ import annotations

import re
from typing import Any

from .contracts.engineering_git import (
    GitAuthorization,
    GitLifecyclePlan,
    GitLifecycleRequest,
    GitLifecycleResult,
    GitLifecycleStatus,
    GitOperation,
    GitRisk,
)


class AuthoritativeGitLifecycle:
    """
    Controlled Git/GitHub lifecycle boundary.

    This component can coordinate existing Git/GitHub services, but it
    never assumes that successful engineering automatically authorizes
    push or merge.

    Push and merge require explicit authorization.
    """

    def __init__(
        self,
        *,
        git_service: Any | None = None,
        github_service: Any | None = None,
    ) -> None:
        self.git_service = git_service
        self.github_service = github_service

    def plan(
        self,
        request: GitLifecycleRequest,
    ) -> GitLifecyclePlan:
        operations: list[GitOperation] = [
            GitOperation.CREATE_BRANCH,
            GitOperation.COMMIT,
        ]

        approval_required: list[GitOperation] = []

        if request.explicit_push_authorized:
            operations.append(
                GitOperation.PUSH
            )
        else:
            approval_required.append(
                GitOperation.PUSH
            )

        if request.create_pr:
            operations.append(
                GitOperation.CREATE_PR
            )

        if request.merge_pr:
            operations.append(
                GitOperation.MERGE_PR
            )

            if not request.explicit_merge_authorized:
                approval_required.append(
                    GitOperation.MERGE_PR
                )

        risk = self._risk(
            request,
            operations,
        )

        status = (
            GitLifecycleStatus.READY
            if not approval_required
            else GitLifecycleStatus.AWAITING_APPROVAL
        )

        return GitLifecyclePlan(
            session_id=request.session_id,
            branch_name=self._normalize_branch(
                request.branch_name
            ),
            commit_message=self._normalize_commit_message(
                request.commit_message
            ),
            operations=tuple(operations),
            risk=risk,
            status=status,
            changed_paths=tuple(
                request.changed_paths
            ),
            remote=request.remote or "origin",
            base_branch=request.base_branch,
            pr_title=(
                f"ARIA: {request.requirement[:80]}"
                if request.create_pr
                else None
            ),
            pr_body=(
                self._build_pr_body(request)
                if request.create_pr
                else None
            ),
            rollback_required=True,
            approval_required=tuple(
                approval_required
            ),
            rationale=(
                "Git lifecycle is separated from engineering acceptance. "
                "Branching and commit preparation may proceed, while "
                "push and merge remain explicitly authorized operations."
            ),
        )

    async def execute(
        self,
        plan: GitLifecyclePlan,
        *,
        authorizations: tuple[GitAuthorization, ...] = (),
    ) -> GitLifecycleResult:
        """
        Execute the authorized portion of a Git lifecycle.

        Existing service APIs are discovered through compatibility
        methods rather than replacing the repository's Git services.
        """
        if not plan.session_id:
            return self._failed(
                plan,
                "Git lifecycle requires a session_id.",
            )

        authorization_map = {
            authorization.operation: authorization
            for authorization in authorizations
        }

        branch_result = await self._create_branch(
            plan
        )

        if not branch_result[0]:
            return self._failed(
                plan,
                branch_result[1],
            )

        commit_result = await self._commit(
            plan
        )

        if not commit_result[0]:
            return self._failed(
                plan,
                commit_result[1],
            )

        commit_sha = commit_result[2]

        push_authorization = authorization_map.get(
            GitOperation.PUSH
        )

        if GitOperation.PUSH in plan.operations:
            if not self._authorized(
                push_authorization
            ):
                return GitLifecycleResult(
                    status=GitLifecycleStatus.AWAITING_APPROVAL,
                    operation=GitOperation.PUSH,
                    branch_name=plan.branch_name,
                    commit_sha=commit_sha,
                    remote=plan.remote,
                    rollback_available=True,
                    warnings=(
                        "Commit completed, but push is not authorized.",
                    ),
                    evidence=(
                        {
                            "stage": "commit",
                            "status": "completed",
                            "commit_sha": commit_sha,
                        },
                    ),
                )

            push_result = await self._push(
                plan
            )

            if not push_result[0]:
                return self._failed(
                    plan,
                    push_result[1],
                    operation=GitOperation.PUSH,
                    commit_sha=commit_sha,
                )

        pushed = GitOperation.PUSH in plan.operations

        if GitOperation.CREATE_PR in plan.operations:
            if not pushed:
                return GitLifecycleResult(
                    status=GitLifecycleStatus.BLOCKED,
                    operation=GitOperation.CREATE_PR,
                    branch_name=plan.branch_name,
                    commit_sha=commit_sha,
                    remote=plan.remote,
                    pushed=False,
                    rollback_available=True,
                    errors=(
                        "A pull request cannot be created before "
                        "the branch is pushed.",
                    ),
                )

            pr_result = await self._create_pr(
                plan
            )

            if not pr_result[0]:
                return self._failed(
                    plan,
                    pr_result[1],
                    operation=GitOperation.CREATE_PR,
                    commit_sha=commit_sha,
                )

            pr_url = pr_result[2]

            if GitOperation.MERGE_PR in plan.operations:
                merge_authorization = authorization_map.get(
                    GitOperation.MERGE_PR
                )

                if not self._authorized(
                    merge_authorization
                ):
                    return GitLifecycleResult(
                        status=GitLifecycleStatus.AWAITING_APPROVAL,
                        operation=GitOperation.MERGE_PR,
                        branch_name=plan.branch_name,
                        commit_sha=commit_sha,
                        remote=plan.remote,
                        pushed=True,
                        pull_request_url=pr_url,
                        rollback_available=True,
                        warnings=(
                            "Pull request created, but merge is not "
                            "authorized.",
                        ),
                    )

                merge_result = await self._merge_pr(
                    plan,
                    pr_url,
                )

                if not merge_result[0]:
                    return self._failed(
                        plan,
                        merge_result[1],
                        operation=GitOperation.MERGE_PR,
                        commit_sha=commit_sha,
                    )

                return GitLifecycleResult(
                    status=GitLifecycleStatus.COMPLETED,
                    operation=GitOperation.MERGE_PR,
                    branch_name=plan.branch_name,
                    commit_sha=commit_sha,
                    remote=plan.remote,
                    pushed=True,
                    pull_request_url=pr_url,
                    merged=True,
                    rollback_available=True,
                )

            return GitLifecycleResult(
                status=GitLifecycleStatus.COMPLETED,
                operation=GitOperation.CREATE_PR,
                branch_name=plan.branch_name,
                commit_sha=commit_sha,
                remote=plan.remote,
                pushed=True,
                pull_request_url=pr_url,
                rollback_available=True,
            )

        return GitLifecycleResult(
            status=GitLifecycleStatus.COMPLETED,
            operation=(
                GitOperation.PUSH
                if pushed
                else GitOperation.COMMIT
            ),
            branch_name=plan.branch_name,
            commit_sha=commit_sha,
            remote=plan.remote,
            pushed=pushed,
            rollback_available=True,
        )

    async def _create_branch(
        self,
        plan: GitLifecyclePlan,
    ) -> tuple[bool, str]:
        if self.git_service is None:
            return (
                False,
                "Git service is unavailable.",
            )

        methods = (
            "create_branch",
            "checkout_new_branch",
            "branch_create",
        )

        for name in methods:
            method = getattr(
                self.git_service,
                name,
                None,
            )

            if not callable(method):
                continue

            try:
                result = method(
                    plan.branch_name
                )

                if hasattr(result, "__await__"):
                    result = await result

                if result is False:
                    return (
                        False,
                        f"Git branch creation failed: {name}",
                    )

                return True, ""

            except TypeError:
                try:
                    result = method(
                        branch_name=plan.branch_name
                    )

                    if hasattr(result, "__await__"):
                        result = await result

                    if result is False:
                        return (
                            False,
                            f"Git branch creation failed: {name}",
                        )

                    return True, ""

                except Exception as exc:
                    return (
                        False,
                        f"Git branch creation failed: {exc}",
                    )

            except Exception as exc:
                return (
                    False,
                    f"Git branch creation failed: {exc}",
                )

        return (
            False,
            "Git service has no supported branch creation method.",
        )

    async def _commit(
        self,
        plan: GitLifecyclePlan,
    ) -> tuple[bool, str, str | None]:
        if self.git_service is None:
            return (
                False,
                "Git service is unavailable.",
                None,
            )

        methods = (
            "commit",
            "create_commit",
            "commit_changes",
        )

        for name in methods:
            method = getattr(
                self.git_service,
                name,
                None,
            )

            if not callable(method):
                continue

            try:
                result = method(
                    plan.commit_message
                )

                if hasattr(result, "__await__"):
                    result = await result

                return self._normalize_commit_result(
                    result,
                    name,
                )

            except TypeError:
                try:
                    result = method(
                        message=plan.commit_message
                    )

                    if hasattr(result, "__await__"):
                        result = await result

                    return self._normalize_commit_result(
                        result,
                        name,
                    )

                except Exception as exc:
                    return (
                        False,
                        f"Git commit failed: {exc}",
                        None,
                    )

            except Exception as exc:
                return (
                    False,
                    f"Git commit failed: {exc}",
                    None,
                )

        return (
            False,
            "Git service has no supported commit method.",
            None,
        )

    async def _push(
        self,
        plan: GitLifecyclePlan,
    ) -> tuple[bool, str]:
        if self.git_service is None:
            return (
                False,
                "Git service is unavailable.",
            )

        methods = (
            "push",
            "push_branch",
            "push_changes",
        )

        for name in methods:
            method = getattr(
                self.git_service,
                name,
                None,
            )

            if not callable(method):
                continue

            try:
                result = method(
                    plan.remote,
                    plan.branch_name,
                )

                if hasattr(result, "__await__"):
                    result = await result

                if result is False:
                    return (
                        False,
                        f"Git push failed: {name}",
                    )

                return True, ""

            except TypeError:
                try:
                    result = method(
                        remote=plan.remote,
                        branch=plan.branch_name,
                    )

                    if hasattr(result, "__await__"):
                        result = await result

                    if result is False:
                        return (
                            False,
                            f"Git push failed: {name}",
                        )

                    return True, ""

                except Exception as exc:
                    return (
                        False,
                        f"Git push failed: {exc}",
                    )

            except Exception as exc:
                return (
                    False,
                    f"Git push failed: {exc}",
                )

        return (
            False,
            "Git service has no supported push method.",
        )

    async def _create_pr(
        self,
        plan: GitLifecyclePlan,
    ) -> tuple[bool, str, str | None]:
        if self.github_service is None:
            return (
                False,
                "GitHub service is unavailable.",
                None,
            )

        methods = (
            "create_pull_request",
            "create_pr",
            "open_pull_request",
        )

        for name in methods:
            method = getattr(
                self.github_service,
                name,
                None,
            )

            if not callable(method):
                continue

            try:
                result = method(
                    title=plan.pr_title or plan.commit_message,
                    body=plan.pr_body or "",
                    head=plan.branch_name,
                    base=plan.base_branch,
                )

                if hasattr(result, "__await__"):
                    result = await result

                url = self._extract_url(
                    result
                )

                if result is False:
                    return (
                        False,
                        f"Pull request creation failed: {name}",
                        None,
                    )

                return True, "", url

            except TypeError:
                try:
                    result = method(
                        plan.pr_title or plan.commit_message,
                        plan.pr_body or "",
                        plan.branch_name,
                        plan.base_branch,
                    )

                    if hasattr(result, "__await__"):
                        result = await result

                    url = self._extract_url(
                        result
                    )

                    return True, "", url

                except Exception as exc:
                    return (
                        False,
                        f"Pull request creation failed: {exc}",
                        None,
                    )

            except Exception as exc:
                return (
                    False,
                    f"Pull request creation failed: {exc}",
                    None,
                )

        return (
            False,
            "GitHub service has no supported PR method.",
            None,
        )

    async def _merge_pr(
        self,
        plan: GitLifecyclePlan,
        pr_url: str | None,
    ) -> tuple[bool, str]:
        if self.github_service is None:
            return (
                False,
                "GitHub service is unavailable.",
            )

        methods = (
            "merge_pull_request",
            "merge_pr",
            "merge",
        )

        for name in methods:
            method = getattr(
                self.github_service,
                name,
                None,
            )

            if not callable(method):
                continue

            try:
                result = method(
                    pr_url
                )

                if hasattr(result, "__await__"):
                    result = await result

                if result is False:
                    return (
                        False,
                        f"Pull request merge failed: {name}",
                    )

                return True, ""

            except TypeError:
                try:
                    result = method(
                        pull_request=pr_url
                    )

                    if hasattr(result, "__await__"):
                        result = await result

                    if result is False:
                        return (
                            False,
                            f"Pull request merge failed: {name}",
                        )

                    return True, ""

                except Exception as exc:
                    return (
                        False,
                        f"Pull request merge failed: {exc}",
                    )

            except Exception as exc:
                return (
                    False,
                    f"Pull request merge failed: {exc}",
                )

        return (
            False,
            "GitHub service has no supported merge method.",
        )

    @staticmethod
    def _authorized(
        authorization: GitAuthorization | None,
    ) -> bool:
        if authorization is None:
            return False

        return (
            authorization.granted
            and authorization.authority == "user"
        )

    @staticmethod
    def _normalize_commit_result(
        result: Any,
        method_name: str,
    ) -> tuple[bool, str, str | None]:
        if result is False:
            return (
                False,
                f"Git commit failed: {method_name}",
                None,
            )

        if result is True or result is None:
            return (
                True,
                "",
                None,
            )

        if isinstance(result, str):
            return (
                True,
                "",
                result,
            )

        if isinstance(result, dict):
            sha = (
                result.get("sha")
                or result.get("commit_sha")
                or result.get("hash")
            )

            return (
                True,
                "",
                str(sha) if sha else None,
            )

        sha = getattr(
            result,
            "sha",
            None,
        )

        return (
            True,
            "",
            str(sha) if sha else None,
        )

    @staticmethod
    def _extract_url(
        result: Any,
    ) -> str | None:
        if result is None:
            return None

        if isinstance(result, str):
            return result

        if isinstance(result, dict):
            for key in (
                "url",
                "html_url",
                "pull_request_url",
            ):
                value = result.get(key)

                if value:
                    return str(value)

        for key in (
            "url",
            "html_url",
            "pull_request_url",
        ):
            value = getattr(
                result,
                key,
                None,
            )

            if value:
                return str(value)

        return None

    @staticmethod
    def _normalize_branch(
        branch: str,
    ) -> str:
        branch = branch.strip()

        branch = re.sub(
            r"[^A-Za-z0-9._/-]+",
            "-",
            branch,
        )

        branch = re.sub(
            r"/+",
            "/",
            branch,
        )

        return branch.strip("/") or "aria/engineering-change"

    @staticmethod
    def _normalize_commit_message(
        message: str,
    ) -> str:
        message = " ".join(
            message.strip().split()
        )

        return (
            message[:200]
            if message
            else "chore(aria): autonomous engineering change"
        )

    @staticmethod
    def _risk(
        request: GitLifecycleRequest,
        operations: list[GitOperation],
    ) -> GitRisk:
        if request.merge_pr:
            return GitRisk.CRITICAL

        if request.create_pr or GitOperation.PUSH in operations:
            return GitRisk.HIGH

        if len(request.changed_paths) > 20:
            return GitRisk.HIGH

        if len(request.changed_paths) > 5:
            return GitRisk.MEDIUM

        return GitRisk.LOW

    @staticmethod
    def _build_pr_body(
        request: GitLifecycleRequest,
    ) -> str:
        paths = "\n".join(
            f"- `{path}`"
            for path in request.changed_paths
        )

        return (
            "## ARIA Autonomous Engineering Change\n\n"
            f"### Requirement\n"
            f"{request.requirement}\n\n"
            "### Changed paths\n"
            f"{paths or '- None recorded'}\n\n"
            "### Safety\n"
            "- Implemented in an isolated engineering workflow.\n"
            "- Verification and acceptance are required before merge.\n"
            "- Merge remains explicitly authorized.\n"
        )

    @staticmethod
    def _failed(
        plan: GitLifecyclePlan,
        error: str,
        *,
        operation: GitOperation = GitOperation.COMMIT,
        commit_sha: str | None = None,
    ) -> GitLifecycleResult:
        return GitLifecycleResult(
            status=GitLifecycleStatus.FAILED,
            operation=operation,
            branch_name=plan.branch_name,
            commit_sha=commit_sha,
            remote=plan.remote,
            rollback_available=True,
            errors=(error,),
        )