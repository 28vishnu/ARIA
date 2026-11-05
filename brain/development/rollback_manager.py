from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .git_manager import GitManager, GitResult


def _utc_now() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


@dataclass(frozen=True)
class KnownGoodVersion:
    version: str
    commit_hash: str
    recorded_at: str
    environment: str

    def to_dict(self) -> dict[str, str]:
        return {
            "version": self.version,
            "commit_hash": self.commit_hash,
            "recorded_at": self.recorded_at,
            "environment": self.environment,
        }


@dataclass(frozen=True)
class RollbackResult:
    success: bool
    target: KnownGoodVersion | None
    git_result: GitResult | None
    message: str
    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "target": (
                self.target.to_dict()
                if self.target
                else None
            ),
            "git_result": (
                self.git_result.to_dict()
                if self.git_result
                else None
            ),
            "message": self.message,
            "metadata": dict(
                self.metadata
            ),
        }


class RollbackManager:
    """
    Maintains the last-known-good Git version.

    This manager prepares the repository for rollback.

    Actual production deployment after rollback remains the
    responsibility of DeploymentManager.

    Rollback is deliberately disabled unless explicitly
    authorized by the caller.
    """

    def __init__(
        self,
        git_manager: GitManager,
    ) -> None:

        self.git = git_manager
        self._known_good: dict[
            str,
            KnownGoodVersion,
        ] = {}

    async def record_known_good(
        self,
        *,
        version: str,
        environment: str = "production",
    ) -> KnownGoodVersion:

        commit_hash = (
            await self.git.head_commit()
        )

        if not commit_hash:
            raise RuntimeError(
                "Cannot record known-good version "
                "without a Git commit."
            )

        target = KnownGoodVersion(
            version=version,
            commit_hash=commit_hash,
            recorded_at=_utc_now(),
            environment=environment,
        )

        self._known_good[
            environment
        ] = target

        return target

    def get_known_good(
        self,
        environment: str = "production",
    ) -> KnownGoodVersion | None:

        return self._known_good.get(
            environment
        )

    def list_known_good(
        self,
    ) -> list[KnownGoodVersion]:

        return list(
            self._known_good.values()
        )

    async def prepare_rollback(
        self,
        *,
        environment: str = "production",
        explicit_authorization: bool = False,
    ) -> RollbackResult:

        if not explicit_authorization:

            return RollbackResult(
                success=False,
                target=self.get_known_good(
                    environment
                ),
                git_result=None,
                message=(
                    "Rollback authorization "
                    "is required."
                ),
            )

        target = self.get_known_good(
            environment
        )

        if not target:

            return RollbackResult(
                success=False,
                target=None,
                git_result=None,
                message=(
                    "No known-good version is "
                    "recorded for this environment."
                ),
            )

        result = await self.git.reset_hard(
            target.commit_hash
        )

        return RollbackResult(
            success=result.ok,
            target=target,
            git_result=result,
            message=(
                "Repository restored to the "
                "known-good commit."
                if result.ok
                else "Rollback preparation failed."
            ),
        )

    async def clear_known_good(
        self,
        environment: str = "production",
    ) -> None:

        self._known_good.pop(
            environment,
            None,
        )